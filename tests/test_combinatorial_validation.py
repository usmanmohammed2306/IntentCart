from copy import deepcopy
from datetime import date
import gzip
import hashlib
from itertools import product
import json
import socket
from unittest.mock import patch

import pytest
from scripts import combination_fixture as fixture
from scripts import validate_matrix as matrix
from scripts import validate_state_sequences as sequences
from scripts import validate_persona_sequences as personas
from scripts import validate_api_matrix as api
from scripts import audit_combinations as audit

DAY = date(2026, 10, 19)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Validation test attempted network access')
    monkeypatch.setattr(socket, 'create_connection', denied)


def test_mixed_radix_indices_exhaustively_decode_the_declared_input_space():
    # This is generation/coverage verification, not a second execution of SUT.
    for index, values in enumerate(product(*fixture.AXES.values())):
        assert fixture.case_from_id(index) == dict(zip(fixture.AXES, values))
    assert index+1 == fixture.TOTAL_CASES == 196608
    assert matrix.projections(2) == 576
    assert matrix.projections(3) == 5920
    with pytest.raises(ValueError):
        fixture.case_from_id(-1)


def test_independent_matrix_oracle_includes_valid_and_invalid_cases():
    rows = []
    result = matrix.evaluate(DAY, limit=1536, emit=rows.append)
    assert result['all_checks_pass']
    assert 0 < result['expected_supported'] < result['cases']
    assert not result['complete_cartesian_enumeration']
    assert result['projection_coverage']['pair_assignments'] is None
    assert len(rows) == 1536
    # Exercise demanding valid positive configurations as well as boundary failure.
    with patch.object(fixture.workbench, 'current_day', return_value=DAY):
        for changes in ({}, {'protocol':'usb-c','allow_driver':False},
                        {'displays':3,'height':2160,'hz':120}, {'budget_gap_cents':-1}):
            case = fixture.positive_case(**changes)
            state = fixture.case_record(fixture.imported_record(case, DAY), case, DAY)
            assert bool(fixture.workbench.rank(state)) == fixture.expected_support(case)


def test_oracle_detects_always_accepting_rank_instead_of_grading_itself(monkeypatch):
    monkeypatch.setattr(matrix.workbench, 'rank', lambda record: [{'items': [], 'total_cents': fixture.subtotal(record['goal']['displays'])}])
    result = matrix.evaluate(DAY, limit=3)
    assert not result['all_checks_pass']
    assert result['false_acceptances'] == 3


def test_review_and_recovery_permutations_detect_declared_faults():
    result = sequences.evaluate(DAY, order_limit=24, review_limit=240)
    assert result['all_checks_pass']
    assert not result['complete_event_orders'] and result['complete_review_orders']
    assert result['boundary_cases'] == 576
    assert result['detected_faults'] == result['seeded_faults'] == 11
    assert result['noop_false_alarms'] == 0


def test_old_proposal_acceptance_mutant_is_detected_by_review_state_machine(monkeypatch):
    original = sequences.workbench.mutate
    def accept_any_pending(record, operation, payload):
        if operation == 'accept_source' and record.get('workbench',{}).get('pending_source'):
            payload = {**payload,'proposal_id':record['workbench']['pending_source']['id']}
        return original(record,operation,payload)
    with patch.object(sequences.workbench, 'current_day', return_value=DAY):
        base = sequences.initial(DAY)
        monkeypatch.setattr(sequences.workbench,'mutate',accept_any_pending)
        result = sequences.review_sequence(base,2,('propose_low','propose_high','accept_low','accept_high','inspect'))
    assert not result['all_checks_pass']
    assert any(not step['checks']['acceptance_matches_review_state_machine'] for step in result['steps'])


def test_disruption_language_includes_all_triples_and_repeats():
    words = list(personas.words())
    assert len(words) == len(set(words)) == 40
    assert set(word for word in words if len(word)==3) == set(product(personas.EVENTS,repeat=3))
    assert ('late-cost-ambiguity',)*3 in words
    _, profiles = personas.load_protocol()
    profile = next(p for p in profiles if p['id']=='felix')
    with patch.object(personas.workbench,'current_day',return_value=DAY):
        result = personas.run_word(profile,('late-cost-ambiguity','conflicting-inventory','late-cost-ambiguity'),DAY)
    assert result['all_checks_pass']
    assert len(result['scripted_decisions']) == 3


def test_actual_api_guard_matrix_preserves_durable_state():
    result = api.evaluate(DAY)
    assert result['all_checks_pass']
    assert result['matrix_cases'] == 243 and result['duplicate_revision_cases'] == 1
    assert result['blocked_network_attempts'] == result['blocked_provider_attempts'] == 0
    assert audit.audit_api(result)['statuses'] == {'200':1,'409':6,'422':54,'403':174,'401':9}
    assert 'csrf_token' not in json.dumps(result)


def write_trace(tmp_path, rows):
    trace = tmp_path/'cases.jsonl.gz'
    with gzip.open(trace,'wt') as stream:
        for row in rows:
            stream.write(json.dumps(row)+'\n')
    return {'filename':trace.name,'sha256':hashlib.sha256(trace.read_bytes()).hexdigest()}


def test_saved_trace_audit_rejects_missing_duplicate_and_tampered_input(tmp_path):
    rows = []
    report = matrix.evaluate(DAY,limit=12,emit=rows.append)
    report['trace'] = write_trace(tmp_path,rows)
    assert audit.audit_matrix(report,tmp_path)['cases'] == 12
    for changed in (rows[:-1], rows[:5]+[deepcopy(rows[4])]+rows[6:]):
        report['trace'] = write_trace(tmp_path,changed)
        with pytest.raises(ValueError):
            audit.audit_matrix(report,tmp_path)
    tampered = deepcopy(rows)
    tampered[0]['case']['costs_known'] = not tampered[0]['case']['costs_known']
    report['trace'] = write_trace(tmp_path,tampered)
    with pytest.raises(ValueError,match='does not decode'):
        audit.audit_matrix(report,tmp_path)


def test_audit_requires_real_boolean_success_and_complete_source_manifest(tmp_path):
    assert not audit.all_true({'guard':'false'})
    assert not audit.all_true({})
    rows=[]
    report=matrix.evaluate(DAY,limit=1,emit=rows.append)
    report['trace']=write_trace(tmp_path,rows)
    report['sources']={}
    with pytest.raises(ValueError,match='sources changed'):
        audit.audit_matrix(report,tmp_path)
