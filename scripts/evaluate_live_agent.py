"""Explicit, gated matched-model pilot. Default is a no-network dry run.

Uses authored public tasks and fresh owned sessions, never existing cookies or
payments. Server durable reservations enforce the operator-approved allowance.
Failed, capped and incomplete trials remain outcomes, not successful samples.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import httpx
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import agent
from scripts.evaluate_agent import grader_catalog
from scripts import missions_oracle as oracle

def run(client, tasks, max_requests, expected_model, base_url, controllers=('direct', 'guided')):
    if type(max_requests) is not int or not 1 <= max_requests <= 48:
        raise ValueError('Choose an explicit 1..48 request ceiling.')
    if not expected_model or len(expected_model) > 100:
        raise ValueError('Specify the operator-reviewed model ID.')
    if not 1 <= len(tasks) <= 6:
        raise ValueError('Choose one to six authored tasks.')
    records, requests, stop = [], 0, False
    for task in tasks:
        for controller in controllers:
            if stop:
                records.append({'task_id': task['id'], 'controller': controller, 'status': 'UNATTEMPTED_AFTER_STOP', 'attempts': []})
                continue
            # A new session for each trial; existing user sessions are never reused.
            client.cookies.clear()
            try:
                session = client.get('/api/session')
                session.raise_for_status()
                headers = {'Origin': base_url, 'X-CSRF-Token': session.json()['csrf_token']}
                status = client.get('/api/agent').json()
                if not status.get('model_enabled'):
                    raise ValueError('Server inference is disabled. No provider call sent.')
                start = client.post('/api/agent', headers=headers, json={'query': task['query'], 'goal': task['goal'],
                    'catalog_kind': task['catalog_kind'], 'inspection_budget': task['inspection_budget'], 'scenario_confirmed': True})
                start.raise_for_status()
                current = start.json()
                if current['source_sha256'] != agent.source_identity(task['catalog_kind']):
                    raise ValueError('Server source differs from this evaluator.')
            except (ValueError, httpx.HTTPError, KeyError, TypeError) as exc:
                records.append({'task_id': task['id'], 'controller': controller, 'status': 'START_ERROR',
                                'attempts': [], 'errors': [str(exc)[:400]]})
                stop = True
                continue
            attempts, errors, models = [], [], []
            while current['status'] == 'ACTIVE' or current['pending_question']:
                if current['pending_question']:
                    try:
                        answer = client.post('/api/agent/answer', headers=headers,
                            json={'revision': current['revision'], 'allow_driver': task['driver_answer']})
                        answer.raise_for_status()
                        current = answer.json()
                    except (ValueError, httpx.HTTPError, KeyError, TypeError):
                        errors.append('Scripted answer transport failed; no retry.')
                        stop = True
                        break
                    continue
                if requests >= max_requests:
                    stop = True
                    break
                requests += 1
                try:
                    response = client.post('/api/agent/model-step', headers=headers,
                        json={'revision': current['revision'], 'controller': controller})
                    payload = response.json()
                    if not isinstance(payload, dict): raise ValueError('Invalid response envelope.')
                except (ValueError, httpx.HTTPError):
                    attempts.append({'http_status': None, 'uncertain_transport': True})
                    errors.append('Model-step transport failed; server reservation may exist. No retry.')
                    stop = True
                    break
                attempts.append({'http_status': response.status_code,
                    'usage': payload.get('usage'), 'reserved_microusd': payload.get('reserved_microusd'),
                    'model_id': payload.get('model_id'), 'model_id_basis': payload.get('model_id_basis')})
                if response.status_code != 200:
                    errors.append(payload.get('detail', 'Model request failed.'))
                    if response.status_code == 429: stop = True
                    break
                models.append(payload['model_id'])
                current = payload
                if payload['model_id'] != expected_model:
                    errors.append('Observed/configured model does not match the frozen expected model.')
                    stop = True
                    break
            result = current['result']
            with grader_catalog(agent.catalog_for(task['catalog_kind'])):
                supported = bool(current['status'] == 'RECOMMENDED' and result['plan'] and
                    oracle.grade(current['goal'], result['plan']['items'], current['inspected']))
            records.append({'task_id': task['id'], 'controller': controller,
                'status': 'ERROR' if errors else 'INCOMPLETE_REQUEST_CAP' if stop and current['status'] == 'ACTIVE' else current['status'],
                'supported_recommendation': supported, 'inspections': len(current['inspected']),
                'attempts': attempts, 'errors': errors, 'model_ids': models,
                'events': current['events'], 'source_sha256': current['source_sha256']})
    return {'schema': 'intentcart-live-pilot/1', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'expected_model': expected_model, 'controllers': list(controllers),
        'planned_tasks': len(tasks), 'planned_trials': len(tasks) * len(controllers),
        'request_attempts': requests, 'records': records,
        'limitations': 'Authored diagnostic tasks and scripted answers; no human participants. Direct and guided share the model, tools, prompt, evidence and gates; guided adds a deterministic observable-evidence hint. Local reservations are not actual billed cost. Caps/errors and unattempted trials prevent an unconditional paired-performance claim. Model identity basis is retained. No GPU hardware is inferred.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', nargs='+', default=['native-default-b16', 'budget-conflict-b16'])
    parser.add_argument('--base-url', default='http://127.0.0.1:4000')
    parser.add_argument('--expected-model')
    parser.add_argument('--max-requests', type=int, default=0)
    parser.add_argument('--execute', action='store_true', help='Requires separate credit-only allowance and configured server gates.')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/live-agent-pilot.json')
    args = parser.parse_args()
    protocol = json.loads((ROOT / 'intentcart/data/agent-protocol.json').read_text())
    by_id = {task['id']: task for task in protocol['tasks']}
    if len(set(args.tasks)) != len(args.tasks) or any(t not in by_id for t in args.tasks):
        parser.error('Choose unique declared task IDs.')
    if not args.execute:
        print(json.dumps({'mode': 'dry run; zero network/provider requests', 'tasks': args.tasks,
            'controllers': ['direct', 'guided'], 'needs': 'Reviewed model/prices, credit-only limits, explicit max requests and positive server allowance.'}, indent=2))
        return 0
    url = urlsplit(args.base_url)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        parser.error('Only a local server origin is supported; do not transmit sessions to another host.')
    try:
        with httpx.Client(base_url=args.base_url, timeout=30, follow_redirects=False, trust_env=False) as client:
            report = run(client, [by_id[t] for t in args.tasks], args.max_requests, args.expected_model, args.base_url.rstrip('/'))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'saved': str(args.output), 'attempts': report['request_attempts'],
                          'note': 'Review every incomplete/failed trial and identity basis before making claims.'}))
        return 0 if report['request_attempts'] and all(not r.get('errors') and r['status'] not in ('UNATTEMPTED_AFTER_STOP', 'INCOMPLETE_REQUEST_CAP', 'START_ERROR') for r in report['records']) else 2
    except (ValueError, httpx.HTTPError, KeyError, TypeError) as exc:
        print('Live pilot stopped: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
