"""Reproduce pre/post query traces and the retained 120-persona policy study.

No provider, user database, or live model is used. This is synthetic parity,
not evidence that decision-aware questioning outperforms the other policies.
"""
import os
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import evaluate
from scripts.benchmarks.learning_v2_1 import choose_pair as reference
from intentcart.learning import choose_pair as optimized


def run(output):
    traces, results = {}, {}
    for label, selector in [('reference', reference), ('optimized', optimized)]:
        entries = []
        def observed(*args, **kwargs):
            value = selector(*args, **kwargs)
            policy = args[4] if len(args) > 4 else kwargs.get('policy', 'decision')
            entries.append({'policy': policy, 'pair': list(value[:2]), 'gain': float(value[2])})
            return value
        evaluate.choose_pair = observed
        results[label] = evaluate.run(120, 2026)
        traces[label] = entries
    original = json.loads((ROOT / 'intentcart/data/evaluation.json').read_text())
    for key in ['results', 'paired_differences']:
        assert results['reference'][key] == results['optimized'][key] == original[key], key
    assert len(traces['reference']) == len(traces['optimized']) == 1440
    maximum = 0.
    for a, b in zip(traces['reference'], traces['optimized']):
        assert a['policy'] == b['policy'] and a['pair'] == b['pair']
        maximum = max(maximum, abs(a['gain'] - b['gain']))
    assert maximum < 5e-13
    artifact = {'date': '2026-10-10', 'seed': 2026, 'personas': 120, 'policies': 4, 'policy_sessions': 480,
        'question_selections_compared': 1440, 'selected_pairs_identical': True, 'max_gain_absolute_error': maximum,
        'policy_outcomes_and_paired_intervals_match_original': True, 'human_participants': 0,
        'original_policy_result': 'No demonstrated superiority; retained unchanged.',
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ['intentcart/learning.py', 'scripts/benchmarks/learning_v2_1.py',
                         'scripts/evaluate.py', 'scripts/verify_learning_parity.py']},
        'trace_pair_sha256': {label: hashlib.sha256(json.dumps([(e['policy'], e['pair']) for e in entries],
            separators=(',', ':')).encode()).hexdigest() for label, entries in traces.items()},
        'optimized_reproduction': results['optimized']}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2) + '\n')
    print('Parity: 1,440/1,440 question selections; 480 policy sessions; original outcomes and paired intervals unchanged.')
    print('Max gain error:', maximum, 'Saved:', output)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'intentcart/data/performance-parity.json')
    run(parser.parse_args().output)
