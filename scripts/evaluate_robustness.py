"""Two-stage frozen synthetic robustness study; never imports payment/storage code.

Run development first, then heldout. Heldout refuses a changed development
source/config identity. Results are synthetic and can be null or negative.
"""
import os
for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[name] = '1'
import argparse
from datetime import datetime, timezone
import hashlib
import json
from itertools import combinations
from pathlib import Path
import platform
import sys
import time
import tracemalloc
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart.decision import assess, distribution
from intentcart.learning import PARTICLES, choose_pair, sigmoid
from intentcart.assurance import feasible_indexes

PROTOCOL_PATH = ROOT/'intentcart/data/robustness-protocol.json'
PROTOCOL = json.loads(PROTOCOL_PATH.read_text())
PRODUCTS = json.loads((ROOT/'intentcart/data/catalog.json').read_text())
MATRIX = np.asarray([p['features'] for p in PRODUCTS])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sources():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
        'intentcart/decision.py', 'intentcart/learning.py', 'intentcart/assurance.py',
        'intentcart/data/catalog.json', 'intentcart/data/robustness-protocol.json',
        'scripts/evaluate_robustness.py')}


def cases(split):
    seed = PROTOCOL[split+'_seed']
    count = PROTOCOL[split+'_per_family']
    for family_number, family in enumerate(PROTOCOL['families']):
        for number in range(count):
            rng = np.random.default_rng(np.random.SeedSequence([seed, family_number, number]))
            hidden = rng.dirichlet(np.ones(7)*1.4)
            later = rng.dirichlet(np.ones(7)*1.4)
            prior = np.zeros(7)
            prior[np.argsort(hidden)[-2:]] = 1
            if family == 'misleading_intake':
                prior[:] = 0
                prior[np.argsort(hidden)[:2]] = 1
            matrix = MATRIX.copy()
            if family == 'corrupted_features':
                matrix = np.clip(matrix + rng.normal(0, .18, matrix.shape), 0, 1)
            mission = {'budget_cents': int(rng.choice([8000, 9000, 11500])),
                       'laptop_inches': int(rng.choice([14, 16])), 'min_capacity_l': 0}
            available = feasible_indexes(PRODUCTS, {'mission': mission, 'excluded': []})
            pool = list(combinations(available, 2))
            # Reserve unique pairs, leaving at least four for learning.
            reserved = [pool[i] for i in rng.choice(len(pool), min(6, max(1, len(pool)-4)), replace=False)]
            item = {'id': f'{split}:{family}:{number}', 'family': family,
                    'hidden': hidden.tolist(), 'later': later.tolist(), 'prior': prior.tolist(),
                    'matrix': matrix.tolist(), 'available': available, 'reserved': reserved,
                    'draws': rng.random((8, 3)).tolist()}
            item['sha256'] = digest(item)
            yield item


def truth(case, changed=False):
    hidden = np.asarray(case['later'] if changed else case['hidden'])
    result = MATRIX @ hidden
    if case['family'] == 'nonlinear':
        # Complementarity: a pack must satisfy both comfort and rain protection.
        result = .55*result + .45*np.minimum(MATRIX[:, 1], MATRIX[:, 4])
    return result


