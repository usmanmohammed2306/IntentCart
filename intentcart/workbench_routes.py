"""Owned, human-triggered workbench operations and non-spending exports."""
import json
from typing import Literal
from fastapi import Request, HTTPException
from fastapi.responses import Response, FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from . import agent, workbench, missions, research, acquisition, finite_budget

class Edit(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=1)
    operation:Literal['requirements','restore_product','withdraw_driver','select_variant','offer',
                      'propose_source','accept_source','undo_preference','delete_preference','edit_preference','revise_goal','import_catalog']
    payload:dict=Field(default_factory=dict)

class Counterfactual(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=1)
    changes:list[dict]=Field(min_length=1,max_length=8)

class CostPreview(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    problem:dict
    costs:dict=Field(default_factory=dict)
    budget:int=Field(ge=0,le=64)

class Clarification(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    text:str=Field(max_length=1000)


def clarify(text):
    result=missions.compile_text(text)
    unsupported=[]
    patterns={'wireless':'wireless','linux':'Linux compatibility','hdr':'HDR','8k':'8K resolution',
              'thunderbolt 5':'Thunderbolt 5','delivery':'delivery date','warranty':'warranty',
              'dolby':'Dolby support','daisy chain':'display daisy chaining','144hz':'144 Hz refresh'}
    lower=text.casefold()
    for token,label in patterns.items():
        if token in lower: unsupported.append(label)
    if any(token in lower for token in ['gaming','hdcp','macos','tax','shipping']):
        unsupported.append('Extra requirements need explicit Workbench fields; no capability was inferred from prose.')
    return {**result,'unsupported':unsupported,'questions':[{'field':f,'prompt':p} for f,p in [
        ('laptop_id','Choose the exact laptop and revision.'),('allow_driver','Will you explicitly permit required display software?'),
        ('shipping','Have tax and shipping costs been reviewed?')]],'applies_automatically':False}


def register(module):
    app=module.app
    def owned(request,db,revision=None,write=False):
        sid,state=module.owner(request,db,write);record=state.get('evidence_agent')
        if not record: raise HTTPException(409,'Start a reviewed evidence task first.')
        if revision is not None and revision!=record['revision']: raise HTTPException(409,'Task changed. Refresh and review again.')
        agent.ensure_current(record)
        return sid,state,record

    @app.get('/workbench')
    def page(): return FileResponse(module.ROOT/'web/workbench.html')

    @app.get('/api/agent/workbench')
    def status(request:Request):
        with module.database() as db:
            try:
                _,_,record=owned(request,db)
                return workbench.summary(record)
            except ValueError as exc: raise HTTPException(409,str(exc)) from exc

    @app.post('/api/agent/workbench')
    def edit(body:Edit,request:Request):
        with module.database() as db:
            try:
                sid,state,record=owned(request,db,body.revision,True)
                new=workbench.mutate(record,body.operation,body.payload)
                state['evidence_agent']=new;state['version']+=1;module.save(db,sid,state)
                return agent.view(new)
            except (ValueError,KeyError,TypeError) as exc: raise HTTPException(409,str(exc)) from exc

    @app.post('/api/agent/counterfactual')
    def counterfactual(body:Counterfactual,request:Request):
        with module.database() as db:
            try:
                _,_,record=owned(request,db,body.revision,True)
                return workbench.counterfactual(record,body.changes)
            except (ValueError,KeyError,TypeError) as exc: raise HTTPException(409,str(exc)) from exc

    @app.post('/api/agent/clarify-query')
    def clarification(body:Clarification,request:Request):
        with module.database() as db: module.owner(request,db,True)
        return clarify(body.text)

    @app.get('/api/agent/report')
    def report(request:Request,format:Literal['text','csv']='text'):
        with module.database() as db:
            try:
                _,_,record=owned(request,db)
                text=workbench.bill_of_materials(record) if format=='csv' else workbench.decision_report(record)
            except (ValueError,KeyError,TypeError) as exc: raise HTTPException(409,str(exc)) from exc
        name='intentcart-bill-of-materials.csv' if format=='csv' else 'intentcart-decision.txt'
        return Response(text,media_type='text/csv' if format=='csv' else 'text/plain',headers={'Content-Disposition':f'attachment; filename="{name}"','Cache-Control':'no-store'})

    @app.get('/research')
    def research_page(): return FileResponse(module.ROOT/'web/roadmap-research.html')

    @app.get('/api/roadmap/evaluation')
    def report_data(kind:Literal['budget','preferences']='budget',full:bool=False):
        try:
            report=research.read_report(kind)
            return report if full else {k:v for k,v in report.items() if k not in ('records','models')}
        except research.EvidenceError as exc: raise HTTPException(409,str(exc)) from exc

    @app.post('/api/research/cost-preview')
    def cost_preview(body:CostPreview,request:Request):
        with module.database() as db:module.owner(request,db,True)
        try:
            p=acquisition.load_problem(body.problem)
            if len(p.queries)>6 or len(p.worlds)>32 or sum(q.cost for q in p.queries)>64:
                raise ValueError('Interactive preview supports at most six queries, 32 worlds and total cost 64.')
            if body.costs:p=finite_budget.edit_costs(p,body.costs)
            if sum(q.cost for q in p.queries)>64:raise ValueError('Edited costs exceed interactive limit.')
            reference=finite_budget.BudgetReference(p)
            value=reference.decide(budget=min(body.budget,sum(q.cost for q in p.queries)))
            return {'schema':'intentcart-cost-preview/1','action':value,'source':'explicit hypothetical finite world model','checkout_supported':False,'changes_saved':False}
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
