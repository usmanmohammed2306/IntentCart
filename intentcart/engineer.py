"""Account-owned, bounded local setup engineering and counterfactual repair.
The model chooses a tool; deterministic checks, never model claims, grade work.
"""
from __future__ import annotations
import copy,json,time,uuid
from typing import Literal,TypedDict
from functools import lru_cache
from fastapi import HTTPException,Request
from pydantic import Field
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from .planning_models import Design,Planning,Goal
from .workspace import Workspace
from . import planning_engine as engine,device_research,trained_agent,seamless

INSTANCE=uuid.uuid4().hex

class Run(Design):
 client_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 action:Literal['build','inspect','repair','stress']='inspect'
 query:str=Field(default='',max_length=1200)
 variant:int=Field(default=0,ge=0,le=31)
 scenario:Literal['suite','desk','budget','dock','cable','host']='suite'
 width_cm:float|None=Field(default=None,gt=0,le=1000)
 depth_cm:float|None=Field(default=None,gt=0,le=1000)
 budget_minor:int|None=Field(default=None,ge=0,le=100000000)
 device_id:str=Field(default='',max_length=100)
class Preferences(Design):
 handedness:Literal['any','left','right']='any'
 budget_minor:int|None=Field(default=None,ge=0,le=100000000)
 no_extra_software:bool=False
 quiet:bool=False

class Cancel(Design):
 client_id:str=Field(pattern=r'^[a-f0-9]{32}$')

def with_core(w,p):
 out=copy.deepcopy(p);kinds={g.kind for g in out.goals if g.required and (not g.state_id or g.state_id==p.active_state)};values=[]
 if w.items:values=[('surface_fit','Fits your desk',None),('identity','Models identified',None)]
 if any(i.kind in ('monitor','mouse','keyboard','dock') for i in w.items):values.append(('connections','Devices connect',None))
 if w.budget_cents is not None:values.append(('budget','Within your budget',w.budget_cents))
 if p.allow_driver is not True and any(i.kind in ('laptop','desktop') for i in w.items) and any(i.kind=='monitor' for i in w.items):values.append(('native_displays','Supports your screens',sum(i.kind=='monitor' for i in w.items)))
 if any(not i.owned for i in w.items):values.append(('availability','Available to buy',None))
 for kind,text,value in values:
  if kind not in kinds:
   ident='engineer-'+kind
   while any(g.id==ident for g in out.goals):ident+='x'
   out.goals.append(Goal(id=ident,kind=kind,text=text,value=value))
 return out

def assessment(w,p):
 a=engine.evaluate(w,with_core(w,p))
 if not any(i.kind in ('laptop','desktop') for i in w.items) and any(i.kind in ('monitor','mouse','keyboard') for i in w.items):
  a['connections']={'status':'unknown','routes':[],'questions':['Add the computer these devices will connect to.'],'summary':'The computer is not specified.'}
  for g in a['goals']:
   if g['kind']=='connections':g.update(status='unknown',reason='Add the computer these devices will connect to.')
  a['status']='NEEDS_INFO'
 a['problems']=[{'key':g['id'],'kind':g['kind'],'title':{'surface_fit':'Check desk measurements','identity':'Identify your equipment','connections':'Complete the connections','budget':'Complete the price','availability':'Check current availability','count':'Adjust the quantity'}.get(g['kind'],g['text']),'detail':g['reason'],'status':g['status']} for g in a['goals'] if g['required'] and g['status'] in ('unknown','unmet')]
 for i in a['source_issues']:a['problems'].append({'key':i['code']+i.get('item_id',''),'kind':'identity','title':'Review a changed specification','detail':i['message'],'status':'unknown'})
 resolved=engine.resolve(w,p);a['native_limits']=[{'item_id':i.id,'name':i.name,'limit':resolved['facts'][i.id].get('native_displays'),'requested':sum(j.kind=='monitor' for j in w.items)} for i in w.items if i.kind in ('laptop','desktop')]
 for problem in a['problems']:
  if problem['kind']=='native_displays' and problem['status']=='unmet':problem['title']='Your laptop supports fewer screens';problem['detail']='; '.join(f"{r['name']}: {r['limit']} external screen(s), {r['requested']} requested" for r in a['native_limits'] if r['limit'] is not None)
 a['label']='Ready to review' if not a['problems'] and w.items else str(len(a['problems']))+' things to resolve' if w.items else 'Add your equipment'
 return a

