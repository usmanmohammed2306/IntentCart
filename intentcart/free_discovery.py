"""Bounded, keyless public search and literal manufacturer-spec extraction.
Search snippets discover URLs only. Only exact official documents yield proposals.
No CAPTCHA bypass, account cookies, script execution, paid APIs or guessed URLs.
"""
from __future__ import annotations
import re,socket,ipaddress,time,html,xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlsplit,parse_qs,unquote,quote_plus
from . import device_research as source

BRANDS={
 'apple':'apple.com','dell':'dell.com','alienware':'dell.com','lenovo':'lenovo.com','thinkpad':'lenovo.com','hp':'hp.com','hewlett packard':'hp.com','logitech':'logitech.com','logi':'logitech.com','plugable':'plugable.com','samsung':'samsung.com','lg':'lg.com','asus':'asus.com','acer':'acer.com','benq':'benq.com','microsoft':'microsoft.com','surface':'microsoft.com','caldigit':'caldigit.com','ikea':'ikea.com','uplift':'upliftdesk.com','flexispot':'flexispot.com','framework':'frame.work','razer':'razer.com','corsair':'corsair.com','steelseries':'steelseries.com','keychron':'keychron.com','msi':'msi.com','gigabyte':'gigabyte.com','aoc':'aoc.com','viewsonic':'viewsonic.com','philips':'philips.com','autonomous':'autonomous.ai','secretlab':'secretlab.co','system76':'system76.com','tuxedo':'tuxedocomputers.com','huawei':'huawei.com','honor':'honor.com','elgato':'elgato.com','jabra':'jabra.com','satechi':'satechi.net','anker':'anker.com'}
OFFICIAL=tuple(dict.fromkeys(source.ROOTS+tuple(BRANDS.values())+('logitechg.com',)))
SEARCH_HOSTS=('lite.duckduckgo.com','www.bing.com')
class DiscoveryError(ValueError):pass

def validate_query(query):
 q=' '.join(query.split())
 if not 2<=len(q)<=120 or not re.fullmatch(r"[\w .()+/,'\"×–−-]+",q) or re.search(r'(?i)https?|password|api.?key|secret|token|@|(?:\d[ -]?){9,}',q):raise DiscoveryError('Enter only a public product model, up to 120 characters. Leave account details and links out.')
 return q

def official(url):
 try:
  p=urlsplit(url);host=(p.hostname or '').lower().rstrip('.')
  return p.scheme=='https' and not p.username and not p.password and p.port in (None,443) and not p.fragment and len(url)<=1500 and any(host==r or host.endswith('.'+r) for r in OFFICIAL)
 except ValueError:return False

