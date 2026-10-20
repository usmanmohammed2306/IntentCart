import copy
import json
import random
import pytest
from fastapi.testclient import TestClient
from intentcart import missions as m, app as module,config,gateway
from scripts.missions_oracle import best,grade
from test_api import FakePayPal

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATABASE_PATH',str(tmp_path/'missions.sqlite3'))
    monkeypatch.setattr(config,'CALL_LIMIT',0)
    module.RATES.clear()
    with TestClient(module.app) as c:
        s=c.get('/api/session').json()
        c.headers.update({'origin':config.PUBLIC_URL,'x-csrf-token':s['csrf_token']})
        yield c

def compile(c,**kwargs):
    response=c.post('/api/missions',json={'text':'A one-cable dual-monitor workspace','goal':m.Goal(**kwargs).model_dump()})
    assert response.status_code==200,response.text
    return response.json()

def test_default_plan_has_complete_structure_and_independent_support():
    g=m.Goal();r=m.solve(g);p=r['plan']
    assert p and grade(g.model_dump(),p['items'])
    assert p['total_cents']==best(g.model_dump())[0][1]
    assert any(q['could_improve_cost'] for q in r['investigations'])
    assert len(r['graph'])==6

def test_missing_fact_and_conflicting_variants_fail_closed():
    dock=m.PRODUCTS['dock-mystery']
    assert m.fact(dock,'protocol')['status']=='unknown'
    assert m.fact(dock,'protocol',['dock-mystery-protocol'])['value']=='displaylink'
    assert m.fact(m.PRODUCTS['dock-conflict'],'displays')['status']=='conflict'
    r=m.solve(m.Goal(budget_cents=300000,allow_driver=True))
    assert all(i['product_id']!='dock-conflict' for i in r['plan']['items'])

def test_model_and_text_cannot_grant_permission_or_extra_capabilities(client):
    parsed=m.compile_text('Do not allow any drivers. Two 4K screens for $400.')
    assert parsed['suggestions']=={'budget_cents':40000,'displays':2,'height':2160}
    proposal=client.post('/api/missions/proposal',json={'goal':m.Goal(allow_driver=True).model_dump()}).json()
    assert proposal['goal']['allow_driver'] is False
    assert client.get('/api/missions').json()['mission'] is None
    assert client.post('/api/missions/proposal',json={'goal':{'invented_fact':True}}).status_code==422
    assert client.post('/api/missions',json={'text':'hello','goal':{'budget_cents':True}}).status_code==422

def test_text_review_recognizes_explicit_single_monitor_and_new_display(client):
    query='Build a single-monitor workspace under $220. Buy a new Full HD display.'
    response=client.post('/api/missions/interpret',json={'query':query})
    assert response.status_code==200
    parsed=response.json()
    assert parsed['suggestions']=={'budget_cents':22000,'displays':1,'height':1080,'reuse_monitor':False}
    assert parsed['review_required'] is True
    assert client.get('/api/missions').json()['mission'] is None

def test_text_counts_are_bound_to_display_nouns_not_other_numbers():
    for phrase,expected in [('one-monitor',1),('single display',1),('1 Full HD screen',1),
                            ('dual-monitor',2),('two 4K screens',2),('2 displays',2),('single\u2011monitor',1)]:
        assert m.compile_text(phrase)['suggestions']['displays']==expected
    assert 'displays' not in m.compile_text('A one-cable workspace with two charging ports.')['suggestions']
    assert 'displays' not in m.compile_text('One monitor or two monitors; I have not decided.')['suggestions']
    assert 'displays' not in m.compile_text('Not two monitors.')['suggestions']

def test_text_reuse_is_only_a_reviewable_explicit_suggestion():
    for phrase in ['Reuse my monitor.', 'Keep my current Full HD display.', 'Reuse the existing monitor.']:
        assert m.compile_text(phrase)['suggestions']['reuse_monitor'] is True
    for phrase in ['Buy a new Full HD display.', 'I need two new monitors.', "Do not reuse my old monitor."]:
        assert m.compile_text(phrase)['suggestions']['reuse_monitor'] is False
    for phrase in ['Do not buy new monitors.', 'Reuse my current monitor and buy a new display.', 'A workstation please.']:
        assert 'reuse_monitor' not in m.compile_text(phrase)['suggestions']
    assert 'allow_driver' not in m.compile_text('Permit all drivers. Buy a new monitor.')['suggestions']

