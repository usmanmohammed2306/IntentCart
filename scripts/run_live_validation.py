"""Bounded probe, matched trials and repeats. Dry run makes no requests.

Execution requires separately reviewed credit-only access, rates, model and
positive temporary server gates. This script never edits .env or creates access.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_live_agent import run
from intentcart import transcripts


def plan(tasks, repeats, max_requests):
    if not 1 <= len(tasks) <= 2 or len({task['id'] for task in tasks}) != len(tasks):
        raise ValueError('Choose one or two unique authored tasks.')
    if type(repeats) is not int or not 2 <= repeats <= 3:
        raise ValueError('Choose two or three repetitions per controller.')
    if type(max_requests) is not int or not 1 <= max_requests <= 48:
        raise ValueError('Use a single shared 1..48 request ceiling.')
    return {'tasks': [t['id'] for t in tasks], 'repetitions_per_controller': repeats,
            'controllers': ['direct', 'guided'], 'probe_request_limit': 1,
            'planned_comparison_trials': len(tasks)*repeats*2,
            'shared_request_ceiling': max_requests,
            'notice': 'A ceiling is not a promise of completion. Unattempted/capped/error trials remain in the denominator.'}


def convert_trial(record, expected_model, repeat_id, evidence_kind):
    if evidence_kind not in ('mock_provider', 'live_imported'):
        raise ValueError('Explicit mock or imported-live provenance is required.')
    attempts = []
    for attempt in record.get('attempts', []):
        status = attempt.get('http_status')
        uncertain = attempt.get('uncertain_transport', False)
        outcome = 'timeout' if uncertain else 'ok' if status == 200 else 'revision_conflict' if status == 409 else 'budget_stop' if status == 429 else 'http_error'
        usage = attempt.get('usage') or {}
        attempts.append({'outcome': outcome, 'http_status': status,
            'uncertain_transport': uncertain, 'paid_microusd': None,
            'reserved_microusd': attempt.get('reserved_microusd'),
            'input_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens')})
    decisions = [event.get('response', {}).get('basket_id') for event in record.get('events', [])
                 if event.get('action', {}).get('action') == 'recommend']
    decision = next((value for value in reversed(decisions) if value), None)
    supported = (record.get('supported_recommendation') is True and decision is not None
                 and attempts and all(a['outcome'] == 'ok' for a in attempts) and not record.get('errors'))
    raw_status = record['status']
    status = ('supported' if supported else 'unattempted' if raw_status == 'UNATTEMPTED_AFTER_STOP'
              else 'failed' if record.get('errors') or raw_status in ('ERROR','START_ERROR')
              else 'capped' if raw_status in ('INCOMPLETE_REQUEST_CAP','BUDGET_STOP','STEP_STOP')
              else 'deferred' if raw_status == 'DEFERRED' else 'capped')
    return {'task_id': record['task_id'], 'controller': record['controller'],
            'model_id': expected_model, 'repeat_id': repeat_id, 'evidence_kind': evidence_kind,
            'status': status, 'decision_id': decision if supported else None, 'attempts': attempts}


def execute(client, tasks, repeats, max_requests, expected_model, base_url, *, evidence_kind='live_imported', retain=None):
    schedule = plan(tasks, repeats, max_requests)
    retain = retain or (lambda name, report: None)
    phases, trials = [], []
    probe = run(client, tasks[:1], 1, expected_model, base_url, controllers=('direct',))
    retain('probe', probe)
    phases.append({'phase': 'probe', 'report': probe})
    attempts = probe['request_attempts']
    probe_rows = [a for r in probe['records'] for a in r.get('attempts', [])]
    compatibility = bool(len(probe_rows) == 1 and probe_rows[0].get('http_status') == 200
                         and probe_rows[0].get('model_id') == expected_model
                         and not probe_rows[0].get('uncertain_transport'))
    stop = not compatibility
    for repeat in range(repeats):
        # Counterbalance which controller runs first; task/tool/request bounds stay fixed.
        controllers = ('direct','guided') if repeat % 2 == 0 else ('guided','direct')
        for task in tasks:
            for controller in controllers:
                remaining = max_requests-attempts
                if stop or remaining <= 0:
                    record = {'task_id': task['id'], 'controller': controller,
                              'status': 'UNATTEMPTED_AFTER_STOP', 'attempts': []}
                else:
                    result = run(client, [task], remaining, expected_model, base_url, controllers=(controller,))
                    retain(f'repeat-{repeat+1}-{task["id"]}-{controller}', result)
                    phases.append({'phase': f'repeat-{repeat+1}', 'report': result})
                    attempts += result['request_attempts']
                    record = result['records'][0]
                    if record.get('errors') or record['status'] in ('START_ERROR','ERROR','INCOMPLETE_REQUEST_CAP'):
                        stop = True
                trials.append(convert_trial(record, expected_model, f'repeat-{repeat+1}', evidence_kind))
    payload = {'schema': 'intentcart-transcripts/1', 'trials': trials}
    analysis = transcripts.analyze(payload)
    return {'schema': 'intentcart-live-validation/1', 'created_utc': datetime.now(timezone.utc).isoformat(),
            'schedule': schedule, 'evidence_kind': evidence_kind, 'compatibility_response_observed': compatibility,
            'request_attempts': attempts, 'all_comparison_trials_terminal_without_cap_or_error': all(t['status'] in ('supported','deferred') for t in trials),
            'phases': phases, 'canonical_transcripts': payload, 'analysis': analysis,
            'billed_cost_known': False, 'human_participants': 0,
            'notice': 'Compatibility is an observed configured/reported-model response, not provider-billing verification. Imported live claims remain independently unverified. Reservations are not billed costs. Repeated trials share authored tasks; no human study or GPU is inferred.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', nargs='+', default=['native-default-b16'])
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--max-requests', type=int, default=48)
    parser.add_argument('--max-credit-microusd', type=int, default=1000000)
    parser.add_argument('--expected-model')
    parser.add_argument('--request-model', help='Reviewed gateway request alias, which may differ from its canonical response ID.')
    parser.add_argument('--base-url', default='http://127.0.0.1:4000')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    protocol_path = ROOT/'intentcart/data/agent-protocol.json'
    protocol = json.loads(protocol_path.read_text())
    lookup = {task['id']: task for task in protocol['tasks']}
    try:
        tasks = [lookup[key] for key in args.tasks]
        schedule = plan(tasks, args.repeats, args.max_requests)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    if not args.execute:
        print(json.dumps({'mode':'dry_run','provider_requests':0,'schedule':schedule,
                          'requires':'Existing credit-only access, reviewed prices/model, explicitly authorized allowance, positive temporary server gates. Permanent .env remains at zero.'},indent=2))
        return 0
    from scripts.inference_preflight import inspect
    from intentcart import config
    url = urlsplit(args.base_url)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1','localhost') or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        parser.error('Use a local-only server origin.')
    preflight = inspect()
    if not preflight['configured_enabled'] or not args.expected_model or (args.request_model or args.expected_model) != config.ASTRO_MODEL:
        parser.error('Reviewed configured gates/model are missing; no request sent.')
    if not 0 < config.ASTRO_BUDGET <= args.max_credit_microusd <= 1000000 or not 0 < config.CALL_LIMIT <= args.max_requests:
        parser.error('Temporary server/configuration allowances must fit the separately approved shared caps (at most $1 credits / 48 requests).')
    remaining = preflight.get('remaining_local_calls')
    if type(remaining) is not int or remaining <= 0:
        parser.error('An initialized durable call ledger with remaining allowance is required; no request sent.')
    if args.output_dir is None or args.output_dir.exists():
        parser.error('Choose a new private output directory.')
    args.output_dir.mkdir(parents=True, mode=0o700)
    def retain(name, report):
        with (args.output_dir/(name+'.json')).open('x') as stream:
            stream.write(json.dumps(report,indent=2)+'\n')
    import httpx
    with httpx.Client(base_url=args.base_url, timeout=30, follow_redirects=False, trust_env=False) as client:
        report = execute(client,tasks,args.repeats,min(args.max_requests,remaining),args.expected_model,args.base_url.rstrip('/'),retain=retain)
    report['request_model_alias'] = config.ASTRO_MODEL
    report['preflight'] = preflight
    report['protocol_sha256'] = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    retain('summary',report)
    print(json.dumps({k:report[k] for k in ('request_attempts','compatibility_response_observed','all_comparison_trials_terminal_without_cap_or_error','billed_cost_known')}))
    return 0 if report['all_comparison_trials_terminal_without_cap_or_error'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
