"""One-sentence, local-model-directed research -> bounded setup proposals.
Only extracted public model names/official URLs leave this process. A reviewed
proposal is a draft, never a purchase, source certification or budget guarantee.
"""
from __future__ import annotations
import copy,json,re,time,uuid,threading,hashlib,itertools
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import TypedDict,Literal
from fastapi import Request,HTTPException
from pydantic import Field
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from . import device_research as research,free_discovery as discovery,planning_engine as engine,trained_agent,workspace_intent
from .planning_compiler import compile_request
from .planning_models import Design,Planning,DeviceSelection,Profile,Goal
from .workspace import Workspace,Item,Requirement,Surface
from .planning_routes import profiles,validated_permission
from .equipment_studio import passport
from .open_research import validate_proposal
from . import landed_budget,delivery_quotes

class Start(Design):
 query:str=Field(min_length=8,max_length=1200)
 client_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 consent:Literal[True]
 delivery:landed_budget.Destination|None=None
 price_research:bool=False
class Charges(Design):
 candidate_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 charges:list[delivery_quotes.StoreCharges]=Field(min_length=1,max_length=12)

class Apply(Design):
 candidate_id:str=Field(pattern=r'^[a-f0-9]{32}$')
 reviewed:Literal[True]

def identity():
 root=Path(__file__).parent
 return research.digest({n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ('sentence_setup.py','retail_sources.py','landed_budget.py','delivery.py','delivery_quotes.py','merchant_totals.py','equipment_studio.py','planning_compiler.py','planning_engine.py','planning_models.py','workspace.py','device_research.py','free_discovery.py','data/device-library.json')})
def snapshot(w,p):return research.digest({'workspace':w.model_dump(),'planning':p.model_dump()})
def tokens(text):return set(research.normalize(text).split())
def configuration(d):
 configs=d['configurations']
 for c in ('in_use','with_stand','stand_low','stand_extended','ergo_stand','default'):
  if c in configs:return c
 return next(iter(configs))
def registry(extra):
 unique={d['id']:d for d in research.catalog()}
 for d in extra:unique[d['id']]=d
 return list(unique.values())
def matches(query,kind,extra):
 wanted=tokens(query);out=[]
 for d in registry(extra):
  if d['kind']!=kind:continue
  scores=[len(tokens(a)) for a in [d['name'],*d.get('aliases',[])] if tokens(a) and tokens(a)<=wanted]
  if scores:out.append((max(scores),d))
 if not out:return []
 best=max(n for n,d in out);return [d for n,d in out if n==best]

