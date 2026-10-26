"""Owned planning/research endpoints. No provider keys, purchases or deployments."""
import copy,json,uuid,base64
from datetime import date
from fastapi import Request,HTTPException
from pydantic import Field
from .workspace import Strict,Workspace
from .planning_models import Planning,Design,Start,Advance,Query,SourceRequest,SourceReview,ImportCatalog,Merge,DeviceSelection,Profile
from . import planning_engine as engine,planning_runs,planning_merge,device_research as research,trained_agent
class Bind(Design):
 item_id:str=Field(max_length=64)
 selection:DeviceSelection
class State(Design):state_id:str=Field(max_length=64)
class Document(Strict):
 filename:str=Field(min_length=1,max_length=100)
 data_base64:str=Field(min_length=1,max_length=2000000)
 consent:bool=False
class Backup(Strict):
 notice:str=Field(default='',max_length=1000)
 schema_version:int
 projects:list[dict]=Field(max_length=20)
class Answer(Strict):
 run_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 revision:int=Field(ge=0)
 decision:__import__('typing').Literal['allowed','denied']
class Permission(Design):
 decision:__import__('typing').Literal['allowed','denied','undecided']
class Cancel(Strict):
 run_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 revision:int=Field(ge=0)

def permission_binding(w,p):
 return research.digest({'devices':[b.model_dump() for b in p.devices],'hosts':[{'id':i.id,'model':i.model} for i in w.items if i.kind in ('laptop','desktop','dock')],'screens':sum(i.kind=='monitor' for i in w.items)})
def validated_permission(w,p,state):
 context=p.model_copy(deep=True)
 if context.allow_driver is True:
  permit=state.get('planning_permissions',{}).get(context.driver_permission_token)
  if not permit or permit['binding']!=permission_binding(w,p) or permit['date']!=date.today().isoformat():context.allow_driver=None;context.driver_permission_token=None
 return context

def profiles(state):return [engine.profile_dict(Profile.model_validate(v)) for v in state.get('planning_profiles',{}).values()]
def view(run,state):
 result=copy.deepcopy(run);result.pop('reservation',None);result['busy']=bool(result.pop('inflight',None));result.pop('source_documents',None)
 current=state.get('workspace_projects',{}).get(run.get('project_id'))
 result['fresh']=run['review_day']==date.today().isoformat() and run['source_identity']==planning_runs.source_identity(profiles(state)) and (not run.get('project_id') or current and current['revision']==run['project_revision'])
 return result

