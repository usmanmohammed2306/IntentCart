from copy import deepcopy
import csv,io
from datetime import date,timedelta
import pytest
from fastapi.testclient import TestClient
from intentcart import agent,workbench,evidence_catalog,config,app as module


def finished(kind='curated'):
    r=agent.create('Reviewed workstation',{},kind,32,True)
    for _ in range(26):
        if r['pending_question']: r=agent.answer(r,True)
        if r['status']!='ACTIVE': return r
        r=agent.step(r,agent.local_action(r))
    raise AssertionError('Task failed to stop')


def test_csv_and_report_bind_owned_revision_and_complete_quantities():
    r=finished();table=list(csv.DictReader(io.StringIO(workbench.bill_of_materials(r))))
    deps={s['source_id']:s['checks'] for s in workbench.summary(r)['sources']}
    assert deps['dell-p2422h-height']==['resolution']
    assert deps['declared-hdmi-pair-height']==['cables']
    assert 'charging_target' not in deps['pdh-included-power-watts']
    assert len(table)==4
    assert sum(int(i['line_cents']) for i in table)==34999
    assert 'Checkout authority: none' in workbench.decision_report(r)
    assert f"Revision: {r['revision']}" in workbench.decision_report(r)
    with pytest.raises(ValueError): workbench.bill_of_materials(agent.create('',{}))


def test_csv_neutralizes_formula_injection():
    r=finished();cat=workbench.catalog(r);cat['products'][0]['name']='=HYPERLINK("bad")'
    r['workbench']={'catalog':cat}
    assert "'=HYPERLINK" in workbench.bill_of_materials(r)


def test_requirements_keep_previous_plan_but_clear_acceptance_and_tax_unknown():
    r=finished();new=workbench.mutate(r,'requirements',{'tax_cents':None})
    assert new['recommended_id'] is None and new['previous_items']
    assert workbench.rank(new)==[]
    assert r['status']=='RECOMMENDED' and workbench.rank(r)
    paid=workbench.mutate(r,'requirements',{'tax_cents':1})
    assert workbench.rank(paid)[0]['total_cents']==35000
    assert not workbench.rank(workbench.mutate(r,'requirements',{'tax_cents':2}))


@pytest.mark.parametrize('payload',[{'hdcp':True},{'gaming':True},{'os_version':'13.0'},{'charging_watts':140},{'connector':'usb-c'}])
def test_missing_extra_capability_fails_closed(payload):
    assert not workbench.rank(workbench.mutate(finished(),'requirements',payload))


def test_owned_monitors_validate_then_replace_baseline_assumption():
    r=finished();payload={'owned_monitors':[{'name':'Desk','height':1080,'hz':60,'connector':'hdmi'}]}
    changed=workbench.mutate(r,'requirements',payload)
    assert workbench.rank(changed)
    with pytest.raises(ValueError): workbench.mutate(r,'requirements',{'owned_monitors':[{'name':'Bad','height':True,'hz':60,'connector':'hdmi'}]})
    with pytest.raises(ValueError): workbench.mutate(r,'requirements',{'owned_monitors':[{'name':'Bad'}]})


def test_driver_withdrawal_and_restore_are_human_revisioned():
    r=finished();withdrawn=workbench.mutate(r,'withdraw_driver',{})
    assert not withdrawn['goal']['allow_driver'] and withdrawn['driver_answered'] is False
    assert not workbench.rank(withdrawn)
    gone=agent.revise(r,exclude='plugable-ud6950pdh');assert not workbench.rank(gone)
    restored=workbench.mutate(gone,'restore_product',{'product_id':'plugable-ud6950pdh'})
    assert workbench.rank(restored) and restored['tool_count']==gone['tool_count']


def test_offer_binding_expiry_and_unknown_shipping():
    r=finished();p=workbench.catalog(r)['products'][0]
    offer={'product_id':p['id'],'variant':p['variant'],'merchant':'Example','offer_id':'O-1','price_cents':19000,'observed_on':workbench.current_day().isoformat(),'available':True}
    updated=workbench.mutate(r,'offer',offer)
    assert workbench.rank(updated)[0]['total_cents']==34000
    with pytest.raises(ValueError): workbench.mutate(r,'offer',{**offer,'variant':'wrong'})
    with pytest.raises(ValueError): workbench.mutate(r,'offer',{**offer,'price_cents':True})
    expired=workbench.mutate(r,'offer',{**offer,'observed_on':(workbench.current_day()-timedelta(days=8)).isoformat()})
    assert not workbench.rank(expired)
    assert not workbench.rank(workbench.mutate(updated,'requirements',{'shipping_cents':None}))


