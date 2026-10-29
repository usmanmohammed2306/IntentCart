"""Exact, owned merchant baskets. Free public estimates; no order/payment tools.
Street/city are transient and require named-merchant consent. Only server-observed
variants can become checkout links. Quotes and actual merchant orders are distinct.
"""
import copy,json,re,time,uuid,threading
from collections import defaultdict
from urllib.parse import urlsplit,urlencode
from typing import Literal
from pydantic import Field,field_validator
from fastapi import Request,HTTPException
from .planning_models import Design,Planning
from .workspace import Strict,Workspace
from .delivery import Destination
from . import device_research as specs,retail_sources as retail,merchant_totals,landed_budget,planning_engine,merchant_api
from .planning_routes import validated_permission,profiles
_active=threading.Lock()
INSTANCE=uuid.uuid4().hex
def present(run):
 value=copy.deepcopy(run)
 if value['status']=='working' and value.get('instance')!=INSTANCE:value.update(status='interrupted',error='The server restarted. No store request was automatically repeated.')
 return value

class Prepare(Design):
 destination:Destination|None=None
class Address(Strict):
 address1:str=Field(min_length=3,max_length=120)
 city:str=Field(min_length=1,max_length=80)
 @field_validator('address1','city')
 @classmethod
 def clean(cls,v):
  v=' '.join(v.strip().split())
  if not v or re.search(r'[\x00-\x1f<>]|https?://',v,re.I):raise ValueError('Use a delivery address, without links or markup.')
  return v
class Quote(Prepare):
 client_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 address:Address|None=None
 consented_merchants:list[str]=Field(default_factory=list,max_length=3)
class Apply(Prepare):pass

def destination_for(body):
 if not body.destination:raise ValueError('Choose your delivery country and postal code.')
 if body.planning.region!=body.destination.key():raise ValueError('The delivery location changed. Set the current location before checking this cart.')
 return body.destination

def key(body):return specs.digest({'workspace':body.workspace.model_dump(),'planning':body.planning.model_dump(),'destination':body.destination.model_dump() if body.destination else None})

def raw_offer(state,o,item,p,allow_expired=False):
 record=state.get('delivered_quotes',{}).get(o.quote_id)
 if not record or record['basket_hash']!=landed_budget.scope(item[0],p) or record['offers'].get(o.id)!=specs.digest(o.model_dump()):return None
 if not allow_expired and record['expires_at']<time.time():return None
 binding=next((b for b in p.devices if b.item_id==item[1].id),None)
 if not binding or not binding.reviewed:return None
 sources=[c.get('landed',{}) for j in state.get('sentence_setups',{}).values() for c in j.get('candidates',[])]
 sources.extend(state.get('checkout_observations',{}).values())
 for source in sources:
  if source.get('id')!=o.quote_id:continue
  for line in source.get('lines',[]):
   v=line.get('offer')
   if line.get('item_id')==item[1].id and v and v['device_id']==binding.device_id and v['device_digest']==binding.source_digest and v['unit_minor']==o.amount_minor and v['currency']==o.currency and v['url']==o.url:return copy.deepcopy(v)
 return None

def refresh_metadata(state,item,p):
 binding=next((v for v in p.devices if v.item_id==item.id and v.reviewed),None)
 if not binding:return None
 sources=[c.get('landed',{}) for j in state.get('sentence_setups',{}).values() for c in j.get('candidates',[])]+list(state.get('checkout_observations',{}).values())
 values=[copy.deepcopy(line['offer']) for source in sources for line in source.get('lines',[]) if line.get('offer') and line['offer']['device_id']==binding.device_id and line['offer']['device_digest']==binding.source_digest]
 # History is only a discovery pointer, never a current-price certificate.
 identities={(v['merchant'],v.get('shopify_variant_id'),v.get('variant'),v['currency']) for v in values}
 if len(identities)!=1:return None
 return max(values,key=lambda v:v['observed_at']) if values else None

