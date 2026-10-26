"""Compile explicit natural-language constraints into reviewable typed goals.
Unrepresented clauses remain visible questions; they never disappear into a plan.
"""
import copy,re,uuid
from .planning_models import Goal
from .workspace import Requirement,Surface
from . import workspace_intent
NUM={'zero':0,'no':0,'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8}
KINDS={'monitor':'monitor','screen':'monitor','display':'monitor','mouse':'mouse','keyboard':'keyboard','laptop':'laptop','desktop':'desktop','dock':'dock','webcam':'webcam'}
def compile_request(w,p,text):
 out=copy.deepcopy(w);meta=copy.deepcopy(p);covered=[];changes=[];questions=[];spans=[]
 def record(match,kind,value=None,category='',value2=None):
  g=Goal(id=uuid.uuid4().hex,kind=kind,text=match.group(0),value=value,category=category,value2=value2);meta.goals=[x for x in meta.goals if not (x.kind==g.kind and x.category==g.category and x.item_id==g.item_id)]+[g];spans.append(match.span());covered.append({'text':match.group(0),'goal_id':g.id,'kind':kind});return g
 for m in re.finditer(r'\b(no|zero|one|two|three|four|five|six|seven|eight|\d+)\s+(?:external\s+)?(monitors?|screens?|displays?|mice|mouse|keyboards?|laptops?|desktops?|docks?|webcams?)\b',text,re.I):
  raw,word=m.groups();count=int(raw) if raw.isdigit() else NUM[raw.lower()];word=word.lower();category='mouse' if word in ('mouse','mice') else KINDS.get(word.rstrip('s'))
  if category:record(m,'count',count,category)
 for phrase,kind in [(r'\b(?:no|without)\s+(?:new\s+)?(?:purchases?|buying)\b|\bbuy\s+nothing\b|\breuse[ -]only\b','no_purchase'),(r'\b(?:no|without)\s+(?:drilling|drill)\b','no_drill'),(r'\b(?:no|without)\s+(?:clamps?|clamping)\b','no_clamp')]:
  for m in re.finditer(phrase,text,re.I):record(m,kind,True)
 for m in re.finditer(r'\b(?:budget|spending limit)\s*(?:is|of|to|under|at most)?\s*(?:\$\s*)?(?:zero|\d+(?:\.\d{1,2})?)\s*(?:USD|EUR|GBP|dollars?|euros?|pounds?)?',text,re.I):
  try:amount=workspace_intent.budget(m.group(0),out.currency);out.budget_cents=amount;record(m,'budget',amount);changes.append('Use the explicitly stated budget.')
  except ValueError as exc:questions.append(str(exc));spans.append(m.span())
 for m in re.finditer(r'\$\s*\d+(?:\.\d{1,2})?',text):
  if not any(a<=m.start() and b>=m.end() for a,b in spans):
   try:amount=workspace_intent.budget(m.group(0),out.currency);out.budget_cents=amount;record(m,'budget',amount)
   except ValueError as exc:questions.append(str(exc))
 for m in re.finditer(r'\b(?:no|without (?:a )?|do not have a?)\s+(?:desk|table|surface)\b',text,re.I):out.surface.kind='none';spans.append(m.span());covered.append({'text':m.group(0),'kind':'no_surface'});changes.append('No desk is introduced.')
 size=re.search(r'\b(?:desk|table|surface)\b.{0,24}?(\d+(?:\.\d+)?)\s*(mm|cm|m)?\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)\b',text,re.I)
 if size:
  try:
   width,depth=workspace_intent.dimensions(size.group(0));out.surface=Surface(**{**out.surface.model_dump(),'kind':'desk','width':width,'depth':depth});spans.append(size.span());covered.append({'text':size.group(0),'kind':'surface_dimensions'});changes.append('Use the declared surface dimensions.')
  except ValueError as exc:questions.append(str(exc))
 for m in re.finditer(r'\b(?:fit|arrange|layout|organize)\b',text,re.I):record(m,'surface_fit',True)
 for m in re.finditer(r'\b(?:connect|connections|compatibility|compatible)\b',text,re.I):record(m,'connections',True)
 for m in re.finditer(r'\b(?:no software|no drivers?|without software|without drivers?|cannot install|not allowed to install)\b',text,re.I):meta.allow_driver=False;spans.append(m.span());covered.append({'text':m.group(0),'kind':'software_denied'})
 for m in re.finditer(r'\b(?:under|max(?:imum)?|at most)\s*(\d+(?:\.\d+)?)\s*(kg|grams?|g)\b',text,re.I):record(m,'max_weight',float(m[1])*(1000 if m[2].lower()=='kg' else 1))
 for m in re.finditer(r'\b(left|right)[ -]handed\s+(?:mouse|mice)\b',text,re.I):record(m,'handedness',m[1].lower(),'mouse')
 for m in re.finditer(r'\b(?:quiet|low.noise|silent)\s+(keyboard|mouse)\b',text,re.I):record(m,'noise','manufacturer_claim_only',m[1].lower())
 for m in re.finditer(r'\b(\d{3,4})p\s*(?:at|@)?\s*(\d{2,3})\s*Hz\b',text,re.I):record(m,'display_mode',int(m[1]),'monitor',float(m[2]))
 if text.strip():
  if len(out.requirements)>=40:raise ValueError('Requirement ledger is full. Export or remove reviewed requirements first.')
  out.requirements.append(Requirement(id=uuid.uuid4().hex,text=text,status='open'))
 remainder=list(text)
 for a,b in spans:remainder[a:b]=[' ']*(b-a)
 leftovers=''.join(remainder)
 glue={'please','plan','my','a','an','the','workspace','setup','with','and','but','for','i','want','need','use','keep','existing','to','it','within','on','only','new','of','is','in','at','me','make','can','you','all','everything'}
 unknown=[t for t in re.findall(r'[a-z0-9]+',leftovers.lower()) if t not in glue]
 if unknown:questions.append('Review the remaining meaning before approval: '+leftovers.strip()[:500])
 if re.search(r'\b(sofas?|rugs?|wall colo[u]?rs?|decorat(?:e|ion))\b',text,re.I) and not re.search(r'\b(computer|laptop|monitor|electronics|keyboard)\b',text,re.I):questions.append('For room decoration alone, use the suitable room-design tool you already have. IntentCart offers a free manual visual sandbox, but no demonstrated reason to buy an electronics planner for that task.')
 if not meta.goals:questions.append('Choose what the plan must achieve: equipment quantities, connections, physical fit, budget or reuse-only.')
 return out,meta,{'covered':covered,'unrepresented':questions,'changes':changes,'receipt':{'router_required_for_edit_requests':True,'basis':'Literal constraint compilation with complete request retention; not semantic completeness or permission approval'}}
