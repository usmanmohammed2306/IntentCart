"""Private revision-bound visual layouts and bounded local-model commands."""
import json,re,time
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from fastapi import Request,HTTPException
from . import trained_agent
PARTS=('laptop','monitor','dock','power','cable')
class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
class Part(Strict):
 position:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)
 rotation:float=Field(default=0.,ge=-6.283186,le=6.283186)
 scale:float=Field(default=1.,ge=.65,le=1.45)
 color:str|None=Field(default=None,pattern=r'^#[0-9a-fA-F]{6}$')
class Layout(Strict):
 model_config=ConfigDict(extra='forbid',strict=True,serialize_by_alias=True)
 version:Literal[1]=Field(default=1,alias='schema')
 finish:Literal['sand','moss','graphite']='graphite'
 light:Literal['aurora','studio','warm']='aurora'
 accent:str=Field(default='#72e6db',pattern=r'^#[0-9a-fA-F]{6}$')
 spread:bool=False
 parts:dict[str,Part]=Field(default_factory=lambda:{k:Part() for k in PARTS})
class Save(Strict):
 revision:int=Field(ge=0)
 layout:Layout
class Command(Strict):
 query:str=Field(min_length=1,max_length=1000)
 catalog_kind:Literal['curated','fixture']='curated'
def valid(body):
 if set(body.parts)!=set(PARTS):raise ValueError('Choose only the five workspace components.')
 for p in body.parts.values():
  if any(not lo<=v<=hi for v,lo,hi in zip(p.position,[-2,0,-1.5],[2,1.5,1.5])):raise ValueError('Component outside workspace.')
 return body.model_dump(mode='json')
def register(module):
 @module.app.get('/api/studio')
 def get(request:Request):
  with module.database() as db:
   _,state=module.owner(request,db)
   return {'layout':state.get('studio_layout',{'revision':0,'layout':Layout().model_dump(mode='json')}),'model':trained_agent.status()}
 @module.app.post('/api/studio/layout')
 def save(body:Save,request:Request):
  try:layout=valid(body.layout)
  except ValueError as exc:raise HTTPException(422,str(exc)) from exc
  with module.database() as db:
   sid,state=module.owner(request,db,True);current=state.get('studio_layout',{'revision':0})
   if current['revision']!=body.revision:raise HTTPException(409,'Your saved layout changed in another tab. Load it before saving again.')
   record={'revision':body.revision+1,'layout':layout};state['studio_layout']=record;state['version']+=1;module.save(db,sid,state);return record
 @module.app.post('/api/studio/request')
 def command(body:Command,request:Request):
  from .accounts import throttle
  with module.database() as db:
   sid,_=module.owner(request,db,True)
   if not throttle(db,'studio:'+sid,12,60):raise HTTPException(429,'Please wait a moment before another AI request.')
   db.commit()
  try:return trained_agent.request(body.query,body.catalog_kind)
  except trained_agent.ModelError as exc:raise HTTPException(503,str(exc)) from exc