def changed_items(a,b):
 before={i.id:i.model_dump() for i in a.items};after={i.id:i.model_dump() for i in b.items}
 return [i for i in sorted(set(before)|set(after)) if before.get(i)!=after.get(i)]

def protected(original,p,w,q):
 # Repair never relaxes requirements, claims ownership or grants software consent.
 if p.goals!=q.goals or p.allow_driver!=q.allow_driver or p.driver_permission_token!=q.driver_permission_token:return False
 for i in original.items:
  other=next((x for x in w.items if x.id==i.id),None)
  if other is None or other.model!=i.model or other.owned!=i.owned:return False
  if i.locked and other!=i:return False
 return {i.id for i in original.items}=={i.id for i in w.items}

def repair(w,p):
 before=assessment(w,p);candidates=[]
 # First and only automatic mutation is verified placement. Selection/purchase changes remain proposals.
 placed,result=engine.arrange(w,p,node_limit=6000)
 if result['status']=='found' and protected(w,p,placed,p):
  after=assessment(placed,p)
  old={g['id']:g['status'] for g in before['goals']};new={g['id']:g['status'] for g in after['goals']}
  nonworse=all(new.get(k)==v for k,v in old.items() if v in ('met','qualified'))
  better=len(after['problems'])<len(before['problems']) or before['physical']['status']=='conflict' and after['physical']['status']=='pass'
  if better and nonworse:candidates.append({'title':'Move equipment to fit','workspace':placed.model_dump(),'planning':p.model_dump(),'assessment':after,'changed_items':changed_items(w,placed),'automatic':True})
 # Model substitutions are offered only through existing reviewed-source selection.
 resolved=engine.resolve(w,p);screens=sum(i.kind=='monitor' for i in w.items)
 alternatives=[]
 for i in w.items:
  f=resolved['facts'].get(i.id,{})
  if i.kind in ('laptop','desktop') and f.get('native_displays') is not None and screens>f['native_displays']:
   alternatives.append({'kind':'native_limit','item_id':i.id,'title':f'{i.name} supports {f["native_displays"]} external screen(s)','action':'Choose a different computer or explicitly change your screen requirement.','automatic':False})
 if before['cost']['total_minor'] is not None and w.budget_cents is not None and before['cost']['total_minor']>w.budget_cents:alternatives.append({'kind':'budget','title':'The complete cost exceeds your budget','action':'Compare lower-cost current offers or mark equipment you actually own.','automatic':False})
 if before['physical']['unknown']:alternatives.append({'kind':'measure','title':'Some equipment sizes are missing','action':'Confirm the model or enter its measured size. Estimated graphics cannot prove desk fit.','automatic':False})
 if any(x['kind']=='connections' for x in before['problems']):alternatives.append({'kind':'connections','title':'A connection needs attention','action':'Identify the affected models and required cable; software changes need your permission.','automatic':False})
 return {'applied':bool(candidates),'candidate':candidates[0] if candidates else None,'alternatives':alternatives,'before':before,'after':candidates[0]['assessment'] if candidates else before,'search':result,'scope':'Only verified placement is automatically repaired. Models, quantities, ownership, budget, permissions and required goals are never silently changed.'}

