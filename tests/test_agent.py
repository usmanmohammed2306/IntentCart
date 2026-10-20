import copy
import json
import pytest
from fastapi.testclient import TestClient
from intentcart import agent, evidence_catalog, app as module, config, gateway, workspace_preferences
from intentcart import missions, validity

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATABASE_PATH', str(tmp_path / 'agent.sqlite3'))
    monkeypatch.setattr(config, 'CALL_LIMIT', 0)
    def forbidden_provider():
        raise AssertionError('Agent tests cannot dispatch a payment provider.')
    monkeypatch.setattr(module, 'provider', forbidden_provider)
    module.RATES.clear()
    with TestClient(module.app) as c:
        session = c.get('/api/session').json()
        c.headers.update({'origin': config.PUBLIC_URL, 'x-csrf-token': session['csrf_token']})
        yield c

def finish(record, policy='targeted', permission=True):
    for _ in range(30):
        if record['pending_question']:
            record = agent.answer(record, permission)
        if record['status'] != 'ACTIVE':
            return record
        record = agent.step(record, agent.local_action(record, policy))
    pytest.fail('Agent did not stop within its bound.')

def test_curated_supported_journey_and_permission_are_separate():
    record = finish(agent.create('Two displays', {}, scenario_confirmed=True))
    assert record['status'] == 'RECOMMENDED'
    assert record['goal']['allow_driver'] is True
    assert agent.view(record)['result']['plan']['total_cents'] == 34999
    assert len(record['inspected']) == 13
    assert any(e['origin'] == 'human' for e in record['events'])
    assert agent.view(record)['checkout_supported'] is False
    assert all(f['status'] == 'supported_curated_record' for f in agent.view(record)['result']['plan']['facts'].values())

def test_permission_denial_defers_and_no_budget_exceeds_limit():
    denied = finish(agent.create('', {}, scenario_confirmed=True), permission=False)
    assert denied['status'] == 'DEFERRED' and denied['goal']['allow_driver'] is False
    stopped = finish(agent.create('', {}, inspection_budget=2, scenario_confirmed=True))
    assert stopped['status'] == 'BUDGET_STOP' and len(stopped['inspected']) == 2

def test_recommendation_requires_explicit_scenario_review():
    record = agent.create('', {}, scenario_confirmed=False)
    for _ in range(24):
        if record['pending_question']: record = agent.answer(record, True)
        action = agent.local_action(record)
        if action.action == 'recommend': break
        record = agent.step(record, action)
    with pytest.raises(agent.AgentError, match='Confirm'):
        agent.step(record, action)
    reviewed = agent.revise(record, scenario_confirmed=True)
    assert agent.step(reviewed, agent.local_action(reviewed))['status'] == 'RECOMMENDED'

@pytest.mark.parametrize('payload', [
    {'action': 'pay'}, {'action': 'inspect', 'facts': {'displays': 99}},
    {'action': 'clarify', 'allow_driver': True}, {'action': 'search', 'reason': 'x' * 401}])
def test_model_action_schema_has_no_authority_escape(payload):
    with pytest.raises(ValueError): agent.Action.model_validate(payload)

def test_unknown_undiscovered_and_repeated_sources_rejected():
    r = agent.create('', {})
    sid = 'plugable-ud6950pdh-protocol'
    with pytest.raises(agent.AgentError): agent.step(r, {'action': 'inspect', 'target': sid})
    r = agent.step(r, {'action': 'search'})
    with pytest.raises(agent.AgentError): agent.step(r, {'action': 'inspect', 'target': 'invented'})
    r = agent.step(r, {'action': 'inspect', 'target': sid})
    with pytest.raises(agent.AgentError): agent.step(r, {'action': 'inspect', 'target': sid})
    with pytest.raises(agent.AgentError): agent.step(r, {'action': 'recommend', 'target': 'fabricated'})

def test_revision_clears_recommendation_and_stock_change_defers():
    r = finish(agent.create('', {}, scenario_confirmed=True))
    changed = agent.revise(r, exclude='plugable-ud6950pdh')
    assert changed['recommended_id'] is None and changed['previous_items']
    assert finish(changed)['status'] == 'DEFERRED'
    revised = agent.revise(r, goal={**r['goal'], 'height': 2160})
    assert agent.solve(revised)['plan'] is None