def simulate(case, policy, decay=1., question_cost=None, risk_limit=None):
    utilities = PARTICLES @ np.asarray(case['matrix']).T
    available = case['available']
    observations, trace = [], []
    used = {tuple(pair) for pair in case['reserved']}
    adaptive = policy.startswith('adaptive')
    applied_decay = decay if (adaptive and policy != 'adaptive_no_forgetting') or policy == 'recency_fixed' else 1.
    answered = 0
    started = time.perf_counter()
    weights = distribution(utilities, observations, case['prior'], applied_decay)
    for step in range(0 if policy == 'static' else 8):
        if adaptive and policy != 'adaptive_no_stopping':
            decision = assess(utilities, weights, available, used, answered=answered, attempts=step,
                              question_cost=PROTOCOL['question_cost'] if question_cost is None else question_cost,
                              risk_limit=PROTOCOL['risk_limit'] if risk_limit is None else risk_limit)
            pair = decision['pair']
        else:
            pair = choose_pair(utilities, weights, available, used,
                               policy if policy in ('random', 'uncertainty') else 'decision',
                               np.random.default_rng(int(case['sha256'][:12], 16)+step)) if answered < 4 else None
        if pair is None:
            break
        a, b, gain = pair
        current_truth = truth(case, case['family'] == 'drift' and answered >= 2)
        difference = current_truth[a]-current_truth[b]
        draw, noise_draw, skip_draw = case['draws'][step]
        choice = 'a' if draw < sigmoid(12*difference) else 'b'
        if case['family'] == 'noisy':
            if skip_draw < .1:
                choice = 'skip'
            elif noise_draw < .35:
                choice = 'a' if draw < .5 else 'b'
        if case['family'] == 'ties' and abs(difference) < .03:
            choice = 'tie'
        observations.append((a, b, choice))
        trace.append({'a': a, 'b': b, 'choice': choice, 'gain': float(gain)})
        used.add(tuple(sorted((a, b))))
        answered += choice != 'skip'
        weights = distribution(utilities, observations, case['prior'], applied_decay)
    decision = assess(utilities, weights, available, used, answered=answered, attempts=len(trace),
                      select_question=False,
                      risk_limit=PROTOCOL['risk_limit'] if risk_limit is None else risk_limit,
                      force_recommend=not adaptive or policy == 'adaptive_no_defer')
    elapsed = (time.perf_counter()-started)*1000
    final_truth = truth(case, case['family'] == 'drift')
    best = max(final_truth[i] for i in available)
    regret = float(best-final_truth[decision['pick']])
    means = weights @ utilities
    heldout = float(np.mean([np.sign(means[a]-means[b]) == np.sign(final_truth[a]-final_truth[b])
                             for a, b in case['reserved']]))
    recommended = decision['action'] == 'RECOMMEND'
    bad = regret > PROTOCOL['bad_regret']
    return {'case_id': case['id'], 'case_sha256': case['sha256'], 'family': case['family'],
            'policy': policy, 'decay': applied_decay, 'candidate_regret': regret,
            'pick': decision['pick'], 'recommended': recommended, 'bad_candidate': bad,
            'questions': len(trace), 'answers': answered, 'heldout_pair_agreement': heldout,
            'model_regret': decision['expected_regret'], 'model_bad_probability': decision['model_bad_probability'],
            'loss': (regret if recommended else PROTOCOL['deferral_cost']) + (PROTOCOL['question_cost'] if question_cost is None else question_cost)*len(trace),
            'elapsed_ms': elapsed, 'trace': trace}


def summarize(records):
    accepted = [r for r in records if r['recommended']]
    rejected = [r for r in records if not r['recommended']]
    bad = [r for r in records if r['bad_candidate']]
    average = lambda rows, name: float(np.mean([r[name] for r in rows])) if rows else None
    return {'personas': len(records), 'recommended': len(accepted), 'deferred': len(rejected),
            'coverage': len(accepted)/len(records), 'candidate_regret': average(records, 'candidate_regret'),
            'recommended_regret': average(accepted, 'candidate_regret'),
            'bad_recommendations': sum(r['bad_candidate'] for r in accepted),
            'bad_recommendation_rate_among_recommended': average(accepted, 'bad_candidate'),
            'bad_candidates': len(bad), 'deferral_recall': sum(not r['recommended'] for r in bad)/len(bad) if bad else None,
            'unnecessary_deferrals': sum(not r['bad_candidate'] for r in rejected),
            'mean_questions': average(records, 'questions'), 'mean_loss': average(records, 'loss'),
            'heldout_pair_agreement': average(records, 'heldout_pair_agreement'),
            'model_bad_brier': float(np.mean([(r['model_bad_probability']-r['bad_candidate'])**2 for r in records])),
            'session_ms_median': float(np.median([r['elapsed_ms'] for r in records])),
            'session_ms_p95': float(np.quantile([r['elapsed_ms'] for r in records], .95))}


def paired(left, right, field):
    assert [r['case_id'] for r in left] == [r['case_id'] for r in right]
    # Positive means right improved over left. Equal weight to each family.
    deltas = np.asarray([a[field]-b[field] for a, b in zip(left, right)])
    families = [np.asarray([i for i, r in enumerate(left) if r['family'] == family])
                for family in PROTOCOL['families']]
    rng = np.random.default_rng(8675309)
    boot = np.mean([deltas[index[rng.integers(len(index), size=(PROTOCOL['bootstrap_resamples'], len(index)))]]
                    .mean(axis=1) for index in families], axis=0)
    return {'reduction': float(deltas.mean()), 'ci95': np.quantile(boot, [.025, .975]).tolist(),
            'paired_personas': len(left), 'unit': 'persona, stratified within family'}


