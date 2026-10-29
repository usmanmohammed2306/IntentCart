"""Tokenless, anonymous Shopify cart estimates; no checkout or payment operation.
Only non-estimated, exact-basket merchant totals qualify as complete. Missing tax
is not zero. Cart keys remain inside one call and every created cart is emptied.
"""
import http.client,ipaddress,json,re,socket,time
from . import retail_sources as retail,device_research as specs

VERSION='2026-07'
FIELDS='''id totalQuantity lines(first:12){nodes{id quantity merchandise{... on ProductVariant{id availableForSale price{amount currencyCode}}} cost{totalAmount{amount currencyCode}}}} cost{subtotalAmount{amount currencyCode} subtotalAmountEstimated totalAmount{amount currencyCode} totalAmountEstimated} estimatedCost{totalTaxAmount{amount currencyCode} totalDutyAmount{amount currencyCode}} deliveryGroups(first:6,withCarrierRates:true){nodes{id deliveryOptions{handle title estimatedCost{amount currencyCode}} selectedDeliveryOption{handle estimatedCost{amount currencyCode}}}}'''
CREATE='mutation IntentCartEstimate($input:CartInput!){cartCreate(input:$input){cart{'+FIELDS+'}userErrors{code} warnings{code}}}'
SELECT='mutation IntentCartDelivery($id:ID!,$options:[CartSelectedDeliveryOptionInput!]!){cartSelectedDeliveryOptionsUpdate(cartId:$id,selectedDeliveryOptions:$options){cart{'+FIELDS+'}userErrors{code} warnings{code}}}'
CLEAR='mutation IntentCartClear($id:ID!,$lines:[ID!]!){cartLinesRemove(cartId:$id,lineIds:$lines){cart{totalQuantity}userErrors{code}}}'
class Cart:
 def __init__(self,origin):
  from urllib.parse import urlsplit
  p=urlsplit(origin)
  if not retail.allowed(origin) or p.path not in ('','/'):raise ValueError('Unsupported merchant origin.')
  self.host=p.hostname;self.url='https://'+self.host+'/api/'+VERSION+'/graphql.json'
 def call(self,query,variables):
  if query not in (CREATE,SELECT,CLEAR):raise ValueError('Unsupported merchant estimate operation.')
  try:ips=list(dict.fromkeys(v[4][0] for v in socket.getaddrinfo(self.host,443,type=socket.SOCK_STREAM)))
  except OSError:raise ValueError('Merchant estimate DNS unavailable.') from None
  if not ips or any(not ipaddress.ip_address(v).is_global for v in ips):raise ValueError('Non-public merchant estimate destination blocked.')
  conn=specs.PublicHTTPS(self.host,ips[0]);conn.timeout=10
  try:
   payload=json.dumps({'query':query,'variables':variables},separators=(',',':')).encode()
   if len(payload)>16000:raise ValueError('Merchant estimate request too large.')
   conn.request('POST','/api/'+VERSION+'/graphql.json',body=payload,headers={'Content-Type':'application/json','Accept':'application/json','Accept-Encoding':'identity','User-Agent':'IntentCart-PublicEstimate/1.0','Connection':'close'})
   response=conn.getresponse()
   if response.status==429:raise retail.RateLimited(response.getheader('Retry-After'))
   if response.status!=200 or response.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise ValueError('Merchant estimate HTTP'+str(response.status)+'; no login or access challenge bypassed.')
   raw=response.read(200001)
   if len(raw)>200000:raise ValueError('Merchant estimate response too large.')
   result=json.loads(raw)
   if not isinstance(result,dict):raise ValueError('Invalid merchant estimate response.')
   return result
  except (OSError,http.client.HTTPException,UnicodeError,json.JSONDecodeError):raise ValueError('Merchant estimate could not be read.') from None
  finally:conn.close()

def money(v,currency):
 if not isinstance(v,dict) or v.get('currencyCode')!=currency:raise ValueError('Merchant estimate currency mismatch.')
 return retail.money(v.get('amount'))
def nodes(v,key,limit):
 data=(v.get(key) or {}).get('nodes')
 if not isinstance(data,list) or len(data)>limit or not all(isinstance(x,dict) for x in data):raise ValueError('Invalid merchant estimate collection.')
 return data

def lines_match(cart,lines,currency):
 observed=[];ids=[]
 for row in nodes(cart,'lines',12):
  product=row.get('merchandise') or {};ident=product.get('id','');qty=row.get('quantity')
  if not re.fullmatch(r'gid://shopify/ProductVariant/[1-9][0-9]*',ident) or type(qty) is not int or qty<1 or product.get('availableForSale') is not True or not isinstance(row.get('id'),str):raise ValueError('Exact merchant variant/availability not confirmed.')
  observed.append((int(ident.rsplit('/',1)[1]),qty,money(product.get('price'),currency),money((row.get('cost') or {}).get('totalAmount'),currency)));ids.append(row['id'])
 wanted=sorted((x['variant_id'],x['quantity'],x['unit_minor'],x['unit_minor']*x['quantity']) for x in lines)
 if sorted(observed)!=wanted or type(cart.get('totalQuantity')) is not int or cart['totalQuantity']!=sum(x['quantity'] for x in lines):raise ValueError('The merchant changed a variant, quantity or item price.')
 return ids

def payload(result,key):
 data=(result.get('data') or {}).get(key) or {}
 if result.get('errors') or data.get('userErrors') or data.get('warnings') or not isinstance(data.get('cart'),dict):raise ValueError('Merchant estimate rejected or changed this basket.')
 return data['cart']