def test_human_edits_cannot_reset_tool_cap_or_grow_unbounded_history():
    r = agent.create('', {})
    for _ in range(agent.MAX_STEPS):
        r = agent.step(r, {'action': 'search'})
    for _ in range(55):
        r = agent.revise(r, scenario_confirmed=True)
    assert r['tool_count'] == agent.MAX_STEPS and len(r['events']) == 48
    assert len({e['index'] for e in r['events']}) == 48
    assert agent.view(r)['steps_remaining'] == 0
    assert agent.step(r, {'action': 'search'})['status'] == 'STEP_STOP'

def test_stale_catalog_is_rejected(monkeypatch):
    r = agent.create('', {})
    original = agent.catalog_for
    def changed(kind):
        cat = original(kind)
        cat['products'][0]['price_cents'] += 1
        return cat
    monkeypatch.setattr(agent, 'catalog_for', changed)
    with pytest.raises(agent.AgentError, match='changed'): agent.view(r)

@pytest.mark.parametrize('field,value', [('variant', 'other'), ('unit', 'Hz'), ('url', 'http://example.com')])
def test_catalog_rejects_wrong_variant_units_or_origin(field, value):
    c = evidence_catalog.load_catalog()
    c['sources']['plugable-ud6950pdh-protocol'][field] = value
    with pytest.raises(ValueError): evidence_catalog.validate_catalog(c)

def test_model_context_contains_only_observed_values():
    r = agent.create('', {})
    r = agent.step(r, {'action': 'search'})
    content = json.loads(agent.model_body(r, 'test-model')['messages'][1]['content'])
    assert content['evidence'] == [] and content['plan'] is None
    assert all(set(s) == {'id', 'product_id', 'field'} for s in content['available_sources'])

def test_import_rejects_boolean_as_display_count():
    c = evidence_catalog.load_catalog()
    observation = next(o for o in c['products'][0]['observations'] if o['field'] == 'displays')
    observation['value'] = True
    c['sources'][observation['source_id']]['value'] = True
    with pytest.raises(ValueError, match='bounded integer'):
        evidence_catalog.validate_catalog(c)

def test_owned_endpoints_revision_csrf_and_no_order(client):
    created = client.post('/api/agent', json={'goal': {}, 'scenario_confirmed': True}).json()
    assert created['revision'] == 1
    assert client.post('/api/agent/step', json={'revision': 99}).status_code == 409
    assert client.post('/api/agent/step', json={'revision': 1}, headers={'x-csrf-token': ''}).status_code == 403
    assert client.post('/api/agent/step', json={'revision': 1}).status_code == 200
    assert client.get('/api/agent/export').headers['content-disposition'].startswith('attachment')
    assert client.post('/api/agent/model-step', json={'revision': 2}).status_code == 409
    assert client.get('/api/orders').json() == []
    with module.database() as db:
        assert db.execute("SELECT COUNT(*) FROM calls WHERE name='astro'").fetchone()[0] == 0

def test_session_isolation(client):
    client.post('/api/agent', json={'goal': {}})
    with TestClient(module.app) as other:
        other.get('/api/session')
        assert other.get('/api/agent').json()['task'] is None
        assert other.get('/api/agent/export').status_code == 409

def enable(monkeypatch):
    for key, value in {'CALL_LIMIT': 3, 'ASTRO_URL': 'https://gateway.example', 'ASTRO_KEY': 'fake-only',
                       'ASTRO_CREDIT_ONLY': True, 'ASTRO_BUDGET': 1000000,
                       'ASTRO_INPUT_RATE': 1000000, 'ASTRO_OUTPUT_RATE': 1000000}.items():
        monkeypatch.setattr(config, key, value)

def test_fake_model_reserves_before_dispatch_and_strictly_applies(client, monkeypatch):
    enable(monkeypatch)
    client.post('/api/agent', json={'goal': {}})
    def fake(*args):
        with module.database() as db:
            assert db.execute("SELECT count FROM calls WHERE name='astro'").fetchone()[0] == 1
        return {'choices': [{'message': {'content': '{"action":"search"}'}}], 'usage': {'total_tokens': 20}}
    monkeypatch.setattr(gateway, 'raw_call', fake)
    response = client.post('/api/agent/model-step', json={'revision': 1})
    assert response.status_code == 200, response.text
    assert response.json()['mode'] == 'model-proposed validated tool action'
    assert response.json()['usage'] == {'total_tokens': 20}

