"""Discover or select local Chinese fonts without downloading font files."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from PIL import ImageFont


FONT_NAMES = {
    'serif': [
        'NotoSerifSC-VF.ttf', 'NotoSerifSC[wght].ttf',
        'NotoSerifSC-VariableFont_wght.ttf',
        'NotoSerifSC-Bold.otf', 'NotoSerifSC-Bold.ttf',
    ],
    'sans': [
        'Noto Sans SC (TrueType).otf', 'NotoSansSC-Regular.otf',
        'NotoSansSC-Regular.ttf', 'Noto Sans SC Regular.otf',
    ],
    'sans_bold': [
        'Noto Sans SC Bold (TrueType).otf', 'NotoSansSC-Bold.otf',
        'NotoSansSC-Bold.ttf', 'Noto Sans SC Bold.otf',
    ],
}


def common_font_directories():
    """Inspect font folders only; never search the entire home directory."""
    home = Path.home()
    if sys.platform == 'win32':
        windir = os.environ.get('WINDIR') or os.environ.get('SystemRoot')
        roots = [Path(windir) / 'Fonts'] if windir else []
        local = os.environ.get('LOCALAPPDATA')
        roots.append((Path(local) if local else home / 'AppData' / 'Local')
                     / 'Microsoft' / 'Windows' / 'Fonts')
    elif sys.platform == 'darwin':
        roots = [home / 'Library' / 'Fonts', Path('/Library/Fonts'),
                 Path('/System/Library/Fonts')]
    else:
        data_home = Path(os.environ.get('XDG_DATA_HOME', str(home / '.local' / 'share')))
        roots = [data_home / 'fonts', home / '.fonts',
                 Path('/usr/local/share/fonts'), Path('/usr/share/fonts')]
    seen = set()
    for root in roots:
        key = str(root).casefold()
        if key not in seen and root.is_dir():
            seen.add(key)
            yield root


def normalized_name(name):
    return re.sub(r'[^a-z0-9]', '', name.casefold())


def discover_fonts():
    """Find known Noto filenames, including standard nested Noto folders."""
    wanted = {normalized_name(name) for names in FONT_NAMES.values() for name in names}
    found = {}
    for root in common_font_directories():
        try:
            for path in root.rglob('*'):
                key = normalized_name(path.name)
                if key in wanted and path.is_file():
                    found.setdefault(key, path)
        except OSError:
            continue
    return found


def choose_font(explicit, kind, discovered):
    if explicit:
        path = Path(explicit).expanduser()
    else:
        path = next((discovered[normalized_name(name)] for name in FONT_NAMES[kind]
                     if normalized_name(name) in discovered), None)
        if path is None:
            option = '--' + kind.replace('_', '-')
            label = {'serif': '封面宋体', 'sans': '字幕常规黑体',
                     'sans_bold': '章节标题粗黑体'}[kind]
            raise ValueError(f'未找到{label}。请先安装对应 Noto SC 字体，或用 {option} 指定字体文件。')
    try:
        # Windows font folders can permit reading while denying real-path
        # resolution; an absolute path is sufficient for this local config.
        path = path.absolute()
        if not path.is_file():
            raise ValueError('不是文件')
        font = ImageFont.truetype(str(path), 32)
        family, _ = font.getname()
        font.getlength('中文字幕')
    except (OSError, ValueError) as exc:
        option = '--' + kind.replace('_', '-')
        raise ValueError(f'{option} 字体无法读取：{path}（{exc}）') from exc
    return path, family


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serif', help='封面宋体字体文件，推荐 Noto Serif SC 可变字体')
    parser.add_argument('--sans', help='字幕常规字体文件，推荐 Noto Sans SC Regular')
    parser.add_argument('--sans-bold', help='章节标题字体文件，推荐 Noto Sans SC Bold')
    parser.add_argument('--force', action='store_true', help='允许替换已有的 fonts.local.json')
    parser.add_argument('--dry-run', action='store_true', help='检查并显示字体配置，不写文件')
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / 'fonts.local.json'
    if target.exists() and not args.force and not args.dry_run:
        parser.error('fonts.local.json 已存在；需要替换时请加 --force。')
    discovered = discover_fonts() if not all((args.serif, args.sans, args.sans_bold)) else {}
    try:
        serif, _ = choose_font(args.serif, 'serif', discovered)
        sans, sans_family = choose_font(args.sans, 'sans', discovered)
        bold, _ = choose_font(args.sans_bold, 'sans_bold', discovered)
    except ValueError as exc:
        parser.error(str(exc))
    config = {
        'font': str(serif),
        'font_weight': 750,
        'subtitle_font': sans_family,
        'subtitle_font_file': str(sans),
        'chapter_font_file': str(bold),
    }
    rendered = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    if args.dry_run:
        print('已找到以下本机字体；dry-run 不写入配置：')
        print(rendered, end='')
        return
    try:
        with target.open('w' if args.force else 'x', encoding='utf-8') as file:
            file.write(rendered)
    except FileExistsError:
        parser.error('fonts.local.json 已存在；需要替换时请加 --force。')
    except OSError as exc:
        parser.error(f'无法写入本机字体配置：{exc}')
    print('已写入本机字体配置：' + str(target))


if __name__ == '__main__':
    main()