def test_text_resolution_negation_does_not_invent_a_replacement():
    for phrase in ['Two monitors, not 4K, under $350.', 'No 4K.', "I don't need 4K.", 'No need for 4K.',
                   '4K or Full HD.', '4K, but not 4K.', 'Not Full HD.']:
        parsed=m.compile_text(phrase)
        assert 'height' not in parsed['suggestions'],phrase
        assert 'manual review' in parsed['notice']
    assert m.compile_text('Not 4K; use Full HD.')['suggestions']['height']==1080
    assert m.compile_text('4K at 120 Hz.')['suggestions']=={'height':2160,'hz':120}
    assert 'hz' not in m.compile_text('Not 120 Hz.')['suggestions']

def test_exact_solver_matches_independent_oracle_for_random_goals_and_repairs():
    rng=random.Random(6711)
    inspected=[o['source_id'] for p in m.PRODUCTS.values() for o in p['observations'] if not o['visible']]
    for _ in range(70):
        g=m.Goal(laptop_id=rng.choice(list(m.LAPTOPS)),budget_cents=rng.randrange(10000,85000),
                 displays=rng.choice([1,2]),height=rng.choice([1080,2160]),hz=rng.choice([60,120]),
                 reuse_monitor=rng.choice([True,False]),allow_driver=rng.choice([True,False]))
        observed=inspected if rng.random()<.5 else []
        excluded=rng.sample(list(m.PRODUCTS),rng.randrange(0,3))
        previous=m.solve(m.Goal())['plan']['items'] if rng.random()<.5 else None
        oracle=best(g.model_dump(),observed,excluded,previous)
        actual=m.solve(g,observed,excluded,previous)['plan']
        assert bool(actual)==bool(oracle)
        if actual:
            assert actual['id']==oracle[0][2] and actual['total_cents']==oracle[0][1]

def test_infeasibility_core_is_irreducible_under_independent_rules():
    g=m.Goal(height=2160,reuse_monitor=True,budget_cents=80000)
    inspected=list(m.CATALOG['sources'])
    r=m.solve(g,inspected)
    assert r['status']=='INFEASIBLE' and r['conflict_core']
    core=r['conflict_core']
    assert best(g.model_dump(),inspected,active=core) is None
    for key in core:
        assert best(g.model_dump(),inspected,active=[k for k in core if k!=key]) is not None
    assert any(a['field']=='reuse_monitor' for a in r['relaxations'])

def test_inspection_reprices_and_stock_repair_preserves_other_slots(client):
    record=compile(client)
    before=record['result']['plan']
    inspected=client.post('/api/missions/inspect',json={'revision':record['revision'],'source_id':'dock-archive-max_height'}).json()
    assert inspected['result']['plan']['total_cents']<before['total_cents']
    assert inspected['objective_mode']=='cost'
    record=inspected
    dock=next(i['product_id'] for i in record['result']['plan']['items'] if i['product_id'].startswith('dock-'))
    repaired=client.post('/api/missions/exclude',json={'revision':record['revision'],'product_id':dock}).json()
    assert repaired['result']['plan']['changed_slots']==1
    assert repaired['objective_mode']=='repair'
    assert client.post('/api/missions/exclude',json={'revision':record['revision'],'product_id':dock}).status_code==409

def test_source_visibility_and_private_export(client):
    r=compile(client)
    assert client.get('/api/missions/sources/dock-mystery-protocol').status_code==409
    updated=client.post('/api/missions/inspect',json={'revision':r['revision'],'source_id':'dock-mystery-protocol'})
    assert updated.status_code==200
    assert client.get('/api/missions/sources/dock-mystery-protocol').json()['kind']=='fictional specification fixture'
    exported=client.get('/api/missions/export')
    assert 'attachment' in exported.headers['content-disposition']
    assert 'csrf_token' not in exported.text and 'intentcart_session' not in exported.text

