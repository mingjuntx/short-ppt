"""Download the official local hand landmark model and save local config."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-root', required=True)
    p.add_argument('--force', action='store_true')
    args = p.parse_args()
    config = Path(__file__).resolve().parents[1] / 'vision.local.json'
    if config.exists() and not args.force:
        p.error('vision.local.json 已存在；需要覆盖时使用 --force。')
    root = Path(args.runtime_root).expanduser().resolve() / 'vision'
    root.mkdir(parents=True, exist_ok=True)
    target = root / 'hand_landmarker.task'
    if not target.exists():
        partial = target.with_suffix('.task.part')
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response, partial.open('wb') as out:
            shutil.copyfileobj(response, out)
        if not zipfile.is_zipfile(partial):
            raise RuntimeError('模型下载不是有效的 MediaPipe Task 文件。')
        with zipfile.ZipFile(partial) as bundle:
            if bundle.testzip() is not None or len([n for n in bundle.namelist() if n.endswith('.tflite')]) < 2:
                raise RuntimeError('模型完整性检查失败。')
        partial.replace(target)
    with target.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    config.write_text(json.dumps(dict(hand_model=str(target), sha256=digest, source=MODEL_URL),
                                 ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(config=str(config), hand_model=str(target), sha256=digest), ensure_ascii=False))


if __name__ == '__main__':
    main()
