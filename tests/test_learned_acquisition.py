import copy
import numpy as np
import pytest
from intentcart import learned_acquisition as l, acquisition as a
from scripts.evaluate_learned_acquisition import generate

def problem(seed=7):
    return generate({'family': 'conditional', 'queries': 3, 'maximum_cost': 3}, seed)

def test_teacher_first_query_cost_matches_exact_reference():
    p = problem()
    rows = l.teacher_rows(p)
    initial = [label for features, label in rows[:len(p.queries)]]
    assert min(initial) == pytest.approx(float(a.ExactReference(p).solve()[0]))

def test_training_deterministic_and_no_truth_argument():
    train = [problem(7), problem(8)]
    model = l.fit(train)
    assert model == l.fit(train)
    assert model['training_structures'] == 2 and model['training_state_query_rows'] > 2
    action = l.decide(problem(9), model)
    assert action['query_id'] in {q.id for q in problem(9).queries}
    assert l.decide(problem(9), model, remaining_budget=0)['status'] == 'BUDGET_EXHAUSTED'

@pytest.mark.parametrize('key,value', [('features', ['fake']), ('scale', [0]*7), ('coefficients', [float('nan')]*8)])
def test_invalid_model_fails_closed(key, value):
    model = l.fit([problem()])
    model[key] = value
    with pytest.raises(a.ProblemError): l.decide(problem(), model)

def test_every_terminal_output_supported_and_bounded():
    model = l.fit([problem(7), problem(8)])
    p = problem(17)
    for world in p.worlds:
        for budget in (0, 2, None):
            result = l.run_episode(p, world.id, model, budget)
            assert budget is None or result['new_cost'] <= budget
            assert result['status'] not in ('DECIDED', 'INFEASIBLE') or result['supported']

def test_observation_shift_conflict_and_version_reuse():
    p = problem()
    model = l.fit([p])
    assert l.decide(p, model, [{'query_id': 'q0', 'version': '1', 'value': 'not-a-world'}])['status'] == 'CONFLICT'
    stale = [{'query_id': 'q0', 'version': 'old', 'value': 'not-a-world'}]
    assert l.decide(p, model, stale) == l.decide(p, model)
