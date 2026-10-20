"""Local, consented pilot instrument. No recruitment or efficacy inference.

Blinded pre/post pairs never enter the learner. Only learning-phase answers
update its posterior. Participant data belongs in private SQLite, never assets.
"""
from itertools import combinations
import secrets
import time
import numpy as np
from .decision import assess, distribution
from .learning import PARTICLES, choose_pair
from .assurance import feasible_indexes, total_cents

POLICIES = ('static', 'random', 'uncertainty', 'decision', 'adaptive')
MISSION = {'text': 'Choose a campus commuter backpack', 'budget_cents': 9000,
           'laptop_inches': 14, 'min_capacity_l': 0}


def create(products):
    available = feasible_indexes(products, {'mission': MISSION, 'excluded': []})
    pairs = list(combinations(available, 2))
    rng = secrets.SystemRandom()
    reserved = rng.sample(pairs, 4)
    before = [(b, a) if rng.choice((True, False)) else (a, b) for a, b in reserved]
    after = list(before)
    rng.shuffle(after)
    return {'schema': 'intentcart-human-pilot/1', 'id': secrets.token_urlsafe(12),
            'policy': rng.choice(POLICIES), 'phase': 'before', 'before': [], 'after': [],
            'history': [], 'before_pairs': before, 'after_pairs': after,
            'available': available, 'started': time.time(), 'consent_version': '2026-10-10/v1',
            'revision': 0, 'seed': secrets.randbits(32)}


def model(study, products, decay):
    utilities = PARTICLES @ np.asarray([p['features'] for p in products]).T
    weights = distribution(utilities, study['history'], decay=decay if study['policy'] == 'adaptive' else 1.)
    return utilities, weights


def current(study, products, decay):
    phase = study['phase']
    base = {'id': study['id'], 'phase': phase, 'revision': study['revision'], 'mission': MISSION,
            'notice': 'Fictional products. No payments. Stored locally with consent. Withdraw to delete this pilot record.'}
    pair = None
    if phase in ('before', 'after'):
        pair = study[phase+'_pairs'][len(study[phase])]
        base['progress'] = f'{len(study[phase])+1} / 4 independent comparisons'
    if phase == 'learn':
        utilities, weights = model(study, products, decay)
        used = {tuple(sorted(p)) for p in study['before_pairs']}
        used.update(tuple(sorted((a, b))) for a, b, _ in study['history'])
        answered = sum(c != 'skip' for _, _, c in study['history'])
        if study['policy'] == 'adaptive':
            pair = assess(utilities, weights, study['available'], used, answered=answered,
                          attempts=len(study['history']))['pair']
        elif study['policy'] != 'static' and answered < 4 and len(study['history']) < 8:
            pair = choose_pair(utilities, weights, study['available'], used, study['policy'],
                               np.random.default_rng(study['seed']+len(study['history'])))
        if pair is None:
            study['phase'] = 'after'
            return current(study, products, decay)
        base['progress'] = f'{answered} / 4 learning answers · at most 8 attempts'
    if pair:
        base.update({'a': products[pair[0]], 'b': products[pair[1]]})
    if phase == 'review':
        utilities, weights = model(study, products, decay)
        best = max(study['available'], key=lambda i: float(weights @ utilities[:, i]))
        base.update({'product': products[best], 'total_cents': total_cents(products[best]),
                     'options': [products[i] for i in study['available']]})
    if phase == 'complete':
        base.update({'policy': study['policy'], 'survey': study['survey'],
                     'message': 'Pilot complete. This record is not proof of improved recommendations.'})
    return base


def respond(study, products, decay, choice):
    view = current(study, products, decay)
    phase = study['phase']
    if phase not in ('before', 'learn', 'after') or 'a' not in view:
        raise ValueError('This phase does not accept a comparison.')
    indexes = {p['id']: i for i, p in enumerate(products)}
    observation = (indexes[view['a']['id']], indexes[view['b']['id']], choice)
    if phase == 'learn':
        study['history'].append(observation)
    else:
        study[phase].append(observation)
        if len(study[phase]) == 4:
            study['phase'] = 'learn' if phase == 'before' else 'review'
    study['revision'] += 1
    return current(study, products, decay)
