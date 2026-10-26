"""Local trained-agent shopping, canonical fixture quotes and human PayPal approval.

The model can search, inspect, recommend or defer. It has no payment tool.
All products and laptop profiles here are explicitly fictional sandbox fixtures.
"""
import copy,json,uuid,time,hashlib
from pathlib import Path
from datetime import date
from fastapi import Request,HTTPException
from pydantic import Field
from .workspace import Strict,Workspace,Surface,Item,Pose
from .planning_models import Planning
from .device_research import digest
from . import missions as catalog,trained_agent,planning_runs

class Start(Strict):
 goal:catalog.Goal
 space:Surface=Field(default_factory=lambda:Surface(kind='none'))
class Revision(Strict):
 run_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 revision:int=Field(ge=0)
class Quote(Revision):
 workspace:Workspace
 planning:Planning
 operation_id:str=Field(pattern=r'^[a-f0-9]{32}$')

def source_identity():
 root=Path(__file__).parent
 return digest({'planner':planning_runs.source_identity(),'catalog':catalog.source_identity(),'commerce':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'app':hashlib.sha256((root/'app.py').read_bytes()).hexdigest()})
def projection(run):
 goal=catalog.Goal(**run['mission']['goal']);plan=run['mission']['result']['plan']
 if not plan:return None
 items=[Item(id='owned-laptop',kind='laptop',name=catalog.LAPTOPS[goal.laptop_id]['name'],model=goal.laptop_id,owned=True,price_cents=None,pose=Pose(x=-400,z=-200))]
 if goal.reuse_monitor:items.append(Item(id='owned-monitor',kind='monitor',name='Existing monitor · sandbox fixture',owned=True,pose=Pose(x=-220,z=0)))
 placements={'dock':(-250.,220.),'power':(250.,220.),'cable':(0.,220.),'monitor':(220.,0.)};monitor=0
 for row in plan['items']:
  p=catalog.PRODUCTS[row['product_id']]
  for n in range(row['quantity']):
   x,z=placements[p['kind']]
   if p['kind']=='monitor':x=(-220. if not goal.reuse_monitor and monitor==0 else 220.);monitor+=1
   items.append(Item(id='buy-'+p['id']+'-'+str(n),kind=p['kind'],name=p['name'],model=p['id'],owned=False,price_cents=p['price_cents'],pose=Pose(x=x,z=z),color='#9de5d2'))
 w=Workspace(name='Sandbox purchase plan',currency='USD',budget_cents=goal.budget_cents,shipping_cents=0,tax_cents=0,surface=Surface.model_validate(run['space']),items=items)
 return {'workspace':w.model_dump(),'planning':Planning().model_dump(),'notice':'Illustrative cart preview. Dimensions are unknown; this does not certify physical fit. Fictional products, sandbox funds, no goods or delivery.'}
def draft_digest(w,p):return digest({'workspace':w.model_dump(),'planning':p.model_dump()})
def fresh(run):return run['source_identity']==source_identity() and run['review_day']==date.today().isoformat()
def view(run):
 out=copy.deepcopy(run);out['busy']=bool(out.pop('inflight',False));out.pop('reservation',None);out['fresh']=fresh(run);out['mission']=catalog.public_record(out['mission']);return out
def compute(record):
 run=copy.deepcopy(record)
 if not fresh(run):run['status']='STALE';return run
 m=run['mission'];useful=[r for r in m['result']['investigations'] if r['could_improve_cost']];ready=run['discovered'] and not useful and bool(m['result']['plan'])
 observed={'discovered':run['discovered'],'decision_facts_missing':min(9,len(useful)),'software_candidate':False,'software_answered':True,'supported_basket':ready,'remaining_steps':run['max_steps']-run['attempts']+1,'budget_cents':m['goal']['budget_cents']}
 raw,receipt=trained_agent.generate(json.dumps(observed,separators=(',',':')),trained_agent.POLICY,8);run['step_count']+=1
 event={'step':run['step_count'],'model_tool':raw,'model_receipt':receipt,'observed_state':observed}
 if raw=='search' and not run['discovered']:
  run['discovered']=True;event['result']={'scope':'Bundled fictional sandbox seller catalog','candidates':len(m['result']['preference_choices']),'notice':catalog.CATALOG['notice']}
 elif raw=='inspect' and run['discovered'] and useful:
  sid=useful[0]['source_ids'][0];assert sid in catalog.CATALOG['sources'];run['mission']=catalog.revise(m,inspect=sid);event['result']={'source_id':sid,'source':catalog.CATALOG['sources'][sid],'scope':'Recorded fictional fixture evidence; no manufacturer/web request.'}
 elif raw=='recommend' and ready:
  plan=m['result']['plan'];verified=catalog.evaluate(catalog.Goal(**m['goal']),plan['items'],m['inspected']);assert verified['valid'] and verified['id']==plan['id']
  run['status']='READY_FOR_REVIEW';run['projection']=projection(run);event['result']={'basket':plan['items'],'total_cents':plan['total_cents'],'scope':'Ready for human cart review; no quote, order or payment approved.'}
 elif raw=='defer' and run['discovered'] and not useful:
  run['status']='NEEDS_REVIEW';event['result']={'reason':'No complete supported cart under the reviewed settings in this finite fictional catalog.','result':m['result']['status']}
 else:
  run['status']='MODEL_PAUSED';event['result']={'rejected':True,'reason':'Selected tool prerequisites were not met. No fallback policy or payment action ran.'}
 run['events'].append(event)
 if run['status']=='RUNNING' and run['attempts']>=run['max_steps']:run['status']='STEP_LIMIT'
 return run

