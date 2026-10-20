import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from intentcart import app as module, config, research


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(research, 'ROOT', tmp_path)
    path = tmp_path / 'intentcart/data'
    path.mkdir(parents=True)
    sources = {}
    for name in research.SOURCES['reliability']:
        source = tmp_path / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text('fixture source')
        sources[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    script = tmp_path / 'scripts/evaluate_reliability.py'
    report = {'schema': research.SCHEMAS['reliability'], 'source_sha256': sources,
              'cases': [{'id': 'control', 'trace': {'fixture': True}}],
              'mutations': [{'id': 'stale', 'shrunk_trace': {'fixture': 'reduced'}}]}
    target = path / 'reliability-evaluation.json'
    target.write_text(json.dumps(report))
    return target, script, report


def test_saved_evidence_rejects_stale_missing_or_unbound_sources(evidence):
    target, script, expected = evidence
    assert research.read_report('reliability') == expected
    script.write_text('changed implementation')
    with pytest.raises(research.EvidenceError, match='stale'):
        research.read_report('reliability')
    target.write_text(json.dumps({'source_sha256': {}}))
    with pytest.raises(research.EvidenceError, match='invalid'):
        research.read_report('reliability')
    target.unlink()
    with pytest.raises(research.EvidenceError, match='No saved result'):
        research.read_report('reliability')


def test_source_manifest_cannot_read_outside_release_root(evidence):
    target, _, report = evidence
    report['source_sha256']['../outside.py'] = 'unknown'
    target.write_text(json.dumps(report))
    with pytest.raises(research.EvidenceError):
        research.read_report('reliability')


def test_every_required_dependency_and_schema_must_be_bound(evidence):
    target, _, report = evidence
    saved = json.loads(json.dumps(report))
    del report['source_sha256']['intentcart/validity.py']
    target.write_text(json.dumps(report))
    with pytest.raises(research.EvidenceError):
        research.read_report('reliability')
    saved['schema'] = 'unknown-version'
    target.write_text(json.dumps(saved))
    with pytest.raises(research.EvidenceError):
        research.read_report('reliability')


def test_trace_selection_never_executes_input(evidence):
    report = research.read_report('reliability')
    assert research.exported_trace(report, 'control') == {'fixture': True}
    assert research.exported_trace(report, 'mutation-stale') == {'fixture': 'reduced'}
    with pytest.raises(research.EvidenceError):
        research.exported_trace(report, 'arbitrary')
    with pytest.raises(research.EvidenceError, match='malformed'):
        research.exported_trace({'cases': [{}]}, 'control')


def test_public_research_routes_do_not_create_orders_or_provider_calls(evidence, tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATABASE_PATH', str(tmp_path / 'app.sqlite3'))
    monkeypatch.setattr(config, 'CALL_LIMIT', 0)
    class UnavailableProvider:
        def __getattr__(self, name):
            raise AssertionError('Research must not invoke the payment provider')
    monkeypatch.setattr(module, 'provider', UnavailableProvider())
    module.RATES.clear()
    with TestClient(module.app) as client:
        assert client.get('/reliability').status_code == 200
        assert client.get('/api/research/reliability').status_code == 200
        result = client.get('/api/reliability/traces/control')
        assert result.status_code == 200
        assert result.headers['content-disposition'].endswith('intentcart-control.json"')
        assert client.post('/api/reliability/traces/control', json={}).status_code in (403, 405)
        assert client.get('/api/reliability/traces/not%20an%20id').status_code == 404
        assert client.get('/api/research/unrecognized').status_code == 422
        with module.database() as db:
            for table in ('orders', 'calls', 'sessions'):
                assert db.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


def test_mission_certificates_are_public_but_reuse_cache_stays_server_side(tmp_path, monkeypatch):
    from intentcart.missions import Goal
    monkeypatch.setattr(config, 'DATABASE_PATH', str(tmp_path / 'owned.sqlite3'))
    monkeypatch.setattr(config, 'CALL_LIMIT', 0)
    module.RATES.clear()
    with TestClient(module.app) as client:
        token = client.get('/api/session').json()['csrf_token']
        client.headers.update({'origin':config.PUBLIC_URL, 'x-csrf-token':token})
        response = client.post('/api/missions', json={'text':'A fixture workspace', 'goal':Goal().model_dump()})
        assert response.status_code == 200
        mission = response.json()
        assert mission['result']['validity']['claims']['feasibility']['status'] == 'verified'
        assert mission['result']['validity']['claims']['authorization']['consent_granted'] is False
        assert '_cache' not in response.text
        with module.database() as db:
            saved = json.loads(db.execute('SELECT state FROM sessions').fetchone()[0])
            assert saved['outcome']['validity']['_cache']
        changed = client.post('/api/missions/inspect', json={
            'revision':mission['revision'], 'source_id':'dock-mystery-protocol'})
        assert changed.status_code == 200
        assert '_cache' not in changed.text
        assert changed.json()['result']['validity']['work']['reused_candidates'] > 0
        for path in ('/api/missions', '/api/missions/export'):
            assert '_cache' not in client.get(path).text
        quote = client.post('/api/missions/quotes', json={'revision':changed.json()['revision']})
        assert quote.status_code == 200
        assert '_cache' not in quote.text
        with TestClient(module.app) as other:
            other.get('/api/session')
            assert other.get('/api/missions').json()['mission'] is None
            assert other.get('/api/missions/export').status_code == 409
