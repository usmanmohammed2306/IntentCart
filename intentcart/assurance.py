"""Deterministic spending checks and declared, fictional world interventions.

These checks constrain proposals; they do not prove preference fidelity or
general language-model security. No provider calls or storage writes occur here.
"""
import copy

WORLD_LABELS = {
    'stock': 'Front-runner unavailable',
    'shipping': 'Shipping increases by $10',
    'budget': 'Budget decreases by $15',
    'no_purchase': 'Budget becomes $30',
}

def total_cents(product, state=None):
    surcharge = (state or {}).get('shipping_surcharge_cents', 0)
    return product['price_cents'] + (0 if product['price_cents'] >= 8800 else 400) + surcharge

def feasible_indexes(products, state):
    mission = state.get('mission')
    if not mission:
        return []
    return [i for i, product in enumerate(products)
            if product['id'] not in state['excluded']
            and total_cents(product, state) <= mission['budget_cents']
            and product['laptop_inches'] >= mission['laptop_inches']
            and product['capacity_l'] >= mission['min_capacity_l']]

def project_world(state, kind, leader_id):
    result = copy.deepcopy(state)
    if kind == 'stock':
        if leader_id and leader_id not in result['excluded']:
            result['excluded'].append(leader_id)
    elif kind == 'shipping':
        result['shipping_surcharge_cents'] = min(5000, result.get('shipping_surcharge_cents', 0) + 1000)
    elif kind == 'budget':
        result['mission']['budget_cents'] = max(3000, result['mission']['budget_cents'] - 1500)
    elif kind == 'no_purchase':
        result['mission']['budget_cents'] = 3000
    else:
        raise ValueError('Unknown rehearsal scenario')
    return result

def check_proposal(products, quote, state, proposal, now):
    product = next((p for p in products if p['id'] == quote['product']['id']), None)
    available = {products[i]['id'] for i in feasible_indexes(products, state)}
    conditions = [
        ('consent', 'Explicit approval of this exact quote', proposal.get('approved') is True),
        ('version', 'Quote and proposal match current preferences',
         quote['version'] == state['version'] == proposal.get('version')),
        ('expiry', 'Quote has not expired', now < quote['expires_at']),
        ('product', 'Proposed product matches the owned quote', proposal.get('product_id') == quote['product']['id']),
        ('amount', 'Proposed total matches the server quote',
         type(proposal.get('total_cents')) is int and proposal['total_cents'] == quote['total_cents']),
        ('currency', 'USD matches the quote', proposal.get('currency') == quote['currency'] == 'USD'),
        ('budget', 'Total is within the current all-in budget',
         state.get('mission') is not None and quote['total_cents'] <= state['mission']['budget_cents']),
        ('feasible', 'Quoted product is available and fits the mission', quote['product']['id'] in available),
        ('pricing', 'Quote still matches current server pricing',
         product is not None and quote['total_cents'] == total_cents(product, state)),
    ]
    checks = [{'id': key, 'label': label, 'passed': bool(passed)} for key, label, passed in conditions]
    return {'eligible': all(c['passed'] for c in checks), 'checks': checks,
            'failed': [c['id'] for c in checks if not c['passed']],
            'note': 'Eligibility is a dry-run result, not recorded consent or PayPal buyer approval.'}

def exact_proposal(quote, approved):
    return {'product_id': quote['product']['id'], 'total_cents': quote['total_cents'],
            'currency': quote['currency'], 'version': quote['version'], 'approved': approved}

def challenge_suite(products, quote, state, now):
    control = exact_proposal(quote, True)
    other = next(p['id'] for p in products if p['id'] != control['product_id'])
    cases = [
        ('control', 'Exact approved proposal', control, state, now, True),
        ('amount', 'Increase total by $10', {**control, 'total_cents': control['total_cents']+1000}, state, now, False),
        ('product', 'Substitute another product', {**control, 'product_id': other}, state, now, False),
        ('currency', 'Change USD to EUR', {**control, 'currency': 'EUR'}, state, now, False),
        ('stale', 'Reuse an earlier preference version', {**control, 'version': max(0, quote['version']-1)}, state, now, False),
        ('consent', 'Skip explicit approval', {**control, 'approved': False}, state, now, False),
        ('expiry', 'Replay after quote expiration', control, state, quote['expires_at']+1, False),
    ]
    results = []
    for key, label, proposal, context, clock, expected in cases:
        outcome = check_proposal(products, quote, context, proposal, clock)
        results.append({'id': key, 'label': label, 'proposal': proposal,
                        'eligible': outcome['eligible'], 'failed': outcome['failed'],
                        'expected_eligible': expected, 'matches_expectation': outcome['eligible'] == expected})
    return {'kind': 'scripted deterministic dry-run challenges', 'provider_calls': 0,
            'quote_id': quote['id'], 'cases': results, 'total': len(results),
            'matched': sum(r['matches_expectation'] for r in results),
            'note': 'Finite scripted cases, not a general security or LLM robustness benchmark. No approval is recorded.'}