def stress(w,p,body):
 worlds=[]
 if body.scenario in ('suite','desk'):
  a=copy.deepcopy(w);a.surface.width=body.width_cm*10 if body.width_cm else max(1,(a.surface.width or 1200)*.75);a.surface.depth=body.depth_cm*10 if body.depth_cm else a.surface.depth;worlds.append(('desk','Smaller desk',a,copy.deepcopy(p)))
 if body.scenario in ('suite','budget'):
  a=copy.deepcopy(w);a.budget_cents=body.budget_minor if body.budget_minor is not None else int((w.budget_cents if w.budget_cents is not None else engine.costs(w,p)['total_minor'] or 10000)*.8);q=copy.deepcopy(p)
  for g in q.goals:
   if g.kind=='budget':g.value=a.budget_cents
  worlds.append(('budget','Lower budget',a,q))
 for kind,label in [('dock','Without the dock'),('cable','Without a cable')]:
  if body.scenario not in ('suite',kind):continue
  row=next((i for i in w.items if i.kind==kind),None)
  if row:
   a=copy.deepcopy(w);q=copy.deepcopy(p);a.items=[i for i in a.items if i.id!=row.id];a.connections=[c for c in a.connections if c.source!=row.id and c.target!=row.id];q.devices=[d for d in q.devices if d.item_id!=row.id];q.observations=[o for o in q.observations if o.item_id!=row.id];q.offers=[o for o in q.offers if o.item_id!=row.id];worlds.append((kind,label,a,q))
 if body.scenario=='host':
  host=next((i for i in w.items if i.kind in ('laptop','desktop')),None);profile=next((d for d in device_research.catalog()+[engine.profile_dict(d) for d in p.profiles] if d['id']==body.device_id),None)
  if not host or not profile or profile['kind'] not in ('laptop','desktop'):raise ValueError('Choose an available computer model for this experiment.')
  from .planning_models import DeviceSelection
  cfg=next((k for k in profile['configurations'] if k=='in_use'),next(iter(profile['configurations'])))
  q=copy.deepcopy(p);q.observations=[o for o in q.observations if o.item_id!=host.id];q.offers=[o for o in q.offers if o.item_id!=host.id];a,q=engine.apply_configuration(w,q,host.id,DeviceSelection(item_id=host.id,device_id=profile['id'],configuration=cfg,source_digest=profile['digest'],reviewed=True));q.allow_driver=None;q.driver_permission_token=None;worlds.append(('host','Different computer · hypothetical',a,q))
 results=[]
 for key,title,a,q in worlds:
  r=repair(a,q);results.append({'key':key,'title':title,'workspace':a.model_dump(),'planning':q.model_dump(),'assessment':r['before'],'repair':r,'hypothetical':True,'identity_review_required':key=='host'})
 return {'baseline':assessment(w,p),'worlds':results,'scope':'Read-only experiments over declared geometry/source snapshots. No changed account, inventory, order, source truth, approval or payment.'}

class State(TypedDict,total=False):
 body:Run
 workspace:Workspace
 planning:Planning
 tool:str
 receipt:dict
 assessment:dict
 result:dict
 events:list
 persist:object
 preferences:dict

