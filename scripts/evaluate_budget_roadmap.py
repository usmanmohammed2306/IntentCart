"""Frozen local learning curves, teacher/feature ablations and prior/cost shifts."""
import argparse
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
import hashlib,itertools,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from intentcart import acquisition as acq,finite_budget as budget


def problem(seed,queries=4):
    entries=[]
    for index,bits in enumerate(itertools.product((0,1),repeat=queries)):
        decision=('plan-A' if sum(bits[:3])>=2 else 'plan-B') if seed%3==0 else ('plan-A' if (bits[0] and bits[1]) or bits[-1] else 'plan-B') if seed%3==1 else ('plan-A' if bits[0]^bits[-1] else None)
        entries.append({'id':f'w{index}','weight':1+(index*7+seed)%4,'answers':{f'q{i}':str(b) for i,b in enumerate(bits)},'decision':decision})
    return acq.load_problem({'schema':acq.SCHEMA,'id':f'finite-{seed}','revision':'1','queries':[{'id':f'q{i}','cost':1+(seed+i*3)%5,'version':'1'} for i in range(queries)],'worlds':entries,'initial_evidence':[]})


def evaluate():
    protocol=json.loads((ROOT/'docs/protocols/roadmap-offline.json').read_text())
    train=[problem(seed,3) for seed in protocol['training_seeds']]
    models={f'finite_student_{n}':budget.fit(train[:n]) for n in protocol['training_sizes']}
    models['unrestricted_student']=budget.fit(train,teacher='unrestricted')
    models['no_budget_feature']=budget.fit(train,mask=[7])
    models['no_information_features']=budget.fit(train,mask=[1,2,3,4])
    records=[]
    for shift in protocol['test_shifts']:
        for seed in protocol['test_seeds']:
            p=problem(seed)
            if shift=='prior':p=replace(p,worlds=tuple(replace(w,weight=1+(i*seed)%13) for i,w in enumerate(p.worlds)))
            if shift=='cost':p=budget.edit_costs(p,{q.id:1+(seed+i*5)%9 for i,q in enumerate(p.queries)})
            ref=budget.BudgetReference(p);unrestricted=acq.ExactReference(p)
            for fraction in protocol['budget_fractions']:
                ceiling=int(sum(q.cost for q in p.queries)*fraction)
                for name in protocol['policies']:
                    if name=='finite_exact':actor=lambda obs,left:ref.decide(obs,left)
                    elif name=='unrestricted_exact':actor=lambda obs,left:acq.decide(p,obs,'exact',left,unrestricted)
                    else:actor=lambda obs,left:budget.decide(p,models[name],obs,left)
                    mass=sum(w.weight for w in p.worlds);episodes=[]
                    for world in p.worlds:
                        row=budget.episode(p,world.id,actor,ceiling)
                        episodes.append({'world':world.id,'weight':world.weight,**row})
                    records.append({'shift':shift,'problem':p.id,'policy':name,'budget_fraction':fraction,'budget':ceiling,
                                    'supported_probability':sum(w['weight'] for w in episodes if w['supported'])/mass,
                                    'expected_cost':sum(w['weight']*w['spent'] for w in episodes)/mass,'episodes':episodes})
    summaries=[]
    for shift in protocol['test_shifts']:
        for name in protocol['policies']:
            rows=[r for r in records if r['shift']==shift and r['policy']==name]
            summaries.append({'shift':shift,'policy':name,'mean_supported_probability':sum(r['supported_probability'] for r in rows)/len(rows),'mean_expected_cost':sum(r['expected_cost'] for r in rows)/len(rows)})
    grouped={}
    for row in records:grouped.setdefault((row['shift'],row['problem'],row['budget']),{})[row['policy']]=row['supported_probability']
    checks={'budget_limits':all(e['spent']<=r['budget'] for r in records for e in r['episodes']),
            'exact_completion_dominates_declared_policies':all(v['finite_exact']+1e-12>=max(v.values()) for v in grouped.values()),
            'no_invalid_terminal_decisions':all(e['supported'] for r in records for e in r['episodes'] if e['status'] in ('DECIDED','INFEASIBLE'))}
    files=['intentcart/finite_budget.py','intentcart/acquisition.py','intentcart/learned_acquisition.py','scripts/evaluate_budget_roadmap.py','docs/protocols/roadmap-offline.json']
    return {'schema':'intentcart-budget-roadmap-evaluation/1','created_utc':datetime.now(timezone.utc).isoformat(),'protocol':protocol,
            'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},'models':models,
            'denominators':{'train_structures':len(train),'test_structures':12,'shift_conditions':3,'policies':9,'budget_cuts':4,'correlated_episodes':sum(len(r['episodes']) for r in records)},
            'checks':checks,'summaries':summaries,'records':records,'limitations':protocol['limits']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'intentcart/data/budget-roadmap-evaluation.json');args=p.parse_args()
    report=evaluate();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['denominators','checks','summaries']},indent=2))
    return 0 if all(report['checks'].values()) else 1
if __name__=='__main__':raise SystemExit(main())
