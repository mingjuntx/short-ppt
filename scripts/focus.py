"""Validate pointer-focus events and build a frame-rate-preserving zoom filter."""
import argparse
import json
import math
from pathlib import Path


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field} 必须是有限数字。')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{field} 必须是有限数字。')
    return value


def validate_focus(data, duration=None):
    """Normalize an event list; retain detection evidence without executing it."""
    if duration is not None:
        duration = _number(duration, 'duration')
        if duration <= 0:
            raise ValueError('duration 必须大于零。')
    if isinstance(data, dict):
        if data.get('version', 1) != 1:
            raise ValueError('只支持 version=1 的放大事件。')
        data = data.get('events')
    if not isinstance(data, list):
        raise ValueError('放大计划必须是 events 列表。')
    result = []
    for index, raw in enumerate(data, 1):
        if not isinstance(raw, dict):
            raise ValueError(f'第 {index} 个放大事件必须是对象。')
        event = dict(raw)
        start = _number(event.get('start'), f'事件 {index} start')
        end = _number(event.get('end'), f'事件 {index} end')
        if start < 0 or end <= start:
            raise ValueError(f'事件 {index} 需满足 0 <= start < end。')
        if duration is not None and end > duration:
            if end - duration > .1 + 1e-9:
                raise ValueError(f'事件 {index} 超出视频时长 {duration:g} 秒。')
            end = duration
        if end <= start:
            raise ValueError(f'事件 {index} 在视频时长内没有有效区间。')
        x = _number(event.get('x'), f'事件 {index} x')
        y = _number(event.get('y'), f'事件 {index} y')
        zoom = _number(event.get('zoom'), f'事件 {index} zoom')
        ramp = _number(event.get('ramp', .45), f'事件 {index} ramp')
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f'事件 {index} 的 x/y 必须是 0–1 的归一化坐标。')
        if not 1 <= zoom <= 1.8:
            raise ValueError(f'事件 {index} 的 zoom 必须在 1.0–1.8 之间。')
        if ramp <= 0:
            raise ValueError(f'事件 {index} 的 ramp 必须大于零。')
        event.update(start=start, end=end, x=x, y=y, zoom=zoom,
                     ramp=min(ramp, (end-start)/2))
        result.append(event)
    result.sort(key=lambda event: event['start'])
    for previous, event in zip(result, result[1:]):
        if previous['end'] > event['start']:
            raise ValueError('放大事件时间重叠，请合并或调整事件。')
    return result


def load_focus(path, duration=None):
    return validate_focus(json.loads(Path(path).read_text(encoding='utf-8-sig')), duration)


def _weight(event, t):
    u = max(0., min(1., (t-event['start'])/event['ramp'],
                    (event['end']-t)/event['ramp']))
    return u*u*(3-2*u)


def focus_state(events, t):
    """Return smooth zoom and crop center; start/end return the original view."""
    for event in events:
        if event['start'] <= t <= event['end']:
            weight = _weight(event, t)
            zoom = 1 + (event['zoom']-1)*weight
            x = .5 + (event['x']-.5)*weight
            y = .5 + (event['y']-.5)*weight
            # Keep the crop fully inside the original image.
            half = .5/zoom
            return {'zoom': zoom, 'x': min(1-half, max(half, x)),
                    'y': min(1-half, max(half, y))}
    return {'zoom': 1., 'x': .5, 'y': .5}


def _fmt(value):
    return format(value, '.9g')


def _envelope(event, clock='t'):
    start, end, ramp = (_fmt(event[key]) for key in ('start', 'end', 'ramp'))
    u = f'max(0,min(1,min(({clock}-{start})/{ramp},({end}-{clock})/{ramp})))'
    return f'({u}*{u}*(3-2*{u}))'


def ffmpeg_focus_filter(events, width, height, fps=30):
    """Resample a fixed-size source rectangle using a smooth perspective warp.

    Apply this after source aspect normalization and before header/subtitle
    overlays. FFmpeg's perspective expressions have frame counters, not PTS;
    the caller must provide CFR frames at *fps*, or prepend ``fps=<fps>`` for
    variable-frame-rate input. This filter itself does not create/drop frames
    or replace PTS. Audio should remain outside the video-only filter graph.
    *fps* may be a positive number or rational string, such as '30000/1001'.
    """
    if isinstance(width, bool) or isinstance(height, bool) or int(width) != width or int(height) != height:
        raise ValueError('输出宽高必须是正偶数。')
    width, height = int(width), int(height)
    if min(width, height) < 2 or width % 2 or height % 2:
        raise ValueError('输出宽高必须是正偶数。')
    events = validate_focus(events)
    if not events:
        return 'null'
    from fractions import Fraction
    try:
        rate = float(Fraction(str(fps)))
    except (ValueError, ZeroDivisionError):
        raise ValueError('fps 必须是正数或有效的帧率分数。') from None
    if isinstance(fps, bool) or not math.isfinite(rate) or rate <= 0:
        raise ValueError('fps 必须是正数或有效的帧率分数。')
    clock = f'((on-1)/{_fmt(rate)})'
    zoom_terms, x_terms, y_terms = [], [], []
    for event in events:
        envelope = _envelope(event, clock)
        zoom_terms.append(f'({_fmt(event["zoom"]-1)}*{envelope})')
        x_terms.append(f'({_fmt(event["x"]-.5)}*{envelope})')
        y_terms.append(f'({_fmt(event["y"]-.5)}*{envelope})')
    z = '1+' + '+'.join(zoom_terms)
    x = '.5+' + '+'.join(x_terms)
    y = '.5+' + '+'.join(y_terms)
    # Source coordinates are clamped so the sampling rectangle never exposes
    # space beyond the image. st/ld registers are local to each expression.
    left = f'st(0,{z});W*(max(.5/ld(0),min(1-.5/ld(0),{x}))-.5/ld(0))'
    right = f'st(0,{z});W*(max(.5/ld(0),min(1-.5/ld(0),{x}))+.5/ld(0))'
    top = f'st(0,{z});H*(max(.5/ld(0),min(1-.5/ld(0),{y}))-.5/ld(0))'
    bottom = f'st(0,{z});H*(max(.5/ld(0),min(1-.5/ld(0),{y}))+.5/ld(0))'
    return (f"perspective=x0='{left}':y0='{top}':x1='{right}':y1='{top}':"
            f"x2='{left}':y2='{bottom}':x3='{right}':y3='{bottom}':"
            'sense=source:eval=frame:interpolation=cubic,setsar=1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--duration', type=float)
    args = parser.parse_args()
    try:
        events = load_focus(args.plan, args.duration)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({'event_count': len(events), 'events': events}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
