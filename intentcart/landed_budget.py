"""Observed item + merchant-cart shipping + source-backed destination tax.
No price is invented. These are time-bound estimates, not order/payment quotes.
"""
from __future__ import annotations
import copy,itertools,json,re,time,uuid
from datetime import datetime,timezone
from pydantic import Field,model_validator
from fastapi import Request
from .workspace import Strict,Workspace
from .planning_models import Planning,Offer
from . import retail_sources as retail,device_research as specs

TAX_URL='https://www.oregon.gov/dor/programs/businesses/Pages/Sales-tax.aspx'
from .delivery import Destination,catalog as delivery_catalog
from .delivery_quotes import line_key
from . import merchant_totals

def same_destination(observed,destination):
 return bool(destination and isinstance(observed,dict) and all(observed.get(k,'')==getattr(destination,k) for k in ('country','region','postal')))

def scope(w,p):
 bindings={b.item_id:b for b in p.devices}
 return specs.digest({'currency':w.currency,'region':p.region,'shipping_cents':w.shipping_cents,'tax_cents':w.tax_cents,'purchases':[{'item_id':i.id,'kind':i.kind,'model':i.model,'price_cents':i.price_cents,'binding':bindings[i.id].model_dump() if i.id in bindings else None} for i in sorted(w.items,key=lambda i:i.id) if not i.owned]})
def verified_offers(w,p,state):
 out=p.model_copy(deep=True);now=int(time.time())
 for o in out.offers:
  if not o.quote_id:continue
  record=state.get('delivered_quotes',{}).get(o.quote_id)
  valid=bool(record and record['expires_at']>=now and record['basket_hash']==scope(w,p) and record['offers'].get(o.id)==specs.digest(o.model_dump()))
  if not valid:o.observed_at=0;o.expires_at=1;o.stock='unknown'
 return out

def tax_rule(destination,read=retail.read,on_event=lambda *a,**k:None):
 # Deliberately narrow jurisdiction rule: this user-authorized demonstration
 # destination is not a ZIP->tax database for other addresses or countries.
 if not destination or (destination.country,destination.region)!=('US','OR'):return {'status':'unknown','amount_minor':None,'reason':'This destination needs a merchant tax quote; no ZIP-wide tax rate was guessed.'}
 try:
  doc=read(TAX_URL,lambda url:on_event('offer_read',url=url))
  m=re.search(r"Oregon\s+(?:doesn.t|does not)\s+have\s+a\s+general\s+sales\s+(?:or\s+use/transaction\s+)?tax",doc['text'],re.I)
  if not m:return {'status':'unknown','amount_minor':None,'reason':'The official tax-source statement could not be verified.'}
  return {'status':'source_policy','rate_basis_points':0,'amount_minor':0,'source_url':doc['url'],'source_sha256':doc['sha256'],'quote':m[0],'observed_at':doc['observed_at'],'scope':'General sales tax on ordinary computer equipment delivered to the declared declared Oregon destination. Not a general tax calculator or a final checkout tax quote.'}
 except ValueError as exc:return {'status':'unknown','amount_minor':None,'reason':str(exc)}

def observe(profile,on_event=lambda *a,**k:None,destination=None,currency="USD"):
 errors=[];offers=[]
 from . import merchant_api
 pointer=merchant_api.discovery_offer(profile,currency)
 if pointer:
  try:return {'offers':[merchant_api.refresh(pointer['merchant'],pointer,profile,currency,lambda operation,host:on_event('offer_'+operation,merchant=host),country=destination.country if destination else 'US')],'errors':[]}
  except ValueError as exc:return {'offers':[],'errors':[profile['name']+': '+str(exc)]}
 direct=[{'url':s['url'],'title':profile['name']} for s in profile['sources'] if retail.allowed(s.get('url','')) and ('/products/' in s['url'] or '/en-us/shop/' in s['url']) and not s['url'].lower().endswith('.pdf')][:1]
 if destination and destination.country!='US':direct=[]
 found={'results':direct,'errors':[]} if direct else retail.discover(profile,on_event,destination.merchant_address()['country_name'] if destination else None,currency)
 errors.extend(found['errors'])
 for row in found['results'][:2]:
  try:
   doc=retail.read(row['url'],lambda url:on_event('offer_read',url=url));rows=retail.parse(doc,profile);offers.extend(rows)
   if not rows:errors.append(profile['name']+': no exact new-condition, single-variant USD offer was established; aggregate/member/other-edition prices were not accepted.')
  except ValueError as exc:errors.append(profile['name']+': '+str(exc))
 unique={v['id']:v for v in offers};return {'offers':list(unique.values())[:4],'errors':errors}

