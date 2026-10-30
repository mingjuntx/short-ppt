"""Conservatively detect stable index-finger or cursor pointing in local video.

This is a candidate detector, not a semantic understanding model. It deliberately
returns no events when the evidence is weak. It never downloads a model or uploads
frames. Confidence is a heuristic quality score, not a calibrated probability.
"""
import argparse
from collections import defaultdict, deque
import json
import math
from pathlib import Path
import statistics


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def joint_angle(a, b, c):
    u = [a[i] - b[i] for i in range(len(a))]
    v = [c[i] - b[i] for i in range(len(a))]
    den = math.sqrt(sum(x*x for x in u) * sum(x*x for x in v))
    if den < 1e-12:
        return 0.0
    cosine = max(-1.0, min(1.0, sum(x*y for x, y in zip(u, v)) / den))
    return math.degrees(math.acos(cosine))


def pointing_hand(landmarks, width, height):
    """Accept a visible, straight index finger with at least two folded fingers."""
    if len(landmarks) != 21:
        return None
    pts = [(float(p.x), float(p.y)) for p in landmarks]
    if not all(math.isfinite(v) and -.05 <= v <= 1.05 for p in pts for v in p):
        return None
    scale = max(width, height)
    metric = [(x*width/scale, y*height/scale) for x, y in pts]
    if distance(metric[5], metric[17]) < .025:
        return None  # too small to judge the hand shape
    a = joint_angle(metric[5], metric[6], metric[7])
    b = joint_angle(metric[6], metric[7], metric[8])
    if a < 155 or b < 155:
        return None
    if distance(metric[8], metric[0]) < 1.12 * distance(metric[6], metric[0]):
        return None
    if distance(metric[8], metric[5]) < .035:
        return None  # pointing toward the camera is not an observable screen target
    folded = 0
    for mcp, pip, dip, tip in [(9,10,11,12), (13,14,15,16), (17,18,19,20)]:
        angle = joint_angle(metric[mcp], metric[pip], metric[dip])
        if angle < 145 or distance(metric[tip], metric[0]) < 1.04 * distance(metric[pip], metric[0]):
            folded += 1
    if folded < 2:
        return None  # open hand, V sign, or casual waving
    tip, pip = pts[8], pts[6]
    if not (0 <= tip[0] <= 1 and 0 <= tip[1] <= 1):
        return None
    x = max(.01, min(.99, tip[0] + .18 * (tip[0] - pip[0])))
    y = max(.01, min(.99, tip[1] + .18 * (tip[1] - pip[1])))
    quality = min(.97, .75 + .13 * min(a, b) / 180 + .03 * (folded-2))
    return dict(x=x, y=y, confidence=quality, source='index-finger',
                evidence=dict(tip=list(tip), index_angles=[round(a,1),round(b,1)],
                              folded_fingers=folded,
                              hand_bbox=[min(p[0] for p in pts), min(p[1] for p in pts),
                                         max(p[0] for p in pts), max(p[1] for p in pts)]))


class HandDetector:
    def __init__(self, model, minimum):
        self.task = None
        if model is None:
            return
        import mediapipe as mp
        self.mp = mp
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=2, min_hand_detection_confidence=minimum,
            min_hand_presence_confidence=minimum, min_tracking_confidence=minimum)
        self.task = mp.tasks.vision.HandLandmarker.create_from_options(options)

    def detect(self, rgb, timestamp_ms):
        if self.task is None:
            return []
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        result = self.task.detect_for_video(image, timestamp_ms)
        h, w = rgb.shape[:2]
        found = []
        for landmarks in result.hand_landmarks:
            candidate = pointing_hand(landmarks, w, h)
            if candidate:
                found.append(candidate)
        return found

    def close(self):
        if self.task is not None:
            self.task.close()