@lru_cache(maxsize=1)
def graph():
 g=StateGraph(State)
 def note(s,tool,data):
  events=s.get('events',[])+[{'tool':tool,**data}];s['persist']('working',events,None);return events
 def model(s):
  b=s['body'];w=b.workspace;raw,receipt=trained_agent.generate(json.dumps({'discovered':bool(w.items),'decision_facts_missing':min(9,sum(not i.dimensions for i in w.items)),'software_candidate':False,'software_answered':True,'supported_basket':bool(w.items),'remaining_steps':6,'budget_cents':w.budget_cents or 0},separators=(',',':')),trained_agent.POLICY,8)
  if raw not in ('search','inspect','recommend','clarify','defer'):raise ValueError('The local model returned an unsupported action.')
  return {'tool':raw,'receipt':receipt,'workspace':copy.deepcopy(w),'planning':copy.deepcopy(b.planning),'events':note(s,'model_decision',{'decision':raw,'inference_performed':receipt['inference_performed']})}
 def plan(s):
  b=s['body'];r=seamless.draft(s['workspace'],s['planning'],b.query,True,b.variant,s['tool'])
  if r['applied']:
   p=Planning.model_validate(r['planning']);w=Workspace.model_validate(r['workspace']);pref=s.get('preferences',{})
   if w.budget_cents is None and pref.get('budget_minor') is not None:w.budget_cents=pref['budget_minor']
   if pref.get('no_extra_software') and p.allow_driver is None:p.allow_driver=False
   for kind,value,text in [('handedness',pref.get('handedness','any'),'Your saved mouse preference'),('noise',None,'Your saved quiet-equipment preference')]:
    if (kind=='handedness' and value=='any') or (kind=='noise' and not pref.get('quiet')) or any(g.kind==kind for g in p.goals) or len(p.goals)>=60:continue
    ident='preference-'+kind
    while any(g.id==ident for g in p.goals):ident+='x'
    p.goals.append(Goal(id=ident,kind=kind,category='mouse' if kind=='handedness' else '',text=text,value=value))
   r['workspace']=w.model_dump();r['planning']=p.model_dump()
  return {'workspace':Workspace.model_validate(r['workspace']),'planning':Planning.model_validate(r['planning']),'result':r,'events':note(s,'build_draft',{'applied':r['applied'],'status':r['status']})}
 def verify(s):
  a=assessment(s['workspace'],s['planning']);return {'assessment':a,'events':note(s,'verify_setup',{'status':a['status'],'unresolved':len(a['problems'])})}
 def fix(s):
  r=repair(s['workspace'],s['planning']);return {'result':{'repair':r,'workspace':r['candidate']['workspace'] if r['candidate'] else s['workspace'].model_dump(),'planning':s['planning'].model_dump(),'applied':r['applied'] or bool(s['body'].action=='build' and s.get('result',{}).get('applied')),'assessment':r['after']},'events':note(s,'repair_layout',{'applied':r['applied'],'remaining':len(r['after']['problems'])})}
 def test(s):
  r=stress(s['workspace'],s['planning'],s['body']);return {'result':r,'events':note(s,'stress_test',{'worlds':len(r['worlds'])})}
 g.add_node('model',model);g.add_node('plan',plan);g.add_node('verify',verify);g.add_node('repair',fix);g.add_node('stress',test)
 g.add_edge(START,'model');g.add_conditional_edges('model',lambda s:'verify' if s['tool'] in ('defer','clarify') or s['body'].action!='build' else 'plan',{'verify':'verify','plan':'plan'});g.add_edge('plan','verify')
 g.add_conditional_edges('verify',lambda s:'end' if s['tool'] in ('defer','clarify') else 'stress' if s['body'].action=='stress' else 'repair',{'end':END,'stress':'stress','repair':'repair'});g.add_edge('repair',END);g.add_edge('stress',END)
 return g.compile()