def published_shipping(selected,subtotal,destination):
 for v in selected if len(selected)==1 else []:
  details=v.get('shipping_details') or [];details=[details] if isinstance(details,dict) else details
  for s in details:
   if not isinstance(s,dict) or s.get('validForMemberTier'):continue
   dest=s.get('shippingDestination',{});rate=s.get('shippingRate',{})
   if not isinstance(dest,dict) or not isinstance(rate,dict) or dest.get('addressCountry')!=destination.country:continue
   if dest.get('addressRegion') and destination.region not in ([dest['addressRegion']] if isinstance(dest['addressRegion'],str) else dest['addressRegion']):continue
   if dest.get('postalCode') and destination.postal not in ([dest['postalCode']] if isinstance(dest['postalCode'],str) else dest['postalCode']):continue
   # Requirements/unknown fees/rate structures are not flattened to zero.
   if any(k in s for k in ('doesNotShip','shippingConditions','shippingLabel')) or rate.get('currency')!=selected[0]['currency'] or rate.get('value') is None:continue
   try:amount=retail.money(rate['value'])
   except ValueError:continue
   return {'amount_minor':amount,'service':'Published destination shipping rate','source_url':v['source_url'],'source_sha256':v['source_sha256'],'basis':'Merchant product shippingDetails','destination':destination.public()}
 policies=[v.get('shipping_policy') for v in selected]
 if policies and all(policies) and all(p.get('country','US')==destination.country for p in policies) and not (destination.country=='US' and destination.region in ('AK','HI','PR','GU','VI','AS','MP')):
  qualified=all(subtotal>=p['threshold_minor'] if p['inclusive'] else subtotal>p['threshold_minor'] for p in policies)
  if qualified:return {'amount_minor':0,'service':'Published free standard delivery','basis':'Merchant-group subtotal satisfies every observed line policy; not a checkout guarantee',**policies[0],'destination':destination.public()}
 return None

def merchant_rate(selected,quantities,destination,on_event,memo):
 merchant=selected[0]['merchant'];lines=[]
 for v,qty in zip(selected,quantities):lines.append({'variant_id':v.get('shopify_variant_id'),'quantity':qty,'unit_minor':v['unit_minor']})
 key=specs.digest({'merchant':merchant,'lines':lines,'destination':destination.public()})
 if key in memo:return memo[key]
 from . import merchant_api
 if merchant_api.supported(merchant):
  # Street/city consent belongs to the delivery review, not sentence intake.
  # Prefer the reviewed API without probing HTML or creating a hidden cart.
  result=merchant_api.quote(merchant,lines,destination,selected[0]['currency'],lambda operation,host:on_event('offer_'+operation,merchant=host))
  memo[key]=result;return result
 subtotal=sum(v['unit_minor']*qty for v,qty in zip(selected,quantities))
 # A real anonymous rate is preferred to a banner threshold when possible.
 if all(v.get('shopify') and isinstance(v.get('shopify_variant_id'),int) and v['shopify_variant_id']>0 for v in selected) and destination is not None:
  grouped={}
  for line in lines:
   ident=line['variant_id']
   if ident in grouped:grouped[ident]['quantity']+=line['quantity']
   else:grouped[ident]=line.copy()
  try:
   result=merchant_totals.quote('https://'+merchant,list(grouped.values()),destination,selected[0]['currency'],on_event)
   memo[key]=result;return result
  except ValueError as exc:cart_error=str(exc)
  session=retail.AnonymousShopify('https://'+merchant,lambda url:on_event('offer_quote',url=url));session.currency=selected[0]['currency']
  try:
   rate=session.quote(list(grouped.values()),destination.merchant_address());rate['quantity_confirmed']=True;rate['cart_total_unavailable']=cart_error;memo[key]=rate;return rate
  except ValueError as exc:
   policy=published_shipping(selected,subtotal,destination)
   if policy:policy['quote_attempt_error']=str(exc);memo[key]=policy;return policy
   memo[key]={'amount_minor':None,'reason':str(exc)};return memo[key]
 policy=published_shipping(selected,subtotal,destination);memo[key]=policy or {'amount_minor':None,'reason':'Destination shipping was not published or quoted.'};return memo[key]

