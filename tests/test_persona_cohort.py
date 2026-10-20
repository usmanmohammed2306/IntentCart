from copy import deepcopy
from datetime import date
import hashlib
import json
import socket
import sys
from unittest.mock import patch

import pytest
from scripts import rehearse_persona_cohort as cohort


def test_expanded_cohort_is_reproducible_offline_with_distinct_workflows(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError('Fictional cohort cannot make network requests')
    monkeypatch.setattr(socket, 'create_connection', no_network)
    report = cohort.evaluate(date(2026, 10, 19))
    assert report == cohort.evaluate(date(2026, 10, 19))
    assert report['fictional_personas'] == 24
    assert report['correlated_journeys'] == 96
    assert report['steps'] == 1069
    assert report['checks'] == report['passed_checks'] == 3269
    assert report['all_checks_pass']
    assert report['human_participants'] == report['consent_records'] == 0
    assert report['provider_requests'] == report['payment_operations'] == report['cash_spend_usd'] == 0
    assert report['software_endings'] == {'RECOMMENDED': 48, 'DEFERRED': 48}
    new_profiles = [p for p in report['profiles'] if not p.get('prior_workflow')]
    assert len(new_profiles) == 16
    signatures = [json.dumps([{k:v for k,v in step.items() if k != 'intent'} for step in p['script']], sort_keys=True)
                  for p in new_profiles]
    assert len(set(signatures)) == 16
    runs = {(j['persona_id'], j['condition']): j for j in report['journeys']}
    for persona in ('priya', 'noah', 'ren', 'zoya', 'theo', 'adil', 'sora', 'ines', 'cam'):
        assert runs[persona, 'ordinary']['steps'][-1]['state']['status'] == 'DEFERRED'
    for persona in ('felix', 'omar', 'hana', 'ben', 'mei', 'nia'):
        assert runs[persona, 'ordinary']['steps'][-1]['state']['status'] == 'RECOMMENDED'
    assert all(j['primary_step_count'] and j['unexpected_error'] is None for j in report['journeys'])
    assert all(hashlib.sha256((cohort.ROOT/path).read_bytes()).hexdigest() == value
               for path, value in report['sources'].items())
    assert 'Zero human participants' in cohort.markdown(report)


def test_cohort_detects_ignored_conflicting_inventory(monkeypatch):
    _, profiles = cohort.load_protocol()
    profile = next(p for p in profiles if p['id'] == 'felix')
    original = cohort.workbench.mutate
    def broken(record, operation, payload):
        monitors = payload.get('owned_monitors', [])
        if operation == 'requirements' and monitors and monitors[0].get('height') == 720:
            new = deepcopy(record)
            new.update(revision=new['revision']+1, recommended_id=None, status='ACTIVE')
            return new
        return original(record, operation, payload)
    monkeypatch.setattr(cohort.workbench, 'mutate', broken)
    with patch.object(cohort.workbench, 'current_day', return_value=date(2026, 10, 19)):
        result = cohort.run_profile(profile, 'conflicting-inventory', date(2026, 10, 19))
    assert not result['all_checks_pass']
    failed = [s for s in result['steps'] if not all(s['checks'].values())]
    assert len(failed) == 1
    assert not failed[0]['checks']['support_matches_expected']


def test_unexpected_instruction_retains_failed_path_without_execution():
    _, profiles = cohort.load_protocol()
    profile = deepcopy(next(p for p in profiles if p['id'] == 'ines'))
    profile['script'].append({'kind': 'arbitrary-execution', 'intent': 'Invalid instruction must be retained as failure'})
    with patch.object(cohort.workbench, 'current_day', return_value=date(2026, 10, 19)):
        result = cohort.run_profile(profile, 'ordinary', date(2026, 10, 19))
    assert not result['all_checks_pass']
    assert 'Unknown bounded scenario instruction' in result['unexpected_error']
    assert result['steps'][-1]['checks'] == {'execution_completed': False}
    assert result['primary_step_count'] is None


def test_cohort_cli_does_not_overwrite_previous_reports(tmp_path, monkeypatch):
    output = tmp_path / 'existing.json'
    output.write_text('retained evidence')
    monkeypatch.setattr(sys, 'argv', ['rehearse_persona_cohort.py', '--as-of', '2026-10-19',
                        '--output', str(output), '--markdown', str(tmp_path/'new.md')])
    with pytest.raises(SystemExit) as error:
        cohort.main()
    assert error.value.code == 2
    assert output.read_text() == 'retained evidence'
    assert not (tmp_path/'new.md').exists()