def quote(origin,lines,destination,currency,on_event=lambda *a,**kw:None,cart_factory=Cart,address=None):
 if not lines or len(lines)>12 or any(type(x.get('variant_id')) is not int or x['variant_id']<=0 or type(x.get('quantity')) is not int or not 1<=x['quantity']<=4 or type(x.get('unit_minor')) is not int or x['unit_minor']<0 for x in lines):raise ValueError('Invalid exact merchant basket.')
 client=cart_factory(origin)
 # Reserve all possible operations before creating anything, including cleanup.
 # A job/rate/cancellation limit cannot prevent a reserved cart cleanup.
 for operation in ('create','delivery','clear'):on_event('offer_quote',url=client.url,operation=operation)
 cart=None;created=None
 try:
  fields={'countryCode':destination.country,'provinceCode':destination.region,'zip':destination.postal}
  if address:fields.update(address)
  data={'lines':[{'merchandiseId':'gid://shopify/ProductVariant/'+str(x['variant_id']),'quantity':x['quantity']} for x in lines],'buyerIdentity':{'countryCode':destination.country,'deliveryAddressPreferences':[{'deliveryAddress':{'country':destination.merchant_address()['country_name'],'province':destination.region,'zip':destination.postal}}]},'delivery':{'addresses':[{'selected':True,'oneTimeUse':True,'address':{'deliveryAddress':fields}}]}}
  if address:data['buyerIdentity'].pop('deliveryAddressPreferences',None)
  result=client.call(CREATE,{'input':data})
  created=(result.get('data') or {}).get('cartCreate') or {};cart=created.get('cart')
  if not isinstance(cart,dict):cart=None
  cart=payload(result,'cartCreate');lines_match(cart,lines,currency)
  groups=nodes(cart,'deliveryGroups',6)
  if not groups:raise ValueError('The merchant returned no delivery group for this destination.')
  options=[];shipping=0;services=[]
  for group in groups:
   rates=[]
   for option in group.get('deliveryOptions') or []:
    title=option.get('title','');handle=option.get('handle')
    if not isinstance(title,str) or re.search(r'pickup|collect|member|subscription',title,re.I) or not title or not isinstance(handle,str):continue
    try:cost=money(option.get('estimatedCost'),currency)
    except ValueError:continue
    rates.append((cost,title,handle))
   if not rates or not isinstance(group.get('id'),str):raise ValueError('The merchant returned no eligible delivery option.')
   amount,title,handle=min(rates);shipping+=amount;services.append(title);options.append({'deliveryGroupId':group['id'],'deliveryOptionHandle':handle})
  selected=payload(client.call(SELECT,{'id':cart['id'],'options':options}),'cartSelectedDeliveryOptionsUpdate')
  lines_match(selected,lines,currency)
  confirmed=nodes(selected,'deliveryGroups',6)
  expected={v['deliveryGroupId']:v['deliveryOptionHandle'] for v in options}
  if len(confirmed)!=len(expected) or any(expected.get(g.get('id'))!=(g.get('selectedDeliveryOption') or {}).get('handle') for g in confirmed):raise ValueError('Merchant did not confirm the requested delivery options.')
  if sum(money(g['selectedDeliveryOption'].get('estimatedCost'),currency) for g in confirmed)!=shipping:raise ValueError('Merchant delivery charge changed.')
  cost=selected.get('cost') or {};subtotal=sum(v['unit_minor']*v['quantity'] for v in lines)
  if money(cost.get('subtotalAmount'),currency)!=subtotal:raise ValueError('Merchant subtotal changed; refresh product offers.')
  reported=money(cost.get('totalAmount'),currency)
  if reported<subtotal+shipping:raise ValueError('Merchant total does not reconcile with items and selected delivery.')
  complete=cost.get('totalAmountEstimated') is False and cost.get('subtotalAmountEstimated') is False
  breakdown=selected.get('estimatedCost') or {};tax=duty=None
  for field in ('totalTaxAmount','totalDutyAmount'):
   value=breakdown.get(field)
   if value is not None:
    amount=money(value,currency)
    if field=='totalTaxAmount':tax=amount
    else:duty=amount
  now=int(time.time())
  return {'automatic':True,'merchant_total_complete':complete,'total_minor':reported if complete else None,'merchant_reported_total_minor':reported,'amount_minor':shipping,'tax_minor':tax if complete else None,'duty_minor':duty if complete else None,'fees_minor':None,'service':' + '.join(services),'quantity_confirmed':True,'source':'Merchant anonymous cart / selected delivery','source_url':client.url,'response_sha256':specs.digest(selected),'observed_at':now,'expires_at':now+900,'destination':destination.public(),'reason':'' if complete else 'The merchant marks the total provisional and withholds final tax/duties; it is not a complete delivered price.','scope':'Merchant estimate, not reserved stock, a final checkout guarantee or an order. Cart key and line IDs are never retained.'}
 finally:
  if cart is not None and isinstance(cart.get('id'),str):
   ids=[r.get('id') for r in ((cart.get('lines') or {}).get('nodes') or []) if isinstance(r,dict) and isinstance(r.get('id'),str)]
   if not ids:raise retail.QuoteCleanupError('Created merchant cart cleanup could not be confirmed.')
   try:cleared=payload(client.call(CLEAR,{'id':cart['id'],'lines':ids}),'cartLinesRemove')
   except Exception:raise retail.QuoteCleanupError('Created merchant cart cleanup failed verification.') from None
   if type(cleared.get('totalQuantity')) is not int or cleared['totalQuantity']!=0:raise retail.QuoteCleanupError('Anonymous merchant cart cleanup not confirmed.')
