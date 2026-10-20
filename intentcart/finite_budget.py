"""Exact finite-budget completion reference and bounded CPU imitation research.

Objective: maximize prior probability of a certified decision within the
remaining budget, then minimize expected inspection cost. No true world,
network, payment authority or calibrated customer probability enters a policy.
"""
from fractions import Fraction
from functools import lru_cache
import numpy as np
from . import acquisition as acq, learned_acquisition as learned

FEATURES=(*learned.FEATURES,'remaining_budget_fraction')

class BudgetReference:
    def __init__(self,problem):
        self.problem=problem;self.states=0
        self._value=lru_cache(maxsize=acq.MAX_STATES)(self._solve)

    def _solve(self,state,budget):
        self.states+=1
        if self.states>acq.MAX_STATES:raise acq.StateLimit('Finite-budget state limit exceeded.')
        if not state:return Fraction(0),Fraction(0),None
        if acq._consensus(self.problem,state)[0]:return Fraction(1),Fraction(0),None
        choices=[]
        for qi,q in enumerate(self.problem.queries):
            if q.cost>budget or len(acq._partitions(self.problem,state,qi))<2:continue
            completion,cost=self.action_value(state,budget,qi)
            choices.append((-completion,cost,q.id,qi))
        if not choices:return Fraction(0),Fraction(0),None
        neg_completion,cost,_,qi=min(choices)
        # Never pay for zero attainable certification probability.
        return (-neg_completion,cost,qi) if neg_completion<0 else (Fraction(0),Fraction(0),None)

    def action_value(self,state,budget,qi):
        q=self.problem.queries[qi]
        if q.cost>budget:raise acq.ProblemError('Query exceeds remaining budget.')
        mass=sum(self.problem.worlds[i].weight for i in state)
        completion,cost=Fraction(0),Fraction(q.cost)
        for branch in acq._partitions(self.problem,state,qi):
            probability=Fraction(sum(self.problem.worlds[i].weight for i in branch),mass)
            p,c,_=self._value(branch,budget-q.cost)
            completion+=probability*p;cost+=probability*c
        return completion,cost

    def value(self,state,budget):
        if type(budget) is not int or not 0<=budget<=sum(q.cost for q in self.problem.queries):raise acq.ProblemError('Invalid finite budget.')
        return self._value(tuple(state),budget)

    def decide(self,observations=(),budget=None):
        if budget is None:budget=sum(q.cost for q in self.problem.queries)
        if type(budget) is not int or not 0<=budget<=sum(q.cost for q in self.problem.queries):raise acq.ProblemError('Invalid finite budget.')
        state,_,_=acq.posterior(self.problem,observations)
        if not state:return {'status':'CONFLICT','decision':None}
        certain,decision=acq._consensus(self.problem,state)
        if certain:return {'status':'INFEASIBLE' if decision is None else 'DECIDED','decision':decision}
        probability,cost,qi=self.value(state,budget)
        meta={'completion_probability':float(probability),'expected_cost':float(cost),
              'objective':'maximum finite-prior certified completion, then minimum expected inspection cost'}
        if qi is None:return {'status':'BUDGET_EXHAUSTED','decision':None,**meta}
        q=self.problem.queries[qi]
        return {'status':'QUERY','query_id':q.id,'version':q.version,'cost':q.cost,**meta}


def edit_costs(problem,payload):
    """Pure counterfactual cost editor. Never changes the original problem."""
    if type(payload) is not dict or not payload or set(payload)-{q.id for q in problem.queries}:raise acq.ProblemError('Supply known query costs.')
    from dataclasses import replace
    queries=[]
    for q in problem.queries:
        value=payload.get(q.id,q.cost);acq._integer(value,'query cost')
        queries.append(replace(q,cost=value))
    return replace(problem,revision=problem.revision+'-cost-review',queries=tuple(queries))


def vector(problem,state,qi,budget):
    return np.r_[learned.feature_vector(problem,state,qi),budget/sum(q.cost for q in problem.queries)]


