"""Budgeted ask/recommend/defer controller. Model quantities are not calibrated.

Exponential likelihood forgetting is a standard heuristic, not a novelty claim.
The original learning module and its historical benchmark remain unchanged.
"""
import numpy as np
from .learning import PARTICLES, choose_pair, sigmoid

QUESTION_COST = .002  # normalized illustrative utility, never dollars
RISK_LIMIT = .025    # expected model regret ceiling, not a safety guarantee
BAD_REGRET = .05
MAX_ANSWERS = 4
MAX_ATTEMPTS = 8


def distribution(utilities, observations, prior=None, decay=1.):
    """Replay (a-index, b-index, choice); skips neither update nor age evidence."""
    if not 0 < decay <= 1:
        raise ValueError('decay must be in (0, 1]')
    logs = np.zeros(len(utilities))
    if prior is not None:
        logs += 2 * (PARTICLES @ np.asarray(prior))
    active = [item for item in observations if item[2] != 'skip']
    for age, (a, b, choice) in enumerate(reversed(active)):
        delta = 12 * (utilities[:, a] - utilities[:, b])
        if choice == 'tie':
            likelihood = .95 * np.exp(-.5 * delta ** 2) + .05
        elif choice in ('a', 'b'):
            likelihood = sigmoid(delta if choice == 'a' else -delta)
        else:
            raise ValueError('unsupported response')
        logs += decay ** age * np.log(np.maximum(likelihood, 1e-12))
    weights = np.exp(logs - logs.max())
    return weights / weights.sum()


def assess(utilities, weights, available, used=(), *, answered=0, attempts=0,
           question_cost=QUESTION_COST, risk_limit=RISK_LIMIT, select_question=True,
           force_questions=False, force_recommend=False):
    """Use posterior regret to defer and binary VOI to price another question.

    Ties/skips are observed but acquisition still models binary answers. The
    mismatch is deliberately exposed in the robustness study.
    """
    if not available:
        return {'action': 'DEFER', 'reason': 'No product meets the hard limits.',
                'pick': None, 'pair': None, 'expected_regret': None,
                'model_bad_probability': None, 'expected_gain': None}
    feasible = utilities[:, available]
    mean = weights @ feasible
    local_pick = int(np.argmax(mean))
    pick = available[local_pick]
    regrets = feasible.max(axis=1) - feasible[:, local_pick]
    risk = float(weights @ regrets)
    bad = float(weights @ (regrets > BAD_REGRET))
    pair = None
    if select_question and answered < MAX_ANSWERS and attempts < MAX_ATTEMPTS:
        pair = choose_pair(utilities, weights, available, used)
    gain = pair[2] if pair else None
    if pair and (force_questions or gain > question_cost):
        action, reason = 'ASK', 'Another comparison exceeds the illustrative question-cost threshold.'
    elif risk <= risk_limit or force_recommend:
        action, reason = 'RECOMMEND', 'Estimated regret is within the model threshold. Your review is still required.'
    else:
        action, reason = 'DEFER', 'The model cannot resolve the trade-off within this comparison budget. Choose manually or revise your mission.'
    return {'action': action, 'reason': reason, 'pick': int(pick),
            'pair': pair if action == 'ASK' else None, 'expected_regret': risk,
            'model_bad_probability': bad, 'expected_gain': gain}
