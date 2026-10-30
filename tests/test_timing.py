import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render import gradient
from transcribe import timed_units, make_cues, srt_time


class LayoutAndTimingTests(unittest.TestCase):
    def test_cover_and_video_gradients_have_opposite_directions(self):
        top = gradient((8, 100), .16, .65, .68, 'top')
        bottom = gradient((8, 100), .41, .91, .99)
        self.assertGreater(top.getpixel((4, 0))[3], 150)
        self.assertEqual(top.getpixel((4, 99))[3], 0)
        self.assertEqual(bottom.getpixel((4, 0))[3], 0)
        self.assertGreater(bottom.getpixel((4, 99))[3], 250)

    def test_filler_merges_without_losing_text_or_timing(self):
        units = timed_units({'text': '嗯，这是测试。', 'timestamp': [[50,200],[200,400],[400,600],[600,800],[800,1000]]})
        cues = make_cues(units, 2)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]['text'], '嗯，这是测试。')
        self.assertEqual(cues[0]['start'], .05)
        self.assertEqual(cues[0]['end'], 1)

    def test_long_speech_preserves_every_character_and_bounds(self):
        text = '这是一段较长的中文测试字幕用于检查自动断句之后每屏的长度以及所有文字是否完整保留'
        units = timed_units({'text': text, 'timestamp': [[i*150,(i+1)*150] for i in range(len(text))]})
        cues = make_cues(units, len(text) * .15)
        self.assertEqual(''.join(c['text'].replace('\n','') for c in cues), text)
        self.assertTrue(all(len(c['text'].replace('\n','')) <= 28 for c in cues))
        self.assertTrue(all(c['end']-c['start'] <= 4.5 for c in cues))
        self.assertTrue(all(cues[i]['end'] <= cues[i+1]['start'] for i in range(len(cues)-1)))

    def test_bad_alignment_is_not_replaced_with_guessed_timing(self):
        with self.assertRaises(ValueError):
            timed_units({'text':'中文字幕', 'timestamp':[[0,100]]})
        self.assertEqual(make_cues([], 10), [])

    def test_srt_time_carries_to_next_minute(self):
        self.assertEqual(srt_time(59.9996), '00:01:00,000')


if __name__ == '__main__':
    unittest.main()
