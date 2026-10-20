"""CPU ridge imitation of unrestricted expected inspection cost.

The features see the declared posterior model, never the actual truth world.
This is a bounded research controller, not a calibrated or budget-optimal policy.
"""
from fractions import Fraction
import math
import numpy as np
from .acquisition import ExactReference, _partitions, _consensus, posterior, ProblemError

FEATURES = ('query_cost', 'decision_impurity', 'answer_entropy', 'post_decision_impurity',
            'largest_branch_mass', 'posterior_fraction', 'query_count')

def feature_vector(problem, state, qi):
    mass = sum(problem.worlds[i].weight for i in state)
    counts = {}
    for i in state:
        d = problem.worlds[i].decision
        counts[d] = counts.get(d, 0) + problem.worlds[i].weight
    before = 1 - sum((v / mass) ** 2 for v in counts.values())
    entropy, after, largest = 0., 0., 0.
    for branch in _partitions(problem, state, qi):
        bm = sum(problem.worlds[i].weight for i in branch)
        ratio = bm / mass
        entropy -= ratio * math.log2(ratio)
        largest = max(largest, ratio)
        bc = {}
        for i in branch:
            d = problem.worlds[i].decision
            bc[d] = bc.get(d, 0) + problem.worlds[i].weight
        after += ratio * (1 - sum((v / bm) ** 2 for v in bc.values()))
    return np.array([problem.queries[qi].cost, before, entropy, after, largest,
                     len(state) / len(problem.worlds), len(problem.queries)], dtype=float)

def teacher_rows(problem):
    reference = ExactReference(problem)
    queue = [tuple(range(len(problem.worlds)))]
    seen = set()
    rows = []
    while queue:
        state = queue.pop()
        if state in seen or _consensus(problem, state)[0]:
            continue
        seen.add(state)
        if len(seen) > 2000:
            raise ProblemError('Training-state enumeration exceeds bound.')
        mass = sum(problem.worlds[i].weight for i in state)
        for qi, query in enumerate(problem.queries):
            branches = _partitions(problem, state, qi)
            if len(branches) < 2:
                continue
            cost = Fraction(query.cost)
            for branch in branches:
                cost += Fraction(sum(problem.worlds[i].weight for i in branch), mass) * reference.solve(branch)[0]
                queue.append(branch)
            rows.append((feature_vector(problem, state, qi), float(cost)))
    return rows

def fit(problems, ridge=1.0):
    if not problems or len(problems) > 64 or ridge <= 0:
        raise ProblemError('Supply bounded training structures and positive ridge.')
    rows = [row for p in problems for row in teacher_rows(p)]
    if not rows:
        raise ProblemError('No informative training states.')
    x, y = np.stack([r[0] for r in rows]), np.array([r[1] for r in rows])
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1
    design = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return {'schema': 'intentcart-learned-acquisition/1', 'features': list(FEATURES),
            'mean': mean.tolist(), 'scale': scale.tolist(), 'coefficients': coefficients.tolist(),
            'training_structures': len(problems), 'training_state_query_rows': len(rows),
            'objective': 'unrestricted expected inspection cost; finite budgets only truncate actions',
            'ridge': ridge}

def decide(problem, model, observations=(), remaining_budget=None):
    if model.get('schema') != 'intentcart-learned-acquisition/1' or model.get('features') != list(FEATURES):
        raise ProblemError('Invalid learned policy schema.')
    mean, scale, coefficients = (np.asarray(model[k], dtype=float) for k in ('mean', 'scale', 'coefficients'))
    if mean.shape != (7,) or scale.shape != (7,) or coefficients.shape != (8,) or not all(np.isfinite(a).all() for a in (mean, scale, coefficients)) or (scale <= 0).any():
        raise ProblemError('Invalid learned policy parameters.')
    if remaining_budget is not None and (type(remaining_budget) is not int or remaining_budget < 0):
        raise ProblemError('Invalid remaining budget.')
    state, _, _ = posterior(problem, observations)
    if not state:
        return {'status': 'CONFLICT', 'decision': None}
    certain, decision = _consensus(problem, state)
    if certain:
        return {'status': 'INFEASIBLE' if decision is None else 'DECIDED', 'decision': decision}
    candidates = []
    for qi, query in enumerate(problem.queries):
        if len(_partitions(problem, state, qi)) > 1:
            vector = np.r_[1., (feature_vector(problem, state, qi) - mean) / scale]
            candidates.append((float(vector @ coefficients), query.id, qi))
    if not candidates:
        raise ProblemError('No informative query.')
    _, _, qi = min(candidates)
    q = problem.queries[qi]
    if remaining_budget is not None and q.cost > remaining_budget:
        return {'status': 'BUDGET_EXHAUSTED', 'decision': None}
    return {'status': 'QUERY', 'query_id': q.id, 'cost': q.cost, 'version': q.version}

def run_episode(problem, truth_world_id, model, budget=None):
    truth = next((w for w in problem.worlds if w.id == truth_world_id), None)
    if truth is None:
        raise ProblemError('Unknown environment truth.')
    observations, cost, trace = [], 0, []
    for _ in range(len(problem.queries) + 1):
        action = decide(problem, model, observations, None if budget is None else budget - cost)
        trace.append(action)
        if action['status'] != 'QUERY':
            return {'status': action['status'], 'decision': action['decision'], 'new_cost': cost, 'trace': trace,
                    'supported': action['status'] in ('DECIDED', 'INFEASIBLE') and action['decision'] == truth.decision}
        qi = next(i for i, q in enumerate(problem.queries) if q.id == action['query_id'])
        observations.append({'query_id': action['query_id'], 'version': action['version'], 'value': truth.answers[qi]})
        cost += action['cost']
    raise ProblemError('Controller exceeded query bound.')
