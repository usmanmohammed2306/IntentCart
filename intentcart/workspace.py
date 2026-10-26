"""Measured, revision-bound workspace planning. No purchasing or certification tools."""
from __future__ import annotations
import math,re,json,hashlib,time,uuid
from typing import Literal
from pydantic import BaseModel,Field,ConfigDict,model_validator
KINDS=('laptop','desktop','monitor','keyboard','mouse','dock','cable','power','webcam','audio','storage','other')
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
class Dimensions(Strict):
 width:float=Field(gt=0,le=10000)
 depth:float=Field(gt=0,le=10000)
 height:float=Field(gt=0,le=10000)
 basis:Literal['user_measured','manufacturer','reviewed_document','illustrative']='user_measured'
 source:str=Field(default='',max_length=500)
 state:str=Field(default='in use',min_length=1,max_length=80)
 @model_validator(mode='after')
 def provenance(self):
  if self.basis=='manufacturer' and not re.fullmatch(r'https://[^\s]+',self.source):raise ValueError('Manufacturer dimensions need an HTTPS source.')
  return self
class Pose(Strict):
 x:float=Field(default=0.,ge=-10000,le=10000)
 z:float=Field(default=0.,ge=-10000,le=10000)
 yaw:float=Field(default=0.,ge=-math.pi*2,le=math.pi*2)
class Item(Strict):
 id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
 kind:Literal['laptop','desktop','monitor','keyboard','mouse','dock','cable','power','webcam','audio','storage','other']
 name:str=Field(min_length=1,max_length=100)
 model:str=Field(default='',max_length=160)
 owned:bool=True
 price_cents:int|None=Field(default=None,ge=0,le=100000000)
 dimensions:Dimensions|None=None
 pose:Pose=Field(default_factory=Pose)
 ports:list[str]=Field(default_factory=list,max_length=24)
 ports_confirmed:bool=False
 locked:bool=False
 color:str=Field(default='#aebac7',pattern=r'^#[a-fA-F0-9]{6}$')
 @model_validator(mode='after')
 def ports_valid(self):
  if any(not re.fullmatch(r'[a-zA-Z0-9 ._+/-]{1,40}',p) for p in self.ports) or len(set(self.ports))!=len(self.ports):raise ValueError('Use distinct, short port labels.')
  return self
class Zone(Strict):
 id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
 name:str=Field(min_length=1,max_length=80)
 width:float=Field(gt=0,le=10000)
 depth:float=Field(gt=0,le=10000)
 pose:Pose=Field(default_factory=Pose)
class Surface(Strict):
 kind:Literal['desk','shared','shelf','lap','wall','none','unknown']='unknown'
 width:float|None=Field(default=None,gt=0,le=10000)
 depth:float|None=Field(default=None,gt=0,le=10000)
 clearance_mm:float|None=Field(default=None,ge=0,le=3000)
 zones:list[Zone]=Field(default_factory=list,max_length=12)
 @model_validator(mode='after')
 def paired(self):
  if (self.width is None)!=(self.depth is None):raise ValueError('Enter both surface dimensions or leave both unknown.')
  return self
class Requirement(Strict):
 id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
 text:str=Field(min_length=1,max_length=1200)
 status:Literal['open','met','unmet','boundary']='open'
 evidence:str=Field(default='',max_length=1000)
 @model_validator(mode='after')
 def support(self):
  if self.status!='open' and not self.evidence.strip():raise ValueError('Resolved requirements need a reason; they are not automatically verified.')
  return self
class Connection(Strict):
 id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
 source:str
 target:str
 source_port:str=Field(max_length=40)
 target_port:str=Field(max_length=40)
 status:Literal['unknown','user_confirmed']='unknown'
 evidence:str=Field(default='',max_length=500)
class Workspace(Strict):
 schema_version:Literal[2]=2
 name:str=Field(default='Untitled workspace',min_length=1,max_length=80)
 currency:str=Field(default='USD',pattern=r'^[A-Z]{3}$')
 budget_cents:int|None=Field(default=None,ge=0,le=100000000)
 shipping_cents:int|None=Field(default=None,ge=0,le=10000000)
 tax_cents:int|None=Field(default=None,ge=0,le=10000000)
 surface:Surface=Field(default_factory=Surface)
 items:list[Item]=Field(default_factory=list,max_length=48)
 connections:list[Connection]=Field(default_factory=list,max_length=64)
 requirements:list[Requirement]=Field(default_factory=list,max_length=40)
 finish:Literal['graphite','sand','moss']='graphite'
 @model_validator(mode='after')
 def references(self):
  ids=[i.id for i in self.items]
  for rows in (self.items,self.connections,self.requirements,self.surface.zones):
   if len({r.id for r in rows})!=len(rows):raise ValueError('IDs must be unique within each collection.')
  for edge in self.connections:
   if edge.source not in ids or edge.target not in ids or edge.source==edge.target:raise ValueError('Connections need two different existing items.')
   if edge.status=='user_confirmed' and not edge.evidence.strip():raise ValueError('Confirmed connections need evidence.')
  return self

