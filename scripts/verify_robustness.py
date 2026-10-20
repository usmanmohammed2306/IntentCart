"""Reproduce both frozen stages in temporary files; never replaces evidence."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VARIABLE = {'created_utc', 'environment', 'development_sha256', 'elapsed_ms',
            'session_ms_median', 'session_ms_p95', 'traced_peak_bytes_one_adaptive_session'}

def compare(expected, actual, path='root'):
    if isinstance(expected, dict):
        keys = set(expected)-VARIABLE
        assert keys == set(actual)-VARIABLE, path
        for key in keys:
            compare(expected[key], actual[key], path+'.'+key)
    elif isinstance(expected, list):
        assert len(expected) == len(actual), path
        for i, (a, b) in enumerate(zip(expected, actual)):
            compare(a, b, f'{path}[{i}]')
    elif isinstance(expected, float):
        assert math.isclose(expected, actual, rel_tol=1e-10, abs_tol=1e-12), path
    else:
        assert expected == actual, path

with tempfile.TemporaryDirectory(prefix='intentcart-robustness-') as directory:
    development = Path(directory)/'development.json'
    for stage in ('development', 'heldout'):
        destination = Path(directory)/(stage+'.json')
        subprocess.run([sys.executable, str(ROOT/'scripts/evaluate_robustness.py'),
                        '--stage', stage, '--development', str(development), '--output', str(destination)],
                       cwd=ROOT, stdout=subprocess.DEVNULL, check=True)
        expected = json.loads((ROOT/f'intentcart/data/robustness-{stage}.json').read_text())
        compare(expected, json.loads(destination.read_text()))
        print(f'{stage}: identities, traces, outcomes, counts and intervals reproduce; timing/timestamp/allocation excluded.', flush=True)
print('No stored evidence replaced, no provider/storage access, no human participation inferred.')