def intake(text,w,p,extra=()):
 """Literal fields and preserved residuals. The trained policy, not this parser,
 chooses the research tool. Ambiguity is retained rather than silently relaxed.
 """
 parsed,meta,coverage=compile_request(Workspace(currency=w.currency),Planning(),text)
 questions=[];span=None;host='';known=matches(text,'laptop',extra)
 if len(known)==1:
  d=known[0];host=d['name']
  aliases=sorted([d['name'],*d.get('aliases',[])],key=len,reverse=True)
  span=next((m.span() for a in aliases if (m:=re.search(re.escape(a),text,re.I))),None)
 elif len(known)>1:questions.append('Choose the exact laptop variant; the name matches multiple profiles.')
 if not host:
  m=re.search(r"(?:\bI\s+(?:already\s+)?(?:have|own|use)|\bmy\s+laptop\s+is|\blaptop\s*:)\s+(?:an?\s+)?(.+?)(?=\s*[,;]|\s+(?:and|with)\s+(?:a\s+)?(?:budget|\$|I\b|need|want)|\s+(?:under|budget)\b|$)",text,re.I)
  if m:
   candidate=m[1].strip().removesuffix(' laptop').strip()
   try:host=discovery.validate_query(candidate);span=m.span(1)
   except ValueError:questions.append('Use only the public manufacturer and exact laptop model after “I have”.')
 if not host:questions.append('Name your exact laptop, including year or chip if relevant.')
 explicit_owned=bool(re.search(r'\bI\s+(?:already\s+)?(?:have|own|use)\b|\bmy\s+laptop\b',text,re.I))
 counts={g.category:int(g.value) for g in meta.goals if g.kind=='count' and g.category not in ('laptop','desktop')}
 if any(g.kind=='count' and g.category in ('laptop','desktop') for g in meta.goals):questions.append('This flow plans around one laptop; additional hosts need separate switching review.')
 for kind,word in [('monitor',r'monitors?|screens?|displays?'),('mouse',r'mouse|mice'),('keyboard',r'keyboards?'),('webcam',r'webcams?')]:
  if kind not in counts and re.search(r'\b(?:an?|another)\s+(?:external\s+)?(?:'+word+r')\b',text,re.I):counts[kind]=1
  if kind not in counts and re.search(r'\b(?:need|want|include)\s+(?:an?\s+)?(?:'+word+r')\b',text,re.I):counts[kind]=1
 # Explicit modifier-bearing quantities: size/workload modifiers remain open
 # requirements even when the noun/count can be represented.
 noun_kind={'monitor':'monitor','screen':'monitor','display':'monitor','mouse':'mouse','mice':'mouse','keyboard':'keyboard','webcam':'webcam','cable':'cable'}
 for m in re.finditer(r"\b(no|zero|one|two|three|four|a|an|\d+)\s+(?:(?:\d+(?:\.\d+)?[- ]inch|4K|external|quiet|silent|left[ -]handed|right[ -]handed|wireless|wired|gaming|ultrawide|curved)\s+){0,4}(monitors?|screens?|displays?|mouse|mice|keyboards?|webcams?|cables?)\b",text,re.I):
  if re.search(r'[$€£]\s*$',text[:m.start()]):continue
  raw,noun=m.groups();kind=noun_kind.get(noun.lower().rstrip('s'),noun_kind.get(noun.lower()));value=int(raw) if raw.isdigit() else {'no':0,'zero':0,'one':1,'two':2,'three':3,'four':4,'a':1,'an':1}[raw.lower()]
  if kind:counts[kind]=value
 for kind,word in [('monitor',r'monitor|screen|display'),('mouse',r'mouse'),('keyboard',r'keyboard'),('cable',r'cable')]:
  if re.search(r"\b(?:do not|don't)\s+(?:need|want)\s+(?:an?\s+)?(?:"+word+r")s?\b",text,re.I):counts[kind]=0
 if any(v>4 for v in counts.values()):questions.append('This one-sentence proposal supports at most four of each accessory. Your requested quantity was retained.')
 if parsed.budget_cents is None:
  m=re.search(r'\b(?:under|up to|at most|budget(?: is| of)?)\s+(\d+(?:\.\d{1,2})?)\s*(USD|dollars?|EUR|euros?|GBP|pounds?)?\b',text,re.I)
  if m:
   try:parsed.budget_cents=workspace_intent.budget(m[0],w.currency)
   except ValueError as exc:questions.append(str(exc))
 budgets=re.findall(r'[$€£]\s*\d+(?:\.\d{1,2})?',text)
 if len(set(budgets))>1:questions.append('Several monetary amounts were found. Confirm one total budget.');parsed.budget_cents=None
 if re.search(r'€|\bEUR\b',text,re.I) and w.currency!='EUR' or re.search(r'£|\bGBP\b',text,re.I) and w.currency!='GBP':questions.append('Choose the workspace currency explicitly; no exchange rate was assumed.')
 # Explicit currency must match the workspace; never reinterpret EUR/CAD as USD.
 import pycountry
 explicit=[]
 for match in re.finditer(r'\b([A-Z]{3})\s*\$?\s*(\d+(?:\.\d{1,2})?)\b|\b(\d+(?:\.\d{1,2})?)\s*([A-Z]{3})\b',text):
  code,amount=(match[1],match[2]) if match[1] else (match[4],match[3])
  if pycountry.currencies.get(alpha_3=code):explicit.append((code,landed_budget.retail.money(amount)))
 for prefix,code in [('US$', 'USD'),('CA$', 'CAD'),('C$', 'CAD'),('AU$', 'AUD'),('A$', 'AUD'),('NZ$', 'NZD'),('€','EUR'),('£','GBP'),('₹','INR')]:
  for match in re.finditer(re.escape(prefix)+r'\s*(\d+(?:\.\d{1,2})?)',text):explicit.append((code,landed_budget.retail.money(match[1])))
 if explicit:
  if any(code!=w.currency for code,value in explicit) or len({value for code,value in explicit})>1:
   parsed.budget_cents=None;questions.append('Choose one total budget in the workspace currency; no exchange rate was assumed.')
  elif parsed.budget_cents is None:parsed.budget_cents=explicit[0][1]
 meta.goals=[g for g in meta.goals if g.kind!='budget']
 if not counts:questions.append('Say which accessories you need, for example one monitor and a mouse.')
 # Keep the compiler's uncovered clauses, minus exact device identity and the
 # ordinary intake connective. Workload/diagonal/OS requirements remain open.
 meta.goals=[g for g in meta.goals if g.kind!='count']
 for kind,count in counts.items():meta.goals.append(Goal(id='requested_'+kind,kind='count',category=kind,value=count,text=f'{count} {kind}',required=True))
 if parsed.budget_cents is not None and not any(g.kind=='budget' for g in meta.goals):meta.goals.append(Goal(id='requested_budget',kind='budget',value=parsed.budget_cents,text='Total budget'))
 leftovers=text
 if span:leftovers=text[:span[0]]+' '+text[span[1]:]
 for c in coverage['covered']:leftovers=leftovers.replace(c['text'],' ')
 leftovers=re.sub(r'\b(?:I|have|own|already|use|my|laptop|is|a|an|and|with|need|want|please|build|setup|for|on|under|up to|at most|budget|of|dollars|USD)\b',' ',leftovers,flags=re.I)
 leftovers=re.sub(r'\b(?:a|an)?\s*(?:mouse|monitor|keyboard|screen|display|webcam)\b',' ',leftovers,flags=re.I)
 leftovers=re.sub(r'[,;:.\s]+',' ',leftovers).strip()
 # Values covered by the alternate budget parser are not workload constraints.
 leftovers=re.sub(r'\b\d+(?:\.\d{1,2})?\b','',leftovers).strip() if not re.search(r'inch|Hz|4K|1440p|1080p',leftovers,re.I) else leftovers
 if leftovers:
  meta.goals.append(Goal(id='request_remaining',kind='custom',text='Review remaining needs: '+leftovers[:900],required=True))
 if parsed.budget_cents is None:questions.append('Budget is not established; no affordable-price claim can be made.')
 return {'host_query':host,'host_owned':explicit_owned,'known_hosts':[d['id'] for d in known],'counts':counts,'budget_cents':parsed.budget_cents,'surface':parsed.surface.model_dump(),'goals':[g.model_dump() for g in meta.goals],'questions':questions,'unrepresented':leftovers,'query':text,'scope':'Literal intake plus local trained tool selection. The full sentence remains an open requirement.'}

