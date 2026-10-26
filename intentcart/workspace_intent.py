"""Hash-bound trained CPU intent router and explicit-number tools. Never a paid fallback."""
import hashlib,json,re
from pathlib import Path
import numpy as np
from .trained_agent import ModelError
ROOT=Path(__file__).parent/'data/workspace-router'
_CACHE=None

def features(text,n):
 words=re.findall(r'[a-z]+',text.lower());words=[w[:-1] if w in ('monitors','screens','displays','laptops','desktops','keyboards','mice','docks','cables','chargers','webcams','speakers','lamps','plants') and w!='mice' else 'mouse' if w=='mice' else w for w in words];v=np.zeros(n,dtype=np.float32)
 for g in ['w:'+w for w in words]+['b:'+a+' '+b for a,b in zip(words,words[1:])]:v[int.from_bytes(hashlib.blake2s(g.encode(),digest_size=4).digest(),'little')%n]+=1
 return v/max(1.,np.linalg.norm(v))

def route(text):
 global _CACHE
 if _CACHE is None:
  try:
   m=json.loads((ROOT/'manifest.json').read_text());blob=(ROOT/'router.npz').read_bytes()
   if hashlib.sha256(blob).hexdigest()!=m['sha256']:raise ValueError()
   with np.load(ROOT/'router.npz',allow_pickle=False) as f:_CACHE=(m,f['weight'].copy(),f['bias'].copy())
  except Exception as exc:raise ModelError('The trained workspace router is unavailable. No alternate model or external request was used.') from exc
 m,weight,bias=_CACHE;logits=weight@features(text,m['features'])+bias;n=len(m['actions'])
 def predict(a):
  e=np.exp(a-a.max());p=e/e.sum();i=int(p.argmax());return i,float(p[i])
 a,ac=predict(logits[:n]);k,kc=predict(logits[n:]);op=m['actions'][a];kind=m['kinds'][k]
 # Explicit policy gates are independent of learned confidence.
 blocked=re.search(r'\b(medical|diagnos\w*|pain|hospital|emergency|electri\w*|load.bearing|structural|buy|purchase|pay|admin|password|secret|install|certif\w*|guarantee)\b',text,re.I)
 if ac<(.75 if op=='remove' else .80) or op in ('add','remove','move') and kc<.80 or blocked:op='clarify'
 if op=='remove' and not re.search(r'\b(remove|delete|no|not|zero|without|take away|get rid)\b',text,re.I):op='clarify'
 if op=='add' and not re.search(r'\b(add|include|put|need|want|place|give)\b',text,re.I):op='clarify'
 return {'action':op,'kind':kind,'confidence':round(ac,5),'kind_confidence':round(kc,5),'model_sha256':m['sha256']}

WORDS={'zero':0,'no':0,'one':1,'a':1,'an':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8}
def explicit_count(text,default=1):
 rows=re.findall(r'\b(?:\d+|zero|one|two|three|four|five|six|seven|eight|no)\b',text.lower())
 if len(rows)>1:raise ValueError('Use one item count per request.')
 return int(rows[0]) if rows and rows[0].isdigit() else WORDS[rows[0]] if rows else default

def dimensions(text):
 # Values are extracted only from explicit metric units, not inferred from model names.
 p=re.search(r'(\d+(?:\.\d+)?)\s*(mm|cm|m)?\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)\b',text,re.I)
 if p:
  a,u,b,v=p.groups();u=u or v;return float(a)*{'mm':1,'cm':10,'m':1000}[u.lower()],float(b)*{'mm':1,'cm':10,'m':1000}[v.lower()]
 width=re.search(r'(\d+(?:\.\d+)?)\s*(mm|cm|m)\s*(?:wide|width)',text,re.I);depth=re.search(r'(\d+(?:\.\d+)?)\s*(mm|cm|m)\s*(?:deep|depth)',text,re.I)
 if width and depth:return tuple(float(p[1])*{'mm':1,'cm':10,'m':1000}[p[2].lower()] for p in (width,depth))
 raise ValueError('Enter the surface width and depth with units, for example 90 × 50 cm.')

def budget(text,currency):
 if re.search(r'-\s*\d',text):raise ValueError('Budget cannot be negative.')
 if re.search(r'\bzero\b',text,re.I):amount=0
 else:
  values=re.findall(r'(?<![\w.])\d+(?:\.\d{1,2})?(?![\w.])',text)
  if len(values)!=1:raise ValueError('Use one explicit budget amount, for example 100 USD.')
  from decimal import Decimal
  amount=int(Decimal(values[0])*100)
 declared='USD' if re.search(r'\$|\b(?:USD|dollars?)\b',text,re.I) else 'EUR' if re.search(r'€|\b(?:EUR|euros?)\b',text,re.I) else 'GBP' if re.search(r'£|\b(?:GBP|pounds?)\b',text,re.I) else currency
 if declared!=currency:raise ValueError('Set the workspace currency explicitly before changing this budget.')
 return amount


def status():
 try:
  m=json.loads((ROOT/'manifest.json').read_text())
  if hashlib.sha256((ROOT/'router.npz').read_bytes()).hexdigest()!=m['sha256']:raise ValueError()
  return {'ready':True,'sha256':m['sha256']}
 except Exception:return {'ready':False,'notice':'The required trained intent router is missing or invalid. No paid fallback will be used.'}
