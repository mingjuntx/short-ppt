import math
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
import importlib.util

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from detect_focus import DwellPlanner, joint_angle, pointing_hand


def candidate(x=.4,y=.5,source='cursor',confidence=.92):
    return dict(x=x,y=y,source=source,confidence=confidence,evidence={'fixture':'synthetic'})


class StablePointingTests(unittest.TestCase):
    def test_stationary_cursor_icon_does_not_create_zoom(self):
        p=DwellPlanner()
        for i in range(18):
            p.observe(i/3,i,[candidate()],motion=(0,0),duration=10)
        self.assertEqual(p.events,[])

    def test_cursor_approach_then_dwell_creates_one_zoom(self):
        p=DwellPlanner()
        xs=[.2,.24,.30,.36,.4,.4,.4,.4,.4,.4,.4,.4]
        for i,x in enumerate(xs):
            p.observe(i/3,i,[candidate(x=x)],motion=(0,0),duration=10)
        self.assertEqual(len(p.events),1)
        self.assertAlmostEqual(p.events[0]['x'],.4)
        self.assertEqual(p.events[0]['source'],'cursor')
        self.assertGreaterEqual(len(p.events[0]['evidence']['sampled_frames']),3)

    def test_background_camera_motion_alone_is_not_cursor_approach(self):
        p=DwellPlanner()
        xs=[.2,.24,.30,.36,.4,.4,.4,.4,.4]
        for i,x in enumerate(xs):
            dx=0 if i==0 else xs[i]-xs[i-1]
            p.observe(i/3,i,[candidate(x=x)],motion=(dx,0),duration=10)
        self.assertEqual(p.events,[])

    def test_brief_hand_flash_and_low_confidence_are_ignored(self):
        p=DwellPlanner()
        p.observe(0,0,[candidate(source='index-finger')],duration=10)
        p.observe(1/3,1,[candidate(source='index-finger')],duration=10)
        self.assertEqual(p.events,[])
        for i in range(2,12):
            p.observe(i/3,i,[candidate(source='index-finger',confidence=.6)],duration=10)
        self.assertEqual(p.events,[])

    def test_stable_explicit_pointing_hand_creates_one_event(self):
        p=DwellPlanner()
        for i in range(24):
            p.observe(i/3,i,[candidate(source='index-finger')],duration=9)
        self.assertEqual(len(p.events),1)
        self.assertLessEqual(p.events[0]['end'],9)

    def test_angle_handles_straight_and_degenerate_joints(self):
        self.assertAlmostEqual(joint_angle((0,0),(1,0),(2,0)),180)
        self.assertEqual(joint_angle((0,0),(0,0),(1,0)),0)

    def test_only_single_index_pointing_shape_is_accepted(self):
        points=[(.5,.9),(.48,.78),(.36,.7),(.32,.62),(.3,.57),
                (.42,.6),(.42,.45),(.42,.32),(.42,.2),
                (.52,.6),(.52,.45),(.55,.56),(.55,.66),
                (.61,.64),(.61,.51),(.64,.61),(.64,.71),
                (.7,.68),(.7,.57),(.72,.67),(.72,.76)]
        landmarks=[SimpleNamespace(x=x,y=y) for x,y in points]
        result=pointing_hand(landmarks,640,480)
        self.assertIsNotNone(result)
        self.assertLess(result['y'],.2)
        for mcp,pip,dip,tip in [(9,10,11,12),(13,14,15,16),(17,18,19,20)]:
            x=points[mcp][0]
            for index,y in [(pip,.45),(dip,.32),(tip,.2)]:
                landmarks[index]=SimpleNamespace(x=x,y=y)
        self.assertIsNone(pointing_hand(landmarks,640,480))

    def test_nearby_hand_candidates_count_as_one_distinct_sample(self):
        p=DwellPlanner()
        for i in range(12):
            p.observe(i/3,i,[candidate(x=.4,source='index-finger'),
                             candidate(x=.41,source='index-finger')],duration=10)
        self.assertEqual(len(p.events),1)
        frames=p.events[0]['evidence']['sampled_frames']
        self.assertEqual(len(frames),len(set(frames)))
        self.assertGreaterEqual(len(frames),3)

    def test_two_distant_equal_pointing_hands_are_ambiguous(self):
        p=DwellPlanner()
        for i in range(12):
            p.observe(i/3,i,[candidate(x=.2,source='index-finger'),
                             candidate(x=.8,source='index-finger')],duration=10)
        self.assertEqual(p.events,[])

    def test_repeated_calls_for_same_frame_cannot_accumulate_dwell(self):
        p=DwellPlanner()
        for i in range(12):
            p.observe(i/3,0,[candidate(source='index-finger')],duration=10)
        self.assertEqual(p.events,[])
        self.assertLessEqual(len(p.history['index-finger']),1)


@unittest.skipUnless(importlib.util.find_spec('cv2') and importlib.util.find_spec('numpy'), 'optional vision dependencies not installed')
class CursorShapeTests(unittest.TestCase):
    def test_clear_outlined_arrow_is_detected_at_its_location(self):
        import cv2 as cv
        import numpy as np
        from detect_focus import CursorDetector
        frame=np.full((240,320),205,np.uint8)
        polygon=np.array([(0,0),(0,22),(6,17),(11,29),(15,27),(10,15),(22,15)],np.int32)+[140,100]
        cv.fillPoly(frame,[polygon],255)
        cv.polylines(frame,[polygon],True,0,2)
        result=CursorDetector(cv,np).detect(frame)
        self.assertTrue(result)
        self.assertAlmostEqual(result[0]['x'],140/320,delta=.03)
        self.assertAlmostEqual(result[0]['y'],100/240,delta=.03)

    def test_plain_ui_text_is_not_a_cursor(self):
        import cv2 as cv
        import numpy as np
        from detect_focus import CursorDetector
        frame=np.full((240,640),205,np.uint8)
        cv.putText(frame,'Typical UI text abc K P 123',(30,150),cv.FONT_HERSHEY_SIMPLEX,.8,80,1)
        self.assertEqual(CursorDetector(cv,np).detect(frame),[])


if __name__=='__main__':
    unittest.main()
