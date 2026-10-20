"""Offline snapshot, reuse and authorization-separation regressions."""
from copy import deepcopy
import json
import random

import pytest

from intentcart import missions as m, validity as v


def changed_catalog(pid, field, value):
    catalog = deepcopy(m.CATALOG)
    item = next(p for p in catalog['products'] if p['id'] == pid)
    if field in ('price_cents', 'name'):
        item[field] = value
    else:
        for observation in item['observations']:
            if observation['field'] == field:
                observation['value'] = value
                catalog['sources'][observation['source_id']]['value'] = value
    return catalog


def full_matches(selective, goal, **kwargs):
    reference = v.analyze(goal, mode='full', **kwargs)
    assert v.semantic_claims(selective) == v.semantic_claims(reference)
    assert reference['work']['rechecked_candidates'] == reference['work']['candidate_count']
    return reference


def test_certificate_distinguishes_feasible_from_unresolved_optimality_and_execution():
    goal = m.Goal()
    certificate = v.analyze(goal)
    assert certificate['claims']['feasibility']['status'] == 'verified'
    assert certificate['claims']['optimality']['status'] == 'unresolved'
    assert certificate['claims']['optimality']['potentially_better_unresolved_candidates'] > 0
    assert certificate['claims']['authorization']['consent_granted'] is False
    assert certificate['claims']['execution']['status'] == 'unknown'
    assert certificate['claims']['execution']['label'] == 'See receipt'
    assert set(certificate['constraint_dependencies']) == {*m.LABELS, 'structure'}
    assert all(e['source_ids'] and e['status'] == 'verified_fixture'
               for e in certificate['selected_evidence'].values())


def test_irrelevant_presentation_change_reuses_all_rows_but_never_reuses_approval():
    goal = m.Goal()
    previous = v.analyze(goal)
    catalog = changed_catalog('dock-solo', 'name', 'A revised display name')
    actual = v.analyze(goal, catalog=catalog, previous=previous)
    assert actual['work']['rechecked_candidates'] == 0
    assert actual['work']['reused_candidates'] == actual['work']['candidate_count']
    assert actual['claims']['feasibility'] == previous['claims']['feasibility']
    assert actual['claims']['authorization']['status'] == 'review_required'
    assert actual['claims']['authorization']['consent_granted'] is False
    full_matches(actual, goal, catalog=catalog, previous=previous)


def test_cheaper_competitor_supersedes_optimality_without_invalidating_feasibility():
    goal = m.Goal(budget_cents=80000)
    previous = v.analyze(goal)
    selected = m.solve(goal)['plan']['items']
    catalog = changed_catalog('dock-pro', 'price_cents', 100)
    actual = v.analyze(goal, items=selected, catalog=catalog, previous=previous)
    assert actual['claims']['feasibility']['status'] == 'verified'
    assert actual['claims']['optimality']['status'] == 'superseded'
    assert actual['claims']['optimality']['best_verified_basket_id'] != m.basket_key(selected)
    assert 0 < actual['work']['rechecked_candidates'] < actual['work']['candidate_count']
    assert any(c['kind'] == 'price' for c in actual['changes'])
    full_matches(actual, goal, items=selected, catalog=catalog, previous=previous)


@pytest.mark.parametrize('change', ['price', 'goal', 'revision', 'source'])
def test_changed_purchase_terms_or_version_always_invalidate_advisory_binding(change):
    goal = m.Goal()
    previous = v.analyze(goal)
    kwargs = {'previous': previous}
    if change == 'price': kwargs['catalog'] = changed_catalog('dock-twin', 'price_cents', 12901)
    elif change == 'goal': goal = m.Goal(budget_cents=35001)
    elif change == 'revision': kwargs['revision'] = 2
    else: kwargs['source_sha256'] = 'different-source'
    actual = v.analyze(goal, **kwargs)
    assert actual['claims']['authorization']['status'] == 'review_required'
    assert actual['claims']['authorization']['binding_sha256'] != previous['claims']['authorization']['binding_sha256']
    assert actual['claims']['authorization']['consent_granted'] is False
    assert actual['claims']['execution'] == previous['claims']['execution']
    if change in ('revision', 'source'):
        assert actual['work']['rechecked_candidates'] == 0
    full_matches(actual, goal, **kwargs)


