"""Reviewed anonymous UCP transport. No payment/order/completion methods.
A separate supported API is preferred explicitly, never retried after an HTML
challenge. Demo capability profile is opt-in and local-only; production needs
its own public agent profile. No browser cookies, tokens or customer identity.
"""
import copy,http.client,ipaddress,json,os,re,socket,threading,time,uuid
from urllib.parse import urlsplit
from . import retail_sources as retail,device_research as specs
VERSION='2026-08-25'
# Advertised by each canonical store's /.well-known/ucp; reviewed 2026-10-28.
# Cross-origin permission is exact, not arbitrary *.myshopify.com access.
STORES={'plugable.com':{'host':'plugabletechnologies.myshopify.com','path':'/api/ucp/mcp','permalink':'/buy'},'satechi.com':{'host':'satechi.myshopify.com','path':'/api/ucp/mcp','permalink':'/buy'}}
TUTORIAL='https://shopify.dev/ucp/agent-profiles/examples/2026-08-25/valid-with-capabilities.json'
CAPABILITIES=('cart','checkout','fulfillment','discount','catalog.lookup','catalog.search')
_cache={};_lock=threading.RLock()
def profile_document():
 capabilities={'dev.ucp.shopping.'+k:[{'version':VERSION}] for k in CAPABILITIES}
 for extension in ('fulfillment','discount'):
  capabilities['dev.ucp.shopping.'+extension][0]['extends']=['dev.ucp.shopping.checkout','dev.ucp.shopping.cart']
 return {'ucp':{'version':VERSION,'services':{'dev.ucp.shopping':[{'version':VERSION,'spec':'https://ucp.dev/'+VERSION+'/specification/overview','transport':'mcp','schema':'https://ucp.dev/'+VERSION+'/services/shopping/mcp.openrpc.json'}]},'capabilities':capabilities,'payment_handlers':{}}}
def profile_uri():
 value=os.environ.get('INTENTCART_UCP_PROFILE_URL','')
 if value==TUTORIAL:
  if os.environ.get('INTENTCART_UCP_TUTORIAL')!='true' or os.environ.get('INTENTCART_MODE')!='local':raise ValueError('The tutorial profile is only available in an explicit local test.')
 elif value:
  p=urlsplit(value)
  if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.port not in (None,443):raise ValueError('Configure a public HTTPS UCP agent profile.')
 return value

def supported(host):return host in STORES and bool(profile_uri())
class Client:
 def __init__(self,merchant):
  if not supported(merchant):raise ValueError('This store has no reviewed UCP connector and configured agent profile.')
  self.merchant=merchant;self.config=STORES[merchant];self.url='https://'+self.config['host']+self.config['path']
 def call(self,name,arguments):
  if name not in ('lookup_catalog','create_checkout','get_checkout','cancel_checkout'):raise ValueError('Only catalog and cancellable estimates are permitted.')
  def forbidden(v):
   if isinstance(v,dict):return any(k in ('payment','buyer','signals','attribution','discounts') or forbidden(x) for k,x in v.items())
   return isinstance(v,list) and any(forbidden(x) for x in v)
  if forbidden(arguments):raise ValueError('Payment credentials, buyer identity and tracking are not supported.')
  payload={'jsonrpc':'2.0','id':uuid.uuid4().hex,'method':'tools/call','params':{'name':name,'arguments':{**arguments,'meta':{'ucp-agent':{'profile':profile_uri()},'idempotency-key':str(uuid.uuid4())}}}}
  raw=json.dumps(payload,separators=(',',':')).encode()
  if len(raw)>20000:raise ValueError('Merchant estimate exceeds request bound.')
  try:ips=list(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(self.config['host'],443,type=socket.SOCK_STREAM)))
  except OSError:raise ValueError('Merchant API DNS unavailable.') from None
  if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):raise ValueError('Non-public merchant API blocked.')
  conn=specs.PublicHTTPS(self.config['host'],ips[0]);conn.timeout=10
  try:
   conn.request('POST',self.config['path'],body=raw,headers={'Content-Type':'application/json','Accept':'application/json','Accept-Encoding':'identity','User-Agent':'IntentCart-UCP-Preview/1.0','Connection':'close'})
   response=conn.getresponse()
   if response.status==429:raise retail.RateLimited(response.getheader('Retry-After'))
   if response.status!=200:raise ValueError('Merchant API HTTP'+str(response.status)+'. No alternate endpoint or retry was attempted.')
   if response.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise ValueError('Unsupported merchant API encoding.')
   raw=response.read(500001)
   if len(raw)>500000:raise ValueError('Merchant API response exceeded bound.')
   value=json.loads(raw);result=value.get('result') or {};data=result.get('structuredContent')
   if value.get('error') or result.get('isError') or not isinstance(data,dict):raise ValueError('Merchant API rejected this estimate.')
   if data.get('ucp',{}).get('status')!='success' or data.get('ucp',{}).get('version')!=VERSION:raise ValueError('Merchant protocol negotiation failed.')
   return data
  except (OSError,http.client.HTTPException,UnicodeError,json.JSONDecodeError):raise ValueError('Merchant API could not be securely read.') from None
  finally:conn.close()