class CursorDetector:
    """Arrow component matching with black/white boundary and uniqueness checks.

    Text and static UI arrows can resemble cursors. The temporal stage therefore
    additionally requires motion relative to the background, then a clear dwell.
    """
    def __init__(self, cv, np):
        self.cv, self.np = cv, np
        mask = np.zeros((90, 70), np.uint8)
        polygon = np.array([(7,5),(7,62),(23,47),(37,80),(49,74),(35,43),(62,43)], np.int32)
        cv.fillPoly(mask, [polygon], 255)
        self.shapes = []
        for angle in [-25,-12,0,12,25]:
            matrix = cv.getRotationMatrix2D((35,45), angle, 1)
            rotated = cv.warpAffine(mask, matrix, (70,90), flags=cv.INTER_NEAREST)
            # Thresholding sees the arrow's interior, not its opposite-colour
            # outline. Match plausible outline thicknesses at the same strict
            # IoU threshold rather than weakening the acceptance threshold.
            for erosion in [0,3,5,7]:
                interior = (cv.erode(rotated,np.ones((erosion,erosion),np.uint8))
                            if erosion else rotated)
                x,y,w,h = cv.boundingRect(interior)
                if w and h:
                    self.shapes.append(cv.resize(interior[y:y+h,x:x+w], (32,48), interpolation=cv.INTER_NEAREST) > 0)

    def detect(self, gray):
        cv, np = self.cv, self.np
        h, w = gray.shape
        candidates = []
        # Connected components are much cheaper than densely matching dozens of
        # templates across every screen pixel, and reject large bright panels.
        for white in [True, False]:
            binary = ((gray >= 190) if white else (gray <= 65)).astype(np.uint8)
            count, labels, stats, _ = cv.connectedComponentsWithStats(binary, 8)
            for label in range(1, count):
                x,y,cw,ch,area = [int(v) for v in stats[label]]
                if not (5 <= cw <= 48 and 10 <= ch <= 68 and .30 <= cw/ch <= 1.12):
                    continue
                if not (.20 <= area/(cw*ch) <= .70):
                    continue
                component = (labels[y:y+ch,x:x+cw] == label).astype(np.uint8)
                normalized = cv.resize(component, (32,48), interpolation=cv.INTER_NEAREST) > 0
                overlaps = []
                for template in self.shapes:
                    union = np.count_nonzero(template | normalized)
                    overlaps.append(np.count_nonzero(template & normalized) / max(1,union))
                overlap = max(overlaps)
                if overlap < .71:
                    continue
                pad = 3
                if x < pad or y < pad or x+cw+pad > w or y+ch+pad > h:
                    continue
                region = gray[y-pad:y+ch+pad,x-pad:x+cw+pad]
                inside = np.pad(component, pad).astype(bool)
                ring = cv.dilate(inside.astype(np.uint8), np.ones((3,3),np.uint8)).astype(bool) & ~inside
                if not np.any(ring):
                    continue
                contrast = float(region[inside].mean() - region[ring].mean())
                if not white:
                    contrast = -contrast
                if contrast < 70:
                    continue
                score = .65*overlap + .35*min(1.,contrast/160)
                # The actual arrow tip is the high-left corner in the accepted
                # small-rotation range, rather than its bounding-box centre.
                tip_x = x + cw*.10
                tip_y = y + ch*.03
                candidates.append(dict(x=tip_x/w, y=tip_y/h, confidence=score,
                    source='cursor', evidence=dict(bbox=[x/w,y/h,(x+cw)/w,(y+ch)/h],
                                                  shape_iou=round(overlap,3), border_contrast=round(contrast,1))))
        candidates.sort(key=lambda c:c['confidence'], reverse=True)
        if len(candidates) > 1:
            best = candidates[0]
            rival = next((c for c in candidates[1:] if distance((c['x'],c['y']), (best['x'],best['y'])) > .025), None)
            if rival and best['confidence'] - rival['confidence'] < .055:
                return []  # several similar symbols: identity is uncertain
        return candidates[:1]


def background_motion(previous, current, cv, np):
    """Median sparse optical flow in normalized image coordinates, or None."""
    if previous is None:
        return None
    h,w = current.shape
    factor = min(1., 320/max(h,w))
    size = (max(1,round(w*factor)), max(1,round(h*factor)))
    a = cv.resize(previous, size)
    b = cv.resize(current, size)
    points = cv.goodFeaturesToTrack(a, maxCorners=120, qualityLevel=.025, minDistance=8)
    if points is None or len(points) < 12:
        return None
    moved, status, error = cv.calcOpticalFlowPyrLK(a,b,points,None,winSize=(21,21),maxLevel=3)
    if moved is None:
        return None
    valid = status.ravel().astype(bool) & (error.ravel() < 22)
    flow = (moved-points).reshape(-1,2)[valid]
    if len(flow) < 12:
        return None
    median = np.median(flow, axis=0)
    residual = np.linalg.norm(flow-median, axis=1)
    inliers = flow[residual < max(2.5, .012*max(size))]
    if len(inliers) < 12:
        return None
    dx,dy = np.median(inliers, axis=0)
    return float(dx/size[0]),float(dy/size[1])