def test_unchanged_snapshot_binding_still_does_not_grant_consent():
    first = v.analyze(m.Goal())
    actual = v.analyze(m.Goal(), previous=first)
    assert actual['claims']['authorization']['status'] == 'binding_unchanged'
    assert actual['claims']['authorization']['consent_granted'] is False
    assert actual['work']['rechecked_candidates'] == 0
    assert actual['changes'] == []


def test_contradictory_selected_fact_fails_closed_and_only_rechecks_dependent_rows():
    goal = m.Goal()
    first = v.analyze(goal)
    selected = m.solve(goal)['plan']['items']
    catalog = deepcopy(m.CATALOG)
    dock = next(p for p in catalog['products'] if p['id'] == 'dock-twin')
    observation = {'field': 'displays', 'value': 1, 'source_id': 'contradictory-display-count', 'visible': True}
    dock['observations'].append(observation)
    catalog['sources'][observation['source_id']] = {
        **catalog['sources']['dock-twin-displays'], 'id': observation['source_id'], 'value': 1}
    actual = v.analyze(goal, catalog=catalog, items=selected, previous=first)
    assert actual['claims']['feasibility']['status'] == 'unresolved'
    assert actual['claims']['feasibility']['checks']['displays'] is None
    assert actual['selected_evidence']['dock-twin:displays']['status'] == 'conflict'
    assert 0 < actual['work']['rechecked_candidates'] < actual['work']['candidate_count']
    full_matches(actual, goal, catalog=catalog, items=selected, previous=first)


@pytest.mark.parametrize('source_field,value', [('value', 1), ('variant', 'another-variant'), ('unit', 'inches')])
def test_inconsistent_source_evidence_is_not_verified(source_field, value):
    goal = m.Goal()
    catalog = deepcopy(m.CATALOG)
    catalog['sources']['dock-twin-displays'][source_field] = value
    selected = m.solve(goal)['plan']['items']
    actual = v.analyze(goal, catalog=catalog, items=selected)
    assert actual['claims']['feasibility']['status'] == 'unresolved'
    assert actual['selected_evidence']['dock-twin:displays']['status'] == 'conflict'


def test_known_relevant_counterexample_invalidates_selected_feasibility():
    goal = m.Goal()
    previous = v.analyze(goal)
    catalog = changed_catalog('dock-twin', 'displays', 1)
    actual = v.analyze(goal, catalog=catalog, items=m.solve(goal)['plan']['items'], previous=previous)
    assert actual['claims']['feasibility']['status'] == 'invalid'
    assert actual['claims']['feasibility']['checks']['displays'] is False
    assert actual['claims']['optimality']['status'] == 'unavailable'


def test_removed_selected_product_is_not_a_canonical_basket():
    goal = m.Goal()
    first = v.analyze(goal)
    selected = m.solve(goal)['plan']['items']
    actual = v.analyze(goal, excluded=['dock-twin'], items=selected, previous=first)
    assert actual['claims']['feasibility']['status'] == 'invalid'
    assert actual['work']['rechecked_candidates'] == 0
    assert actual['work']['candidate_count'] < first['work']['candidate_count']
    full_matches(actual, goal, excluded=['dock-twin'], items=selected, previous=first)


def test_repair_objective_matches_existing_solver_without_changing_its_plan():
    goal = m.Goal()
    selected = m.solve(goal)['plan']['items']
    first = v.analyze(goal)
    expected = m.solve(goal, excluded=['dock-twin'], previous=selected)['plan']
    actual = v.analyze(goal, excluded=['dock-twin'], previous_items=selected, previous=first)
    assert actual['claims']['optimality']['best_verified_basket_id'] == expected['id']
    assert actual['claims']['optimality']['objective'] == 'changed slots, cents, stable ID'
    full_matches(actual, goal, excluded=['dock-twin'], previous_items=selected, previous=first)


def test_cache_corruption_or_old_algorithm_forces_full_recomputation():
    first = v.analyze(m.Goal())
    for corruption in ('row', 'algorithm'):
        broken = deepcopy(first)
        if corruption == 'row': next(iter(broken['_cache'].values()))['row']['valid'] = True
        else: broken['identities']['algorithm_sha256'] = 'obsolete'
        actual = v.analyze(m.Goal(), previous=broken)
        assert actual['work']['cache_accepted'] is False
        assert actual['work']['rechecked_candidates'] == actual['work']['candidate_count']
        full_matches(actual, m.Goal(), previous=broken)