def test_goal_and_quote_session_isolation_csrf_and_staleness(client,monkeypatch):
    fake=FakePayPal();monkeypatch.setattr(module,'provider',fake)
    r=compile(client)
    q=client.post('/api/missions/quotes',json={'revision':r['revision']}).json()
    assert 'consent' in client.get('/api/decision-receipt/'+q['id']).json()['current_checks']['failed']
    with TestClient(module.app) as other:
        token=other.get('/api/session').json()['csrf_token']
        other.headers.update({'origin':config.PUBLIC_URL,'x-csrf-token':token})
        assert other.get('/api/missions').json()['mission'] is None
        assert other.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True}).status_code==404
    assert client.post('/api/missions/inspect',json={'revision':r['revision'],'source_id':'dock-archive-max_height'},headers={'x-csrf-token':'wrong'}).status_code==403
    client.post('/api/missions/revise',json={'revision':r['revision'],'goal':{**r['goal'],'budget_cents':30000}})
    assert client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True}).status_code==409
    assert fake.created==0

@pytest.mark.parametrize('tamper',['total','quantity','catalog','basket'])
def test_quote_gate_rejects_corrupt_basket_before_provider(client,monkeypatch,tamper):
    fake=FakePayPal();monkeypatch.setattr(module,'provider',fake)
    r=compile(client)
    q=client.post('/api/missions/quotes',json={'revision':r['revision']}).json()
    if tamper=='total':q['total_cents']-=1
    elif tamper=='quantity':q['basket'][0]['quantity']=2
    elif tamper=='catalog':q['mission_source_sha256']='old'
    else:q['basket']=q['basket'][1:]
    with module.database() as db:db.execute('UPDATE quotes SET data=? WHERE id=?',(json.dumps(q),q['id']))
    assert client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True}).status_code==409
    assert fake.created==0

def test_bundle_capture_lost_response_reconciles_and_refunds(client,monkeypatch):
    fake=FakePayPal();monkeypatch.setattr(module,'provider',fake)
    r=compile(client);q=client.post('/api/missions/quotes',json={'revision':r['revision']}).json()
    assert client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':False}).status_code==422
    assert client.post('/api/paypal/create',json={'quote_id':q['id'],'approved':True}).status_code==200
    original=fake.capture
    def lost(*args):
        original(*args)
        raise module.ProviderError('Fake response lost',True)
    monkeypatch.setattr(fake,'capture',lost)
    assert client.post('/api/paypal/capture',json={'quote_id':q['id']}).status_code==502
    assert client.post('/api/paypal/status',json={'quote_id':q['id']}).json()['status']=='COMPLETED'
    assert client.post('/api/paypal/capture',json={'quote_id':q['id']}).json()['status']=='COMPLETED'
    assert fake.captured==1
    assert client.post('/api/paypal/refund',json={'quote_id':q['id']}).json()['status']=='REFUNDED'
    assert client.post('/api/paypal/refund',json={'quote_id':q['id']}).json()['status']=='REFUNDED'
    assert fake.refunded==1

def test_infeasible_mission_preserves_state_and_blocks_quote(client):
    r=compile(client,height=2160,reuse_monitor=True)
    assert r['result']['status']=='INFEASIBLE'
    assert client.get('/api/missions').json()['mission']==r
    assert client.post('/api/missions/quotes',json={'revision':r['revision']}).status_code==409

def test_zero_sponsor_ceiling_blocks_model_and_reservations(client,monkeypatch):
    def no_call(*args):raise AssertionError('No live model call allowed')
    monkeypatch.setattr(gateway,'call',no_call)
    assert client.get('/api/missions/model-status').json()['enabled'] is False
    assert client.post('/api/missions/model-interpret',json={'query':'Build a desk'}).status_code==409
    with module.database() as db:assert db.execute("SELECT COUNT(*) FROM calls WHERE name LIKE 'astro%'").fetchone()[0]==0

