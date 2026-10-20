from fractions import Fraction
from copy import deepcopy
import itertools
import pytest
from intentcart import acquisition as a,finite_budget as b
from scripts.evaluate_budget_roadmap import problem


def brute(problem,state,remaining):
    if a._consensus(problem,state)[0]:return Fraction(1),Fraction(0)
    choices=[(Fraction(0),Fraction(0))]
    for qi,q in enumerate(problem.queries):
        if q.cost>remaining:continue
        parts=a._partitions(problem,state,qi)
        if len(parts)<2:continue
        mass=sum(problem.worlds[i].weight for i in state);p=Fraction(0);cost=Fraction(q.cost)
        for branch in parts:
            pp,cc=brute(problem,branch,remaining-q.cost);weight=Fraction(sum(problem.worlds[i].weight for i in branch),mass)
            p+=weight*pp;cost+=weight*cc
        choices.append((p,cost))
    return min(choices,key=lambda x:(-x[0],x[1]))


def test_budget_reference_matches_independent_exhaustive_tree_enumeration():
    for seed in range(4):
        p=problem(seed,3);ref=b.BudgetReference(p)
        for budget in range(sum(q.cost for q in p.queries)+1):
            expected=brute(p,tuple(range(len(p.worlds))),budget)
            observed=ref.value(tuple(range(len(p.worlds))),budget)
            assert observed[:2]==expected
            for w in p.worlds:
                row=b.episode(p,w.id,lambda obs,left:ref.decide(obs,left),budget)
                assert row['spent']<=budget
                if row['status'] in ('DECIDED','INFEASIBLE'):assert row['supported']


def test_cost_editor_preserves_original_and_rejects_invalid_costs():
    p=problem(12);updated=b.edit_costs(p,{'q0':9})
    assert updated.queries[0].cost==9 and p.queries[0].cost!=9
    for values in [{'q0':True},{'made-up':1},{'q0':0}]:
        with pytest.raises(a.ProblemError):b.edit_costs(p,values)


def test_budget_conditioned_learning_and_ablations_are_bounded_and_deterministic():
    train=[problem(i,3) for i in [100,101]];p=problem(302)
    model=b.fit(train);assert model==b.fit(train)
    assert model['features'][-1]=='remaining_budget_fraction' and model['research_only'] is True
    for model in [model,b.fit(train,'unrestricted'),b.fit(train,mask=[7]),b.fit(train,mask=[1,2,3,4])]:
        for w in p.worlds:
            for ceiling in [0,3,8,20]:
                row=b.episode(p,w.id,lambda obs,left:b.decide(p,model,obs,left),ceiling)
                assert row['spent']<=ceiling
                if row['status'] in ('DECIDED','INFEASIBLE'):assert row['supported']
    bad=deepcopy(model);bad['scale'][0]=0
    with pytest.raises(a.ProblemError):b.decide(p,bad,[],3)