def compose(brief,old,p,extra=(),fresh=(),result_limit=3):
 """Bounded finite comparison; sourced dimensions do not turn missing prices
 or native-video limits into successful checks. No old wire/permission reuse.
 """
 all_profiles=registry(list(extra)+list(fresh));by={d['id']:d for d in all_profiles}
 host_matches=matches(brief['host_query'],'laptop',list(extra)+list(fresh))
 host=host_matches[0] if len(host_matches)==1 else next((d for d in fresh if d['kind']=='laptop' and d['name']==brief['host_query']),None)
 requirements=[Requirement(id=uuid.uuid4().hex,text=brief['query'])]
 base=Workspace(name='Your next setup',currency=old.currency,budget_cents=brief['budget_cents'],surface=Surface.model_validate(brief['surface']),requirements=requirements,finish=old.finish)
 # Never silently remove locked items from the current draft.
 locked=[copy.deepcopy(i) for i in old.items if i.locked]
 choices=[]
 for kind,count in brief['counts'].items():
  if count<0 or count>4:continue
  owned=[i for i in old.items if i.kind==kind and i.owned]
  rows=[d for d in all_profiles if d['kind']==kind and (any(discovery.official(v.get('url','')) for v in d['sources']) or any(i.model==d['name'] for i in owned))]
  def key(d):
   fields=d['configurations'][configuration(d)]
   reuse=any(i.model==d['name'] for i in owned)
   fit=fields.get('width_mm',9999) if kind=='monitor' else 0
   host_f=host['configurations'][configuration(host)] if host else {}
   connection=bool(host_f.get('video_out_usb_c') and fields.get('video_in_dp')) if kind=='monitor' else bool(host_f.get('bluetooth') and fields.get('bluetooth'))
   observed=any(v.get('document_sha256') and discovery.official(v.get('url','')) for v in d['sources'])
   return (not reuse,not connection,not observed,fit,d['id'])
  rows.sort(key=key);choices.append((kind,count,rows[:3] or [None]))
 candidates=[]
 for combo in itertools.islice(itertools.product(*(r for _,_,r in choices)),9):
  w=copy.deepcopy(base);meta=Planning(goals=copy.deepcopy([Goal.model_validate(g) for g in brief['goals']]),allow_driver=False if re.search(r'no (?:software|drivers?)|without (?:software|drivers?)',brief['query'],re.I) else None)
  meta.offers=copy.deepcopy([o for o in p.offers if o.device_id]);meta.region=p.region;meta.exchange_rates=copy.deepcopy(p.exchange_rates)
  selected=[]
  def add(kind,d,owned=False,old_item=None,n=0):
   i=copy.deepcopy(old_item) if old_item else Item(id=uuid.uuid4().hex,kind=kind,name=(d['name'] if d else 'Proposed '+kind)[:100],owned=owned)
   if old_item:
    i.ports=[];i.ports_confirmed=False
   w.items.append(i)
   poses={'laptop':(-420,160),'monitor':(80,-180),'mouse':(520,180),'keyboard':(0,230),'cable':(-100,330),'webcam':(300,-300)}
   x,z=poses.get(kind,(0,0));i.pose.x=x+n*620;i.pose.z=z;i.pose.yaw=0
   if d:
    if d['id'] not in {v['id'] for v in research.catalog()} and not any(v.id==d['id'] for v in meta.profiles):meta.profiles.append(Profile.model_validate(d))
    selection=DeviceSelection(item_id=i.id,device_id=d['id'],configuration=configuration(d),source_digest=d['digest'],reviewed=True)
    out,context=engine.apply_configuration(w,meta,i.id,selection,list(extra)+list(fresh));w.items=out.items;meta.devices=context.devices;selected.append(d)
   return next(i2 for i2 in w.items if i2.id==i.id)
  own_host=next((i for i in old.items if i.kind=='laptop' and host and i.model==host['name'] and i.owned),None)
  laptop=add('laptop',host,brief['host_owned'] or bool(own_host),own_host)
  if not host:laptop.name=brief['host_query'][:100];laptop.model=brief['host_query']
  for (kind,count,_),d in zip(choices,combo):
   previous=[i for i in old.items if i.kind==kind and i.owned and d and i.model==d['name']]
   for n in range(count):add(kind,d,bool(n<len(previous)),previous[n] if n<len(previous) else None,n)
  for locked_item in locked:
   if not any(i.id==locked_item.id for i in w.items):w.items.append(locked_item)
  # Only a sourced USB-C DisplayPort cable is proposed for this bounded route.
  # A display, dock and cable remain independent 3D objects.
  screen_count=sum(i.kind=='monitor' for i in w.items)
  if host and screen_count:
   hf=host['configurations'][configuration(host)]
   cable=next((d for d in all_profiles if d['kind']=='cable' and any(v.get('link_type')=='usb_c_dp' for v in d['configurations'].values())),None)
   if hf.get('video_out_usb_c') and cable and brief['counts'].get('cable')!=0:
    previous=[i for i in old.items if i.kind=='cable' and i.owned and i.model==cable['name']]
    for n in range(screen_count):add('cable',cable,n<len(previous),previous[n] if n<len(previous) else None,n)
  # Reuse observations only for the exact unchanged owned item/model/config.
  old_bindings={b.item_id:(b.device_id,b.configuration,b.source_digest) for b in p.devices}
  new_bindings={b.item_id:(b.device_id,b.configuration,b.source_digest) for b in meta.devices}
  ids={i.id for i in w.items if i.owned and old_bindings.get(i.id)==new_bindings.get(i.id) and i.id in new_bindings and any(o.id==i.id and o.model==i.model for o in old.items)}
  meta.observations=copy.deepcopy([v for v in p.observations if v.item_id in ids])
  if all(i.dimensions and i.dimensions.basis!='illustrative' for i in w.items) and w.surface.width:
   w,placement=engine.arrange(w,meta,node_limit=3000)
  else:placement={'status':'illustrative','nodes':0}
  w=Workspace.model_validate(w.model_dump());meta=Planning.model_validate(meta.model_dump())
  check=passport(w,meta,list(extra)+list(fresh));hard=sum(v['status']=='unmet' for v in check['checks']);gaps=len(check['blockers'])
  candidates.append({'id':uuid.uuid4().hex,'workspace':w.model_dump(),'planning':meta.model_dump(),'passport':check,'placement':placement,'profiles':[d['id'] for d in selected],'reuse_count':sum(i.owned for i in w.items),'purchase_count':sum(not i.owned for i in w.items),'rank':[hard,gaps,check['cost']['total_minor'] is None,check['cost']['total_minor'] or 0],'scope':'A source-backed draft with explicit missing checks. No price/stock/physical-fit guarantee or purchase.'})
 candidates.sort(key=lambda c:c['rank'])
 seen=set();unique=[]
 for c in candidates:
  key=tuple((i['kind'],i['model']) for i in c['workspace']['items'])
  if key in seen:continue
  seen.add(key);unique.append(c)
 return unique[:result_limit]

