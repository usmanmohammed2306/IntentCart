import copy
import json
import pytest
from fastapi.testclient import TestClient
from intentcart import app as module, config, study
from scripts.analyze_pilot import aggregate

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATABASE_PATH', str(tmp_path/'pilot.sqlite3'))
    module.RATES.clear()
    with TestClient(module.app) as client:
        token = client.get('/api/session').json()['csrf_token']
        client.headers.update({'origin': config.PUBLIC_URL, 'x-csrf-token': token})
        yield client

@pytest.mark.parametrize('policy', study.POLICIES)
def test_consent_blinding_holdout_nonleakage_survey_and_withdrawal(client, monkeypatch, policy):
    original = study.create
    monkeypatch.setattr(study, 'create', lambda products: {**original(products), 'policy': policy})
    assert client.post('/api/study/start', json={'consent': False}).status_code == 422
    assert client.get('/api/study').json()['study'] is None
    state_before = client.get('/api/session').json()['state']
    view = client.post('/api/study/start', json={'consent': True}).json()
    assert client.post('/api/study/start', json={'consent': True}).json()['id'] == view['id']
    first = copy.deepcopy(view)
    for _ in range(16):
        if view['phase'] == 'review':
            break
        assert 'policy' not in view and 'product' not in view and 'ranked' not in view
        previous = view['revision']
        response = client.post('/api/study/answer', json={'revision': previous, 'choice': 'a'})
        assert response.status_code == 200
        view = response.json()
        assert client.post('/api/study/answer', json={'revision': previous, 'choice': 'a'}).status_code == 409
    assert view['phase'] == 'review'
    record = client.get('/api/study/export').json()
    assert len(record['before']) == len(record['after']) == 4
    assert {tuple(sorted(pair)) for pair in record['before_pairs']} == {tuple(sorted(pair)) for pair in record['after_pairs']}
    assert not {tuple(sorted(pair)) for pair in record['before_pairs']}.intersection(tuple(sorted((a, b))) for a, b, _ in record['history'])
    assert len(record['history']) <= 4
    survey = {'revision': view['revision'], 'product_id': 'none', 'burden': 3,
              'total_cents': 0, 'approval_understood': False}
    result = client.post('/api/study/finish', json=survey)
    assert result.status_code == 200 and not result.json()['survey']['correct_total']
    assert client.get('/api/orders').json() == []
    assert client.get('/api/session').json()['state'] == state_before
    assert client.delete('/api/study').json()['deleted']
    assert client.get('/api/study/export').status_code == 404
    assert client.get('/api/study').json()['study'] is None

def test_study_ownership_csrf_and_premature_survey(client):
    client.post('/api/study/start', json={'consent': True})
    assert client.delete('/api/study', headers={'x-csrf-token': 'wrong'}).status_code == 403
    assert client.post('/api/study/finish', json={'revision': 0, 'product_id': 'none', 'burden': 1, 'total_cents': 0, 'approval_understood': True}).status_code == 409
    with TestClient(module.app) as other:
        other.get('/api/session')
        assert other.get('/api/study/export').status_code == 404

def test_adaptive_decision_is_advice_not_payment_authority(client):
    mission = {'text': 'comfortable rain commuter', 'budget_cents': 9000, 'laptop_inches': 14, 'min_capacity_l': 0, 'adaptive': True}
    response = client.post('/api/mission', json=mission)
    assert response.status_code == 200
    state = response.json()
    assert state['decision']['action'] in ('ASK', 'RECOMMEND', 'DEFER')
    quote = client.post('/api/quotes', json={'version': state['version'], 'product_id': state['ranked'][0]['id']}).json()
    assert quote['decision_snapshot']['decision_controller']['model_only']
    assert client.post('/api/paypal/create', json={'quote_id': quote['id'], 'approved': False}).status_code == 422
    assert client.get('/api/orders').json() == []
    state = client.post('/api/scenario', json={'kind': 'no_purchase', 'version': state['version']}).json()
    assert state['decision']['action'] == 'DEFER' and not state['ranked']

def test_robustness_summary_is_source_bound(client, monkeypatch):
    response = client.get('/api/robustness')
    assert response.status_code == 200
    assert response.json()['personas'] == 280 and 'records' not in response.json()
    monkeypatch.setitem(module.DECISION_CONFIG, 'decay', .123)
    assert client.get('/api/robustness').status_code == 409

def test_stale_pilot_cannot_mix_revisions_but_can_export_and_withdraw(client):
    client.post('/api/study/start', json={'consent': True})
    with module.database() as db:
        row = db.execute('SELECT owner,data FROM studies').fetchone()
        record = json.loads(row['data'])
        record['source_sha256']['study.py'] = 'stale'
        db.execute('UPDATE studies SET data=? WHERE owner=?', (json.dumps(record), row['owner']))
    assert client.get('/api/study').status_code == 409
    assert client.get('/api/study/export').status_code == 200
    assert client.delete('/api/study').status_code == 200

def test_pilot_aggregate_empty_and_incomplete_records_are_not_people(client):
    empty = aggregate([], module.CATALOG)
    assert empty['assigned_records'] == 0
    client.post('/api/study/start', json={'consent': True})
    record = client.get('/api/study/export').json()
    result = aggregate([record], module.CATALOG)
    assert result['assigned_records'] == 1
    assert result['policies'][record['policy']]['incomplete'] == 1
    assert all(p['complete'] == 0 for p in result['policies'].values())
