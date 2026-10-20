"""Scoped decision certificates and dependency-directed fixture revalidation.

No I/O other than reading source identities; no provider, model or payment calls.
Certificates are reproducibility artifacts, not signatures or payment authority.
The cache is trusted server state with accidental-corruption detection. Public
certificates contain no cache or hidden observation values.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

SCHEMA = 'intentcart-validity/1'
FIELDS = {
    'dock': ('protocol', 'displays', 'max_height', 'max_hz', 'pd_watts'),
    'monitor': ('height', 'hz', 'connector'),
    'cable': ('height', 'hz', 'count', 'connector'),
    'power': ('watts',),
}
MAX_CANDIDATES = 4096


class Change(BaseModel):
    """A content-addressed difference, never a new source of fact values."""
    model_config = ConfigDict(extra='forbid')
    kind: Literal['goal', 'fact', 'price', 'availability', 'catalog', 'source',
                  'revision', 'algorithm', 'objective', 'basket']
    path: str
    before_sha256: str | None
    after_sha256: str | None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def algorithm_identity():
    root = Path(__file__).parent
    return hashlib.sha256((root / 'validity.py').read_bytes() +
                          (root / 'missions.py').read_bytes()).hexdigest()


def _validate_catalog(catalog):
    """Reject malformed snapshots before arithmetic; omitted facts stay unknown."""
    products, laptops, sources = catalog['products'], catalog['laptops'], catalog['sources']
    if not 1 <= len(products) <= 64 or not 1 <= len(laptops) <= 16 or len(sources) > 1024:
        raise ValueError('Catalog exceeds the bounded certificate envelope.')
    ids = [p['id'] for p in products]
    if len(ids) != len(set(ids)):
        raise ValueError('Product identities must be unique.')
    laptop_ids = [p['id'] for p in laptops]
    if len(laptop_ids) != len(set(laptop_ids)):
        raise ValueError('Laptop identities must be unique.')
    for item in [*products, *laptops]:
        if not isinstance(item['id'], str) or not item['id'] or len(item['id']) > 100:
            raise ValueError('Invalid fixture identity.')
    for item in products:
        if item['kind'] not in FIELDS or type(item['price_cents']) is not int or item['price_cents'] < 0:
            raise ValueError('Invalid product kind or integer price.')
        if len(item['observations']) > 128:
            raise ValueError('Too many fixture observations.')
        for observation in item['observations']:
            if type(observation['visible']) is not bool or observation['source_id'] not in sources:
                raise ValueError('Observation visibility/source is invalid.')
            # Even hidden malformed facts are rejected, rather than becoming an
            # exception when a later explicit inspection reveals them.
            field, value = observation['field'], observation['value']
            if field in FIELDS[item['kind']]:
                if field in ('protocol', 'connector'):
                    if not isinstance(value, str):
                        raise ValueError('Categorical fixture facts must be strings.')
                elif type(value) is not int or value < 0:
                    raise ValueError('Numeric fixture facts must be nonnegative integers.')
            source = sources[observation['source_id']]
            if not isinstance(source, dict) or 'unit' not in source:
                raise ValueError('Observation source needs declared units.')
    for laptop in laptops:
        if (not isinstance(laptop['protocols'], list) or
                any(not isinstance(p, str) for p in laptop['protocols']) or
                any(type(laptop[k]) is not int or laptop[k] < 0 for k in ('native_displays', 'charge_watts'))):
            raise ValueError('Invalid laptop fixture capabilities.')


def _world(goal, catalog, inspected, excluded, revision, source, previous_items):
    """Hash visible values and provenance; never export hidden source values."""
    from . import missions as m
    values = {f'goal.{k}': digest(v) for k, v in goal.model_dump().items()}
    for laptop in catalog['laptops']:
        for key in ('protocols', 'native_displays', 'charge_watts'):
            values[f'laptop.{laptop["id"]}.{key}'] = digest(laptop[key])
    for item in catalog['products']:
        pid = item['id']
        values[f'product.{pid}.kind'] = digest(item['kind'])
        values[f'product.{pid}.price_cents'] = digest(item['price_cents'])
        values[f'availability.{pid}'] = digest(pid not in excluded)
        for field in FIELDS[item['kind']]:
            observed = [o for o in item['observations'] if o['field'] == field and
                        (o['visible'] or o['source_id'] in inspected)]
            fact = m.fact(item, field, inspected, catalog=catalog)
            values[f'fact.{pid}.{field}'] = digest({
                'fact': fact,
                'observations': observed,
                'sources': {o['source_id']: catalog['sources'][o['source_id']] for o in observed},
                'variant': item.get('variant', pid),
            })
    values.update({'catalog': digest(catalog), 'source': digest(source),
                   'revision': digest(revision), 'algorithm': digest(algorithm_identity()),
                   'objective': digest(previous_items or [])})
    return values


def _dependencies(goal, items, catalog):
    products = {p['id']: p for p in catalog['products']}
    selected = {products[i['product_id']]['kind']: i['product_id'] for i in items}
    def facts(kind, *fields):
        return [f'fact.{selected[kind]}.{f}' for f in fields] if kind in selected else []
    laptop = f'laptop.{goal.laptop_id}.'
    by_check = {
        'budget': ['goal.budget_cents'] + [f'product.{i["product_id"]}.price_cents' for i in items],
        'transport': ['goal.laptop_id', laptop + 'protocols'] + facts('dock', 'protocol'),
        'driver': ['goal.allow_driver'] + facts('dock', 'protocol'),
        'displays': ['goal.displays', 'goal.laptop_id', laptop + 'native_displays'] + facts('dock', 'protocol', 'displays'),
        'resolution': ['goal.height', 'goal.reuse_monitor'] + facts('dock', 'max_height') + facts('monitor', 'height'),
        'refresh': ['goal.hz', 'goal.reuse_monitor'] + facts('dock', 'max_hz') + facts('monitor', 'hz') + facts('cable', 'hz'),
        'charging': ['goal.laptop_id', laptop + 'charge_watts'] + facts('dock', 'pd_watts') + facts('power', 'watts'),
        'cables': ['goal.displays', 'goal.height'] + facts('cable', 'count', 'height', 'connector') + facts('monitor', 'connector'),
        'structure': ['goal.displays', 'goal.reuse_monitor'] + [v for i in items for v in
                       (f'product.{i["product_id"]}.kind', f'availability.{i["product_id"]}')],
    }
    return {key: sorted(set(value)) for key, value in by_check.items()}


def _change_kind(path):
    if path.startswith('goal.'): return 'goal'
    if path.startswith(('fact.', 'laptop.')): return 'fact'
    if path.endswith('.price_cents'): return 'price'
    if path.startswith('availability.'): return 'availability'
    return path if path in ('source', 'revision', 'algorithm', 'objective', 'basket') else 'catalog'


def public_certificate(certificate):
    """Small inspectable summary, without row cache or full dependency map."""
    return deepcopy({k: v for k, v in certificate.items()
                     if k not in ('_cache', '_cache_sha256', 'dependency_fingerprints')})


def analyze(goal, *, catalog=None, inspected=(), excluded=(), items=None,
            previous_items=None, revision=1, source_sha256=None, previous=None,
            mode='selective'):
    """Revalidate a selected basket against a bounded immutable snapshot.

    ``items=None`` selects the current best verified basket. An explicit list
    audits that exact basket instead, even after it becomes invalid/suboptimal.
    ``previous_items`` selects the existing minimal-change repair objective.
    ``previous`` is an earlier server-generated certificate, never client input.
    ``mode='full'`` ignores the cache for a recomputation reference. No execution
    or consent assertion can be derived from either mode.
    """
    from . import missions as m
    if mode not in ('selective', 'full'):
        raise ValueError('Mode must be selective or full.')
    if type(revision) is not int or revision < 1:
        raise ValueError('Revision must be a positive integer.')
    goal = m.Goal(**(goal.model_dump() if isinstance(goal, m.Goal) else goal))
    catalog = deepcopy(m.CATALOG if catalog is None else catalog)
    _validate_catalog(catalog)
    products = {p['id']: p for p in catalog['products']}
    if goal.laptop_id not in {p['id'] for p in catalog['laptops']}:
        raise ValueError('The reviewed laptop is absent from this snapshot.')
    if any(s not in catalog['sources'] for s in inspected) or any(p not in products for p in excluded):
        raise ValueError('Unknown inspected source or excluded product.')
    inspected, excluded = sorted(set(inspected)), sorted(set(excluded))
    previous_items = deepcopy(previous_items or [])
    if any(i.get('product_id') not in products or type(i.get('quantity')) is not int
           or i['quantity'] < 1 for i in previous_items):
        raise ValueError('Repair reference must contain known positive-quantity products.')
    source = source_sha256 or m.source_identity()
    algorithm = algorithm_identity()
    world = _world(goal, catalog, inspected, excluded, revision, source, previous_items)
    cache_usable = bool(previous and previous.get('schema') == SCHEMA and
                        previous.get('identities', {}).get('algorithm_sha256') == algorithm and
                        isinstance(previous.get('_cache'), dict) and
                        previous.get('_cache_sha256') == digest(previous['_cache']))
    prior_cache = previous['_cache'] if cache_usable and mode == 'selective' else {}
    rows, cache, dependencies = {}, {}, {}
    rechecked = 0
    for basket in m.candidates(goal, excluded, catalog=catalog):
        if len(rows) >= MAX_CANDIDATES:
            raise ValueError('Candidate universe exceeds the bounded certificate envelope.')
        bid = m.basket_key(basket)
        dep = _dependencies(goal, basket, catalog)
        keys = sorted({k for values in dep.values() for k in values})
        identity = digest({'items': basket, 'dependencies': {k: world[k] for k in keys}})
        old = prior_cache.get(bid)
        if old and old.get('dependency_sha256') == identity:
            row = deepcopy(old['row'])
        else:
            evaluated = m.evaluate(goal, basket, inspected, catalog=catalog)
            row = {k: evaluated[k] for k in ('id', 'items', 'total_cents', 'checks', 'failed', 'unknown', 'valid')}
            rechecked += 1
        rows[bid] = row
        cache[bid] = {'dependency_sha256': identity, 'row': row}
        dependencies[bid] = dep
    prior = {products[i['product_id']]['kind']: (i['product_id'], i['quantity']) for i in previous_items}
    def rank(row):
        current = {products[i['product_id']]['kind']: (i['product_id'], i['quantity']) for i in row['items']}
        changed = sum(prior.get(k) != current.get(k) for k in prior.keys() | current.keys()) if prior else 0
        return changed, row['total_cents'], row['id']
    valid = sorted((r for r in rows.values() if r['valid']), key=rank)
    best = valid[0] if valid else None
    selected_items = deepcopy(best['items'] if items is None and best else (items or []))
    selected_id = m.basket_key(selected_items) if selected_items else None
    selected = rows.get(selected_id)
    # Digest lookup alone is insufficient: structure and exact integer quantity
    # equality are required, including against bool-as-int dictionary equality.
    if selected and (selected['items'] != selected_items or any(type(i.get('quantity')) is not int for i in selected_items)):
        selected = None
    uncertain_better = [r['id'] for r in rows.values() if not r['failed'] and r['unknown'] and
                        (selected is None or rank(r) < rank(selected))]
    feasibility_status = 'verified' if selected and selected['valid'] else 'unresolved' if selected and not selected['failed'] else 'invalid' if selected_items else 'no_plan'
    optimality_status = ('unavailable' if not selected or not selected['valid'] else
                         'superseded' if best['id'] != selected_id else
                         'unresolved' if uncertain_better else 'verified')
    world['basket'] = digest(selected_items)
    old_world = previous.get('dependency_fingerprints', {}) if previous else {}
    changes = [Change(kind=_change_kind(k), path=k, before_sha256=old_world.get(k), after_sha256=world.get(k)).model_dump()
               for k in sorted(old_world.keys() | world.keys()) if old_world.get(k) != world.get(k)] if previous else []
    binding = digest({'goal': goal.model_dump(), 'basket': selected_items,
                      'total_cents': selected['total_cents'] if selected else None,
                      'currency': 'USD', 'catalog_sha256': digest(catalog),
                      'source_sha256': source, 'algorithm_sha256': algorithm, 'revision': revision,
                      'observations': {k: v for k, v in world.items() if k.startswith('fact.')}})
    same_binding = bool(previous and previous.get('claims', {}).get('authorization', {}).get('binding_sha256') == binding)
    selected_deps = dependencies.get(selected_id, {})
    source_support = {}
    if selected:
        for item in selected['items']:
            product = products[item['product_id']]
            for field in FIELDS[product['kind']]:
                fact = m.fact(product, field, inspected, catalog=catalog)
                source_support[f'{product["id"]}:{field}'] = {
                    'status': fact['status'], 'source_ids': fact['sources'],
                    'observation_sha256': world[f'fact.{product["id"]}.{field}'],
                }
    public = {
        'schema': SCHEMA,
        'identities': {'algorithm_sha256': algorithm, 'catalog_sha256': digest(catalog),
                       'goal_sha256': digest(goal.model_dump()), 'source_sha256': source,
                       'observations_sha256': digest({k: v for k, v in world.items() if k.startswith('fact.')}),
                       'snapshot_sha256': digest(world)},
        'revision': revision,
        'claims': {
            'feasibility': {'status': feasibility_status, 'basket_id': selected_id,
                            'checks': selected['checks'] if selected else {},
                            'unresolved_facts': selected['unknown'] if selected else [],
                            'note': 'Only declared fixture constraints and observed source values; no real hardware certificate.'},
            'optimality': {'status': optimality_status, 'best_verified_basket_id': best['id'] if best else None,
                           'potentially_better_unresolved_candidates': len(uncertain_better),
                           'objective': 'changed slots, cents, stable ID' if previous_items else 'cents, stable ID',
                           'note': 'Bounded candidate universe. Unresolved includes contradictory observations that could affect a better plan.'},
            'authorization': {'status': 'binding_unchanged' if same_binding else 'review_required',
                              'binding_sha256': binding, 'consent_granted': False,
                              'note': 'Advisory decision binding only. Exact quote, expiry, session ownership and explicit approval remain separate gates.'},
            'execution': {'status': 'unknown', 'label': 'See receipt',
                          'note': 'Planning cannot establish payment outcome; reconcile the owned provider receipt.'},
        },
        'constraint_dependencies': selected_deps,
        'selected_evidence': source_support,
        'changes': changes,
        'work': {'mode': mode, 'candidate_count': len(rows), 'rechecked_candidates': rechecked,
                 'reused_candidates': len(rows) - rechecked, 'cache_accepted': cache_usable and mode == 'selective',
                 'note': 'Counts of candidate evaluations, not measured latency, model tokens or cash savings.'},
    }
    public['certificate_sha256'] = digest(public)
    return {**public, 'dependency_fingerprints': world, '_cache': cache, '_cache_sha256': digest(cache)}


def semantic_claims(certificate):
    """Stable comparison target for selective-versus-full recomputation."""
    return deepcopy({'identities': certificate['identities'], 'claims': certificate['claims'],
                     'constraint_dependencies': certificate['constraint_dependencies'],
                     'selected_evidence': certificate['selected_evidence']})
