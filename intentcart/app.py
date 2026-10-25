"""Single-instance sandbox demonstration server with durable SQLite state."""
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from collections import defaultdict, deque
import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
import re
import math
from typing import Literal
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from . import config, production, accounts
from .learning import FEATURES, PARTICLES, posterior, choose_pair, infer_intake
from .decision import assess, distribution, QUESTION_COST, RISK_LIMIT
from . import study as pilot
from . import missions as outcomes
from . import gateway, research
from .paypal import provider, ProviderError, verify_capture
from .assurance import (WORLD_LABELS, total_cents, feasible_indexes, project_world,
                        check_proposal, exact_proposal, challenge_suite)

ROOT = Path(__file__).parent
CATALOG = json.loads((ROOT / 'data/catalog.json').read_text())
BY_ID = {p['id']: p for p in CATALOG}
DECISION_CONFIG = json.loads((ROOT / 'data/decision-config.json').read_text())
LOCK = threading.RLock()
RATE_LOCK = threading.Lock()
RATES = defaultdict(deque)

@contextmanager
def database():
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        db = sqlite3.connect(config.DATABASE_PATH, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

def initialize():
    with database() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, csrf TEXT NOT NULL, state TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES sessions(id), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders (quote_id TEXT PRIMARY KEY REFERENCES quotes(id), owner TEXT NOT NULL REFERENCES sessions(id),
              request_id TEXT NOT NULL, capture_request TEXT NOT NULL, refund_request TEXT NOT NULL,
              provider_id TEXT, capture_id TEXT, refund_id TEXT, status TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS calls (name TEXT PRIMARY KEY, count INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS research_documents (id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES sessions(id),revision INTEGER NOT NULL,data TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS document_answers (id TEXT PRIMARY KEY,owner TEXT NOT NULL REFERENCES sessions(id),document_id TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS feedback (owner TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS studies (owner TEXT PRIMARY KEY REFERENCES sessions(id), data TEXT NOT NULL);
        ''')
        accounts.initialize(db)
        # Upgrade existing installations without losing receipts. An old pending
        # operation has no trustworthy first-attempt time: require review.
        columns = {r['name'] for r in db.execute('PRAGMA table_info(orders)')}
        for name in ('create_started', 'capture_started', 'refund_started'):
            if name not in columns:
                db.execute(f'ALTER TABLE orders ADD COLUMN {name} REAL')
        db.execute('UPDATE orders SET create_started=0 WHERE create_started IS NULL')
        db.execute("UPDATE orders SET refund_started=0 WHERE status='REFUND_PENDING' AND refund_started IS NULL")

@asynccontextmanager
async def lifespan(application):
    # Opening storage belongs to server startup, not module import. This keeps
    # tooling and test collection from touching a user's saved payment state.
    production.validate(config)
    initialize()
    yield

app = FastAPI(title='IntentCart Missions sandbox API', version='4.3.0', lifespan=lifespan)

@app.exception_handler(ProviderError)
async def payment_error(request, exc):
    return JSONResponse({'detail': str(exc), 'uncertain': exc.uncertain}, status_code=502)

@app.middleware('http')
async def boundaries(request: Request, call_next):
    denied=await production.access_async(request,config)
    if denied is not None:return denied
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if request.headers.get('origin') != config.PUBLIC_URL:
            return JSONResponse({'detail': 'Request origin is not allowed.'}, status_code=403)
        # Stream-bound the body too; Content-Length alone does not cover chunked input.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > (1_600_000 if request.url.path=='/api/documents/import' else 65536):
                return JSONResponse({'detail': 'Request body is too large.'}, status_code=413)
        request._body = bytes(body)
    if request.url.path.startswith('/api/'):
        key = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        with RATE_LOCK:
            queue = RATES[key]
            while queue and queue[0] < now - 60:
                queue.popleft()
            if len(queue) >= 120:
                return JSONResponse({'detail': 'Please wait a minute before making more requests.'}, status_code=429, headers={'Retry-After': '60'})
            queue.append(now)
            if len(RATES) > 10000:
                for old in list(RATES):
                    if not RATES[old] or RATES[old][-1] < now - 60:
                        del RATES[old]
    denied=accounts.bind(request,__import__(__name__,fromlist=['app']))
    if denied is not None:return denied
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://*.paypal.com https://*.paypalobjects.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.paypal.com https://*.paypalobjects.com; connect-src 'self' https://*.paypal.com https://*.paypalobjects.com; frame-src https://*.paypal.com https://*.paypalobjects.com; object-src 'none'; base-uri 'self'; form-action 'self' https://*.paypal.com; frame-ancestors 'none'"
    return production.cache_policy(request,response,ROOT/'web')

def fresh_state():
    return {'version': 0, 'mission': None, 'history': [], 'excluded': [], 'question': None, 'answered_ids': [],
            'shipping_surcharge_cents': 0, 'scenario_events': []}

def owner(request, db, mutation=False):
    if accounts.enabled():
        account=accounts.current(request,db,mutation)
        request.scope['intentcart_account_workspace']=account['workspace']
        request.scope['intentcart_account_csrf']=account['csrf']
        request.scope['intentcart_auth_subject']='account:'+account['id']
    token = request.cookies.get('intentcart_session', '')
    digest = request.scope.get('intentcart_account_workspace') or hashlib.sha256(token.encode()).hexdigest()
    row = db.execute('SELECT * FROM sessions WHERE id=? AND expires>?', (digest, time.time())).fetchone()
    if row is None:
        raise HTTPException(401, 'Session expired. Reload the page to start a new session.')
    subject=request.scope.get('intentcart_auth_subject')
    state=json.loads(row['state'])
    if subject is not None and state.get('_auth_subject')!=subject:
        raise HTTPException(401,'Session belongs to a different signed-in account. Reload to start your own session.')
    expected=request.scope.get('intentcart_account_csrf',row['csrf'])
    if mutation and not secrets.compare_digest(expected, request.headers.get('x-csrf-token', '')):
        raise HTTPException(403, 'Request security token is missing or invalid.')
    return digest, state

def save(db, sid, state):
    row=db.execute('SELECT state FROM sessions WHERE id=?',(sid,)).fetchone()
    previous=json.loads(row['state']) if row else {}
    if previous.get('_auth_subject') is not None:state={**state,'_auth_subject':previous['_auth_subject']}
    db.execute('UPDATE sessions SET state=? WHERE id=?', (json.dumps(state), sid))

def feasible(state):
    return feasible_indexes(CATALOG, state)

def total(product, state=None):
    return total_cents(product, state)

def compute(state, *, include_question=True):
    available = feasible(state)
    answered = sum(h['choice'] != 'skip' for h in state['history'])
    if not available:
        pref = []
        if state['mission']:
                utilities, preference_weights = posterior(CATALOG, state['history'], infer_intake(state['mission']['text']))
                if state['mission'].get('adaptive'):
                    observations = [(list(BY_ID).index(h['a']), list(BY_ID).index(h['b']), h['choice']) for h in state['history']]
                    preference_weights = distribution(utilities, observations, infer_intake(state['mission']['text']), DECISION_CONFIG['decay'])
                pref = [{'name': label, 'value': round(float(v),4)} for label,v in zip(FEATURES,preference_weights @ PARTICLES)]
        result = {'ranked': [], 'weights': pref, 'question': None, 'feasible_count': 0,
                  'answered': answered, 'question_limit': config.MAX_QUESTIONS}
        if state.get('mission') and state['mission'].get('adaptive'):
            result['decision'] = assess(None, None, [])
        return result
    utilities, weights = posterior(CATALOG, state['history'], infer_intake(state['mission']['text']))
    adaptive = state['mission'].get('adaptive', False)
    observations = [(list(BY_ID).index(h['a']), list(BY_ID).index(h['b']), h['choice']) for h in state['history']]
    if adaptive:
        weights = distribution(utilities, observations, infer_intake(state['mission']['text']), DECISION_CONFIG['decay'])
    means = weights @ utilities
    rank = sorted(available, key=lambda i: (-means[i], CATALOG[i]['id']))
    pref = weights @ PARTICLES
    winners = utilities[:, available].argmax(axis=1)
    ranked = []
    for i in rank[:6]:
        reasons = sorted(range(7), key=lambda j: -(pref[j] * CATALOG[i]['features'][j]))[:3]
        ranked.append({**CATALOG[i], 'total_cents': total(CATALOG[i], state), 'score': round(float(means[i]), 4),
                       'model_win_share': round(float(weights[winners == available.index(i)].sum()), 4),
                       'reasons': [FEATURES[j] for j in reasons]})
    used = {tuple(sorted((list(BY_ID).index(h['a']), list(BY_ID).index(h['b'])))) for h in state['history']}
    answered = sum(h['choice'] != 'skip' for h in state['history'])
    query = None
    decision = None
    if include_question and answered < config.MAX_QUESTIONS and len(state['history']) < 8:
        if adaptive:
            decision = assess(utilities, weights, available, used, answered=answered, attempts=len(state['history']))
            pair = decision['pair']
        else:
            pair = choose_pair(utilities, weights, available, used)
        if pair:
            a, b, gain = pair
            query = {'id': f"{state['version']}:{CATALOG[a]['id']}:{CATALOG[b]['id']}",
                     'a': CATALOG[a], 'b': CATALOG[b], 'expected_gain': round(gain, 6)}
    if adaptive and decision is None:
        decision = assess(utilities, weights, available, used, answered=answered,
                          attempts=len(state['history']), select_question=False)
    result = {'ranked': ranked, 'weights': [{'name': label, 'value': round(float(v), 4)} for label,v in zip(FEATURES,pref)],
            'question': query, 'feasible_count': len(available), 'answered': answered,
            'effective_particles': round(float(1 / (weights @ weights))), 'question_limit': config.MAX_QUESTIONS}
    if decision:
        result['decision'] = {k: v for k, v in decision.items() if k not in ('pair', 'pick')}
        result['decision'].update({'question_cost': QUESTION_COST, 'risk_limit': RISK_LIMIT,
            'decay': DECISION_CONFIG['decay'], 'model_only': True,
            'note': 'Illustrative model utility, not dollars or calibrated confidence. Deferral stops agent recommendations; you may still choose manually. Exact approval is always required.'})
    return result

def public_state(state):
    result = compute(state)
    state['question'] = result['question']
    return {'version': state['version'], 'mission': state['mission'], 'history': state['history'],
            'excluded': state['excluded'], 'shipping_surcharge_cents': state.get('shipping_surcharge_cents', 0),
            'scenario_events': state.get('scenario_events', []), **result}

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Mission(Strict):
    text: str = Field(min_length=3, max_length=800)
    budget_cents: int = Field(ge=3000, le=15000, strict=True)
    laptop_inches: int = Field(ge=0, le=17, strict=True)
    min_capacity_l: int = Field(ge=0, le=38, strict=True)
    adaptive: bool = Field(default=False, strict=True)

class Answer(Strict):
    question_id: str = Field(max_length=100)
    choice: str = Field(pattern='^(a|b|tie|skip)$')

class Selection(Strict):
    product_id: str = Field(pattern=r'^bag-\d{2}$')
    version: int = Field(ge=0, strict=True)

class Approval(Strict):
    quote_id: str = Field(max_length=64)
    approved: bool = Field(strict=True)

class OrderAction(Strict):
    quote_id: str = Field(max_length=64)

class Scenario(Strict):
    kind: Literal['stock', 'shipping', 'budget', 'no_purchase']
    version: int = Field(ge=0, strict=True)

class Proposal(Approval):
    product_id: str = Field(pattern=r'^bag-\d{2}$')
    total_cents: int = Field(ge=0, le=100000, strict=True)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    version: int = Field(ge=0, strict=True)

@app.get('/api/rehearsal')
def rehearsal(request: Request):
    with database() as db:
        _, state = owner(request, db)
        if not state['mission']:
            raise HTTPException(409, 'Set a mission before rehearsing alternate situations.')
        baseline = compute(state, include_question=False)
        leader = baseline['ranked'][0] if baseline['ranked'] else None
        worlds = []
        for kind, label in WORLD_LABELS.items():
            projected = project_world(state, kind, leader['id'] if leader else None)
            outcome = compute(projected, include_question=False)
            pick = outcome['ranked'][0] if outcome['ranked'] else None
            worlds.append({'kind': kind, 'label': label, 'feasible_count': outcome['feasible_count'],
                           'pick': pick, 'budget_cents': projected['mission']['budget_cents'],
                           'shipping_surcharge_cents': projected.get('shipping_surcharge_cents', 0),
                           'changed_pick': bool(pick and leader and pick['id'] != leader['id']),
                           'decision': 'NO_PURCHASE' if not pick else 'REVIEW_REQUIRED',
                           'preferences_retained': projected['history'] == state['history']})
        return {'source_version': state['version'], 'baseline': leader, 'worlds': worlds,
                'note': 'Declared fictional interventions, not predictions. Preview changes nothing and authorizes no payment.'}

@app.post('/api/scenario')
def apply_scenario(body: Scenario, request: Request):
    with database() as db:
        sid, state = owner(request, db, True)
        if not state['mission'] or body.version != state['version']:
            raise HTTPException(409, 'This rehearsal is stale. Reload the current mission.')
        current = compute(state)
        leader = current['ranked'][0]['id'] if current['ranked'] else None
        if body.kind == 'stock' and not leader:
            raise HTTPException(422, 'There is no feasible front-runner to remove.')
        state = project_world(state, body.kind, leader)
        state['version'] += 1
        state['scenario_events'] = (state.get('scenario_events', []) + [WORLD_LABELS[body.kind]])[-8:]
        result = public_state(state)
        save(db, sid, state)
        return result

@app.get('/api/session')
def session(request: Request):
    with database() as db:
        try:
            sid, state = owner(request, db)
            row = db.execute('SELECT csrf FROM sessions WHERE id=?', (sid,)).fetchone()
            token = None
            csrf = request.scope.get('intentcart_account_csrf',row['csrf'])
            if accounts.enabled():db.execute('UPDATE sessions SET expires=? WHERE id=?',(time.time()+7*86400,sid))
        except HTTPException:
            if accounts.enabled():raise
            token = secrets.token_urlsafe(32)
            sid = hashlib.sha256(token.encode()).hexdigest()
            csrf = secrets.token_urlsafe(32)
            state = fresh_state()
            if request.scope.get('intentcart_auth_subject') is not None:state['_auth_subject']=request.scope['intentcart_auth_subject']
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (sid, csrf, json.dumps(state), time.time()+7*86400))
        result = public_state(state)
        save(db, sid, state)
        calls = db.execute("SELECT COALESCE(SUM(count),0) AS count FROM calls WHERE name IN ('channel3','astro')").fetchone()
        remaining = max(0, config.CALL_LIMIT - (calls['count'] if calls else 0))
        response = JSONResponse({'csrf_token': csrf, 'state': result, 'config': {
            'paypal_client_id': config.CLIENT_ID if config.CLIENT_SECRET else '',
            'paypal_connected': bool(config.CLIENT_ID and config.CLIENT_SECRET),
            'channel3_connected': bool(config.CHANNEL3_KEY), 'channel3_calls_remaining': remaining, 'sandbox': True}})
        if token:
            response.set_cookie('intentcart_session', token, httponly=True, secure=config.COOKIE_SECURE,
                                samesite='lax', max_age=7*86400)
        return response

@app.post('/api/mission')
def mission(body: Mission, request: Request):
    with database() as db:
        sid, previous = owner(request, db, True)
        state = fresh_state()
        state['version'] = previous['version'] + 1
        state['mission'] = body.model_dump()
        result = public_state(state)
        if not result['ranked']:
            raise HTTPException(422, 'No backpack meets these limits. Increase the budget or relax a size constraint.')
        save(db, sid, state)
        return result

@app.post('/api/answer')
def answer(body: Answer, request: Request):
    with database() as db:
        sid, state = owner(request, db, True)
        if body.question_id in state['answered_ids']:
            prior = next(h for h in state['history'] if h['question_id'] == body.question_id)
            if prior['choice'] != body.choice:
                raise HTTPException(409, 'This question already has a different answer.')
            return public_state(state)
        question = state['question']
        if not question or question['id'] != body.question_id:
            raise HTTPException(409, 'This comparison is stale. Reload your current shortlist.')
        state['history'].append({'question_id': body.question_id, 'a': question['a']['id'], 'b': question['b']['id'], 'choice': body.choice})
        state['answered_ids'].append(body.question_id)
        state['version'] += 1
        result = public_state(state)
        save(db, sid, state)
        return result

@app.post('/api/unavailable')
def unavailable(body: Selection, request: Request):
    with database() as db:
        sid, state = owner(request, db, True)
        if body.version != state['version'] or body.product_id not in [CATALOG[i]['id'] for i in feasible(state)]:
            raise HTTPException(409, 'This shortlist changed. Reload before simulating a stock change.')
        if len(feasible(state)) < 2:
            raise HTTPException(422, 'At least two feasible products are needed for a stock-change demonstration.')
        state['excluded'].append(body.product_id)
        state['version'] += 1
        result = public_state(state)
        save(db, sid, state)
        return result

@app.post('/api/quotes')
def quote(body: Selection, request: Request):
    with database() as db:
        sid, state = owner(request, db, True)
        if body.version != state['version'] or body.product_id not in [CATALOG[i]['id'] for i in feasible(state)]:
            raise HTTPException(409, 'The product or preferences changed. Generate a new quote.')
        p = BY_ID[body.product_id]
        data = {'id': str(uuid.uuid4()), 'version': state['version'], 'product': p, 'item_cents': p['price_cents'],
                'shipping_cents': total(p,state)-p['price_cents'], 'tax_cents': 0, 'total_cents': total(p,state),
                'currency': 'USD', 'expires_at': time.time()+900, 'sandbox': True}
        model = compute(state)
        data['decision_snapshot'] = {'mission': state['mission'], 'version': state['version'],
            'comparisons': state['history'], 'preferences': model['weights'], 'hypotheses': len(PARTICLES),
            'excluded': state['excluded'], 'shipping_surcharge_cents': state.get('shipping_surcharge_cents',0),
            'scenario_events': state.get('scenario_events',[]),
            'shortlist': [{k: item[k] for k in ('id','name','total_cents','score','model_win_share','reasons')}
                          for item in model['ranked']],
            'selected_product_id': p['id'],
            'decision_controller': model.get('decision'),
            'limits': 'Illustrative linear preference model; support is not satisfaction probability.'}
        db.execute('INSERT INTO quotes VALUES (?,?,?)', (data['id'], sid, json.dumps(data)))
        return data

def owned_quote(db, sid, quote_id):
    row = db.execute('SELECT data FROM quotes WHERE id=? AND owner=?', (quote_id,sid)).fetchone()
    if not row:
        raise HTTPException(404, 'Quote not found in this session.')
    return json.loads(row['data'])

def valid_quote(quote, state):
    if quote['expires_at'] < time.time() or quote['version'] != state['version']:
        raise HTTPException(409, 'The approved quote expired or your shortlist changed. Generate a new quote.')
    if quote.get('kind')=='mission' and not spending_gate(quote,state,exact_proposal(quote,True),time.time())['eligible']:
        raise HTTPException(409, 'This complete plan no longer passes its compatibility and source checks. Generate a new quote.')

def spending_gate(quote,state,proposal,now):
    if quote.get('kind')=='mission':
        return outcomes.quote_gate(quote,state,proposal,now)
    return check_proposal(CATALOG,quote,state,proposal,now)

@app.post('/api/proposals/check')
def proposal_check(body: Proposal, request: Request):
    with database() as db:
        sid, state = owner(request, db, True)
        quote = owned_quote(db, sid, body.quote_id)
        return check_proposal(CATALOG, quote, state, body.model_dump(), time.time())

@app.post('/api/challenges')
def challenges(body: OrderAction, request: Request):
    with database() as db:
        sid, state = owner(request, db, True)
        quote = owned_quote(db, sid, body.quote_id)
        return challenge_suite(CATALOG, quote, state, time.time())

@app.get('/api/decision-receipt/{quote_id}')
def decision_receipt(quote_id: str, request: Request, download: bool = False):
    with database() as db:
        sid, state = owner(request, db)
        quote = owned_quote(db, sid, quote_id)
        snapshot = quote.get('decision_snapshot')
        row = db.execute('SELECT status FROM orders WHERE quote_id=? AND owner=?', (quote_id,sid)).fetchone()
        encoded = json.dumps(snapshot, sort_keys=True, separators=(',',':')).encode()
        result = {'schema': 'intentcart-decision-receipt/1', 'sandbox': True, 'quote': quote,
                'snapshot_sha256': hashlib.sha256(encoded).hexdigest() if snapshot else None,
                'snapshot_note': 'Content fingerprint, not a digital signature or proof of correct preferences.' if snapshot else
                    'Historical quote predates decision snapshots; no missing evidence has been reconstructed.',
                'current_checks': spending_gate(quote, state, exact_proposal(quote,row is not None), time.time()),
                'order_status': row['status'] if row else 'NO_ORDER',
                'approval_note': 'Lab eligibility never records consent. Only an explicit checkout request can create an order; PayPal separately approves the buyer.',
                'privacy_note': 'Contains your mission and comparisons. Review before sharing; no credentials or session tokens included.'}
        if download:
            return JSONResponse(result, headers={'Content-Disposition': f'attachment; filename="intentcart-decision-{quote["id"]}.json"'})
        return result

@app.get('/api/lab-evidence')
def lab_evidence():
    path = ROOT/'data/lab-evaluation.json'
    if not path.is_file():
        raise HTTPException(404, 'Recovery evidence has not been generated. Run scripts/evaluate_lab.py.')
    data = json.loads(path.read_text())
    names = ('intentcart/app.py','intentcart/assurance.py','intentcart/learning.py','scripts/evaluate_lab.py')
    if not all((ROOT.parent/name).is_file() and hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest()
               == data.get('source_sha256',{}).get(name) for name in names):
        raise HTTPException(409, 'Saved recovery evidence is stale. Re-run scripts/evaluate_lab.py for this source version.')
    return data

@app.post('/api/paypal/create')
def create(body: Approval, request: Request):
    if not body.approved:
        raise HTTPException(422, 'Approve the exact sandbox quote before opening PayPal.')
    with database() as db:
        sid, state = owner(request, db, True)
        quote = owned_quote(db, sid, body.quote_id)
        valid_quote(quote,state)
        gate = spending_gate(quote, state, exact_proposal(quote,body.approved), time.time())
        if not gate['eligible']:
            raise HTTPException(409, 'Spending checks failed: ' + ', '.join(gate['failed']) + '. Generate a fresh quote.')
        row = db.execute('SELECT * FROM orders WHERE quote_id=?', (body.quote_id,)).fetchone()
        if not row:
            db.execute('''INSERT INTO orders
                       (quote_id,owner,request_id,capture_request,refund_request,status,updated,create_started)
                       VALUES (?,?,?,?,?,?,?,?)''',
                       (quote['id'],sid,str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()),'CREATING',time.time(),time.time()))
            db.commit()  # Persist idempotency keys BEFORE the external side effect.
            row = db.execute('SELECT * FROM orders WHERE quote_id=?', (body.quote_id,)).fetchone()
        if row['provider_id']:
            return {'id': row['provider_id'], 'status': row['status']}
        if time.time() - row['create_started'] > 5*3600:
            raise HTTPException(409, 'Creation requires operator reconciliation; the safe retry window ended.')
        result = provider.create(quote,row['request_id'])
        order_id = result.get('id', '')
        if not re.fullmatch(r'[A-Za-z0-9-]{1,64}',order_id):
            raise ProviderError('PayPal returned an invalid order identity.')
        db.execute('UPDATE orders SET provider_id=?,status=?,updated=? WHERE quote_id=?',
                   (order_id,'CREATED',time.time(),quote['id']))
        return {'id': order_id, 'status': 'CREATED'}

def owned_order(db,sid,quote_id):
    quote = owned_quote(db,sid,quote_id)
    row = db.execute('SELECT * FROM orders WHERE quote_id=? AND owner=?', (quote_id,sid)).fetchone()
    if not row or not row['provider_id']:
        raise HTTPException(409,'No PayPal order exists for this quote yet. Retry opening the same quote.')
    return quote,row

def reconcile(db,quote,row,payload):
    capture = verify_capture(payload,quote,row['provider_id'])
    if capture:
        status = 'REFUNDED' if capture['status'] == 'REFUNDED' else (
            row['status'] if row['status'] in ('REFUNDED','REFUND_PENDING') else 'COMPLETED')
        db.execute('UPDATE orders SET capture_id=?,status=?,updated=? WHERE quote_id=?',
                   (capture['id'],status,time.time(),quote['id']))
        return {'status': status, 'capture_id': capture['id'], 'quote': quote, 'order_id': row['provider_id'], 'refund_id': row['refund_id']}
    # An order can be COMPLETED while its capture is still PENDING. Never
    # report successful payment from the order-level status alone.
    captures = payload['purchase_units'][0].get('payments', {}).get('captures', [])
    status = 'CAPTURE_' + captures[0]['status'] if captures else payload.get('status','UNKNOWN')
    if row['status'] not in ('COMPLETED', 'REFUNDED', 'REFUND_PENDING'):
        db.execute('UPDATE orders SET status=?,updated=? WHERE quote_id=?', (status,time.time(),quote['id']))
    return {'status': status, 'quote': quote, 'order_id':row['provider_id']}

@app.post('/api/paypal/capture')
def capture(body: OrderAction,request: Request):
    with database() as db:
        sid,state = owner(request,db,True)
        quote,row = owned_order(db,sid,body.quote_id)
        payload = provider.get(row['provider_id'])
        if payload.get('status') == 'COMPLETED':
            return reconcile(db,quote,row,payload)
        valid_quote(quote,state)
        if payload.get('status') != 'APPROVED':
            raise HTTPException(409,'Approve this exact order in the PayPal sandbox window first.')
        if row['capture_started'] is not None and time.time() - row['capture_started'] > 5*3600:
            raise HTTPException(409,'The capture needs operator reconciliation; its safe retry window ended.')
        if row['capture_started'] is None:
            db.execute('UPDATE orders SET capture_started=? WHERE quote_id=?',(time.time(),quote['id']))
            db.commit()
        result = provider.capture(row['provider_id'],row['capture_request'])
        return reconcile(db,quote,row,result)

@app.post('/api/paypal/status')
def payment_status(body: OrderAction,request: Request):
    with database() as db:
        sid,_ = owner(request,db,True)
        quote,row = owned_order(db,sid,body.quote_id)
        return reconcile(db,quote,row,provider.get(row['provider_id']))

@app.post('/api/paypal/refund')
def refund(body: OrderAction,request: Request):
    with database() as db:
        sid,_ = owner(request,db,True)
        quote,row = owned_order(db,sid,body.quote_id)
        if row['status'] == 'REFUNDED':
            return {'status':'REFUNDED','refund_id':row['refund_id'],'quote':quote}
        if not row['capture_id'] or row['status'] not in ('COMPLETED','REFUND_PENDING'):
            raise HTTPException(409,'Only a verified completed sandbox capture can be refunded.')
        if row['refund_started'] is not None and time.time() - row['refund_started'] > 5*3600:
            raise HTTPException(409,'The refund needs operator reconciliation; its safe retry window ended.')
        if row['status'] != 'REFUND_PENDING':
            db.execute('UPDATE orders SET status=?,updated=?,refund_started=? WHERE quote_id=?',('REFUND_PENDING',time.time(),time.time(),quote['id']))
            db.commit()
        result = provider.refund(row['capture_id'],row['refund_request'])
        amount = result.get('amount',{}) if isinstance(result,dict) else {}
        from decimal import Decimal, InvalidOperation
        try:
            valid = amount.get('currency_code') == 'USD' and Decimal(amount.get('value','0')) * 100 == quote['total_cents']
        except (InvalidOperation, TypeError, ValueError, AttributeError):
            valid = False
        if not valid or not result.get('id'):
            raise ProviderError('Refund amount needs operator review.')
        status = 'REFUNDED' if result.get('status') == 'COMPLETED' else 'REFUND_PENDING'
        db.execute('UPDATE orders SET refund_id=?,status=? WHERE quote_id=?',(result['id'],status,quote['id']))
        return {'status':status,'refund_id':result['id'],'quote':quote}

@app.get('/api/orders')
def orders(request: Request):
    with database() as db:
        sid,_ = owner(request,db)
        rows = db.execute('SELECT * FROM orders WHERE owner=? ORDER BY updated DESC LIMIT 20',(sid,)).fetchall()
        return [{'quote_id':r['quote_id'],'order_id':r['provider_id'],'capture_id':r['capture_id'],
                 'status':r['status'],'refund_id':r['refund_id'],'quote':owned_quote(db,sid,r['quote_id'])} for r in rows]

class Discovery(Strict):
    query: str = Field(min_length=3,max_length=300)

@app.post('/api/discover')
def discover(body: Discovery,request: Request):
    with database() as db:
        owner(request,db,True)
        if not config.CHANNEL3_KEY:
            raise HTTPException(503,'Channel3 is not connected. The local learning experience remains available.')
        row = db.execute("SELECT COALESCE(SUM(count),0) AS count FROM calls WHERE name IN ('channel3','astro')").fetchone()
        count = row['count'] if row else 0
        if count >= config.CALL_LIMIT:
            raise HTTPException(429,'The local sponsor-call limit was reached. No additional request was sent.')
        db.execute("INSERT INTO calls VALUES ('channel3',1) ON CONFLICT(name) DO UPDATE SET count=count+1")
        db.commit()
    try:
        result = httpx.post('https://api.trychannel3.com/v1/search',headers={'x-api-key':config.CHANNEL3_KEY},
                            json={'query':body.query,'limit':6},timeout=20)
        result.raise_for_status()
        payload = result.json()
    except (httpx.HTTPError,ValueError):
        raise HTTPException(502,'Channel3 search is unavailable. No fabricated results were substituted.')
    products = payload.get('products',[]) if isinstance(payload,dict) else payload
    if not isinstance(products,list):
        raise HTTPException(502,'Channel3 returned an unsupported response. No results were fabricated.')
    clean = []
    for p in products[:6]:
        if not isinstance(p,dict):
            continue
        offers = p.get('offers',[])
        offers = offers if isinstance(offers,list) else []
        def safe_offer(o):
            if not isinstance(o,dict) or not isinstance(o.get('url'),str):
                return False
            try:
                url = urlsplit(o['url'])
                return url.scheme == 'https' and bool(url.hostname) and not (url.username or url.password)
            except ValueError:
                return False
        offer = next((o for o in offers if safe_offer(o)), {})
        raw_price = offer.get('price',{})
        amount = raw_price.get('price') if isinstance(raw_price,dict) else None
        price = {'amount':amount,'currency':'USD'} if type(amount) in (int,float) and math.isfinite(amount) and 0 <= amount <= 1000000 and raw_price.get('currency') == 'USD' else None
        clean.append({'title':str(p.get('title','Untitled'))[:200], 'description':str(p.get('description',''))[:400],
                      'url':offer.get('url'), 'price':price, 'source':'Channel3',
                      'notice':'Discovery only. Retailer inventory and checkout are separate from our fictional sandbox store.'})
    return {'products':clean,'calls_remaining':max(0,config.CALL_LIMIT-count-1)}

class Feedback(Strict):
    consent: bool = Field(strict=True)
    rating: int = Field(ge=1,le=5,strict=True)
    product_id: str = Field(pattern=r'^bag-\d{2}$')
    comment: str = Field(max_length=1000,default='')

class OutcomeCompile(Strict):
    text: str = Field(min_length=3,max_length=800)
    goal: outcomes.Goal

class OutcomeText(Strict):
    query: str = Field(min_length=3,max_length=800)

class OutcomeProposal(Strict):
    goal: outcomes.Goal

class OutcomeRevision(Strict):
    revision: int = Field(ge=1,strict=True)

class OutcomeChange(OutcomeRevision):
    goal: outcomes.Goal
    text: str | None = Field(default=None,min_length=3,max_length=800)

class OutcomeInspect(OutcomeRevision):
    source_id: str = Field(min_length=1,max_length=100)

class OutcomeExclude(OutcomeRevision):
    product_id: str = Field(min_length=1,max_length=100)

def outcome_record(state, revision=None):
    record=state.get('outcome')
    if not record:
        raise HTTPException(409,'Compile a workstation mission first.')
    if record.get('source_sha256')!=outcomes.source_identity():
        raise HTTPException(409,'The planning source or catalog changed. Compile and review a new mission; the prior record remains exportable.')
    if revision is not None and revision!=record['revision']:
        raise HTTPException(409,'This plan changed. Reload before making another change.')
    return record

@app.get('/api/missions/catalog')
def outcome_catalog():
    return outcomes.public_catalog()

@app.get('/api/missions')
def outcome_status(request: Request):
    with database() as db:
        _,state=owner(request,db)
        record=state.get('outcome')
        stale=bool(record and record.get('source_sha256')!=outcomes.source_identity())
        return {'mission':None if stale or record is None else outcomes.public_record(record),'stale':stale}

@app.post('/api/missions/interpret')
def outcome_interpret(body: OutcomeText, request: Request):
    with database() as db:
        owner(request,db,True)
    return outcomes.compile_text(body.query)

@app.post('/api/missions/proposal')
def outcome_proposal(body: OutcomeProposal,request: Request):
    with database() as db:
        owner(request,db,True)
    return {'goal':{**body.goal.model_dump(),'allow_driver':False},
            'notice':'Structured proposal only. Review every field and explicitly set driver permission; no plan, fact or consent has changed.'}

@app.get('/api/missions/model-status')
def outcome_model_status():
    enabled=bool(config.CALL_LIMIT>0 and config.ASTRO_URL and config.ASTRO_KEY and config.ASTRO_CREDIT_ONLY
                 and config.ASTRO_BUDGET>0 and config.ASTRO_INPUT_RATE>0 and config.ASTRO_OUTPUT_RATE>0)
    return {'enabled':enabled,'notice':'Explicit opt-in only. Needs gateway credentials, reviewed pricing, credit-only account confirmation and a positive local budget/call ceiling. Live connectivity not inferred from configuration.'}

@app.post('/api/missions/model-interpret')
def outcome_model_interpret(body: OutcomeText,request: Request):
    with database() as db:
        owner(request,db,True)
        if not outcome_model_status()['enabled']:
            raise HTTPException(409,'Model calls are disabled. No credits were used; use the local compiler or import a reviewed proposal.')
        used=db.execute("SELECT COALESCE(SUM(count),0) AS n FROM calls WHERE name IN ('channel3','astro')").fetchone()['n']
        if used>=config.CALL_LIMIT: raise HTTPException(429,'External call ceiling reached; no request sent.')
        payload=gateway.request_body(body.query,config.ASTRO_MODEL)
        reserve=gateway.reservation(payload,config.ASTRO_INPUT_RATE,config.ASTRO_OUTPUT_RATE)
        row=db.execute("SELECT count FROM calls WHERE name='astro_reserved_microusd'").fetchone()
        spent=row['count'] if row else 0
        if spent+reserve>config.ASTRO_BUDGET: raise HTTPException(429,'Local model budget reservation exhausted; no request sent.')
        db.execute("INSERT INTO calls VALUES ('astro',1) ON CONFLICT(name) DO UPDATE SET count=count+1")
        db.execute("INSERT INTO calls VALUES ('astro_reserved_microusd',?) ON CONFLICT(name) DO UPDATE SET count=count+excluded.count",(reserve,))
        db.commit()  # Failed/uncertain requests retain reservations; never auto-retry.
    try:
        return {**gateway.call(config.ASTRO_URL,config.ASTRO_KEY,payload),'reserved_microusd':reserve}
    except gateway.GatewayError as exc:
        raise HTTPException(502,str(exc)) from exc

@app.post('/api/missions')
def outcome_compile(body: OutcomeCompile,request: Request):
    with database() as db:
        sid,state=owner(request,db,True)
        prior=state.get('outcome',{}).get('revision',0)
        state['outcome']=outcomes.create(body.text,body.goal,prior+1)
        state['version']+=1
        save(db,sid,state)
        return outcomes.public_record(state['outcome'])

def store_outcome(db,sid,state,record):
    state['outcome']=record
    state['version']+=1
    save(db,sid,state)
    return outcomes.public_record(record)

@app.post('/api/missions/revise')
def outcome_revise(body: OutcomeChange,request: Request):
    with database() as db:
        sid,state=owner(request,db,True)
        record=outcome_record(state,body.revision)
        revised=outcomes.revise(record,goal=body.goal)
        if body.text is not None: revised['text']=body.text
        return store_outcome(db,sid,state,revised)

@app.get('/api/missions/sources/{source_id}')
def outcome_source(source_id: str,request: Request):
    with database() as db:
        _,state=owner(request,db)
        record=outcome_record(state)
        source=outcomes.CATALOG['sources'].get(source_id)
        if not source: raise HTTPException(404,'Specification fixture not found.')
        obs=next(o for o in outcomes.PRODUCTS[source['product_id']]['observations'] if o['source_id']==source_id)
        if not obs['visible'] and source_id not in record['inspected']:
            raise HTTPException(409,'Inspect this missing specification before viewing its recorded evidence.')
        return source

@app.post('/api/missions/inspect')
def outcome_inspect(body: OutcomeInspect,request: Request):
    with database() as db:
        sid,state=owner(request,db,True)
        record=outcome_record(state,body.revision)
        if body.source_id not in outcomes.CATALOG['sources']:
            raise HTTPException(404,'Specification fixture not found.')
        return store_outcome(db,sid,state,outcomes.revise(record,inspect=body.source_id))

@app.post('/api/missions/exclude')
def outcome_exclude(body: OutcomeExclude,request: Request):
    with database() as db:
        sid,state=owner(request,db,True)
        record=outcome_record(state,body.revision)
        if body.product_id not in outcomes.PRODUCTS:
            raise HTTPException(404,'Component not found in the controlled catalog.')
        return store_outcome(db,sid,state,outcomes.revise(record,exclude=body.product_id))

@app.post('/api/missions/investigate')
def outcome_investigate(body: OutcomeRevision,request: Request):
    with database() as db:
        sid,state=owner(request,db,True)
        record=outcome_record(state,body.revision)
        # One explicit user action, finite fixture-only acquisition. No network.
        for _ in range(5):
            useful=[q for q in record['result']['investigations'] if q['could_improve_cost']]
            if not useful: break
            record=outcomes.revise(record,inspect=useful[0]['source_ids'][0])
        return store_outcome(db,sid,state,record)

@app.post('/api/missions/quotes')
def outcome_quote(body: OutcomeRevision,request: Request):
    with database() as db:
        sid,state=owner(request,db,True)
        record=outcome_record(state,body.revision)
        # Recompute from admitted facts at the execution boundary.
        result=outcomes.solve(outcomes.Goal(**record['goal']),record['inspected'],record['excluded'],record['previous_plan'] if record.get('objective_mode')=='repair' else None,
                              preference_history=record.get('preference_history', ()))
        plan=result['plan']
        if not plan: raise HTTPException(409,'A complete verified fixture plan is required before quoting.')
        if plan['id']!=record['result']['plan']['id']:
            raise HTTPException(409,'The computed plan changed. Review it again before quoting.')
        data={'id':str(uuid.uuid4()),'kind':'mission','version':state['version'],
              'mission_revision':record['revision'],'mission_source_sha256':outcomes.source_identity(),
              'product':{'id':'mission-'+plan['id'],'name':'Complete workstation · fictional sandbox bundle'},
              'basket':plan['items'],'item_cents':plan['total_cents'],'shipping_cents':0,'tax_cents':0,
              'total_cents':plan['total_cents'],'currency':'USD','expires_at':time.time()+900,'sandbox':True,
              'decision_snapshot':{'mission':outcomes.public_record(record),'catalog_notice':outcomes.CATALOG['notice']}}
        db.execute('INSERT INTO quotes VALUES (?,?,?)',(data['id'],sid,json.dumps(data)))
        return data

@app.get('/api/missions/export')
def outcome_export(request: Request):
    with database() as db:
        _,state=owner(request,db)
        record=state.get('outcome')
        if not record: raise HTTPException(409,'Compile a workstation mission first.')
    return JSONResponse({'mission':outcomes.public_record(record),'source_sha256':outcomes.source_identity(),
        'notice':'Private goal text may be present. No session tokens or credentials. This is not payment approval.'},
        headers={'Content-Disposition':'attachment; filename="intentcart-mission.json"'})

@app.get('/api/missions/evaluation')
def outcome_evaluation():
    path=ROOT/'data/missions-evaluation.json'
    if not path.is_file(): raise HTTPException(404,'Run scripts/evaluate_missions.py to generate local fixture evidence.')
    result=json.loads(path.read_text())
    for name,expected in result['source_sha256'].items():
        p=ROOT.parent/name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise HTTPException(409,'Mission evaluation is stale. Re-run scripts/evaluate_missions.py.')
    return {k:v for k,v in result.items() if k not in ('records','repair_records')}

@app.get('/missions')
def outcomes_page():
    return FileResponse(ROOT/'web/missions.html')

@app.get('/reliability')
def research_page():
    return FileResponse(ROOT/'web/reliability.html')

@app.get('/api/research/{kind}')
def research_evidence(kind: Literal['validity', 'reliability', 'acquisition'], full: bool = False):
    try:
        report = research.read_report(kind)
        return report if full else {k: v for k, v in report.items() if k not in ('records', 'rows')}
    except research.EvidenceError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.get('/api/reliability/traces/{trace_id}')
def research_trace(trace_id: str):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', trace_id):
        raise HTTPException(404, 'Unknown saved trace.')
    try:
        report = research.read_report('reliability')
        trace = research.exported_trace(report, trace_id)
    except research.EvidenceError as exc:
        raise HTTPException(409, str(exc)) from exc
    return JSONResponse(trace, headers={'Content-Disposition':
        f'attachment; filename="intentcart-{trace_id}.json"'})

class StudyConsent(Strict):
    consent: bool = Field(strict=True)

class StudyAnswer(Strict):
    revision: int = Field(ge=0, strict=True)
    choice: Literal['a', 'b', 'tie', 'skip']

class StudySurvey(Strict):
    revision: int = Field(ge=0, strict=True)
    product_id: str = Field(pattern=r'^(bag-\d{2}|none)$')
    burden: int = Field(ge=1, le=5, strict=True)
    total_cents: int = Field(ge=0, le=15000, strict=True)
    approval_understood: bool = Field(strict=True)

def owned_study(db, sid):
    row = db.execute('SELECT data FROM studies WHERE owner=?', (sid,)).fetchone()
    if not row:
        raise HTTPException(404, 'No consented pilot record in this session.')
    return json.loads(row['data'])

def study_view(db, sid, record):
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected
           for name, expected in record['source_sha256'].items()):
        raise HTTPException(409, 'Pilot source changed. Export or withdraw this record; do not mix study revisions.')
    view = pilot.current(record, CATALOG, record['controller_config']['decay'])
    db.execute('UPDATE studies SET data=? WHERE owner=?', (json.dumps(record), sid))
    return view

@app.get('/api/study')
def study_status(request: Request):
    with database() as db:
        sid, _ = owner(request, db)
        row = db.execute('SELECT data FROM studies WHERE owner=?', (sid,)).fetchone()
        return {'study': study_view(db, sid, json.loads(row['data'])) if row else None}

@app.post('/api/study/start')
def study_start(body: StudyConsent, request: Request):
    if not body.consent:
        raise HTTPException(422, 'Explicit adult consent is required to store pilot data.')
    with database() as db:
        sid, _ = owner(request, db, True)
        row = db.execute('SELECT data FROM studies WHERE owner=?', (sid,)).fetchone()
        record = json.loads(row['data']) if row else pilot.create(CATALOG)
        if not row:
            record['controller_config'] = DECISION_CONFIG
            record['source_sha256'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                                       for name in ('app.py', 'study.py', 'decision.py', 'learning.py',
                                                    'web/study.js', 'web/study.html', 'data/catalog.json')}
            record['events'] = []
            db.execute('INSERT INTO studies VALUES (?,?)', (sid, json.dumps(record)))
        return study_view(db, sid, record)

@app.post('/api/study/answer')
def study_answer(body: StudyAnswer, request: Request):
    with database() as db:
        sid, _ = owner(request, db, True)
        record = owned_study(db, sid)
        if body.revision != record['revision']:
            raise HTTPException(409, 'This pilot comparison has already changed. Reload the page.')
        phase = record['phase']
        try:
            pilot.respond(record, CATALOG, record['controller_config']['decay'], body.choice)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        record['events'].append({'phase': phase, 'elapsed_seconds': time.time()-record['started']})
        return study_view(db, sid, record)

@app.post('/api/study/finish')
def study_finish(body: StudySurvey, request: Request):
    with database() as db:
        sid, _ = owner(request, db, True)
        record = owned_study(db, sid)
        if record['phase'] != 'review' or body.revision != record['revision']:
            raise HTTPException(409, 'Complete the independent comparisons before this survey.')
        view = pilot.current(record, CATALOG, record['controller_config']['decay'])
        if body.product_id != 'none' and body.product_id not in [p['id'] for p in view['options']]:
            raise HTTPException(422, 'Choose a feasible pilot product or none.')
        record['survey'] = {**body.model_dump(), 'correct_total': body.total_cents == view['total_cents']}
        record['phase'] = 'complete'
        record['completed'] = time.time()
        record['revision'] += 1
        return study_view(db, sid, record)

@app.delete('/api/study')
def study_withdraw(request: Request):
    with database() as db:
        sid, _ = owner(request, db, True)
        db.execute('DELETE FROM studies WHERE owner=?', (sid,))
    return {'deleted': True, 'note': 'Local pilot record deleted. Previously downloaded copies require separate deletion.'}

@app.get('/api/study/export')
def study_export(request: Request):
    with database() as db:
        sid, _ = owner(request, db)
        record = owned_study(db, sid)
    return JSONResponse(record, headers={'Content-Disposition': 'attachment; filename="intentcart-private-pilot.json"'})

@app.get('/study')
def study_page():
    return FileResponse(ROOT/'web/study.html')

@app.post('/api/feedback')
def feedback(body: Feedback,request: Request):
    if not body.consent:
        raise HTTPException(422,'Feedback storage requires explicit consent.')
    with database() as db:
        sid,state = owner(request,db,True)
        if body.product_id not in [CATALOG[i]['id'] for i in feasible(state)]:
            raise HTTPException(422,'Choose a product from your current feasible shortlist.')
        db.execute('INSERT INTO feedback VALUES (?,?,?)',(sid,json.dumps({**body.model_dump(),'history':state['history'],'mission':state['mission']}),time.time()))
    return {'saved':True}

@app.get('/api/evidence')
def evidence():
    path = ROOT / 'data/evaluation.json'
    return json.loads(path.read_text()) if path.exists() else {'status':'not run','human_participants':0}

@app.get('/api/robustness')
def robustness():
    path = ROOT/'data/robustness-heldout.json'
    if not path.exists():
        raise HTTPException(404, 'Run the two-stage robustness evaluation first.')
    data = json.loads(path.read_text())
    # Container images include evaluation source so stale results fail closed.
    for name, expected in data['source_sha256'].items():
        source = ROOT.parent/name
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise HTTPException(409, 'Robustness evidence is stale for this source.')
    development = ROOT/'data/robustness-development.json'
    if hashlib.sha256(development.read_bytes()).hexdigest() != data['development_sha256']:
        raise HTTPException(409, 'Development evidence identity changed.')
    if (DECISION_CONFIG['development_sha256'] != data['development_sha256']
            or DECISION_CONFIG['decay'] != data['selected_decay']):
        raise HTTPException(409, 'Controller configuration differs from the evaluation.')
    return {k: v for k, v in data.items() if k != 'records'}

@app.get('/readyz')
def ready():
    result=production.configuration(config)
    try:
        with database() as db:db.execute('SELECT 1')
        storage=True
    except (OSError,sqlite3.Error):storage=False
    ready=result['configuration_ready'] and storage
    return JSONResponse({'status':'ready' if ready else 'not_ready','profile':result['profile'],'storage':storage,'scope':'Single-instance readiness, not a durability or security certification.'},status_code=200 if ready else 503)

@app.get('/healthz')
def health():
    with database() as db:
        db.execute('SELECT 1')
    return {'status':'ok','environment':'sandbox'}

@app.get('/')
def home():
    return FileResponse(ROOT/'web/agent.html')

@app.get('/learn')
@app.get('/evidence')
@app.get('/lab')
def index():
    return FileResponse(ROOT / 'web/index.html')

app.mount('/static',StaticFiles(directory=ROOT / 'web'),name='static')

# Register after the existing sandbox endpoints; the agent has no payment tool.
from . import agent_routes
import sys
agent_routes.register(sys.modules[__name__])

from . import workbench_routes
workbench_routes.register(sys.modules[__name__])

from . import document_routes
document_routes.register(sys.modules[__name__])

from . import progress
progress.register(sys.modules[__name__])

accounts.register(sys.modules[__name__])
