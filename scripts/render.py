"""Deterministic video gradient, ASS subtitles, and editorial cover renderer."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

SKILL_ROOT = Path(__file__).resolve().parents[1]
FONT_FIELDS = ('font', 'subtitle_font_file', 'chapter_font_file')


def read_style_file(path):
    path = Path(path).expanduser().resolve()
    style = json.loads(path.read_text(encoding='utf-8'))
    for name in FONT_FIELDS:
        if name in style:
            value = Path(style[name]).expanduser()
            if not value.is_absolute():
                value = path.parent / value
            style[name] = str(value.absolute())
    return style


def check_ffmpeg(binary, subtitles=False):
    result = run([binary, '-hide_banner', '-filters'])
    if subtitles and not re.search(r'\bsubtitles\s+V->V', result.stdout.decode('utf-8', errors='replace')):
        raise RuntimeError('当前 FFmpeg 未包含 subtitles/libass，请使用支持 libass 的构建或 imageio-ffmpeg。')


def ffmpeg_path():
    binary = os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg')
    if binary:
        return binary
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(cmd, cwd=None):
    p = subprocess.run(cmd, capture_output=True, cwd=cwd)
    if p.returncode:
        raise RuntimeError(p.stderr.decode('utf-8', errors='replace')[-5000:])
    return p


def gradient(size, start, end, opacity, direction='bottom'):
    w, h = size
    rows = []
    for y in range(h):
        t = max(0, min(1, (y / h - start) / (end - start)))
        level = t * t * (3 - 2 * t)
        rows.append(round(255 * opacity * (1 - level if direction == 'top' else level)))
    alpha = Image.new('L', (1, h))
    alpha.putdata(rows)
    out = Image.new('RGBA', size, (0, 0, 0, 0))
    out.putalpha(alpha.resize(size))
    return out


def load_font(path, size, weight=None):
    font = ImageFont.truetype(path, size)
    if weight is not None:
        try:
            axes = font.get_variation_axes()
            values = [a['default'] for a in axes]
            for i, axis in enumerate(axes):
                if axis['name'].lower() == b'weight':
                    values[i] = max(axis['minimum'], min(axis['maximum'], weight))
            font.set_variation_by_axes(values)
        except OSError:
            pass  # Static font, e.g. Source Han Serif SC Heavy.
    return font


def cover(frame, title, style, output):
    w, h = 1080, 1440
    image = ImageOps.fit(frame.convert('RGB'), (w, h), method=Image.Resampling.LANCZOS).convert('RGBA')
    image = Image.alpha_composite(image, gradient((w, h), style['cover_gradient_start'],
                                  style['cover_gradient_end'], style['cover_gradient_opacity']))
    lines = title.replace('\\n', '\n').splitlines()
    if not 1 <= len(lines) <= 3:
        raise ValueError('封面标题需要 1–3 行，建议两行。')
    size = int(style['cover_font_size'])
    while size >= 48:
        font = load_font(style['font'], size, style.get('font_weight'))
        if max(font.getlength(line) for line in lines) <= w - 100:
            break
        size -= 2
    if max(font.getlength(line) for line in lines) > w - 100:
        raise ValueError('标题过长，请分成 2–3 行或缩短。')
    line_height = round(size * style['cover_line_height'])
    top = min(round(h * style['cover_top']), h - 150 - line_height * len(lines))
    left = round(w * style['cover_left'])
    shadow = Image.new('RGBA', (w, h))
    d = ImageDraw.Draw(shadow)
    for n, line in enumerate(lines):
        d.text((left, top + n * line_height + 3), line, font=font,
               fill=(0, 0, 0, 165), anchor='lt')
    image = Image.alpha_composite(image, shadow.filter(ImageFilter.GaussianBlur(4)))
    d = ImageDraw.Draw(image)
    for n, line in enumerate(lines):
        d.text((left, top + n * line_height), line, font=font, fill='white', anchor='lt')
    image.convert('RGB').save(output, quality=95)


def ass_time(seconds):
    cs = round(seconds * 100)
    return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'


def chapter_overlay(size, title, subtitle, style, label='01'):
    w, h = size
    image = Image.new('RGBA', size)
    text = Image.new('RGBA', size)
    draw = ImageDraw.Draw(text)
    x, y = round(w * .09), round(h * .14)
    regular = style['subtitle_font_file']
    title_lines = title.splitlines()
    rows = [(label, regular, round(w * .047), y)]
    for i, line in enumerate(title_lines):
        rows.append((line, style['chapter_font_file'], round(w * .095), y + round(w * (.073 + i * .115))))
    if subtitle:
        rows.append((subtitle, regular, round(w * .044), y + round(w * (.205 + (len(title_lines)-1) * .115))))
    for words, font_file, fs, top in rows:
        font = load_font(font_file, fs)
        while font.getlength(words) > .82 * w and fs > 12:
            fs -= 1
            font = load_font(font_file, fs)
        draw.text((x, top), words, font=font, fill=(255, 255, 255, 250), anchor='lt')
    shadow = Image.new('RGBA', size)
    shadow.putalpha(text.getchannel('A').point(lambda a: round(a * .45)))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, w / 500))), (0, 2))
    image.alpha_composite(text)
    return image


def video_duration(binary, source):
    result = subprocess.run([binary, '-hide_banner', '-i', str(source)], capture_output=True)
    info = result.stderr.decode('utf-8', errors='replace')
    match = re.search(r'Duration: (\d+):(\d+):([\d.]+)', info)
    if not match:
        raise RuntimeError('无法读取视频时长，未生成顶部节点时间轴。')
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def ellipse_path(cx, cy, rx, ry):
    k = .55228475
    return (f'm {cx-rx:.1f} {cy:.1f} '
            f'b {cx-rx:.1f} {cy-k*ry:.1f} {cx-k*rx:.1f} {cy-ry:.1f} {cx:.1f} {cy-ry:.1f} '
            f'b {cx+k*rx:.1f} {cy-ry:.1f} {cx+rx:.1f} {cy-k*ry:.1f} {cx+rx:.1f} {cy:.1f} '
            f'b {cx+rx:.1f} {cy+k*ry:.1f} {cx+k*rx:.1f} {cy+ry:.1f} {cx:.1f} {cy+ry:.1f} '
            f'b {cx-k*rx:.1f} {cy+ry:.1f} {cx-rx:.1f} {cy+k*ry:.1f} {cx-rx:.1f} {cy:.1f}')


def caption_lines(text, font, max_width, tokenizer):
    # ASR's character-count line breaks are not semantic word boundaries.
    fragments = [s.strip() for s in text.splitlines() if s.strip()]
    flat = ''
    for fragment in fragments:
        if flat and flat[-1].isascii() and flat[-1].isalnum() and fragment[0].isascii() and fragment[0].isalnum():
            flat += ' '
        flat += fragment
    if not flat:
        raise ValueError('字幕条目没有可显示的文字。')
    if font.getlength(flat) <= max_width:
        return [flat]
    boundaries = [end for _, _, end in tokenizer.tokenize(flat, HMM=False)]
    candidates = []
    for end in boundaries:
        left, right = flat[:end].strip(), flat[end:].strip()
        if not left or not right or right[0] in '，。！？；：、,.!?;:':
            continue
        a, b = font.getlength(left), font.getlength(right)
        candidates.append((max(0,a-max_width)+max(0,b-max_width), abs(a-b), left, right))
    if not candidates:
        return [flat]
    _, _, left, right = min(candidates)
    return [left, right]


def make_ass(source, dest, width, height, style):
    import jieba
    import logging
    jieba.setLogLevel(logging.ERROR)
    tokenizer = jieba.Tokenizer()
    tokenizer.tmp_dir = str(dest.parent)
    text = Path(source).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    pattern = r'(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)[^\n]*\n(.*?)(?=\n\s*\n|\Z)'
    cues = re.findall(pattern, text, flags=re.S)
    if not cues:
        raise ValueError('SRT 没有可用时间轴。')
    def seconds(t):
        hh, mm, ss = t.replace(',', '.').split(':')
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    fs = round(width * style['subtitle_scale'])
    ass_scale = style.get('subtitle_ass_scale', 1.30)
    margin = round(height * style['subtitle_bottom'])
    side = round(width * .045)
    outline = max(.5, width / 900)
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style['subtitle_font']},{round(fs*ass_scale)},&H00FFFFFF,&H00FFFFFF,&H70000000,&H90000000,0,0,0,0,100,100,0,0,1,{outline:.2f},{max(.7, width / 700):.1f},2,{side},{side},{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    for begin, end, words in cues:
        a, b = seconds(begin), seconds(end)
        if b <= a:
            raise ValueError('字幕结束时间必须晚于开始时间。')
        words = re.sub(r'<[^>]+>', '', words).strip()
        # Never interpret SRT content as ASS override instructions.
        words = words.replace('\\', '／').replace('{', '（').replace('}', '）')
        cue_size = fs
        font = load_font(style['subtitle_font_file'], cue_size)
        lines = caption_lines(words, font, width - side * 2, tokenizer)
        while max(font.getlength(line) for line in lines) > width - side * 2 and cue_size > fs * .88:
            cue_size -= 1
            font = load_font(style['subtitle_font_file'], cue_size)
            lines = caption_lines(words, font, width - side * 2, tokenizer)
        if max(font.getlength(line) for line in lines) > width - side * 2:
            raise ValueError('字幕过长，无法在两行内安全显示，请重新分段。')
        # Soft oval behind the words, separate from the top-to-bottom mask.
        max_line = min(width - side * 2, max(font.getlength(line) for line in lines))
        ry = cue_size * (.72 + .62 * (len(lines) - 1))
        cy = height - margin - cue_size * (.55 + .62 * (len(lines) - 1))
        shape = ellipse_path(width / 2, cy, max_line / 2 + cue_size * .45, ry)
        alpha = round(255 * (1 - style['subtitle_halo_opacity']))
        halo = (f'{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\blur{width*.022:.1f}'
                f'\\1c&H000000&\\1a&H{alpha:02X}&\\fad(50,70)}}{shape}')
        events.append(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Default,,0,0,0,,{halo}')
        words = r'\N'.join(lines)
        events.append(f'Dialogue: 1,{ass_time(a)},{ass_time(b)},Default,,0,0,0,,{{\\fs{round(cue_size*ass_scale)}\\blur0.2\\fad(50,70)}}{words}')
    dest.write_text(header + '\n'.join(events) + '\n', encoding='utf-8-sig')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--title', required=True)
    p.add_argument('--cover-time', type=float, default=0)
    p.add_argument('--srt')
    p.add_argument('--auto-subtitles', action='store_true', help='使用本地 Paraformer 自动生成中文字幕')
    p.add_argument('--hotwords', default='', help='空格分隔的中文识别热词')
    p.add_argument('--font')
    p.add_argument('--subtitle-font')
    p.add_argument('--style')
    p.add_argument('--gradient-opacity', type=float)
    p.add_argument('--aspect', choices=['original', '3:4', '9:16'])
    p.add_argument('--cover-only', action='store_true')
    p.add_argument('--chapter-title', help='片头左上角的章节标题')
    p.add_argument('--chapter-subtitle', default='')
    p.add_argument('--chapters', help='根据转录语义提炼的顶部关键词节点 JSON 时间表')
    args = p.parse_args()
    if args.auto_subtitles and (args.srt or args.cover_only):
        p.error('--auto-subtitles 不能与 --srt 或 --cover-only 同时使用。')
    if args.chapters and (args.chapter_title or args.chapter_subtitle or args.cover_only):
        p.error('--chapters 不能与单个片头标题参数或 --cover-only 同时使用。')
    source = Path(args.input).resolve()
    out = Path(args.output_dir).resolve()
    if not source.is_file():
        p.error('输入文件不存在。')
    if args.cover_time < 0:
        p.error('封面时间不能小于零。')
    preset = SKILL_ROOT / 'assets' / 'style-v2.json'
    style = read_style_file(preset)
    local_fonts = SKILL_ROOT / 'fonts.local.json'
    if local_fonts.is_file():
        style.update(read_style_file(local_fonts))
    if args.style:
        style.update(read_style_file(args.style))
    for name in ['font', 'subtitle_font', 'gradient_opacity', 'aspect']:
        if getattr(args, name) is not None:
            style[name] = getattr(args, name)
    if not 0 <= style['gradient_opacity'] <= 1:
        p.error('渐变透明度需要在 0–1 之间。')
    if style['aspect'] not in ['original', '3:4', '9:16']:
        p.error('无效的宽高比。')
    if not Path(style['font']).is_file():
        p.error('请先运行 scripts/configure_fonts.py 配置本机字体，或通过 --font 指定封面宋体文件。')
    if (args.srt or args.auto_subtitles or args.chapter_title or args.chapters) and not Path(style['subtitle_font_file']).is_file():
        p.error('字幕字体文件不存在，请在样式配置中指定 subtitle_font_file。')
    if (args.chapter_title or args.chapters) and not Path(style['chapter_font_file']).is_file():
        p.error('章节标题字体文件不存在，请在样式配置中指定 chapter_font_file。')
    out.mkdir(parents=True, exist_ok=True)
    targets = ['cover.jpg', 'style.json'] + ([] if args.cover_only else ['video.mp4'])
    if args.srt:
        targets.append('subtitles.srt')
    if args.auto_subtitles:
        targets += ['recognized.srt', 'recognized.txt', 'recognized.json', 'subtitles.srt']
    if args.chapters:
        targets.append('chapters.json')
    if any((out / name).exists() for name in targets):
        p.error('输出目录已有同名成品，请使用新的目录。')
    ff = ffmpeg_path()
    check_ffmpeg(ff, subtitles=bool(args.srt or args.auto_subtitles))
    chapter_schedule = []
    if args.chapters:
        from chapters import load_chapters
        chapter_schedule = load_chapters(args.chapters, duration=video_duration(ff, source))
    if args.auto_subtitles:
        from transcribe import runtime_config
        import sys
        worker = Path(__file__).with_name('transcribe.py')
        cfg = runtime_config()
        python = cfg.get('python', sys.executable)
        subtitle_path = out / 'recognized.srt'
        task = [python, str(worker), '--input', str(source), '--output', str(subtitle_path)]
        if args.hotwords:
            task += ['--hotwords', args.hotwords]
        # Stream recognition progress; fail before rendering if ASR fails.
        subprocess.run(task, check=True)
        args.srt = str(subtitle_path)
    with tempfile.TemporaryDirectory(prefix='.render-', dir=out) as temp:
        tmp = Path(temp)
        is_image = source.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']
        if is_image and not args.cover_only:
            p.error('图片输入需使用 --cover-only。')
        if is_image:
            frame = Image.open(source)
        else:
            ff = ffmpeg_path()
            run([ff, '-hide_banner', '-loglevel', 'error', '-ss', str(args.cover_time),
                 '-i', str(source), '-frames:v', '1', '-update', '1', str(tmp / 'frame.png')])
            if not (tmp / 'frame.png').is_file():
                p.error('无法抽取封面帧，请选择视频时长内的时间。')
            frame = Image.open(tmp / 'frame.png')
        cover(frame, args.title, style, out / 'cover.jpg')
        if not args.cover_only:
            ow, oh = frame.size
            width = min(1080, ow) // 2 * 2
            ratio = ow / oh if style['aspect'] == 'original' else {'3:4': .75, '9:16': .5625}[style['aspect']]
            height = round(width / ratio / 2) * 2
            gradient((width, height), style['gradient_start'], style['gradient_end'],
                     style['gradient_opacity'], style['gradient_direction']).save(tmp / 'gradient.png')
            graph = (f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,'
                     f"eq=contrast={style['contrast']}:brightness={style['brightness']}:saturation={style['saturation']}[base];"
                     '[base][1:v]overlay=0:0:format=auto[masked];')
            inputs = [ff, '-hide_banner', '-loglevel', 'error', '-i', str(source), '-i', str(tmp / 'gradient.png')]
            if args.chapter_title:
                duration = video_duration(ff, source)
                chapter_schedule = [dict(start=min(.35, duration*.1), end=min(7.55, duration),
                                         title=args.chapter_title, subtitle=args.chapter_subtitle, label='01')]
            current = 'masked'
            for i, chapter in enumerate(chapter_schedule):
                picture = chapter_overlay((width, height), chapter['title'], chapter.get('subtitle', ''), style,
                                          label=chapter.get('label', f'{i+1:02d}'))
                bbox = picture.getbbox()
                # Keep only the header area to avoid decoding a full-frame PNG for every node.
                if bbox:
                    picture = picture.crop((0, 0, width, min(height, bbox[3]+8)))
                filename = tmp / f'chapter-{i}.png'
                picture.save(filename)
                inputs += ['-loop', '1', '-framerate', '30', '-i', str(filename)]
                a, b = chapter['start'], chapter['end']
                fade = min(.22, (b-a)/4)
                graph += (f'[{i+2}:v]format=rgba,fade=t=in:st={a:.6f}:d={fade:.6f}:alpha=1,'
                          f'fade=t=out:st={b-fade:.6f}:d={fade:.6f}:alpha=1[chapter{i}];'
                          f"[{current}][chapter{i}]overlay=0:0:format=auto:shortest=1:enable='gte(t,{a:.6f})*lt(t,{b:.6f})'[headed{i}];")
                current = f'headed{i}'
            graph += f'[{current}]'
            if args.srt:
                make_ass(args.srt, tmp / 'subtitles.ass', width, height, style)
                fonts = tmp / 'fonts'
                fonts.mkdir()
                shutil.copyfile(style['subtitle_font_file'], fonts / 'caption.otf')
                graph += 'subtitles=filename=subtitles.ass:fontsdir=fonts'
            else:
                graph += 'null'
            graph += '[v]'
            run(inputs + ['-filter_complex_threads', '2', '-filter_complex', graph, '-map', '[v]',
                 '-map', '0:a?', '-c:v', 'libx264', '-crf', '19', '-preset', 'medium',
                 '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
                 str(out / 'video.mp4')], cwd=tmp)
        if args.srt:
            shutil.copyfile(args.srt, out / 'subtitles.srt')
        if args.chapters:
            (out / 'chapters.json').write_text(json.dumps({'version':1, 'chapters':chapter_schedule}, ensure_ascii=False, indent=2), encoding='utf-8')
        (out / 'style.json').write_text(json.dumps(style, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(out), 'files': targets}, ensure_ascii=False))


if __name__ == '__main__':
    main()