def search_bytes(url):
 p=urlsplit(url);host=p.hostname
 if host not in SEARCH_HOSTS or p.scheme!='https' or p.username or p.password or p.port not in (None,443):raise DiscoveryError('Unapproved search destination.')
 try:ips=list(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
 except OSError:raise DiscoveryError('Search DNS is unavailable.') from None
 if not ips or any(not ipaddress.ip_address(v).is_global for v in ips):raise DiscoveryError('Non-public search destination blocked.')
 conn=source.PublicHTTPS(host,ips[0]);conn.timeout=10
 try:
  conn.request('GET',p.path+'?'+p.query,headers={'User-Agent':'Mozilla/5.0 (compatible; IntentCart-SpecDiscovery/1.0)','Accept':'text/html,application/rss+xml','Accept-Encoding':'identity','Connection':'close'})
  r=conn.getresponse()
  if r.status!=200:raise DiscoveryError('Search unavailable (HTTP '+str(r.status)+'). No challenge or rate limit is bypassed.')
  if r.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise DiscoveryError('Unsupported search response encoding.')
  raw=r.read(700001)
  if len(raw)>700000:raise DiscoveryError('Search response exceeds its size limit.')
  text=raw.decode('utf8','replace')
  if any(k in text.lower() for k in ('anomaly.js','challenge-form','g-recaptcha','/sorry/')):raise DiscoveryError('Search presented a challenge; no bypass attempted.')
  return text
 except OSError as exc:raise DiscoveryError('Public search timed out or is unavailable.') from exc
 finally:conn.close()

class Links(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.rows=[];self.current=None
 def handle_starttag(self,tag,attrs):
  if tag=='a':self.current={'url':dict(attrs).get('href',''),'title':''}
 def handle_data(self,data):
  if self.current:self.current['title']+=data
 def handle_endtag(self,tag):
  if tag=='a' and self.current:self.rows.append(self.current);self.current=None

def decode_link(url):
 if url.startswith('//'):url='https:'+url
 p=urlsplit(url)
 if (p.hostname or '').endswith('duckduckgo.com'):
  value=parse_qs(p.query).get('uddg',[''])[0]
  if value:url=value
 return html.unescape(url).split('#')[0]

def rank_links(rows,query,kind):
 tokens=set(source.normalize(query).split());brand=next((r for b,r in BRANDS.items() if set(b.split())<=tokens),None)
 rows_out=[];seen=set()
 for row in rows:
  url=decode_link(row['url']);title=' '.join(row['title'].split())[:240]
  if not official(url) or url in seen:continue
  p=urlsplit(url)
  if brand and not (p.hostname==brand or p.hostname.endswith('.'+brand) or brand=='logitech.com' and p.hostname.endswith('logi.com')):continue
  hay=set(source.normalize(title+' '+unquote(p.path)).split());coverage=len(tokens&hay)/max(1,len(tokens))
  # At least one meaningful exact product term, beyond just a matching brand.
  product_tokens=tokens-set(BRANDS)-{'laptop','monitor','mouse','desk','desktop','specifications','technical','proart'}
  strong=[t for t in product_tokens if len(t)>2 and t in hay]
  if not strong or coverage<.65:continue
  score=coverage*10+int(any(x in url.lower() for x in ('techspec','specifications','specs','.pdf')))*2
  if any(x in url.lower() for x in ('/search','/category','/login','/cart')):continue
  seen.add(url);rows_out.append({'url':url,'title':title,'score':round(score,3),'identity_confirmed':False})
 rows_out.sort(key=lambda r:(-r['score'],r['url']))
 return rows_out[:6]

def discover(query,kind='',on_event=lambda *a:None):
 query=validate_query(query);errors=[];search_terms=query+(' PSREF' if any(t in source.normalize(query).split() for t in ('lenovo','thinkpad')) else '')
 endpoints=[('DuckDuckGo Lite','https://lite.duckduckgo.com/lite/?q='+quote_plus(search_terms+' technical specifications')),('Bing RSS','https://www.bing.com/search?q='+quote_plus('"'+search_terms+'"')+'&format=rss&count=10')]
 for name,url in endpoints:
  on_event('search',provider=name,query=query)
  try:
   text=search_bytes(url)
   if name=='Bing RSS':
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise DiscoveryError('Unsupported XML declarations.')
    rows=[{'url':i.findtext('link') or '', 'title':i.findtext('title') or ''} for i in ET.fromstring(text).findall('.//item')]
   else:parser=Links();parser.feed(text);rows=parser.rows
   ranked=rank_links(rows,query,kind)
   if ranked:return {'results':ranked,'search_provider':name,'errors':errors}
   errors.append(name+': no exact official result, rather than an unrelated brand home page.')
  except (ValueError,ET.ParseError,OSError) as exc:errors.append(name+': '+str(exc))
 return {'results':[],'search_provider':None,'errors':errors}

# Parse only unit-bearing literal facts; every retained value carries its quote.
NUMBER=r'(\d+(?:\.\d+)?)';UNIT=r'(mm|cm|inches|inch|in\b)'
def proposals(doc,query,kind):
 text=' '.join(doc['text'].split());query_tokens=set(source.normalize(query).split())
 # Missing model terms block unrelated or redirected generic support pages.
 identity=query_tokens<=set(source.normalize(text).split())
 if not identity:return []
 fields={};evidence={};conflicts=[];candidates={}
 def add(key,value,quote,confidence='literal'):
  if len(quote)>300:return
  if isinstance(value,(float,int)) and not isinstance(value,bool) and not 0<=float(value)<=100000:return
  prior=candidates.setdefault(key,[])
  if not any(r['value']==value and r['quote']==quote for r in prior):prior.append({'value':value,'quote':quote,'basis':confidence})
 scale=lambda unit:10 if unit.lower()=='cm' else 25.4 if unit.lower().startswith('in') else 1
 # Three-axis rows retain axis order and distinguish operating stand vs panel.
 triples=[]
 axis=r'(W|Width|L|Length)\s*[x×/]\s*(H|Height|D|Depth)\s*[x×/]\s*(D|Depth|H|Height)'
 pattern=re.compile(r'(?:dimensions?|size)[^:()]{0,90}\(\s*'+axis+r'\s*\)\s*[:：]?\s*'+NUMBER+r'\s*[x×]\s*'+NUMBER+r'\s*[x×]\s*'+NUMBER+r'\s*'+UNIT,re.I)
 for m in pattern.finditer(text):
  axes=m.groups()[:3];vals=m.groups()[3:6];unit=m.groups()[6];context=m.group(0);prefix=text[max(0,m.start()-18):m.start()];
  if re.search(r'box|shipping|packag|carton',prefix,re.I):continue
  label='with_stand' if re.search(r'with\s+(?:the\s+)?stand',context,re.I) and not re.search(r'without\s+(?:the\s+)?stand',context,re.I) else 'panel_only' if re.search(r'without\s+(?:the\s+)?stand',context,re.I) else 'closed' if kind=='laptop' else 'in_use'
  mapping={a[0].lower():round(float(v)*scale(unit),3) for a,v in zip(axes,vals)}
  if set(mapping)=={'w','h','d'}:triples.append((label,mapping,m.group(0)))
 chosen=next((t for t in triples if t[0]=='with_stand'),next(iter(triples),None))
 configuration=chosen[0] if chosen else 'in_use'
 if chosen:
  for short,key in [('w','width_mm'),('d','depth_mm'),('h','height_mm')]:add(key,chosen[1][short],chosen[2],'explicit_axis_row')
 # Restrict individual numeric rows to unambiguous single values. Stand-less
 # screen dimensions and ambiguous mouse H/W/D orientations stay unresolved.
 if not chosen:
  region=text
  for marker in ('Measurements','Technical specifications','Tech Specs','Dimensions'):
   index=text.find(marker)
   if index>=0:region=text[index:index+4500];break
  if kind in ('desk','mouse','laptop'):
   for label in ('Width','Depth','Height','Length'):
    matches=list(re.finditer(r'\b'+label+r'\s*[:：]?\s*'+NUMBER+r'\s*'+UNIT,region,re.I))
    if len({m.group(1)+m.group(2) for m in matches})==1 and matches:
     m=matches[0];key={'Width':'width_mm','Depth':'depth_mm','Height':'height_mm','Length':'length_mm'}[label];add(key,round(float(m.group(1))*scale(m.group(2)),3),m.group(0))
   if kind=='desk':
    configuration='usable_surface'
    if 'length_mm' in candidates and 'width_mm' in candidates and 'depth_mm' not in candidates:candidates['depth_mm']=candidates['width_mm'];candidates['width_mm']=candidates.pop('length_mm')
   elif kind=='laptop':configuration='closed'
   elif kind=='mouse':
    # "Height" often denotes mouse length in vendor diagrams. Require the
    # explicit Length/Width/Height scheme, otherwise omit geometry entirely.
    if 'length_mm' in candidates and 'width_mm' in candidates and 'height_mm' in candidates:candidates['depth_mm']=candidates.pop('length_mm')
    else:
     for key in ('width_mm','depth_mm','height_mm','length_mm'):candidates.pop(key,None)
  candidates.pop('length_mm',None)
 # Literal port/connection declarations. Counts and GPU modes are not inferred.
 if kind=='monitor':
  for label,key in [('DisplayPort','video_in_dp'),('HDMI','video_in_hdmi')]:
   m=re.search(r'\b'+label+r'(?:™)?(?:\s*\(v?\d(?:\.\d)?\)|\s*v?\d(?:\.\d)?)?\s*(?:[:：]?\s*[xX]\s*[1-4]|[:：]\s*(?:Yes|YES|1|2))\b',text)
   if m:add(key,True,m.group(0),'explicit_monitor_input_listing')
 if kind in ('mouse','keyboard','laptop'):
  m=re.search(r'\bBluetooth(?:®|™)?\s*(?:Low Energy|LE|Smart|\d(?:\.\d)?)',text,re.I)
  if m and not re.search(r'not|without|no ',text[max(0,m.start()-30):m.start()],re.I):add('bluetooth',True,m.group(0))
 if kind=='laptop':
  matches=re.finditer(r'\b(One|Two|Three|Four|[1-4])\s+external\s+(?:displays?|monitors?)\b',text,re.I)
  for m in matches:
   count={'one':1,'two':2,'three':3,'four':4}.get(m.group(1).lower(),int(m.group(1)) if m.group(1).isdigit() else 0)
   # The literal-review validator checks these exact external-display words.
   add('native_displays',count,m.group(0))
 for key,values in candidates.items():
  unique={str(v['value']) for v in values}
  if len(unique)==1:fields[key]=values[0]['value'];evidence[key]=values[0]['quote']
  else:conflicts.append({'field':key,'values':values})
 if not fields:return []
 # Laptops need an independent open-lid measurement in an operating setup.
 if kind=='laptop' and configuration=='closed' and not all(k in fields for k in ('width_mm','depth_mm','height_mm')):configuration='in_use'
 configurations=[(configuration,fields,evidence)]
 if kind=='laptop' and configuration=='closed':configurations.append(('in_use',{k:v for k,v in fields.items() if k not in ('width_mm','depth_mm','height_mm')},{k:v for k,v in evidence.items() if k not in ('width_mm','depth_mm','height_mm')}))
 return [{'name':query,'kind':'other' if kind=='desk' else kind,'configuration':cfg,'fields':fs,'evidence':ev,'conflicts':conflicts,'source_id':doc['id'],'source_url':doc['url'],'reviewed_on':doc['retrieved_on'],'needs_in_use_measurement':kind=='laptop' and cfg=='in_use','scope':'Automatically proposed literal specification facts. Confirm the exact model/variant/configuration; missing or conflicting facts remain unknown.'} for cfg,fs,ev in configurations if fs]
