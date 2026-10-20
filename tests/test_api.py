import copy
import httpx
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from intentcart import app as module
from intentcart import config
from intentcart.paypal import ProviderError, verify_capture

MISSION={'text':'comfortable rain laptop commuter','budget_cents':9000,'laptop_inches':16,'min_capacity_l':20}

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATABASE_PATH',str(tmp_path/'test.sqlite3'))
    module.RATES.clear()
    with TestClient(module.app) as client:
        token=client.get('/api/session').json()['csrf_token']
        client.headers.update({'origin':config.PUBLIC_URL,'x-csrf-token':token})
        yield client

def start(client):
    r=client.post('/api/mission',json=MISSION);assert r.status_code==200
    return r.json()

def new_quote(client):
    state=start(client)
    return client.post('/api/quotes',json={'product_id':state['ranked'][0]['id'],'version':state['version']}).json()

class FakePayPal:
    def __init__(self):self.created=0;self.captured=0;self.refunded=0;self.orders={};self.fail_create=False;self.approved=True
    def create(self,quote,key):
        self.created+=1
        self.keys=getattr(self,'keys',[])+[key]
        if self.fail_create:raise ProviderError('interrupted',True)
        payload={'id':'ORDER-1','status':'APPROVED' if self.approved else 'CREATED','purchase_units':[{'reference_id':quote['id']} ]}
        self.quote=quote;self.orders['ORDER-1']=payload
        return payload
    def get(self,order):return copy.deepcopy(self.orders[order])
    def capture(self,order,key):
        self.captured+=1
        payload=self.orders[order];payload['status']='COMPLETED'
        payload['purchase_units'][0]['payments']={'captures':[{'id':'CAPTURE-1','status':'COMPLETED','amount':{'currency_code':'USD','value':f"{self.quote['total_cents']/100:.2f}"}}]}
        return copy.deepcopy(payload)
    def refund(self,capture,key):
        self.refunded+=1
        return {'id':'REFUND-1','status':'COMPLETED','amount':{'currency_code':'USD','value':f"{self.quote['total_cents']/100:.2f}"}}

@pytest.fixture
def paypal(monkeypatch):
    fake=FakePayPal();monkeypatch.setattr(module,'provider',fake);return fake

def test_mission_filters_total_shipping_laptop_and_capacity(client):
    state=start(client)
    assert state['ranked']
    for p in state['ranked']:
        assert p['total_cents']<=MISSION['budget_cents']
        assert p['laptop_inches']>=16 and p['capacity_l']>=20

def test_csrf_and_origin_enforced(client):
    assert client.post('/api/mission',json=MISSION,headers={'origin':'https://evil.example'}).status_code==403
    assert client.post('/api/mission',json=MISSION,headers={'x-csrf-token':'wrong'}).status_code==403

def test_unfeasible_and_arbitrary_price_input_rejected(client):
    assert client.post('/api/mission',json={**MISSION,'budget_cents':3000,'laptop_inches':17}).status_code==422
    assert client.post('/api/mission',json={**MISSION,'price_cents':1}).status_code==422
    assert client.post('/api/mission',json={**MISSION,'budget_cents':True}).status_code==422

def test_answer_idempotency_and_conflict(client):
    s=start(client);body={'question_id':s['question']['id'],'choice':'a'}
    one=client.post('/api/answer',json=body).json()
    two=client.post('/api/answer',json=body).json()
    assert one['version']==two['version'] and len(two['history'])==1
    assert client.post('/api/answer',json={**body,'choice':'b'}).status_code==409

def test_stale_comparison_rejected(client):
    old=start(client);start(client)
    assert client.post('/api/answer',json={'question_id':old['question']['id'],'choice':'a'}).status_code==409

def test_four_answers_end_comparisons(client):
    state=start(client)
    for _ in range(4):
        state=client.post('/api/answer',json={'question_id':state['question']['id'],'choice':'a'}).json()
    assert state['question'] is None and state['answered']==4

def test_stock_shock_preserves_evidence_and_invalidates_quote(client,paypal):
    q=new_quote(client);s=client.get('/api/session').json()['state']
    changed=client.post('/api/unavailable',json={'product_id':s['ranked'][0]['id'],'version':s['version']}).json()
    assert q['product']['id'] not in [p['id'] for p in changed['ranked']]
    assert client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True}).status_code==409
    assert paypal.created==0

def test_quote_owner_isolation(client,paypal):
    q=new_quote(client)
    with TestClient(module.app) as other:
        token=other.get('/api/session').json()['csrf_token']
        other.headers.update({'origin':config.PUBLIC_URL,'x-csrf-token':token})
        assert other.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True}).status_code==404

