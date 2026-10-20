"""Permutation, source-review state-machine and deliberate-fault validation."""
import argparse
from copy import deepcopy
from datetime import date, timedelta
import gzip
import hashlib
from itertools import permutations, product
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import agent, workbench
from scripts.combination_fixture import (DOCK, SOURCE, positive_case, imported_record,
                                        case_record, expected_support)
from scripts.validate_matrix import source_hashes

GATES = ('cost', 'inventory', 'offer', 'driver')
SEEDS = ({'displays': 2, 'height': 1080, 'hz': 60},
         {'displays': 3, 'height': 2160, 'hz': 120},
         {'displays': 2, 'height': 2160, 'hz': 60, 'charging_watts': 0})
ORDER_CASES = len(SEEDS) * 24 * 24
REVIEW_CASES = 2 * 120


def initial(as_of, **values):
    case = positive_case(**values)
    record = case_record(imported_record(case, as_of), case, as_of)
    return record


def semantic(record):
    return [{key: row[key] for key in ('id', 'items', 'total_cents', 'checks')}
            for row in workbench.rank(record)]


def offer(as_of, available=True):
    return {'product_id': DOCK, 'variant': 'fictional-v1', 'merchant': 'Synthetic merchant',
            'offer_id': 'FICTIONAL-MATRIX-OFFER', 'price_cents': 10000,
            'observed_on': as_of.isoformat(), 'available': available}


def edit_gate(record, gate, blocked, as_of, original_monitors):
    if gate == 'cost':
        return workbench.mutate(record, 'requirements', {'tax_cents': None if blocked else 0})
    if gate == 'inventory':
        wrong = [{'name': 'Synthetic conflicting inventory', 'height': 720, 'hz': 60, 'connector': 'hdmi'}]
        return workbench.mutate(record, 'requirements', {'owned_monitors': wrong if blocked else original_monitors})
    if gate == 'offer':
        return workbench.mutate(record, 'offer', offer(as_of, not blocked))
    if gate == 'driver':
        return workbench.mutate(record, 'withdraw_driver' if blocked else 'revise_goal', {} if blocked else {'allow_driver': True})
    raise ValueError('Unknown finite gate.')


def order_sequence(base, seed_index, block_order, restore_order, as_of):
    state = deepcopy(base)
    original = semantic(state)
    rows = workbench.rank(state)
    state = agent.step(state, agent.Action(action='recommend', target=rows[0]['id']), origin='scripted_test')
    monitors = deepcopy(workbench.settings(state).owned_monitors)
    blocked = set()
    steps = []
    for phase, ordering in (('block', block_order), ('restore', restore_order)):
        for gate in ordering:
            before = deepcopy(state)
            reference = state
            state = edit_gate(state, gate, phase == 'block', as_of, monitors)
            blocked.add(gate) if phase == 'block' else blocked.remove(gate)
            checks = {'prior_record_unchanged': reference == before,
                      'revision_advances_once': state['revision'] == before['revision']+1,
                      'old_recommendation_cleared': state['recommended_id'] is None,
                      'support_matches_independent_block_set': bool(workbench.rank(state)) == (not blocked)}
            steps.append({'phase': phase, 'gate': gate, 'expected_supported': not blocked, 'checks': checks})
    checks = {'restored_semantics_match_start': semantic(state) == original}
    rows = workbench.rank(state)
    if rows:
        state = agent.step(state, agent.Action(action='recommend', target=rows[0]['id']), origin='scripted_test')
        before = deepcopy(state)
        state = workbench.mutate(state, 'requirements', {'tax_cents': 0})
        checks.update(repeated_noop_clears_acceptance=state['recommended_id'] is None,
                      repeated_noop_advances_revision=state['revision'] == before['revision']+1,
                      repeated_noop_preserves_semantics=semantic(state) == original)
    else:
        checks['restored_recommendation_possible'] = False
    steps.append({'phase': 'repeat_edit', 'checks': checks})
    return {'suite': 'event_orders', 'seed': seed_index, 'block_order': list(block_order),
            'restore_order': list(restore_order), 'steps': steps,
            'all_checks_pass': all(all(s['checks'].values()) for s in steps)}


