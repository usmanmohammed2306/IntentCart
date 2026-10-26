"""Three-way ID-aware merges and portable, non-authorizing backup data."""
import copy
from . import device_research as research
MISSING=object()
def merge(base,mine,latest):
 def clone(value):return MISSING if value is MISSING else copy.deepcopy(value)
 conflicts=[]
 def walk(b,m,l,path):
  if m==b:return clone(l)
  if l==b or m==l:return clone(m)
  if isinstance(b,dict) and isinstance(m,dict) and isinstance(l,dict):
   out={}
   for key in sorted(set(b)|set(m)|set(l)):
    bv,mv,lv=b.get(key,MISSING),m.get(key,MISSING),l.get(key,MISSING)
    value=walk(bv,mv,lv,path+[key])
    if value is not MISSING:out[key]=value
   return out
  if isinstance(b,list) and isinstance(m,list) and isinstance(l,list) and all(isinstance(x,dict) and 'id' in x for rows in (b,m,l) for x in rows):
   bv={x['id']:x for x in b};mv={x['id']:x for x in m};lv={x['id']:x for x in l};out=[]
   for key in dict.fromkeys([x['id'] for x in l]+[x['id'] for x in m]):
    value=walk(bv.get(key,MISSING),mv.get(key,MISSING),lv.get(key,MISSING),path+[{'id':key}])
    if value is not MISSING:out.append(value)
   return out
  conflicts.append({'path':path,'base':None if b is MISSING else b,'mine':None if m is MISSING else m,'latest':None if l is MISSING else l,'mine_deleted':m is MISSING,'latest_deleted':l is MISSING})
  return MISSING if l is MISSING else clone(l)
 result=walk(base,mine,latest,[])
 return {'merged':result,'conflicts':conflicts,'digest':research.digest({'base':base,'mine':mine,'latest':latest}),'notice':'Automatic nonconflicting merge is a proposal only. Explicitly resolve conflicting edits, then save against the latest revision.'}
