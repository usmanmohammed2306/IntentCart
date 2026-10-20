from copy import deepcopy
import json
from scripts import run_live_validation as live
from scripts import analyze_workstation_pilot as pilot
import pytest

def test_model_transport_wrapper_does_not_extract_actions_from_prose():
    from intentcart import agent, gateway
    action='{"action":"search"}'
    assert agent.Action.model_validate_json(gateway.action_json('```json\n'+action+'\n```')).action=='search'
    for raw in ('Explanation\n```json\n'+action+'\n```', action+'\n'+action, '[]', '```json\n'+action+'\n```\nExtra', '```json\n'+action+'\n```\n```json\n'+action+'\n```'):
        with pytest.raises(ValueError):gateway.action_json(raw)
    with pytest.raises(ValueError):
        agent.Action.model_validate_json(gateway.action_json('{"action":"pay","approved":true}'))

def test_sandbox_guard_amount_host_and_durable_ceiling(tmp_path):
    import httpx
    from scripts.sandbox_budget_server import Ledger, guard_request
    path='/v2/checkout/orders'
    body={'purchase_units':[{'amount':{'currency_code':'USD','value':'279.00'}}]}
    guard_request(httpx.Request('POST','https://api-m.sandbox.paypal.com'+path,json=body),27900)
    for url in ('https://api-m.paypal.com'+path,'http://api-m.sandbox.paypal.com'+path,'https://api-m.sandbox.paypal.com/not-approved'):
        with pytest.raises(RuntimeError):guard_request(httpx.Request('POST',url,json=body),27900)
    body['purchase_units'][0]['amount']['value']='279.01'
    with pytest.raises(RuntimeError):guard_request(httpx.Request('POST','https://api-m.sandbox.paypal.com'+path,json=body),27900)
    ledger_path=tmp_path/'calls.sqlite3'
    ledger=Ledger(ledger_path,2)
    ledger.reserve('POST',path)
    Ledger(ledger_path,2).reserve('GET',path+'/saved')
    with pytest.raises(RuntimeError,match='ceiling'):Ledger(ledger_path,2).reserve('POST',path)

def test_external_audit_preserves_refund_and_failure_denominators(tmp_path):
    from scripts import audit_external_validation as audit
    from pathlib import Path
    import shutil
    for name in ('live-validation.json','workstation-sandbox-verification.json'):
        shutil.copy2(audit.ROOT/'submission'/name,tmp_path/name)
    assert audit.evaluate(tmp_path)['completed_bounded_external_milestones']==[78,79,81,84]
    path=tmp_path/'workstation-sandbox-verification.json'
    original=path.read_text();data=json.loads(original)
    data['refund_amount']['value']='278.99';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='refund amount'):audit.evaluate(tmp_path)
    path.write_text(original)
    path=tmp_path/'live-validation.json';data=json.loads(path.read_text())
    data['strict_outputs_rejected']=0;path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='failed model requests'):audit.evaluate(tmp_path)


def task():
    return {'id':'public-fixture','query':'Authored fixture','goal':{},'catalog_kind':'fixture','inspection_budget':16,'driver_answer':False}


def fake_run(client,tasks,max_requests,expected_model,base_url,controllers=('direct','guided')):
    required=1 if max_requests==1 else 2
    attempts=[{'http_status':200,'model_id':expected_model,'model_id_basis':'provider_response',
               'reserved_microusd':120,'usage':{'prompt_tokens':10,'completion_tokens':5}} for _ in range(required)]
    done=required==2
    record={'task_id':tasks[0]['id'],'controller':controllers[0],
            'status':'RECOMMENDED' if done else 'INCOMPLETE_REQUEST_CAP',
            'supported_recommendation':done,'attempts':attempts,'errors':[],
            'events':[{'action':{'action':'recommend'},'response':{'basket_id':'fixture-decision'}}] if done else []}
    return {'schema':'intentcart-live-pilot/1','request_attempts':required,'records':[record]}


