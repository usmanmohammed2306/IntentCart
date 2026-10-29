"""Free public-manufacturer research. Explicit consent, bounded reads, pinned public DNS.
The model never receives remote instructions. Documents are data, not authority.
"""
from __future__ import annotations
import hashlib,http.client,ipaddress,json,re,socket,ssl,time,unicodedata
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit,urljoin
ROOT=Path(__file__).parent
ROOTS=('apple.com','dell.com','delltechnologies.com','logitech.com','logi.com','plugable.com','lenovo.com','hp.com','microsoft.com','samsung.com','lg.com','asus.com','acer.com','benq.com','caldigit.com','ikea.com','upliftdesk.com','flexispot.com','frame.work','razer.com','corsair.com','steelseries.com','keychron.com','msi.com','gigabyte.com','aoc.com','viewsonic.com','philips.com','autonomous.ai','secretlab.co','system76.com','tuxedocomputers.com','huawei.com','honor.com','elgato.com','jabra.com','satechi.net','satechi.com','anker.com','logitechg.com')
MAX_BYTES=1_500_000
class ResearchError(ValueError):pass

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
def normalize(value):return ' '.join(re.findall(r'[a-z0-9]+',unicodedata.normalize('NFKC',value).lower()))
def catalog():
 data=json.loads((ROOT/'data/device-library.json').read_text())
 for device in data['devices']:device['digest']=digest(device)
 return data['devices']
def lookup(query,kind='',extra=()):
 query=normalize(query);tokens=set(query.split());rows=[]
 if not query:return []
 for d in list(catalog())+list(extra):
  if kind and d.get('kind')!=kind:continue
  names=[normalize(d['name']),normalize(d['id']),*[normalize(a) for a in d.get('aliases',[])]]
  exact=query in names;overlap=max((len(tokens&set(n.split()))/max(1,len(tokens)) for n in names),default=0)
  if exact or overlap>=.75:rows.append((int(exact),overlap,d))
 rows.sort(key=lambda x:(-x[0],-x[1],x[2]['id']))
 return [{**d,'match':'exact_alias' if exact else 'candidate','identity_confirmed':False} for exact,_,d in rows[:12]]
def get(device_id,extra=()):
 for d in list(catalog())+list(extra):
  if d['id']==device_id:return d
 raise ResearchError('Unknown device identifier. Research and review the exact variant first.')