class DwellPlanner:
    def __init__(self, sample_fps=3., minimum=.75, cooldown=6.):
        self.fps, self.minimum, self.cooldown = sample_fps, minimum, cooldown
        self.history = defaultdict(deque)
        self.events = []
        self.last_target = None
        self.last_seen = {}
        self.last_frame = {}

    def observe(self, timestamp, frame_index, candidates, motion=None, duration=None):
        # A dwell is a sequence of distinct video samples, not a count of hands
        # found inside one sample. Reject ambiguous simultaneous pointing and
        # keep at most one candidate per source in a frame.
        grouped = defaultdict(list)
        for candidate in candidates:
            if candidate['confidence'] >= self.minimum:
                grouped[candidate['source']].append(candidate)
        selected = []
        for source, group in grouped.items():
            group.sort(key=lambda c:c['confidence'], reverse=True)
            best = group[0]
            ambiguous = any(
                distance((best['x'],best['y']),(other['x'],other['y'])) > .07
                and best['confidence']-other['confidence'] < .055
                for other in group[1:])
            if not ambiguous:
                selected.append(best)
        present = {c['source'] for c in selected}
        for source in list(self.history):
            if source not in present and timestamp-self.last_seen.get(source,-100) > 1.5/self.fps:
                self.history[source].clear()
                if self.last_target and self.last_target[0] == source:
                    self.last_target = None
        # Prefer the explicit pointing hand over a coincidental arrow-like UI.
        selected.sort(key=lambda c:(c['source']!='index-finger',-c['confidence']))
        for candidate in selected:
            source = candidate['source']
            if self.last_frame.get(source) == frame_index:
                continue
            self.last_frame[source] = frame_index
            history = self.history[source]
            if history and timestamp-history[-1]['t'] > 1.5/self.fps:
                history.clear()
            item = dict(candidate,t=timestamp,frame=frame_index,relative_move=None)
            if history and motion is not None:
                previous = history[-1]
                item['relative_move'] = distance((candidate['x']-previous['x'],candidate['y']-previous['y']),motion)
            history.append(item)
            self.last_seen[source] = timestamp
            while history and timestamp-history[0]['t'] > 3:
                history.popleft()
            needed = max(3,math.ceil(.6*self.fps)+1)
            if len(history) < needed:
                continue
            dwell = list(history)[-needed:]
            if dwell[-1]['t']-dwell[0]['t'] < .6-1e-6:
                continue
            x = statistics.median(c['x'] for c in dwell)
            y = statistics.median(c['y'] for c in dwell)
            if max(distance((c['x'],c['y']),(x,y)) for c in dwell) > .022:
                continue
            if self.events and timestamp-self.events[-1]['start'] < self.cooldown:
                continue
            if self.last_target and self.last_target[0] == source and distance(self.last_target[1],(x,y)) < .07:
                continue
            if source == 'cursor':
                approach = [c for c in history if c['t'] < dwell[0]['t']]
                movement = [c['relative_move'] for c in approach if c['relative_move'] is not None]
                stable_movement = [c['relative_move'] for c in dwell if c['relative_move'] is not None]
                if not movement or max(movement) < .006 or sum(movement) < .012:
                    continue  # stationary UI icon, or cursor appeared without an observed approach
                if len(stable_movement) < 2 or statistics.mean(stable_movement) > .008:
                    continue
            start = max(0.,dwell[0]['t']-.12)
            end = timestamp+2.0
            if duration is not None:
                end = min(end,duration)
            if end-start < 1.2:
                continue
            quality = min(c['confidence'] for c in dwell)
            evidence = dict(candidate['evidence'], sampled_frames=[c['frame'] for c in dwell],
                            sample_times=[round(c['t'],4) for c in dwell],
                            stable_radius=.022, confidence_kind='heuristic-quality')
            event = dict(start=round(start,4),end=round(end,4),x=round(x,6),y=round(y,6),
                         zoom=1.35,ramp=.45,source=source,confidence=round(quality,4),evidence=evidence)
            self.events.append(event)
            self.last_target = source,(x,y)
            return event
        return None


def configured_hand_model(explicit):
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if not path.is_file():
            raise ValueError('指定的手部模型文件不存在：'+str(path))
        return path
    config = Path(__file__).resolve().parents[1]/'vision.local.json'
    if config.is_file():
        data = json.loads(config.read_text(encoding='utf-8'))
        if data.get('hand_model'):
            path = Path(data['hand_model']).expanduser()
            if not path.is_absolute():
                path = config.parent/path
            if not path.is_file():
                raise ValueError('vision.local.json 中的手部模型文件不存在。')
            return path
    return None


