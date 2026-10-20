"""Deterministic fixture evaluation. No providers, model calls or human records.

Three exact finite controllers differ only in evidence acquisition. This is
NOT a model comparison, untouched public benchmark, or statistical market study.
"""
import argparse
from datetime import datetime,timezone
import hashlib
from itertools import product
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from intentcart.missions import Goal, CATALOG, solve
from scripts.missions_oracle import best,grade

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=ROOT/'intentcart/data/missions-evaluation.json')
args=parser.parse_args()
hidden=[o['source_id'] for p in CATALOG['products'] for o in p['observations'] if not o['visible']]
records=[]
for idx,values in enumerate(product(('studio-pro','studio-air','studio-work'),(18000,28000,40000,70000),(1,2),(1080,2160),(60,120),(True,False),(False,True))):
    laptop,budget,n,height,hz,reuse,driver=values
    goal=Goal(laptop_id=laptop,budget_cents=budget,displays=n,height=height,hz=hz,reuse_monitor=reuse,allow_driver=driver)
    excluded=[('dock-twin','monitor-4k','power-65')[idx%3]] if idx%4==0 else []
    oracle=best(goal.model_dump(),hidden,excluded)
    for policy in ('known_facts_only','inspect_every_missing_fact','constraint_guided'):
        inspected=list(hidden) if policy=='inspect_every_missing_fact' else []
        started=time.perf_counter()
        result=solve(goal,inspected,excluded)
        if policy=='constraint_guided':
            while result['investigations']:
                useful=[q for q in result['investigations'] if q['could_improve_cost']]
                if not useful:break
                source=useful[0]['source_ids'][0]
                if source in inspected:raise RuntimeError('Repeated acquisition')
                inspected.append(source)
                if len(inspected)>len(hidden):raise RuntimeError('Acquisition cap exceeded')
                result=solve(goal,inspected,excluded)
        plan=result['plan']
        sound=plan is None or grade(goal.model_dump(),plan['items'],inspected,excluded)
        optimal=bool(plan and oracle and plan['id']==oracle[0][2])
        if not sound:raise RuntimeError('Independent grader found an invalid plan')
        records.append({'task_id':f'fixture-{idx:03d}','goal':goal.model_dump(),'excluded':excluded,
            'policy':policy,'oracle_solvable':oracle is not None,'recommended':plan is not None,
            'valid':sound,'optimal':optimal,'total_cents':plan['total_cents'] if plan else None,
            'oracle_cents':oracle[0][1] if oracle else None,'inspections':len(inspected),
            'latency_ms':round((time.perf_counter()-started)*1000,4)})
repairs=[]
for row in records:
    if row['policy']!='constraint_guided' or not row['oracle_solvable']:continue
    g=Goal(**row['goal'])
    original=best(row['goal'],hidden,row['excluded'])[1]
    for line in original:
        removed=row['excluded']+[line['product_id']]
        reference=best(row['goal'],hidden,removed,original)
        repaired=solve(g,hidden,removed,original)['plan']
        matches=(repaired is None and reference is None) or bool(repaired and reference and repaired['id']==reference[0][2])
        if not matches:raise RuntimeError('Independent repair oracle mismatch')
        repairs.append({'task_id':row['task_id'],'removed':line['product_id'],'recovered':repaired is not None,'oracle_match':matches,'changed_slots':repaired['changed_slots'] if repaired else None})
policies=[]
for key,label in [('known_facts_only','Exact solver / known facts'),('inspect_every_missing_fact','Exact solver / inspect all'),('constraint_guided','Exact solver / targeted inspection')]:
    rows=[r for r in records if r['policy']==key]
    solvable=sum(r['oracle_solvable'] for r in rows)
    lat=sorted(r['latency_ms'] for r in rows)
    policies.append({'id':key,'name':label,'successes':sum(r['recommended'] and r['oracle_solvable'] for r in rows),
        'solvable':solvable,'unsolvable':len(rows)-solvable,
        'correct_deferrals':sum(not r['recommended'] and not r['oracle_solvable'] for r in rows),
        'optimal_baskets':sum(r['optimal'] for r in rows),'invalid_baskets':sum(not r['valid'] for r in rows),
        'inspections':sum(r['inspections'] for r in rows),'median_ms':lat[len(lat)//2],'p95_ms':lat[int((len(lat)-1)*.95)]})
result={'schema':'intentcart-missions-evaluation/1','date':datetime.now(timezone.utc).date().isoformat(),
    'created_utc':datetime.now(timezone.utc).isoformat(),'tasks':len(records)//3,'policy_runs':len(records),
    'description':'Fixed Cartesian grid of fictional workstation goals with deterministic stock exclusions. Three controllers share the exact solver and differ in fixture inspection. All attempts retained; no models or external calls.',
    'conclusion':'Correctness and acquisition trade-offs in a bounded synthetic catalog. Inspection counts include failed/irrelevant lookups in the full-census baseline. No live-model, human, external benchmark or real-commerce superiority is established.',
    'policies':policies,'repair_cases':len(repairs),'repair_oracle_matches':sum(r['oracle_match'] for r in repairs),'repair_recoveries':sum(r['recovered'] for r in repairs),'repair_records':repairs,'live_provider_calls':0,'human_participants':0,
    'source_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('intentcart/missions.py','intentcart/data/missions-catalog.json','scripts/missions_oracle.py','scripts/evaluate_missions.py')},'records':records}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('records','repair_records','source_sha256')},indent=2))