def register(module):
 app=module.app
 def error(exc):return HTTPException(422,str(exc))
 @app.post('/api/planning/permission')
 def permission(body:Permission,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);p=body.planning.model_copy(deep=True);p.allow_driver={'allowed':True,'denied':False,'undecided':None}[body.decision];p.driver_permission_token=None
   if p.allow_driver is True:
    token=uuid.uuid4().hex;permits=state.setdefault('planning_permissions',{});permits[token]={'binding':permission_binding(body.workspace,p),'date':date.today().isoformat()}
    while len(permits)>16:del permits[next(iter(permits))]
    p.driver_permission_token=token
   state['version']+=1;module.save(db,sid,state);return {'planning':p.model_dump(),'notice':'Your explicit software decision is bound to these exact devices/screens and today. No software was installed.'}
 def save_run(db,sid,state,run):state.setdefault('planning_runs',{})[run['id']]=run;state['version']+=1;module.save(db,sid,state)
 @app.post('/api/planning/evaluate')
 def evaluate(body:Design,request:Request):
  with module.database() as db:_,state=module.owner(request,db,True);extra=profiles(state);body.planning=validated_permission(body.workspace,body.planning,state)
  try:return {'assessment':engine.evaluate(body.workspace,body.planning,extra),'states':engine.state_reports(body.workspace,body.planning,extra),'procurement':engine.procurement(body.workspace,body.planning,extra)}
  except (ValueError,TypeError,KeyError) as exc:raise error(exc) from exc
 @app.post('/api/planning/research')
 def search(body:Query,request:Request):
  with module.database() as db:_,state=module.owner(request,db,True);extra=profiles(state)
  rows=research.lookup(body.query,body.kind,extra)
  return {'candidates':rows,'notice':'Select the exact year, revision and operating configuration. A name match does not identify your physical device. No network request or paid service used.'}
 @app.post('/api/planning/bind')
 def bind(body:Bind,request:Request):
  with module.database() as db:_,state=module.owner(request,db,True);extra=profiles(state)
  body.planning=validated_permission(body.workspace,body.planning,state)
  try:w,p=engine.apply_configuration(body.workspace,body.planning,body.item_id,body.selection,extra);return {'workspace':w.model_dump(),'planning':p.model_dump(),'assessment':engine.evaluate(w,p,extra)}
  except ValueError as exc:raise error(exc) from exc
 @app.post('/api/planning/source')
 def source(body:SourceRequest,request:Request):
  from .accounts import throttle
  with module.database() as db:
   sid,state=module.owner(request,db,True)
   if not throttle(db,'public-source:'+sid,8,3600):raise HTTPException(429,'Public research is limited to eight source reads per hour; cached reviewed facts remain available.')
  try:doc=research.fetch(body.url,consent=body.consent);extraction=research.extract_candidates(doc,body.identity)
  except (ValueError,OSError) as exc:raise error(exc) from exc
  with module.database() as db:
   sid,state=module.owner(request,db,True);docs=state.setdefault('planning_documents',{});docs[doc['id']]=doc
   while len(docs)>8:del docs[next(iter(docs))]
   state['version']+=1;module.save(db,sid,state)
  return {'source':doc,'extraction':extraction,'notice':'Remote content is data, never a tool instruction. No fact was accepted or workspace changed.'}
 @app.post('/api/planning/document')
 def document(body:Document,request:Request):
  with module.database() as db:module.owner(request,db,True)
  if not body.consent:raise HTTPException(422,'Confirm local document processing. No document content is sent to a model provider.')
  from pathlib import Path
  from .documents import extract
  try:
   raw=base64.b64decode(body.data_base64,validate=True);parsed=extract(raw,Path(body.filename).suffix.lower());sha=__import__('hashlib').sha256(raw).hexdigest();doc={'id':sha,'url':'local-document:'+sha,'retrieved_on':date.today().isoformat(),'text':'\n'.join(p['text'] for p in parsed['pages']),'method':parsed['method'],'bytes':len(raw),'authority':'Untrusted locally processed document; its instructions cannot authorize tools.'}
  except (ValueError,TypeError) as exc:raise error(exc) from exc
  with module.database() as db:
   sid,state=module.owner(request,db,True);docs=state.setdefault('planning_documents',{});docs[sha]=doc
   while len(docs)>8:del docs[next(iter(docs))]
   state['version']+=1;module.save(db,sid,state)
  return {'source':doc,'extraction':{'candidates':[],'notice':'Select short literal evidence; private document content stays on this installation.'}}
 @app.get('/api/planning/sources/{source_id}')
 def saved_source(source_id:str,request:Request):
  with module.database() as db:_,state=module.owner(request,db);doc=state.get('planning_documents',{}).get(source_id)
  if not doc:raise HTTPException(404,'Owned source snapshot unavailable; read it again.')
  return {'source':doc}
 @app.post('/api/planning/source/review')
 def review(body:SourceReview,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);doc=state.get('planning_documents',{}).get(body.source_id)
   if not doc:raise HTTPException(404,'Source is unavailable. Read it again before reviewing facts.')
   if body.device_id in {d['id'] for d in research.catalog()}:raise HTTPException(409,'Use a new revision ID; built-in reviewed profiles cannot be replaced silently.')
   try:profile=engine.profile_dict(Profile.model_validate(research.review(doc,body)))
   except ValueError as exc:raise error(exc) from exc
   rows=state.setdefault('planning_profiles',{})
   if body.device_id not in rows and len(rows)>=40:raise HTTPException(409,'Keep at most forty personal reviewed profiles.')
   rows[body.device_id]=profile;state['version']+=1;module.save(db,sid,state)
   return {'profile':profile,'notice':'Saved as a user-reviewed source snapshot. Existing plans bound to an older digest become stale.'}
 @app.post('/api/planning/state')
 def state_view(body:State,request:Request):
  with module.database() as db:_,state=module.owner(request,db,True);extra=profiles(state)
  body.planning=validated_permission(body.workspace,body.planning,state)
  try:w,p=engine.state_design(body.workspace,body.planning,body.state_id,extra);return {'workspace':w.model_dump(),'planning':p.model_dump(),'assessment':engine.evaluate(w,p,extra)}
  except ValueError as exc:raise error(exc) from exc
 @app.post('/api/planning/import-catalog')
 def import_catalog(body:ImportCatalog,request:Request):
  with module.database() as db:module.owner(request,db,True)
  unique={};invalid=[]
  for n,record in enumerate(body.records):
   try:
    value=engine.profile_dict(Profile.model_validate(record))
    if value['id'] in {d['id'] for d in research.catalog()}:raise ValueError('Built-in identity cannot be overridden.')
    if value['id'] in unique:
     if unique[value['id']]['digest']!=value['digest']:raise ValueError('Conflicting duplicate identifier.')
    else:unique[value['id']]=value
   except ValueError as exc:invalid.append({'record':n,'reason':str(exc)[:300]})
  rows=list(unique.values());tokens=set(research.normalize(body.query).split())
  if tokens:rows.sort(key=lambda r:-len(tokens&set(research.normalize(r['name']+' '+r['id']).split())))
  return {'records':rows[:body.max_records],'input_count':len(body.records),'unique_count':len(unique),'invalid':invalid[:20],'omitted':max(0,len(rows)-body.max_records),'notice':'Relevant bounded subset for review only. No workspace change, remote assets, source certification or automatic profile acceptance.'}
 @app.post('/api/planning/start')
 def start(body:Start,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True)
   if body.project_id:
    project=state.get('workspace_projects',{}).get(body.project_id)
    if not project:raise HTTPException(404,'Owned project not found.')
    if project['revision']!=body.project_revision:raise HTTPException(409,'Saved project changed. Merge/reload before starting a new plan.')
   body.planning=validated_permission(body.workspace,body.planning,state)
   if body.research_urls:
    from .accounts import throttle
    if not throttle(db,'autonomous-sources:'+sid,4,3600):raise HTTPException(429,'At most four source-reading plans per hour. Cached facts and manual editing remain available.')
   try:run=planning_runs.create(body,profiles(state));engine.evaluate(Workspace.model_validate(run['workspace']),Planning.model_validate(run['planning']),profiles(state))
   except (ValueError,TypeError) as exc:raise error(exc) from exc
   runs=state.setdefault('planning_runs',{})
   if any(r['status']=='RUNNING' for r in runs.values()):raise HTTPException(409,'Pause/cancel the current planning run before starting another.')
   while len(runs)>=4:del runs[next(iter(runs))]
   run.update(attempts=0,inflight=False);save_run(db,sid,state,run);return view(run,state)
 @app.get('/api/planning/runs')
 def runs(request:Request):
  with module.database() as db:_,state=module.owner(request,db);return {'runs':[view(r,state) for r in state.get('planning_runs',{}).values()]}
 @app.post('/api/planning/advance')
 def advance(body:Advance,request:Request):
  from .accounts import throttle
  last=None
  for _ in range(body.steps):
   with module.database() as db:
    sid,state=module.owner(request,db,True);old=state.get('planning_runs',{}).get(body.run_id)
    if not old:raise HTTPException(404,'Owned planning run not found.')
    if old['revision']!=(last['revision'] if last else body.revision):raise HTTPException(409,'Run changed in another request. Reload its current checkpoint.')
    if not view(old,state)['fresh']:
     old['status']='STALE';old['revision']+=1;save_run(db,sid,state,old);return view(old,state)
    if old['status']!='RUNNING':return view(old,state)
    if old.get('inflight'):raise HTTPException(409,'This step is already in flight. Do not resubmit it.')
    if old.get('attempts',0)>=old['max_steps']:old['status']='STEP_LIMIT';old['revision']+=1;save_run(db,sid,state,old);return view(old,state)
    if not throttle(db,'planning-step:'+sid,40,60):raise HTTPException(429,'Please wait before continuing the local agent.')
    token=uuid.uuid4().hex;old['inflight']=True;old['reservation']=token;old['attempts']=old.get('attempts',0)+1;save_run(db,sid,state,old);snapshot=copy.deepcopy(old);extra=profiles(state)
   try:computed=planning_runs.advance(snapshot,extra)
   except trained_agent.ModelError as exc:computed=copy.deepcopy(snapshot);computed['status']='MODEL_PAUSED';computed['questions'].append(str(exc))
   except (ValueError,TypeError,KeyError) as exc:computed=copy.deepcopy(snapshot);computed['status']='INPUT_PAUSED';computed['questions'].append(str(exc)[:500])
   with module.database() as db:
    sid,state=module.owner(request,db,True);current=state.get('planning_runs',{}).get(body.run_id)
    if not current or current['revision']!=snapshot['revision'] or current.get('reservation')!=token:raise HTTPException(409,'Run was cancelled or changed while the model was working. Its response was discarded.')
    docs=state.setdefault('planning_documents',{})
    for doc in computed.pop('source_documents',[]):docs[doc['id']]=doc
    while len(docs)>8:del docs[next(iter(docs))]
    computed['inflight']=False;computed.pop('reservation',None);computed['revision']+=1;save_run(db,sid,state,computed);last=view(computed,state)
    if computed['status']!='RUNNING':break
  return last
 @app.post('/api/planning/answer')
 def answer(body:Answer,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);run=state.get('planning_runs',{}).get(body.run_id)
   if not run or run['revision']!=body.revision or not view(run,state)['fresh'] or run['status']!='NEEDS_INFO' or not run.get('candidates'):raise HTTPException(409,'This checkpoint is not awaiting a supported candidate review.')
   if any(v['id']!=run['id'] and v['status']=='RUNNING' for v in state.get('planning_runs',{}).values()):raise HTTPException(409,'Stop the other active run first.')
   proposal=run['candidates'][0];w=Workspace.model_validate(proposal['workspace']);p=Planning.model_validate(proposal['planning']);p.allow_driver=body.decision=='allowed';p.driver_permission_token=None
   if p.allow_driver:
    token=uuid.uuid4().hex;state.setdefault('planning_permissions',{})[token]={'binding':permission_binding(w,p),'date':date.today().isoformat()};p.driver_permission_token=token
   run['workspace']=w.model_dump();run['planning']=p.model_dump();run['candidates']=[];run['questions']=list(run['coverage']['unrepresented']);run['status']='RUNNING';run['revision']+=1;run['events'].append({'step':run['step_count'],'model_tool':'human_permission','model_receipt':{'model_id':None,'external_requests':0},'result':{'decision':body.decision,'scope':'User decision for the displayed exact candidate; no software installed.'}});save_run(db,sid,state,run);return view(run,state)
 @app.post('/api/planning/cancel')
 def cancel(body:Cancel,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);run=state.get('planning_runs',{}).get(body.run_id)
   if not run:raise HTTPException(404,'Owned run not found.')
   if run['revision']!=body.revision:raise HTTPException(409,'Run changed. Reload before cancelling.')
   run['status']='CANCELLED';run['inflight']=False;run.pop('reservation',None);run['revision']+=1;save_run(db,sid,state,run);return view(run,state)
 @app.post('/api/planning/recover')
 def recover(body:Cancel,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);run=state.get('planning_runs',{}).get(body.run_id)
   if not run or run['revision']!=body.revision:raise HTTPException(409,'Owned checkpoint unavailable or changed.')
   if run['status'] in ('READY_FOR_REVIEW','CANCELLED','STALE'):raise HTTPException(409,'Start a new reviewed continuation for this terminal checkpoint.')
   if any(v['id']!=run['id'] and v['status']=='RUNNING' for v in state.get('planning_runs',{}).values()):raise HTTPException(409,'Stop the other active run before recovering this checkpoint.')
   run['inflight']=False;run.pop('reservation',None);run['status']='RUNNING';run['revision']+=1;save_run(db,sid,state,run);return view(run,state)
 @app.get('/api/planning/runs/{run_id}/brief')
 def brief(run_id:str,request:Request):
  with module.database() as db:
   _,state=module.owner(request,db);run=state.get('planning_runs',{}).get(run_id)
   if not run:raise HTTPException(404,'Owned run not found.')
   result=planning_runs.brief(run);result['fresh']=view(run,state)['fresh'];return result
 @app.post('/api/planning/merge')
 def merge(body:Merge,request:Request):
  with module.database() as db:
   _,state=module.owner(request,db,True);project=state.get('workspace_projects',{}).get(body.project_id)
   if not project:raise HTTPException(404,'Owned project not found.')
   base=next((r for r in project.get('previous',[])+[project] if r['revision']==body.base_revision),None)
   if not base:raise HTTPException(409,'The merge base is outside the retained history. Export both drafts and compare them explicitly.')
   result=planning_merge.merge({'workspace':base['workspace'],'planning':base.get('planning',Planning().model_dump())},{'workspace':body.workspace.model_dump(),'planning':body.planning.model_dump()},{'workspace':project['workspace'],'planning':project.get('planning',Planning().model_dump())});result['revision']=project['revision'];return result
 @app.get('/api/planning/backup')
 def backup(request:Request):
  with module.database() as db:
   _,state=module.owner(request,db);rows=[{'workspace':r['workspace'],'planning':{**r.get('planning',Planning().model_dump()),'allow_driver':False if r.get('planning',{}).get('allow_driver') is False else None,'driver_permission_token':None},'original_project_id':r['id'],'original_revision':r['revision']} for r in state.get('workspace_projects',{}).values()]
   return {'schema_version':1,'projects':rows,'notice':'Project data only, not an account/database/provider-usage backup. Old data may only be restored as new reviewed drafts; later authoritative work and spending counters are never rolled back.'}
 @app.post('/api/planning/restore-review')
 def restore(body:Backup,request:Request):
  with module.database() as db:_,state=module.owner(request,db,True)
  if body.schema_version!=1:raise HTTPException(422,'Unsupported project backup.')
  rows=[]
  try:
   for r in body.projects:
    if set(r)-{'workspace','planning','original_project_id','original_revision'}:raise ValueError('Backup contains unsupported authority or account fields.')
    w=Workspace.model_validate(r['workspace']);p=Planning.model_validate(r.get('planning',{}));p.client_id=None;p.allow_driver=False if p.allow_driver is False else None;p.driver_permission_token=None
    current=state.get('workspace_projects',{}).get(r.get('original_project_id'))
    rows.append({'workspace':w.model_dump(),'planning':p.model_dump(),'new_draft_only':True,'later_revision_exists':bool(current and current['revision']>r.get('original_revision',0))})
  except (ValueError,TypeError,KeyError) as exc:raise error(exc) from exc
  return {'drafts':rows,'notice':'Review each imported draft and save as a new project. Existing projects, identities, credentials, permissions, provider budgets and usage are unchanged.'}