def analyze(input_path, output_path, hand_model=None, sample_fps=3., minimum=.75, force=False):
    import cv2 as cv
    import numpy as np
    source = Path(input_path).expanduser().absolute()
    output = Path(output_path).expanduser().absolute()
    if not source.is_file():
        raise ValueError('输入视频不存在。')
    if output.exists() and not force:
        raise ValueError('检测结果已存在；换一个输出路径或显式使用 --force。')
    if not math.isfinite(sample_fps) or not .5 <= sample_fps <= 15:
        raise ValueError('sample-fps 必须在 0.5–15 之间。')
    if not math.isfinite(minimum) or not .5 <= minimum <= 1:
        raise ValueError('min-confidence 必须在 0.5–1 之间。')
    model = configured_hand_model(hand_model)
    hand = HandDetector(model,minimum)
    cap = cv.VideoCapture(str(source))
    if hasattr(cv,'CAP_PROP_ORIENTATION_AUTO'):
        cap.set(cv.CAP_PROP_ORIENTATION_AUTO,1)
    if not cap.isOpened():
        hand.close()
        raise ValueError('OpenCV 无法打开视频。')
    fps = float(cap.get(cv.CAP_PROP_FPS))
    count = float(cap.get(cv.CAP_PROP_FRAME_COUNT))
    if not math.isfinite(fps) or fps <= 0 or not math.isfinite(count) or count <= 0:
        cap.release(); hand.close()
        raise ValueError('无法读取视频帧率或总帧数，未猜测检测时间轴。')
    duration = count/fps
    cursor = CursorDetector(cv,np)
    planner = DwellPlanner(sample_fps,minimum)
    stats = dict(sampled_frames=0,index_finger_candidates=0,cursor_candidates=0,background_motion_frames=0)
    next_sample = 0.
    previous_gray = None
    previous_time = -1.
    frame_index = 0
    source_size = None
    try:
        while True:
            ok,frame = cap.read()
            if not ok:
                break
            timestamp = float(cap.get(cv.CAP_PROP_POS_MSEC))/1000
            if not math.isfinite(timestamp) or timestamp <= previous_time:
                timestamp = frame_index/fps
            frame_index += 1
            previous_time = timestamp
            if timestamp+1e-6 < next_sample:
                continue
            next_sample = timestamp + 1/sample_fps
            h,w = frame.shape[:2]
            source_size = [w,h]
            if max(h,w) > 1280:
                factor = 1280/max(h,w)
                frame = cv.resize(frame,(round(w*factor),round(h*factor)))
            gray = cv.cvtColor(frame,cv.COLOR_BGR2GRAY)
            motion = background_motion(previous_gray,gray,cv,np)
            previous_gray = gray
            if motion is not None:
                stats['background_motion_frames'] += 1
            rgb = cv.cvtColor(frame,cv.COLOR_BGR2RGB)
            hands = hand.detect(np.ascontiguousarray(rgb),round(timestamp*1000))
            cursors = cursor.detect(gray)
            stats['sampled_frames'] += 1
            stats['index_finger_candidates'] += len(hands)
            stats['cursor_candidates'] += len(cursors)
            planner.observe(timestamp,frame_index-1,hands+cursors,motion,duration)
    finally:
        cap.release(); hand.close()
    if not stats['sampled_frames']:
        raise ValueError('视频没有解码出可分析画面。')
    analysis = dict(stats,source_size=source_size,duration=round(duration,6),sample_fps=sample_fps,
                    min_confidence=minimum,hand_enabled=model is not None,
                    cursor_method='arrow-shape + black/white boundary + background-relative motion + dwell',
                    hand_method='single extended index + folded fingers + stable dwell',
                    confidence_kind='heuristic-quality, not calibrated probability',
                    cooldown_seconds=6,
                    reason='reliable-pointing-events' if planner.events else 'no-reliable-stable-pointing; no zoom was invented')
    if model is None:
        analysis['hand_note']='No local hand model configured; only cursor candidates were analyzed.'
    result=dict(version=1,events=planner.events,analysis=analysis)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--hand-model')
    parser.add_argument('--sample-fps',type=float,default=3.)
    parser.add_argument('--min-confidence',type=float,default=.75)
    parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    try:
        result=analyze(args.input,args.output,args.hand_model,args.sample_fps,args.min_confidence,args.force)
    except (OSError,ValueError,ImportError,RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(dict(output=str(Path(args.output).absolute()),event_count=len(result['events']),analysis=result['analysis']),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
