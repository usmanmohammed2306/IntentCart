"""Executable offline replay through the real Missions/payment endpoints."""
import copy
import json
import os

import pytest

from intentcart import replay


def trace(name):
    return copy.deepcopy(next(case['trace'] for case in replay.scenario_traces() if case['id'] == name))


@pytest.mark.parametrize('operation', ['create', 'capture', 'refund'])
@pytest.mark.parametrize('point', ['before', 'after'])
def test_durable_recovery_across_actual_interpreter_restart(operation, point):
    result = replay.run_trace(trace(operation + '-' + point))
    assert not result['violations']
    assert result['completed'] and result['process_restarts'] == 1
    assert result['ledger_counts']['commits'] == {
        'create': 1, 'capture': 1, 'refund': int(operation == 'refund')}
    assert result['ledger_counts']['request_identities'][operation] == 1
    assert any(event.get('http_status') == 502 and event['uncertain'] for event in result['events'])
    assert result['live_provider_calls'] == 0


def test_valid_controls_complete_and_replay_digest_is_exact():
    for name in ('valid-refund', 'valid-restart'):
        original = trace(name)
        result = replay.run_trace(original)
        original['expected_digest'] = result['replay_digest']
        assert replay.run_trace(original) == result
        assert result['completed'] and not result['violations']


@pytest.mark.parametrize('case,expected', [('stale-approval', None), ('missing-approval', None), ('order-completed', 'CREATED')])
def test_intact_gates_reject_declared_invalid_events(case, expected):
    result = replay.run_trace(trace(case))
    assert not result['violations'] and not result['completed']
    assert result['local_status'] == expected
    assert result['ledger_counts']['commits']['capture'] == 0


@pytest.mark.parametrize('mutant,case,violation', [
    ('stale-approval', 'stale-approval', 'stale-approval-dispatched'),
    ('fresh-retry-id', 'create-after', 'duplicate-provider-create'),
    ('order-completed', 'order-completed', 'unsupported-completion'),
])
def test_mutation_is_detected_reduced_and_reproduced(mutant, case, violation):
    original = trace(case)
    original['mutant'] = mutant
    reduced = replay.shrink_trace(original)
    assert reduced['outcome']['violations'] == [violation]
    assert reduced['removal_minimal']
    assert reduced['reduced_events'] < reduced['original_events']
    assert replay.run_trace(reduced['trace']) == reduced['outcome']
    # Independently check the claimed single-deletion minimum for this case.
    for index in range(1, len(reduced['trace']['steps'])):
        candidate = copy.deepcopy(reduced['trace'])
        candidate['steps'].pop(index)
        candidate['expected_digest'] = None
        try:
            replay.load_trace(candidate)
        except replay.ReplayError:
            continue
        assert replay.run_trace(candidate)['violations'] != [violation]


@pytest.mark.parametrize('edit', [
    lambda value: value.update(url='https://example.invalid'),
    lambda value: value.update(code='print(1)'),
    lambda value: value.update(schema_version='unknown-version'),
    lambda value: value['steps'].append({'op': 'fetch', 'url': 'https://example.invalid'}),
    lambda value: value['steps'].append({'op': 'create', 'approved': 'true'}),
    lambda value: value.update(steps=[{'op': 'start'}, {'op': 'capture'}]),
    lambda value: value.update(steps=[{'op': 'start'}, {'op': 'restart'}]),
    lambda value: value.update(steps=[{'op': 'start'}, {'op': 'restart'}, {'op': 'restart'}, {'op': 'read'}]),
    lambda value: value.update(steps=[{'op': 'start'}, {'op': 'fault', 'at': 'capture-after'}]),
    lambda value: value['source_sha256'].update({'../../elsewhere': '0' * 64}),
])
def test_strict_trace_language_rejects_extensions_and_invalid_prerequisites(edit):
    value = trace('valid-refund')
    edit(value)
    with pytest.raises(replay.ReplayError):
        replay.load_trace(value)


def test_stale_source_and_unexpected_outcome_are_rejected():
    value = trace('valid-restart')
    value['source_sha256']['intentcart/app.py'] = '0' * 64
    with pytest.raises(replay.SourceMismatch, match='Source mismatch'):
        replay.run_trace(value)
    value = trace('valid-restart')
    value['expected_digest'] = '0' * 64
    with pytest.raises(replay.ReplayError, match='digest mismatch'):
        replay.run_trace(value)


def test_replay_does_not_touch_configured_storage_or_export_private_ids(tmp_path, monkeypatch):
    protected = tmp_path / 'user.sqlite3'
    protected.write_bytes(b'do not touch this database')
    monkeypatch.setenv('DATABASE_PATH', str(protected))
    monkeypatch.setenv('PAYPAL_CLIENT_SECRET', 'replay-must-not-export-this')
    result = replay.run_trace(trace('valid-refund'))
    encoded = json.dumps(result)
    assert protected.read_bytes() == b'do not touch this database'
    assert 'replay-must-not-export-this' not in encoded
    for private_field in ('csrf', 'cookie', 'request_key', 'quote_id', 'provider_id'):
        assert private_field not in encoded
    assert os.environ['PAYPAL_CLIENT_SECRET'] == 'replay-must-not-export-this'


def test_private_worker_cannot_start_without_disposable_environment(tmp_path):
    with pytest.raises(replay.ReplayError, match='disposable storage'):
        replay._segment({'directory': str(tmp_path)})


def test_shrinker_rejects_no_failure_and_reports_bounded_incompletion():
    with pytest.raises(replay.ReplayError, match='requires a reproduced'):
        replay.shrink_trace(trace('valid-refund'))
    value = trace('stale-approval')
    value['mutant'] = 'stale-approval'
    result = replay.shrink_trace(value, max_attempts=1)
    assert not result['removal_minimal'] and result['attempts'] == 1


def test_source_change_during_reduction_aborts_instead_of_claiming_minimum(monkeypatch):
    value = trace('stale-approval')
    value['mutant'] = 'stale-approval'
    calls = []
    def interrupted(candidate):
        calls.append(True)
        if len(calls) == 1:
            return {'violations': ['stale-approval-dispatched']}
        raise replay.SourceMismatch('Source changed during candidate execution')
    monkeypatch.setattr(replay, 'run_trace', interrupted)
    with pytest.raises(replay.SourceMismatch):
        replay.shrink_trace(value)
