import copy
from intentcart.assurance import check_proposal, project_world, total_cents

def test_counterfactual_world_is_a_deep_copy_and_retains_choices():
    state={'mission':{'budget_cents':9000},'history':[{'choice':'a'}], 'excluded':[], 'version':4}
    original=copy.deepcopy(state)
    world=project_world(state,'shipping','bag-01')
    world['history'][0]['choice']='b'
    assert state==original
    assert world['shipping_surcharge_cents']==1000
    assert total_cents({'price_cents':5800},world)==7200

def test_proposal_cannot_use_boolean_as_amount_or_approval_string():
    product={'id':'bag-01','price_cents':5800,'laptop_inches':16,'capacity_l':22}
    state={'mission':{'budget_cents':9000,'laptop_inches':16,'min_capacity_l':20},'excluded':[],'version':3}
    quote={'product':product,'total_cents':6200,'version':3,'currency':'USD','expires_at':200}
    proposal={'product_id':'bag-01','total_cents':True,'version':3,'currency':'USD','approved':'true'}
    outcome=check_proposal([product],quote,state,proposal,100)
    assert not outcome['eligible'] and set(outcome['failed'])=={'amount','consent'}