def discovery_offer(profile,currency='USD'):
 """Builtin, source-bound variant pointers contain no live price or stock.
 An imported profile with a matching ID cannot inherit this authority.
 """
 from pathlib import Path
 if currency!='USD':return None
 builtin=next((v for v in specs.catalog() if v['id']==profile['id'] and v['digest']==profile['digest']),None)
 if not builtin:return None
 rows=json.loads((Path(__file__).parent/'data/store-products.json').read_text())['products']
 row=next((v for v in rows if v['device_id']==profile['id']),None)
 if not row or not supported(row['merchant']) or row['url'] not in [v.get('url') for v in profile['sources']]:return None
 return {'id':specs.digest({'discovery':row,'device':profile['digest']})[:32],'device_id':profile['id'],'device_digest':profile['digest'],'name':profile['name'],'variant':row['sku'],'seller':row['merchant'],'merchant':row['merchant'],'unit_minor':0,'currency':currency,'market_country':None,'stock':'unknown','confirmed_quantity':0,'url':row['url'],'observed_at':0,'expires_at':0,'source_sha256':specs.digest(row),'source_url':row['url'],'evidence':{},'shopify_variant_id':row['variant_id'],'shopify':True,'discovery_only':True,'scope':'Reviewed variant pointer only. Refresh the merchant catalog for price and availability.'}

def refresh(merchant,old,profile,currency,event,client_factory=Client,country='US'):
 ident=old.get('shopify_variant_id')
 if type(ident) is not int or ident<=0:raise ValueError('An exact observed store variant is required.')
 key=(merchant,ident,currency,country,profile['digest']);now=int(time.time())
 # Serialize bounded catalog cache misses; no customer address is cached.
 with _lock:
  cached=_cache.get(key)
  if cached and now<cached['until']:return copy.deepcopy(cached['offer'])
  event('catalog',merchant);client=client_factory(merchant)
  data=client.call('lookup_catalog',{'catalog':{'ids':['gid://shopify/ProductVariant/'+str(ident)],'context':{'address_country':country,'currency':currency}}})
  candidates=[]
  for product in data.get('products',[])[:10]:
   p=urlsplit(product.get('url',''))
   if p.scheme!='https' or p.hostname!=merchant or p.path.rstrip('/')!=urlsplit(old['url']).path.rstrip('/'):continue
   for v in product.get('variants',[])[:20]:
    if v.get('id')=='gid://shopify/ProductVariant/'+str(ident):candidates.append((product,v))
  if len(candidates)!=1:raise ValueError('The exact variant is unavailable or no longer exposed by the merchant catalog.')
  product,v=candidates[0];price=v.get('price') or {}
  if not retail.identity({'name':product.get('title',''),'sku':v.get('sku','')},profile):raise ValueError('The merchant model no longer matches the reviewed device.')
  if v.get('requires',{}).get('selling_plan') is True:raise ValueError('Subscription variants are not supported.')
  if v.get('availability',{}).get('available') is not True:raise ValueError('The exact variant is unavailable at this store.')
  if price.get('currency')!=currency or type(price.get('amount')) is not int or not 0<=price['amount']<=100000000:raise ValueError('The merchant price or currency is invalid.')
  offer=copy.deepcopy(old);fingerprint=specs.digest({'product':product,'variant':v,'currency':currency})
  offer.update(id=specs.digest({'catalog':fingerprint,'device':profile['digest'],'time':now})[:32],unit_minor=price['amount'],stock='in_stock',confirmed_quantity=1,observed_at=now,expires_at=now+900,market_country=country,source_url=client.url,source_sha256=fingerprint,evidence={'price':str(price['amount'])+' minor '+currency,'identity':product['title'],'sku':v.get('sku',''),'via':'Anonymous merchant UCP catalog'},scope='Current exact merchant catalog observation; no stock reservation or order.',discovery_only=False)
  _cache[key]={'until':now+60,'offer':copy.deepcopy(offer)}
  while len(_cache)>64:del _cache[next(iter(_cache))]
  return offer

