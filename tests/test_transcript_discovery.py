from copy import deepcopy
from datetime import date
import pytest
from intentcart import workbench,transcripts,discovery_import,evidence_catalog


def trial(repeat='1',paid=20,status='supported'):
    return {'task_id':'t1','controller':'direct','model_id':'reported-model','repeat_id':repeat,'evidence_kind':'mock_provider','status':status,'decision_id':'basket-1' if status=='supported' else None,'attempts':[{'outcome':'ok' if status=='supported' else 'timeout','paid_microusd':paid,'uncertain_transport':status!='supported'}]}


def test_cost_metrics_retain_failure_cost_unknowns_and_single_trial_limits():
    report=transcripts.analyze({'schema':'intentcart-transcripts/1','trials':[trial(),trial('2',40,'failed')]});g=report['groups'][0]
    assert g['cost_per_supported_completion_microusd']==60 and g['errors']=={'timeout':1}
    assert report['verified_live'] is False and g['repeated_supported_decision_agreement'] is None
    report=transcripts.analyze({'schema':'intentcart-transcripts/1','trials':[trial(),trial('2',None)]})
    assert report['groups'][0]['paid_microusd'] is None and report['groups'][0]['repeated_supported_decision_agreement']==1
    with pytest.raises(ValueError):transcripts.analyze({'schema':'intentcart-transcripts/1','trials':[trial(),trial()]})


def test_transcripts_reject_capability_escalation_and_unresolved_success_claims():
    t=trial();t['attempts'][0]['action']={'action':'pay'}
    with pytest.raises(ValueError):transcripts.analyze({'schema':'intentcart-transcripts/1','trials':[t]})
    t=trial();t['attempts'][0]['uncertain_transport']=True
    with pytest.raises(ValueError):transcripts.analyze({'schema':'intentcart-transcripts/1','trials':[t]})


def test_discovery_import_binds_offers_to_exact_products_without_facts_or_calls():
    cat=evidence_catalog.load_catalog();p=cat['products'][0]
    row={'merchant':'Example','offer_id':'offer-1','url':'https://example.com/dock','name':p['name'],'product_id':p['id'],'variant':p['variant'],'price_cents':19999,'observed_on':workbench.current_day().isoformat()}
    result=discovery_import.review({'source':'channel3','items':[row]},cat)
    assert result['provider_calls']==0 and result['items'][0]['compatibility_facts_imported'] is False
    for changed in [{**row,'variant':'another kit'},{**row,'price_cents':True},{**row,'url':'https://user:secret@example.com'}]:
        with pytest.raises(ValueError):discovery_import.review({'source':'channel3','items':[changed]},cat)
    with pytest.raises(ValueError):discovery_import.review({'source':'channel3','items':[row,row]},cat)