_active=threading.Lock();_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='explicit-sentence-setup');_instance=uuid.uuid4().hex
class Halt(Exception):pass

def register(module):
 def state_for(db,sid):
  row=db.execute('SELECT state FROM sessions WHERE id=? AND expires>?',(sid,time.time())).fetchone()
  if not row:raise Halt('Owning session expired.')
  return json.loads(row['state'])
 def update(sid,jid,fn):
  with module.database() as db:
   db.execute('BEGIN IMMEDIATE');s=state_for(db,sid);j=s.get('sentence_setups',{}).get(jid)
   if not j or j['status'] not in ('QUEUED','RUNNING'):raise Halt('This setup action stopped.')
   if time.time()>j['expires_at']:raise Halt('The fixed research time bound was reached.')
   fn(s,j);s['version']+=1;module.save(db,sid,s);return copy.deepcopy(j)
 def event(sid,jid,phase,**v):
  def mutate(s,j):
   if phase.startswith('offer_'):
    if j.get('quote_requests',0)>=32:raise Halt('The thirty-two-request public price/fee bound was reached.')
    j['quote_requests']=j.get('quote_requests',0)+1
   if phase in ('search','read'):
    if j['public_requests']>=12:raise Halt('The twelve-request public research bound was reached.')
    j['public_requests']+=1
   j['phase']=phase;j['events'].append({'phase':phase,'at':int(time.time()),**v})
  return update(sid,jid,mutate)
 def finish(sid,jid,status,error=None):
  with module.database() as db:
   db.execute('BEGIN IMMEDIATE');s=state_for(db,sid);j=s.get('sentence_setups',{}).get(jid)
   if not j or j['status'] not in ('QUEUED','RUNNING'):return
   j['status']=status;j['phase']='finished'
   if error:j['errors'].append(str(error)[:500])
   s['version']+=1;module.save(db,sid,s)
 def worker(sid,jid):
  try:
   job=update(sid,jid,lambda s,j:j.update(status='RUNNING'));old=Workspace.model_validate(job['workspace']);p=Planning.model_validate(job['planning']);extra=job['owned_profiles'];brief=job['brief'];fresh=[];sources=[];errors=[]
   class State(TypedDict,total=False):tool:str;candidates:list
   g=StateGraph(State)
   def model(_):
    event(sid,jid,'agent');observed={'discovered':False,'decision_facts_missing':1,'software_candidate':False,'software_answered':True,'supported_basket':False,'remaining_steps':4,'budget_cents':brief['budget_cents'] or 0}
    raw,receipt=trained_agent.generate(json.dumps(observed,separators=(',',':')),trained_agent.POLICY,8)
    update(sid,jid,lambda s,j:j.update(model_receipt=receipt,model_tool=raw))
    if raw not in ('search','inspect','clarify','recommend','defer'):raise ValueError('Unsupported local research tool.')
    return {'tool':raw}
   def read_task(query,kind,known=None):
    if not query:return
    # Reuse this account's retained matching observed documents for24h.
    update(sid,jid,lambda s,j:None)
    with module.database() as db:saved=state_for(db,sid)
    cached=next((j for j in reversed(list(saved.get('open_research',{}).values())) if j['query'].lower()==query.lower() and j['status']=='AWAITING_REVIEW' and time.time()-j.get('researched_at',j['created_at'])<86400 and all(d['id'] in saved.get('planning_documents',{}) for d in j['sources'])),None)
    if cached:
     for prop in cached['proposals']:
      if kind=='laptop' and prop['configuration']!='in_use':continue
      doc=saved['planning_documents'][prop['source_id']]
      if not known and not any(v['name']==prop['name'] and prop['configuration'] in v['configurations'] for v in fresh):fresh.append(validate_proposal(doc,prop))
      sources.append({'query':query,'url':doc['url'],'status':'owned_snapshot','method':doc.get('method',''),'facts':list(prop['fields'])})
     return
    if known:
     results=[{'url':s['url'],'title':known['name']} for s in known['sources'] if discovery.official(s.get('url',''))][:1]
    else:
     found=discovery.discover(query,kind,lambda phase,**v:event(sid,jid,phase,**v));results=found['results'][:2];errors.extend(found['errors'])
    successful=False
    for result in results:
     try:
      event(sid,jid,'read',model=query,url=result['url']);doc=research.fetch(result['url'],consent=True);successful=True
      props=discovery.proposals(doc,query,kind)
      for prop in props[:2]:
       if kind=='laptop' and prop['configuration']!='in_use':continue
       prop['proposal_id']=uuid.uuid4().hex;checked=validate_proposal(doc,prop)
       if not known and not any(v['name']==prop['name'] and prop['configuration'] in v['configurations'] for v in fresh):fresh.append(checked)
      sources.append({'query':query,'url':doc['url'],'status':'quoted_facts' if props else 'read_no_supported_new_facts','method':doc['method'],'facts':sorted({k for v in props for k in v['fields']})})
      def remember(s,j):
       docs=s.setdefault('planning_documents',{});docs[doc['id']]=doc
       while len(docs)>8:del docs[next(iter(docs))]
      update(sid,jid,remember)
     except Halt:raise
     except (ValueError,OSError) as exc:errors.append(query+': '+str(exc)[:300]);sources.append({'query':query,'url':result['url'],'status':'unavailable'})
    if known and results and not successful:read_task(query,kind,None)
   def research_node(_):
    event(sid,jid,'research')
    hosts=matches(brief['host_query'],'laptop',extra);read_task(brief['host_query'],'laptop',hosts[0] if len(hosts)==1 else None)
    initial=compose(brief,old,p,extra,fresh)
    if initial:
     selected=initial[0];all_by={d['id']:d for d in registry(extra+fresh)}
     # Read one selected exact option per requested category, at most two
     # accessories; do not send the full sentence/workspace to public search.
     for kind in ('monitor','mouse'):
      item=next((i for i in selected['workspace']['items'] if i['kind']==kind and not i['owned']),None)
      binding=next((b for b in selected['planning']['devices'] if item and b['item_id']==item['id']),None)
      d=all_by.get(binding['device_id']) if binding else None
      if d:read_task(d['name'],kind,d)
    update(sid,jid,lambda s,j:j.update(sources=sources,errors=errors));return {}
   def build(_):
    event(sid,jid,'compose');candidates=compose(brief,old,p,extra,fresh,result_limit=9 if job.get('price_research') else 3);records={}
    if job.get('price_research'):
     event(sid,jid,'prices');destination=landed_budget.Destination.model_validate(job['delivery']) if job.get('delivery') else None
     needed=list(dict.fromkeys(b['device_id'] for c in candidates for b in c['planning']['devices'] if any(i['id']==b['item_id'] and not i['owned'] for i in c['workspace']['items'])))
     available={d['id']:d for d in registry(extra+fresh)};observed={};price_errors=[];memo={}
     for ident in list(needed)[:7]:
      found=landed_budget.observe(available[ident],lambda phase,**v:event(sid,jid,phase,**v),destination=destination,currency=old.currency);observed[ident]=found['offers'];price_errors.extend(found['errors'])
     tax=landed_budget.tax_rule(destination,on_event=lambda phase,**v:event(sid,jid,phase,**v)) if needed else {'status':'no_purchase','amount_minor':0}
     priced=[]
     for c in candidates:
      value,record=landed_budget.price_candidate(c,observed,destination,tax,on_event=lambda phase,**v:event(sid,jid,phase,**v),memo=memo,reviewed_rates=());priced.append(value);records[record['id']]=record
     priced.sort(key=lambda c:c['rank']);candidates=priced[:3]
     def save_quotes(state,j):
      quotes=state.setdefault('delivered_quotes',{});retained={c['landed']['id'] for c in candidates}
      quotes.update({k:v for k,v in records.items() if k in retained})
      while len(quotes)>12:del quotes[next(iter(quotes))]
      j['price_errors']=price_errors;j['comparison_count']=len(priced);j['outcome']={'within_budget':sum(c['landed']['status']=='within_budget_estimate' for c in priced),'complete_estimates':sum(c['landed']['total_minor'] is not None for c in priced),'scope':'Compared bounded observed options; no guarantee that a feasible setup exists or that all market options were searched.'}
     update(sid,jid,save_quotes)
    update(sid,jid,lambda s,j:j.update(candidates=candidates,research_profiles=fresh));return {'candidates':candidates}
   g.add_node('agent',model);g.add_node('research',research_node);g.add_node('build',build);g.add_edge(START,'agent');g.add_conditional_edges('agent',lambda s:'research' if s['tool']=='search' else 'end',{'research':'research','end':END});g.add_edge('research','build');g.add_edge('build',END)
   with tracing_context(enabled=False):out=g.compile().invoke({},config={'recursion_limit':6,'callbacks':[]})
   finish(sid,jid,'PROPOSALS_READY' if out.get('candidates') else 'AGENT_PAUSED')
  except Halt as exc:finish(sid,jid,'STOPPED',exc)
  except Exception as exc:finish(sid,jid,'FAILED',exc)
  finally:_active.release()
 def view(j):
  value=copy.deepcopy(j);value.pop('owned_profiles',None);value.pop('owned_charge_quotes',None);value.pop('input_planning',None);value.pop('server_instance',None);value.pop('research_profiles',None)
  if j['status'] in ('RUNNING','QUEUED') and (j['server_instance']!=_instance or time.time()>j['expires_at']):value['status']='INTERRUPTED';value['errors'].append('Stopped; no automatic restart or renewed allowance.')
  return value
 @module.app.post('/api/setup/sentence/start')
 def start(body:Start,request:Request):
  from .accounts import throttle
  with module.database() as db:
   sid,s=module.owner(request,db,True);extra=profiles(s);base=snapshot(body.workspace,body.planning);input_planning=body.planning.model_dump();body.planning=validated_permission(body.workspace,body.planning,s);existing=s.get('sentence_setups',{}).get(body.client_id)
   if existing:
    if existing['input_hash']!=base or existing['query']!=body.query or existing.get('price_research',False)!=body.price_research or existing.get('delivery')!=(body.delivery.model_dump() if body.delivery else None):raise HTTPException(409,'This action belongs to another setup/request.')
    return view(existing)
   if body.price_research and body.delivery is None:raise HTTPException(422,'Set the coarse delivery destination before researching delivered prices.')
   try:brief=intake(body.query,body.workspace,body.planning,extra)
   except ValueError as exc:raise HTTPException(422,'Use one exact laptop, one total budget, and at most four of each accessory in this setup request. No draft was changed.') from exc
   if not brief['host_query']:raise HTTPException(422,'Name your exact laptop, for example “I have a MacBook Air M1, $300 and need one monitor and a mouse.”')
   if not _active.acquire(blocking=False):raise HTTPException(429,'A one-sentence setup is already being researched.')
   try:
    if not throttle(db,'sentence-setup:'+sid,4,3600):raise HTTPException(429,'Four complete research actions per hour. Your draft is unchanged.')
    j={'id':body.client_id,'query':body.query,'price_research':body.price_research,'delivery':body.delivery.model_dump() if body.delivery else None,'input_hash':base,'input_planning':input_planning,'workspace':body.workspace.model_dump(),'planning':body.planning.model_dump(),'owned_profiles':extra,'owned_charge_quotes':[r for old in s.get('sentence_setups',{}).values() for c in old.get('candidates',[]) for r in c.get('landed',{}).get('shipments',[]) if r.get('attested') and r.get('expires_at',0)>time.time()][-24:],'brief':brief,'status':'QUEUED','phase':'queued','created_at':int(time.time()),'expires_at':int(time.time()+(360 if body.price_research else 240)),'server_instance':_instance,'source_identity':identity(),'events':[],'sources':[],'errors':[],'candidates':[],'research_profiles':[],'public_requests':0,'quote_requests':0,'scope':'Local CPU-model tool selection, literal intake and bounded official-source research. Public model names only; no paid APIs/purchases. Proposed 3D drafts can have unresolved price, stock, variant and measurement checks.'}
    rows=s.setdefault('sentence_setups',{});rows[j['id']]=j
    while len(rows)>6:del rows[next(iter(rows))]
    s['version']+=1;module.save(db,sid,s)
   except BaseException:_active.release();raise
  try:_pool.submit(worker,sid,j['id'])
  except Exception:
   _active.release();finish(sid,j['id'],'FAILED','The local worker could not start.');raise HTTPException(503,'Could not start research. Nothing was applied.')
  return view(j)
 @module.app.get('/api/setup/sentence/{jid}')
 def read(jid:str,request:Request):
  with module.database() as db:
   _,s=module.owner(request,db);j=s.get('sentence_setups',{}).get(jid)
   if not j:raise HTTPException(404,'Setup research is not in this account.')
   return view(j)
 @module.app.post('/api/setup/sentence/{jid}/cancel')
 def cancel(jid:str,request:Request):
  with module.database() as db:
   sid,s=module.owner(request,db,True);j=s.get('sentence_setups',{}).get(jid)
   if not j:raise HTTPException(404,'Setup research is not in this account.')
   if j['status'] in ('RUNNING','QUEUED'):j['status']='CANCELLED';s['version']+=1;module.save(db,sid,s)
   return view(j)
 @module.app.post('/api/setup/sentence/{jid}/charges')
 def complete_charges(jid:str,body:Charges,request:Request):
  with module.database() as db:
   sid,s=module.owner(request,db,True);j=s.get('sentence_setups',{}).get(jid)
   if not j or j['status']!='PROPOSALS_READY':raise HTTPException(409,'Research the current setup first.')
   submitted=snapshot(body.workspace,body.planning);body.planning=validated_permission(body.workspace,body.planning,s)
   if j['input_hash']!=submitted or j['source_identity']!=identity():raise HTTPException(409,'The input or source changed. Research the current setup again.')
   candidate=next((c for c in j['candidates'] if c['id']==body.candidate_id),None)
   if not candidate:raise HTTPException(404,'Choose an owned proposal.')
   if candidate['landed']['expires_at']<time.time():raise HTTPException(409,'Refresh current product prices before reviewing store totals.')
   destination=landed_budget.Destination.model_validate(j['delivery']);lines=candidate['landed']['lines'];grouped={};observations={}
   for row in lines:
    if row['offer']:
     v=row['offer'];grouped.setdefault(v['merchant'],[]).append(v);observations.setdefault(v['device_id'],[])
     if not any(o['id']==v['id'] for o in observations[v['device_id']]):observations[v['device_id']].append(v)
   if len({c.merchant for c in body.charges})!=len(body.charges):raise HTTPException(422,'Review each merchant once.')
   rates={v['merchant']:v for v in candidate['landed']['shipments']}
   try:
    for c in body.charges:
     reviewed=delivery_quotes.reviewed_rate(c,grouped.get(c.merchant,[]),destination);reviewed['quantity_confirmed']=bool(rates.get(c.merchant,{}).get('quantity_confirmed'));rates[c.merchant]=reviewed
    candidate=copy.deepcopy(candidate);candidate['planning']=validated_permission(Workspace.model_validate(candidate['workspace']),Planning.model_validate(candidate['planning']),s).model_dump()
    value,record=landed_budget.price_candidate(candidate,observations,destination,candidate['landed']['tax'],fixed_rates=rates)
   except ValueError as exc:raise HTTPException(422,str(exc)) from exc
   value['id']=uuid.uuid4().hex;j['candidates']=[value if c['id']==candidate['id'] else c for c in j['candidates']]
   quotes=s.setdefault('delivered_quotes',{});quotes[record['id']]=record
   while len(quotes)>12:del quotes[next(iter(quotes))]
   j.setdefault('charge_reviews',[]).append({'at':int(time.time()),'merchants':[c.merchant for c in body.charges],'scope':'User-reviewed charges; no model, external request, order or payment.'})
   j['charge_reviews']=j['charge_reviews'][-12:];j['outcome']={'within_budget':sum(c['landed']['status']=='within_budget_estimate' for c in j['candidates']),'complete_estimates':sum(c['landed']['total_minor'] is not None for c in j['candidates']),'scope':'Current reviewed proposals only; not an all-market optimum.'};s['version']+=1;module.save(db,sid,s)
   result=view(j);result['reviewed_candidate_id']=value['id'];return result
 @module.app.post('/api/setup/sentence/{jid}/apply')
 def apply(jid:str,body:Apply,request:Request):
  with module.database() as db:
   sid,s=module.owner(request,db,True);j=s.get('sentence_setups',{}).get(jid)
   if not j or j['status']!='PROPOSALS_READY':raise HTTPException(409,'Research a current setup proposal first.')
   submitted=snapshot(body.workspace,body.planning);body.planning=validated_permission(body.workspace,body.planning,s)
   if j['input_hash']!=submitted or j['source_identity']!=identity() or time.time()-j['created_at']>3600:raise HTTPException(409,'The input or source changed. Research the current setup again.')
   candidate=next((c for c in j['candidates'] if c['id']==body.candidate_id),None)
   if not candidate:raise HTTPException(404,'Choose an owned proposal.')
   if candidate.get('landed') and candidate['landed']['expires_at']<time.time():raise HTTPException(409,'These prices expired. Research current prices before building.')
   w=Workspace.model_validate(candidate['workspace']);p=validated_permission(w,Planning.model_validate(candidate['planning']),s);extra=profiles(s)+j['research_profiles'];check=passport(w,p,extra)
   if research.digest(check)!=research.digest(candidate['passport']):raise HTTPException(409,'The evidence changed. Recheck this setup.')
   rows=s.setdefault('planning_profiles',{})
   for d in j['research_profiles']:
    if d['id'] not in rows and len(rows)>=40:raise HTTPException(409,'Personal profile limit reached; your draft is unchanged.')
    rows[d['id']]=d
   s['version']+=1;module.save(db,sid,s)
   return {'workspace':w.model_dump(),'planning':p.model_dump(),'passport':check,'notice':'3D draft prepared. Unresolved checks still need evidence; no purchase or saved project change.'}
