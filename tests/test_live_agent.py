import json
import pytest
import httpx
from fastapi.testclient import TestClient
from intentcart import agent, app as module, config, gateway
from scripts.evaluate_live_agent import run

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATABASE_PATH', str(tmp_path / 'pilot.sqlite3'))
    for key, value in {'CALL_LIMIT': 8, 'ASTRO_URL': 'https://gateway.example', 'ASTRO_KEY': 'fake-only',
                       'ASTRO_CREDIT_ONLY': True, 'ASTRO_BUDGET': 1000000,
                       'ASTRO_INPUT_RATE': 1000000, 'ASTRO_OUTPUT_RATE': 1000000,
                       'ASTRO_MODEL': 'fixture-model'}.items():
        monkeypatch.setattr(config, key, value)
    module.RATES.clear()
    with TestClient(module.app) as c:
        yield c

def task():
    return {'id': 'fixture-native', 'query': 'Authored evaluation task', 'goal': {},
            'catalog_kind': 'fixture', 'inspection_budget': 16, 'driver_answer': False}

def test_guided_hint_is_only_added_context_and_has_no_hidden_truth():
    r = agent.create('', {}, 'fixture')
    direct = agent.model_body(r, 'fixture-model', 'direct')
    guided = agent.model_body(r, 'fixture-model', 'guided')
    assert direct['messages'][0] == guided['messages'][0]
    d = json.loads(direct['messages'][1]['content'])
    g = json.loads(guided['messages'][1]['content'])
    assert g.pop('advisory_next_action')['action'] == 'search'
    assert g == d and d['evidence'] == []

def test_fake_matched_run_retains_cap_and_identical_model(client, monkeypatch):
    def fake(url, key, body):
        context = json.loads(body['messages'][1]['content'])
        action = {'action': 'search'} if not context['products'] else {'action': 'recommend', 'target': context['plan']['id']}
        return {'model': 'fixture-model', 'choices': [{'message': {'content': json.dumps(action)}}], 'usage': {'total_tokens': 30}}
    monkeypatch.setattr(gateway, 'raw_call', fake)
    report = run(client, [task()], 2, 'fixture-model', config.PUBLIC_URL)
    assert report['request_attempts'] == 2
    assert report['records'][0]['supported_recommendation']
    assert report['records'][1]['status'] == 'INCOMPLETE_REQUEST_CAP'
    assert report['records'][0]['model_ids'] == ['fixture-model', 'fixture-model']
    assert all(a['model_id_basis'] == 'provider_response' for a in report['records'][0]['attempts'])

def test_disabled_pilot_and_bad_ceiling_send_no_provider_call(client, monkeypatch):
    monkeypatch.setattr(config, 'CALL_LIMIT', 0)
    def forbidden(*args): raise AssertionError('Disabled pilot cannot dispatch.')
    monkeypatch.setattr(gateway, 'raw_call', forbidden)
    report = run(client, [task()], 2, 'fixture-model', config.PUBLIC_URL)
    assert report['request_attempts'] == 0 and report['records'][0]['status'] == 'START_ERROR'
    with pytest.raises(ValueError, match='ceiling'):
        run(client, [task()], 0, 'fixture-model', config.PUBLIC_URL)

def test_uncertain_transport_retained_without_retry(client):
    class Interrupted:
        cookies = client.cookies
        get = client.get
        def post(self, path, **kwargs):
            if path == '/api/agent/model-step':
                raise httpx.ReadTimeout('Simulated local transport interruption.')
            return client.post(path, **kwargs)
    report = run(Interrupted(), [task()], 3, 'fixture-model', config.PUBLIC_URL)
    assert report['request_attempts'] == 1
    assert report['records'][0]['status'] == 'ERROR'
    assert report['records'][0]['attempts'][0]['uncertain_transport'] is True
    assert report['records'][1]['status'] == 'UNATTEMPTED_AFTER_STOP'
