"""Bounded, local-only replay of real API endpoints and an independent fake ledger.

This module is tooling, never registered as an HTTP handler. Replay accepts an
allowlisted language, not code, URLs, arbitrary HTTP bodies or database paths.
Every runtime segment runs in a new child interpreter with temporary storage.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version as package_version
import json
import os
import platform
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from typing import Annotated, Literal, Union
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'intentcart-replay-v1'
SOURCE_FILES = (
    'intentcart/workbench.py','intentcart/workbench_routes.py','intentcart/finite_budget.py','intentcart/learned_acquisition.py','intentcart/acquisition.py',
    'intentcart/replay.py', 'intentcart/app.py', 'intentcart/paypal.py',
    'intentcart/config.py', 'intentcart/missions.py', 'intentcart/validity.py', 'intentcart/assurance.py',
    'intentcart/data/missions-catalog.json', 'scripts/evaluate_reliability.py',
    'intentcart/agent.py', 'intentcart/agent_routes.py', 'intentcart/evidence_catalog.py',
    'intentcart/workspace_preferences.py', 'intentcart/gateway.py', 'intentcart/research.py',
    'intentcart/orchestrator.py', 'intentcart/orchestrator_routes.py',
    'intentcart/workflow.py', 'intentcart/observability.py', 'intentcart/semantic.py', 'intentcart/sdk_transport.py', 'intentcart/production.py', 'intentcart/accounts.py','intentcart/studio.py','intentcart/trained_agent.py', 'intentcart/astro_auth.py', 'intentcart/installation.py', 'intentcart/__main__.py', 'intentcart/model_usage.py', 'intentcart/progress.py', 'intentcart/documents.py', 'intentcart/document_routes.py', 'intentcart/vector_search.py',
    'intentcart/data/evidence-catalog.json',
)
MAX_TRACE_BYTES = 65536
MUTANTS = ('none', 'stale-approval', 'fresh-retry-id', 'order-completed')
FAULTS = ('create-before', 'create-after', 'capture-before', 'capture-after',
          'refund-before', 'refund-after')


class ReplayError(ValueError):
    """Invalid, stale, unreproducible or failed-to-execute local replay."""


class SourceMismatch(ReplayError):
    """Source changed; this must abort, never count as a shrink rejection."""


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class PlainStep(Strict):
    op: Literal['start', 'quote', 'revise', 'read', 'capture', 'status', 'refund',
                'restart', 'completed-without-capture']


class CreateStep(Strict):
    op: Literal['create']
    approved: bool


class FaultStep(Strict):
    op: Literal['fault']
    at: Literal['create-before', 'create-after', 'capture-before', 'capture-after',
                'refund-before', 'refund-after']


Step = Annotated[Union[PlainStep, CreateStep, FaultStep], Field(discriminator='op')]
Hash = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]


class Trace(Strict):
    schema_version: Literal['intentcart-replay-v1'] = SCHEMA
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{1,63}$')
    mutant: Literal['none', 'stale-approval', 'fresh-retry-id', 'order-completed'] = 'none'
    source_sha256: dict[str, Hash]
    steps: list[Step] = Field(min_length=2, max_length=40)
    expected_digest: Hash | None = None

    @model_validator(mode='after')
    def prerequisites(self):
        if set(self.source_sha256) != set(SOURCE_FILES):
            raise ValueError('Trace must bind exactly the supported source files.')
        started = quoted = created = captured = False
        active_fault = None
        for i, step in enumerate(self.steps):
            op = step.op
            if op == 'start':
                if started or i != 0:
                    raise ValueError('Exactly one start must be the first event.')
                started = True
                continue
            if not started:
                raise ValueError('Events require a prior start.')
            if op == 'quote':
                if quoted or created:
                    raise ValueError('A trace has one immutable quote.')
                quoted = True
            elif op == 'revise':
                if not quoted:
                    raise ValueError('Revision scenario requires the earlier quote.')
            elif op == 'restart':
                if i == len(self.steps) - 1 or self.steps[i + 1].op == 'restart':
                    raise ValueError('Restart requires a nonempty following process segment.')
            elif op == 'fault':
                if active_fault:
                    raise ValueError('Consume an armed interruption before arming another.')
                active_fault = step.at
            elif op == 'create':
                if not quoted:
                    raise ValueError('Create requires the quoted terms.')
                if step.approved and active_fault and active_fault.startswith('create-'):
                    active_fault = None
                elif step.approved:
                    created = True
            elif op in ('capture', 'status', 'completed-without-capture'):
                if not created:
                    raise ValueError(f'{op} requires an acknowledged create event.')
                if op == 'capture':
                    if active_fault and active_fault.startswith('capture-'):
                        # After-commit loss can be reconciled by a later status;
                        # before-dispatch needs a later successful capture.
                        captured = captured or active_fault == 'capture-after'
                        active_fault = None
                    else:
                        captured = True
            elif op == 'refund':
                if not captured:
                    raise ValueError('Refund requires a prior possible capture.')
                if active_fault and active_fault.startswith('refund-'):
                    active_fault = None
        if active_fault:
            raise ValueError('An armed interruption must have a matching attempted operation.')
        return self


def source_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def load_trace(value: dict | Trace, *, check_sources: bool = True) -> Trace:
    raw = value.model_dump() if isinstance(value, Trace) else value
    if len(canonical(raw)) > MAX_TRACE_BYTES:
        raise ReplayError('Trace exceeds the 64 KiB limit.')
    try:
        trace = Trace.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise ReplayError(f'Invalid replay schema or prerequisites: {exc}') from exc
    if check_sources and trace.source_sha256 != source_hashes():
        raise SourceMismatch('Source mismatch: preserve the old evidence and generate a fresh evaluation for this source.')
    return trace


class LedgerProvider:
    """Independent SQLite provider truth; only exact request-key retries dedupe.

    This intentionally does not model all PayPal behavior. In particular distinct
    create identities can create duplicate orders. All IDs and money are fake.
    """
    def __init__(self, path: Path):
        self.path = path
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS operations (
                    kind TEXT NOT NULL, request_key TEXT NOT NULL, target TEXT NOT NULL,
                    response TEXT NOT NULL, PRIMARY KEY (kind, request_key));
                CREATE TABLE IF NOT EXISTS provider_orders (id TEXT PRIMARY KEY, quote TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (kind TEXT NOT NULL, request_key TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    def db(self):
        return sqlite3.connect(self.path)

    def arm(self, at):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('fault', ?)", (at,))

    def interrupt(self, point):
        from .paypal import ProviderError
        with self.db() as db:
            row = db.execute("SELECT value FROM settings WHERE name='fault'").fetchone()
            if not row or row[0] != point:
                return
            db.execute("DELETE FROM settings WHERE name='fault'")
        raise ProviderError('Declared local fake-provider interruption at ' + point, True)

    def _attempt(self, kind, key):
        with self.db() as db:
            db.execute('INSERT INTO attempts VALUES (?,?)', (kind, key))
        self.interrupt(kind + '-before')
        with self.db() as db:
            row = db.execute('SELECT response FROM operations WHERE kind=? AND request_key=?', (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def _commit(self, kind, key, target, response):
        with self.db() as db:
            db.execute('INSERT INTO operations VALUES (?,?,?,?)', (kind, key, target, json.dumps(response)))
        self.interrupt(kind + '-after')
        return response

    def create(self, quote, key):
        previous = self._attempt('create', key)
        if previous:
            return previous
        with self.db() as db:
            n = db.execute('SELECT COUNT(*) FROM provider_orders').fetchone()[0] + 1
            payload = {'id': f'FAKE-ORDER-{n}', 'status': 'APPROVED',
                       'purchase_units': [{'reference_id': quote['id']}]}
            db.execute('INSERT INTO provider_orders VALUES (?,?,?)',
                       (payload['id'], json.dumps(quote), json.dumps(payload)))
        return self._commit('create', key, quote['id'], payload)

    def get(self, order):
        with self.db() as db:
            row = db.execute('SELECT payload FROM provider_orders WHERE id=?', (order,)).fetchone()
        if not row:
            raise ReplayError('Fake provider order missing; trace prerequisites failed.')
        return json.loads(row[0])

    def capture(self, order, key):
        previous = self._attempt('capture', key)
        if previous:
            return previous
        with self.db() as db:
            quote, raw = db.execute('SELECT quote,payload FROM provider_orders WHERE id=?', (order,)).fetchone()
            quote, payload = json.loads(quote), json.loads(raw)
            n = db.execute("SELECT COUNT(*) FROM operations WHERE kind='capture'").fetchone()[0] + 1
            payload['status'] = 'COMPLETED'
            payload['purchase_units'][0]['payments'] = {'captures': [{
                'id': f'FAKE-CAPTURE-{n}', 'status': 'COMPLETED',
                'amount': {'currency_code': 'USD', 'value': f"{quote['total_cents'] / 100:.2f}"}}]}
            db.execute('UPDATE provider_orders SET payload=? WHERE id=?', (json.dumps(payload), order))
        return self._commit('capture', key, order, payload)

    def refund(self, capture, key):
        previous = self._attempt('refund', key)
        if previous:
            return previous
        with self.db() as db:
            captures = db.execute("SELECT response FROM operations WHERE kind='capture'").fetchall()
            match = next((json.loads(r[0])['purchase_units'][0]['payments']['captures'][0]
                          for r in captures if json.loads(r[0])['purchase_units'][0]['payments']['captures'][0]['id'] == capture), None)
            if match is None:
                raise ReplayError('Cannot refund an uncommitted fake capture.')
            n = db.execute("SELECT COUNT(*) FROM operations WHERE kind='refund'").fetchone()[0] + 1
            response = {'id': f'FAKE-REFUND-{n}', 'status': 'COMPLETED', 'amount': match['amount']}
        return self._commit('refund', key, capture, response)

    def corrupt_completed(self, order):
        payload = self.get(order)
        payload['status'] = 'COMPLETED'
        payload['purchase_units'][0].pop('payments', None)
        with self.db() as db:
            db.execute('UPDATE provider_orders SET payload=? WHERE id=?', (json.dumps(payload), order))

    def summary(self):
        with self.db() as db:
            commits = {kind: db.execute('SELECT COUNT(*) FROM operations WHERE kind=?', (kind,)).fetchone()[0]
                       for kind in ('create', 'capture', 'refund')}
            attempts = {kind: db.execute('SELECT COUNT(*) FROM attempts WHERE kind=?', (kind,)).fetchone()[0]
                        for kind in commits}
            identities = {kind: db.execute('SELECT COUNT(DISTINCT request_key) FROM attempts WHERE kind=?', (kind,)).fetchone()[0]
                          for kind in commits}
            captures = [json.loads(r[0])['purchase_units'][0]['payments']['captures'][0]['id']
                        for r in db.execute("SELECT response FROM operations WHERE kind='capture'")]
        return {'commits': commits, 'attempts': attempts, 'request_identities': identities,
                'capture_ids': captures}


def _segment(payload):
    """Private subprocess entry; paths only supplied by run_trace, not trace JSON."""
    directory = Path(payload['directory']).resolve()
    expected_db = directory / 'application.sqlite3'
    empty_keys = ('PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET', 'CHANNEL3_API_KEY',
                  'ASTRO_GATEWAY_URL', 'ASTRO_GATEWAY_API_KEY')
    if (not directory.name.startswith('intentcart-replay-')
            or not directory.is_relative_to(Path(tempfile.gettempdir()).resolve())
            or Path(os.environ.get('DATABASE_PATH', '')).resolve() != expected_db
            or os.environ.get('EXTERNAL_CALL_LIMIT') != '0'
            or any(os.environ.get(key) != '' for key in empty_keys)):
        raise ReplayError('Private replay worker requires disposable storage and explicitly blank credentials.')
    from fastapi.testclient import TestClient
    from . import app as module, config, missions
    from .paypal import PayPal
    context = payload['context']
    trace = load_trace(payload['trace'])
    fake = LedgerProvider(Path(payload['directory']) / 'provider.sqlite3')
    module.provider = fake
    module.RATES.clear()
    events = []

    def network_forbidden(*args, **kwargs):
        raise ReplayError('Network is forbidden in offline replay.')

    with ExitStack() as stack:
        # TestClient uses its own ASGI transport. All real HTTP transports and
        # the production provider request boundary are independently disabled.
        stack.enter_context(patch('httpx.HTTPTransport.handle_request', network_forbidden))
        stack.enter_context(patch('httpx.AsyncHTTPTransport.handle_async_request', network_forbidden))
        stack.enter_context(patch('httpx2.HTTPTransport.handle_request', network_forbidden))
        stack.enter_context(patch('httpx2.AsyncHTTPTransport.handle_async_request', network_forbidden))
        stack.enter_context(patch.object(PayPal, 'request', network_forbidden))
        if trace.mutant == 'stale-approval':
            stack.enter_context(patch.object(module, 'valid_quote', lambda *args: None))
            stack.enter_context(patch.object(module, 'spending_gate', lambda *args: {'eligible': True, 'failed': []}))
        elif trace.mutant == 'order-completed':
            original = module.verify_capture
            def unsafe_verify(response, quote, order):
                if response.get('status') == 'COMPLETED' and not response.get('purchase_units', [{}])[0].get('payments'):
                    return {'id': 'MUTANT-UNVERIFIED', 'status': 'COMPLETED'}
                return original(response, quote, order)
            stack.enter_context(patch.object(module, 'verify_capture', unsafe_verify))
        with TestClient(module.app) as client:
            if context.get('cookie'):
                client.cookies.set('intentcart_session', context['cookie'])
                client.headers.update({'origin': config.PUBLIC_URL, 'x-csrf-token': context['csrf']})
            for raw_step in payload['steps']:
                op = raw_step['op']
                prior = fake.summary()
                response = None
                if op == 'start':
                    session = client.get('/api/session')
                    if session.status_code != 200:
                        raise ReplayError('Session setup failed.')
                    context['csrf'] = session.json()['csrf_token']
                    context['cookie'] = client.cookies.get('intentcart_session')
                    client.headers.update({'origin': config.PUBLIC_URL, 'x-csrf-token': context['csrf']})
                    response = client.post('/api/missions', json={'text': 'Declared fictional replay workstation', 'goal': missions.Goal().model_dump()})
                    if response.status_code == 200:
                        context['mission'] = response.json()
                elif op == 'quote':
                    response = client.post('/api/missions/quotes', json={'revision': context['mission']['revision']})
                    if response.status_code == 200:
                        context['quote'] = response.json()
                elif op == 'revise':
                    response = client.post('/api/missions/revise', json={
                        'revision': context['mission']['revision'],
                        'goal': {**context['mission']['goal'], 'budget_cents': 30000}})
                    if response.status_code == 200:
                        context['mission'] = response.json()
                elif op == 'read':
                    response = client.get('/api/missions')
                elif op == 'fault':
                    fake.arm(raw_step['at'])
                elif op == 'completed-without-capture':
                    fake.corrupt_completed(context['order_id'])
                else:
                    if op == 'create' and trace.mutant == 'fresh-retry-id':
                        # Deliberate local-only call-site mutation: replace a
                        # durable create identity on an uncertain retry.
                        with module.database() as db:
                            row = db.execute('SELECT request_id,provider_id FROM orders WHERE quote_id=?', (context['quote']['id'],)).fetchone()
                            if row and not row['provider_id']:
                                db.execute('UPDATE orders SET request_id=? WHERE quote_id=?',
                                           (row['request_id'] + '-MUTANT', context['quote']['id']))
                    body = {'quote_id': context['quote']['id']}
                    if op == 'create':
                        body['approved'] = raw_step['approved']
                    response = client.post('/api/paypal/' + op, json=body)
                    if op == 'create' and response.status_code == 200:
                        context['order_id'] = response.json()['id']
                if op in ('start', 'quote', 'revise') and response.status_code != 200:
                    raise ReplayError(f'Required {op} setup failed with HTTP {response.status_code}.')
                observed = _observe(module, fake, context)
                if op == 'create' and observed['ledger']['commits']['create'] > prior['commits']['create']:
                    if context['quote']['mission_revision'] != context['mission']['revision']:
                        observed['violations'].append('stale-approval-dispatched')
                    if not raw_step['approved']:
                        observed['violations'].append('missing-approval-dispatched')
                event = {'op': op, 'http_status': response.status_code if response is not None else None,
                         'response_status': response.json().get('status') if response is not None else None,
                         'uncertain': bool(response.json().get('uncertain', False)) if response is not None else False,
                         'local_status': observed['local_status'], 'ledger': observed['ledger'],
                         'violations': sorted(observed['violations'])}
                if op == 'fault':
                    event['at'] = raw_step['at']
                events.append(event)
    return {'context': context, 'events': events}


def _observe(module, fake, context):
    ledger = fake.summary()
    with module.database() as db:
        row = db.execute('SELECT * FROM orders WHERE quote_id=?', (context.get('quote', {}).get('id', ''),)).fetchone()
        count = db.execute('SELECT COALESCE(SUM(count),0) FROM calls').fetchone()[0]
    status = row['status'] if row else None
    violations = []
    for kind in ('create', 'capture', 'refund'):
        if ledger['commits'][kind] > 1:
            violations.append('duplicate-provider-' + kind)
    if status in ('COMPLETED', 'REFUNDED', 'REFUND_PENDING') and row['capture_id'] not in ledger['capture_ids']:
        violations.append('unsupported-completion')
    if count:
        violations.append('unexpected-sponsor-reservation')
    # Do not export raw retry keys, session/csrf, quote UUIDs or user data.
    ledger.pop('capture_ids')
    return {'local_status': status, 'ledger': ledger, 'violations': violations}


def run_trace(value: dict | Trace, *, timeout: float = 20) -> dict:
    """Replay strict source-bound input; return only normalized public observations.

    A restart closes the TestClient and interpreter, then reconstructs the app
    and fake provider from their separate durable stores. It is not SIGKILL:
    exceptions model the interruption points before that actual process restart.
    """
    trace = load_trace(value)
    if not 0 < timeout <= 60:
        raise ReplayError('Each subprocess timeout must be within 0–60 seconds.')
    events, context = [], {}
    with tempfile.TemporaryDirectory(prefix='intentcart-replay-') as directory:
        env = os.environ.copy()
        for key in ('PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET', 'CHANNEL3_API_KEY',
                    'SANDBOX_BUYER_EMAIL', 'SANDBOX_BUYER_PASSWORD', 'ASTRO_GATEWAY_URL', 'ASTRO_GATEWAY_API_KEY'):
            env[key] = ''
        env.update({'DATABASE_PATH': str(Path(directory) / 'application.sqlite3'),
                    'EXTERNAL_CALL_LIMIT': '0', 'ASTRO_BUDGET_MICROUSD': '0',
                    'ASTRO_CREDIT_ONLY_CONFIRMED': 'false', 'COOKIE_SECURE': 'false',
                    'PUBLIC_URL': 'http://testserver', 'PYTHONHASHSEED': '0',
                    'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
        batches = [[]]
        for step in trace.steps:
            if step.op == 'restart':
                batches.append([])
            else:
                batches[-1].append(step.model_dump())
        for batch_index, steps in enumerate(batches):
            if batch_index:
                events.append({'op': 'restart', 'process_recreated': True})
            if not steps:
                continue
            message = {'trace': trace.model_dump(), 'steps': steps, 'context': context, 'directory': directory}
            try:
                worker = subprocess.run([sys.executable, '-m', 'intentcart.replay', '--segment'],
                                        input=json.dumps(message), text=True, capture_output=True,
                                        env=env, cwd=ROOT, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ReplayError('Replay subprocess exceeded its time bound.') from exc
            if worker.returncode:
                if trace.source_sha256 != source_hashes():
                    raise SourceMismatch('Source changed during replay; regenerate when edits finish.')
                # Worker uses only generated data; still do not echo cookie-bearing input.
                tail = worker.stderr[-1800:]
                raise ReplayError('Replay subprocess failed: ' + tail)
            try:
                result = json.loads(worker.stdout)
                context = result['context']
                events.extend(result['events'])
            except (ValueError, KeyError, TypeError) as exc:
                raise ReplayError('Replay subprocess returned invalid output.') from exc
    observations = [event for event in events if 'ledger' in event]
    if trace.source_sha256 != source_hashes():
        raise SourceMismatch('Source changed during replay; regenerate when edits finish.')
    last = observations[-1]
    violations = sorted({v for event in observations for v in event['violations']})
    outcome = {'events': events, 'violations': violations, 'local_status': last['local_status'],
               'ledger_counts': last['ledger'], 'completed': last['local_status'] in ('COMPLETED', 'REFUNDED') and not violations,
               'process_restarts': sum(step.op == 'restart' for step in trace.steps), 'live_provider_calls': 0}
    outcome['replay_digest'] = hashlib.sha256(canonical(outcome)).hexdigest()
    if trace.expected_digest and trace.expected_digest != outcome['replay_digest']:
        raise ReplayError('Normalized replay digest mismatch. Preserve the original trace and investigate.')
    return outcome


def scenario_traces() -> list[dict]:
    """Declared finite scenarios, not randomly sampled incidents or users."""
    def step(op, **fields):
        return {'op': op, **fields}
    prefix = [step('start'), step('read'), step('quote')]
    create = step('create', approved=True)
    definitions = [
        ('valid-refund', 'control', prefix + [create, step('capture'), step('status'), step('refund'), step('status')], 'REFUNDED'),
        ('valid-restart', 'control', prefix + [create, step('restart'), step('capture'), step('status')], 'COMPLETED'),
        ('stale-approval', 'fault', prefix + [step('read'), step('revise'), step('read'), create, step('read')], None),
        ('missing-approval', 'fault', prefix + [step('create', approved=False), step('read')], None),
        ('order-completed', 'fault', prefix + [create, step('read'), step('completed-without-capture'), step('status'), step('read')], 'CREATED'),
    ]
    for kind in ('create', 'capture', 'refund'):
        for point in ('before', 'after'):
            steps = copy.deepcopy(prefix)
            if kind != 'create':
                steps.append(create)
            if kind == 'refund':
                steps.append(step('capture'))
            steps += [step('fault', at=kind + '-' + point), create if kind == 'create' else step(kind),
                      step('restart'), step('read'), create if kind == 'create' else step(kind)]
            if kind == 'create':
                steps.append(step('capture'))
            steps.append(step('status'))
            definitions.append((kind + '-' + point, 'fault', steps, 'REFUNDED' if kind == 'refund' else 'COMPLETED'))
    sources = source_hashes()
    return [{'id': name, 'kind': kind, 'expected_status': status,
             'trace': Trace(id=name, source_sha256=sources, steps=steps).model_dump()}
            for name, kind, steps, status in definitions]


def shrink_trace(value: dict | Trace, *, max_attempts: int = 80) -> dict:
    """Greedy single-event deletion preserving exact observed violation names.

    Every candidate passes structural prerequisites and executes real endpoints.
    Finishing a no-deletion pass establishes removal-minimality for this deletion
    operator, not a globally shortest trace or a unique causal explanation.
    """
    trace = load_trace(value)
    raw = trace.model_dump()
    raw['expected_digest'] = None
    initial = run_trace(raw)
    if not initial['violations']:
        raise ReplayError('Shrinking requires a reproduced invariant failure.')
    target = initial['violations']
    current, outcome = raw, initial
    attempts = rejected = 0
    minimal = False
    while attempts < max_attempts:
        removed = False
        for index in range(1, len(current['steps'])):
            candidate = copy.deepcopy(current)
            candidate['steps'].pop(index)
            try:
                load_trace(candidate)
            except SourceMismatch:
                raise
            except ReplayError:
                rejected += 1
                continue
            if attempts >= max_attempts:
                break
            attempts += 1
            # Execution errors and source changes abort the reduction. Silently
            # counting a broken runtime as an invalid candidate could falsely
            # establish removal-minimality.
            trial = run_trace(candidate)
            if trial['violations'] == target:
                current, outcome = candidate, trial
                removed = True
                break
        if not removed:
            minimal = attempts < max_attempts
            break
    current['expected_digest'] = outcome['replay_digest']
    return {'trace': current, 'outcome': outcome, 'attempts': attempts,
            'invalid_candidates': rejected, 'original_events': len(raw['steps']),
            'reduced_events': len(current['steps']), 'removal_minimal': minimal,
            'limit': max_attempts, 'operator': 'single-event deletion with valid prerequisites and identical violation set'}


def evaluate_suite(*, shrink: bool = True) -> dict:
    cases = []
    for scenario in scenario_traces():
        outcome = run_trace(scenario['trace'])
        trace = {**scenario['trace'], 'expected_digest': outcome['replay_digest']}
        repeat = run_trace(trace)
        counts = {'create': 1, 'capture': 1, 'refund': int(scenario['expected_status'] == 'REFUNDED')}
        if scenario['id'] in ('stale-approval', 'missing-approval'):
            counts = {'create': 0, 'capture': 0, 'refund': 0}
        elif scenario['id'] == 'order-completed':
            counts = {'create': 1, 'capture': 0, 'refund': 0}
        checks = {'expected_status': outcome['local_status'] == scenario['expected_status'],
                  'expected_commit_counts': outcome['ledger_counts']['commits'] == counts,
                  'no_invariant_violations': not outcome['violations']}
        if scenario['id'] in FAULTS:
            operation, point = scenario['id'].split('-')
            interrupted = [event for event in outcome['events'] if event.get('http_status') == 502 and event.get('uncertain')]
            checks['interruption_point_observed'] = (len(interrupted) == 1 and
                interrupted[0]['ledger']['commits'][operation] == int(point == 'after'))
            checks['retry_identity_preserved'] = outcome['ledger_counts']['request_identities'][operation] == 1
        rejected_status = {'stale-approval': 409, 'missing-approval': 422, 'order-completed': 502}.get(scenario['id'])
        if rejected_status:
            checks['invalid_request_rejected'] = any(event.get('http_status') == rejected_status for event in outcome['events'])
        matches = all(checks.values())
        cases.append({**scenario, 'trace': trace, 'outcome': outcome,
                      'expected_outcome_matches': matches, 'checks': checks,
                      'repeat_digest_matches': repeat['replay_digest'] == outcome['replay_digest']})
    mutations = []
    for mutant, scenario_id, expected_violation in [
        ('stale-approval', 'stale-approval', 'stale-approval-dispatched'),
        ('fresh-retry-id', 'create-after', 'duplicate-provider-create'),
        ('order-completed', 'order-completed', 'unsupported-completion')]:
        case = next(c for c in cases if c['id'] == scenario_id)
        trace = {**case['trace'], 'id': 'mutant-' + mutant, 'mutant': mutant, 'expected_digest': None}
        outcome = run_trace(trace)
        trace['expected_digest'] = outcome['replay_digest']
        reduced = shrink_trace(trace) if shrink else None
        mutations.append({'id': mutant, 'scenario_id': scenario_id, 'trace': trace,
                          'detected': outcome['violations'] == [expected_violation], 'expected_violation': expected_violation, 'outcome': outcome,
                          'shrunk_trace': reduced['trace'] if reduced else None,
                          'shrunk_outcome': reduced['outcome'] if reduced else None,
                          'shrink': {key: value for key, value in reduced.items() if key not in ('trace', 'outcome')} if reduced else None})
    controls = [c for c in cases if c['kind'] == 'control']
    return {
        'schema': 'intentcart-reliability-v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'kind': 'Declared local fault injection and mutation testing through real API endpoints; independent fake SQLite provider',
        'source_sha256': source_hashes(),
        'environment': {'python': platform.python_version(), 'platform': platform.system(),
                        'packages': {name: package_version(name) for name in ('fastapi', 'starlette', 'pydantic', 'httpx', 'httpx2', 'openai', 'torch', 'transformers', 'langgraph', 'mcp', 'opentelemetry-sdk')}},
        'denominators': {'fault_cases': len(cases) - len(controls), 'controls': len(controls),
                         'baseline_replays': len(cases) * 2, 'mutants': len(mutations), 'mutant_cases': len(mutations),
                         'interruption_points': len(FAULTS),
                         'shrink_candidate_replays': sum(m['shrink']['attempts'] for m in mutations if m['shrink'])},
        'checks': {'baseline_expected_outcomes': all(c['expected_outcome_matches'] for c in cases),
                   'baseline_no_invariant_violations': all(not c['outcome']['violations'] for c in cases),
                   'normalized_replay_matches': all(c['repeat_digest_matches'] for c in cases),
                   'valid_controls_complete': all(c['outcome']['completed'] for c in controls),
                   'declared_mutants_detected': all(m['detected'] for m in mutations),
                   'shrunk_failures_removal_minimal': bool(shrink) and all(m['shrink']['removal_minimal'] for m in mutations)},
        'cases': cases, 'mutations': mutations, 'live_provider_calls': 0,
        'limits': ['Finite scripted fake-provider scenarios, not a population reliability estimate or live PayPal experiment.',
                   'ProviderError injection before dispatch or after independent ledger commit; then an actual new interpreter, not an OS kill.',
                   'No claim of universal exactly-once processing, arbitrary failure coverage, concurrency safety, or a unique causal explanation.',
                   'Three deliberate tooling-only mutations are not discovered production incidents; same fixtures and checker can share blind spots.',
                   'Normalized outcomes omit random IDs, clock values and private session data; no wall-clock performance claim.'],
    }


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--segment', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.segment:
        parser.error('Use scripts/evaluate_reliability.py for supported commands.')
    print(json.dumps(_segment(json.loads(sys.stdin.read()))))


if __name__ == '__main__':
    _main()