def test_approval_required_and_create_idempotent(client,paypal):
    q=new_quote(client)
    assert client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':False}).status_code==422
    for _ in range(2):assert client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True}).json()['id']=='ORDER-1'
    assert paypal.created==1

def test_interrupted_create_reuses_durable_request_key(client,paypal):
    q=new_quote(client);paypal.fail_create=True
    r=client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    assert r.status_code==502 and r.json()['uncertain']
    paypal.fail_create=False
    assert client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True}).status_code==200
    assert paypal.keys[0]==paypal.keys[1]

def test_unapproved_paypal_order_not_captured(client,paypal):
    q=new_quote(client);paypal.approved=False
    client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    assert client.post('/api/paypal/capture',json={'quote_id':q['id']}).status_code==409
    assert paypal.captured==0

def test_capture_and_refund_idempotent_and_survive_session_reload(client,paypal):
    q=new_quote(client);client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    for _ in range(2):assert client.post('/api/paypal/capture',json={'quote_id':q['id']}).json()['status']=='COMPLETED'
    assert paypal.captured==1
    assert client.get('/api/orders').json()[0]['capture_id']=='CAPTURE-1'
    for _ in range(2):assert client.post('/api/paypal/refund',json={'quote_id':q['id']}).json()['status']=='REFUNDED'
    assert paypal.refunded==1
    assert client.post('/api/paypal/status',json={'quote_id':q['id']}).json()['status']=='REFUNDED'

def test_captured_mismatch_never_presented_as_success(client,paypal):
    q=new_quote(client);client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    paypal.capture('ORDER-1','test')
    paypal.orders['ORDER-1']['purchase_units'][0]['payments']['captures'][0]['amount']['value']='0.01'
    assert client.post('/api/paypal/status',json={'quote_id':q['id']}).status_code==502
    assert client.get('/api/orders').json()[0]['status']=='CREATED'

def test_actual_paypal_refunded_capture_status_is_preserved(client,paypal):
    q=new_quote(client);client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    client.post('/api/paypal/capture',json={'quote_id':q['id']})
    client.post('/api/paypal/refund',json={'quote_id':q['id']})
    paypal.orders['ORDER-1']['purchase_units'][0]['payments']['captures'][0]['status']='REFUNDED'
    receipt=client.post('/api/paypal/status',json={'quote_id':q['id']}).json()
    assert receipt['status']=='REFUNDED' and receipt['refund_id']=='REFUND-1'
    assert client.post('/api/paypal/capture',json={'quote_id':q['id']}).json()['status']=='REFUNDED'
    assert paypal.captured==1

def test_contradictory_provider_capture_is_not_success(client,paypal):
    q=new_quote(client);client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    paypal.capture('ORDER-1','test');paypal.orders['ORDER-1']['status']='APPROVED'
    assert client.post('/api/paypal/status',json={'quote_id':q['id']}).status_code==502

def test_completed_capture_reconciles_even_after_preferences_change(client,paypal):
    q=new_quote(client);client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    paypal.capture('ORDER-1','test');start(client)
    assert client.post('/api/paypal/capture',json={'quote_id':q['id']}).json()['status']=='COMPLETED'

def test_body_limit_and_feedback_consent(client):
    assert client.post('/api/mission',content='x'*65537).status_code==413
    state=start(client)
    assert client.post('/api/feedback',json={'consent':False,'product_id':state['ranked'][0]['id'],'rating':4}).status_code==422

def test_sensitive_config_not_exposed(client,monkeypatch):
    monkeypatch.setattr(config,'CLIENT_SECRET','super-secret-value')
    monkeypatch.setattr(config,'CHANNEL3_KEY','private-channel3-key')
    text=client.get('/api/session').text
    assert 'super-secret-value' not in text and 'private-channel3-key' not in text

def test_sponsor_budget_blocks_external_request(client,monkeypatch):
    monkeypatch.setattr(config,'CHANNEL3_KEY','configured');monkeypatch.setattr(config,'CALL_LIMIT',0)
    assert client.post('/api/discover',json={'query':'backpack'}).status_code==429

