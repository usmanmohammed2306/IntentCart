"""Portable planning context. Declarations and observed manufacturer facts stay distinct."""
from __future__ import annotations
from datetime import date
from typing import Literal
from pydantic import Field,model_validator
from .workspace import Strict,Workspace,Pose
NUMERIC={'width_mm','depth_mm','height_mm','weight_g','native_displays','max_height','max_hz','displays','pd_watts','voltage_min','voltage_max','camera_height','noise_db','hdmi_outputs','dp_outputs','usb_c_video_outputs','switch_hosts'}
BOOLEAN={'video_out_hdmi','video_out_dp','video_out_usb_c','video_in_hdmi','video_in_dp','bluetooth','usb_a','usb_c','driver_required','requires_software','isolation_verified'}
TEXTUAL={'mount','handedness','noise_claim','link_type','os','switch_mode','identity','custom'}
def fact_valid(key,value):
 import math
 if key in NUMERIC:
  if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or not 0<=value<=100000:raise ValueError('Numeric fact required for '+key)
 elif key in BOOLEAN:
  if not isinstance(value,bool):raise ValueError('Boolean fact required for '+key)
 elif key in TEXTUAL:
  if not isinstance(value,str) or not 1<=len(value)<=300:raise ValueError('Short text fact required for '+key)
 else:raise ValueError('Unsupported fact field '+key)
 return value
class Point(Strict):
 x:float=Field(ge=-20000,le=20000)
 z:float=Field(ge=-20000,le=20000)
class Region(Strict):
 id:str=Field(pattern=r'^[\w-]{1,64}$')
 name:str=Field(min_length=1,max_length=80)
 points:list[Point]=Field(min_length=3,max_length=24)
class DeviceSelection(Strict):
 item_id:str=Field(max_length=64)
 device_id:str=Field(max_length=100)
 configuration:str=Field(max_length=100)
 source_digest:str=Field(pattern=r'^[a-f0-9]{64}$')
 reviewed:bool=False
class Observation(Strict):
 state_id:str=Field(default='',max_length=64)
 item_id:str=Field(max_length=64)
 field:str=Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')
 value:str|int|float|bool|None
 unit:str=Field(default='',max_length=20)
 note:str=Field(min_length=1,max_length=500)
 observed_on:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
 authority:Literal['user_observation','reviewed_document']='user_observation'
 @model_validator(mode='after')
 def bounded(self):
  date.fromisoformat(self.observed_on);fact_valid(self.field,self.value)
  if isinstance(self.value,str) and len(self.value)>300:raise ValueError('Observation text too long.')
  return self
class Goal(Strict):
 id:str=Field(pattern=r'^[\w-]{1,64}$')
 kind:Literal['count','no_purchase','surface_fit','connections','no_drill','no_clamp','max_weight','bag_fit','reach','clearance','display_mode','native_displays','budget','identity','noise','handedness','availability','returnability','power_region','custom']
 text:str=Field(min_length=1,max_length=1200)
 state_id:str=Field(default='',max_length=64)
 item_id:str=Field(default='',max_length=64)
 category:str=Field(default='',max_length=20)
 value:int|float|str|bool|None=None
 value2:float|None=None
 required:bool=True
 @model_validator(mode='after')
 def bounded(self):
  if isinstance(self.value,str) and len(self.value)>200:raise ValueError('Goal value too long.')
  if self.kind in ('count','max_weight','reach','clearance','display_mode','native_displays','budget') and (not isinstance(self.value,(int,float)) or isinstance(self.value,bool) or self.value<0):raise ValueError('This goal needs a nonnegative numeric value.')
  if self.kind=='count' and (int(self.value)!=self.value or self.value>48 or self.category not in ('laptop','desktop','monitor','keyboard','mouse','dock','cable','power','webcam','audio','storage','other')):raise ValueError('Invalid item count goal.')
  return self