def selected(body,state,allow_expired=False):
 w,p=body.workspace,body.planning;destination=destination_for(body);groups={};missing=[];resolved=planning_engine.resolve(w,p,profiles(state))
 for item in w.items:
  if item.owned:continue
  offer=next((o for o in p.offers if o.item_id==item.id),None)
  v=raw_offer(state,offer,(w,item),p,allow_expired) if offer and offer.quote_id else None
  current=bool(v and offer.expires_at>=time.time() and v['expires_at']>=time.time())
  if v is None and allow_expired:
   v=refresh_metadata(state,item,p)
   if v is None and resolved['identities'].get(item.id):v=merchant_api.discovery_offer(resolved['identities'][item.id],w.currency)
  if not v or not resolved['identities'].get(item.id):missing.append({'item_id':item.id,'name':item.name,'reason':'Find a current exact-model offer for this item.'});continue
  host=v.get('merchant');parts=urlsplit(v.get('url',''))
  if not host or parts.hostname!=host or not retail.allowed(v['url']) or v['currency']!=w.currency:raise ValueError('The merchant identity or currency does not match this cart.')
  group=groups.setdefault(host,{'merchant':host,'lines':[],'raw':[],'currency':w.currency})
  group['lines'].append({'item_id':item.id,'name':item.name,'variant_id':v.get('shopify_variant_id'),'quantity':1,'unit_minor':v['unit_minor'],'stock':v['stock'],'expires_at':v['expires_at'],'quote_current':current,'discovery_only':v.get('discovery_only',False)});group['raw'].append(v)
 if len(groups)>3:raise ValueError('Review up to three stores in one delivery check.')
 return list(groups.values()),missing,destination

def exact_lines(group):
 out={}
 for v in group['lines']:
  ident=v['variant_id']
  if type(ident) is not int or ident<=0:raise ValueError('This store needs its own product-page checkout; no exact cart variant was exposed.')
  row=out.setdefault(ident,{'variant_id':ident,'quantity':0,'unit_minor':v['unit_minor']})
  if row['unit_minor']!=v['unit_minor']:raise ValueError('This variant has conflicting observed prices.')
  row['quantity']+=1
 if len(out)>12 or any(v['quantity']>4 for v in out.values()):raise ValueError('Use up to twelve variants and four units per variant at one store.')
 return sorted(out.values(),key=lambda v:v['variant_id'])

