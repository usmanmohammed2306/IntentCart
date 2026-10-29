"""Local model-directed setup inspection with independently checked layout proposals."""
import copy,hashlib,json,threading,uuid
from functools import lru_cache
from typing import TypedDict
from fastapi import HTTPException,Request
from pydantic import Field
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from .workspace import Strict,Workspace,Item
from .planning_models import Planning
from . import planning_engine as engine,trained_agent,procurement

class VisualItem(Item):
    id:str=Field(min_length=1,max_length=200)
class VisualWorkspace(Workspace):
    items:list[VisualItem]=Field(default_factory=list,max_length=48)
class Design(Strict):
    workspace:VisualWorkspace
    team_id:str=Field(default='',max_length=64)
    request_id:str=Field(default='',max_length=64)
    revision:int=Field(default=0,ge=0)
    fingerprint:str=Field(default='',max_length=64)
    client_id:str=Field(pattern=r'^[a-f0-9]{32}$')

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def canonical(visual):
    value=visual.model_dump();mapping={i['id']:'i'+str(n) for n,i in enumerate(value['items'])};reverse={v:k for k,v in mapping.items()}
    for i in value['items']:i['id']=mapping[i['id']]
    for c in value['connections']:c['source']=mapping[c['source']];c['target']=mapping[c['target']]
    return Workspace.model_validate(value),reverse
def restore(value,reverse):
    value=value.model_dump()
    for i in value['items']:i['id']=reverse[i['id']]
    for c in value['connections']:c['source']=reverse[c['source']];c['target']=reverse[c['target']]
    return value

def team_facts(db,uid,body):
    if not body.team_id and not body.request_id:return None,[]
    if not body.team_id or not body.request_id:raise HTTPException(422,'Select an employee setup first.')
    procurement.member(db,body.team_id,uid)
    row=procurement.request_row(db,body.team_id,body.request_id);current=procurement.view(db,row)
    if row['revision']!=body.revision or current['plan']['fingerprint']!=body.fingerprint:raise HTTPException(409,'The setup changed. Refresh before asking again.')
    choices=[]
    for screens in range(3):
        candidate=dict(row);need=copy.deepcopy(current['data']);need['screens']=screens;candidate['data']=json.dumps(need)
        p=procurement.plan(db,candidate)
        choices.append({'screens':screens,'total_cents':p['total_cents'],'reuse_count':len(p['reuse']),'purchase_units':sum(v['quantity'] for v in p['purchase']),'ready':p['ready'],'missing':[c['key'] for c in p['checks'] if not c['ok']]})
    return {'revision':row['revision'],'fingerprint':current['plan']['fingerprint'],'catalog':procurement.CATALOG_HASH,'ready':current['plan']['ready'],'approval_current':current['approval_current'],'state':row['state']},choices

class State(TypedDict,total=False):
    original:Workspace
    candidate:Workspace
    missing:list[str]
    placement:dict
    physical:dict
    receipt:dict
    tool:str
    status:str
    events:list