def run(stage, development_path):
    material = list(cases(stage))
    base = {'schema': 'intentcart-robustness/1', 'stage': stage, 'created_utc': datetime.now(timezone.utc).isoformat(),
            'source_sha256': sources(), 'protocol_sha256': hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
            'case_set_sha256': digest([c['sha256'] for c in material]), 'human_participants': 0,
            'live_provider_calls': 0, 'personas': len(material),
            'environment': {'python': platform.python_version(), 'numpy': np.__version__,
                            'platform': platform.platform(), 'thread_ceilings': 1}}
    if stage == 'development':
        candidates = {str(decay): [simulate(c, 'recency_fixed', decay) for c in material]
                      for decay in PROTOCOL['candidate_decays']}
        # Declaration order resolves exact ties in favor of no forgetting.
        selected = min(PROTOCOL['candidate_decays'], key=lambda d: summarize(candidates[str(d)])['candidate_regret'])
        return {**base, 'selected_decay': selected, 'selection_metric': 'mean fixed-four candidate regret',
                'summaries': {key: summarize(rows) for key, rows in candidates.items()}, 'records': candidates}
    development = json.loads(development_path.read_text())
    if development.get('stage') != 'development' or development['source_sha256'] != sources():
        raise ValueError('Development evidence is stale or invalid. Reproduce development before heldout.')
    decay = development['selected_decay']
    if decay not in PROTOCOL['candidate_decays']:
        raise ValueError('Unknown development candidate')
    expected = min(PROTOCOL['candidate_decays'], key=lambda d: summarize(development['records'][str(d)])['candidate_regret'])
    if expected != decay:
        raise ValueError('Development selection does not match its records')
    policies = ('static', 'random', 'uncertainty', 'decision', 'recency_fixed',
                'adaptive', 'adaptive_no_defer', 'adaptive_no_stopping', 'adaptive_no_forgetting')
    records = {p: [] for p in policies}
    # Rotate execution order across cases; timings are descriptive, not paired speedup evidence.
    for i, case in enumerate(material):
        for p in policies[i % len(policies):]+policies[:i % len(policies)]:
            records[p].append(simulate(case, p, decay))
    sensitivity = []
    for cost in PROTOCOL['sensitivity']['question_costs']:
        for limit in PROTOCOL['sensitivity']['risk_limits']:
            rows = [simulate(c, 'adaptive', decay, cost, limit) for c in material]
            sensitivity.append({'question_cost': cost, 'risk_limit': limit, 'summary': summarize(rows)})
    tracemalloc.start()
    simulate(material[0], 'adaptive', decay)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    comparison = paired(records['decision'], records['recency_fixed'], 'candidate_regret')
    return {**base, 'development_sha256': hashlib.sha256(development_path.read_bytes()).hexdigest(),
            'selected_decay': decay, 'policy_sessions': sum(map(len, records.values())),
            'sensitivity_sessions': len(material)*len(sensitivity), 'summaries': {p: summarize(r) for p, r in records.items()},
            'by_family': {f: {p: summarize([r for r in rows if r['family'] == f]) for p, rows in records.items()}
                          for f in PROTOCOL['families']},
            'primary': comparison,
            'paired_adaptive_loss': paired(records['decision'], records['adaptive'], 'loss'),
            'sensitivity': sensitivity, 'traced_peak_bytes_one_adaptive_session': peak,
            'conclusion': ('Positive pooled fixed-four recency result under these synthetic assumptions.'
                           if comparison['ci95'][0] > 0 else 'No established pooled fixed-four recency improvement; null/negative results retained.'),
            'limits': PROTOCOL['limits'], 'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('development', 'heldout'), required=True)
    parser.add_argument('--development', type=Path, default=ROOT/'intentcart/data/robustness-development.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run(args.stage, args.development)
    destination = args.output or ROOT/f'intentcart/data/robustness-{args.stage}.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('records', 'by_family', 'sensitivity')}, indent=2))


if __name__ == '__main__':
    main()
