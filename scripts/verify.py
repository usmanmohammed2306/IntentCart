"""Run local release checks with disposable storage and no provider credentials."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--node', default=os.environ.get('NODE_BINARY') or shutil.which('node'),
                    help='Node executable (or set NODE_BINARY)')
args = parser.parse_args()
if not args.node:
    parser.error('Node is required for the JavaScript syntax check; supply --node PATH.')

with tempfile.TemporaryDirectory(prefix='intentcart-verify-') as directory:
    env = dict(os.environ, DATABASE_PATH=str(Path(directory) / 'app.sqlite3'),
               PYTHONDONTWRITEBYTECODE='1', EXTERNAL_CALL_LIMIT='0',
               PAYPAL_CLIENT_ID='', PAYPAL_CLIENT_SECRET='', CHANNEL3_API_KEY='',
               ASTRO_GATEWAY_URL='', ASTRO_GATEWAY_API_KEY='', ASTRO_BUDGET_MICROUSD='0',
               SANDBOX_BUYER_EMAIL='', SANDBOX_BUYER_PASSWORD='')
    commands = [
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider'],
        [args.node, '--check', 'intentcart/web/app.js'],
        [args.node, '--check', 'intentcart/web/insights.js'],
        [args.node, '--check', 'intentcart/web/study.js'],
        [args.node, '--check', 'intentcart/web/missions.js'],
        [args.node, '--check', 'intentcart/web/missions-state.js'],
        [args.node, '--check', 'intentcart/web/spatial-scene.js'],
        [args.node, '--check', 'intentcart/web/reliability.js'],
        [args.node, '--check', 'intentcart/web/validity-view.js'],
        [args.node, '--check', 'intentcart/web/agent.js'],
        [args.node, '--check', 'intentcart/web/workbench.js'],
        [args.node, '--check', 'intentcart/web/roadmap-research.js'],
        [args.node, '--test', 'tests/test_insights.js', 'tests/missions-state.test.mjs', 'tests/validity-view.test.mjs'],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=env)
        if result.returncode:
            raise SystemExit(result.returncode)
print('Python tests, JavaScript behavior tests and syntax passed. Disposable storage removed; provider credentials blank; sponsor ceiling zero.')
