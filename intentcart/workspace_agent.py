"""Local trained-model proposals with executable checks and complete request retention."""
import json,uuid,copy
from .workspace import Workspace,Item,Requirement,Surface,analyze,digest
from . import trained_agent

def propose(w:Workspace,query:str):
 if len(w.requirements)>=40:raise trained_agent.ModelError('Your requirement ledger is full. Export the project or remove reviewed requirements before another request.')
 # No external provider. Artifacts and model outputs must pass the same validators as manual edits.
 from . import workspace_intent
 route=workspace_intent.route(query)
 action={'action':route['action'],'kind':route['kind'],'count':1,'label':'','direction':'none','width_mm':None,'depth_mm':None,'budget_cents':None}
 parse_question=None
 try:
  if action['action'] in ('add','remove'):action['count']=workspace_intent.explicit_count(query,0 if action['action']=='remove' else 1)
  if action['action']=='surface':action['width_mm'],action['depth_mm']=workspace_intent.dimensions(query)
  if action['action']=='budget':action['budget_cents']=workspace_intent.budget(query,w.currency)
  if action['action']=='move':
   import re
   directions=re.findall(r'\b(left|right|forward|back)\b',query.lower())
   if len(directions)!=1:raise ValueError('Choose one direction.')
   action['direction']=directions[0]
  if action['action'] in ('add','move') and __import__('re').search(r"\b(no|not|without|zero)\b",query,__import__('re').I):raise ValueError('This negated request needs explicit review.')
  if __import__('re').search(r'\b(and|then|except|unless|but|at most|at least)\b',query,__import__('re').I) and action['action']!='surface':raise ValueError('Use one edit per request; all coupled constraints will be retained for review.')
 except ValueError as exc:action['action']='clarify';parse_question=str(exc)
 # The actual generative LoRA chooses the investigation tool from observed state.
 current=analyze(w)
 missing=[i for i in w.items if i.dimensions is None or not i.ports_confirmed]
 observed={'discovered':bool(w.items),'decision_facts_missing':min(9,len(missing)),'software_candidate':False,'software_answered':True,'supported_basket':bool(w.items) and current['fit']!='conflict' and current['budget']!='conflict','remaining_steps':8,'budget_cents':w.budget_cents or 0}
 raw,receipt=trained_agent.generate(json.dumps(observed,separators=(',',':')),trained_agent.POLICY,8)
 if raw not in ('search','inspect','clarify','recommend','defer'):raise trained_agent.ModelError('The trained controller returned an invalid tool. Nothing was changed.')
 tools=[{'tool':'read_workspace','result':{'items':len(w.items),'requirements':len(w.requirements),'observed_state':observed}}]
 if raw=='search':
  catalog=json.loads((__import__('pathlib').Path(__file__).parent/'data/evidence-catalog.json').read_text())
  tools.append({'tool':'search','result':{'scope':'Bundled curated catalog only; no current web search or availability claim','products':[{'id':p['id'],'name':p['name'],'kind':p['kind']} for p in catalog['products']]}})
 elif raw=='inspect':
  inspected=(missing or w.items)[:2]
  tools.append({'tool':'inspect','result':[{'id':i.id,'model':i.model or None,'dimensions':i.dimensions.model_dump() if i.dimensions else None,'ports':i.ports if i.ports_confirmed else None,'scope':'Recorded facts only; missing specifications are not invented'} for i in inspected]})
 elif raw=='clarify':tools.append({'tool':'clarify','result':'Confirm exact model, measured dimensions, ownership and your remaining requirements.'})
 elif raw=='recommend':tools.append({'tool':'recommend','result':{'scope':'Review a bounded workspace edit; no spending authority','checks':current}})
 else:
  tools.append({'tool':'defer','result':'No supported recommendation under the observed constraints.'})
  if route['action']=='clarify':parse_question='No supported recommendation yet. Review your unresolved requirements.'
 receipt['router']=route;receipt['tools']=tools+[{'tool':'check_workspace','result':current}]
 target=copy.deepcopy(w);changes=[];op=action['action'];kind=action['kind'];count=action['count'];blocked=[]
 if parse_question:blocked.append(parse_question)
 # Trained proposals are not evidence. Retain EVERY full utterance open, even after applying a suggested edit.
 req=Requirement(id=uuid.uuid4().hex,text=query,status='open')
 target.requirements.append(req)
 if op=='add':
  if count<1:blocked.append('Specify how many items to add.')
  elif len(target.items)+count>48:blocked.append('The workspace supports at most 48 items.')
  else:
   for n in range(count):
    ordinal=sum(i.kind==kind for i in target.items)+1
    target.items.append(Item(id=uuid.uuid4().hex,kind=kind,name=action['label'] or kind.title()+' '+str(ordinal),owned=False,pose={'x':float((ordinal-1)*220-220),'z':0.,'yaw':0.}))
   changes.append(f'Add {count} {kind} item(s), as proposed items with unknown prices and specifications. Review ownership.')
 elif op=='remove':
  rows=[i for i in target.items if i.kind==kind]
  chosen=rows if count==0 else rows[:count]
  if not chosen:blocked.append('There are no matching items to remove.')
  elif any(i.locked for i in chosen):blocked.append('A matching item is locked. Unlock it explicitly first.')
  else:
   ids={i.id for i in chosen};target.items=[i for i in target.items if i.id not in ids];target.connections=[c for c in target.connections if c.source not in ids and c.target not in ids];changes.append(f'Remove {len(ids)} {kind} item(s).')
 elif op=='move':
  rows=[i for i in target.items if i.kind==kind]
  if len(rows)!=1:blocked.append('Select a unique item in the visual editor; this request has no unique target.')
  elif rows[0].locked:blocked.append('This item is locked.')
  elif action['direction']=='none':blocked.append('Specify a direction.')
  else:
   p=rows[0].pose;axis,delta={'left':('x',-100.),'right':('x',100.),'forward':('z',100.),'back':('z',-100.)}[action['direction']];setattr(p,axis,getattr(p,axis)+delta);changes.append('Move '+rows[0].name+' 100 mm '+action['direction']+'.')
 elif op=='surface':
  if action['width_mm'] is None or action['depth_mm'] is None:blocked.append('Enter the width and depth of your surface.')
  else:target.surface=Surface(**{**target.surface.model_dump(),'kind':'desk','width':float(action['width_mm']),'depth':float(action['depth_mm'])});changes.append(f"Use a {action['width_mm']} × {action['depth_mm']} mm desk. Reserved areas must be reviewed.")
 elif op=='none':
  target.surface.kind='none';changes.append('Use no support surface. Physical fit remains unknown; no desk is added.')
 elif op=='budget':
  if action['budget_cents'] is None:blocked.append('Please specify a budget amount and review the currency.')
  else:target.budget_cents=action['budget_cents'];changes.append('Update the budget; currency stays '+w.currency+'.')
 else:blocked.append('This request needs clarification or a specialist. Use the requirement ledger to keep the full request visible.')
 if blocked:
  target=copy.deepcopy(w);target.requirements.append(req);changes=['Keep your request in the requirement ledger; no object or budget changes.']
 # Re-validate ALL fields after edits. A generated edit never bypasses schema or bounds.
 try:target=Workspace.model_validate(target.model_dump())
 except Exception as exc:raise trained_agent.ModelError('The proposed edit exceeds workspace limits. Nothing was changed.') from exc
 return {'source_hash':digest(w),'workspace':target.model_dump(),'changes':changes,'questions':blocked+['Review every part of your request in the ledger. Exact model identity, dimensions, compatibility, ownership and prices are never inferred from a name.'],'analysis':analyze(target),'receipt':receipt,'model_instruction':action,'scope':'One local model-proposed edit per request. Open requirements remain unresolved until you review evidence. No external search, purchase or paid inference.'}