def test_discovery_sanitizes_offers_and_limits_credit_calls(client,monkeypatch):
    monkeypatch.setattr(config,'CHANNEL3_KEY','configured');monkeypatch.setattr(config,'CALL_LIMIT',1)
    payload=[{'title':'Real backpack','offers':[{'url':'javascript:alert(1)'},{'url':'https://shop.example/pack','price':{'price':87.99,'currency':'USD'}}]},None,{'title':'No unsafe offer','offers':[{'url':'https://user:secret@shop.example/pack'}]}]
    calls=[]
    def fake_post(url,**kwargs):
        calls.append(kwargs)
        return httpx.Response(200,json=payload,request=httpx.Request('POST',url))
    monkeypatch.setattr(module.httpx,'post',fake_post)
    r=client.post('/api/discover',json={'query':'backpack'});assert r.status_code==200
    products=r.json()['products']
    assert len(products)==2 and products[0]['url']=='https://shop.example/pack'
    assert products[0]['price']=={'amount':87.99,'currency':'USD'} and products[1]['url'] is None
    assert client.post('/api/discover',json={'query':'backpack'}).status_code==429
    assert len(calls)==1 and calls[0]['json']['limit']==6

def test_malformed_discovery_response_reports_provider_failure(client,monkeypatch):
    monkeypatch.setattr(config,'CHANNEL3_KEY','configured');monkeypatch.setattr(config,'CALL_LIMIT',1)
    monkeypatch.setattr(module.httpx,'post',lambda url,**kw:httpx.Response(200,json={'products':None},request=httpx.Request('POST',url)))
    assert client.post('/api/discover',json={'query':'backpack'}).status_code==502
    assert client.post('/api/discover',json={'query':'backpack'}).status_code==429

def test_browser_security_headers(client):
    r=client.get('/healthz')
    assert r.headers['x-frame-options']=='DENY'
    assert "object-src 'none'" in r.headers['content-security-policy']

def test_text_values_cannot_grant_payment_or_feedback_consent(client):
    q = new_quote(client)
    assert client.post('/api/paypal/create', json={'quote_id': q['id'], 'approved': 'true'}).status_code == 422
    assert client.post('/api/feedback', json={'consent': 1, 'product_id': q['product']['id'], 'rating': 4}).status_code == 422

@pytest.mark.parametrize('captures,code', [([],502), (None,502), ([{}],502), ([{'id':'PENDING-1','status':'PENDING'}],200)])
def test_completed_order_without_completed_capture_is_not_success(client,paypal,captures,code):
    q = new_quote(client)
    client.post('/api/paypal/create', json={'quote_id':q['id'],'approved':True})
    payload = paypal.orders['ORDER-1']
    payload['status'] = 'COMPLETED'
    payload['purchase_units'][0]['payments'] = {'captures':captures}
    response = client.post('/api/paypal/status',json={'quote_id':q['id']})
    assert response.status_code == code
    if code == 200:
        assert response.json()['status'] == 'CAPTURE_PENDING'
    assert client.get('/api/orders').json()[0]['status'] != 'COMPLETED'

def test_pending_refund_status_checks_cannot_extend_retry_window(client,paypal,monkeypatch):
    q = new_quote(client)
    client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    client.post('/api/paypal/capture',json={'quote_id':q['id']})
    def interrupted(*args):
        raise ProviderError('interrupted',True)
    monkeypatch.setattr(paypal,'refund',interrupted)
    assert client.post('/api/paypal/refund',json={'quote_id':q['id']}).status_code == 502
    with module.database() as db:
        db.execute('UPDATE orders SET refund_started=? WHERE quote_id=?',(module.time.time()-6*3600,q['id']))
    assert client.post('/api/paypal/status',json={'quote_id':q['id']}).json()['status'] == 'REFUND_PENDING'
    assert client.post('/api/paypal/refund',json={'quote_id':q['id']}).status_code == 409

def test_interrupted_capture_keeps_key_and_blocks_late_retry(client,paypal,monkeypatch):
    q = new_quote(client)
    client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True})
    keys = []
    def interrupted(order,key):
        keys.append(key)
        raise ProviderError('interrupted',True)
    monkeypatch.setattr(paypal,'capture',interrupted)
    for _ in range(2):
        assert client.post('/api/paypal/capture',json={'quote_id':q['id']}).status_code == 502
    assert len(keys) == 2 and keys[0] == keys[1]
    with module.database() as db:
        db.execute('UPDATE orders SET capture_started=? WHERE quote_id=?',(module.time.time()-6*3600,q['id']))
    client.post('/api/paypal/status',json={'quote_id':q['id']})
    assert client.post('/api/paypal/capture',json={'quote_id':q['id']}).status_code == 409
    assert len(keys) == 2

