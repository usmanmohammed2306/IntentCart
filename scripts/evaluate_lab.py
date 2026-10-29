"""Reproduce rehearsal, gate and lost-response recovery against actual endpoints.

All provider responses here are explicitly fake. Uses disposable storage and
blank external credentials; never opens the user's saved database or calls PayPal.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=ROOT/'intentcart/data/lab-evaluation.json')
args = parser.parse_args()
sys.path.insert(0, str(ROOT))
for name in ('PAYPAL_CLIENT_ID','PAYPAL_CLIENT_SECRET','CHANNEL3_API_KEY','SANDBOX_BUYER_EMAIL','SANDBOX_BUYER_PASSWORD'):
    os.environ[name]=''
os.environ['EXTERNAL_CALL_LIMIT']='0'

class InterruptedFakeProvider:
    def __init__(self):
        self.capture_calls=0
        self.orders={}
        self.create_calls=0
    def create(self, quote, key):
        self.create_calls+=1
        self.quote=quote
        self.orders['FAKE-ORDER-1']={'id':'FAKE-ORDER-1','status':'APPROVED',
            'purchase_units':[{'reference_id':quote['id']}]}
        return copy.deepcopy(self.orders['FAKE-ORDER-1'])
    def get(self, order):
        return copy.deepcopy(self.orders[order])
    def capture(self, order, key):
        from intentcart.paypal import ProviderError
        self.capture_calls+=1
        payload=self.orders[order]
        payload['status']='COMPLETED'
        payload['purchase_units'][0]['payments']={'captures':[{'id':'FAKE-CAPTURE-1','status':'COMPLETED',
            'amount':{'currency_code':'USD','value':f"{self.quote['total_cents']/100:.2f}"}}]}
        raise ProviderError('Scripted lost response after fake capture committed.', True)
    def refund(self, capture, key):
        return {'id':'FAKE-REFUND-1','status':'COMPLETED',
                'amount':{'currency_code':'USD','value':f"{self.quote['total_cents']/100:.2f}"}}

with tempfile.TemporaryDirectory(prefix='intentcart-lab-') as directory:
    os.environ['DATABASE_PATH']=str(Path(directory)/'lab.sqlite3')
    from fastapi.testclient import TestClient
    from intentcart import app as module, config
    fake=InterruptedFakeProvider()
    module.provider=fake
    module.RATES.clear()
    with TestClient(module.app) as client:
        session=client.get('/api/session').json()
        client.headers.update({'origin':config.PUBLIC_URL,'x-csrf-token':session['csrf_token']})
        state=client.post('/api/mission',json={'text':'A comfortable rainy campus commute',
            'budget_cents':9000,'laptop_inches':16,'min_capacity_l':20}).json()
        for choice in ('a','b','a','b'):
            state=client.post('/api/answer',json={'question_id':state['question']['id'],'choice':choice}).json()
        worlds=client.get('/api/rehearsal').json()
        unchanged=client.get('/api/session').json()['state']==state
        quote=client.post('/api/quotes',json={'product_id':state['ranked'][0]['id'],'version':state['version']}).json()
        challenges=client.post('/api/challenges',json={'quote_id':quote['id']}).json()
        dry_run_no_orders=client.get('/api/orders').json()==[] and fake.create_calls==0
        created=client.post('/api/paypal/create',json={'quote_id':quote['id'],'approved':True})
        assert created.status_code==200
        lost=client.post('/api/paypal/capture',json={'quote_id':quote['id']})
        assert lost.status_code==502 and lost.json()['uncertain']
        status=client.post('/api/paypal/status',json={'quote_id':quote['id']}).json()
        retried=client.post('/api/paypal/capture',json={'quote_id':quote['id']}).json()
        refunded=client.post('/api/paypal/refund',json={'quote_id':quote['id']}).json()
        changed=client.post('/api/scenario',json={'kind':'shipping','version':state['version']}).json()
        stale=client.post('/api/paypal/create',json={'quote_id':quote['id'],'approved':True})
        stopped=client.post('/api/scenario',json={'kind':'no_purchase','version':changed['version']}).json()
        checks={'preview_leaves_state_unchanged':unchanged,
            'four_worlds_retain_comparisons':len(worlds['worlds'])==4 and all(w['preferences_retained'] for w in worlds['worlds']),
            'seven_scripted_gate_outcomes':challenges['matched']==challenges['total']==7,
            'dry_run_creates_no_order':dry_run_no_orders,
            'lost_response_reconciles_once':status['status']==retried['status']=='COMPLETED' and fake.capture_calls==1,
            'fake_refund_completes':refunded['status']=='REFUNDED',
            'world_change_invalidates_old_quote':stale.status_code==409,
            'infeasible_world_retains_preferences':not stopped['ranked'] and stopped['history']==state['history']}
        assert all(checks.values()),checks
        result={'created_utc':datetime.now(timezone.utc).isoformat(), 'app_version':module.app.version,
            'kind':'One deterministic scripted local run; actual API endpoints, explicitly fake provider',
            'live_provider_calls':0,'checks':checks,
            'challenge_cases':challenges['cases'],
            'recovery':{'capture_calls':fake.capture_calls,'final_status':refunded['status'],
                'trace':[{'action':'Create under explicit test consent','result':'Fake buyer is scripted as APPROVED; no live PayPal approval.'},
                    {'action':'Capture response disappears','result':'HTTP 502 uncertain; fake provider has already committed one capture.'},
                    {'action':'Reconcile saved order','result':'COMPLETED with matching quote, currency and amount.'},
                    {'action':'Retry capture safely','result':'Existing completed capture returned; capture call count remains one.'},
                    {'action':'Refund the verified fake capture','result':'REFUNDED for the exact original total.'}]},
            'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                for name in ('intentcart/app.py','intentcart/assurance.py','intentcart/learning.py','intentcart/procurement.py','intentcart/data/it-catalog.json','scripts/evaluate_lab.py')},
            'limits':'Not a human study, live outage experiment, general security benchmark, or proof of prompt-injection resistance.'}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,indent=2)+'\n')
print(f"Lab evidence: {sum(checks.values())}/{len(checks)} scripted assertions; {fake.capture_calls} fake capture; 0 live provider calls. Saved {args.output}")