def link(group,destination,profile=None):
 lines=exact_lines(group);origin='https://'+group['merchant'];path='/cart';params={'checkout[shipping_address][country]':destination.country};protocol='Shopify cart permalink'
 if profile:
  caps=profile.get('ucp',{}).get('capabilities',{}).get('dev.ucp.shopping.permalink',[])
  for c in caps[:4] if isinstance(caps,list) else []:
   if not isinstance(c,dict):continue
   endpoint=c.get('config',{}).get('endpoint','');u=urlsplit(endpoint)
   if u.scheme!='https' or u.netloc!=group['merchant'] or u.query or u.fragment or u.username or not re.fullmatch(r'/[A-Za-z0-9_/-]{1,100}',u.path):continue
   path=u.path.rstrip('/');params={'context/address_country':destination.country};version=c.get('version')
   if isinstance(version,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',version):params['ucp/version']=version
   protocol='UCP cart permalink';break
 url=origin+path+'/'+','.join(str(v['variant_id'])+':'+str(v['quantity']) for v in lines)+'?'+urlencode(params)
 if len(url.encode())>2048:raise ValueError('The exact store cart link is too long.')
 return url,protocol

def prepare(body,state):
 groups,missing,destination=selected(body,state,True);now=int(time.time());result=[]
 for group in groups:
  expired=any(not v['quote_current'] or v['expires_at']<now or v['stock']!='in_stock' for v in group['lines']);url=protocol=None;reason='Refresh current prices and stock.' if expired else ''
  try:
   if not expired and all(v.get('shopify') for v in group['raw']):
    url,protocol=link(group,destination)
    for o in body.planning.offers:
     if o.item_id not in {v['item_id'] for v in group['lines']}:continue
     cached=state.get('checkout_observations',{}).get(o.quote_id,{}).get('checkout_links',{}).get(group['merchant'])
     if cached:
      u=urlsplit(cached);suffix='/'+','.join(str(v['variant_id'])+':'+str(v['quantity']) for v in exact_lines(group))
      if u.scheme=='https' and u.netloc==group['merchant'] and not u.fragment and u.path.endswith(suffix) and len(cached.encode())<=2048:url=cached;protocol='Merchant cart permalink'
   elif not expired:reason='This store does not expose a supported exact-cart link.'
  except ValueError as exc:reason=str(exc)
  result.append({k:group[k] for k in ['merchant','lines','currency']}|{'subtotal_minor':None if any(v.get('discovery_only') for v in group['lines']) else sum(v['unit_minor'] for v in group['lines']),'checkout_url':url,'protocol':protocol,'reason':reason,'expires_at':min(v['expires_at'] for v in group['lines']),'retry_at':state.get('checkout_cooldowns',{}).get(group['merchant'],0),'can_quote':all(v.get('shopify') and type(v.get('shopify_variant_id')) is int and v['shopify_variant_id']>0 for v in group['raw'])})
 cost=planning_engine.costs(body.workspace,landed_budget.verified_offers(body.workspace,body.planning,state))
 purchases={i.id for i in body.workspace.items if not i.owned};qids={o.quote_id for o in body.planning.offers if o.item_id in purchases};saved=None;partial=None
 if not missing and result and len(qids)==1 and None not in qids and all(v['quote_current'] for g in groups for v in g['lines']):
  observation=state.get('checkout_observations',{}).get(next(iter(qids)),{})
  if observation.get('expires_at',0)>now:
   fields=('total_minor','subtotal_minor','discount_minor','shipping_minor','tax_minor','duty_minor','fees_minor','remaining_minor','expires_at','observed_at')
   partial={k:observation.get(k) for k in fields}
   partial['shipments']=[{k:r.get(k) for k in ('merchant','total_minor','amount_minor','tax_minor','reason','merchant_total_complete')} for r in observation.get('shipments',[])]
  if observation.get('expires_at',0)>now and observation.get('total_minor') is not None and observation.get('total_minor')==cost['total_minor']:
   fields=('total_minor','subtotal_minor','discount_minor','shipping_minor','tax_minor','duty_minor','fees_minor','remaining_minor','expires_at','observed_at')
   saved={k:observation.get(k) for k in fields}
   saved['shipments']=copy.deepcopy(partial['shipments'])
   saved['remaining_minor']=body.workspace.budget_cents-cost['total_minor'] if body.workspace.budget_cents is not None else None
 return {'basket_key':key(body),'merchants':result,'missing':missing,'cost':cost,'saved_estimate':saved,'partial_estimate':partial,'destination':destination.public(),'scope':'Exact observed variants grouped by store; opening a new store cart is not a completed order. The store confirms final charges and may change stock or price.'}

def fetch_quote(body,state,event,cooldown=lambda *a:None):
 groups,missing,destination=selected(body,state,True)
 if missing or not groups:raise ValueError('Find current exact-model offers for every purchase item first.')
 names=sorted(g['merchant'] for g in groups if all(v.get('shopify') and type(v.get('shopify_variant_id')) is int and v['shopify_variant_id']>0 for v in g['raw']))
 if body.address and sorted(body.consented_merchants)!=names:raise ValueError('Approve sending the street and city only to the displayed stores.')
 if sum(len({v['id'] for v in g['raw']}) for g in groups)>12:raise ValueError('Review up to twelve exact products per delivery check.')
 observations=defaultdict(list);rates={};errors=[];permalinks={}
 resolved=planning_engine.resolve(body.workspace,body.planning,profiles(state));by_id={d['id']:d for d in resolved['identities'].values() if d}
 for group in groups:
  host=group['merchant']
  if state.get('checkout_cooldowns',{}).get(host,0)>time.time():
   rates[host]={'amount_minor':None,'reason':'The store is temporarily rate-limited. Try again later.'};errors.append({'merchant':host,'reason':rates[host]['reason'],'retry_at':state['checkout_cooldowns'][host]});continue
  fresh=[];originals={v['id']:v for v in group['raw']};fresh_by_id={}
  if len({v['device_id'] for v in originals.values()})!=len(originals):raise ValueError('Check one exact variant per model; review different editions separately.')
  for old in originals.values():
   try:
    profile=by_id[old['device_id']]
    if merchant_api.supported(host):values=[merchant_api.refresh(host,old,profile,body.workspace.currency,event,country=destination.country)]
    else:
     doc=retail.read(old['source_url'],lambda url:event('read',host));values=retail.parse(doc,profile)
    value=next((v for v in values if v['merchant']==host and v['currency']==body.workspace.currency and v.get('shopify_variant_id')==old.get('shopify_variant_id') and v.get('variant')==old.get('variant')),None)
    if not value or value['stock']!='in_stock':raise ValueError('The exact variant is no longer available at this store.')
    observations[value['device_id']].append(value);fresh.append(value);fresh_by_id[old['id']]=value
   except ValueError as exc:
    if 'HTTP429' in str(exc):
     if isinstance(exc,retail.RateLimited):cooldown(host,exc.retry_at)
     else:cooldown(host)
    errors.append({'merchant':host,'reason':str(exc),'retry_at':getattr(exc,'retry_at',None)});break
  prior_raw=group['raw'];group['raw']=fresh
  if len(fresh)!=len(originals):rates[host]={'amount_minor':None,'reason':'Current items could not be refreshed.'};continue
  for line,old in zip(group['lines'],prior_raw):
   v=fresh_by_id[old['id']];line.update(variant_id=v.get('shopify_variant_id'),unit_minor=v['unit_minor'],stock=v['stock'],expires_at=v['expires_at'])
  try:
   if not all(v.get('shopify') for v in fresh):raise ValueError('This store does not expose the supported cart-total API.')
   if merchant_api.supported(host):
    store_profile={'ucp':{'capabilities':{'dev.ucp.shopping.permalink':[{'version':merchant_api.VERSION,'config':{'endpoint':'https://'+host+merchant_api.STORES[host]['permalink']}}]}}}
    permalinks[host]=link(group,destination,store_profile)[0]
    rates[host]=merchant_api.quote(host,exact_lines(group),destination,body.workspace.currency,event,address=body.address.model_dump() if body.address else None)
   else:
    # Optional capability discovery never supplies an arbitrary request endpoint.
    try:
     profile_doc=retail.read('https://'+host+'/.well-known/ucp',lambda url:event('capability',host));profile=json.loads(profile_doc['html']);permalinks[host]=link(group,destination,profile)[0]
    except ValueError as exc:
     if any(code in str(exc) for code in ('HTTP429','HTTP403')):raise
     permalinks[host]=link(group,destination)[0]
    rates[host]=merchant_totals.quote('https://'+host,exact_lines(group),destination,body.workspace.currency,lambda *a,**k:event(k.get('operation','quote'),host),address=body.address.model_dump() if body.address else None)
  except retail.QuoteCleanupError:raise
  except ValueError as exc:
   if 'HTTP429' in str(exc):
    if isinstance(exc,retail.RateLimited):cooldown(host,exc.retry_at)
    else:cooldown(host)
   rates[host]=landed_budget.published_shipping(fresh,sum(v['unit_minor'] for v in group['lines']),destination) or {'amount_minor':None,'reason':str(exc)};errors.append({'merchant':host,'reason':str(exc),'retry_at':getattr(exc,'retry_at',None)})
 candidate={'id':uuid.uuid4().hex,'workspace':body.workspace.model_dump(),'planning':body.planning.model_dump()}
 value,record=landed_budget.price_candidate(candidate,observations,destination,{'status':'merchant','amount_minor':None},fixed_rates=rates)
 value['checkout_links']=permalinks;value['errors']=errors
 return value,record

def register(module):
 from . import accounts
 # Built-in manufacturer snapshots and ISO identifiers contain no account data.
 accounts.PUBLIC_APIS.update({'/api/equipment/catalog','/api/setup/delivery'})
 @module.app.get('/.well-known/ucp')
 def agent_profile():return merchant_api.profile_document()
 @module.app.post('/api/setup/checkout/prepare')
 def preview(body:Prepare,request:Request):
  try:
   with module.database() as db:
    _,state=module.owner(request,db,True);return prepare(body,state)
  except ValueError as exc:raise HTTPException(422,str(exc)) from exc
 @module.app.post('/api/setup/checkout/quote')
 def quote(body:Quote,request:Request):
  try:
   with module.database() as db:
    sid,state=module.owner(request,db,True);base=key(body);identity=specs.digest({'base':base,'address':body.address.model_dump() if body.address else None,'consent':body.consented_merchants});rows=state.setdefault('checkout_runs',{});old=rows.get(body.client_id)
    if old:
     if old['input_hash']!=identity:raise HTTPException(409,'That check belongs to a different cart or address.')
     if old['status']=='working':raise HTTPException(409,'This check is already running; it was not repeated.')
     return present(old)
    from .accounts import throttle
    if not throttle(db,'merchant-checkout:'+sid,3,300):raise HTTPException(429,'Three delivery checks per five minutes. Keep reviewing your saved cart meanwhile.')
    if not _active.acquire(blocking=False):raise HTTPException(429,'Another delivery check is finishing.')
    rows[body.client_id]={'id':body.client_id,'input_hash':identity,'source_key':base,'status':'working','instance':INSTANCE,'public_requests':0,'events':[],'result':None,'error':None}
    while len(rows)>8:del rows[next(iter(rows))]
    try:module.save(db,sid,state)
    except BaseException:_active.release();raise
   owner_sid=sid;started=time.monotonic()
   def update(fn):
    with module.database() as db:
     row=db.execute('SELECT state FROM sessions WHERE id=?',(owner_sid,)).fetchone()
     if not row:raise ValueError('The owning session expired.')
     s=json.loads(row['state']);run=s['checkout_runs'][body.client_id];fn(s,run);module.save(db,owner_sid,s)
   def event(operation,host):
    if time.monotonic()-started>45:raise ValueError('This delivery check reached its time window. No new store request was started.')
    def record(s,run):
     if run['public_requests']>=24:raise ValueError('The fixed twenty-four-request check bound was reached.')
     run['public_requests']+=1;run['events'].append({'operation':operation,'merchant':host,'at':int(time.time())})
    update(record)
   try:
    value,record=fetch_quote(body,state,event,lambda host,retry_at=None:update(lambda s,run:s.setdefault('checkout_cooldowns',{}).update({host:int(retry_at or time.time()+300)})))
    def complete(s,run):
     run.update(status='complete',result=value);s.setdefault('delivered_quotes',{})[record['id']]=record;s.setdefault('checkout_observations',{})[record['id']]=copy.deepcopy(value['landed'])|{'checkout_links':value['checkout_links']}
     while len(s['checkout_observations'])>8:del s['checkout_observations'][next(iter(s['checkout_observations']))]
    update(complete)
   except Exception as exc:
    update(lambda s,run:run.update(status='failed',error='Temporary merchant cart or checkout cleanup could not be confirmed; no further estimate was attempted.' if isinstance(exc,retail.QuoteCleanupError) else str(exc) if isinstance(exc,ValueError) else 'The delivery check stopped. No order was placed.'))
   finally:_active.release()
   with module.database() as db:
    _,s=module.owner(request,db);return present(s['checkout_runs'][body.client_id])
  except ValueError as exc:raise HTTPException(422,str(exc)) from exc
 @module.app.get('/api/setup/checkout/{run_id}')
 def read(run_id:str,request:Request):
  with module.database() as db:
   _,state=module.owner(request,db);run=state.get('checkout_runs',{}).get(run_id)
   if not run:raise HTTPException(404,'This delivery check is not in your account.')
   return present(run)
 @module.app.post('/api/setup/checkout/{run_id}/apply')
 def apply(run_id:str,body:Apply,request:Request):
  with module.database() as db:
   sid,state=module.owner(request,db,True);run=state.get('checkout_runs',{}).get(run_id)
   if not run or run['status']!='complete' or run['source_key']!=key(body):raise HTTPException(409,'The cart changed. Check delivery for this version.')
   result=run['result'];landed=result['landed']
   if landed['expires_at']<time.time():raise HTTPException(409,'These prices expired. Check delivery again.')
   if landed['subtotal_minor'] is None:raise HTTPException(409,'Some item prices could not be verified. Your current cart is retained.')
   p=validated_permission(body.workspace,Planning.model_validate(result['planning']),state)
   return {'workspace':body.workspace.model_dump(),'planning':p.model_dump(),'landed':landed,'notice':'Current store estimates applied. Review the exact store cart before paying.'}