def totals(rows):
 if not isinstance(rows,list) or len(rows)>12:raise ValueError('Invalid merchant totals.')
 out={}
 for row in rows:
  if not isinstance(row,dict):raise ValueError('Invalid merchant charge.')
  k=row.get('type');n=row.get('amount')
  if k not in ('subtotal','fulfillment','tax','total','fee','duty','discount','items_discount') or k in out or type(n) is not int:raise ValueError('Unrecognized, repeated or invalid merchant charge.')
  if n<0 and k not in ('discount','items_discount') or n>0 and k in ('discount','items_discount'):raise ValueError('Invalid merchant charge/discount sign.')
  out[k]=n
 return out

def checked_lines(data,lines,currency):
 if data.get('currency')!=currency:raise ValueError('Merchant currency changed.')
 from .merchant_discounts import validate
 return validate(data,lines,totals)

def estimate(data,lines,destination,currency,address,source_url,renderer_verified=False):
 if not renderer_verified and (data.get('status')=='requires_escalation' or any(m.get('code')=='extension_interaction_required' for m in data.get('messages',[]))):
  raise ValueError('This store requires its checkout page to confirm delivery, discounts and tax. Open the store checkout; no final total was accepted.')
 discounts=checked_lines(data,lines,currency);cost=totals(data.get('totals'));subtotal=sum(v['quantity']*v['unit_minor'] for v in lines)
 if cost.get('subtotal')!=subtotal:raise ValueError('Merchant subtotal changed.')
 codes=[m.get('code','unknown') for m in data.get('messages',[]) if m.get('type') in ('error','warning')]
 allowed={'buyer_identity_contact_method_required','delivery_first_name_required','delivery_last_name_required'}
 if renderer_verified:allowed|={'extension_interaction_required','delivery_phone_number_required'}
 if set(codes)-allowed:raise ValueError('The merchant needs more delivery details or cannot supply this cart: '+', '.join(sorted(set(codes)-allowed)))
 methods=data.get('fulfillment',{}).get('methods',[]);shipping=0;services=[];covered=[]
 if not methods:raise ValueError('The merchant returned no delivery method.')
 expected_ids=sorted(v['id'] for v in data['line_items'])
 for m in methods:
  if m.get('type')!='shipping':raise ValueError('A non-shipping method was returned.')
  destinations=[v for v in m.get('destinations',[]) if v.get('id')==m.get('selected_destination_id')]
  if len(destinations)!=1:raise ValueError('Delivery destination was not selected.')
  dest=destinations[0];expected={'address_country':destination.country,'address_region':destination.region,'postal_code':destination.postal,'street_address':address['address1'],'address_locality':address['city']}
  if any(str(dest.get(k,'')).strip().casefold()!=str(v).strip().casefold() for k,v in expected.items()):raise ValueError('The merchant changed the delivery address.')
  for g in m.get('groups',[]):
   option=next((o for o in g.get('options',[]) if o.get('id')==g.get('selected_option_id')),None)
   if not option or re.search(r'pickup|collect|member|subscription',option.get('title',''),re.I):raise ValueError('No eligible shipping option is selected.')
   amount=totals(option.get('totals')).get('total')
   if amount is None:raise ValueError('Selected shipping charge is unresolved.')
   shipping+=amount;services.append(option.get('title','Shipping'));covered.extend(g.get('line_item_ids',[]))
 if sorted(covered)!=expected_ids:raise ValueError('Shipping does not cover every exact cart line once.')
 if not {'subtotal','fulfillment','total'}<=cost.keys() or cost['fulfillment']!=shipping or sum(cost.get(k,0) for k in ('subtotal','fulfillment','tax','duty','fee','discount','items_discount'))!=cost['total']:raise ValueError('The merchant total does not reconcile with itemized delivery and tax.')
 if data.get('status') not in (('incomplete','ready_for_complete','requires_escalation') if renderer_verified else ('incomplete','ready_for_complete')):raise ValueError('Merchant checkout requires separate review.')
 from datetime import datetime
 try:expiry=int(datetime.fromisoformat(data['expires_at'].replace('Z','+00:00')).timestamp())
 except (KeyError,ValueError,TypeError,AttributeError):raise ValueError('Merchant estimate expiry is unavailable.') from None
 now=int(time.time())
 if expiry<=now:raise ValueError('Merchant estimate has expired.')
 return {'automatic':True,'merchant_total_complete':True,'total_minor':cost['total'],**discounts,'merchant_reported_total_minor':cost['total'],'amount_minor':shipping,'tax_minor':cost.get('tax'),'duty_minor':cost.get('duty'),'fees_minor':cost.get('fee'),'service':' + '.join(services),'quantity_confirmed':True,'source':'Merchant UCP checkout estimate / selected delivery','source_url':source_url,'response_sha256':specs.digest({'currency':currency,'totals':data['totals'],'lines':lines,'destination':destination.public(),'shipping':services}),'observed_at':now,'expires_at':min(now+900,expiry),'destination':destination.public(),'reason':'','checkout_status':data['status'],'remaining_input_codes':codes,'scope':'Itemized merchant estimate for this destination, not a completed or payment-ready purchase. The temporary checkout is canceled; final store charges can change.'}

