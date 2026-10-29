"""Offline prompt-to-visual-draft planning. No payment or network tools.

New selections remain unreviewed. Estimated envelopes are used only in a
separate layout check and are never returned as measured device dimensions.
"""
from __future__ import annotations
import copy,json,re,threading,uuid
from fastapi import HTTPException,Request
from pydantic import Field
from .workspace import Workspace,Item,Pose,Dimensions,Requirement
from .planning_models import Design,Planning
from . import device_research,planning_engine as engine,trained_agent
from .planning_compiler import compile_request
from .sentence_setup import matches,configuration

class Draft(Design):
 query:str=Field(default='',max_length=1200)
 populate:bool=False
 variant:int=Field(default=0,ge=0,le=31)
 client_id:str=Field(pattern=r'^[a-f0-9]{32}$')

# Rendering envelopes only, not manufacturer measurements or purchase offers.
ENVELOPES={'laptop':(320,240,230),'desktop':(190,350,400),'monitor':(540,210,400),'keyboard':(360,140,30),'mouse':(75,120,45),'dock':(200,100,45),'cable':(160,50,15),'power':(100,65,35),'webcam':(100,65,55),'audio':(150,130,220),'storage':(100,70,20),'other':(160,160,100)}
_active=threading.Lock()

def draft(w:Workspace,p:Planning,query:str,populate:bool,variant:int,tool:str):
 if tool not in ('search','inspect','recommend'):return {'workspace':w.model_dump(),'planning':p.model_dump(),'applied':False,'status':'clarify','message':'Describe the equipment you want to include.','layout':None}
 out=copy.deepcopy(w);context=copy.deepcopy(p);changes=[];unreviewed=[];counts={}
 if populate:
  if len(set(re.findall(r'[$€£]\s*\d+(?:\.\d{1,2})?',query)))>1:return {'workspace':w.model_dump(),'planning':p.model_dump(),'applied':False,'status':'clarify','message':'Use one total budget amount. Your current setup is unchanged.','layout':None}
  parsed,compiled,coverage=compile_request(out,context,query)
  context=compiled
  counts={g.category:int(g.value) for g in compiled.goals if g.kind=='count' and any(c.get('goal_id')==g.id for c in coverage['covered'])}
  for kind in ENVELOPES:
   if re.search(r'\b(?:a|an)\s+'+re.escape(kind)+r'\b',query,re.I):counts.setdefault(kind,1)
  if matches(query,'laptop',[d.model_dump() for d in context.profiles]):counts.setdefault('laptop',1)
  if any(v>8 for v in counts.values()):raise ValueError('Use up to eight of each item and sixteen objects per setup.')
  # Explicit dimensions and budget are independent of item counts.
  from .workspace_intent import dimensions,budget
  if re.search(r'\d\s*(?:mm|cm|m)?\s*(?:x|×|by)\s*\d',query,re.I):
   try:width,depth=dimensions(query);out.surface=out.surface.model_copy(update={'kind':'desk','width':width,'depth':depth})
   except ValueError:pass
  if parsed.budget_cents is not None:out.budget_cents=parsed.budget_cents
  if query and not any(r.text==query for r in out.requirements):
   if len(out.requirements)>=40:raise ValueError('Review existing requirements before adding another request.')
   out.requirements.append(Requirement(id=uuid.uuid4().hex,text=query))
  for kind in ENVELOPES:
   if kind not in counts and re.search(r'\b(?:need|want|include|with)\b.*\b'+re.escape(kind)+r's?\b',query,re.I):counts[kind]=0 if re.search(r'\b(?:no|without|zero)\s+'+re.escape(kind)+r's?\b',query,re.I) else 1
  if not counts and not out.items:
   width=out.surface.width or 0;depth=out.surface.depth or 0;counts={'laptop':1,'monitor':1 if width>=1000 and depth>=500 else 0,'mouse':1 if width>=480 else 0};changes.append('A size-aware starter draft; adjust the prompt to change the equipment.')
  for kind,count in counts.items():
   previous=[i for i in out.items if i.kind==kind];locked=[i for i in previous if i.locked]
   if len(locked)>count:return {'workspace':w.model_dump(),'planning':p.model_dump(),'applied':False,'status':'locked','message':'Unlock equipment before reducing its quantity.','layout':None}
   keep=locked+[i for i in previous if not i.locked][:max(0,count-len(locked))]
   removed={i.id for i in previous if i not in keep};out.items=[i for i in out.items if i.id not in removed]
   identified=matches(query,kind,[d.model_dump() for d in context.profiles])
   profile=identified[0] if len(identified)==1 else None
   # Exact model names are suggestions, not human-reviewed identity bindings.
   replaced=set()
   for row in keep:
    if profile and row.model!=profile['name']:
     if row.locked:return {'workspace':w.model_dump(),'planning':p.model_dump(),'applied':False,'status':'locked','message':'Unlock equipment before changing its model.','layout':None}
     row.model=profile['name'];row.name=profile['name'][:100];row.dimensions=None;row.ports=[];row.ports_confirmed=False;row.price_cents=None;row.owned=bool(re.search(r'\bI (?:have|own|use)\b|\bmy laptop\b',query,re.I));replaced.add(row.id);unreviewed.append(row.id)
   context.devices=[d for d in context.devices if d.item_id not in replaced];context.observations=[d for d in context.observations if d.item_id not in replaced];context.offers=[o for o in context.offers if o.item_id not in replaced]
   for n in range(count-len(keep)):
    row=Item(id=uuid.uuid4().hex,kind=kind,name=(profile['name'] if profile else kind.title())[:100],model=profile['name'] if profile else '',owned=bool(kind=='laptop' and profile and re.search(r'\bI (?:have|own|use)\b|\bmy laptop\b',query,re.I)))
    if profile:
     fields=profile['configurations'][configuration(profile)]
     if all(fields.get(k) for k in ('width_mm','depth_mm','height_mm')):row.dimensions=Dimensions(width=fields['width_mm'],depth=fields['depth_mm'],height=fields['height_mm'],basis='illustrative',source='Unreviewed catalog configuration; confirm exact variant',state=configuration(profile))
    out.items.append(row);unreviewed.append(row.id)
   changes.append(f'{count} {kind}')
  live={i.id for i in out.items};out.connections=[c for c in out.connections if c.source in live and c.target in live]
  context.devices=[d for d in context.devices if d.item_id in live];context.observations=[d for d in context.observations if d.item_id in live];context.offers=[o for o in context.offers if not o.item_id or o.item_id in live]
 if any(g.kind=='no_purchase' and g.required for g in context.goals) and any(not i.owned for i in out.items):return {'workspace':w.model_dump(),'planning':p.model_dump(),'applied':False,'status':'reuse','message':'Reuse-only needs enough owned equipment. No purchase items were added.','layout':None}
 if len(out.items)>16:raise ValueError('Use up to sixteen objects in one interactive setup.')
 if not out.items:return {'workspace':w.model_dump(),'planning':p.model_dump(),'applied':False,'status':'empty','message':'Describe what to include, such as one monitor and a mouse.','layout':None}
 if out.surface.kind not in ('desk','shared','shelf') or not out.surface.width or not out.surface.depth:return {'workspace':w.model_dump(),'planning':p.model_dump(),'applied':False,'status':'surface','message':'Set a table width and depth first.','layout':None}
 from .planning_routes import permission_binding
 if context.allow_driver is True and permission_binding(w,p)!=permission_binding(out,context):context.allow_driver=None;context.driver_permission_token=None
 original_dimensions={i.id:copy.deepcopy(i.dimensions) for i in out.items};estimated=[];temp=copy.deepcopy(out)
 for i in temp.items:
  if not i.dimensions or i.dimensions.basis=='illustrative':
   a,b,c=(i.dimensions.width,i.dimensions.depth,i.dimensions.height) if i.dimensions else ENVELOPES[i.kind];estimated.append(i.id)
   i.dimensions=Dimensions(width=a,depth=b,height=c,basis='user_measured',source='Temporary layout envelope only; not returned as measurement',state='visual draft')
  if not i.locked:
   width=out.surface.width;depth=out.surface.depth;side=-1 if variant%2 else 1
   anchors={'monitor':(side*width*.12,-depth*.21),'laptop':(-side*width*.25,depth*.16),'mouse':(side*width*.32,depth*.19),'keyboard':(0,depth*.23),'dock':(-side*width*.35,-depth*.12),'cable':(0,depth*.34)}
   x,z=anchors.get(i.kind,(side*width*.22,0));index=[j.id for j in temp.items if j.kind==i.kind].index(i.id);i.pose=Pose(x=x+index*min(width*.18,240),z=z+(variant//2%2)*min(depth*.07,45),yaw=0)
 arranged,placement=engine.arrange(temp,context,node_limit=6000)
 physical=engine.physical(arranged,context)
 if placement['status']!='found' or physical['status']!='pass':return {'workspace':w.model_dump(),'planning':p.model_dump(),'applied':False,'status':'no_fit','message':'The requested equipment did not fit. Try a larger table or fewer items.','layout':{'status':placement['status'],'nodes':placement['nodes'],'estimated_items':estimated}}
 for i in arranged.items:i.dimensions=original_dimensions[i.id]
 actual=engine.physical(arranged,context)
 return {'workspace':Workspace.model_validate(arranged.model_dump()).model_dump(),'planning':Planning.model_validate(context.model_dump()).model_dump(),'applied':True,'status':'draft','message':'Layout updated'+(' · estimated sizes' if estimated else ''),'changes':changes,'unreviewed_items':unreviewed,'layout':{'status':'pass','nodes':placement['nodes'],'estimated_items':estimated,'physical':actual['status']},'scope':'Reversible visual draft. Estimated envelopes are not measurements. New model identities, prices and compatibility remain unreviewed. No purchase or approval.'}

def register(module):
 @module.app.post('/api/setup/visual-draft')
 def start(body:Draft,request:Request):
  from .planning_routes import validated_permission
  identity=device_research.digest(body.model_dump(exclude={'client_id'}))
  with module.database() as db:
   sid,state=module.owner(request,db,True);body.planning=validated_permission(body.workspace,body.planning,state)
   old=state.get('visual_drafts',{}).get(body.client_id)
   if old:
    if old['input_hash']!=identity:raise HTTPException(409,'That action belongs to another setup.')
    return old['result']
   from .accounts import throttle
   if not throttle(db,'visual-draft:'+sid,12,60):raise HTTPException(429,'Autopilot paused after twelve requests this minute. Keep editing or retry shortly.')
  if not _active.acquire(blocking=False):raise HTTPException(429,'Autopilot is finishing a layout. Try again shortly.')
  try:
   observed={'discovered':bool(body.workspace.items),'decision_facts_missing':min(9,sum(not i.dimensions for i in body.workspace.items)),'software_candidate':False,'software_answered':True,'supported_basket':bool(body.workspace.items),'remaining_steps':4,'budget_cents':body.workspace.budget_cents or 0}
   raw,receipt=trained_agent.generate(json.dumps(observed,separators=(',',':')),trained_agent.POLICY,8)
   result=draft(body.workspace,body.planning,body.query,body.populate,body.variant,raw);result['receipt']=receipt;result['model_tool']=raw;result['variant']=body.variant
   with module.database() as db:
    sid,state=module.owner(request,db,True);rows=state.setdefault('visual_drafts',{});rows[body.client_id]={'input_hash':identity,'result':result}
    while len(rows)>8:del rows[next(iter(rows))]
    state['version']+=1;module.save(db,sid,state)
   return result
  except ValueError as exc:raise HTTPException(422,str(exc)) from exc
  except trained_agent.ModelError as exc:raise HTTPException(503,str(exc)) from exc
  finally:_active.release()

 from . import engineer
 engineer.register(module)