def test_freshness_includes_future_invalid_and_exact_boundary():
    today=date(2026,10,19)
    assert workbench.freshness({'observed_on':'2026-10-12'},7,today)['status']=='current'
    assert workbench.freshness({'observed_on':'2026-10-11'},7,today)['status']=='expired'
    assert workbench.freshness({'observed_on':'2026-10-20'},7,today)['status']=='future'
    assert workbench.freshness({'observed_on':'invalid'},7,today)['status']=='invalid_date'


def test_source_replacement_needs_exact_second_review_and_reinspection():
    r=finished();cat=workbench.catalog(r);sid='plugable-ud6950pdh-displays';replacement=deepcopy(cat['sources'][sid]);replacement['value']=1
    proposed=workbench.mutate(r,'propose_source',{'source_id':sid,'replacement':replacement,'reason':'Reviewed a correction'})
    assert workbench.catalog(proposed)['sources'][sid]['value']==2
    with pytest.raises(ValueError): workbench.mutate(proposed,'accept_source',{'proposal_id':'wrong','reviewed':True})
    with pytest.raises(ValueError): workbench.mutate(proposed,'accept_source',{'proposal_id':proposed['workbench']['pending_source']['id'],'reviewed':False})
    accepted=workbench.mutate(proposed,'accept_source',{'proposal_id':proposed['workbench']['pending_source']['id'],'reviewed':True})
    assert sid not in accepted['inspected'] and accepted['recommended_id'] is None
    assert workbench.catalog(accepted)['sources'][sid]['value']==1
    assert not workbench.rank(accepted)
    assert workbench.catalog(r)['sources'][sid]['value']==2


def test_preferences_history_undo_edit_delete_and_source_invalidation():
    r=finished('fixture');r['history']=[{'a':'x','b':'y','choice':'a'},{'a':'x','b':'z','choice':'skip'}];r['personalized']=True
    edited=workbench.mutate(r,'edit_preference',{'index':0,'choice':'b'})
    assert edited['history'][0]['choice']=='b' and r['history'][0]['choice']=='a'
    assert len(workbench.mutate(edited,'undo_preference',{})['history'])==1
    assert len(workbench.mutate(edited,'delete_preference',{'index':0})['history'])==1
    assert workbench.mutate(edited,'requirements',{'tax_cents':0})['history']==[]
    assert set(workbench.summary(edited)['uncertainty'])==set(workbench.preferences.FEATURES)


def test_counterfactual_is_non_mutating_and_has_no_payment_authority():
    r=finished();before=deepcopy(r)
    result=workbench.counterfactual(r,[{'budget_cents':1000},{'budget_cents':35000}])
    assert r==before and result['mutates_task'] is False and result['checkout_supported'] is False
    assert result['scenarios'][0]['supported']==0 and result['scenarios'][1]['supported']==1


def test_variant_selection_and_reviewed_catalog_import_reject_stale_identity():
    r=finished();cat=workbench.catalog(r);p=cat['products'][0]
    with pytest.raises(ValueError):workbench.mutate(r,'select_variant',{'product_id':p['id'],'variant':'not the variant'})
    assert workbench.rank(workbench.mutate(r,'select_variant',{'product_id':p['id'],'variant':p['variant']}))
    with pytest.raises(ValueError):workbench.mutate(r,'import_catalog',{'catalog':cat,'base_sha256':'old','reviewed':True})
    imported=workbench.mutate(r,'import_catalog',{'catalog':cat,'base_sha256':workbench.digest(cat),'reviewed':True})
    assert not imported['inspected'] and not imported['discovered'] and imported['recommended_id'] is None


def test_curated_three_display_prototype_accepts_goal_but_does_not_invent_support():
    r=agent.create('',{'displays':3},scenario_confirmed=True)
    assert r['goal']['displays']==3 and not workbench.rank(r)
    with pytest.raises(ValueError):agent.create('',{'displays':5})


def test_source_value_types_and_laptop_identity_validation():
    cat=evidence_catalog.load_catalog();bad=deepcopy(cat);bad['laptops'][0]['source_url']='https://user:pass@support.apple.com/doc'
    with pytest.raises(ValueError):evidence_catalog.validate_catalog(bad)
    for bad_url in (None,123,{}):
        source=deepcopy(next(iter(cat['sources'].values())));source['url']=bad_url
        with pytest.raises(ValueError):evidence_catalog.validate_source(source)
        bad=deepcopy(cat);bad['laptops'][0]['source_url']=bad_url
        with pytest.raises(ValueError):evidence_catalog.validate_catalog(bad)
    orphan=deepcopy(cat);orphan['sources']['orphan']=deepcopy(next(iter(cat['sources'].values())))
    with pytest.raises(ValueError):evidence_catalog.validate_catalog(orphan)
    for field,value in [('hdcp',1),('minimum_os','macOS latest'),('direction','backwards')]:
        with pytest.raises(ValueError):evidence_catalog.validate_value(field,value)


