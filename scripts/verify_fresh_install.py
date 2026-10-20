"""Install pinned dependencies into a new disposable environment and verify.

Explicit operator command. Downloads official PyPI packages; never consumes
sponsor credits, copies .env, starts a service or pushes a repository.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', help='Optional Node executable for the canonical verifier.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='intentcart-fresh-') as directory:
        target = Path(directory)
        subprocess.run([sys.executable, '-m', 'venv', str(target)], check=True)
        python = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        env = {k: v for k, v in os.environ.items() if k not in ('PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL')}
        subprocess.run([str(python), '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple',
                        '--retries', '0', '--timeout', '20', '-r', str(ROOT / 'requirements.lock.txt')], cwd=ROOT, env=env, check=True)
        command = [str(python), str(ROOT / 'scripts/verify.py')]
        if args.node: command += ['--node', args.node]
        subprocess.run(command, cwd=ROOT, check=True)
    print('Fresh dependency installation and canonical verification passed; disposable environment removed.')

if __name__ == '__main__':
    main()