def price_candidate(candidate,observations,destination,tax,on_event=lambda *a,**k:None,memo=None,fixed_rates=None,reviewed_rates=()):
 from .equipment_studio import passport
 memo={} if memo is None else memo;fixed_rates=fixed_rates or {};w=Workspace.model_validate(candidate['workspace']);p=Planning.model_validate(candidate['planning']);now=int(time.time());p.region=destination.key() if destination else ''
 purchases=[i for i in w.items if not i.owned];bindings={b.item_id:b for b in p.devices};rows=[];offer_options=[]
 for i in purchases:
  b=bindings.get(i.id);available=[v for v in observations.get(b.device_id,[]) if b and v['device_digest']==b.source_digest and v['currency']==w.currency and v['observed_at']<=now<=v['expires_at'] and v['stock']!='out_of_stock'] if b else []
  available.sort(key=lambda v:(v['stock']!='in_stock',v['unit_minor'],v['id']));offer_options.append(available[:2] or [None])
 best=None;combinations=0
 for combo in itertools.islice(itertools.product(*offer_options),256):
  combinations+=1;line_rows=[];groups={};unknown=[]
  for i,v in zip(purchases,combo):
   row={'item_id':i.id,'name':i.name,'quantity':1,'offer':v,'unit_minor':v['unit_minor'] if v else None,'stock':v['stock'] if v else 'unknown','shipping_minor':None,'tax_minor':None,'duty_minor':None,'fees_minor':None,'delivered_minor':None,'discount_minor':0};line_rows.append(row)
   if v:groups.setdefault(v['merchant'],[]).append(row)
   else:unknown.append(i.name+': no current exact-variant price/availability observation.')
  shipments=[]
  for merchant,lines in groups.items():
   rate=fixed_rates.get(merchant)
   if rate is None:
    rate=next((r for r in reviewed_rates if r.get('attested') and r['merchant']==merchant and r.get('basket_key')==line_key([v['offer'] for v in lines]) and same_destination(r.get('destination'),destination) and time.time()<=r.get('expires_at',0)),None)
   if rate and rate.get('attested') and (not destination or rate.get('basket_key')!=line_key([v['offer'] for v in lines]) or not same_destination(rate.get('destination'),destination) or time.time()>rate.get('expires_at',0)):rate=None
   if rate is None and fixed_rates:rate={'amount_minor':None,'reason':'Refresh this merchant quote for the current basket.'}
   if rate is None and not destination:rate={'amount_minor':None,'reason':'Set a delivery destination.'}
   elif rate is None:rate=merchant_rate([l['offer'] for l in lines],[1]*len(lines),destination,on_event,memo)
   shipments.append({'merchant':merchant,**rate});amount=rate.get('amount_minor')
   # Charge merchant shipping once, not once per item or across merchants.
   ordered=sorted(lines,key=lambda r:r['item_id'])
   if rate.get('merchant_total_complete') is True:
    subtotal=sum(v['unit_minor'] for v in lines);total=rate.get('total_minor');discount=rate.get('discount_minor',0)
    if type(total) is not int or type(discount) is not int or not 0<=discount<=subtotal or total<subtotal-discount:raise ValueError('Invalid complete merchant total.')
    allocations=rate.get('line_discounts',{})
    if discount and sum(allocations.values())!=discount:raise ValueError('Exact line discounts are unresolved.')
    for ident,amount in allocations.items():
     targets=[row for row in ordered if str(row['offer'].get('shopify_variant_id'))==ident]
     if type(amount) is not int or amount<0 or not targets or amount>sum(row['unit_minor'] for row in targets):raise ValueError('Invalid exact discount allocation.')
     base,remainder=divmod(amount,len(targets))
     for index,row in enumerate(targets):row['discount_minor']=base+(1 if index<remainder else 0)
    extra=total-(subtotal-discount)
    for n,row in enumerate(ordered):row['delivered_minor']=row['unit_minor']-row['discount_minor']+(extra if n==0 else 0)
   for n,row in enumerate(ordered):
    row['shipping_minor']=amount if n==0 else 0 if amount is not None else None
    for field in ('tax_minor','duty_minor','fees_minor'):
     if rate.get(field) is not None:row[field]=rate[field] if n==0 else 0
   grouped_units={}
   for row in lines:grouped_units[row['offer']['id']]=grouped_units.get(row['offer']['id'],0)+1
   for row in lines:
    if row['tax_minor'] is None:row['tax_minor']=0 if tax.get('amount_minor')==0 else 0 if row['offer'].get('tax_included') and destination and row['offer'].get('market_country')==destination.country else None
    # This preview only completes domestic-US delivery; imports aren't treated
    # as duty-free. Merchant quote remains an estimate before actual checkout.
    if row['duty_minor'] is None:row['duty_minor']=0 if destination and (row['offer'].get('ship_from_country')==destination.country or (row['offer'].get('included_charges') or {}).get('country')==destination.country) else None
    if row['fees_minor'] is None:row['fees_minor']=0 if destination and (row['offer'].get('ship_from_country')==destination.country or (row['offer'].get('included_charges') or {}).get('country')==destination.country) else None
    confirmed=rate.get('quantity_confirmed') or grouped_units[row['offer']['id']]<=row['offer']['confirmed_quantity']
    if row['stock']!='in_stock' or not confirmed:row['stock']='unknown';unknown.append(row['name']+': quantity is not confirmed available.')
    if row['delivered_minor'] is None and any(row[k] is None for k in ('unit_minor','shipping_minor','tax_minor','duty_minor','fees_minor')):unknown.append(row['name']+': a delivered charge is unresolved.')
  total=None if unknown else sum(row['delivered_minor'] if row['delivered_minor'] is not None else sum(row[k] for k in ('unit_minor','shipping_minor','tax_minor','duty_minor','fees_minor')) for row in line_rows)
  rank=(bool(unknown),sum(r['offer'] is None for r in line_rows),len(unknown),total if total is not None else sum(r['unit_minor'] or 0 for r in line_rows))
  value={'lines':line_rows,'shipments':shipments,'total_minor':total,'unknown':list(dict.fromkeys(unknown)),'rank':rank}
  if best is None or rank<best['rank']:best=value
 if best is None:best={'lines':[],'shipments':[],'total_minor':0,'unknown':[]}
 p.offers=[];qid=uuid.uuid4().hex;expiry=min([now+900,*[r['offer']['expires_at'] for r in best['lines'] if r['offer']],*[r['expires_at'] for r in best['shipments'] if r.get('expires_at')]])
 for row in best['lines']:
  v=row['offer']
  if not v:continue
  expiry=min(expiry,v['expires_at']);day=datetime.fromtimestamp(v['observed_at'],timezone.utc).date().isoformat();end=datetime.fromtimestamp(expiry,timezone.utc).date().isoformat()
  p.offers.append(Offer(id=uuid.uuid4().hex,item_id=row['item_id'],device_id=v['device_id'],currency=v['currency'],amount_minor=v['unit_minor'],discount_minor=row['discount_minor'],delivered_minor=row['delivered_minor'],shipping_minor=row['shipping_minor'],tax_minor=row['tax_minor'],duty_minor=row['duty_minor'],fees_minor=row['fees_minor'],stock=row['stock'],region=p.region,url=v['url'],observed_on=day,valid_until=end,quote_id=qid,observed_at=v['observed_at'],expires_at=expiry,return_note=('Public item price; additional charges are a user-reviewed merchant quote, not independently fetched tax evidence. '+next((r.get('reference','') for r in best['shipments'] if r.get('merchant')==v['merchant'] and r.get('attested')),''))[:500] if any(r.get('merchant')==v['merchant'] and r.get('attested') for r in best['shipments']) else 'Automatic merchant cart total; charge allocation belongs to the whole store basket. Tax/duty breakdown may be unitemized.' if row['delivered_minor'] is not None else 'Public merchant observation; confirm current terms at the store.'))
 candidate=copy.deepcopy(candidate);candidate['planning']=p.model_dump();candidate['passport']=passport(w,p)
 total=best['total_minor'];budget=w.budget_cents;status='incomplete' if total is None else 'over_budget' if budget is not None and total>budget else 'within_budget_estimate' if budget is not None else 'no_budget'
 candidate['landed']={'id':qid,'status':status,'currency':w.currency,'subtotal_minor':sum(r['unit_minor'] or 0 for r in best['lines']) if all(r['unit_minor'] is not None for r in best['lines']) else None,'shipping_minor':sum(s['amount_minor'] for s in best['shipments']) if all(r['offer'] is not None for r in best['lines']) and all(s['amount_minor'] is not None for s in best['shipments']) else None,'tax_minor':sum(r['tax_minor'] for r in best['lines']) if all(r['tax_minor'] is not None for r in best['lines']) else None,'duty_minor':sum(r['duty_minor'] for r in best['lines']) if all(r['duty_minor'] is not None for r in best['lines']) else None,'fees_minor':sum(r['fees_minor'] for r in best['lines']) if all(r['fees_minor'] is not None for r in best['lines']) else None,'discount_minor':sum(r.get('discount_minor',0) for r in best['lines']),'has_reviewed_charges':any(v.get('attested') for v in best['shipments']),'automatic_totals':bool(best['shipments']) and all(v.get('merchant_total_complete') for v in best['shipments']),'combined_charges_minor':total-sum(r['unit_minor']-r.get('discount_minor',0) for r in best['lines']) if total is not None else None,'tax_included':bool(best['lines']) and all(r['offer'] and r['offer'].get('tax_included') and destination and r['offer'].get('market_country')==destination.country and r['tax_minor']==0 for r in best['lines']),'offer_combinations_evaluated':combinations,'offer_search_complete':combinations==__import__('math').prod(len(v) for v in offer_options),'total_minor':total,'remaining_minor':budget-total if budget is not None and total is not None else None,'destination':destination.public() if destination else None,'lines':best['lines'],'shipments':best['shipments'],'tax':tax,'unknown':best['unknown'],'observed_at':now,'expires_at':expiry,'scope':'Time-bound delivered estimate from exact public offers, recorded stock and merchant shipping/tax basis. Worldwide destination support where store quotes are available. Imported duties/taxes/fees must be resolved; no reservation, order, payment or final checkout guarantee.'}
 candidate['rank']=[sum(g['status']=='unmet' and g['kind'] not in ('budget','availability') for g in candidate['passport']['checks']),{'within_budget_estimate':0,'no_budget':1,'incomplete':3,'over_budget':2}[status],sum(r['offer'] is None for r in best['lines']),len(best['unknown']),len(candidate['passport']['blockers']),total if total is not None else sum(r['unit_minor'] or 0 for r in best['lines'])]
 record={'id':qid,'expires_at':expiry,'basket_hash':scope(w,p),'offers':{o.id:specs.digest(o.model_dump()) for o in p.offers}}
 return candidate,record

def register(module):
 @module.app.get('/api/setup/delivery')
 def preview_delivery():
  import os
  return {'destination':{'country':'US','region':'OR','postal':'97205','test':True} if os.environ.get('INTENTCART_TEST_DELIVERY')=='true' else None,**delivery_catalog(),'scope':'Coarse delivery destination only; no street address or account data is sent to merchants.'}
