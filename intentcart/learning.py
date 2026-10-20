"""Particle Bayesian preference learning and one-step value-of-information queries.

This is an existing active preference-learning approach, not a new foundation model.
The particles model nonnegative linear utilities on explicitly specified attributes.
"""
from itertools import combinations
import numpy as np

FEATURES = ['lightness', 'weather protection', 'organization', 'capacity', 'comfort', 'style', 'affordability']
PARTICLES = np.random.default_rng(2026).dirichlet(np.ones(7) * 1.4, 2048)

def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -40, 40)))

def posterior(products, history, prior=None):
    matrix = np.asarray([p['features'] for p in products], dtype=float)
    utilities = PARTICLES @ matrix.T
    indexes = {p['id']: i for i, p in enumerate(products)}
    logs = np.zeros(len(PARTICLES))
    # Weak, explicit intake prior; comparisons can overturn it.
    if prior:
        target = np.asarray(prior)
        logs += 2 * (PARTICLES @ target)
    for observation in history:
        if observation['choice'] == 'skip':
            continue
        delta = 12 * (utilities[:, indexes[observation['a']]] - utilities[:, indexes[observation['b']]])
        if observation['choice'] == 'tie':
            likelihood = np.exp(-0.5 * delta ** 2) * 0.95 + 0.05
        else:
            likelihood = sigmoid(delta if observation['choice'] == 'a' else -delta)
        logs += np.log(np.maximum(likelihood, 1e-12))
    weights = np.exp(logs - logs.max())
    weights /= weights.sum()
    return utilities, weights

def choose_pair(utilities, weights, available, used=(), policy='decision', rng=None):
    pairs = [p for p in combinations(available, 2) if tuple(sorted(p)) not in used]
    if not pairs:
        return None
    if policy == 'random':
        pair = pairs[int((rng or np.random.default_rng(0)).integers(len(pairs)))]
        return (*pair, 0.)
    # Reuse one contiguous feasible matrix instead of copying it per pair.
    feasible = np.ascontiguousarray(utilities[:, available])
    expected = weights @ feasible
    current = expected.max()
    best = None
    # Bound temporary likelihood arrays to 64 pairs, independent of catalog size.
    # The binary branches partition expected utility: right = expected - left.
    for start in range(0, len(pairs), 64):
        batch = np.asarray(pairs[start:start + 64])
        probability = sigmoid(12 * (utilities[:, batch[:, 0]] - utilities[:, batch[:, 1]]))
        if policy == 'uncertainty':
            mean = weights @ probability
            values = (-mean * np.log(np.maximum(mean, 1e-12))
                      - (1 - mean) * np.log(np.maximum(1 - mean, 1e-12)))
        else:
            left = (weights[:, None] * probability).T @ feasible
            right = expected[None, :] - left
            values = np.maximum(0., left.max(axis=1) + right.max(axis=1) - current)
        # Preserve the original traversal and tolerance-based tie behavior.
        for (a, b), value in zip(batch, values):
            if best is None or value > best[2] + 1e-12:
                best = (int(a), int(b), float(value))
    return best

def infer_intake(text):
    """Transparent rule-based intake. The learning engine itself is probabilistic."""
    keys = [('light', 'weight', 'walk'), ('rain', 'weather', 'water'), ('organ', 'pocket', 'laptop'),
            ('large', 'capacity', 'travel', 'gym'), ('comfort', 'back', 'commut'), ('style', 'look', 'minimal'),
            ('cheap', 'price', 'budget', 'afford')]
    value = text.lower()
    return [float(any(word in value for word in group)) for group in keys]
