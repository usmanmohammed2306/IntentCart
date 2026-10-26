"""Durable bounded plan–research–inspect–verify controller, using the trained local LLM."""
import copy,json,uuid,os
from functools import lru_cache
from datetime import date
from . import trained_agent,device_research as research,planning_engine as engine
from .planning_models import Planning,DeviceSelection
from .workspace import Workspace,digest
from .planning_compiler import compile_request

def _stamp(path):
 st=os.stat(path);return (path,st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
_SOURCE_FILES=('planning_models.py','planning_engine.py','planning_compiler.py','planning_runs.py','device_research.py','trained_agent.py','workspace_intent.py','planning_routes.py','planning_merge.py','workspace.py')
from pathlib import Path as _Path
_SOURCE_PATHS=tuple(str(_Path(__file__).parent/n) for n in _SOURCE_FILES)+ (str(_Path(__file__).parent/'data/device-library.json'),)
@lru_cache(maxsize=16)
def _source_identity_verified(stamp,adapter_sha,serving_sha,extra_json):
 from pathlib import Path
 import hashlib
 base=Path(__file__).parent;code={n:hashlib.sha256((base/n).read_bytes()).hexdigest() for n in _SOURCE_FILES}
 return research.digest({'code':code,'model':adapter_sha,'serving':serving_sha,'library':[{'id':d['id'],'digest':d['digest']} for d in research.catalog()+json.loads(extra_json)]})
def source_identity(extra=()):
 from pathlib import Path
 stamp=tuple(_stamp(f) for f in _SOURCE_PATHS);model=trained_agent.identity()
 return _source_identity_verified(stamp,model['adapter_sha256'],model.get('serving_sha256'),json.dumps(list(extra),sort_keys=True,separators=(',',':')))

def create(body,extra=()):
 original=research.digest({'workspace':body.workspace.model_dump(),'planning':body.planning.model_dump()});w,p,coverage=compile_request(body.workspace,body.planning,body.query)
 return {'original_workspace':body.workspace.model_dump(),'original_planning':body.planning.model_dump(),'id':uuid.uuid4().hex,'revision':0,'status':'RUNNING','workspace':w.model_dump(),'planning':p.model_dump(),'source_hash':original,'source_identity':source_identity(extra),'review_day':date.today().isoformat(),'project_id':body.project_id,'project_revision':body.project_revision,'query':body.query,'coverage':coverage,'max_steps':body.max_steps,'step_count':0,'discovered':False,'inspected':[],'events':[],'questions':list(coverage['unrepresented']),'candidates':[],'source_consent':body.source_consent,'research_urls':body.research_urls,'source_documents':[],'scope':'No purchases, account changes, software approval or paid model calls. Public research requires explicit consent.'}

def advance(record,extra=()):
 run=copy.deepcopy(record)
 if run['status']!='RUNNING':raise ValueError('This plan is paused or finished. Update the inputs and start a reviewed continuation.')
 if run['step_count']>=run['max_steps']:run['status']='STEP_LIMIT';return run
 if run['source_identity']!=source_identity(extra) or run['review_day']!=date.today().isoformat():run['status']='STALE';run['questions'].append('Sources or review day changed. Start a new plan with current facts.');return run
 w=Workspace.model_validate(run['workspace']);p=Planning.model_validate(run['planning']);bindings={b.item_id:b for b in p.devices};pending=[b.item_id for b in p.devices if b.reviewed and b.item_id not in run['inspected']]
 if run['discovered'] and not pending and not run['candidates']:
  candidates,questions=engine.candidate_designs(w,p,extra);run['candidates']=candidates[:4];run['searched_candidates']=len(candidates);run['questions'].extend(questions)
 inspection_w=w;inspection_p=p
 if run['candidates']:
  inspection_w=Workspace.model_validate(run['candidates'][0]['workspace']);inspection_p=Planning.model_validate(run['candidates'][0]['planning']);pending=[b.item_id for b in inspection_p.devices if b.reviewed and b.item_id not in run['inspected']]
 ready=bool(run['candidates'] and run['candidates'][0].get('scope_assessment',run['candidates'][0]['assessment'])['status'] in ('READY','READY_WITH_CAVEATS') and not run['questions'])
 software=any(engine.resolve(inspection_w,inspection_p,extra)['facts'].get(i.id,{}).get('driver_required') is True for i in inspection_w.items if i.kind=='dock')
 observed={'discovered':run['discovered'],'decision_facts_missing':min(9,len(pending)),'software_candidate':software,'software_answered':p.allow_driver is not None,'supported_basket':ready,'remaining_steps':run['max_steps']-run['step_count'],'budget_cents':w.budget_cents or 0}
 raw,receipt=trained_agent.generate(json.dumps(observed,separators=(',',':')),trained_agent.POLICY,8);run['step_count']+=1
 event={'step':run['step_count'],'model_tool':raw,'model_receipt':receipt,'observed_state':observed}
 if raw=='search' and not run['discovered']:
  discoveries=[]
  for i in w.items:
   if i.id in bindings:continue
   rows=research.lookup(i.model or i.name,i.kind,tuple(extra)+tuple(engine.profile_dict(v) for v in p.profiles));discoveries.append({'item_id':i.id,'query':i.model or i.name,'candidates':[{'id':d['id'],'name':d['name'],'configurations':list(d['configurations']),'digest':d['digest']} for d in rows]})
   if any(g.kind=='identity' and (not g.item_id or g.item_id==i.id) for g in p.goals):run['questions'].append('Confirm exact identity/configuration for '+i.name+'.')
  public_reads=[]
  if run.get('source_consent'):
   for url in run.get('research_urls',[])[:2]:
    try:
     doc=research.fetch(url,consent=True);run['source_documents'].append(doc);public_reads.append({'url':doc['url'],'source_id':doc['id'],'bytes':doc['bytes'],'status':'read_requires_review'})
    except (ValueError,OSError) as exc:public_reads.append({'url':url,'status':'unavailable','error':str(exc)[:300]})
  event['result']={'public_reads':public_reads,'discoveries':discoveries,'notice':'Names produce candidates, not an assumed identity. Use Research to confirm exact variant and state.'};run['discovered']=True
 elif raw=='inspect' and pending:
  selected=pending[:2];facts=engine.resolve(inspection_w,inspection_p,extra);event['result']={'inspected_items':[{'item_id':i,'facts':facts['facts'].get(i,{}),'identity':facts['identities'].get(i,{}).get('name'),'sources':facts['identities'].get(i,{}).get('sources',[])} for i in selected],'source_issues':facts['issues']};run['inspected']+=selected
 elif raw=='clarify' and software and p.allow_driver is None:
  run['status']='NEEDS_INFO';run['questions'].append('May this exact setup use DisplayLink software? The agent cannot grant permission. Set Allow driver explicitly, or choose Denied.');event['result']={'question':'software_permission'}
 elif raw=='recommend' and ready:
  run['status']='READY_FOR_REVIEW';best=run['candidates'][0];event['result']={'selected_candidate':0,'assessment':best['assessment'],'alternatives':len(run['candidates'])};scope=best.get('scope_assessment') or engine.scope_assessment(Workspace.model_validate(best['workspace']),Planning.model_validate(best['planning']),extra);run['state_reports']=scope['states'];run['procurement']=scope['procurement']
 elif raw=='defer' and run['discovered'] and not pending:
  best=run['candidates'][0] if run['candidates'] else None
  run['status']='NEEDS_INFO' if run['questions'] or best and best.get('scope_assessment',best['assessment'])['status']=='NEEDS_INFO' else 'CONSTRAINTS_UNMET'
  if best:
   run['questions']+=best.get('scope_assessment',{}).get('issues',[])
   run['questions']+= [g['text']+': '+g['reason'] for g in best['assessment']['goals'] if g['required'] and g['status'] in ('unknown','unmet')]
   run['questions']+= [i['message'] for i in best['assessment']['source_issues']]
   if best['placement']['status'] in ('search_limit','no_layout_in_search'):run['status']='SEARCH_LIMIT'
  event['result']={'reason':'No fully supported candidate under the current goals, facts and bounded search. Deferral is not task success.'}
 else:
  run['status']='MODEL_PAUSED';event['result']={'rejected':True,'reason':'The trained controller selected a tool whose prerequisites were not met. No deterministic policy was substituted.'}
 run['events'].append(event);run['questions']=list(dict.fromkeys(run['questions']))[:40]
 if run['status']=='RUNNING' and run['step_count']>=run['max_steps']:run['status']='STEP_LIMIT'
 return run

def brief(run):
 run=copy.deepcopy(run)
 for c in run.get('candidates',[]):c['planning']['driver_permission_token']=None
 best=run['candidates'][0] if run.get('candidates') else None
 return {'schema':'intentcart-planning-brief/1','run_id':run['id'],'status':run['status'],'query':run['query'],'input_digest':run['source_hash'],'source_identity':run['source_identity'],'review_day':run['review_day'],'coverage':run['coverage'],'questions':run['questions'],'proposal':best,'states':run.get('state_reports',[]),'procurement':run.get('procurement',{}),'tools':[{'step':e['step'],'tool':e['model_tool'],'result':e.get('result'),'model_id':e['model_receipt'].get('model_id'),'cache_hit':e['model_receipt'].get('cache_hit',False),'inference_performed':e['model_receipt'].get('inference_performed'),'decision_id':e['model_receipt'].get('decision_id')} for e in run['events']],'scope':run['scope'],'truth':'Content fingerprints are not signatures or proof that user declarations are true. Unknown facts and subjective judgments remain explicit.'}