def fit(problems,teacher='finite',mask=()):
    if teacher not in ('finite','unrestricted') or not 1<=len(problems)<=32:raise acq.ProblemError('Invalid bounded training protocol.')
    if any(type(i) is not int or not 0<=i<len(FEATURES) for i in mask):raise acq.ProblemError('Invalid feature ablation.')
    xs=[];ys=[]
    for problem in problems:
        reference=BudgetReference(problem);unrestricted=acq.ExactReference(problem)
        queue=[tuple(range(len(problem.worlds)))];seen=set()
        while queue:
            state=queue.pop()
            if state in seen or acq._consensus(problem,state)[0]:continue
            seen.add(state)
            if len(seen)>2000:raise acq.StateLimit('Training-state limit exceeded.')
            for qi,q in enumerate(problem.queries):
                branches=acq._partitions(problem,state,qi)
                if len(branches)<2:continue
                queue.extend(branches)
                for budget in range(q.cost,sum(x.cost for x in problem.queries)+1):
                    if teacher=='finite':
                        p,c=reference.action_value(state,budget,qi);target=[float(p),float(c)]
                    else:
                        mass=sum(problem.worlds[i].weight for i in state)
                        cost=Fraction(q.cost)+sum(Fraction(sum(problem.worlds[i].weight for i in branch),mass)*unrestricted.solve(branch)[0] for branch in branches)
                        target=[-float(cost),float(cost)]
                    x=vector(problem,state,qi,budget);x[list(mask)]=0;xs.append(x);ys.append(target)
                    if len(xs)>100000:raise acq.StateLimit('Training-row limit exceeded.')
    if not xs:raise acq.ProblemError('No informative training rows.')
    x=np.stack(xs);y=np.array(ys);mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale==0]=1
    design=np.column_stack([np.ones(len(x)),(x-mean)/scale]);penalty=np.eye(design.shape[1]);penalty[0,0]=0
    coefficients=np.linalg.solve(design.T@design+penalty,design.T@y)
    return {'schema':'intentcart-budget-imitation/1','features':list(FEATURES),'mask':list(mask),'teacher':teacher,
            'mean':mean.tolist(),'scale':scale.tolist(),'coefficients':coefficients.tolist(),
            'training_structures':len(problems),'training_rows':len(xs),'research_only':True}


def decide(problem,model,observations=(),budget=None):
    if model.get('schema')!='intentcart-budget-imitation/1' or model.get('features')!=list(FEATURES):raise acq.ProblemError('Invalid budget-conditioned model.')
    mean,scale,coef=(np.asarray(model[k],dtype=float) for k in ('mean','scale','coefficients'))
    if mean.shape!=(8,) or scale.shape!=(8,) or coef.shape!=(9,2) or not all(np.isfinite(v).all() for v in (mean,scale,coef)) or (scale<=0).any():raise acq.ProblemError('Invalid model parameters.')
    if budget is None:budget=sum(q.cost for q in problem.queries)
    if type(budget) is not int or budget<0:raise acq.ProblemError('Invalid remaining budget.')
    mask=model.get('mask',[])
    if type(mask) is not list or any(type(i) is not int or not 0<=i<8 for i in mask):raise acq.ProblemError('Invalid feature mask.')
    state,_,_=acq.posterior(problem,observations)
    if not state:return {'status':'CONFLICT','decision':None}
    certain,answer=acq._consensus(problem,state)
    if certain:return {'status':'INFEASIBLE' if answer is None else 'DECIDED','decision':answer}
    choices=[]
    for qi,q in enumerate(problem.queries):
        if q.cost>budget or len(acq._partitions(problem,state,qi))<2:continue
        x=vector(problem,state,qi,budget);x[mask]=0;prediction=np.r_[1.,(x-mean)/scale]@coef
        choices.append((-prediction[0],prediction[1],q.id,qi))
    if not choices:return {'status':'BUDGET_EXHAUSTED','decision':None}
    q=problem.queries[min(choices)[3]]
    return {'status':'QUERY','query_id':q.id,'version':q.version,'cost':q.cost}


def episode(problem,world_id,policy,budget):
    truth=next((w for w in problem.worlds if w.id==world_id),None)
    if truth is None:raise acq.ProblemError('Unknown simulation world.')
    acq._integer(budget,'episode budget',0,1000000)
    observations=[];spent=0;trace=[]
    for _ in range(len(problem.queries)+1):
        action=policy(observations,budget-spent)
        if action['status']!='QUERY':
            supported=action['status'] in ('DECIDED','INFEASIBLE') and action.get('decision')==truth.decision
            return {'status':action['status'],'supported':supported,'spent':spent,'budget':budget,'trace':trace,'decision':action.get('decision')}
        qi=next((i for i,q in enumerate(problem.queries) if q.id==action['query_id']),None)
        if qi is None:raise acq.ProblemError('Policy selected an unknown query.')
        q=problem.queries[qi]
        if q.id in {o['query_id'] for o in observations} or q.cost>budget-spent:raise acq.ProblemError('Invalid repeated or unaffordable policy action.')
        observation={'query_id':q.id,'version':q.version,'value':truth.answers[qi]}
        observations.append(observation);spent+=q.cost;trace.append({**observation,'cost':q.cost})
    raise acq.ProblemError('Policy exceeded the query bound.')
