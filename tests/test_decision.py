import json
from pathlib import Path
import numpy as np
import pytest
from intentcart.learning import posterior, PARTICLES
from intentcart.decision import assess, distribution, QUESTION_COST, RISK_LIMIT, BAD_REGRET
from scripts.evaluate_robustness import cases, simulate, paired, PROTOCOL

CATALOG = json.loads((Path(__file__).parents[1]/'intentcart/data/catalog.json').read_text())

def test_no_forgetting_matches_original_including_ties_and_skips():
    history = [{'a': CATALOG[0]['id'], 'b': CATALOG[1]['id'], 'choice': choice} for choice in ('a', 'tie', 'skip', 'b')]
    prior = [0, 1, 0, 1, 0, 0, 0]
    utilities, expected = posterior(CATALOG, history, prior)
    np.testing.assert_allclose(distribution(utilities, [(0, 1, h['choice']) for h in history], prior, 1), expected, atol=1e-15)

def test_recent_likelihood_has_more_influence_and_skip_does_not_age_evidence():
    utilities = np.tile([[1., 0.], [0., 1.]], (1024, 1))
    history = [(0, 1, 'a'), (0, 1, 'b')]
    equal = distribution(utilities, history)
    recent = distribution(utilities, history, decay=.5)
    assert equal[1] == pytest.approx(equal[0])
    assert recent[1] > recent[0]*100
    np.testing.assert_array_equal(recent, distribution(utilities, [history[0], (0, 1, 'skip'), history[1]], decay=.5))

def test_controller_asks_then_defers_when_budget_is_spent():
    utilities = np.array([[1., 0.], [0., 1.]])
    weights = np.array([.5, .5])
    assert assess(utilities, weights, [0, 1])['action'] == 'ASK'
    result = assess(utilities, weights, [0, 1], answered=4)
    assert result['action'] == 'DEFER' and result['pair'] is None
    assert result['expected_regret'] == .5
    assert result['model_bad_probability'] == .5
    assert assess(utilities, weights, [0])['action'] == 'RECOMMEND'
    assert assess(None, None, [])['action'] == 'DEFER'
    assert assess(utilities, weights, [0, 1], attempts=8)['pair'] is None

def test_freeze_matches_runtime_thresholds():
    assert (QUESTION_COST, RISK_LIMIT, BAD_REGRET) == (PROTOCOL['question_cost'], PROTOCOL['risk_limit'], PROTOCOL['bad_regret'])

def test_split_identity_and_reserved_comparisons_are_independent():
    development = list(cases('development'))
    heldout = list(cases('heldout'))
    assert {c['sha256'] for c in development}.isdisjoint(c['sha256'] for c in heldout)
    assert len(development) == 140 and len(heldout) == 280
    for policy in ('decision', 'random', 'uncertainty', 'adaptive'):
        case = heldout[0]
        run = simulate(case, policy, .5)
        reserved = {tuple(sorted(pair)) for pair in case['reserved']}
        asked = [tuple(sorted((r['a'], r['b']))) for r in run['trace']]
        assert not reserved.intersection(asked)
        assert len(set(asked)) == len(asked)
        assert run['answers'] <= 4 and run['questions'] <= 8

def test_paired_bootstrap_uses_personas_and_retains_negative_values():
    rows = [{'case_id': str(i), 'family': f, 'value': 1.} for i, f in enumerate(PROTOCOL['families'])]
    other = [{**row, 'value': 2.} for row in rows]
    result = paired(rows, other, 'value')
    assert result['reduction'] == -1 and result['ci95'] == [-1., -1.]
    assert result['paired_personas'] == 7