def review_sequence(base, displays, events):
    state = deepcopy(base)
    model = {'value': 3, 'pending': None, 'inspected': True}
    ids = {}
    steps = []
    for event in events:
        before = deepcopy(state)
        reference = state
        should_accept = True
        error = None
        operation = None
        try:
            if event in ('propose_low', 'propose_high'):
                value = 1 if event == 'propose_low' else 3
                replacement = deepcopy(workbench.catalog(state)['sources'][SOURCE])
                replacement['value'] = value
                operation = 'propose_source'
                state = workbench.mutate(state, operation, {'source_id': SOURCE, 'replacement': replacement,
                                          'reason': 'Synthetic event-order correction'})
                ids[event] = state['workbench']['pending_source']['id']
                model['pending'] = event
            elif event in ('accept_low', 'accept_high'):
                label = 'propose_low' if event == 'accept_low' else 'propose_high'
                should_accept = model['pending'] == label
                operation = 'accept_source'
                state = workbench.mutate(state, operation, {'proposal_id': ids.get(label, 'not-proposed'), 'reviewed': True})
                if should_accept:
                    model.update(value=1 if event == 'accept_low' else 3, pending=None, inspected=False)
            else:
                should_accept = not model['inspected']
                state = agent.step(state, agent.Action(action='inspect', target=SOURCE), origin='scripted_test')
                if should_accept:
                    model['inspected'] = True
        except ValueError as exc:
            error = str(exc)
        checks = {'acceptance_matches_review_state_machine': (error is None) == should_accept,
                  'prior_record_unchanged': reference == before,
                  'source_value_matches_state_machine': workbench.catalog(state)['sources'][SOURCE]['value'] == model['value'],
                  'inspection_matches_state_machine': (SOURCE in state['inspected']) == model['inspected'],
                  'support_matches_state_machine': bool(workbench.rank(state)) == (model['inspected'] and model['value'] >= displays)}
        if error:
            checks['rejected_action_does_not_change_state'] = state == before
        if operation and error is None:
            checks['review_edit_clears_recommendation'] = state['recommended_id'] is None
        steps.append({'event': event, 'expected_accepted': should_accept, 'error': error, 'checks': checks})
    return {'suite': 'source_review_orders', 'requested_displays': displays, 'events': list(events),
            'steps': steps, 'all_checks_pass': all(all(s['checks'].values()) for s in steps)}


def boundary_cases(as_of):
    rows = []
    base = initial(as_of)
    # Offer and specification clocks are varied independently, at exact limits,
    # one day past them, in the future, and at recent dates.
    for evidence_age, offer_age, os_version, tax, shipping in product(
            (-1, 0, 90, 91), (-1, 0, 7, 8), ('11.9', '12.0', '12.0.0', '13.0'), (None, 0, 1), (None, 0, 1)):
        state = deepcopy(base)
        state['goal']['budget_cents'] = 100000
        cat = state['workbench']['catalog']
        for source in cat['sources'].values():
            source['observed_on'] = (as_of-timedelta(days=evidence_age)).isoformat()
        state['workbench']['offers'][DOCK]['observed_on'] = (as_of-timedelta(days=offer_age)).isoformat()
        state['workbench']['requirements'].update(os_version=os_version, tax_cents=tax, shipping_cents=shipping)
        expected = 0 <= evidence_age <= 90 and 0 <= offer_age <= 7 and os_version != '11.9' and tax is not None and shipping is not None
        actual = bool(workbench.rank(state))
        rows.append({'suite': 'freshness_os_cost_boundaries', 'evidence_age_days': evidence_age,
                     'offer_age_days': offer_age, 'os_version': os_version, 'tax_cents': tax,
                     'shipping_cents': shipping, 'expected': expected, 'observed': actual,
                     'all_checks_pass': actual == expected})
    return rows


def mutation_challenge(as_of):
    targets = [
        ('ignore_driver', {'allow_driver': False}, ['driver']),
        ('ignore_display_count', {'display_capacity': 2, 'displays': 3}, ['displays']),
        ('ignore_resolution_path', {'height_capacity': 1080, 'height': 2160}, ['resolution', 'cables']),
        ('ignore_refresh', {'refresh_capacity': 60, 'hz': 120}, ['refresh']),
        ('ignore_charging_target', {'power_capacity': 65, 'charging_watts': 90}, ['charging_target']),
        ('ignore_hdcp', {'hdcp_capability': False}, ['hdcp']),
        ('ignore_gaming', {'gaming_capability': False}, ['gaming']),
        ('ignore_availability', {'available': False}, ['offer_'+DOCK]),
        ('ignore_unknown_all_in_cost', {'costs_known': False}, ['all_in_price']),
    ]
    original = workbench.evaluate
    records = []
    for name, overrides, gates in targets:
        case = positive_case(**overrides)
        state = case_record(imported_record(case, as_of), case, as_of)
        baseline = bool(workbench.rank(state))
        def weakened(record, row, cat, selected=gates):
            result = original(record, row, cat)
            for gate in selected:
                result['checks'][gate] = True
            result['valid'] = all(v is True for v in result['checks'].values())
            return result
        with patch.object(workbench, 'evaluate', weakened):
            mutant = bool(workbench.rank(state))
        records.append({'suite': 'mutation_challenge', 'name': name, 'case': case,
                        'expected': bool(expected_support(case)), 'baseline': baseline,
                        'mutant': mutant, 'detected': mutant != expected_support(case),
                        'is_noop_control': False,
                        'all_checks_pass': baseline == expected_support(case) and mutant != expected_support(case)})
    case = positive_case()
    state = case_record(imported_record(case, as_of), case, as_of)
    baseline = bool(workbench.rank(state))
    def strict_boundary(record, row, cat):
        result = original(record, row, cat)
        result['checks']['all_in_price'] = result['total_cents'] < record['goal']['budget_cents']
        result['valid'] = all(v is True for v in result['checks'].values())
        return result
    with patch.object(workbench, 'evaluate', strict_boundary):
        mutant = bool(workbench.rank(state))
    records.append({'suite': 'mutation_challenge', 'name': 'reject_exact_budget_equality',
                    'expected': True, 'baseline': baseline, 'mutant': mutant, 'detected': mutant is False,
                    'is_noop_control': False, 'all_checks_pass': baseline is True and mutant is False})
    with patch.object(workbench, 'rank', return_value=[]):
        mutant = bool(workbench.rank(state))
    records.append({'suite': 'mutation_challenge', 'name': 'always_defer', 'expected': True,
                    'baseline': baseline, 'mutant': mutant, 'detected': not mutant,
                    'is_noop_control': False, 'all_checks_pass': baseline and not mutant})
    with patch.object(workbench, 'evaluate', lambda record, row, cat: original(record, row, cat)):
        control = bool(workbench.rank(state))
    records.append({'suite': 'mutation_challenge', 'name': 'noop_control', 'expected': True,
                    'baseline': baseline, 'mutant': control, 'detected': control != baseline,
                    'is_noop_control': True, 'all_checks_pass': control == baseline})
    return records