class Offer(Strict):
 id:str=Field(pattern=r'^[\w-]{1,64}$')
 item_id:str=Field(default='',max_length=64)
 device_id:str=Field(default='',max_length=100)
 currency:str=Field(pattern=r'^[A-Z]{3}$')
 amount_minor:int=Field(ge=0,le=100000000)
 shipping_minor:int|None=Field(default=None,ge=0,le=10000000)
 tax_minor:int|None=Field(default=None,ge=0,le=10000000)
 duty_minor:int|None=Field(default=None,ge=0,le=10000000)
 stock:Literal['unknown','in_stock','out_of_stock']='unknown'
 region:str=Field(default='',max_length=60)
 url:str=Field(default='',max_length=800)
 observed_on:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
 valid_until:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
 return_days:int|None=Field(default=None,ge=0,le=365)
 return_note:str=Field(default='',max_length=500)
 @model_validator(mode='after')
 def dates(self):
  if date.fromisoformat(self.valid_until)<date.fromisoformat(self.observed_on):raise ValueError('Offer expiry precedes observation.')
  if self.url and not self.url.startswith('https://'):raise ValueError('Offer links must use HTTPS.')
  return self
class FX(Strict):
 currency:str=Field(pattern=r'^[A-Z]{3}$')
 rate:float=Field(gt=0,le=1000000)
 source:str=Field(min_length=1,max_length=500)
 observed_on:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
 valid_until:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
 @model_validator(mode='after')
 def dates(self):
  if date.fromisoformat(self.valid_until)<date.fromisoformat(self.observed_on):raise ValueError('FX expiry precedes observation.')
  return self
class SavedState(Strict):
 outline:list[Point]|None=Field(default=None,max_length=24)
 obstacles:list[Region]|None=Field(default=None,max_length=16)
 seating:Point|None=None
 bag_mm:list[float]|None=Field(default=None,min_length=3,max_length=3)
 workspace:Workspace|None=None
 devices:list[DeviceSelection]|None=Field(default=None,max_length=48)
 id:str=Field(pattern=r'^[\w-]{1,64}$')
 name:str=Field(min_length=1,max_length=80)
 owner_label:str=Field(default='',max_length=80)
 poses:dict[str,Pose]=Field(default_factory=dict,max_length=48)
 hidden:list[str]=Field(default_factory=list,max_length=48)
 configurations:dict[str,str]=Field(default_factory=dict,max_length=48)
 surface_width:float|None=Field(default=None,gt=0,le=10000)
 surface_depth:float|None=Field(default=None,gt=0,le=10000)
 clearance_mm:float|None=Field(default=None,ge=0,le=3000)
class Group(Strict):
 name:str=Field(min_length=1,max_length=80)
 quantity:int=Field(ge=1,le=10000)
 state_id:str=Field(default='',max_length=64)
 responsible:str=Field(min_length=1,max_length=100)
class Profile(Strict):
 id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
 name:str=Field(min_length=1,max_length=160)
 kind:Literal['laptop','desktop','monitor','keyboard','mouse','dock','cable','power','webcam','audio','storage','other']
 aliases:list[str]=Field(default_factory=list,max_length=12)
 reviewed_on:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
 sources:list[dict]=Field(min_length=1,max_length=6)
 configurations:dict[str,dict]=Field(min_length=1,max_length=8)
 field_evidence:dict[str,str]=Field(default_factory=dict,max_length=24)
 authority:str=Field(default='Imported user-reviewed snapshot, not independently certified',max_length=200)
 note:str=Field(default='',max_length=1000)
 digest:str=Field(default='',max_length=64)
 @model_validator(mode='after')
 def bounded(self):
  import math
  self.authority='User-reviewed/imported source snapshot, not independently certified'
  date.fromisoformat(self.reviewed_on)
  for source in self.sources:
   if any(k not in ('url','document_sha256','reviewed_on','retrieved_on','basis') or not isinstance(v,str) or len(v)>1500 for k,v in source.items()):raise ValueError('Invalid source metadata.')
  if any(len(x)>160 for x in self.aliases):raise ValueError('Alias too long.')
  for state,fields in self.configurations.items():
   if len(state)>100 or len(fields)>32:raise ValueError('Profile too large.')
   for k,v in fields.items():
    fact_valid(k,v)
    if not __import__('re').fullmatch('[a-z][a-z0-9_]{0,39}',k) or not isinstance(v,(str,int,float,bool,type(None))):raise ValueError('Invalid fact field.')
    if isinstance(v,str) and len(v)>300 or isinstance(v,float) and not math.isfinite(v):raise ValueError('Fact value invalid.')
  return self
