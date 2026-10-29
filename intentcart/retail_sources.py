"""Keyless public offer observations. No browser/account cookies, checkout or scripts.
Product JSON-LD is data, never instructions. Snippets/aggregate prices aren't quotes.
"""
import hashlib,http.client,ipaddress,json,re,socket,ssl,time
import pycountry
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,quote_plus,unquote,parse_qs
from . import device_research as specs,free_discovery as discovery
ROOTS=tuple(dict.fromkeys(specs.ROOTS+('bhphotovideo.com','bestbuy.com','officedepot.com','staples.com','newegg.com','oregon.gov')))
class Unavailable(ValueError):pass
class QuoteCleanupError(RuntimeError):pass
class RateLimited(Unavailable):
 def __init__(self,retry_after=None):
  now=time.time()
  try:
   if str(retry_after).strip().isdigit():until=now+int(retry_after)
   else:
    from email.utils import parsedate_to_datetime
    until=parsedate_to_datetime(retry_after).timestamp()
  except (TypeError,ValueError,OverflowError,AttributeError):until=now+300
  self.retry_at=int(max(now+1,until))
  super().__init__('Merchant HTTP429. Try after '+datetime.fromtimestamp(self.retry_at,timezone.utc).isoformat()+'. No request was retried.')

def allowed(url):
 try:
  p=urlsplit(url);h=(p.hostname or '').lower().rstrip('.')
  return p.scheme=='https' and not p.username and not p.password and p.port in (None,443) and not p.fragment and len(url)<=1500 and not re.search(r'(?:token|password|api.?key|secret|session|auth)=',p.query,re.I) and any(h==r or h.endswith('.'+r) for r in ROOTS)
 except ValueError:return False