def test_workbench_api_ownership_revision_csrf_and_no_provider(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATABASE_PATH',str(tmp_path/'db.sqlite3'));monkeypatch.setattr(config,'CALL_LIMIT',0)
    monkeypatch.setattr(module,'provider',lambda:(_ for _ in ()).throw(AssertionError('No provider allowed')))
    module.RATES.clear()
    with TestClient(module.app) as c:
        session=c.get('/api/session').json();c.headers.update({'origin':config.PUBLIC_URL,'x-csrf-token':session['csrf_token']})
        r=c.post('/api/agent',json={'goal':{},'scenario_confirmed':True}).json()
        assert c.get('/workbench').status_code==200
        assert c.get('/research').status_code==200
        for kind in ('budget','preferences'):
            report=c.get('/api/roadmap/evaluation?kind='+kind)
            assert report.status_code==200 and 'summaries' in report.json()
        q=c.post('/api/agent/workbench',json={'revision':r['revision'],'operation':'requirements','payload':{'hdcp':True}})
        assert q.status_code==200 and q.json()['workbench']['requirements']['hdcp'] is True
        assert c.post('/api/agent/workbench',json={'revision':r['revision'],'operation':'withdraw_driver'}).status_code==409
        assert c.get('/api/agent/report').status_code==200
        assert c.get('/api/agent/report?format=csv').status_code==409
        assert c.post('/api/agent/clarify-query',json={'text':'No 4K; two monitors; Linux and HDR'}).json()['unsupported']
        with TestClient(module.app) as other:
            other.get('/api/session');assert other.get('/api/agent/workbench').status_code==409
        c.headers['x-csrf-token']='wrong'
        assert c.post('/api/agent/workbench',json={'revision':q.json()['revision'],'operation':'withdraw_driver'}).status_code==403


def synthetic_catalog():
    fields={
      'dock':{'protocol':'usb-c','displays':4,'max_height':2160,'max_hz':120,'pd_watts':100,'hdcp':True,'gaming':True,'minimum_os':'12.0','output_connector':'usb-c'},
      'monitor':{'height':2160,'hz':120,'connector':'usb-c'},
      'cable':{'height':2160,'hz':120,'count':4,'connector':'usb-c','direction':'dock-to-display'},
      'power':{'watts':130,'adapter_for':'synthetic-dock'}}
    cat={'schema':evidence_catalog.SCHEMA,'notice':'Explicitly synthetic test catalog, no hardware truth claim.','warnings':[],
         'laptops':[{'id':'synthetic-laptop','name':'Synthetic laptop','variant':'test-v1','protocols':['usb-c'],'native_displays':4,'charge_watts':30,'source_url':'https://support.apple.com/','observed_on':workbench.current_day().isoformat(),'source_summary':'Test identity only.'}],
         'products':[],'sources':{}}
    from intentcart.missions import FACT_UNITS
    for kind,values in fields.items():
        pid='synthetic-'+kind;product={'id':pid,'name':pid,'kind':kind,'variant':'test-v1','price_cents':100,'observations':[]}
        for field,value in values.items():
            sid=pid+'-'+field
            product['observations'].append({'field':field,'value':value,'source_id':sid,'visible':False})
            cat['sources'][sid]={'product_id':pid,'variant':'test-v1','field':field,'value':value,'unit':FACT_UNITS[field], 'kind':'scenario_declaration','url':'','observed_on':workbench.current_day().isoformat(),'summary':'Synthetic regression fixture.'}
        cat['products'].append(product)
    return evidence_catalog.validate_catalog(cat)


def test_three_displays_usb_c_hard_capabilities_and_multiple_owned_monitors():
    base=finished();cat=synthetic_catalog()
    imported=workbench.mutate(base,'import_catalog',{'catalog':cat,'reviewed':True,'base_sha256':workbench.digest(workbench.catalog(base)),
        'goal':{'laptop_id':'synthetic-laptop','displays':3,'budget_cents':10000,'height':2160,'hz':120,'reuse_monitor':True}})
    required=workbench.mutate(imported,'requirements',{'hdcp':True,'gaming':True,'os_version':'13.0','connector':'usb-c','charging_watts':90,
        'owned_monitors':[{'name':'First','height':2160,'hz':120,'connector':'usb-c'},{'name':'Second','height':2160,'hz':120,'connector':'usb-c'}]})
    assert not workbench.rank(required)  # uninspected extra capabilities cannot pass
    required['inspected']=list(cat['sources']);required['discovered']=[p['id'] for p in cat['products']]
    candidates=workbench.rank(required);assert len(candidates)==1
    assert next(i['quantity'] for i in candidates[0]['items'] if i['product_id']=='synthetic-monitor')==1
    assert all(candidates[0]['checks'][key] is True for key in ['hdcp','gaming','os_version','dock_output','connector_direction','adapter_match','owned_monitors'])
    assert not workbench.rank(workbench.mutate(required,'requirements',{'os_version':'11.0'}))
    old=deepcopy(required);old['inspected'].remove('synthetic-power-adapter_for')
    assert not workbench.rank(old)
    old=deepcopy(required);old['inspected'].remove('synthetic-cable-direction')
    assert not workbench.rank(old)


def test_duplicate_products_and_offer_identity_collisions_are_visible():
    r=finished();cat=workbench.catalog(r);duplicate=deepcopy(cat['products'][0]);duplicate['id']='duplicate-dock'
    cat['products'].append(duplicate);r['workbench']={'catalog':cat}
    assert ['plugable-ud6950pdh','duplicate-dock'] in workbench.summary(r)['duplicate_products']


def test_multiple_owned_displays_do_not_duplicate_baskets():
    r=finished('fixture')
    r=workbench.mutate(r,'requirements',{'owned_monitors':[{'name':'A','height':1080,'hz':60,'connector':'hdmi'},{'name':'B','height':1080,'hz':60,'connector':'hdmi'}]})
    rows=list(workbench.rows(r));assert len(rows)==len({row['id'] for row in rows})
    assert all(not any(i['product_id'].startswith('monitor') for i in row['items']) for row in rows)


def test_contradictory_sources_require_reviewed_resolution():
    r=finished();cat=workbench.catalog(r);sid='plugable-ud6950pdh-displays'
    conflicting=deepcopy(cat['sources'][sid]);conflicting['value']=1
    cat['sources']['synthetic-contradiction']=conflicting
    cat['products'][0]['observations'].append({'field':'displays','value':1,'source_id':'synthetic-contradiction','visible':False})
    r['workbench']={'catalog':cat};r['inspected'].append('synthetic-contradiction')
    assert not workbench.rank(r)
    replacement={**conflicting,'value':2}
    proposal=workbench.mutate(r,'propose_source',{'source_id':'synthetic-contradiction','replacement':replacement,'reason':'Synthetic explicit conflict resolution regression'})
    assert not workbench.rank(proposal)
    accepted=workbench.mutate(proposal,'accept_source',{'proposal_id':proposal['workbench']['pending_source']['id'],'reviewed':True})
    assert workbench.rank(accepted) and 'synthetic-contradiction' not in accepted['inspected']
    assert any('displays' in source['checks'] for source in workbench.summary(accepted)['sources'])


def test_cost_preview_is_bounded_owned_and_does_not_change_task(tmp_path,monkeypatch):
    from scripts.evaluate_budget_roadmap import problem
    monkeypatch.setattr(config,'DATABASE_PATH',str(tmp_path/'costs.sqlite3'));module.RATES.clear()
    from intentcart import acquisition as a
    sample={'schema':a.SCHEMA,'id':'p','revision':'v1','queries':[{'id':'q','cost':1,'version':'v1'}],
            'worlds':[{'id':'a','weight':1,'answers':{'q':'yes'},'decision':'plan'},{'id':'b','weight':1,'answers':{'q':'no'},'decision':None}],'initial_evidence':[]}
    with TestClient(module.app) as c:
        session=c.get('/api/session').json();c.headers.update({'origin':config.PUBLIC_URL,'x-csrf-token':session['csrf_token']})
        task=c.post('/api/agent',json={'goal':{}}).json()
        response=c.post('/api/research/cost-preview',json={'problem':sample,'costs':{'q':2},'budget':1})
        assert response.status_code==200 and response.json()['action']['status']=='BUDGET_EXHAUSTED'
        assert response.json()['changes_saved'] is False
        assert c.get('/api/agent').json()['task']['revision']==task['revision']
        assert c.post('/api/research/cost-preview',json={'problem':sample,'budget':65}).status_code==422
        c.headers['x-csrf-token']='wrong'
        assert c.post('/api/research/cost-preview',json={'problem':sample,'budget':1}).status_code==403