def test_matched_repeated_runner_shares_one_ceiling_and_counterbalances(monkeypatch):
    monkeypatch.setattr(live,'run',fake_run)
    report=live.execute(None,[task()],2,48,'mock-model','http://localhost',evidence_kind='mock_provider')
    assert report['request_attempts']==9
    assert report['compatibility_response_observed'] and report['all_comparison_trials_terminal_without_cap_or_error']
    trials=report['canonical_transcripts']['trials']
    assert [(r['repeat_id'],r['controller']) for r in trials]==[('repeat-1','direct'),('repeat-1','guided'),('repeat-2','guided'),('repeat-2','direct')]
    assert all(t['evidence_kind']=='mock_provider' for t in trials)
    assert all(g['trials']==2 and g['paid_microusd'] is None and g['repeated_supported_decision_agreement']==1 for g in report['analysis']['groups'])
    assert report['analysis']['verified_live'] is False


def test_shared_cap_leaves_missing_comparison_trials_unattempted(monkeypatch):
    monkeypatch.setattr(live,'run',fake_run)
    report=live.execute(None,[task()],2,3,'mock-model','http://localhost',evidence_kind='mock_provider')
    assert report['request_attempts']==3
    trials=report['canonical_transcripts']['trials']
    assert len(trials)==4 and sum(t['status']=='unattempted' for t in trials)==3
    assert not report['all_comparison_trials_terminal_without_cap_or_error']


def test_wrong_probe_model_prevents_further_calls(monkeypatch):
    calls=[]
    def wrong(*args,**kwargs):
        calls.append(1);report=fake_run(*args,**kwargs)
        report['records'][0]['attempts'][0]['model_id']='wrong-model'
        return report
    monkeypatch.setattr(live,'run',wrong)
    report=live.execute(None,[task()],2,48,'mock-model','http://localhost',evidence_kind='mock_provider')
    assert len(calls)==1 and not report['compatibility_response_observed']
    assert all(t['status']=='unattempted' for t in report['canonical_transcripts']['trials'])


def sheet():
    return {'local_id':'P001','consent':True,'adult_confirmed':True,'status':'completed',
            'tasks':{k:'completed' for k in pilot.TASKS},
            'comprehension':{'approval':'yes','evidence':'no','price':'unsure'}}


def payload(records,kind='fictional'):
    return {'schema':'intentcart-workstation-observation-sheets/1','evidence_kind':kind,'records':records}


def test_fictional_and_empty_pilot_reports_never_count_humans():
    report=pilot.analyze(payload([sheet()]))
    assert report['recorded_active_human_participants']==0 and report['fictional_records']==1
    assert report['study_status']=='not_conducted'
    assert report['comprehension']['approval']['incorrect_yes']==1
    assert report['comprehension']['price']['unsure']==1
    empty=pilot.analyze(payload([]))
    assert empty['entered_records']==0 and empty['recorded_active_human_participants']==0


def test_observer_claims_keep_withdrawals_errors_and_missing_answers():
    row=sheet();row.update(status='incomplete',comprehension={'approval':'yes'})
    withdrawn={'local_id':'P002','consent':False,'adult_confirmed':True,'status':'withdrawn'}
    report=pilot.analyze(payload([row,withdrawn],'human_observer_entry'))
    assert report['recorded_active_human_participants']==1 and report['independently_verified_participants']==0
    assert report['withdrawn_records_excluded']==1 and report['incomplete_records']==1
    assert report['comprehension']['price']['unanswered']==1
    assert 'P001' not in json.dumps(report)
    withdrawn['comprehension']={'approval':'yes'}
    with pytest.raises(ValueError,match='no answers'):pilot.analyze(payload([withdrawn]))


def test_missing_consent_duplicate_ids_and_fake_completion_are_rejected():
    row=sheet();row['consent']=False
    with pytest.raises(ValueError,match='consent'):pilot.analyze(payload([row]))
    row=sheet()
    with pytest.raises(ValueError,match='Repeated'):pilot.analyze(payload([row,deepcopy(row)]))
    row['comprehension'].pop('price')
    with pytest.raises(ValueError,match='every task'):pilot.analyze(payload([row]))
