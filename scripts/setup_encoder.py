"""Download the pinned public encoder once. Never called by the app itself."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from intentcart.semantic import REPO, REVISION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'var/models/all-MiniLM-L6-v2')
    args = parser.parse_args()
    target = args.directory.resolve()
    target.mkdir(parents=True,exist_ok=True)
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    from huggingface_hub import snapshot_download
    snapshot_download(REPO, revision=REVISION, local_dir=str(target), token=False,
                      allow_patterns=['config.json','model.safetensors','tokenizer.json',
                                      'tokenizer_config.json','special_tokens_map.json','vocab.txt',
                                      'README.md','LICENSE.txt','LICENSE'], max_workers=4)
    names = ['config.json','model.safetensors','tokenizer.json','tokenizer_config.json',
             'special_tokens_map.json','vocab.txt','README.md','LICENSE.txt']
    files = {name:hashlib.sha256((target/name).read_bytes()).hexdigest()
             for name in names if (target/name).is_file()}
    required = {'config.json','model.safetensors','tokenizer.json','tokenizer_config.json','vocab.txt'}
    if not required <= set(files):
        raise RuntimeError('The pinned encoder download is incomplete.')
    manifest = {'schema':'intentcart-local-encoder/1','repo':REPO,'revision':REVISION,
                'dimension':384,'max_wordpieces':256,'pooling':'attention-mask mean + L2 normalization',
                'device':'cpu','license':'Apache-2.0','model_card':'https://huggingface.co/'+REPO,
                'files':files}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'directory':str(target),'revision':REVISION,'files':len(files),'device':'cpu',
                      'setup':'Explicit public model download; no hosted inference or API credentials.'},indent=2))


if __name__ == '__main__':
    main()
