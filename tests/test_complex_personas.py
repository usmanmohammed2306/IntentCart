from copy import deepcopy
from datetime import date
import socket
import sys

import pytest
from scripts import rehearse_complex_personas as rehearsal


def test_complex_journeys_are_offline_reproducible_and_preserve_different_endings(monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError('No network in a fictional persona rehearsal')
    monkeypatch.setattr(socket, 'create_connection', deny_network)
    report = rehearsal.evaluate(date(2026, 10, 19))
    assert report == rehearsal.evaluate(date(2026, 10, 19))
    assert report['human_participants'] == report['consent_records'] == 0
    assert report['provider_requests'] == report['payment_operations'] == 0
    assert report['fictional_personas'] == 8
    assert report['correlated_journeys'] == 24
    assert report['steps'] == 223
    assert report['passed_checks'] == report['checks'] == 648
    assert report['all_checks_pass']
    runs = {(j['persona_id'], j['variant']): j for j in report['journeys']}
    final = lambda persona, variant: runs[persona, variant]['steps'][-1]['state']
    assert final('mira', 'baseline')['recommended']
    assert not final('mira', 'cost-shock')['recommended']
    for variant in ('baseline', 'cost-shock', 'interrupted'):
        assert not final('noah', variant)['allow_driver']
        assert not final('noah', variant)['recommended']
        assert not final('tess', variant)['recommended']
        assert final('jules', variant)['recommended']
        assert final('ari', variant)['recommended']
    assert any('rank_roundtrip_exact' in s['checks'] for j in report['journeys'] for s in j['steps'])
    assert all(len(p['competing_priorities']) >= 4 and p['stop_condition'] for p in report['profiles'])
    assert 'Zero human participants' in rehearsal.markdown(report)


def test_complex_journeys_detect_silent_acceptance_of_wrong_variant(monkeypatch):
    original = rehearsal.workbench.mutate
    def broken(record, operation, payload):
        if operation == 'offer' and payload.get('variant') == 'wrong-model-suffix':
            return deepcopy(record)
        return original(record, operation, payload)
    monkeypatch.setattr(rehearsal.workbench, 'mutate', broken)
    report = rehearsal.evaluate(date(2026, 10, 19))
    assert not report['all_checks_pass']
    failed = [(j['persona_id'], s['checks']) for j in report['journeys'] for s in j['steps']
              if not all(s['checks'].values())]
    assert len(failed) == 3
    assert all(persona == 'leena' and not checks['invalid_input_rejected'] for persona, checks in failed)


def test_cli_preserves_existing_evidence(tmp_path, monkeypatch):
    existing = tmp_path / 'evidence.json'
    existing.write_text('previous evidence')
    monkeypatch.setattr(sys, 'argv', ['rehearse_complex_personas.py', '--as-of', '2026-10-19',
                        '--output', str(existing), '--markdown', str(tmp_path / 'report.md')])
    with pytest.raises(SystemExit) as error:
        rehearsal.main()
    assert error.value.code == 2
    assert existing.read_text() == 'previous evidence'
    assert not (tmp_path / 'report.md').exists()
