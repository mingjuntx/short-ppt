"""Download the three official models into an explicitly chosen runtime folder."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-root', required=True)
    args = p.parse_args()
    root = Path(args.runtime_root).resolve()
    cache = root / 'models'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['MODELSCOPE_CACHE'] = str(cache)
    os.environ.setdefault('MODELSCOPE_DOWNLOAD_PARALLEL_THRESHOLD_MB', '64')
    os.environ.setdefault('MODELSCOPE_DOWNLOAD_PARALLEL_WORKERS', '8')
    os.environ.setdefault('MODELSCOPE_DOWNLOAD_PART_SIZE_MB', '32')
    from modelscope import snapshot_download
    ids = {
        'asr': 'iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch',
        'vad': 'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch',
        'punc': 'iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch',
    }
    models = {}
    for key, model_id in ids.items():
        print('Preparing ' + key + ': ' + model_id, flush=True)
        models[key] = snapshot_download(model_id, cache_dir=str(cache), ignore_patterns=['*.onnx', '*.zip', '*.tar.gz'])
    cfg = dict(python=sys.executable, model_cache=str(cache), models=models, model_ids=ids)
    target = Path(__file__).resolve().parents[1] / 'runtime.json'
    target.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Runtime ready: ' + str(target), flush=True)


if __name__ == '__main__':
    main()