def polygon(w,d,p):
 c,s=math.cos(p.yaw),math.sin(p.yaw)
 return [(p.x+x*c-z*s,p.z+x*s+z*c) for x,z in [(-w/2,-d/2),(w/2,-d/2),(w/2,d/2),(-w/2,d/2)]]
def overlap(a,b):
 # Strict SAT: touching edges are allowed; this checks horizontal footprints only.
 for poly in (a,b):
  for i,point in enumerate(poly):
   q=poly[(i+1)%4];axis=(-(q[1]-point[1]),q[0]-point[0]);pa=[x*axis[0]+z*axis[1] for x,z in a];pb=[x*axis[0]+z*axis[1] for x,z in b]
   if max(pa)<=min(pb)+1e-7 or max(pb)<=min(pa)+1e-7:return False
 return True

def analyze(w:Workspace):
 issues=[];polys={};fit='unknown';space=w.surface
 def issue(code,text,ids=None):issues.append({'code':code,'text':text,'item_ids':ids or []})
 if space.kind in ('none','unknown','wall','lap'):issue('surface_unknown','Choose a measured stable surface to assess a horizontal footprint. Wall, lap and structural suitability are not certified.')
 if space.kind in ('desk','shared','shelf') and space.width is not None:
  fit='pass'
  for i in w.items:
   if i.dimensions is None or i.dimensions.basis=='illustrative':
    issue('dimensions_unknown',i.name+' has no measured footprint.',[i.id]);continue
   d=i.dimensions;poly=polygon(d.width,d.depth,i.pose);polys[i.id]=poly
   if any(abs(x)>space.width/2+1e-6 or abs(z)>space.depth/2+1e-6 for x,z in poly):issue('outside_surface',i.name+' extends beyond the surface.',[i.id])
   for zone in space.zones:
    if overlap(poly,polygon(zone.width,zone.depth,zone.pose)):issue('reserved_overlap',i.name+' overlaps '+zone.name+'.',[i.id])
  rows=list(polys)
  for n,a in enumerate(rows):
   for b in rows[n+1:]:
    if overlap(polys[a],polys[b]):issue('item_overlap','Two measured footprints overlap.',[a,b])
  if any(i['code'] in ('outside_surface','reserved_overlap','item_overlap') for i in issues):fit='conflict'
  elif any(i['code']=='dimensions_unknown' for i in issues):fit='unknown'
 else:
  if not any(i['code']=='surface_unknown' for i in issues):issue('surface_unknown','Surface dimensions are unknown.')
 new=[i for i in w.items if not i.owned];subtotal=sum(i.price_cents or 0 for i in new);unknown_price=[i.id for i in new if i.price_cents is None]
 # No purchases => no shipping/tax; otherwise missing charges stay unknown.
 total=0 if not new else None if unknown_price or w.shipping_cents is None or w.tax_cents is None else subtotal+w.shipping_cents+w.tax_cents
 budget='unknown' if total is None or w.budget_cents is None else 'pass' if total<=w.budget_cents else 'conflict'
 if unknown_price:issue('price_unknown','Some proposed purchases have no price.',unknown_price)
 if new and (w.shipping_cents is None or w.tax_cents is None):issue('charges_unknown','Shipping and tax are not recorded; this is an items-only subtotal.')
 if budget=='conflict':issue('over_budget','The declared total exceeds your budget.')
 by_id={i.id:i for i in w.items};topology=[]
 for edge in w.connections:
  a,b=by_id[edge.source],by_id[edge.target]
  valid=edge.status=='user_confirmed' and a.ports_confirmed and b.ports_confirmed and edge.source_port in a.ports and edge.target_port in b.ports
  topology.append({'id':edge.id,'status':'user_confirmed' if valid else 'unknown'})
  if not valid:issue('connection_unknown','A connection needs exact ports and evidence.',[a.id,b.id])
 if not w.connections and len(w.items)>1:issue('connection_unknown','No connection map has been recorded.')
 open_requirements=[r.id for r in w.requirements if r.status=='open'];unmet=[r.id for r in w.requirements if r.status=='unmet'];boundaries=[r.id for r in w.requirements if r.status=='boundary']
 return {'fit':fit,'budget':budget,'subtotal_cents':subtotal,'total_cents':total,'purchase_count':len(new),'unknown_prices':unknown_price,'connections':topology,'requirements':{'open':open_requirements,'unmet':unmet,'boundary':boundaries},'issues':issues,'scope':'Horizontal bounding footprints and declared costs only. Connection evidence and requirement resolution are user declarations, not manufacturer certification. No purchases are made.'}

def digest(w):return hashlib.sha256(json.dumps(w.model_dump(),sort_keys=True,separators=(',',':')).encode()).hexdigest()

class Save(Strict):
 project_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
 revision:int=Field(ge=0)
 workspace:Workspace
 planning:dict|None=None
class Delete(Strict):revision:int=Field(ge=1)
class Check(Strict):workspace:Workspace
class Ask(Check):query:str=Field(min_length=1,max_length=700)

