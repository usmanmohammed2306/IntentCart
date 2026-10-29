"""Private subprocess for rendering one approved anonymous Satechi checkout.
No completion calls, payment fields, user storage, downloads or external profiles.
"""
import ipaddress,json,re,socket,sys,time
from urllib.parse import urlsplit
HOSTS={'satechi.com','satechi.myshopify.com','cdn.shopify.com','checkout.shopify.com','extensions.shopifycdn.com','fonts.shopifycdn.com','checkout.pci.shopifyinc.com'}

def allowed_request(url,method,kind,post=''):
 p=urlsplit(url)
 if p.scheme!='https' or p.hostname not in HOSTS or p.port not in (None,443) or p.username or p.password or method not in ('GET','HEAD','POST') or kind in ('image','media','font'):return False
 if p.hostname=='checkout.pci.shopifyinc.com' and method!='GET':return False
 if re.search(r'/(?:payments|orders|complete)(?:/|$)',p.path,re.I):return False
 if method=='POST':
  try:body=json.loads(post);operation=str(body.get('operationName') or '');query=str(body.get('query') or '')
  except (ValueError,AttributeError):operation='';query=post
  action=r'(?:completeCheckout|submitForCompletion|checkoutComplete|paymentSessionCreate|processPayment|orderCreate)'
  if re.search(action+r'|^Completion$|^Submit$',operation,re.I):return False
  # A misleading operationName cannot conceal a financial mutation in a query.
  query=re.sub(r'"(?:[^"\\]|\\.)*"','""',query)
  if re.search(r'\b'+action+r'\s*(?:\(|\{)',query,re.I):return False
 return True

def main(data):
 if not isinstance(data,dict) or not {'url','address','destination'}<=data.keys():raise ValueError('Missing bounded input')
 from playwright.sync_api import sync_playwright
 phase='launch';stats={'resource_requests':0,'blocked_requests':0,'declared_response_bytes':0};hosts={};blocked_hosts=set();blocked_details=[];browser_errors=[];failures=[];started=time.monotonic()
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True)
  try:
   context=browser.new_context(accept_downloads=False,service_workers='block',locale='en-US',viewport={'width':1280,'height':900})
   def route(r):
    if failures:return r.abort()
    req=r.request;p=urlsplit(req.url)
    if stats['resource_requests']>=400 or time.monotonic()-started>30:failures.append('resource_limit');return r.abort()
    # No payment submission, tracking, local-network fetch, or third-party login.
    post=req.post_data or '';operation=''
    if req.method=='POST':
     try:operation=str(json.loads(post).get('operationName') or '')[:160]
     except (ValueError,AttributeError):pass
    if not allowed_request(req.url,req.method,req.resource_type,post):
     stats['blocked_requests']+=1;blocked_hosts.add(p.hostname or '')
     if len(blocked_details)<20 and req.resource_type not in ('image','font','media'):blocked_details.append({'host':p.hostname,'method':req.method,'type':req.resource_type,'operation':operation[:80],'path_category':'/'.join(p.path.split('/')[:3]) if not p.path.startswith(('/checkouts/cn/','/cart/c/')) else '/private-cart'})
     return r.abort()
    if p.hostname not in hosts:
     try:hosts[p.hostname]=all(ipaddress.ip_address(v[4][0]).is_global for v in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM))
     except OSError:hosts[p.hostname]=False
    if not hosts[p.hostname]:failures.append('public_network');return r.abort()
    stats['resource_requests']+=1;return r.continue_()
   def response(r):
    try:stats['declared_response_bytes']+=int(r.headers.get('content-length','0'))
    except (ValueError,TypeError):pass
    if stats['declared_response_bytes']>50000000:failures.append('response_limit')
    if r.status in (403,429):
     failures.append('store_access')
     if r.status==429:stats['retry_after']=str(r.headers.get('retry-after','300'))[:80]
   context.route('**/*',route);page=context.new_page();page.on('response',response);page.on('pageerror',lambda error:browser_errors.append(re.sub(r'https?://[^\s]+','[url]',str(error))[:220]) if len(browser_errors)<4 else None);page.set_default_timeout(7000);page.set_default_navigation_timeout(18000)
   phase='open_store';page.goto(data['url'],wait_until='domcontentloaded')
   phase='delivery.country';country=page.get_by_role('combobox',name='Country/Region',exact=True).first
   if country.count()==0:
    # A continuation can show the merchant cart first; only its non-payment
    # checkout-navigation action is eligible. Never click Buy/Pay/Submit.
    phase='cart_navigation';next_step=page.get_by_role('button',name=re.compile(r'^Check ?out$',re.I))
    if next_step.count()==0:next_step=page.get_by_role('link',name=re.compile(r'^Check ?out$',re.I))
    if next_step.count()==1 and next_step.is_visible():next_step.click()
    phase='delivery.country'
   if country.input_value()!='US':country.select_option('US')
   fields=[(page.locator('#shipping-address1'),data['address']['address1']),(page.get_by_role('textbox',name='City',exact=True).first,data['address']['city']),(page.get_by_role('textbox',name='ZIP code',exact=True).first,data['destination']['postal'])]
   for n,(field,value) in enumerate(fields):
    phase='delivery.'+['street','city','postal'][n]
    if field.input_value()!=value:field.fill(value)
   phase='delivery.region';state=page.get_by_role('combobox',name='State',exact=True).first
   if state.input_value()!=data['destination']['region']:state.select_option(data['destination']['region'])
   fields[-1][0].press('Tab')
   phase='calculate';summary=page.get_by_role('table',name='Cost summary',exact=True);previous=None;stable=0
   # Allow the merchant's asynchronous tax/rate calculation to settle. These
   # are bounded DOM reads, not retries or new cart requests.
   for _ in range(14):
    page.wait_for_timeout(500)
    if failures:raise ValueError(failures[0])
    text=summary.inner_text()
    if text==previous:stable+=1
    else:stable=0
    previous=text
    if stable>=5 and re.search(r'\bTotal\b',text):break
   else:raise ValueError('Unsettled merchant total')
   values=[field.input_value() for field,_ in fields];matches=values==[v for _,v in fields] and state.input_value()==data['destination']['region'] and country.input_value()=='US'
   phase='read_result';result={**stats,'address_matches':matches,'summary':text[:12000],'summary_rows':summary.get_by_role('row').all_inner_texts(),'cart_rows':page.get_by_role('table',name='Shopping cart',exact=True).inner_text()[:12000],'hostnames':sorted(hosts),'elapsed_ms':int((time.monotonic()-started)*1000)}
   context.close();return result
  except Exception as exc:
   try:heading=page.locator('h1').filter(visible=True).all_text_contents()[:2];title=page.title()[:100]
   except Exception:heading=[];title=''
   return {'error':True,'phase':phase,'exception_type':type(exc).__name__,'country_matches':page.get_by_label('Country/Region',exact=True).count(),'country_visible_matches':page.get_by_role('combobox',name='Country/Region',exact=True).count(),'page_title':title,'headings':heading,'hostnames':sorted(hosts),'blocked_hosts':sorted(blocked_hosts)[:20],'blocked_details':blocked_details,'browser_errors':browser_errors,'failures':failures[:6],**stats}
  finally:browser.close()
if __name__=='__main__':
 try:
  raw=sys.stdin.read(20001)
  if len(raw)>20000:raise ValueError('Bound')
  result=main(json.loads(raw));print(json.dumps(result));sys.exit(1 if result.get('error') else 0)
 except Exception:print(json.dumps({'error':True,'phase':'runtime'}));sys.exit(1)
