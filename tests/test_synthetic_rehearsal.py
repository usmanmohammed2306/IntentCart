from datetime import date
import socket

from scripts import rehearse_workstation as rehearsal


def test_rehearsal_is_reproducible_offline_and_never_counts_people(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError('Synthetic rehearsal must remain offline')
    monkeypatch.setattr(socket, 'create_connection', no_network)
    first = rehearsal.evaluate(date(2026, 10, 19))
    assert first == rehearsal.evaluate(date(2026, 10, 19))
    assert first['human_participants'] == first['consent_records'] == 0
    assert first['provider_requests'] == first['payment_operations'] == 0
    assert first['fictional_personas'] == 8
    assert first['passed_checks'] == first['scenario_checks'] == 23
    assert first['all_checks_pass']
    assert all(r['persona_is_fictional'] for r in first['records'])
    assert 'intentcart/data/evidence-catalog.json' in first['sources']
    assert 'zero human participants' in rehearsal.markdown(first)
    assert 'not a participant success rate' in rehearsal.markdown(first)
    assert all('elapsed' not in stage and 'rating' not in stage
               for r in first['records'] for stage in r['stages'].values())


def test_rehearsal_detects_ignored_unknown_cost_change(monkeypatch):
    original = rehearsal.workbench.mutate
    def broken(record, operation, payload):
        if operation == 'requirements' and payload.get('tax_cents', 0) is None:
            return record
        return original(record, operation, payload)
    monkeypatch.setattr(rehearsal.workbench, 'mutate', broken)
    report = rehearsal.evaluate(date(2026, 10, 19))
    assert not report['all_checks_pass']
    price_case = next(r for r in report['records'] if r['id'] == 'S03')
    assert not price_case['checks']['unknown_cost_blocks_support']
    assert not price_case['checks']['acceptance_cleared']
