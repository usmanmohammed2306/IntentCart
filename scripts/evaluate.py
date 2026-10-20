"""Reproduce a paired, synthetic preference-learning benchmark. No human claims."""
import argparse
import json
import time
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentcart.learning import PARTICLES, choose_pair, sigmoid

def run(personas=120,seed=2026):
    products=json.loads((Path(__file__).resolve().parents[1]/'intentcart/data/catalog.json').read_text())
    matrix=np.array([p['features'] for p in products])
    utilities=PARTICLES @ matrix.T
    rng=np.random.default_rng(seed)
    profiles=rng.dirichlet(np.ones(7)*1.4,personas)
    records={policy:[] for policy in ['static','random','uncertainty','decision']}
    timings=[]
    for number,hidden in enumerate(profiles):
        budget=int(rng.choice([8000,9000,11500])); laptop=int(rng.choice([14,16]))
        available=[i for i,p in enumerate(products) if p['price_cents']+(0 if p['price_cents']>=8800 else 400)<=budget and p['laptop_inches']>=laptop]
        truth=matrix @ hidden
        optimum=max(available,key=lambda i:truth[i])
        prior=np.zeros(7); prior[np.argsort(hidden)[-2:]]=1
        initial=np.exp(2*(PARTICLES @ prior));initial/=initial.sum()
        draws=np.random.default_rng(seed+number).random(4)
        heldout=[tuple(rng.choice(available,2,replace=False)) for _ in range(12)]
        for policy in records:
            weights=initial.copy();used=set()
            for step in range(0 if policy=='static' else 4):
                start=time.perf_counter()
                a,b,_=choose_pair(utilities,weights,available,used,policy,np.random.default_rng(seed+10000+number*4+step))
                if policy=='decision':timings.append((time.perf_counter()-start)*1000)
                used.add(tuple(sorted((a,b))))
                choice=draws[step]<sigmoid(12*(truth[a]-truth[b]))
                likelihood=sigmoid(12*(utilities[:,a]-utilities[:,b])*(1 if choice else -1))
                weights*=likelihood;weights/=weights.sum()
            mean=weights @ utilities
            pick=max(available,key=lambda i:mean[i])
            accuracy=np.mean([(mean[a]>mean[b])==(truth[a]>truth[b]) for a,b in heldout])
            records[policy].append((truth[optimum]-truth[pick],pick==optimum,accuracy))
    results=[]
    bootstrap=np.random.default_rng(seed+50000).integers(personas,size=(1000,personas))
    for policy,values in records.items():
        values=np.array(values)
        ci=np.quantile(values[bootstrap,0].mean(axis=1),[.025,.975])
        results.append({'policy':policy,'mean_regret':round(float(values[:,0].mean()),6),
                        'regret_ci':[round(float(n),6) for n in ci],
                        'top1_agreement':round(float(values[:,1].mean()),6),
                        'heldout_pair_accuracy':round(float(values[:,2].mean()),6),
                        'questions':0 if policy=='static' else 4})
    differences={}
    decision=np.array(records['decision'])[:,0]
    for policy in ['static','random','uncertainty']:
        delta=np.array(records[policy])[:,0]-decision
        ci=np.quantile(delta[bootstrap].mean(axis=1),[.025,.975])
        differences[policy]={'regret_reduction':round(float(delta.mean()),6),'paired_ci':[round(float(n),6) for n in ci]}
    return {'status':'measured','seed':seed,'personas':personas,'human_participants':0,'results':results,
            'paired_differences':differences,'query_ms':{'median':round(float(np.median(timings)),3),'p95':round(float(np.quantile(timings,.95)),3)},
            'description':'Paired synthetic benchmark: Dirichlet(1.4) hidden linear weights; noisy logistic choices (beta=12); 24 fictional packs; 3 budget levels; 2 laptop-fit constraints; weak prior from the hidden top two attributes. 1,000 bootstrap resamples.',
            'conclusion':'Performance is conditional on these simulation assumptions. Confidence intervals may overlap; inspect paired differences before claiming an improvement.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--personas',type=int,default=120);parser.add_argument('--seed',type=int,default=2026)
    parser.add_argument('--output',default='intentcart/data/evaluation.json');args=parser.parse_args()
    if not 20<=args.personas<=2000:parser.error('personas must be between 20 and 2000')
    result=run(args.personas,args.seed);Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
