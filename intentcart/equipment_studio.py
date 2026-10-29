"""Bring-your-own equipment discovery and evidence-bound setup passport.
No shopping, network, approval or model calls are made by these checks.
"""
import copy
from fastapi import Request,HTTPException
from . import device_research as research,planning_engine as engine
from .planning_models import Goal
from .planning_routes import Design,profiles,validated_permission

def passport(w,p,extra=()):
    p=copy.deepcopy(p)
    mandatory=[('identity',True,'Exact models'),('surface_fit',True,'Desk fit'),('connections',True,'Connections')]
    if any(not i.owned for i in w.items):mandatory.append(('availability',True,'Purchase availability'))
    if w.budget_cents is not None:mandatory.append(('budget',w.budget_cents,'Complete cost'))
    screens=sum(i.kind=='monitor' for i in w.items)
    if screens and any(i.kind in ('laptop','desktop') for i in w.items):mandatory.append(('native_displays',screens,'Native screen count'))
    # Reserved required check IDs cannot be shadowed by optional imported goals.
    p.goals=[g for g in p.goals if not g.id.startswith('passport_')]
    for kind,value,text in mandatory:
        p.goals.append(Goal(id='passport_'+kind,kind=kind,value=value,text=text,required=True))
    assessment=engine.evaluate(w,p,extra)
    resolved=engine.resolve(w,p,extra)
    checks=[g for g in assessment['goals'] if g['required']]
    nodes=[]
    for i in w.items:
        d=resolved['identities'].get(i.id)
        issues=[v for v in resolved['issues'] if v.get('item_id')==i.id]
        nodes.append(dict(id=i.id,name=i.name,kind=i.kind,owned=i.owned,identity='linked' if d and not issues else 'needs_review',profile_id=d['id'] if d else None,sources=d['sources'] if d else [],needs_measurement=not i.dimensions or i.dimensions.basis=='illustrative'))
    blockers=[dict(check=g['kind'],status=g['status'],reason=g['reason']) for g in checks if g['status'] not in ('met','qualified')]
    # Explicitly scoped what-if: same already-owned hardware minus an optional dock.
    alternatives=[]
    docks=[i for i in w.items if i.kind=='dock' and not i.locked]
    for dock in docks[:4]:
        trial=copy.deepcopy(w);trial.items=[i for i in trial.items if i.id!=dock.id];trial.connections=[e for e in trial.connections if dock.id not in (e.source,e.target)]
        context=copy.deepcopy(p);context.devices=[b for b in context.devices if b.item_id!=dock.id]
        outcome=engine.evaluate(trial,context,extra)
        alternatives.append(dict(label='Without '+dock.name,remove_id=dock.id,connections=outcome['connections']['status'],physical=outcome['physical']['status'],total_minor=outcome['cost']['total_minor'],status=outcome['status'],scope='Comparison only; retained evidence must still qualify every route. No item is removed.'))
    return dict(schema='intentcart-setup-passport/1',input_digest=research.digest({'workspace':w.model_dump(),'planning':p.model_dump()}),status=assessment['status'],checks=checks,nodes=nodes,routes=assessment['connections']['routes'],questions=assessment['connections'].get('questions',[]),blockers=blockers,source_issues=assessment['source_issues'],alternatives=alternatives,cost=assessment['cost'],scope='Recorded exact configurations, declared operating footprints and bounded connection rules. Unknown facts remain unresolved. Not physical certification, supplier approval or payment authorization.')

def register(module):
    @module.app.get('/api/equipment/catalog')
    def catalog():
        return {'devices':research.catalog(),'scope':'All built-in research profiles in this preview; not the entire hardware market. No price or stock feed.','desk_templates':[{'id':'compact','name':'Compact desk','width':1200,'depth':600},{'id':'standard','name':'Everyday desk','width':1600,'depth':800},{'id':'wide','name':'Wide desk','width':1800,'depth':800}]}
    @module.app.get('/api/equipment/personal-catalog')
    def personal_catalog(request:Request):
        with module.database() as db:
            _,state=module.owner(request,db);return {'devices':profiles(state)}
    @module.app.post('/api/equipment/check')
    def check(body:Design,request:Request):
        with module.database() as db:
            _,state=module.owner(request,db,True);extra=profiles(state)
            body.planning=validated_permission(body.workspace,body.planning,state)
        try:return passport(body.workspace,body.planning,extra)
        except (ValueError,TypeError,KeyError) as exc:raise HTTPException(422,str(exc)) from exc