def test_public_certificate_contains_no_cache_or_hidden_source_values():
    catalog = deepcopy(m.CATALOG)
    sentinel = 'hidden-observation-never-export-this-value'
    mystery = next(p for p in catalog['products'] if p['id'] == 'dock-mystery')
    observation = next(o for o in mystery['observations'] if o['field'] == 'protocol')
    assert observation['visible'] is False
    observation['value'] = sentinel
    source = catalog['sources'][observation['source_id']]
    source['value'] = sentinel
    source['excerpt'] = sentinel
    certificate = v.analyze(m.Goal(), catalog=catalog)
    public = v.public_certificate(certificate)
    serialized = json.dumps(public)
    assert sentinel not in serialized
    assert sentinel not in json.dumps(certificate)
    assert '_cache' not in public and 'dependency_fingerprints' not in public
    public['claims']['execution']['status'] = 'fabricated'
    assert certificate['claims']['execution']['status'] == 'unknown'


def test_mission_revision_stores_reusable_cache_and_public_copy_never_mutates_it():
    mission = m.create('fixture request', m.Goal())
    public = m.public_record(mission)
    assert '_cache' in mission['validity']
    assert '_cache' not in json.dumps(public)
    assert 'dependency_fingerprints' not in json.dumps(public)
    revised = m.revise(mission, inspect='dock-archive-max_height')
    assert revised['validity']['claims']['authorization']['status'] == 'review_required'
    assert revised['validity']['work']['reused_candidates'] > 0
    assert revised['result']['validity'] == v.public_certificate(revised['validity'])
    assert mission['revision'] == 1 and mission['inspected'] == []


def test_catalog_override_is_pure_and_default_solver_matches_override():
    goal = m.Goal()
    original = deepcopy(m.CATALOG)
    assert m.solve(goal) == m.solve(goal, catalog=deepcopy(original))
    catalog = changed_catalog('dock-pro', 'price_cents', 1)
    assert m.solve(goal, catalog=catalog)['plan']['total_cents'] < m.solve(goal)['plan']['total_cents']
    v.analyze(goal, catalog=catalog)
    assert m.CATALOG == original


def test_selective_and_full_agree_on_seeded_mixed_snapshot_changes():
    rng = random.Random(7324)
    catalog, goal = deepcopy(m.CATALOG), m.Goal()
    inspected, excluded = [], []
    previous = v.analyze(goal, catalog=catalog)
    for revision in range(2, 26):
        action = rng.choice(['price', 'inspect', 'goal', 'exclude', 'name'])
        if action in ('price', 'name'):
            item = rng.choice(catalog['products'])
            item['price_cents' if action == 'price' else 'name'] = rng.randrange(100, 25000) if action == 'price' else f'Fixture label {revision}'
        elif action == 'inspect':
            inspected = sorted(set([*inspected, rng.choice(list(catalog['sources']))]))
        elif action == 'goal':
            goal = m.Goal(budget_cents=rng.choice([20000, 35000, 80000]), displays=rng.choice([1, 2]),
                          reuse_monitor=rng.choice([True, False]), allow_driver=rng.choice([True, False]))
        else:
            excluded = rng.sample([p['id'] for p in catalog['products']], rng.randrange(3))
        kwargs = {'catalog': catalog, 'inspected': inspected, 'excluded': excluded,
                  'revision': revision, 'previous': previous}
        actual = v.analyze(goal, **kwargs)
        full_matches(actual, goal, **kwargs)
        assert actual['claims']['authorization']['consent_granted'] is False
        previous = actual


@pytest.mark.parametrize('bad', ['negative_price', 'duplicate_id', 'bool_fact', 'unknown_source'])
def test_malformed_snapshot_fails_closed(bad):
    catalog = deepcopy(m.CATALOG)
    if bad == 'negative_price': catalog['products'][0]['price_cents'] = -1
    elif bad == 'duplicate_id': catalog['products'][1]['id'] = catalog['products'][0]['id']
    elif bad == 'bool_fact': catalog['products'][0]['observations'][1]['value'] = True
    else: catalog['products'][0]['observations'][0]['source_id'] = 'absent'
    with pytest.raises(ValueError): v.analyze(m.Goal(), catalog=catalog)