def test_legacy_database_upgrade_preserves_receipts_and_blocks_unknown_retry(client):
    q = new_quote(client)
    with module.database() as db:
        sid = db.execute('SELECT owner FROM quotes WHERE id=?',(q['id'],)).fetchone()['owner']
        db.execute('DROP TABLE orders')
        db.execute('''CREATE TABLE orders (quote_id TEXT PRIMARY KEY,owner TEXT,request_id TEXT,
            capture_request TEXT,refund_request TEXT,provider_id TEXT,capture_id TEXT,refund_id TEXT,status TEXT,updated REAL)''')
        db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?)',(q['id'],sid,'create','capture','refund','ORDER-OLD','CAP-OLD',None,'REFUND_PENDING',module.time.time()))
    module.initialize()
    receipt = client.get('/api/orders').json()[0]
    assert receipt['order_id'] == 'ORDER-OLD' and receipt['status'] == 'REFUND_PENDING'
    assert client.post('/api/paypal/refund',json={'quote_id':q['id']}).status_code == 409

def test_rehearsal_preview_is_read_only_and_preserves_preferences(client,paypal):
    state=start(client)
    state=client.post('/api/answer',json={'question_id':state['question']['id'],'choice':'a'}).json()
    worlds=client.get('/api/rehearsal').json()
    assert len(worlds['worlds'])==4 and all(w['preferences_retained'] for w in worlds['worlds'])
    assert client.get('/api/session').json()['state']==state
    assert paypal.created==paypal.captured==paypal.refunded==0

def test_shipping_world_changes_server_quote_and_invalidates_old_approval(client,paypal):
    quote=new_quote(client)
    before=client.get('/api/session').json()['state']
    changed=client.post('/api/scenario',json={'kind':'shipping','version':before['version']}).json()
    assert changed['history']==before['history'] and changed['shipping_surcharge_cents']==1000
    assert client.post('/api/paypal/create',json={'quote_id':quote['id'],'approved':True}).status_code==409
    product=changed['ranked'][0]
    fresh=client.post('/api/quotes',json={'product_id':product['id'],'version':changed['version']}).json()
    assert fresh['total_cents']==module.total(module.BY_ID[product['id']])+1000
    assert fresh['shipping_cents']==module.total(module.BY_ID[product['id']])-fresh['item_cents']+1000
    assert paypal.created==0

def test_no_purchase_world_retains_learning_and_blocks_quote(client,paypal):
    state=start(client)
    state=client.post('/api/answer',json={'question_id':state['question']['id'],'choice':'b'}).json()
    changed=client.post('/api/scenario',json={'kind':'no_purchase','version':state['version']}).json()
    assert changed['ranked']==[] and changed['question'] is None and changed['history']==state['history']
    assert len(changed['weights'])==7
    assert client.post('/api/quotes',json={'product_id':'bag-01','version':changed['version']}).status_code==409
    assert client.get('/api/session').json()['state']==changed
    assert paypal.created==0

def test_scenario_rejects_stale_version_invalid_kind_and_missing_csrf(client):
    state=start(client)
    assert client.post('/api/scenario',json={'kind':'shipping','version':state['version']-1}).status_code==409
    assert client.post('/api/scenario',json={'kind':'arbitrary','version':state['version']}).status_code==422
    assert client.post('/api/scenario',json={'kind':'stock','version':state['version']},headers={'x-csrf-token':'wrong'}).status_code==403

def test_decision_snapshot_remains_frozen_after_world_changes(client):
    quote=new_quote(client)
    receipt=client.get('/api/decision-receipt/'+quote['id']).json()
    state=client.get('/api/session').json()['state']
    client.post('/api/scenario',json={'kind':'budget','version':state['version']})
    after=client.get('/api/decision-receipt/'+quote['id']).json()
    assert receipt['snapshot_sha256']==after['snapshot_sha256']
    assert after['quote']['decision_snapshot']==quote['decision_snapshot']
    assert 'version' in after['current_checks']['failed']
    assert after['order_status']=='NO_ORDER'
    assert 'consent' in receipt['current_checks']['failed']
    export=client.get('/api/decision-receipt/'+quote['id']+'?download=true')
    assert export.status_code==200 and export.headers['content-disposition'].startswith('attachment;')
    assert export.json()['snapshot_sha256']==receipt['snapshot_sha256']

def test_decision_receipt_and_proposal_owner_isolation(client):
    quote=new_quote(client)
    with TestClient(module.app) as other:
        token=other.get('/api/session').json()['csrf_token']
        other.headers.update({'origin':config.PUBLIC_URL,'x-csrf-token':token})
        assert other.get('/api/decision-receipt/'+quote['id']).status_code==404
        assert other.post('/api/challenges',json={'quote_id':quote['id']}).status_code==404