def quote(merchant,lines,destination,currency,event,address=None,client_factory=Client):
 client=client_factory(merchant)
 if not lines or len(lines)>12 or any(type(v.get('variant_id')) is not int or v['variant_id']<=0 or type(v.get('quantity')) is not int or not 1<=v['quantity']<=4 or type(v.get('unit_minor')) is not int or v['unit_minor']<0 for v in lines):raise ValueError('Invalid exact merchant basket.')
 if not address:return {'amount_minor':None,'reason':'This store needs a street and city to calculate delivery and tax. Enter them under More precise delivery or directly at the store.'}
 # Reserve create and cancellation before mutation. Cancellation uses no new
 # reservation and cannot be suppressed by the outer elapsed/request ceiling.
 for op in ('ucp_estimate','ucp_cancel'):event(op,merchant)
 created=None;visible=None
 try:
  line_items=[{'item':{'id':'gid://shopify/ProductVariant/'+str(v['variant_id'])},'quantity':v['quantity']} for v in lines]
  fields={'id':'delivery','street_address':address['address1'],'address_locality':address['city'],'address_region':destination.region,'postal_code':destination.postal,'address_country':destination.country}
  data=client.call('create_checkout',{'checkout':{'line_items':line_items,'context':{'address_country':destination.country,'currency':currency},'fulfillment':{'methods':[{'type':'shipping','selected_destination_id':'delivery','destinations':[fields]}]}}})
  created=data.get('id')
  if not isinstance(created,str) or not created.startswith('gid://shopify/Checkout/'):raise ValueError('The merchant did not create a cancellable estimate.')
  if merchant=='satechi.com' and data.get('status')=='requires_escalation':
   from .merchant_browser import render
   event('merchant_browser',merchant)
   visible=render(data.get('continue_url',''),destination,address)
   event('checkout_verify',merchant)
   data=client.call('get_checkout',{'id':created})
   # Visible amounts are diagnostic until the exact API contract reconciles.
   from .merchant_browser import displayed_total
   if data.get('id')!=created or displayed_total(visible['summary_rows'],currency)!=totals(data.get('totals')).get('total'):raise ValueError('The displayed merchant total and exact checkout response disagree.')
  value=estimate(data,lines,destination,currency,address,client.url,renderer_verified=visible is not None)
  if visible:value.update(source='Rendered merchant checkout + exact API revalidation',renderer={k:visible.get(k) for k in ('resource_requests','blocked_requests','declared_response_bytes','elapsed_ms')})
  return value
 finally:
  if created:
   try:
    result=client.call('cancel_checkout',{'id':created})
    if result.get('id')!=created or result.get('status')!='canceled':raise ValueError('Cancellation not confirmed.')
   except Exception:raise retail.QuoteCleanupError('Temporary merchant checkout cancellation could not be verified.') from None
