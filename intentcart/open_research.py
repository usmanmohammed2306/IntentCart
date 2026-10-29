"""Owned, bounded research jobs: local model → free search → official read →
literal proposals → independent quote validation → explicit human acceptance.
No job changes a workspace, buys hardware, grants approval or calls a paid model.
"""
from __future__ import annotations
import copy,json,time,threading,uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Literal,TypedDict
from pydantic import Field,model_validator
from fastapi import Request,HTTPException
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from .workspace import Strict
from .planning_models import SourceReview,Profile,Design,DeviceSelection
from . import free_discovery as discovery,device_research as research,trained_agent,planning_engine as engine
from .planning_routes import profiles,validated_permission

class StartResearch(Strict):
 query:str=Field(min_length=2,max_length=120)
 kind:Literal['laptop','monitor','mouse','desk','dock','keyboard','desktop','cable','power','webcam','audio','storage','other']
 consent:Literal[True]
 client_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 source_job:str|None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
 source_index:int=Field(default=0,ge=0,le=5)
 @model_validator(mode='after')
 def public_query(self):self.query=discovery.validate_query(self.query);return self
class Accept(Strict):
 proposal_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 reviewed:Literal[True]
class Compare(Design):
 item_id:str=Field(min_length=1,max_length=64)

class Halt(Exception):pass
_active=threading.Lock();_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='explicit-spec-research')
_instance=uuid.uuid4().hex

def validate_proposal(doc,proposal):
 body=SourceReview(source_id=doc['id'],device_id='discovered-'+proposal['proposal_id'],name=proposal['name'],kind=proposal['kind'],configuration=proposal['configuration'],fields=proposal['fields'],evidence=proposal['evidence'])
 value=Profile.model_validate(research.review(doc,body))
 if 'PDF excerpt' in doc.get('method',''):value.note=doc['method']
 return engine.profile_dict(value)

def compare_designs(w,p,item_id,extra=()):
 item=next((i for i in w.items if i.id==item_id),None)
 if not item:raise ValueError('Select a current setup item to compare.')
 rows=[];seen=set()
 registry=research.catalog()+list(extra)+[engine.profile_dict(v) for v in p.profiles]
 for d in registry:
  if d['id'] in seen or d['kind']!=item.kind:continue
  seen.add(d['id'])
  configs=list(d['configurations']);preferred=next((c for c in configs if c in ('in_use','with_stand','stand_low','stand_extended','ergo_stand')),configs[0])
  if len(rows)>=16:break
  try:
   trial,meta=engine.apply_configuration(w,p,item_id,DeviceSelection(item_id=item_id,device_id=d['id'],configuration=preferred,source_digest=d['digest'],reviewed=True),extra)
   changed=not any(b.item_id==item_id and b.device_id==d['id'] and b.source_digest==d['digest'] for b in p.devices)
   current=next(i for i in trial.items if i.id==item_id)
   if changed:
    current.owned=False;current.price_cents=None;current.ports=[];current.ports_confirmed=False
    trial.connections=[v for v in trial.connections if item_id not in (v.source,v.target)]
    meta.observations=[v for v in meta.observations if v.item_id!=item_id]
   result=engine.evaluate(trial,meta,extra)
   # Evaluate essential checks even when no authored goals were selected.
   from .equipment_studio import passport
   check=passport(trial,meta,extra)
   rows.append({'profile':d,'configuration':preferred,'is_current':not changed,'status':check['status'],'checks':check['checks'],'missing':check['blockers'],'physical':result['physical']['status'],'connections':result['connections']['status'],'total_minor':result['cost']['total_minor'],'scope':'Comparison over available source snapshots. Different equipment is a proposed purchase with unknown price, not assumed owned or in stock.'})
  except (ValueError,KeyError,TypeError):continue
 rows.sort(key=lambda r:(sum(g['status']=='unmet' for g in r['checks']),len(r['missing']),not r['is_current'],r['profile']['id']))
 return {'options':rows,'input_digest':research.digest({'workspace':w.model_dump(),'planning':p.model_dump()}),'scope':'Up to sixteen source-backed alternatives in the installed and personally researched library. This is not an exhaustive market search, quote or purchase.'}

