"""CPU-only tie-sensitivity and held-out basket preference diagnostics."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from intentcart import missions,workspace_preferences as pref


def evaluate():
    protocol=json.loads((ROOT/'docs/protocols/preference-workbench.json').read_text());rng=np.random.default_rng(protocol['seed'])
    cat=missions.CATALOG;goal=missions.Goal(allow_driver=True,budget_cents=150000)
    valid=[missions.evaluate(goal,items,list(cat['sources'])) for items in missions.candidates(goal)]
    valid=sorted([r for r in valid if r['valid']],key=lambda r:r['id']);train=valid[::2];heldout=valid[1::2]
    if len(train)<2 or not heldout:raise ValueError('Not enough disjoint baskets for a diagnostic.')
    records=[]
    profiles=rng.dirichlet([1.2]*4,protocol['synthetic_profiles'])
    pairs=[tuple(rng.choice(len(train),2,replace=False)) for _ in range(protocol['training_comparisons'])]
    for index,truth in enumerate(profiles):
        for threshold in protocol['tie_thresholds']:
            history=[]
            for a,b in pairs:
                difference=float((pref.features(train[a],cat)-pref.features(train[b],cat))@truth)
                history.append({'a':train[a]['id'],'b':train[b]['id'],'choice':'tie' if abs(difference)<=threshold else 'a' if difference>0 else 'b'})
            initial=pref.rank(heldout,cat,[])[0];ranked=pref.rank(heldout,cat,history)[0]
            utility=lambda row:float(pref.features(row,cat)@truth)
            optimum=max(map(utility,heldout))
            records.append({'profile':index,'tie_threshold':threshold,'training_pairs':len(history),'ties':sum(h['choice']=='tie' for h in history),
                            'baseline_regret':optimum-utility(initial),'learned_regret':optimum-utility(ranked),
                            'baseline_basket':initial['id'],'learned_basket':ranked['id'],'history':history})
    files=['intentcart/workspace_preferences.py','intentcart/missions.py','intentcart/data/missions-catalog.json','scripts/evaluate_preference_workbench.py','docs/protocols/preference-workbench.json']
    summaries=[{'tie_threshold':t,'mean_baseline_regret':float(np.mean([r['baseline_regret'] for r in records if r['tie_threshold']==t])),
                'mean_learned_regret':float(np.mean([r['learned_regret'] for r in records if r['tie_threshold']==t]))} for t in protocol['tie_thresholds']]
    return {'schema':'intentcart-preference-workbench-evaluation/1','protocol':protocol,'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
            'denominators':{'synthetic_profiles':len(profiles),'train_baskets':len(train),'heldout_baskets':len(heldout),'tie_conditions':3,'correlated_runs':len(records)},
            'checks':{'basket_ids_disjoint':not {r['id'] for r in train}&{r['id'] for r in heldout},'finite_nonnegative_regret':all(np.isfinite(r['learned_regret']) and r['learned_regret']>=-1e-12 for r in records)},'summaries':summaries,'records':records,'limitations':protocol['evaluation']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'intentcart/data/preference-workbench-evaluation.json');args=p.parse_args();report=evaluate()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ('denominators','checks','summaries')},indent=2))
    return 0 if all(report['checks'].values()) else 1
if __name__=='__main__':raise SystemExit(main())
