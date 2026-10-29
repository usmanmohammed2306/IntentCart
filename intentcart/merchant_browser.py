"""Ephemeral merchant checkout renderer. No user browser, payment or login.
Only a server-created Satechi checkout may be rendered after address consent.
The parent independently validates the exact merchant response after rendering.
"""
import json,os,signal,subprocess,sys,tempfile
from pathlib import Path
from urllib.parse import urlsplit

class RenderError(ValueError):
 def __init__(self,value):
  self.diagnostic=value;super().__init__('Store calculation could not finish ('+str(value.get('phase','browser'))+'). No payment was attempted.')

def render(url,destination,address):
 p=urlsplit(url)
 if p.scheme!='https' or p.hostname not in ('satechi.com','satechi.myshopify.com') or p.port not in (None,443) or p.username or p.password or p.fragment or not p.path.startswith(('/cart/c/','/checkouts/')) or len(url)>2400:raise ValueError('Unrecognized Satechi checkout continuation.')
 if destination.country!='US':raise ValueError('Automatic Satechi checkout rendering currently supports US delivery; review imports at the store.')
 try:
  import playwright
 except ImportError:raise ValueError('Install the documented free merchant-browser runtime to calculate this store’s delivery.') from None
 allowed=('PATH','HOME','TMPDIR','SYSTEMROOT','WINDIR','PLAYWRIGHT_BROWSERS_PATH')
 env={k:v for k,v in os.environ.items() if k in allowed}
 env['PYTHONPATH']=os.pathsep.join([str(Path(__file__).parent.parent),str(Path(playwright.__file__).parent.parent)])
 request={'url':url,'address':address,'destination':destination.public()}
 if os.name!='posix':raise ValueError('The isolated merchant renderer currently requires macOS or Linux. Use the store checkout on this platform.')
 with tempfile.TemporaryDirectory(prefix='intentcart-merchant-') as merchant_temp:
  env['TMPDIR']=merchant_temp
  process=subprocess.Popen([sys.executable,'-m','intentcart.merchant_browser_worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,cwd=str(Path(__file__).parent.parent),start_new_session=True)
  try:stdout,_=process.communicate(json.dumps(request),timeout=38)
  except subprocess.TimeoutExpired:
   os.killpg(process.pid,signal.SIGKILL);process.communicate()
   raise ValueError('The store’s delivery calculation timed out. No payment was attempted.') from None
  except BaseException:
   if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.communicate()
   raise
 if len(stdout)>30000:raise ValueError('The merchant result exceeded its size bound.')
 try:value=json.loads(stdout)
 except (ValueError,TypeError):raise ValueError('The isolated store renderer did not return a valid estimate.') from None
 if value.get('retry_after'):
  from .retail_sources import RateLimited
  raise RateLimited(value['retry_after'])
 if process.returncode or value.get('error'):raise RenderError(value)
 if value.get('address_matches') is not True or type(value.get('resource_requests')) is not int:raise ValueError('The store did not confirm the selected delivery address.')
 return value


def displayed_total(rows,currency):
 import re
 from decimal import Decimal
 if currency!='USD' or not isinstance(rows,list) or len(rows)>12:raise ValueError('Unsupported displayed merchant currency.')
 matches=[]
 for row in rows:
  if re.match(r'^\s*Total\b',row,re.I) and not re.match(r'^\s*Total\s+savings',row,re.I):
   values=re.findall(r'\$([0-9,]+\.[0-9]{2})(?![0-9])',row)
   if currency not in row or len(values)!=1:raise ValueError('Displayed total or currency is ambiguous.')
   matches.append(int(Decimal(values[0].replace(',',''))*100))
 if len(matches)!=1:raise ValueError('No unique displayed merchant total.')
 return matches[0]
