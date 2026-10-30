"""Local Paraformer Chinese transcription with real token timestamps."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import wave


def runtime_config():
    path = Path(__file__).resolve().parents[1] / 'runtime.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def tokenize(text):
    # Paraformer postprocessing uses Chinese characters and whole English words.
    return re.findall(r'[A-Za-z]+(?:[\x27\u2019][A-Za-z]+)*|[\u3400-\u9fff]|[0-9]|[^\s]', text)


PUNCT = set('，。！？；：、,.!?;:…“”‘’"()（）《》【】—-')


def timed_units(item):
    text = item.get('text', '').strip()
    if not text:
        return []
    parts = tokenize(text)
    tokens = []
    leading = ''
    for part in parts:
        if all(c in PUNCT for c in part):
            if tokens:
                tokens[-1] += part
            else:
                leading += part
        else:
            tokens.append(leading + part)
            leading = ''
    stamps = item.get('timestamp', [])
    if len(tokens) != len(stamps):
        # Some checkpoints group digit runs instead of individual digits.
        grouped = []
        for token in tokens:
            if grouped and grouped[-1].isdigit() and token.isdigit():
                grouped[-1] += token
            else:
                grouped.append(token)
        if len(grouped) == len(stamps):
            tokens = grouped
        else:
            raise ValueError(f'识别文字与时间戳数量不匹配：{len(tokens)} / {len(stamps)}，已停止，未生成猜测时间轴。')
    units = []
    for word, (a, b) in zip(tokens, stamps):
        if float(b) < float(a) or float(a) < 0:
            raise ValueError('识别模型返回无效时间戳。')
        units.append({'text': word, 'start': float(a) / 1000, 'end': float(b) / 1000})
    return units


def join_words(words):
    text = ''
    for word in words:
        if text and text[-1].isascii() and text[-1].isalnum() and word[0].isascii() and word[0].isalnum():
            text += ' '
        text += word
    return text


def make_cues(units, duration, max_chars=28, max_seconds=4.5):
    cues, pending = [], []
    def flush():
        if not pending:
            return
        a = max(0, pending[0]['start'])
        b = min(duration, max(pending[-1]['end'], a + .08))
        if b > a:
            text = join_words([u['text'] for u in pending])
            cues.append({'start': a, 'end': b, 'text': text})
        pending.clear()
    for unit in units:
        if pending and (unit['start'] - pending[-1]['end'] > .5
                        or len(join_words([u['text'] for u in pending] + [unit['text']])) > max_chars
                        or unit['end'] - pending[0]['start'] > max_seconds):
            flush()
        pending.append(unit)
        if unit['text'][-1] in '，。！？；,.!?;':
            flush()
    flush()
    # Brief fillers such as 嗯/好 should not flash as isolated captions.
    def short(cue):
        return cue['end'] - cue['start'] < .8 or len(cue['text']) <= 2
    def mergeable(left, right):
        return (0 <= right['start'] - left['end'] <= .5
                and right['end'] - left['start'] <= max_seconds
                and len(join_words([left['text'], right['text']])) <= max_chars)
    merged = []
    for cue in cues:
        if merged and short(merged[-1]) and mergeable(merged[-1], cue):
            merged[-1]['text'] = join_words([merged[-1]['text'], cue['text']])
            merged[-1]['end'] = cue['end']
        else:
            merged.append(cue.copy())
    cues = []
    for cue in merged:
        if cues and short(cue) and mergeable(cues[-1], cue):
            cues[-1]['text'] = join_words([cues[-1]['text'], cue['text']])
            cues[-1]['end'] = cue['end']
        else:
            cues.append(cue)
    for cue in cues:
        text = cue['text']
        if len(text) > 16:
            middle = len(text) // 2
            spaces = [m.start() for m in re.finditer(' ', text) if abs(m.start() - middle) <= 5]
            cut = min(spaces, key=lambda x: abs(x - middle)) if spaces else middle
            cue['text'] = text[:cut].strip() + '\n' + text[cut:].strip()
    # A model can produce touching/overlapping token edges; keep SRT monotonic.
    for i in range(len(cues) - 1):
        cues[i]['end'] = min(cues[i]['end'], cues[i + 1]['start'])
    if any(c['end'] <= c['start'] for c in cues):
        raise ValueError('字幕时间轴发生重叠，已停止以免丢失文字。')
    return cues


def srt_time(value):
    ms = round(value * 1000)
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def transcribe(source, destination, hotwords='', device='cpu'):
    from render import ffmpeg_path, run
    cfg = runtime_config()
    if cfg.get('model_cache'):
        os.environ['MODELSCOPE_CACHE'] = cfg['model_cache']
        cache_root = Path(cfg['model_cache']).parent
        os.environ.setdefault('HF_HOME', str(cache_root / 'huggingface'))
        os.environ.setdefault('NUMBA_CACHE_DIR', str(cache_root / 'numba-cache'))
    os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = destination.with_suffix('.json')
    transcript = destination.with_suffix('.txt')
    if any(p.exists() for p in [destination, report, transcript]):
        raise FileExistsError('识别输出文件已存在，请选新路径。')
    source = Path(source).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='.asr-', dir=destination.parent) as temp:
        audio = Path(temp) / 'audio.wav'
        run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-i', str(source),
             '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)])
        with wave.open(str(audio), 'rb') as wav:
            duration = wav.getnframes() / wav.getframerate()
        from funasr import AutoModel
        models = cfg.get('models', {})
        model = AutoModel(model=models.get('asr', 'paraformer-zh'),
                          vad_model=models.get('vad', 'fsmn-vad'),
                          punc_model=models.get('punc', 'ct-punc'),
                          device=device, ncpu=4, disable_update=True,
                          trust_remote_code=False, disable_pbar=True,
                          vad_kwargs={'max_single_segment_time': 15000})
        options = dict(input=str(audio), batch_size_s=60, sentence_timestamp=True)
        if hotwords:
            options['hotword'] = hotwords
        result = model.generate(**options)
    transcript.write_text('\n'.join(item.get('text', '') for item in result), encoding='utf-8')
    data = dict(engine='FunASR Paraformer', device=device, duration=duration,
                versions={n: importlib.metadata.version(n) for n in ['funasr', 'torch', 'torchaudio']},
                models=models or {'asr': 'paraformer-zh', 'vad': 'fsmn-vad', 'punc': 'ct-punc'},
                hotwords=hotwords, result=result, status='recognized')
    def serializable(value):
        if hasattr(value, 'tolist'):
            return value.tolist()
        raise TypeError(type(value).__name__)
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=serializable), encoding='utf-8')
    units = []
    for item in result:
        units.extend(timed_units(item))
    units.sort(key=lambda u: u['start'])
    cues = make_cues(units, duration)
    if not cues:
        raise ValueError('没有识别到带时间戳的语音，未生成空字幕。')
    srt = '\n\n'.join(f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}"
                       for i, c in enumerate(cues, 1)) + '\n'
    destination.write_text(srt, encoding='utf-8-sig')
    data.update(cues=cues, status='subtitled')
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=serializable), encoding='utf-8')
    print(json.dumps({'srt': str(destination), 'cues': len(cues), 'duration': duration}, ensure_ascii=False))
    return destination


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--hotwords', default='')
    p.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    args = p.parse_args()
    transcribe(args.input, args.output, args.hotwords, args.device)


if __name__ == '__main__':
    main()