@lru_cache(maxsize=1)
def graph():
    g=StateGraph(State)
    def observe(s):
        w=s['original'];missing=[i.id for i in w.items if not i.dimensions or i.dimensions.basis=='illustrative']
        return {'candidate':w,'placement':{'status':'not_run','nodes':0},'missing':missing,'physical':engine.physical(w,Planning()),'events':[{'tool':'read_setup','items':len(w.items),'missing_measurements':len(missing)}]}
    def decide(s):
        surface=s['original'].surface
        complete=not s['missing'] and surface.kind in ('desk','shared','shelf') and surface.width is not None and surface.depth is not None
        observed={'discovered':True,'decision_facts_missing':min(9,len(s['missing'])),'software_candidate':False,'software_answered':True,'supported_basket':complete,'remaining_steps':3,'budget_cents':s['original'].budget_cents or 0}
        raw,receipt=trained_agent.generate(json.dumps(observed,separators=(',',':')),trained_agent.POLICY,8)
        if raw not in ('search','inspect','clarify','recommend','defer'):raise trained_agent.ModelError('The model returned an unsupported tool. Nothing was changed.')
        return {'tool':raw,'receipt':receipt,'events':s['events']+[{'tool':raw,'model_id':receipt['model_id'],'inference_performed':receipt['inference_performed'],'layout_inputs_complete':complete}]}
    def arrange(s):
        candidate,placement=engine.arrange(s['original'],Planning(),node_limit=6000)
        return {'candidate':candidate,'placement':placement,'events':s['events']+[{'tool':'arrange_footprints','status':placement['status'],'search_nodes':placement['nodes']}]}
    def inspect(s):
        return {'events':s['events']+[{'tool':'inspect_measurements','missing_items':s['missing'],'surface_measured':s['original'].surface.width is not None and s['original'].surface.depth is not None}]}
    def verify(s):
        # The model cannot declare a fit. Recompute geometry independently.
        physical=engine.physical(s['candidate'],Planning());ready=s['tool']=='recommend' and s['placement']['status']=='found' and physical['status']=='pass'
        status='READY_FOR_REVIEW' if ready else 'NEEDS_MEASUREMENTS' if s['missing'] or s['placement']['status']=='needs_measurements' else 'SEARCH_LIMIT' if s['placement']['status']=='search_limit' else 'MODEL_PAUSED' if s['tool']=='recommend' else 'NEEDS_REVIEW'
        return {'status':status,'physical':physical,'events':s['events']+[{'tool':'verify_footprints','status':physical['status']}]}
    g.add_node('observe',observe);g.add_node('model',decide);g.add_node('inspect',inspect);g.add_node('arrange',arrange);g.add_node('verify',verify)
    g.add_edge(START,'observe');g.add_edge('observe','model')
    g.add_conditional_edges('model',lambda s:'arrange' if s['tool']=='recommend' else 'inspect' if s['tool'] in ('search','inspect') else 'verify',{'arrange':'arrange','inspect':'inspect','verify':'verify'})
    g.add_edge('arrange','verify');g.add_edge('inspect','verify');g.add_edge('verify',END)
    return g.compile()

_active=threading.Lock()
def register(module):
    @module.app.post('/api/setup/autopilot')
    def start(body:Design,request:Request):
        input_hash=digest(body.model_dump(exclude={'client_id'}))
        with module.database() as db:
            sid,state=module.owner(request,db,True);uid=state.get('account_id')
            from . import accounts
            uid=accounts.current(request,db)['id']
            binding,choices=team_facts(db,uid,body)
            saved=state.get('setup_autopilot',{}).get(body.client_id)
            if saved:
                if saved['input_hash']!=input_hash:raise HTTPException(409,'This action ID belongs to a different setup.')
                if saved['binding']!=binding:raise HTTPException(409,'This saved proposal is no longer current.')
                return saved
        if not body.workspace.items:raise HTTPException(422,'Add equipment before asking the agent.')
        if not _active.acquire(blocking=False):raise HTTPException(429,'The local agent is busy. Your setup is unchanged.')
        try:
            w,reverse=canonical(body.workspace)
            with tracing_context(enabled=False):out=graph().invoke({'original':w},config={'recursion_limit':7,'callbacks':[]})
            result={'schema':'intentcart-setup-autopilot/1','id':body.client_id,'input_hash':input_hash,'status':out['status'],'candidate':restore(out['candidate'],reverse) if out['status']=='READY_FOR_REVIEW' else None,'missing_items':[reverse[i] for i in out['missing']],'placement':out['placement'],'physical':out['physical'],'alternatives':choices,'binding':binding,'receipt':out['receipt'],'events':out['events'],'scope':'User-declared in-use bounding footprints; bounded placement search, not physical certification. Quote alternatives come from the current team records. No reservation, purchase or approval performed.'}
            with module.database() as db:
                sid,state=module.owner(request,db,True);new_binding,_=team_facts(db,uid,body)
                if new_binding!=binding:raise HTTPException(409,'Facts changed during planning. Nothing was applied.')
                rows=state.setdefault('setup_autopilot',{});rows[body.client_id]=result
                while len(rows)>8:del rows[next(iter(rows))]
                state['version']+=1;module.save(db,sid,state)
            return result
        except trained_agent.ModelError as exc:raise HTTPException(503,str(exc)) from exc
        finally:_active.release()
    @module.app.get('/api/setup/autopilot/{run_id}')
    def read(run_id:str,request:Request):
        with module.database() as db:
            _,state=module.owner(request,db);row=state.get('setup_autopilot',{}).get(run_id)
            if not row:raise HTTPException(404,'Plan not found in this account.')
            return row

    from . import seamless
    seamless.register(module)
