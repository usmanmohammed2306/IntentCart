"""Paired deterministic snapshot-change study, with no providers or storage.

Full and selective modes share the same fixture evaluator. Agreement tests cache
invalidation correctness, not independent mathematical validity or novel policy
superiority. Work counts are candidate evaluations, never latency or token cost.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import missions as m, validity as v

SOURCES = ('intentcart/missions.py', 'intentcart/validity.py',
           'intentcart/data/missions-catalog.json', 'scripts/evaluate_validity.py')


def scenarios():
    """Public development/regression cases, not a held-out sample."""
    return [
        ('initial', 'No previous certificate; all candidates require checks.'),
        ('unchanged', 'Identical snapshot; reuse still grants no consent.'),
        ('display_name', 'Unselected display text changes; quote binding is conservatively refreshed.'),
        ('competitor_price', 'A cheaper compatible competitor supersedes the old plan.'),
        ('selected_price', 'Selected price changes; explicit purchase review is required.'),
        ('selected_fact_false', 'Selected dock cannot drive the required displays.'),
        ('selected_fact_conflict', 'A contradicting visible specification prevents verification.'),
        ('source_provenance', 'A source disagrees with its observation; fail closed.'),
        ('inspect_hidden', 'Explicit inspection reveals a relevant fixture field.'),
        ('availability', 'The selected dock becomes unavailable.'),
        ('budget', 'Budget changes affect every basket budget check.'),
        ('display_count', 'Goal changes the candidate structure and quantities.'),
        ('source_identity', 'Source identity changes; preserve computation but invalidate binding.'),
        ('revision', 'Revision changes invalidate binding even with identical requirements.'),
        ('cache_corruption', 'An accidentally damaged row cache is fully recomputed.'),
        ('repair', 'Availability changes under the minimal-change repair objective.'),
    ]


def make_case(name, first, selected):
    catalog = deepcopy(m.CATALOG)
    products = {p['id']: p for p in catalog['products']}
    goal = m.Goal()
    kwargs = {'catalog': catalog, 'previous': deepcopy(first), 'items': deepcopy(selected)}
    def fact(pid, field, value):
        for o in products[pid]['observations']:
            if o['field'] == field:
                o['value'] = value
                catalog['sources'][o['source_id']]['value'] = value
    if name == 'initial': kwargs['previous'] = None
    elif name == 'display_name': products['dock-solo']['name'] = 'Revised fixture label'
    elif name == 'competitor_price': products['dock-pro']['price_cents'] = 100
    elif name == 'selected_price': products['dock-twin']['price_cents'] += 1
    elif name == 'selected_fact_false': fact('dock-twin', 'displays', 1)
    elif name == 'selected_fact_conflict':
        sid = 'conflicting-displays-observation'
        products['dock-twin']['observations'].append({'field': 'displays', 'value': 1, 'source_id': sid, 'visible': True})
        catalog['sources'][sid] = {**catalog['sources']['dock-twin-displays'], 'id': sid, 'value': 1}
    elif name == 'source_provenance': catalog['sources']['dock-twin-displays']['variant'] = 'different-variant'
    elif name == 'inspect_hidden': kwargs['inspected'] = ['dock-archive-max_height']
    elif name == 'availability': kwargs['excluded'] = ['dock-twin']
    elif name == 'budget': goal = m.Goal(budget_cents=27000)
    elif name == 'display_count': goal = m.Goal(displays=1)
    elif name == 'source_identity': kwargs['source_sha256'] = 'declared-source-change-fixture'
    elif name == 'revision': kwargs['revision'] = 2
    elif name == 'cache_corruption':
        next(iter(kwargs['previous']['_cache'].values()))['row']['total_cents'] += 1
    elif name == 'repair':
        kwargs.update(excluded=['dock-twin'], previous_items=selected, items=None)
    return goal, kwargs


def run():
    first = v.analyze(m.Goal())
    selected = m.solve(m.Goal())['plan']['items']
    records = []
    for name, description in scenarios():
        goal, kwargs = make_case(name, first, selected)
        row = {'case_id': name, 'description': description, 'goal': goal.model_dump(),
               'inspected': kwargs.get('inspected', []), 'excluded': kwargs.get('excluded', []),
               'selected_items': kwargs['items'], 'previous_items': kwargs.get('previous_items', []),
               'catalog_sha256': v.digest(kwargs['catalog'])}
        try:
            selective = v.analyze(goal, mode='selective', **kwargs)
            full = v.analyze(goal, mode='full', **kwargs)
            checks = {
                'semantic_claims_match': v.semantic_claims(selective) == v.semantic_claims(full),
                'consent_never_granted': selective['claims']['authorization']['consent_granted'] is False,
                'execution_not_inferred': selective['claims']['execution']['status'] == 'unknown',
                'all_full_candidates_rechecked': full['work']['rechecked_candidates'] == full['work']['candidate_count'],
            }
            if name not in ('initial', 'unchanged', 'cache_corruption'):
                checks['changed_context_requires_review'] = selective['claims']['authorization']['status'] == 'review_required'
            if name in ('initial', 'budget', 'display_count', 'cache_corruption'):
                checks['expected_full_work'] = selective['work']['rechecked_candidates'] == selective['work']['candidate_count']
            if name in ('unchanged', 'display_name', 'source_identity', 'revision', 'availability', 'repair'):
                checks['expected_zero_rechecks'] = selective['work']['rechecked_candidates'] == 0
            if name == 'competitor_price':
                checks['old_plan_superseded'] = selective['claims']['optimality']['status'] == 'superseded'
            if name in ('selected_fact_conflict', 'source_provenance'):
                checks['selected_evidence_unresolved'] = selective['claims']['feasibility']['status'] == 'unresolved'
            if name in ('selected_fact_false', 'availability', 'budget', 'display_count'):
                checks['old_plan_invalid'] = selective['claims']['feasibility']['status'] == 'invalid'
            row.update(passed=all(checks.values()), checks=checks,
                       selective=v.public_certificate(selective), full=v.public_certificate(full))
        except Exception as error:
            # Persist failure as a case outcome; never silently drop an attempt.
            row.update(passed=False, error_type=type(error).__name__, error=str(error))
        records.append(row)
    completed = [r for r in records if 'selective' in r]
    return {
        'schema': 'intentcart-validity-evaluation/1',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'description': 'Sixteen public deterministic snapshot-change cases; paired selective and full recomputation. Fixed development/regression set; not held out.',
        'conclusion': 'Candidate-evaluation reuse with the same evaluator. This measures declared invalidation behavior, not latency, model quality, cash savings, generalization or independent proof of compatibility.',
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES},
        'cases': len(records), 'passed_cases': sum(r['passed'] for r in records),
        'paired_runs_completed': len(completed) * 2,
        'semantic_matches': sum(r['checks']['semantic_claims_match'] for r in completed),
        'checks': sum(len(r.get('checks', {})) for r in records),
        'passed_checks': sum(sum(r.get('checks', {}).values()) for r in records),
        'selective_candidate_evaluations': sum(r['selective']['work']['rechecked_candidates'] for r in completed),
        'full_candidate_evaluations': sum(r['full']['work']['rechecked_candidates'] for r in completed),
        'reused_candidate_evaluations': sum(r['selective']['work']['reused_candidates'] for r in completed),
        'live_provider_calls': 0, 'human_participants': 0,
        'records': records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'intentcart/data/validity-evaluation.json')
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: value for k, value in result.items() if k not in ('records', 'source_sha256')}, indent=2))
    return 0 if result['passed_cases'] == result['cases'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