def read(url,on_request=lambda *x:None):
 started=time.monotonic();redirects=[]
 for _ in range(4):
  if not allowed(url):raise Unavailable('Use an approved public HTTPS merchant/source; login links are not supported.')
  p=urlsplit(url);host=p.hostname
  try:ips=list(dict.fromkeys(v[4][0] for v in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
  except OSError:raise Unavailable('Public-source DNS unavailable.') from None
  if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):raise Unavailable('Non-public or mixed DNS blocked.')
  if time.monotonic()-started>25:raise Unavailable('Public offer read timed out.')
  on_request(url);conn=specs.PublicHTTPS(host,ips[0]);conn.timeout=10
  try:
   conn.request('GET',(p.path or '/')+('?' +p.query if p.query else ''),headers={'User-Agent':'IntentCart-PublicOfferReader/1.0','Accept':'text/html,application/json,text/plain','Accept-Encoding':'identity','Connection':'close'})
   r=conn.getresponse()
   if r.status in (301,302,303,307,308):url=urljoin(url,r.getheader('Location',''));redirects.append(url);continue
   if r.status==429:raise RateLimited(r.getheader('Retry-After'))
   if r.status!=200:raise Unavailable('Public merchant/source HTTP'+str(r.status)+'; no challenge or access limit was bypassed.')
   if r.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise Unavailable('Unsupported compressed response.')
   raw=bytearray()
   while True:
    if time.monotonic()-started>25:raise Unavailable('Public offer exceeded time bound.')
    block=r.read(min(65536,1_500_001-len(raw)))
    if not block:break
    raw.extend(block)
    if len(raw)>1_500_000:raise Unavailable('Public response exceeded1.5MB.')
   content=r.getheader('Content-Type','').split(';')[0].lower()
   if content not in ('text/html','application/xhtml+xml','application/json','text/plain'):raise Unavailable('Only public HTML/JSON/text offers are supported.')
  except (OSError,ssl.SSLError,http.client.HTTPException) as exc:raise Unavailable('Secure public offer read failed.') from exc
  finally:conn.close()
  decoded=bytes(raw).decode('utf8','replace')
  if any(w in decoded.lower() for w in ('challenge-form','anomaly.js','cf-chl-')):raise Unavailable('Public merchant presented an access challenge; no bypass.')
  parser=Page();parser.feed(decoded) if content!='application/json' else None
  return {'url':url,'observed_at':int(time.time()),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'html':decoded,'text':' '.join(parser.parts)[:80000] if content!='application/json' else '', 'jsonld':parser.jsonld,'content_type':content,'redirects':redirects}
 raise Unavailable('Too many redirects.')

class Page(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.jsonld=[];self.capture=False;self.ignore=False;self.chunk=[]
 def handle_starttag(self,tag,attrs):
  if tag=='script':self.ignore=True;self.capture=dict(attrs).get('type','').lower()=='application/ld+json';self.chunk=[]
  elif tag in ('style','noscript','svg'):self.ignore=True
 def handle_endtag(self,tag):
  if tag=='script':
   if self.capture:
    try:self.jsonld.append(json.loads(''.join(self.chunk)))
    except (ValueError,TypeError):pass
   self.capture=False;self.ignore=False
  elif tag in ('style','noscript','svg'):self.ignore=False
 def handle_data(self,data):
  if self.capture:self.chunk.append(data)
  elif not self.ignore:self.parts.append(data.strip())

def money(value):
 if isinstance(value,bool):raise ValueError('Boolean price rejected.')
 raw=str(value).strip()
 if ',' in raw and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?',raw):raise ValueError('Ambiguous localized amount; use an explicit decimal quote.')
 try:n=Decimal(raw.replace(',',''))
 except InvalidOperation:raise ValueError('Invalid currency amount.') from None
 if not n.is_finite() or n<0 or n>1000000 or n!=n.quantize(Decimal('.01')):raise ValueError('Invalid price precision/range.')
 return int(n*100)
def objects(value):
 if isinstance(value,list):
  for v in value:yield from objects(v)
 elif isinstance(value,dict):
  yield value
  for k in ('@graph','mainEntity','hasVariant','itemListElement','item'):
   if k in value:yield from objects(value[k])
def is_type(v,t):
 value=v.get('@type');return t in ([value] if isinstance(value,str) else value if isinstance(value,list) else [])
def identity(product,profile):
 brand=product.get('brand',{});brand=brand.get('name','') if isinstance(brand,dict) else brand
 name=' '.join(str(product.get(k,'')) for k in ('name','sku','mpn','model'))+' '+str(brand)
 actual=set(specs.normalize(name).split())
 # Contradictory named model codes do not become exact just because a SKU matches.
 expected_codes=set(re.findall(r'\b[a-z0-9]+-[a-z0-9]+\b',' '.join(profile.get('aliases',[])).lower()))
 named_codes=set(re.findall(r'\b[a-z0-9]+-[a-z0-9]+\b',str(product.get('name','')).lower()))
 if any(a.split('-')[0]==b.split('-')[0] and a!=b for a in expected_codes for b in named_codes):return False
 if {'without','stand'}<=actual and 'without' not in specs.normalize(profile['name']).split():return False
 if 'edition' in actual and 'edition' not in specs.normalize(profile['name']).split():return False
 expected=set(re.findall(r'\b\d{3}-\d{6}\b',' '.join([profile['name'],*profile.get('aliases',[])])))
 if expected and str(product.get('sku') or product.get('mpn') or '') not in expected:return False
 aliases=[profile['name'],*profile.get('aliases',[])]
 # Exact token subsets: P2422H doesn't match P2422HE; left/large/business
 # variants don't collapse into the generic M650 retail product.
 stop={'inch','inches','consumer','monitor','mouse','wireless','the','revision','serial','bidirectional','cable'}
 for a in aliases:
  wanted=set(specs.normalize(a).split())-stop
  if len(wanted)>=2 and wanted<=actual:return True
 return False

def parse(doc,profile):
 out=[];host=urlsplit(doc['url']).hostname;now=doc['observed_at'];linked={}
 for root in doc['jsonld']:
  for node in objects(root):
   values=node.get('offers',[]);values=[values] if isinstance(values,dict) else values
   for v in values if isinstance(values,list) else []:
    if isinstance(v,dict) and is_type(v,'Offer') and v.get('@id') and v.get('price') is not None:linked.setdefault(v['@id'],[]).append(v)

 for root in doc['jsonld']:
  for p in objects(root):
   if not is_type(p,'Product'):continue
   variants=p.get('model',[])
   if isinstance(variants,list):
    for child in variants:
     if isinstance(child,dict) and is_type(child,'ProductModel'):
      wrapped={**child,'@type':'Product','brand':p.get('brand'),'itemCondition':child.get('itemCondition',p.get('itemCondition')),'url':p.get('url',doc['url'])};offers_doc={**doc,'jsonld':[wrapped]};out.extend(parse(offers_doc,profile))
   if not identity(p,profile):continue
   offers=p.get('offers',[]);offers=[offers] if isinstance(offers,dict) else offers
   if not isinstance(offers,list):continue
   for v in offers[:20]:
    if isinstance(v,dict) and v.get('price') is None and v.get('@id') in linked:
     candidates=linked[v['@id']]
     if len({(str(x.get('price')),x.get('priceCurrency'),x.get('availability')) for x in candidates})==1:v={**candidates[0],**v}
    if not isinstance(v,dict) or not is_type(v,'Offer') or v.get('price') is None:continue
    if not isinstance(v.get('priceCurrency'),str) or not pycountry.currencies.get(alpha_3=v['priceCurrency']):continue
    try:
     if v.get('priceValidUntil') and datetime.fromisoformat(v['priceValidUntil'].replace('Z','+00:00')).date()<datetime.fromtimestamp(now,timezone.utc).date():continue
     if v.get('validFrom'):
      start=datetime.fromisoformat(v['validFrom'].replace('Z','+00:00'));start=start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
      if start.timestamp()>now:continue
    except (ValueError,TypeError,AttributeError):continue
    condition=v.get('itemCondition') or p.get('itemCondition')
    if condition not in ('NewCondition','https://schema.org/NewCondition','http://schema.org/NewCondition'):continue
    if v.get('eligibleCustomerType') or v.get('validForMemberTier') or (isinstance(v.get('seller'),dict) and v['seller'].get('@type')=='AggregateOffer'):continue
    try:price=money(v['price'])
    except ValueError:continue
    availability=str(v.get('availability','')).rsplit('/',1)[-1]
    stock='in_stock' if availability=='InStock' else 'out_of_stock' if availability in ('OutOfStock','SoldOut','Discontinued','BackOrder','PreOrder') else 'unknown'
    seller=v.get('seller',{});seller=seller.get('name','') if isinstance(seller,dict) else str(seller)
    url=urljoin(doc['url'],v.get('url',''))
    if not allowed(url) or urlsplit(url).hostname!=host:continue
    out.append({'id':specs.digest({'source':doc['sha256'],'offer':v,'profile':profile['digest']})[:32],'device_id':profile['id'],'device_digest':profile['digest'],'name':p.get('name',profile['name']),'variant':str(p.get('sku') or p.get('mpn') or v.get('sku') or 'Exact page variant'),'seller':seller or host,'merchant':host,'unit_minor':price,'currency':v['priceCurrency'],'market_country':market_country(doc['url']),'stock':stock,'confirmed_quantity':1 if stock=='in_stock' else 0,'url':url,'observed_at':now,'expires_at':now+900,'source_sha256':doc['sha256'],'source_url':doc['url'],'evidence':{'price':str(v['price'])+' '+v['priceCurrency'],'availability':availability,'identity':str(p.get('name','')),'sku':str(p.get('sku') or p.get('mpn') or '')},'shopify_variant_id':int(parse_qs(urlsplit(url).query).get('variant',['0'])[0]) if parse_qs(urlsplit(url).query).get('variant',['0'])[0].isdigit() else None,'shopify':bool('cdn.shopify.com' in doc['html']),'shipping_details':v.get('shippingDetails'),'shipping_policy':shipping_policy(doc),'tax_included':bool(included_policy(doc)) or isinstance(v.get('priceSpecification'),dict) and v['priceSpecification'].get('valueAddedTaxIncluded') is True,'included_charges':included_policy(doc),'scope':'Observed public exact-product offer, not reserved stock or final checkout.'})
 return out[:8]

def included_policy(doc):
 text=' '.join(doc['text'].split())
 m=re.search(r'\b(?:all\s+)?prices\s+include\s+(?:all\s+)?(?:applicable\s+)?taxes,\s*duties\s*(?:,?\s*and|&)\s*(?:other\s+)?fees\b',text,re.I)
 if not m:return None
 country=market_country(doc['url'])
 return {'quote':m[0],'country':country,'source_url':doc['url'],'source_sha256':doc['sha256']} if country else None

def market_country(url):
 m=re.search(r'/[a-z]{2}-([a-z]{2})(?:/|$)',url,re.I)
 if m:return m[1].upper()
 return 'US' if urlsplit(url).hostname in ('plugable.com','www.plugable.com') else None

def shipping_policy(doc):
 text=' '.join(doc['text'].split());host=urlsplit(doc['url']).hostname
 # Generic thresholds need the US storefront context; no other merchant's
 # basket or account/member promotion can satisfy this threshold.
 country=market_country(doc['url']);us=bool(country)
 m=re.search(r'free\s+(?:standard\s+)?shipping\s*(?:\([^)]{0,80}\)\s*)?on\s+all\s+orders\b',text,re.I)
 if us and m:return {'kind':'store_all_orders','country':country,'threshold_minor':0,'inclusive':True,'source_url':doc['url'],'quote':m[0],'source_sha256':doc['sha256']}
 m=re.search(r'free\s+(?:(?:standard|ground|3-Day|2-Day)\s+)?(?:Continental\s+U\.?S\.?\s+)?shipping\s+(?:\([^)]{0,80}\)\s*)?(?:on\s+)?(?:all\s+)?orders\s+(over|of|above|from|at least)\s*\$\s*(\d+(?:\.\d{1,2})?)(\s*(?:and\s+above|or\s+more|and\s+over))?',text,re.I)
 if us and m:return {'kind':'threshold','country':country,'threshold_minor':money(m[2]),'inclusive':bool(m[3]) or m[1].lower() in ('of','from','at least'),'source_url':doc['url'],'quote':m[0],'source_sha256':doc['sha256']}
 m=re.search(r'free\s+(?:(?:standard|ground|3-Day|2-Day)\s+)?(?:Continental\s+U\.?S\.?\s+)?shipping\s+(?:on\s+)?(?:all\s+)?(?:orders\s+)?(?:to|within|in)\s+(?:the\s+)?(?:contiguous|continental|lower\s*48)\s+(?:U\.?S\.?|United States)',text,re.I)
 if m:return {'kind':'contiguous_us_free','country':'US','threshold_minor':0,'inclusive':True,'source_url':doc['url'],'quote':m[0],'source_sha256':doc['sha256']}
 return None

def discover(profile,on_event=lambda *a,**k:None,country=None,currency="USD"):
 query=profile['name'].split(' — ')[0];results=[];errors=[]
 for name,url in [('DuckDuckGo Lite','https://lite.duckduckgo.com/lite/?q='+quote_plus(query+' buy price '+currency+(' '+country if country else ''))),('Bing RSS','https://www.bing.com/search?q='+quote_plus('"'+query+'" buy price '+currency+(' '+country if country else ''))+'&format=rss&count=10')]:
  on_event('offer_search',query=query,provider=name)
  try:
   text=discovery.search_bytes(url)
   if name=='Bing RSS':
    import xml.etree.ElementTree as ET
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('Unsupported XML declarations.')
    rows=[{'url':x.findtext('link') or '', 'title':x.findtext('title') or ''} for x in ET.fromstring(text).findall('.//item')]
   else:parser=discovery.Links();parser.feed(text);rows=parser.rows
   model_terms={t for t in specs.normalize(query).split() if re.search(r'\d',t) and len(t)>=2}
   words=set(specs.normalize(query).split())-{'inch','monitor','for','business','medium','right','handed','wireless','revision','serial','with','stand','black','graphite'}
   for row in rows:
    link=discovery.decode_link(row['url']);hay=set(specs.normalize(row['title']+' '+unquote(urlsplit(link).path)).split())
    if allowed(link) and model_terms<=hay and len(words&hay)/max(1,len(words))>=.6 and not any(v in link for v in ('/compare/','/replacement_for/','/search','/login','/cart')):results.append({'url':link,'title':row['title']})
   if results:return {'results':results[:3],'errors':errors}
  except (ValueError,OSError) as exc:errors.append(name+': '+str(exc))
 return {'results':[],'errors':errors}

class AnonymousShopify:
 """A new cookie jar for one public shipping quote. Never browser/account
 cookies. Only fixed cart/rate paths, no checkout/order/payment endpoint.
 """
 def __init__(self,origin,on_request=lambda *a:None):
  p=urlsplit(origin)
  if not allowed(origin) or p.path not in ('','/'):raise Unavailable('Use an approved store origin.')
  self.origin=p.scheme+'://'+p.hostname;self.host=p.hostname;self.cookies={};self.on_request=on_request
 def call(self,path,body=None):
  p=urlsplit(path)
  allowed_paths=('/cart.js','/cart/add.js','/cart/clear.js','/cart/shipping_rates.json')
  if p.scheme or p.netloc or p.path not in allowed_paths or p.fragment:raise Unavailable('Only public cart shipping-quote paths are permitted.')
  if body is not None and p.path not in ('/cart/add.js','/cart/clear.js'):raise Unavailable('Unsupported public cart operation.')
  self.on_request(self.origin+path)
  try:ips=list(dict.fromkeys(v[4][0] for v in socket.getaddrinfo(self.host,443,type=socket.SOCK_STREAM)))
  except OSError:raise Unavailable('Store DNS unavailable.') from None
  if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):raise Unavailable('Non-public store destination blocked.')
  conn=specs.PublicHTTPS(self.host,ips[0]);conn.timeout=10
  headers={'User-Agent':'IntentCart-PublicShippingQuote/1.0','Accept':'application/json','Accept-Encoding':'identity','Connection':'close'}
  if self.cookies:headers['Cookie']='; '.join(k+'='+v for k,v in self.cookies.items())
  raw_body=None
  if body is not None:headers['Content-Type']='application/json';raw_body=json.dumps(body,separators=(',',':')).encode()
  try:
   conn.request('POST' if body is not None else 'GET',path,body=raw_body,headers=headers);r=conn.getresponse()
   if r.status!=200:raise Unavailable('Public shipping quote HTTP'+str(r.status)+'. No checkout was attempted.')
   if r.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise Unavailable('Unsupported quote encoding.')
   raw=r.read(1_000_001)
   if len(raw)>1_000_000:raise Unavailable('Shipping quote too large.')
   from http.cookies import SimpleCookie
   for key,value in r.getheaders():
    if key.lower()=='set-cookie':
     jar=SimpleCookie();jar.load(value)
     for name,m in jar.items():
      domain=m['domain'].lstrip('.')
      if domain and self.host!=domain and not self.host.endswith('.'+domain):continue
      if re.fullmatch(r'[\w-]{1,100}',name) and re.fullmatch(r'[\w%:.~+/_=-]{0,1500}',m.value):self.cookies[name]=m.value
   return json.loads(raw)
  except (OSError,ValueError,http.client.HTTPException) as exc:raise Unavailable('Public shipping quote could not be verified.') from exc
  finally:conn.close()
 def quote(self,lines,destination):
  from urllib.parse import urlencode
  params=urlencode({'shipping_address[zip]':destination['postal'],'shipping_address[country]':destination['country_name'],'shipping_address[province]':destination['region_name']})
  callback=self.on_request
  for path in ('/cart.js','/cart/add.js','/cart/shipping_rates.json?'+params,'/cart/clear.js'):callback(self.origin+path)
  self.on_request=lambda *a:None
  try:return self._quote(lines,destination)
  finally:self.on_request=callback;self.cookies.clear()
 def _quote(self,lines,destination):
  from urllib.parse import urlencode
  cart=self.call('/cart.js')
  if cart.get('currency')!=getattr(self,'currency','USD') or cart.get('items') or cart.get('item_count',0)!=0:raise Unavailable('A fresh empty matching-currency cart was not established. Nothing was added.')
  if not lines or len(lines)>12 or any(not isinstance(i['variant_id'],int) or i['variant_id']<=0 or not 1<=i['quantity']<=4 for i in lines):raise Unavailable('Invalid exact-variant quote lines.')
  changed=False
  try:
   changed=True;added=self.call('/cart/add.js',{'items':[{'id':i['variant_id'],'quantity':i['quantity']} for i in lines]})
   items=added.get('items',[]);wanted=sorted((i['variant_id'],i['quantity'],i['unit_minor']*i['quantity']) for i in lines)
   observed=sorted((int(i.get('variant_id',i.get('id',0))),i.get('quantity'),i.get('final_line_price',i.get('line_price'))) for i in items)
   if wanted!=observed:raise Unavailable('The store changed a variant, quantity or price. Recheck before using a quote.')
   params=urlencode({'shipping_address[zip]':destination['postal'],'shipping_address[country]':destination['country_name'],'shipping_address[province]':destination['region_name']})
   result=self.call('/cart/shipping_rates.json?'+params);rates=[]
   for v in result.get('shipping_rates',[]):
    try:amount=money(v['price'])
    except (ValueError,KeyError):continue
    if v.get('currency') not in (None,'',cart['currency']):continue
    name=str(v.get('name',''))
    if not name or re.search(r'pickup|collect|member|subscription',name,re.I):continue
    rates.append({'amount_minor':amount,'service':name,'source':'Store-generated anonymous shipping rate','response_sha256':specs.digest(result),'observed_at':int(time.time()),'destination':{k:destination[k] for k in ('country','region','postal')}})
   if not rates:raise Unavailable('No public delivery rate was returned for this destination.')
   return min(rates,key=lambda v:(v['amount_minor'],v['service']))
  finally:
   if changed:
    try:
     try:cleared=self.call('/cart/clear.js',{})
     except Exception:raise QuoteCleanupError('Anonymous quote cart cleanup could not be verified.') from None
     if cleared.get('item_count',0)!=0:raise QuoteCleanupError('Anonymous quote cart cleanup was not confirmed.')
    finally:self.cookies.clear()
