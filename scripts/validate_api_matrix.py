"""In-process ASGI authorization/revision combinations with disposable storage."""
import argparse
from contextlib import ExitStack
from datetime import date
import hashlib
from itertools import product
import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from fastapi.testclient import TestClient
from intentcart import app as module, config, workbench
from scripts.validate_matrix import source_hashes

DOMAINS = {'session': ['owner', 'other', 'missing'], 'origin': ['valid', 'wrong', 'missing'],
           'csrf': ['valid', 'wrong', 'missing'], 'revision': ['current', 'stale', 'future'],
           'body': ['valid', 'wrong_type', 'extra_field']}


def expected_status(case):
    if case['origin'] != 'valid':
        return 403
    if case['body'] != 'valid':
        return 422
    if case['session'] == 'missing':
        return 401
    if case['csrf'] != 'valid':
        return 403
    if case['session'] == 'other' or case['revision'] != 'current':
        return 409
    return 200


def evaluate(as_of):
    network_attempts = []
    provider_attempts = []
    rows = []
    def deny_network(*args, **kwargs):
        network_attempts.append('blocked')
        raise AssertionError('External network is forbidden in this local API matrix.')
    def deny_provider(*args, **kwargs):
        provider_attempts.append('blocked')
        raise AssertionError('Provider construction is forbidden in this local API matrix.')
    with tempfile.TemporaryDirectory(prefix='intentcart-api-matrix-') as directory, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'DATABASE_PATH', str(Path(directory)/'state.sqlite3')))
        stack.enter_context(patch.object(config, 'PUBLIC_URL', 'http://testserver'))
        stack.enter_context(patch.object(config, 'COOKIE_SECURE', False))
        stack.enter_context(patch.object(config, 'CALL_LIMIT', 0))
        stack.enter_context(patch.object(workbench, 'current_day', return_value=as_of))
        stack.enter_context(patch.object(module, 'provider', deny_provider))
        stack.enter_context(patch.object(socket, 'create_connection', deny_network))
        stack.enter_context(patch.object(httpx.HTTPTransport, 'handle_request', deny_network))
        module.RATES.clear()
        owner = stack.enter_context(TestClient(module.app))
        other = stack.enter_context(TestClient(module.app))
        missing = stack.enter_context(TestClient(module.app))
        sessions = {label: client.get('/api/session').json() for label, client in (('owner', owner), ('other', other))}
        good_headers = {'origin': config.PUBLIC_URL, 'x-csrf-token': sessions['owner']['csrf_token']}
        created = owner.post('/api/agent', json={'goal': {'budget_cents': 40000}, 'scenario_confirmed': True}, headers=good_headers)
        created.raise_for_status()
        # Advance to revision >=2 so a stale revision is valid schema input.
        warmup = owner.post('/api/agent/workbench', json={'revision': created.json()['revision'],
                           'operation': 'requirements', 'payload': {'tax_cents': 0}}, headers=good_headers)
        warmup.raise_for_status()
        token = owner.cookies.get('intentcart_session')
        owner_id = hashlib.sha256(token.encode()).hexdigest()
        def stored():
            with module.database() as db:
                value = db.execute('SELECT state FROM sessions WHERE id=?', (owner_id,)).fetchone()['state']
            return json.loads(value), hashlib.sha256(value.encode()).hexdigest()
        for index, values in enumerate(product(*DOMAINS.values())):
            case = dict(zip(DOMAINS, values))
            client = {'owner': owner, 'other': other, 'missing': missing}[case['session']]
            before, before_hash = stored()
            revision = before['evidence_agent']['revision']
            revision += {'current': 0, 'stale': -1, 'future': 1}[case['revision']]
            body = {'revision': revision, 'operation': 'requirements', 'payload': {'tax_cents': 0}}
            if case['body'] == 'wrong_type':
                body['revision'] = str(revision)
            if case['body'] == 'extra_field':
                body['authority'] = 'fictional-unrecognized-field'
            headers = {}
            if case['origin'] != 'missing':
                headers['origin'] = config.PUBLIC_URL if case['origin'] == 'valid' else 'https://fictional.invalid'
            if case['csrf'] != 'missing':
                valid_token = sessions.get(case['session'], sessions['owner'])['csrf_token']
                headers['x-csrf-token'] = valid_token if case['csrf'] == 'valid' else 'fictional-wrong-token'
            # This suite isolates auth/revision guards. Rate limiting is not under test.
            module.RATES.clear()
            response = client.post('/api/agent/workbench', json=body, headers=headers)
            after, after_hash = stored()
            expected = expected_status(case)
            success = expected == 200
            checks = {'status_matches_guard_precedence': response.status_code == expected,
                      'durable_owner_state_matches_authority': (after_hash != before_hash) == success,
                      'revision_matches_authority': after['evidence_agent']['revision'] == before['evidence_agent']['revision'] + int(success)}
            rows.append({'suite': 'api_guard_matrix', 'id': index, 'case': case,
                         'expected_status': expected, 'observed_status': response.status_code,
                         'owner_before_sha256': before_hash, 'owner_after_sha256': after_hash,
                         'checks': checks, 'all_checks_pass': all(checks.values())})
            if success:
                module.RATES.clear()
                replay = client.post('/api/agent/workbench', json=body, headers=headers)
                replay_state, replay_hash = stored()
                checks = {'duplicate_revision_rejected': replay.status_code == 409,
                          'duplicate_does_not_mutate_durable_state': replay_hash == after_hash,
                          'duplicate_does_not_advance_revision': replay_state['evidence_agent']['revision'] == after['evidence_agent']['revision']}
                rows.append({'suite': 'api_duplicate_revision', 'observed_status': replay.status_code,
                             'checks': checks, 'all_checks_pass': all(checks.values())})
        module.RATES.clear()
    statuses = {}
    for row in rows:
        key = str(row['observed_status'])
        statuses[key] = statuses.get(key, 0)+1
    return {'schema': 'intentcart-api-guard-matrix/1', 'snapshot_date': as_of.isoformat(),
            'evidence_class': 'local_asgi_api_validation', 'domains': DOMAINS,
            'matrix_cases': sum(row['suite'] == 'api_guard_matrix' for row in rows),
            'duplicate_revision_cases': sum(row['suite'] == 'api_duplicate_revision' for row in rows),
            'status_counts': statuses, 'failed_records': sum(not row['all_checks_pass'] for row in rows),
            'blocked_network_attempts': len(network_attempts), 'blocked_provider_attempts': len(provider_attempts),
            'provider_requests': 0, 'payment_operations': 0, 'human_participants': 0,
            'all_checks_pass': all(row['all_checks_pass'] for row in rows) and not network_attempts and not provider_attempts,
            'records': rows,
            'sources': source_hashes(['scripts/validate_api_matrix.py', 'intentcart/app.py',
                                     'intentcart/agent_routes.py', 'intentcart/workbench_routes.py', 'intentcart/config.py']),
            'limits': ['In-process TestClient requests against actual routes; disposable SQLite storage, no socket server.',
                       'Five three-level axes, 243 combinations and one duplicate-revision case; not arbitrary endpoint coverage.',
                       'Rate buckets are cleared between cases to isolate these guards; rate limiting is not measured here.',
                       'Cookie/CSRF values never appear in the artifact; only labels and synthetic durable-state hashes.',
                       'Does not establish multi-process concurrency, browser UX, production authentication or real payment behavior.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output path; preserve previous evidence.')
    report = evaluate(args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as out:
        out.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('matrix_cases','duplicate_revision_cases','failed_records','status_counts','all_checks_pass')}))
    return 0 if report['all_checks_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