def register(module):
 def load(db,sid):
  row=db.execute('SELECT state FROM sessions WHERE id=? AND expires>?',(sid,time.time())).fetchone()
  if not row:raise Halt('The owning session expired.')
  return json.loads(row['state'])
 def edit(sid,jid,fn):
  with module.database() as db:
   db.execute('BEGIN IMMEDIATE');state=load(db,sid);job=state.get('open_research',{}).get(jid)
   if not job:raise Halt('Research receipt is unavailable.')
   if job['status'] not in ('RUNNING','QUEUED'):raise Halt('Research stopped.')
   if time.time()>job['expires_at']:raise Halt('Research reached its fixed time bound.')
   fn(state,job);state['version']+=1;module.save(db,sid,state);return copy.deepcopy(job)
 def event(sid,jid,phase,**values):
  def update(state,job):
   if phase in ('search','read'):
    if job['public_requests']>=5:raise Halt('The five-request public-source bound was reached.')
    job['public_requests']+=1
   job['phase']=phase;job['events'].append({'phase':phase,'at':int(time.time()),**values});job['events']=job['events'][-24:]
  return edit(sid,jid,update)
 def finish(sid,jid,status,error=None):
  with module.database() as db:
   db.execute('BEGIN IMMEDIATE');state=load(db,sid);job=state.get('open_research',{}).get(jid)
   if not job or job['status'] not in ('RUNNING','QUEUED'):return
   job['status']=status;job['phase']='finished';job['finished_at']=int(time.time())
   if error:job['errors'].append(str(error)[:500])
   state['version']+=1;module.save(db,sid,state)
 def view(job):
  out=copy.deepcopy(job);out.pop('server_instance',None)
  if out['status'] in ('RUNNING','QUEUED') and (job['server_instance']!=_instance or time.time()>job['expires_at']):out['status']='INTERRUPTED';out['phase']='stopped';out['errors'].append('This bounded run ended. Start a new research action if needed; it will not resume automatically.')
  return out
 class State(TypedDict,total=False):
  query:str;kind:str;sid:str;jid:str;tool:str;results:list;proposals:list;errors:list
 @lru_cache(maxsize=1)
 def graph():
  g=StateGraph(State)
  def model(s):
   event(s['sid'],s['jid'],'agent')
   observed={'discovered':bool(s.get('results')),'decision_facts_missing':1,'software_candidate':False,'software_answered':True,'supported_basket':False,'remaining_steps':3,'budget_cents':0}
   raw,receipt=trained_agent.generate(json.dumps(observed,separators=(',',':')),trained_agent.POLICY,8)
   if raw not in ('search','inspect','clarify','recommend','defer'):raise trained_agent.ModelError('The local model returned an unsupported research tool.')
   edit(s['sid'],s['jid'],lambda _,j:j.update(model_receipt=receipt,model_tool=raw,status='RUNNING'))
   return {'tool':raw}
  def search(s):
   found=discovery.discover(s['query'],s['kind'],lambda phase,**v:event(s['sid'],s['jid'],phase,**v))
   edit(s['sid'],s['jid'],lambda _,j:j.update(results=found['results'],errors=found['errors'],search_provider=found['search_provider']))
   return {'results':found['results'],'errors':found['errors'],'proposals':[]}
  def inspect(s):
   proposals=[];errors=list(s['errors'])
   for result in s['results'][:2]:
    try:
     event(s['sid'],s['jid'],'read',url=result['url'],title=result['title'])
     doc=research.fetch(result['url'],consent=True)
     event(s['sid'],s['jid'],'extract',source_url=doc['url'])
     options=discovery.proposals(doc,s['query'],s['kind'])
     checked=[]
     for proposal in options[:3]:
      proposal['proposal_id']=uuid.uuid4().hex;proposal['source_title']=result['title'];proposal['source_method']=doc.get('method','');validate_proposal(doc,proposal);checked.append(proposal)
     def remember(state,job):
      docs=state.setdefault('planning_documents',{});docs[doc['id']]=doc
      while len(docs)>8:del docs[next(iter(docs))]
      job['proposals'].extend(checked);job['sources'].append({'id':doc['id'],'url':doc['url'],'bytes':doc['bytes'],'retrieved_on':doc['retrieved_on'],'identity_terms_present':research.extract_candidates(doc,s['query'])['identity_terms_present']})
     edit(s['sid'],s['jid'],remember);proposals.extend(checked)
     if not checked:errors.append(result['title']+': no unambiguous supported literal facts. No specification was invented.')
    except Halt:raise
    except (ValueError,OSError) as exc:errors.append(result['title']+': '+str(exc)[:300])
   edit(s['sid'],s['jid'],lambda _,j:j.update(errors=errors))
   return {'proposals':proposals,'errors':errors}
  g.add_node('agent',model);g.add_node('search',search);g.add_node('inspect',inspect);g.add_edge(START,'agent')
  g.add_conditional_edges('agent',lambda s:'inspect' if s['tool']=='inspect' and s.get('results') else 'search' if s['tool']=='search' else 'end',{'search':'search','inspect':'inspect','end':END});g.add_edge('search','inspect');g.add_edge('inspect',END)
  return g.compile()
 def worker(sid,jid,query,kind,selected_results=None):
  try:
   with tracing_context(enabled=False):out=graph().invoke({'sid':sid,'jid':jid,'query':query,'kind':kind,'results':selected_results or [],'errors':[],'proposals':[]},config={'recursion_limit':6,'callbacks':[]})
   finish(sid,jid,'AWAITING_REVIEW' if out.get('proposals') else 'NEEDS_MODEL_DETAILS' if out.get('results') else 'NO_OFFICIAL_RESULT' if out.get('tool')=='search' else 'AGENT_PAUSED')
  except Halt as exc:finish(sid,jid,'STOPPED',exc)
  except Exception as exc:finish(sid,jid,'FAILED',str(exc)[:500])
  finally:_active.release()
 @module.app.get('/api/equipment/research-history')
 def history(request:Request):
  with module.database() as db:
   _,state=module.owner(request,db);rows=list(state.get('open_research',{}).values())
   return {'runs':[{'id':j['id'],'query':j['query'],'kind':j['kind'],'status':view(j)['status'],'created_at':j['created_at']} for j in reversed(rows)]}
 @module.app.post('/api/equipment/research/start')
 def start(body:StartResearch,request:Request):
  from .accounts import throttle
  with module.database() as db:
   sid,state=module.owner(request,db,True);saved=state.get('open_research',{}).get(body.client_id)
   if saved:
    if saved['query']!=body.query or saved['kind']!=body.kind or saved.get('selection')!={'source_job':body.source_job,'source_index':body.source_index}:raise HTTPException(409,'This action ID belongs to another public model query.')
    return view(saved)
   selected_results=[]
   if body.source_job:
    prior_source=state.get('open_research',{}).get(body.source_job)
    if not prior_source or prior_source['query']!=body.query or prior_source['kind']!=body.kind or body.source_index>=len(prior_source['results']):raise HTTPException(404,'Choose a source from your own matching discovery run.')
    selected_results=[prior_source['results'][body.source_index]]
   # Reuse only this account's complete, still-retained public snapshots.
   prior=None if body.source_job else next((v for v in reversed(list(state.get('open_research',{}).values())) if v['query']==body.query and v['kind']==body.kind and v['status']=='AWAITING_REVIEW' and time.time()-v.get('researched_at',v['created_at'])<86400 and all(doc['id'] in state.get('planning_documents',{}) for doc in v['sources'])),None)
   if prior:
    job=copy.deepcopy(prior);job.update(selection={'source_job':body.source_job,'source_index':body.source_index},id=body.client_id,created_at=int(time.time()),researched_at=prior.get('researched_at',prior['created_at']),cache_source_job=prior['id'],cache_reused=True,public_requests=0,accepted=[],server_instance=_instance)
    if job.get('model_receipt'):job['model_receipt'].update(cache_hit=True,inference_performed=False,reused_generated_tokens=job['model_receipt'].get('reused_generated_tokens',job['model_receipt'].get('generated_tokens',0)),generated_tokens=0)
    rows=state.setdefault('open_research',{});rows[body.client_id]=job
    while len(rows)>8:del rows[next(iter(rows))]
    state['version']+=1;module.save(db,sid,state);return view(job)
   if not _active.acquire(blocking=False):raise HTTPException(429,'A local research action is already running. Your setup is unchanged.')
   try:
    if not throttle(db,'open-research:'+sid,8,3600):raise HTTPException(429,'Eight public-model research actions per hour. Existing source profiles remain usable.')
    job={'id':body.client_id,'query':body.query,'kind':body.kind,'status':'QUEUED','phase':'queued','created_at':int(time.time()),'expires_at':int(time.time()+150),'server_instance':_instance,'events':[],'sources':[],'results':[],'proposals':[],'errors':[],'public_requests':0,'model_receipt':None,'accepted':[],'selection':{'source_job':body.source_job,'source_index':body.source_index},'scope':'Only this public product name is sent to free search. Manufacturer pages are untrusted data; every proposed fact is checked against its literal quote. No workspace, account, document, credential or payment data goes to search. No paid API, model-provider call, order or setup mutation.'}
    rows=state.setdefault('open_research',{});rows[body.client_id]=job
    while len(rows)>8:del rows[next(iter(rows))]
    state['version']+=1;module.save(db,sid,state)
   except BaseException:_active.release();raise
  _pool.submit(worker,sid,body.client_id,body.query,body.kind,selected_results)
  return view(job)
 @module.app.get('/api/equipment/research/{jid}')
 def read(jid:str,request:Request):
  with module.database() as db:
   _,state=module.owner(request,db);job=state.get('open_research',{}).get(jid)
   if not job:raise HTTPException(404,'Research is unavailable in this account.')
   return view(job)
 @module.app.post('/api/equipment/research/{jid}/cancel')
 def cancel(jid:str,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);job=state.get('open_research',{}).get(jid)
   if not job:raise HTTPException(404,'Research is unavailable in this account.')
   if job['status'] in ('RUNNING','QUEUED'):job['status']='CANCELLED';job['finished_at']=int(time.time());state['version']+=1;module.save(db,sid,state)
   return view(job)
 @module.app.post('/api/equipment/research/{jid}/accept')
 def accept(jid:str,body:Accept,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);job=state.get('open_research',{}).get(jid)
   if not job or job['status']!='AWAITING_REVIEW':raise HTTPException(409,'Finish a current research run before reviewing a proposal.')
   proposal=next((p for p in job['proposals'] if p['proposal_id']==body.proposal_id),None)
   if not proposal:raise HTTPException(404,'This proposal is unavailable in your research run.')
   doc=state.get('planning_documents',{}).get(proposal['source_id'])
   if not doc:raise HTTPException(409,'The owned source snapshot was evicted. Research the current source again.')
   try:profile=validate_proposal(doc,proposal)
   except ValueError as exc:raise HTTPException(422,str(exc)) from exc
   rows=state.setdefault('planning_profiles',{})
   if profile['id'] not in rows and len(rows)>=40:raise HTTPException(409,'Keep at most forty personal source profiles.')
   rows[profile['id']]=profile
   if profile['id'] not in job['accepted']:job['accepted'].append(profile['id'])
   state['version']+=1;module.save(db,sid,state)
   return {'profile':profile,'notice':'Saved the reviewed source profile. Choose its exact configuration before adding it to your setup.'}
 @module.app.post('/api/equipment/alternatives')
 def alternatives(body:Compare,request:Request):
  with module.database() as db:
   _,state=module.owner(request,db,True);extra=profiles(state);body.planning=validated_permission(body.workspace,body.planning,state)
  try:return compare_designs(body.workspace,body.planning,body.item_id,extra)
  except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