def public_record(r):return {k:v for k,v in r.items() if k not in ('proposal','previous')}
def register(module):
 from fastapi import Request,HTTPException
 # Request must be visible to FastAPI resolving postponed annotations.
 globals()['Request']=Request
 @module.app.get('/api/workspaces')
 def listing(request:Request):
  with module.database() as db:
   _,state=module.owner(request,db)
   from . import trained_agent,workspace_intent
   model=trained_agent.status();router=workspace_intent.status();model['ready']=model['ready'] and router['ready']
   if not router['ready']:model['notice']=router['notice']
   return {'projects':[public_record(v) for v in state.get('workspace_projects',{}).values()],'legacy_available':bool(state.get('studio_layout')),'model':model}
 @module.app.post('/api/workspaces/import-legacy')
 def import_legacy(request:Request):
  with module.database() as db:
   _,state=module.owner(request,db,True);old=state.get('studio_layout',{}).get('layout')
   if not old:raise HTTPException(404,'No earlier saved layout is available.')
   from .studio import Layout,valid
   old=valid(Layout.model_validate(old));items=[]
   sizes={'laptop':(320.,220.,230.),'monitor':(540.,190.,420.),'dock':(170.,80.,35.),'power':(110.,60.,30.),'cable':(120.,45.,12.)}
   for kind,part in old['parts'].items():
    width,depth,height=sizes[kind];scale=part['scale'];x,y,z=part['position']
    items.append(Item(id=kind,kind=kind,name='Earlier '+kind,owned=False,dimensions=Dimensions(width=width*scale,depth=depth*scale,height=height*scale,basis='illustrative',source='Earlier conceptual layout; not measured',state='Illustrative'),pose=Pose(x=x*1000,z=z*1000,yaw=max(-math.pi*2,min(math.pi*2,part['rotation']))),color=part['color'] or '#aebac7'))
   reference=json.dumps(old,separators=(',',':'))
   w=Workspace(name='Earlier visual layout',finish=old['finish'],items=items,requirements=[Requirement(id='legacy-reference',text=('Earlier scene reference, including relative scale/vertical offsets: '+reference)[:1200])])
   return {'workspace':w.model_dump(),'analysis':analyze(w),'notice':'Imported as a new unmeasured draft. Earlier saved work remains intact. Review ownership and placement.'}
 @module.app.post('/api/workspaces/check')
 def check(body:Check,request:Request):
  with module.database() as db:module.owner(request,db,True)
  return analyze(body.workspace)
 @module.app.post('/api/workspaces/save')
 def save_project(body:Save,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);rows=state.setdefault('workspace_projects',{});pid=body.project_id or uuid.uuid4().hex;old=rows.get(pid)
   if body.project_id and old is None:raise HTTPException(404,'Workspace not found.')
   if body.revision!=(old['revision'] if old else 0):raise HTTPException(409,'This workspace changed in another tab. Export your draft, then reload the saved project.')
   if old is None and len(rows)>=20:raise HTTPException(409,'Keep at most 20 saved projects. Export one before removing it.')
   from .planning_models import Planning
   try:planning=Planning.model_validate(body.planning if body.planning is not None else old.get('planning',{}) if old else {}).model_dump()
   except ValueError as exc:raise HTTPException(422,str(exc)) from exc
   if planning.get('client_id'):
    account=module.accounts.current(request,db)
    if not db.execute('SELECT 1 FROM customers WHERE id=? AND owner=?',(planning['client_id'],account['id'])).fetchone():raise HTTPException(404,'Owned customer record not found.')
   prior=(old.get('previous',[])+[{'revision':old['revision'],'workspace':old['workspace'],'planning':old.get('planning',Planning().model_dump())}])[-4:] if old else []
   r={'planning':planning,'previous':prior,'id':pid,'revision':body.revision+1,'workspace':body.workspace.model_dump(),'updated':int(time.time()),'analysis':analyze(body.workspace)};rows[pid]=r;state['version']+=1;module.save(db,sid,state);return public_record(r)
 @module.app.post('/api/workspaces/{pid}/delete')
 def delete_project(pid:str,body:Delete,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);rows=state.get('workspace_projects',{});old=rows.get(pid)
   if old is None:raise HTTPException(404,'Workspace not found.')
   if old['revision']!=body.revision:raise HTTPException(409,'Workspace changed. Reload before deleting.')
   del rows[pid];state['version']+=1;module.save(db,sid,state);return {'deleted':pid}
 @module.app.post('/api/workspaces/ask')
 def ask(body:Ask,request:Request):
  from . import workspace_agent,trained_agent
  from .accounts import throttle
  with module.database() as db:
   sid,_=module.owner(request,db,True)
   if not throttle(db,'workspace-agent:'+sid,20,60):raise HTTPException(429,'Please wait before another request.')
  try:return workspace_agent.propose(body.workspace,body.query)
  except trained_agent.ModelError as exc:raise HTTPException(503,str(exc)) from exc
