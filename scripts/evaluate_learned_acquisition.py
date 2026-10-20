"""One frozen CPU imitation experiment with structural distribution shift.

Training labels come from the bounded exact expected-cost teacher. New test
families are generated separately before fitting; no tuning on test outcomes.
"""
import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
from itertools import product
import json
from pathlib import Path
import random
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import acquisition as a, learned_acquisition as learner

SOURCE_FILES = ('intentcart/acquisition.py', 'intentcart/learned_acquisition.py',
                'scripts/evaluate_learned_acquisition.py', 'intentcart/data/learned-protocol.json')

def generate(spec, seed):
    rng = random.Random(seed)
    count = spec['queries']
    family = spec['family']
    worlds = []
    for i, bits in enumerate(product([0, 1], repeat=count)):
        if family == 'parity': outcome = sum(bits) % 2
        elif family == 'any': outcome = int(any(bits))
        elif family == 'threshold': outcome = int(sum(bits) >= 2)
        elif family == 'conditional': outcome = bits[1] if bits[0] else bits[-1]
        else: raise ValueError('Unknown structural family.')
        worlds.append({'id': f'w{i}', 'weight': rng.randint(1, 7),
                       'answers': {f'q{j}': str(b) for j, b in enumerate(bits)},
                       'decision': 'supported-basket' if outcome else None})
    return a.load_problem({'schema': a.SCHEMA, 'id': f'{family}-{seed}', 'revision': '1',
        'queries': [{'id': f'q{j}', 'cost': rng.randint(1, spec['maximum_cost']), 'version': '1'} for j in range(count)],
        'worlds': worlds, 'initial_evidence': []})

def evaluate():
    protocol = json.loads((ROOT / 'intentcart/data/learned-protocol.json').read_text())
    train = [generate(s, seed) for s in protocol['train'] for seed in s['seeds']]
    test = [generate(s, seed) for s in protocol['test'] for seed in s['seeds']]
    model = learner.fit(train, protocol['ridge'])
    rows, summaries = [], {}
    for p in test:
        for policy in ('learned', 'exact', 'decision_split', 'information'):
            for budget in protocol['budgets']:
                episodes = []
                for world in p.worlds:
                    result = learner.run_episode(p, world.id, model, budget) if policy == 'learned' else a.run_episode(p, world.id, policy, budget)
                    cost = result['new_cost'] if policy == 'learned' else result['spent']
                    terminal = result['status'] in ('DECIDED', 'INFEASIBLE')
                    episodes.append({'world_id': world.id, 'weight': world.weight, 'status': result['status'],
                                     'cost': cost, 'supported': terminal and result['decision'] == world.decision})
                mass = sum(w.weight for w in p.worlds)
                expected = sum(Fraction(e['weight'] * e['cost'], mass) for e in episodes)
                coverage = sum(Fraction(e['weight'], mass) for e in episodes if e['supported'])
                rows.append({'problem_id': p.id, 'policy': policy, 'budget': budget,
                             'expected_cost': float(expected), 'supported_coverage': float(coverage), 'episodes': episodes})
    for policy in ('learned', 'exact', 'decision_split', 'information'):
        unrestricted = [r for r in rows if r['policy'] == policy and r['budget'] is None]
        summaries[policy] = {'structures': len(unrestricted),
            'mean_expected_cost': sum(r['expected_cost'] for r in unrestricted) / len(unrestricted),
            'mean_supported_coverage': sum(r['supported_coverage'] for r in unrestricted) / len(unrestricted)}
    report = {'schema': 'intentcart-learned-evaluation/1', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        'model': model, 'denominators': {'train_structures': len(train), 'test_structures': len(test),
            'test_worlds': sum(len(p.worlds) for p in test), 'policies': 4, 'budget_cuts': len(protocol['budgets']),
            'correlated_episodes': sum(len(r['episodes']) for r in rows)}, 'summaries': summaries, 'records': rows,
        'checks': {'supported_terminal_decisions': all(e['supported'] for r in rows for e in r['episodes'] if e['status'] in ('DECIDED', 'INFEASIBLE')),
                   'budget_limits': all(r['budget'] is None or all(e['cost'] <= r['budget'] for e in r['episodes']) for r in rows)},
        'limitations': 'Generated finite priors, structural family shift and scripted outcomes. State/query rows and budget cuts are correlated. CPU ridge imitation is not foundation-model training. Teacher and student target unrestricted expected cost; finite budgets truncate actions. No generalization beyond the declared families or improvement is assumed.'}
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'intentcart/data/learned-evaluation.json')
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('denominators', 'checks', 'summaries')}, indent=2))
    return 0 if all(report['checks'].values()) else 1

if __name__ == '__main__':
    raise SystemExit(main())