def test_challenge_suite_exercises_shared_gate_without_recording_approval(client,paypal):
    quote=new_quote(client)
    result=client.post('/api/challenges',json={'quote_id':quote['id']}).json()
    assert result['matched']==result['total']==7
    assert sum(c['eligible'] for c in result['cases'])==1
    assert client.get('/api/orders').json()==[]
    assert paypal.created==paypal.captured==paypal.refunded==0
    assert client.post('/api/paypal/create',json={'quote_id':quote['id'],'approved':False}).status_code==422

@pytest.mark.parametrize('change,reason',[({'total_cents':1},'amount'),({'product_id':'bag-99'},'product'),({'currency':'EUR'},'currency'),({'approved':False},'consent')])
def test_custom_proposal_is_checked_without_execution(client,paypal,change,reason):
    quote=new_quote(client)
    proposal={'quote_id':quote['id'],'product_id':quote['product']['id'],'total_cents':quote['total_cents'],
              'version':quote['version'],'currency':'USD','approved':True,**change}
    result=client.post('/api/proposals/check',json=proposal).json()
    assert not result['eligible'] and reason in result['failed']
    assert paypal.created==0 and client.get('/api/orders').json()==[]

def test_actual_creation_reuses_gate_and_rejects_corrupt_server_quote(client,paypal):
    quote=new_quote(client)
    with module.database() as db:
        quote['total_cents']-=1
        db.execute('UPDATE quotes SET data=? WHERE id=?',(module.json.dumps(quote),quote['id']))
    response=client.post('/api/paypal/create',json={'quote_id':quote['id'],'approved':True})
    assert response.status_code==409 and 'pricing' in response.json()['detail']
    assert paypal.created==0

def test_capture_committed_but_response_lost_reconciles_without_second_capture(client,paypal,monkeypatch):
    quote=new_quote(client)
    client.post('/api/paypal/create',json={'quote_id':quote['id'],'approved':True})
    actual=paypal.capture
    def committed_but_lost(order,key):
        actual(order,key)
        raise ProviderError('Simulated response lost after fake provider committed.',True)
    monkeypatch.setattr(paypal,'capture',committed_but_lost)
    assert client.post('/api/paypal/capture',json={'quote_id':quote['id']}).status_code==502
    assert client.post('/api/paypal/status',json={'quote_id':quote['id']}).json()['status']=='COMPLETED'
    assert client.post('/api/paypal/capture',json={'quote_id':quote['id']}).json()['status']=='COMPLETED'
    assert paypal.captured==1

def test_saved_recovery_evidence_matches_current_source(client):
    response=client.get('/api/lab-evidence')
    assert response.status_code==200
    assert response.json()['live_provider_calls']==0
    assert all(response.json()['checks'].values())

def test_stale_recovery_evidence_is_not_presented_as_current(client,tmp_path,monkeypatch):
    (tmp_path/'data').mkdir()
    (tmp_path/'data/lab-evaluation.json').write_text('{"source_sha256":{}}')
    monkeypatch.setattr(module,'ROOT',tmp_path)
    assert client.get('/api/lab-evidence').status_code==409


@pytest.mark.parametrize('choices', [[], ['a'], ['b', 'tie', 'skip'], ['a', 'a', 'b', 'b']])
def test_ranking_only_rehearsal_matches_previous_full_question_path(client, monkeypatch, choices):
    from scripts.benchmarks.learning_v2_1 import choose_pair as reference_pair
    state = start(client)
    for choice in choices:
        state = client.post('/api/answer', json={'question_id': state['question']['id'], 'choice': choice}).json()
    compute = module.compute
    with monkeypatch.context() as previous:
        previous.setattr(module, 'choose_pair', reference_pair)
        previous.setattr(module, 'compute', lambda state, **kwargs: compute(state, include_question=True))
        expected = client.get('/api/rehearsal')
    actual = client.get('/api/rehearsal')
    assert expected.status_code == actual.status_code == 200
    assert expected.json() == actual.json()


def test_rehearsal_never_selects_questions_it_does_not_return(client, monkeypatch):
    start(client)
    def unused_question(*args, **kwargs):
        raise AssertionError('A read-only world preview must not select an unused question.')
    monkeypatch.setattr(module, 'choose_pair', unused_question)
    result = client.get('/api/rehearsal')
    assert result.status_code == 200 and len(result.json()['worlds']) == 4