class Planning(Strict):
 schema_version:Literal[1]=1
 active_state:str=Field(default='',max_length=64)
 profiles:list[Profile]=Field(default_factory=list,max_length=40)
 devices:list[DeviceSelection]=Field(default_factory=list,max_length=48)
 observations:list[Observation]=Field(default_factory=list,max_length=192)
 goals:list[Goal]=Field(default_factory=list,max_length=60)
 outline:list[Point]=Field(default_factory=list,max_length=24)
 obstacles:list[Region]=Field(default_factory=list,max_length=16)
 states:list[SavedState]=Field(default_factory=list,max_length=8)
 offers:list[Offer]=Field(default_factory=list,max_length=96)
 exchange_rates:list[FX]=Field(default_factory=list,max_length=12)
 seating:Point|None=None
 bag_mm:list[float]|None=Field(default=None,min_length=3,max_length=3)
 inventory:dict[str,int]=Field(default_factory=dict,max_length=100)
 procurement_budget_minor:int|None=Field(default=None,ge=0,le=10000000000)
 groups:list[Group]=Field(default_factory=list,max_length=20)
 allow_driver:bool|None=None
 driver_permission_token:str|None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
 region:str=Field(default='',max_length=60)
 client_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
 notes:str=Field(default='',max_length=2000)
 @model_validator(mode='after')
 def unique(self):
  for rows in (self.devices,self.goals,self.obstacles,self.states,self.offers,self.profiles):
   ids=[getattr(r,'id',None) or r.item_id for r in rows]
   if len(ids)!=len(set(ids)):raise ValueError('Duplicate planning IDs.')
  if any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=100000 or not 1<=len(k)<=100 for k,v in self.inventory.items()):raise ValueError('Invalid inventory counts.')
  if self.bag_mm and any(not 0<x<=10000 for x in self.bag_mm):raise ValueError('Invalid bag size.')
  if self.outline and len(self.outline)<3:raise ValueError('Use three or more outline points.')
  return self
class Design(Strict):
 workspace:Workspace
 planning:Planning=Field(default_factory=Planning)
class Start(Design):
 query:str=Field(default='',max_length=1200)
 research_urls:list[str]=Field(default_factory=list,max_length=2)
 source_consent:bool=False
 max_steps:int=Field(default=12,ge=1,le=24)
 project_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
 project_revision:int=Field(default=0,ge=0)
 @model_validator(mode='after')
 def sources(self):
  from urllib.parse import urlsplit
  if self.research_urls and not self.source_consent:raise ValueError('Explicit source-reading consent is required.')
  if any(len(u)>1500 or urlsplit(u).scheme!='https' for u in self.research_urls):raise ValueError('Use bounded official HTTPS source URLs.')
  return self
class Advance(Strict):
 run_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 revision:int=Field(ge=0)
 steps:int=Field(default=1,ge=1,le=4)
class Query(Strict):
 query:str=Field(min_length=2,max_length=160)
 kind:str=Field(default='',max_length=20)
class SourceRequest(Strict):
 url:str=Field(min_length=10,max_length=1500)
 consent:Literal[True]
 identity:str=Field(min_length=2,max_length=160)
class SourceReview(Strict):
 source_id:str=Field(pattern=r'^[a-f0-9]{64}$')
 device_id:str=Field(min_length=1,max_length=100)
 name:str=Field(min_length=1,max_length=160)
 kind:Literal['laptop','desktop','monitor','keyboard','mouse','dock','cable','power','webcam','audio','storage','other']
 configuration:str=Field(min_length=1,max_length=100)
 fields:dict[str,str|float|int|bool]=Field(max_length=24)
 evidence:dict[str,str]=Field(max_length=24)
class ImportCatalog(Strict):
 records:list[dict]=Field(max_length=500)
 query:str=Field(default='',max_length=160)
 max_records:int=Field(default=40,ge=1,le=100)
class Merge(Strict):
 project_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 base_revision:int=Field(ge=1)
 workspace:Workspace
 planning:Planning=Field(default_factory=Planning)
