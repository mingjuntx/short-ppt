import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from chapters import load_chapters


class ChapterPlanTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parent
        self.temporary = tempfile.TemporaryDirectory(dir=test_root)
        self.directory = Path(self.temporary.name).resolve()
        assert self.directory.is_relative_to(test_root)
        self.addCleanup(self.temporary.cleanup)
        self.path = self.directory / 'chapters.json'

    def write_plan(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return self.path

    def test_list_is_sorted_and_labels_follow_time_order(self):
        self.write_plan([
            {'start': 10, 'end': 20, 'title': '第二个主题'},
            {'start': 0, 'end': 8, 'title': '第一个主题'},
        ])
        result = load_chapters(self.path)
        self.assertEqual([chapter['start'] for chapter in result], [0, 10])
        self.assertEqual([chapter['label'] for chapter in result], ['01', '02'])
        self.assertTrue(all(chapter['subtitle'] == '' for chapter in result))

    def test_wrapped_plan_preserves_evidence_and_does_not_write(self):
        data = {'version': 1, 'chapters': [
            {'start': 1.2, 'end': 5.4, 'title': '关键词', 'subtitle': '主题概括',
             'label': 'A', 'evidence': {'cue_start': 2, 'cue_end': 4}},
        ]}
        self.write_plan(data)
        before = self.path.read_bytes()
        result = load_chapters(self.path, 10)
        self.assertEqual(result[0]['evidence'], {'cue_start': 2, 'cue_end': 4})
        self.assertEqual(result[0]['label'], 'A')
        self.assertEqual(result[0]['subtitle'], '主题概括')
        self.assertEqual(self.path.read_bytes(), before)

    def test_overlapping_chapters_fail(self):
        self.write_plan([
            {'start': 4, 'end': 8, 'title': '后一个'},
            {'start': 0, 'end': 5, 'title': '前一个'},
        ])
        with self.assertRaisesRegex(ValueError, '重叠'):
            load_chapters(self.path)

    def test_touching_intervals_and_gaps_are_allowed(self):
        self.write_plan([
            {'start': 0, 'end': 3, 'title': '一'},
            {'start': 3, 'end': 4, 'title': '二'},
            {'start': 6, 'end': 8, 'title': '三'},
        ])
        self.assertEqual(len(load_chapters(self.path, 8)), 3)

    def test_nonfinite_and_non_numeric_times_fail(self):
        for value in [float('nan'), float('inf'), -float('inf'), '2', True, None]:
            with self.subTest(value=value):
                self.write_plan([{'start': 0, 'end': value, 'title': '主题'}])
                with self.assertRaises(ValueError):
                    load_chapters(self.path)

    def test_negative_or_reversed_times_fail(self):
        for start, end in [(-1, 2), (2, 2), (4, 3)]:
            with self.subTest(start=start, end=end):
                self.write_plan([{'start': start, 'end': end, 'title': '主题'}])
                with self.assertRaises(ValueError):
                    load_chapters(self.path)

    def test_substantial_duration_overrun_fails(self):
        self.write_plan([{'start': 0, 'end': 10.101, 'title': '主题'}])
        with self.assertRaisesRegex(ValueError, '超出视频时长'):
            load_chapters(self.path, 10)

    def test_rounding_overflow_is_clipped_without_modifying_source(self):
        self.write_plan([{'start': 9, 'end': 10.1, 'title': '主题'}])
        before = self.path.read_bytes()
        self.assertEqual(load_chapters(self.path, 10)[0]['end'], 10)
        self.assertEqual(self.path.read_bytes(), before)

    def test_chapter_starting_after_duration_fails(self):
        self.write_plan([{'start': 10.01, 'end': 10.05, 'title': '主题'}])
        with self.assertRaises(ValueError):
            load_chapters(self.path, 10)

    def test_invalid_duration_fails(self):
        self.write_plan([{'start': 0, 'end': 1, 'title': '主题'}])
        for duration in [0, -1, float('nan'), float('inf'), True]:
            with self.subTest(duration=duration):
                with self.assertRaises(ValueError):
                    load_chapters(self.path, duration)

    def test_titles_allow_two_lines_but_reject_empty_or_more(self):
        self.write_plan([{'start': 0, 'end': 1, 'title': '第一行\\n第二行'}])
        self.assertEqual(load_chapters(self.path)[0]['title'], '第一行\n第二行')
        for title in ['', '  ', None, '一\n二\n三']:
            with self.subTest(title=title):
                self.write_plan([{'start': 0, 'end': 1, 'title': title}])
                with self.assertRaises(ValueError):
                    load_chapters(self.path)

    def test_empty_or_malformed_roots_fail(self):
        for data in [[], {}, {'chapters': []}, {'version': 2, 'chapters': []}, 'bad']:
            with self.subTest(data=data):
                self.write_plan(data)
                with self.assertRaises(ValueError):
                    load_chapters(self.path)

    def test_subtitle_and_label_reject_real_newlines(self):
        for field in ['subtitle', 'label']:
            for value in ['第一行\n第二行', '第一行\r第二行', '第一行\r\n第二行', '文字\n']:
                with self.subTest(field=field, value=value):
                    chapter = {'start': 0, 'end': 1, 'title': '主题', field: value}
                    self.write_plan([chapter])
                    with self.assertRaisesRegex(ValueError, '单行'):
                        load_chapters(self.path)


if __name__ == '__main__':
    unittest.main()