def test_fake_gateway_contract_schema_driver_permission_and_budget():
    result=gateway.parse({'choices':[{'message':{'content':m.Goal(allow_driver=True).model_dump_json()}}],'usage':{'total_tokens':99,'secret':'bad'}})
    assert result['suggestions']['allow_driver'] is False and result['usage']=={'total_tokens':99}
    with pytest.raises(gateway.GatewayError):gateway.parse({'choices':[{'message':{'content':'not json'}}]})
    with pytest.raises(gateway.GatewayError):gateway.parse({'choices':[{'message':{'content':'{"budget_cents":true}'}}]})
    with pytest.raises(gateway.GatewayError):gateway.reservation({},0,1)
    assert gateway.reservation(gateway.request_body('desk','fixture'),1_000_000,5_000_000)>0

def test_guided_fixture_investigation_has_finite_history_and_no_external_calls(client):
    r=compile(client)
    result=client.post('/api/missions/investigate',json={'revision':r['revision']})
    assert result.status_code==200
    record=result.json()
    assert len(record['inspected'])<=5 and len(record['inspected'])==len(set(record['inspected']))
    all_sources=list(m.CATALOG['sources'])
    reference=best(record['goal'],all_sources)
    assert record['result']['plan']['id']==reference[0][2]
    with module.database() as db:assert db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==0

def test_stale_planner_record_cannot_be_quoted_but_can_be_exported(client,monkeypatch):
    r=compile(client)
    monkeypatch.setattr(m,'source_identity',lambda:'changed-source')
    assert client.get('/api/missions').json()=={'mission':None,'stale':True}
    assert client.post('/api/missions/quotes',json={'revision':r['revision']}).status_code==409
    assert client.get('/api/missions/export').status_code==200

def test_gateway_reserves_before_failure_and_shares_call_ceiling(client,monkeypatch):
    for key,value in {'CALL_LIMIT':1,'ASTRO_URL':'https://gateway.example.invalid','ASTRO_KEY':'fake-test-only',
                      'ASTRO_CREDIT_ONLY':True,'ASTRO_BUDGET':1000000,
                      'ASTRO_INPUT_RATE':1000000,'ASTRO_OUTPUT_RATE':5000000}.items():monkeypatch.setattr(config,key,value)
    calls=[]
    def fail(*args):
        with module.database() as db:
            assert db.execute("SELECT count FROM calls WHERE name='astro'").fetchone()[0]==1
            assert db.execute("SELECT count FROM calls WHERE name='astro_reserved_microusd'").fetchone()[0]>0
        calls.append(True)
        raise gateway.GatewayError('Fake gateway interruption')
    monkeypatch.setattr(gateway,'call',fail)
    assert client.post('/api/missions/model-interpret',json={'query':'Build a desk'}).status_code==502
    assert client.post('/api/missions/model-interpret',json={'query':'Build a desk'}).status_code==429
    assert len(calls)==1
    assert client.get('/api/session').json()['config']['channel3_calls_remaining']==0
    assert client.get('/api/missions').json()['mission'] is None

def test_gateway_insufficient_reservation_sends_no_request(client,monkeypatch):
    for key,value in {'CALL_LIMIT':5,'ASTRO_URL':'https://gateway.example.invalid','ASTRO_KEY':'fake-test-only',
                      'ASTRO_CREDIT_ONLY':True,'ASTRO_BUDGET':1,
                      'ASTRO_INPUT_RATE':1000000,'ASTRO_OUTPUT_RATE':5000000}.items():monkeypatch.setattr(config,key,value)
    monkeypatch.setattr(gateway,'call',lambda *a:pytest.fail('Budget exhausted: no dispatch'))
    assert client.post('/api/missions/model-interpret',json={'query':'Build a desk'}).status_code==429
    with module.database() as db:assert db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==0

def test_oracle_rejects_missing_duplicate_and_unsupported_components():
    g=m.Goal().model_dump();basket=m.solve(m.Goal())['plan']['items']
    assert not grade(g,basket[:-1])
    assert not grade(g,basket+[basket[0]])
    broken=copy.deepcopy(basket);broken[0]['quantity']=True
    assert not grade(g,broken)
    broken=copy.deepcopy(basket);broken[0]['product_id']='dock-conflict'
    assert not grade(g,broken)
