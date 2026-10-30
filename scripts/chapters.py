"""Validate a timed plan of semantic chapter headings without modifying it."""
import argparse
import json
import math
from pathlib import Path


def _seconds(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field} 必须是以秒为单位的数字。')
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'{field} 必须是有限数字。')
    return number


def load_chapters(path, duration=None):
    """Return sorted, validated chapters; preserve evidence and other metadata.

    Accepted JSON roots are a list or {"version": 1, "chapters": [...] }.
    A known duration permits at most 0.1 seconds of end-time rounding overflow.
    Headings and metadata are data only; this function never writes to *path*.
    """
    if duration is not None:
        duration = _seconds(duration, 'duration')
        if duration <= 0:
            raise ValueError('duration 必须大于零。')
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if isinstance(data, dict):
        if data.get('version', 1) != 1:
            raise ValueError('只支持 version=1 的章节计划。')
        data = data.get('chapters')
    if not isinstance(data, list) or not data:
        raise ValueError('章节计划必须包含非空 chapters 列表。')

    result = []
    for source_index, entry in enumerate(data, 1):
        prefix = f'第 {source_index} 个章节'
        if not isinstance(entry, dict):
            raise ValueError(f'{prefix}必须是对象。')
        chapter = dict(entry)
        start = _seconds(chapter.get('start'), f'{prefix} start')
        end = _seconds(chapter.get('end'), f'{prefix} end')
        if start < 0 or end <= start:
            raise ValueError(f'{prefix}需满足 0 <= start < end。')
        if duration is not None and end > duration:
            if end - duration > .1 + 1e-9:
                raise ValueError(f'{prefix}结束时间 {end:g} 超出视频时长 {duration:g} 秒。')
            end = duration
        if duration is not None and start >= duration:
            raise ValueError(f'{prefix}开始时间必须小于视频时长。')
        if end <= start:
            raise ValueError(f'{prefix}在视频时长范围内没有有效显示区间。')

        title = chapter.get('title')
        if not isinstance(title, str):
            raise ValueError(f'{prefix} title 必须是非空文字。')
        title = title.replace('\\n', '\n').strip()
        if not title or len(title.splitlines()) > 2:
            raise ValueError(f'{prefix} title 必须是非空文字，且最多两行。')
        subtitle = chapter.get('subtitle', '')
        if not isinstance(subtitle, str):
            raise ValueError(f'{prefix} subtitle 必须是文字。')
        if '\n' in subtitle or '\r' in subtitle:
            raise ValueError(f'{prefix} subtitle 必须是单行文字。')
        label = chapter.get('label')
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise ValueError(f'{prefix} label 必须是非空文字。')
        if label is not None and ('\n' in label or '\r' in label):
            raise ValueError(f'{prefix} label 必须是单行文字。')
        chapter.update(start=start, end=end, title=title, subtitle=subtitle.strip())
        if label is not None:
            chapter['label'] = label.strip()
        result.append(chapter)

    result.sort(key=lambda item: item['start'])
    for index, chapter in enumerate(result):
        if index and result[index - 1]['end'] > chapter['start']:
            raise ValueError(f'章节时间重叠：{result[index - 1]["title"]} / {chapter["title"]}。')
        if chapter.get('label') is None:
            chapter['label'] = f'{index + 1:02d}'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, help='章节计划 JSON')
    parser.add_argument('--duration', type=float, help='可选的视频时长（秒）')
    args = parser.parse_args()
    try:
        chapters = load_chapters(args.plan, args.duration)
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({'chapter_count': len(chapters), 'chapters': [
        {key: chapter[key] for key in ('label', 'start', 'end', 'title')}
        for chapter in chapters
    ]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
