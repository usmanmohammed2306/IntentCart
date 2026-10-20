"""Matched local-policy evaluation, deliberately not a live-model benchmark.

New fixed tasks share catalog, goal, budgets, user answers and an independent
grader. Raw action attempts and failures are retained. No provider imports.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import agent
from scripts import missions_oracle as oracle

SOURCE_FILES = ('intentcart/workbench.py', 'intentcart/agent.py', 'intentcart/evidence_catalog.py', 'intentcart/workspace_preferences.py',
                'intentcart/missions.py', 'intentcart/data/missions-catalog.json', 'intentcart/data/evidence-catalog.json',
                'scripts/missions_oracle.py', 'scripts/evaluate_agent.py', 'intentcart/data/agent-protocol.json')

@contextmanager
def grader_catalog(catalog):
    old_data, old_items = oracle.DATA, oracle.ITEMS
    oracle.DATA, oracle.ITEMS = catalog, {p['id']: p for p in catalog['products']}
    try:
        yield
    finally:
        oracle.DATA, oracle.ITEMS = old_data, old_items

def trial(task, policy):
    started = time.perf_counter()
    record = agent.create(task['query'], task['goal'], task['catalog_kind'], task['inspection_budget'], True)
    errors = []
    for _ in range(30):
        try:
            if record['pending_question']:
                record = agent.answer(record, task['driver_answer'], origin='scripted_user')
            if record['status'] != 'ACTIVE': break
            record = agent.step(record, agent.local_action(record, policy))
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
            break
    catalog = agent.catalog_for(task['catalog_kind'])
    with grader_catalog(catalog):
        full = [o['source_id'] for p in catalog['products'] for o in p['observations']]
        # The task's answer is fixed independently of whether a policy asks it.
        # Existing explicit permission takes precedence over a scripted reply.
        final_goal = {**record['goal'], 'allow_driver': bool(task['goal'].get('allow_driver', False) or task['driver_answer'])}
        gold = oracle.best(final_goal, full)
        result = agent.solve(record)
        plan = result['plan']
        supported = bool(record['status'] == 'RECOMMENDED' and plan and
                         oracle.grade(record['goal'], plan['items'], record['inspected']))
        invalid = record['status'] == 'RECOMMENDED' and not supported
        minimum_cost = bool(supported and gold and plan['total_cents'] == gold[0][1])
        correct_defer = record['status'] == 'DEFERRED' and gold is None
    return {'task_id': task['id'], 'family': task['family'], 'policy': policy,
            'catalog_kind': task['catalog_kind'], 'inspection_budget': task['inspection_budget'],
            'solvable_under_scripted_answer': gold is not None, 'status': record['status'],
            'supported_recommendation': supported, 'minimum_cost_match': minimum_cost,
            'invalid_recommendation': invalid, 'correct_deferral': correct_defer,
            'solvable_deferral': record['status'] == 'DEFERRED' and gold is not None,
            'inspections': len(record['inspected']), 'questions': sum(e['action']['action'] == 'clarify' for e in record['events']),
            'steps': len(record['events']), 'elapsed_ms': (time.perf_counter() - started) * 1000,
            'errors': errors, 'events': record['events'], 'model_calls': 0, 'tokens': None,
            'provider_cost_microusd': 0}

def evaluate():
    protocol_path = ROOT / 'intentcart/data/agent-protocol.json'
    protocol = json.loads(protocol_path.read_text())
    records = [trial(t, p) for t in protocol['tasks'] for p in protocol['policies']]
    summaries = {}
    for policy in protocol['policies']:
        rows = [r for r in records if r['policy'] == policy]
        summaries[policy] = {'task_count': len(rows),
            'solvable_tasks': sum(r['solvable_under_scripted_answer'] for r in rows),
            'supported_recommendations': sum(r['supported_recommendation'] for r in rows),
            'minimum_cost_matches': sum(r['minimum_cost_match'] for r in rows),
            'correct_deferrals': sum(r['correct_deferral'] for r in rows),
            'solvable_deferrals': sum(r['solvable_deferral'] for r in rows),
            'invalid_recommendations': sum(r['invalid_recommendation'] for r in rows),
            'budget_stops': sum(r['status'] == 'BUDGET_STOP' for r in rows),
            'inspections_total': sum(r['inspections'] for r in rows),
            'questions_total': sum(r['questions'] for r in rows), 'failed_trials': sum(bool(r['errors']) for r in rows)}
    return {'schema': 'intentcart-agent-evaluation/1', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
        'mode': 'matched deterministic local policies; no live model',
        'denominators': {'scenario_structures': len({t['family'] for t in protocol['tasks']}),
                         'budgeted_tasks': len(protocol['tasks']), 'policies': len(protocol['policies']), 'runs': len(records)},
        'checks': {'no_invalid_recommendations': not any(r['invalid_recommendation'] for r in records),
                   'inspection_limits': all(r['inspections'] <= r['inspection_budget'] for r in records),
                   'no_runner_errors': not any(r['errors'] for r in records)},
        'summaries': summaries, 'records': records,
        'limitations': 'Authored tasks and scripted human answers; repeated budget cuts are correlated. Curated records are not hardware tests. Independent grader shares declared rules. No LLM quality, statistical superiority, human benefit or provider latency claim.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'intentcart/data/agent-evaluation.json')
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('mode', 'denominators', 'checks', 'summaries')}, indent=2))
    return 0 if all(report['checks'].values()) else 1

if __name__ == '__main__':
    raise SystemExit(main())
