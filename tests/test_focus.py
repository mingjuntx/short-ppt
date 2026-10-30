import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from focus import load_focus, validate_focus, focus_state, ffmpeg_focus_filter


def event(**overrides):
    result = dict(start=1., end=3., x=.65, y=.5, zoom=1.6, ramp=.45)
    result.update(overrides)
    return result


class FocusPlanTests(unittest.TestCase):
    def test_continuous_path_validation_and_interpolation(self):
        from focus import target_state
        points=[dict(t=1.5,x=.4,y=.4),dict(t=2.5,x=.6,y=.6)]
        e=validate_focus([event(keyframes=points)])[0]
        self.assertAlmostEqual(target_state(e,2)['x'],.5)
        self.assertEqual(target_state(e,0),points[0])
        self.assertEqual(target_state(e,4),points[-1])
        self.assertAlmostEqual(focus_state([e],2)['x'],.5)
        for bad in [[points[0]],list(reversed(points)),[points[0],dict(t=4,x=.5,y=.5)],
                    [points[0],dict(t=2,x=float('nan'),y=.5)]]:
            with self.assertRaises(ValueError):
                validate_focus([event(keyframes=bad)])

    def test_continuous_path_maps_with_aspect_crop(self):
        from render import focus_in_output_frame
        mapped=focus_in_output_frame([event(keyframes=[dict(t=1,x=.4,y=.5),dict(t=2,x=.6,y=.5)])],(400,200),(200,200))
        self.assertAlmostEqual(mapped[0]['keyframes'][0]['x'],.3)
        self.assertAlmostEqual(mapped[0]['keyframes'][1]['x'],.7)

    def test_empty_events_are_a_noop(self):
        self.assertEqual(validate_focus({'version':1,'events':[]}), [])
        self.assertEqual(ffmpeg_focus_filter([], 320,180), 'null')
        self.assertEqual(focus_state([], 2), dict(zoom=1., x=.5,y=.5))

    def test_sort_metadata_and_rounding(self):
        data=[event(start=3,end=4.05,source='cursor',confidence=.91,evidence={'frame':12}),event(start=0,end=2)]
        normalized=validate_focus(data,duration=4)
        self.assertEqual([e['start'] for e in normalized],[0,3])
        self.assertEqual(normalized[1]['end'],4)
        self.assertEqual(normalized[1]['evidence'],{'frame':12})
        self.assertEqual(normalized[1]['source'],'cursor')
        self.assertEqual(data[0]['end'],4.05)

    def test_loading_preserves_the_file(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            path=Path(temp)/'focus.json'
            contents=json.dumps({'version':1,'events':[event()]})
            path.write_text(contents,encoding='utf-8')
            self.assertEqual(len(load_focus(path,duration=4)),1)
            self.assertEqual(path.read_text(encoding='utf-8'),contents)

    def test_bad_types_ranges_and_overlaps_fail(self):
        invalid=[event(start=-1),event(end=1),event(x=-.01),event(y=1.1),
                 event(zoom=.9),event(zoom=1.81),event(ramp=0),
                 event(start=float('nan')),event(end=float('inf')),event(x=True)]
        for item in invalid:
            with self.subTest(item=item),self.assertRaises(ValueError):
                validate_focus([item],duration=4)
        with self.assertRaises(ValueError):
            validate_focus([event(),event(start=2,end=4)])
        with self.assertRaises(ValueError):
            validate_focus([event(end=4.2)],duration=4)

    def test_start_end_and_midpoint(self):
        events=validate_focus([event()])
        for t in [-1,1,3,5]:
            self.assertEqual(focus_state(events,t)['zoom'],1)
        middle=focus_state(events,2)
        self.assertAlmostEqual(middle['zoom'],1.6)
        self.assertAlmostEqual(middle['x'],.65)
        samples=[focus_state(events,t)['zoom'] for t in [1,1.1,1.2,1.3,1.45]]
        self.assertEqual(samples,sorted(samples))
        self.assertLess(abs(focus_state(events,1.0001)['zoom']-1),1e-6)

    def test_centers_are_clamped_at_edges(self):
        for x,y in [(0,0),(1,1),(0,1),(1,0)]:
            state=focus_state(validate_focus([event(x=x,y=y)]),2)
            half=.5/state['zoom']
            self.assertGreaterEqual(state['x'],half)
            self.assertLessEqual(state['x'],1-half)
            self.assertGreaterEqual(state['y'],half)
            self.assertLessEqual(state['y'],1-half)

    def test_ramp_cannot_exceed_half_event(self):
        events=validate_focus([event(start=0,end=.5,ramp=5)])
        self.assertEqual(events[0]['ramp'],.25)
        self.assertAlmostEqual(focus_state(events,.25)['zoom'],1.6)

    def test_filter_accepts_rational_fps_and_rejects_invalid(self):
        self.assertIn('perspective=',ffmpeg_focus_filter([event()],320,180,'30000/1001'))
        for rate in [0,-1,True,'invalid','1/0',float('nan')]:
            with self.subTest(rate=rate),self.assertRaises(ValueError):
                ffmpeg_focus_filter([event()],320,180,rate)


class FFmpegFocusTests(unittest.TestCase):
    def test_renderer_keeps_tail_frame_and_reads_video_fps(self):
        try:
            import imageio_ffmpeg
            from configure_fonts import common_font_directories
        except ImportError:
            self.skipTest('Install base video dependencies to run the render smoke test')
        font = None
        for directory in common_font_directories():
            for name in ['arial.ttf','DejaVuSans.ttf','LiberationSans-Regular.ttf','NotoSerifSC-VF.ttf']:
                candidates=list(directory.rglob(name))
                if candidates:
                    font=candidates[0]
                    break
            if font:
                break
        if not font:
            self.skipTest('No local TrueType font is available for the renderer cover')
        ff=imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            temp=Path(temp)
            # The filename intentionally disagrees with the real frame rate.
            source=temp/'sample 60 fps.mp4'
            made=subprocess.run([ff,'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=0x6e8796:s=320x180:r=30',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','4','-c:v','libx264',
                '-pix_fmt','yuv420p','-c:a','aac',str(source)],capture_output=True)
            self.assertEqual(made.returncode,0,made.stderr.decode('utf-8',errors='replace'))
            plan=temp/'focus.json'
            plan.write_text(json.dumps({'version':1,'events':[event()]}),encoding='utf-8')
            out=temp/'rendered'
            rendered=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/render.py'),
                '--input',str(source),'--output-dir',str(out),'--title','Focus',
                '--font',str(font),'--focus',str(plan)],capture_output=True)
            self.assertEqual(rendered.returncode,0,rendered.stderr.decode('utf-8',errors='replace')[-3000:])
            decoded=subprocess.run([ff,'-hide_banner','-i',str(out/'video.mp4'),'-f','null','-'],capture_output=True)
            self.assertEqual(decoded.returncode,0)
            info=decoded.stderr.decode('utf-8',errors='replace')
            self.assertIn('320x180',info)
            self.assertIn('Audio:',info)
            self.assertRegex(info,r'frame=\s*120\b')
            self.assertRegex(info,r'Duration: 00:00:04\.')
            exported=json.loads((out/'focus.json').read_text(encoding='utf-8'))
            self.assertEqual(exported['normalized_fps'],30)

    def test_real_video_keeps_size_frame_count_audio_and_focus(self):
        try:
            import imageio_ffmpeg
            from PIL import Image,ImageDraw
        except ImportError:
            self.skipTest('Install base video dependencies to run the FFmpeg smoke test')
        ff=imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            temp=Path(temp)
            base=Image.new('RGB',(320,180),(30,50,100))
            ImageDraw.Draw(base).rectangle((202,84,214,96),fill='white')
            base.save(temp/'base.png')
            def run(args):
                result=subprocess.run([ff,'-hide_banner','-loglevel','error']+args,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr.decode('utf-8',errors='replace')[-3000:])
                return result
            run(['-loop','1','-framerate','30','-i',str(temp/'base.png'),'-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                 '-t','4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(temp/'in.mp4')])
            events=validate_focus([event(start=0,end=.8,x=0,y=0,zoom=1.8,ramp=.2),
                event(keyframes=[dict(t=1.5,x=.65,y=.5),dict(t=2,x=.65,y=.5),dict(t=2.5,x=.6,y=.5)])])
            run(['-i',str(temp/'in.mp4'),'-vf',ffmpeg_focus_filter(events,320,180),
                 '-c:v','libx264','-pix_fmt','yuv420p','-c:a','copy',str(temp/'out.mp4')])
            result=subprocess.run([ff,'-hide_banner','-i',str(temp/'out.mp4'),'-f','null','-'],capture_output=True)
            self.assertEqual(result.returncode,0)
            info=result.stderr.decode('utf-8',errors='replace')
            self.assertIn('320x180',info)
            self.assertIn('Audio:',info)
            self.assertRegex(info,r'Duration: 00:00:04\.')
            self.assertRegex(info,r'frame=\s*120\b')
            run(['-ss','0.4','-i',str(temp/'out.mp4'),'-frames:v','1',str(temp/'edge.png')])
            edge=Image.open(temp/'edge.png').convert('RGB')
            for point in [(1,1),(318,1),(1,178),(318,178)]:
                self.assertGreater(min(edge.getpixel(point)),18)
            run(['-ss','2','-i',str(temp/'out.mp4'),'-frames:v','1',str(temp/'middle.png')])
            middle=Image.open(temp/'middle.png').convert('RGB')
            self.assertEqual(middle.size,(320,180))
            self.assertGreater(min(middle.getpixel((160,90))),220)
            run(['-ss','2.5','-i',str(temp/'out.mp4'),'-frames:v','1',str(temp/'moving.png')])
            moving=Image.open(temp/'moving.png').convert('RGB')
            self.assertGreater(min(moving.getpixel((186,90))),220)
            # Outside the event the same source marker returns to x=208.
            run(['-ss','3.5','-i',str(temp/'out.mp4'),'-frames:v','1',str(temp/'after.png')])
            after=Image.open(temp/'after.png').convert('RGB')
            self.assertGreater(min(after.getpixel((208,90))),220)
            self.assertLess(max(after.getpixel((160,90))),180)


if __name__=='__main__':
    unittest.main()