def register(module):
 from . import team_planning,merchant_checkout
 team_planning.register(module)
 merchant_checkout.register(module)
 def present(row):
  out=copy.deepcopy(row)
  if out['status']=='working' and out.get('server_instance')!=INSTANCE:out.update(status='interrupted',error='The server restarted. No task was automatically repeated.')
  return out
 def owned(request,db,run_id):
  sid,state=module.owner(request,db);row=state.get('engineer_runs',{}).get(run_id)
  if not row:raise HTTPException(404,'This task is not in your account.')
  return sid,state,row
 @module.app.post('/api/setup/engineer')
 def start(body:Run,request:Request):
  from .planning_routes import validated_permission
  if len(body.workspace.items)>16:raise HTTPException(422,'Use up to sixteen items per workspace.')
  with module.database() as db:
   sid,state=module.owner(request,db,True);body.planning=validated_permission(body.workspace,body.planning,state);pref=copy.deepcopy(state.get('setup_preferences',{}));digest=device_research.digest({'input':body.model_dump(exclude={'client_id'}),'preferences':pref})
   rows=state.setdefault('engineer_runs',{});old=rows.get(body.client_id)
   if old:
    if old['input_hash']!=digest:raise HTTPException(409,'That task belongs to another setup.')
    return present(old)
   from .accounts import throttle
   if not throttle(db,'engineer:'+sid,12,60):raise HTTPException(429,'Too many tasks this minute. Your workspace is retained.')
   if not seamless._active.acquire(blocking=False):raise HTTPException(429,'The local agent is finishing another task.')
   rows[body.client_id]={'id':body.client_id,'input_hash':digest,'status':'working','events':[],'result':None,'started_at':int(time.time()),'cancelled':False,'server_instance':INSTANCE}
   while len(rows)>12:del rows[next(iter(rows))]
   try:module.save(db,sid,state)
   except BaseException:
    seamless._active.release();raise
  initial_sid=sid
  def failed(error):
   with module.database() as db:
    saved=db.execute('SELECT state FROM sessions WHERE id=?',(initial_sid,)).fetchone()
    if saved:
     state=json.loads(saved['state']);row=state.get('engineer_runs',{}).get(body.client_id)
     if row:row.update(status='cancelled' if row['cancelled'] else 'failed',error=error);module.save(db,initial_sid,state)
  def persist(status,events,result):
   with module.database() as db:
    sid,state,row=owned(request,db,body.client_id)
    if state.get('setup_preferences',{})!=pref:raise ValueError('Your preferences changed. Run the task again with your current choices.')
    if row['cancelled']:raise ValueError('Task cancelled. Your workspace is unchanged.')
    row.update(status=status,events=events,result=result);module.save(db,sid,state)
  try:
   with tracing_context(enabled=False):out=graph().invoke({'body':body,'events':[],'persist':persist,'preferences':pref},config={'recursion_limit':10,'callbacks':[]})
   result=out.get('result') or {'applied':False,'workspace':body.workspace.model_dump(),'planning':body.planning.model_dump()}
   result.update(assessment=out['assessment'] if body.action=='stress' or not result.get('assessment') else result['assessment'],receipt=out['receipt'],model_tool=out['tool'])
   persist('complete',out['events'],result)
   with module.database() as db:return present(owned(request,db,body.client_id)[2])
  except (ValueError,trained_agent.ModelError) as exc:
   failed(str(exc));raise HTTPException(503 if isinstance(exc,trained_agent.ModelError) else 422,str(exc)) from exc
  except HTTPException as exc:
   failed('The login or permission changed while the task was running.');raise
  except Exception as exc:
   failed('Task interrupted: '+type(exc).__name__)
   raise HTTPException(500,'The task stopped. Your workspace is retained; inspect the saved task before trying again.') from exc
  finally:seamless._active.release()
 @module.app.get('/api/setup/engineer/{run_id}')
 def read(run_id:str,request:Request):
  with module.database() as db:return present(owned(request,db,run_id)[2])
 @module.app.post('/api/setup/engineer/{run_id}/cancel')
 def cancel(run_id:str,request:Request):
  with module.database() as db:
   module.owner(request,db,True);sid,state,row=owned(request,db,run_id)
   if present(row)['status']!='working':return {'cancelled':row['cancelled'],'status':present(row)['status']}
   row['cancelled']=True;row['status']='cancelled';module.save(db,sid,state);return {'cancelled':True,'status':'cancelled'}
 @module.app.post('/api/setup/readiness')
 def inspect(body:Design,request:Request):
  from .planning_routes import validated_permission
  with module.database() as db:
   _,state=module.owner(request,db,True);body.planning=validated_permission(body.workspace,body.planning,state)
  if len(body.workspace.items)>16:raise HTTPException(422,'Use up to sixteen items per workspace.')
  return assessment(body.workspace,body.planning)

 @module.app.get('/api/setup/preferences')
 def preferences(request:Request):
  with module.database() as db:
   _,state=module.owner(request,db);return state.get('setup_preferences',{'handedness':'any','budget_minor':None,'no_extra_software':False,'quiet':False})
 @module.app.post('/api/setup/preferences')
 def save_preferences(body:Preferences,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);value=body.model_dump(exclude={'workspace','planning'});state['setup_preferences']=value;module.save(db,sid,state);return value
 @module.app.get('/api/setup/workspaces/{project_id}/history')
 def history(project_id:str,request:Request):
  with module.database() as db:
   _,state=module.owner(request,db);row=state.get('workspace_projects',{}).get(project_id)
   if not row:raise HTTPException(404,'This workspace is not in your account.')
   results=[]
   for old in row.get('previous',[])[-4:]:
    item=copy.deepcopy(old);context=item.get('planning',{});context['allow_driver']=None;context['driver_permission_token']=None;context['offers']=[o for o in context.get('offers',[]) if not o.get('quote_id')];context['client_id']=None;results.append(item)
   return {'revisions':results,'notice':'Restore a separate copy. Previous payment approvals, delivery quotes and software permissions are not restored.'}

 @module.app.get('/api/setup/engineer')
 def recent(request:Request):
  with module.database() as db:
   _,state=module.owner(request,db);rows=[present(v) for v in state.get('engineer_runs',{}).values()]
   return {'tasks':[{'id':v['id'],'status':v['status'],'started_at':v['started_at']} for v in rows[-12:]]}
