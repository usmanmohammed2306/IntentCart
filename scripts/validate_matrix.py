"""Exhaust a declared 17-axis synthetic validator matrix, with retained cases."""
import argparse
from contextlib import nullcontext
from datetime import date
import gzip
import hashlib
from itertools import product
import json
from math import prod
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import workbench
from scripts.combination_fixture import (AXES, WORLD_KEYS, REQUEST_KEYS, TOTAL_CASES,
    axis_rows, case_from_id, expected_support, imported_record, case_record, subtotal)


def source_hashes(extra=()):
    paths = ['scripts/validate_matrix.py', 'scripts/combination_fixture.py',
             'intentcart/agent.py', 'intentcart/workbench.py', 'intentcart/missions.py',
             'intentcart/evidence_catalog.py', 'intentcart/workspace_preferences.py',
             'intentcart/data/evidence-catalog.json', 'intentcart/data/missions-catalog.json', *extra]
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}


def projections(strength):
    from itertools import combinations
    return sum(prod(len(AXES[key]) for key in group) for group in combinations(AXES, strength))


def evaluate(as_of, limit=TOTAL_CASES, emit=None, progress=None):
    if type(limit) is not int or not 1 <= limit <= TOTAL_CASES:
        raise ValueError('Limit must fit the declared matrix.')
    emit = emit or (lambda row: None)
    counts = {'cases': 0, 'expected_supported': 0, 'observed_supported': 0,
              'false_acceptances': 0, 'false_rejections': 0, 'unexpected_errors': 0,
              'total_price_mismatches': 0, 'index_decode_mismatches': 0}
    first_failures = []
    input_hash = hashlib.sha256()
    index = 0
    with patch.object(workbench, 'current_day', return_value=as_of):
        for world in axis_rows(WORLD_KEYS):
            base = imported_record(world, as_of)
            for request in axis_rows(REQUEST_KEYS):
                for available, costs_known, gap in product(AXES['available'], AXES['costs_known'], AXES['budget_gap_cents']):
                    case = {**world, **request, 'available': available, 'costs_known': costs_known, 'budget_gap_cents': gap}
                    if index == limit:
                        break
                    expected = bool(expected_support(case))
                    actual = None
                    actual_total = None
                    error = None
                    price_ok = True
                    try:
                        rows = workbench.rank(case_record(base, case, as_of))
                        actual = bool(rows)
                        actual_total = rows[0]['total_cents'] if rows else None
                        price_ok = not rows or actual_total == subtotal(case['displays'])
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        error = f'{type(exc).__name__}: {exc}'
                    decoded = case == case_from_id(index)
                    row = {'suite': 'matrix', 'id': index, 'case': case,
                           'expected': expected, 'observed': actual, 'observed_total_cents': actual_total,
                           'price_matches_fixture_arithmetic': price_ok, 'index_decodes_to_input': decoded,
                           'unexpected_error': error}
                    failed = actual != expected or not price_ok or not decoded or error is not None
                    counts['cases'] += 1
                    counts['expected_supported'] += expected
                    counts['observed_supported'] += actual is True
                    counts['false_acceptances'] += actual is True and not expected
                    counts['false_rejections'] += actual is False and expected
                    counts['unexpected_errors'] += error is not None
                    counts['total_price_mismatches'] += not price_ok
                    counts['index_decode_mismatches'] += not decoded
                    if failed and len(first_failures) < 20:
                        first_failures.append(row)
                    input_hash.update(json.dumps(case, sort_keys=True, separators=(',', ':')).encode()+b'\n')
                    emit(row)
                    index += 1
                    if progress and index % 16384 == 0:
                        progress({'matrix_cases_completed': index, 'target': limit})
                if index == limit:
                    break
            if index == limit:
                break
    complete = limit == TOTAL_CASES and counts['cases'] == TOTAL_CASES and counts['index_decode_mismatches'] == 0
    return {'schema': 'intentcart-combination-matrix/1', 'evidence_class': 'synthetic_validator_matrix',
            'snapshot_date': as_of.isoformat(), 'axes': AXES, 'declared_axes': len(AXES),
            'declared_cartesian_cases': TOTAL_CASES, 'requested_limit': limit,
            'complete_cartesian_enumeration': complete,
            'projection_coverage': {
                'basis': 'Implied by full mixed-radix enumeration; auditor independently checks retained IDs and input decoding.',
                'pair_assignments': projections(2) if complete else None,
                'triple_assignments': projections(3) if complete else None},
            **counts, 'first_failures': first_failures,
            'all_checks_pass': not any(counts[k] for k in ('false_acceptances', 'false_rejections', 'unexpected_errors', 'total_price_mismatches', 'index_decode_mismatches')),
            'input_sha256': input_hash.hexdigest(), 'sources': source_hashes(),
            'human_participants': 0, 'provider_requests': 0, 'payment_operations': 0,
            'limits': [
                'Finite authored worlds; no physical hardware or manufacturer truth claim.',
                'Raw validated state construction tests the actual validator, not UI/controller/session behavior.',
                'The oracle is a separately stated finite predicate and price arithmetic; it does not call the planner.',
                'Correlated configurations and projection assignments are not people or independent benchmark tasks.',
                'Exhaustive applies only to these seventeen declared axes and their listed values.',
                'All cases, including every failed case if any, remain in the compressed trace; summary shows only the first twenty failures.',
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    parser.add_argument('--limit', type=int, default=TOTAL_CASES)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--trace', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.trace.resolve() or any(p.exists() for p in (args.output, args.trace)):
        parser.error('Use distinct new output paths; preserve previous evidence.')
    args.trace.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.trace.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as stream:
        def emit(row):
            stream.write((json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n').encode())
        report = evaluate(args.as_of, args.limit, emit, lambda row: print(json.dumps(row), flush=True))
    report['trace'] = {'filename': args.trace.name, 'sha256': hashlib.sha256(args.trace.read_bytes()).hexdigest()}
    with args.output.open('x') as out:
        out.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('cases', 'expected_supported', 'observed_supported', 'false_acceptances', 'false_rejections', 'all_checks_pass', 'complete_cartesian_enumeration')}))
    return 0 if report['all_checks_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
