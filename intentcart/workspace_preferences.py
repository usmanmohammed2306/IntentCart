"""Optional finite Bayesian preference ranking over already valid workstations.

No hard requirement, product fact or consent is learned. Only human pairwise
choices update these four preference weights. This model is uncalibrated.
"""
import numpy as np

FEATURES = ('lower_cost', 'no_driver', 'charging_capacity', 'dock_refresh_capacity')
PARTICLES = np.random.default_rng(614).dirichlet([1.5] * 4, 512)

def active(history):
    return any(pair.get('choice') in ('a', 'b', 'tie') for pair in history)

def features(row, catalog):
    products = {p['id']: p for p in catalog['products']}
    dock = next(products[i['product_id']] for i in row['items'] if products[i['product_id']]['kind'] == 'dock')
    observations = {key.split(':', 1)[1]: fact['value'] for key, fact in row['facts'].items()
                    if key.startswith(dock['id'] + ':') and fact['value'] is not None}
    return np.array([1 - min(row['total_cents'] / 300000, 1),
                     float(observations.get('protocol') != 'displaylink'),
                     min(observations.get('pd_watts', 0) / 240, 1),
                     min(observations.get('max_hz', 0) / 240, 1)])

def distribution(history, rows, catalog):
    by_id = {r['id']: r for r in rows}
    logp = np.zeros(len(PARTICLES))
    for pair in history:
        if pair.get('a') not in by_id or pair.get('b') not in by_id:
            continue  # Removed/ineligible choices cannot influence this ranking.
        choice = pair.get('choice')
        if choice == 'skip':
            continue
        diff = PARTICLES @ (features(by_id[pair['a']], catalog) - features(by_id[pair['b']], catalog))
        z = np.clip(8 * diff, -40, 40)
        if choice == 'a':
            logp -= np.logaddexp(0, -z)
        elif choice == 'b':
            logp -= np.logaddexp(0, z)
        elif choice == 'tie':
            logp -= 4 * diff ** 2
        else:
            raise ValueError('Invalid human preference choice.')
    prob = np.exp(logp - logp.max())
    return prob / prob.sum()

def rank(rows, catalog, history=()):
    if not rows:
        return []
    mean = distribution(history, rows, catalog) @ PARTICLES
    scored = [{**r, 'preference_utility': float(features(r, catalog) @ mean)} for r in rows]
    return sorted(scored, key=lambda r: (-r['preference_utility'], r['total_cents'], r['id']))

def weights(history, rows, catalog):
    mean = distribution(history, rows, catalog) @ PARTICLES
    return dict(zip(FEATURES, map(float, mean)))
