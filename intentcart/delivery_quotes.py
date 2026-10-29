"""Exact-basket, owned user-reviewed merchant charges. Not an automated tax certificate."""
import json,time,uuid,copy
from collections import Counter
from typing import Literal
from pydantic import Field
from .workspace import Strict
from . import device_research as specs

class StoreCharges(Strict):
 merchant:str=Field(min_length=1,max_length=200,pattern=r'^[a-z0-9.-]+$')
 currency:str=Field(pattern=r'^[A-Z]{3}$')
 shipping_minor:int=Field(ge=0,le=10000000)
 tax_minor:int=Field(ge=0,le=10000000)
 duty_minor:int=Field(ge=0,le=10000000)
 fees_minor:int=Field(default=0,ge=0,le=10000000)
 total_minor:int=Field(ge=0,le=100000000)
 reference:str=Field(min_length=3,max_length=200)
 reviewed:Literal[True]

def line_key(lines):
 counts=Counter((v['device_id'],v['device_digest'],v['variant'],v['unit_minor'],v['currency']) for v in lines)
 return specs.digest(sorted([list(k)+[v] for k,v in counts.items()]))

def reviewed_rate(body,lines,destination):
 if not lines or any(v['merchant']!=body.merchant or v['currency']!=body.currency for v in lines):raise ValueError('The charges must belong to this exact merchant, currency and basket.')
 expected=sum(v['unit_minor'] for v in lines)+body.shipping_minor+body.tax_minor+body.duty_minor+body.fees_minor
 if expected!=body.total_minor:raise ValueError('The quoted store total must equal the exact items plus delivery, additional tax, duty and other fees. Do not add included VAT twice.')
 if any(v['stock']!='in_stock' or time.time()>v['expires_at'] for v in lines):raise ValueError('Refresh current exact-product prices and stock before reviewing store charges.')
 return {'merchant':body.merchant,'currency':body.currency,'amount_minor':body.shipping_minor,'tax_minor':body.tax_minor,'duty_minor':body.duty_minor,'fees_minor':body.fees_minor,'basis':'User-reviewed merchant quote for these exact variants, quantities and destination; not independently fetched tax evidence.','service':'Reviewed store delivery','reference':body.reference,'quoted_total_minor':body.total_minor,'attested':True,'destination':destination.public(),'basket_key':line_key(lines),'observed_at':int(time.time()),'expires_at':min(v['expires_at'] for v in lines),'quantity_confirmed':False}