def quote_gate(quote,state):
 binding=quote.get('ai_purchase')
 if not binding:return []
 run=state.get('commerce_runs',{}).get(binding.get('run_id'))
 return [{'id':'ai_plan','label':'Trained-agent plan remains reviewable','passed':bool(run and run['status']=='READY_FOR_REVIEW')},
         {'id':'ai_source','label':'Agent and catalog sources are current','passed':bool(run and fresh(run) and binding.get('source_identity')==run['source_identity'])},
         {'id':'ai_revision','label':'Exact reviewed plan revision','passed':bool(run and binding.get('revision')==run['revision'])},
         {'id':'ai_cart','label':'Exact active sandbox cart quote','passed':bool(run and run.get('active_quote_id')==quote['id'] and binding.get('draft_digest')==run.get('quoted_draft_digest'))}]

def register(module):
 app=module.app
 def find(state,body):
  run=state.get('commerce_runs',{}).get(body.run_id)
  if not run:raise HTTPException(404,'Purchase plan not found in this account.')
  if run['revision']!=body.revision:raise HTTPException(409,'The purchase plan changed. Reload its current checkpoint.')
  return run
 def save(db,sid,state,run):state.setdefault('commerce_runs',{})[run['id']]=run;state['version']+=1;module.save(db,sid,state)
 @app.get('/api/commerce/config')
 def config(request:Request):
  with module.database() as db:module.owner(request,db)
  return {'sandbox':True,'paypal_connected':bool(module.config.CLIENT_ID and module.config.CLIENT_SECRET),'paypal_client_id':module.config.CLIENT_ID if module.config.CLIENT_SECRET else '',**catalog.public_catalog()}
 @app.get('/api/commerce/runs')
 def runs(request:Request):
  with module.database() as db:_,state=module.owner(request,db);return {'runs':[view(r) for r in state.get('commerce_runs',{}).values()]}
 @app.post('/api/commerce/start')
 def start(body:Start,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);runs=state.setdefault('commerce_runs',{})
   if any(r['status']=='RUNNING' for r in runs.values()):raise HTTPException(409,'Stop the active purchase plan before starting another.')
   while len(runs)>=4:del runs[next(iter(runs))]
   prior=state.get('outcome',{}).get('revision',0);m=catalog.create('Human-reviewed fictional sandbox purchase settings',body.goal,prior+1)
   run={'id':uuid.uuid4().hex,'revision':0,'status':'RUNNING','mission':m,'space':body.space.model_dump(),'source_identity':source_identity(),'review_day':date.today().isoformat(),'discovered':False,'step_count':0,'attempts':0,'max_steps':12,'inflight':False,'events':[],'projection':None,'scope':'Local trained tool selection; canonical fictional cart; human-only exact PayPal sandbox approval. No real goods, physical-fit certification, paid inference or automatic payment.'}
   save(db,sid,state,run);return view(run)
 @app.post('/api/commerce/advance')
 def advance(body:Revision,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);run=find(state,body)
   if run['status']!='RUNNING' or run.get('inflight'):raise HTTPException(409,'This plan is paused, busy or finished.')
   if run['attempts']>=run['max_steps']:raise HTTPException(409,'The reserved step limit has been reached.')
   token=uuid.uuid4().hex;run['attempts']+=1;run['revision']+=1;run['inflight']=token;save(db,sid,state,run);reserved_version=state['version'];snapshot=copy.deepcopy(run);db.commit()
  try:computed=compute(snapshot)
  except (ValueError,OSError) as exc:computed=copy.deepcopy(snapshot);computed['status']='MODEL_PAUSED';computed['error']=str(exc)[:400]
  with module.database() as db:
   sid,state=module.owner(request,db,True);current=state.get('commerce_runs',{}).get(body.run_id)
   if not current:raise HTTPException(409,'The purchase checkpoint was removed; no result applied.')
   if current['revision']!=snapshot['revision'] or current.get('inflight')!=token:return view(current)
   if state['version']!=reserved_version:computed=copy.deepcopy(current);computed['status']='STALE';computed['error']='Other saved work changed while this step ran. Review a fresh purchase plan.'
   computed['inflight']=False;computed['revision']+=1
   if computed['status']=='READY_FOR_REVIEW':state['outcome']=copy.deepcopy(computed['mission'])
   save(db,sid,state,computed);return view(computed)
 @app.post('/api/commerce/cancel')
 def cancel(body:Revision,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);run=find(state,body)
   if run['status']!='RUNNING':raise HTTPException(409,'Only an active purchase plan can be stopped.')
   run['status']='CANCELLED';run['inflight']=False;run['revision']+=1;save(db,sid,state,run);return view(run)
 @app.post('/api/commerce/recover')
 def recover(body:Revision,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);run=find(state,body)
   if run['status'] not in ('RUNNING','MODEL_PAUSED') or not fresh(run) or run['attempts']>=run['max_steps']:raise HTTPException(409,'This checkpoint cannot be recovered. Review a new plan.')
   if any(r['id']!=run['id'] and r['status']=='RUNNING' for r in state['commerce_runs'].values()):raise HTTPException(409,'Stop the other active purchase plan first.')
   run['status']='RUNNING';run['inflight']=False;run['revision']+=1;save(db,sid,state,run);return view(run)
 @app.post('/api/commerce/quotes')
 def quote(body:Quote,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);run=state.get('commerce_runs',{}).get(body.run_id)
   if not run:raise HTTPException(404,'Purchase plan not found in this account.')
   if run['status']!='READY_FOR_REVIEW' or not fresh(run):raise HTTPException(409,'A current trained-agent purchase plan is required.')
   projected=run['projection'];expected=draft_digest(Workspace.model_validate(projected['workspace']),Planning.model_validate(projected['planning']));actual=draft_digest(body.workspace,body.planning)
   if actual!=expected:raise HTTPException(409,'Your draft differs from the reviewed sandbox cart. Review its purchase plan again.')
   if run.get('quote_operation_id')==body.operation_id:
    saved=module.owned_quote(db,sid,run['active_quote_id']);module.valid_quote(saved,state);return saved
   if run['revision']!=body.revision:raise HTTPException(409,'Purchase plan changed. Review its current revision.')
   m=run['mission'];result=catalog.solve(catalog.Goal(**m['goal']),m['inspected'],m['excluded']);plan=result['plan']
   if not plan or plan['id']!=m['result']['plan']['id']:raise HTTPException(409,'The canonical cart changed. Review a fresh plan.')
   qid=str(uuid.uuid4());run['revision']+=1;run.update(active_quote_id=qid,quoted_draft_digest=actual,quote_operation_id=body.operation_id);state['outcome']=copy.deepcopy(m);save(db,sid,state,run)
   data={'id':qid,'kind':'mission','version':state['version'],'mission_revision':m['revision'],'mission_source_sha256':catalog.source_identity(),'product':{'id':'mission-'+plan['id'],'name':'AI-reviewed workstation · fictional sandbox bundle'},'basket':plan['items'],'item_cents':plan['total_cents'],'shipping_cents':0,'tax_cents':0,'total_cents':plan['total_cents'],'currency':'USD','expires_at':time.time()+900,'sandbox':True,'ai_purchase':{'run_id':run['id'],'revision':run['revision'],'source_identity':run['source_identity'],'draft_digest':actual},'decision_snapshot':{'mission':catalog.public_record(m),'agent_events':copy.deepcopy(run['events']),'catalog_notice':catalog.CATALOG['notice'],'projection_notice':projected['notice']}}
   gate=catalog.quote_gate(data,state,module.exact_proposal(data,True),time.time())
   if not gate['eligible']:raise HTTPException(409,'The canonical sandbox cart failed its spending checks.')
   db.execute('INSERT INTO quotes VALUES (?,?,?)',(qid,sid,json.dumps(data)));return data
