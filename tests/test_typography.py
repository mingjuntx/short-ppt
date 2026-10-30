import sys
import tempfile
import unittest
from pathlib import Path
import jieba

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render import caption_lines


class MonospaceMeasure:
    def getlength(self, text):
        return len(text)


class CaptionLineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.tokenizer = jieba.Tokenizer()
        self.tokenizer.tmp_dir = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def test_reflow_repairs_asr_break_inside_video(self):
        text = '一段日常短视\n频也可以展示一个精美的小工具。'
        lines = caption_lines(text, MonospaceMeasure(), 16, self.tokenizer)
        self.assertEqual(''.join(lines), text.replace('\n', ''))
        self.assertLessEqual(len(lines), 2)
        self.assertTrue(all(len(line) <= 16 for line in lines))
        self.assertFalse(lines[0].endswith('视') and lines[1].startswith('频'))

    def test_short_caption_stays_on_one_line(self):
        self.assertEqual(caption_lines('中文自动字幕。', MonospaceMeasure(), 16, self.tokenizer), ['中文自动字幕。'])

    def test_empty_text_fails(self):
        with self.assertRaises(ValueError):
            caption_lines(' \n ', MonospaceMeasure(), 16, self.tokenizer)


if __name__ == '__main__':
    unittest.main()