def test_fake_model_failure_retains_reservation_and_no_task_change(client, monkeypatch):
    enable(monkeypatch)
    client.post('/api/agent', json={'goal': {}})
    monkeypatch.setattr(gateway, 'raw_call', lambda *a: {'choices': [{'message': {'content': '{"action":"pay"}'}}]})
    assert client.post('/api/agent/model-step', json={'revision': 1}).status_code == 502
    assert client.get('/api/agent').json()['task']['revision'] == 1
    with module.database() as db:
        assert db.execute("SELECT count FROM calls WHERE name='astro'").fetchone()[0] == 1

def test_stale_model_reply_cannot_overwrite_concurrent_human_change(client, monkeypatch):
    enable(monkeypatch)
    client.post('/api/agent', json={'goal': {}})
    def fake(*args):
        response = client.post('/api/agent/revise', json={'revision': 1, 'scenario_confirmed': True})
        assert response.status_code == 200
        return {'choices': [{'message': {'content': '{"action":"search"}'}}]}
    monkeypatch.setattr(gateway, 'raw_call', fake)
    assert client.post('/api/agent/model-step', json={'revision': 1}).status_code == 409
    assert client.get('/api/agent').json()['task']['discovered'] == []

def test_preferences_skip_neutral_and_choice_updates_only_valid_ranking():
    r = finish(agent.create('', {'allow_driver': True, 'budget_cents': 80000}, 'fixture'))
    choices = agent.view(r)['comparisons']
    assert len(choices) >= 2
    a, b = choices[0]['id'], choices[1]['id']
    skipped = agent.compare(r, a, b, 'skip')
    assert agent.view(skipped)['preference_weights'] == agent.view(r)['preference_weights']
    assert agent.solve(skipped)['plan']['id'] == agent.solve(r)['plan']['id']
    changed = agent.compare(r, a, b, 'a')
    assert changed['recommended_id'] is None and changed['personalized']
    assert agent.solve(changed)['plan']['valid']
    with pytest.raises(agent.AgentError): agent.compare(r, a, 'invented', 'b')

def test_mission_preferences_bind_selected_basket_certificate_and_quote(client):
    goal = missions.Goal(allow_driver=True, budget_cents=80000).model_dump()
    record = client.post('/api/missions', json={'text': 'A reviewed workstation', 'goal': goal}).json()
    choices = record['result']['preference_choices']
    assert len(choices) >= 2
    quote = client.post('/api/missions/quotes', json={'revision': record['revision']}).json()
    changed = client.post('/api/missions/preference', json={'revision': record['revision'],
        'a': choices[0]['id'], 'b': choices[-1]['id'], 'choice': 'b'})
    assert changed.status_code == 200, changed.text
    new = changed.json()
    cert = new['result']['validity']
    assert cert['claims']['feasibility']['basket_id'] == new['result']['plan']['id']
    assert cert['claims']['optimality']['status'] == 'unresolved'
    assert cert['claims']['authorization']['consent_granted'] is False
    public = {k: v for k, v in cert.items() if k != 'certificate_sha256'}
    assert validity.digest(public) == cert['certificate_sha256']
    assert client.post('/api/paypal/create', json={'quote_id': quote['id'], 'approved': True}).status_code == 409
    fresh = client.post('/api/missions/quotes', json={'revision': new['revision']})
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()['basket'] == new['result']['plan']['items']

def test_mission_skip_does_not_change_selected_plan():
    r = missions.create('', missions.Goal(allow_driver=True, budget_cents=80000))
    choices = r['result']['preference_choices']
    skipped = missions.prefer(r, choices[0]['id'], choices[1]['id'], 'skip')
    assert skipped['result']['plan']['id'] == r['result']['plan']['id']
    assert skipped['result']['validity']['claims']['optimality']['status'] == r['result']['validity']['claims']['optimality']['status']

def test_human_refresh_tradeoff_can_select_a_costlier_valid_basket():
    r = missions.create('', missions.Goal())
    choices = r['result']['preference_choices']
    pro = next(c for c in choices if c['total_cents'] == 32900)
    changed = missions.prefer(r, choices[0]['id'], pro['id'], 'b')
    assert changed['result']['plan']['total_cents'] == 32900
    assert changed['result']['plan']['valid']
    assert changed['result']['validity']['claims']['authorization']['consent_granted'] is False