def evaluate(as_of, order_limit=ORDER_CASES, review_limit=REVIEW_CASES, emit=None):
    if not 0 <= order_limit <= ORDER_CASES or not 0 <= review_limit <= REVIEW_CASES:
        raise ValueError('Sequence limits must fit their finite spaces.')
    emit = emit or (lambda row: None)
    counts = {'event_order_sequences': 0, 'source_review_sequences': 0, 'mutation_operations': 0,
              'boundary_cases': 0, 'seeded_faults': 0, 'detected_faults': 0,
              'noop_controls': 0, 'noop_false_alarms': 0, 'failed_records': 0}
    first_failures = []
    def retain(row):
        if not row['all_checks_pass']:
            counts['failed_records'] += 1
            if len(first_failures) < 20:
                first_failures.append(row)
        emit(row)
    with patch.object(workbench, 'current_day', return_value=as_of):
        for seed_index, values in enumerate(SEEDS):
            base = initial(as_of, **values)
            for block_order, restore_order in product(permutations(GATES), repeat=2):
                if counts['event_order_sequences'] == order_limit:
                    break
                row = order_sequence(base, seed_index, block_order, restore_order, as_of)
                counts['event_order_sequences'] += 1
                counts['mutation_operations'] += 9
                retain(row)
            if counts['event_order_sequences'] == order_limit:
                break
        for displays in (2, 3):
            base = initial(as_of, displays=displays)
            for events in permutations(('propose_low', 'propose_high', 'accept_low', 'accept_high', 'inspect')):
                if counts['source_review_sequences'] == review_limit:
                    break
                retain(review_sequence(base, displays, events))
                counts['source_review_sequences'] += 1
            if counts['source_review_sequences'] == review_limit:
                break
        for row in boundary_cases(as_of):
            counts['boundary_cases'] += 1
            retain(row)
        for row in mutation_challenge(as_of):
            if row['is_noop_control']:
                counts['noop_controls'] += 1
                counts['noop_false_alarms'] += row['detected']
            else:
                counts['seeded_faults'] += 1
                counts['detected_faults'] += row['detected']
            retain(row)
    return {'schema': 'intentcart-state-sequence-validation/1', 'snapshot_date': as_of.isoformat(),
            'evidence_class': 'synthetic_state_machine_validation', **counts,
            'complete_event_orders': order_limit == ORDER_CASES,
            'complete_review_orders': review_limit == REVIEW_CASES,
            'all_checks_pass': counts['failed_records'] == 0, 'first_failures': first_failures,
            'human_participants': 0, 'provider_requests': 0, 'payment_operations': 0,
            'sources': source_hashes(['scripts/validate_state_sequences.py']),
            'limits': ['Specified finite state machines and synthetic fixtures only.',
                       'Deliberate in-process faults are test-only patches, not deployed application changes.',
                       'Eleven seeded faults and one negative control do not establish detection of arbitrary bugs.',
                       'All failed records are retained in the compressed trace; summary lists the first twenty.',
                       'Mutation operations, boundary cases and source-order sequences are different denominators.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    parser.add_argument('--order-limit', type=int, default=ORDER_CASES)
    parser.add_argument('--review-limit', type=int, default=REVIEW_CASES)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--trace', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.trace.resolve() or any(p.exists() for p in (args.output,args.trace)):
        parser.error('Supply distinct new paths; existing evidence cannot be overwritten.')
    args.trace.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.trace.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
        def emit(row):
            stream.write((json.dumps(row, sort_keys=True, separators=(',',':'))+'\n').encode())
        report = evaluate(args.as_of, args.order_limit, args.review_limit, emit)
    report['trace'] = {'filename': args.trace.name, 'sha256': hashlib.sha256(args.trace.read_bytes()).hexdigest()}
    with args.output.open('x') as out:
        out.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('event_order_sequences','source_review_sequences','boundary_cases','seeded_faults','detected_faults','failed_records','all_checks_pass')}))
    return 0 if report['all_checks_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