def checked_url(url):
 try:p=urlsplit(url);port=p.port
 except ValueError:raise ResearchError('Invalid public source URL.') from None
 host=(p.hostname or '').lower().rstrip('.')
 if re.search(r'(?:^|[&])(?:token|api_key|password|secret|session|auth)=',p.query,re.I):raise ResearchError('Credential-bearing URLs are not public specifications.')
 if p.scheme!='https' or p.username or p.password or port not in (None,443) or p.fragment or len(url)>1500 or not any(host==r or host.endswith('.'+r) for r in ROOTS):raise ResearchError('Use a direct HTTPS page on a supported manufacturer domain, without login details or a fragment.')
 try:addresses=list(dict.fromkeys(a[4][0] for a in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
 except OSError:raise ResearchError('Manufacturer DNS is unavailable. Your workspace is unchanged.') from None
 if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise ResearchError('Non-public or mixed DNS destinations are blocked.')
 return p,host,addresses
class PublicHTTPS(http.client.HTTPSConnection):
 def __init__(self,host,ip):super().__init__(host,timeout=8,context=ssl.create_default_context());self.public_ip=ip
 def connect(self):
  sock=socket.create_connection((self.public_ip,443),timeout=self.timeout)
  try:self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
  except BaseException:sock.close();raise
class Text(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.ignore=0
 def handle_starttag(self,tag,attrs):
  if tag in ('script','style','noscript','svg'):self.ignore+=1
  elif tag in ('p','br','div','tr','td','th','h1','h2','h3','li'):self.parts.append('\n')
 def handle_endtag(self,tag):
  if tag in ('script','style','noscript','svg'):self.ignore=max(0,self.ignore-1)
 def handle_data(self,data):
  if not self.ignore:self.parts.append(data)

def fetch(url,*,consent=False):
 if not consent:raise ResearchError('Public source research requires explicit consent. Only the source URL is sent; not your workspace or account.')
 started=time.monotonic();redirects=[]
 for _ in range(4):
  if time.monotonic()-started>25:raise ResearchError('Public research timed out. Try again later or use recorded facts.')
  p,host,ips=checked_url(url);conn=PublicHTTPS(host,ips[0])
  try:
   conn.request('GET',(p.path or '/')+('?' +p.query if p.query else ''),headers={'User-Agent':'IntentCart-SpecReader/1.0','Accept':'text/html,application/pdf,text/plain','Accept-Encoding':'identity','Connection':'close'})
   response=conn.getresponse()
   if response.status in (301,302,303,307,308):
    location=response.getheader('Location','');url=urljoin(url,location);redirects.append(url);continue
   if response.status!=200:raise ResearchError('Manufacturer returned HTTP '+str(response.status)+'. No facts were accepted.')
   if response.getheader('Content-Encoding','identity').lower() not in ('','identity'):raise ResearchError('Compressed remote responses are not accepted by this bounded reader.')
   raw=bytearray()
   while True:
    if time.monotonic()-started>25:raise ResearchError('Public research exceeded its time limit.')
    block=response.read(min(65536,MAX_BYTES+1-len(raw)))
    if not block:break
    raw.extend(block)
    if len(raw)>MAX_BYTES:raise ResearchError('Source exceeded 1.5 MB. Use a shorter official specification page.')
   content=response.getheader('Content-Type','').split(';')[0].lower()
  except (OSError,ssl.SSLError,http.client.HTTPException) as exc:raise ResearchError('Could not securely read this manufacturer source. No facts were accepted.') from exc
  finally:conn.close()
  raw=bytes(raw)
  if content=='application/pdf' or raw.startswith(b'%PDF-'):
   from .documents import extract
   text='\n'.join(p['text'] for p in extract(raw,'.pdf',specification=True)['pages']);method='Bounded public PDF excerpt: first40 pages scanned, up to8 relevant pages/40000 characters retained; network-disabled parser'
  elif content in ('text/html','application/xhtml+xml','text/plain'):
   decoded=raw.decode('utf-8',errors='replace')
   if content=='text/plain':text=decoded
   else:
    parser=Text();parser.feed(decoded);text=''.join(parser.parts)
   text=re.sub(r'[ \t]+',' ',text);text=re.sub(r'\n\s*\n+','\n',text).strip()[:80000];method='Text-only HTML parsing; no scripts or external assets'
  else:raise ResearchError('Use a text-based manufacturer page or PDF.')
  return {'id':hashlib.sha256(raw).hexdigest(),'url':url,'retrieved_on':date.today().isoformat(),'text':text,'bytes':len(raw),'method':method,'redirects':redirects,'authority':'Observed manufacturer document, not an accepted device specification until reviewed.'}
 raise ResearchError('Too many source redirects.')

def extract_candidates(source,identity):
 """Candidate fields with literal evidence. Ambiguous page/table axes need review."""
 text=source['text'];normalized=normalize(text);need=set(normalize(identity).split())
 matched=bool(need) and need<=set(normalized.split())
 fields=[]
 # Extract evidence lines, not executable instructions or unsourced LLM facts.
 for line in text.splitlines():
  line=line.strip()
  if not line or len(line)>600:continue
  for key in ('width','depth','height','weight'):
   if re.search(r'\b'+key+r'\b',line,re.I) and re.search(r'\d\s*(mm|cm|inch|in\b|kg|g\b)',line,re.I):fields.append({'field':key,'evidence':line[:250],'needs_axis_and_configuration_review':True})
  if len(fields)>=24:break
 return {'identity_terms_present':matched,'candidates':fields[:24],'notice':'Review exact model/year/revision, table row, units, packaging versus item size and operating state. No field is automatically accepted.'}

def review(source,body):
 if not extract_candidates(source,body.identity if hasattr(body,'identity') else body.name)['identity_terms_present']:raise ResearchError('The document does not contain all selected identity terms. Choose the exact variant or another source.')
 permitted={'width_mm','depth_mm','height_mm','weight_g','native_displays','max_height','max_hz','video_out_hdmi','video_out_dp','video_out_usb_c','video_in_hdmi','video_in_dp','bluetooth','usb_a','usb_c','driver_required','displays','mount','handedness','noise_claim','camera_height','voltage_min','voltage_max','requires_software'}
 fields={};evidence={};text=' '.join(source['text'].split())
 for key,value in body.fields.items():
  if key not in permitted:raise ResearchError('Unsupported fact field.')
  quote=body.evidence.get(key,'').strip()
  if not 1<=len(quote)<=300 or ' '.join(quote.split()) not in text:raise ResearchError('Every fact needs an exact, short quotation from the retrieved document.')
  if isinstance(value,str) and len(value)>160:raise ResearchError('Fact value too long.')
  if isinstance(value,(int,float)) and not isinstance(value,bool):
   if value<0 or value>100000:raise ResearchError('Fact value outside supported bounds.')
   # Numeric transformations must be directly checkable from the quoted text.
   nums=[float(x) for x in re.findall(r'\d+(?:\.\d+)?',quote)]
   factors=[1]
   if key.endswith('_mm'):
    if re.search(r'\bcm\b',quote,re.I):factors.append(10)
    if re.search(r'\binches?\b|\bin\b',quote,re.I):factors.append(25.4)
   if key=='weight_g' and re.search(r'\bkg\b',quote,re.I):factors.append(1000)
   word_count=re.search(r'\b(one|two|three|four)\s+external\s+(?:displays?|monitors?)\b',quote,re.I) if key=='native_displays' else None
   literal_count={'one':1,'two':2,'three':3,'four':4}.get(word_count.group(1).lower()) if word_count else None
   if not any(abs(n*f-value)<.051 for n in nums for f in factors) and literal_count!=value:raise ResearchError('Numeric fact is not supported by its quotation and units.')
  fields[key]=value;evidence[key]=quote
 if not fields:raise ResearchError('Choose at least one fact.')
 result={'id':body.device_id,'name':body.name,'kind':body.kind,'aliases':[],'reviewed_on':source['retrieved_on'],'sources':[{'url':source['url'],'document_sha256':source['id'],'retrieved_on':source['retrieved_on']}],'configurations':{body.configuration:fields},'field_evidence':evidence,'authority':'User-reviewed source extraction, not independently certified'};result['digest']=digest(result);return result
