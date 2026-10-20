import copy
from fractions import Fraction
from itertools import product
import json
from pathlib import Path

import pytest

from intentcart.acquisition import (
    ExactReference, MAX_QUERIES, MAX_WORLDS, ProblemError, StateLimit,
    carry_evidence, decide, load_problem, posterior, run_episode,
)


def fixture_payload(function=lambda a, b: "valid" if a and b else None):
    return {"schema": "intentcart-acquisition/1", "id": "bounded", "revision": "1",
            "queries": [{"id": "a", "cost": 1, "version": "1"}, {"id": "b", "cost": 3, "version": "1"}],
            "worlds": [{"id": f"{a}{b}", "weight": (2 if a else 1), "answers": {"a": str(a), "b": str(b)},
                        "decision": function(a, b)} for a, b in product((0, 1), repeat=2)],
            "initial_evidence": []}


def observation(query="a", value="1", version="1"):
    return {"query_id": query, "version": version, "value": value}


def independent_tree_cost(worlds, queries):
    """Tiny brute-force adaptive tree enumeration without production helpers."""
    if len({world["decision"] for world in worlds}) == 1:
        return Fraction(0)
    total = sum(world["weight"] for world in worlds)
    alternatives = []
    for query in queries:
        answers = sorted({world["answers"][query["id"]] for world in worlds})
        if len(answers) == 1:
            continue
        cost = Fraction(query["cost"])
        for answer in answers:
            branch = [world for world in worlds if world["answers"][query["id"]] == answer]
            cost += Fraction(sum(world["weight"] for world in branch), total) * independent_tree_cost(
                branch, [other for other in queries if other["id"] != query["id"]])
        alternatives.append(cost)
    return min(alternatives)


@pytest.mark.parametrize("function", [lambda a, b: "valid" if a and b else None,
                                     lambda a, b: "same" if a == b else "different",
                                     lambda a, b: f"basket-{a}",
                                     lambda a, b: f"basket-{a}-{b}"])
def test_exact_matches_independent_adaptive_tree_and_realized_prior_cost(function):
    payload = fixture_payload(function)
    problem = load_problem(payload)
    reference = ExactReference(problem)
    expected, _ = reference.solve()
    assert expected == independent_tree_cost(payload["worlds"], payload["queries"])
    runs = [run_episode(problem, world.id, reference=reference) for world in problem.worlds]
    realized = Fraction(sum(world.weight * run["spent"] for world, run in zip(problem.worlds, runs)),
                        sum(world.weight for world in problem.worlds))
    assert realized == expected
    assert all(run["status"] in ("DECIDED", "INFEASIBLE") for run in runs)


def test_exact_choice_has_no_truth_argument_or_clairvoyant_world_selection():
    problem = load_problem(fixture_payload())
    runs = [run_episode(problem, world.id) for world in problem.worlds]
    assert {run["trace"][0]["query_id"] for run in runs} == {"a"}
    # Worlds with identical visible evidence take the same second action even
    # though they eventually produce different outcomes.
    assert runs[2]["trace"][1]["query_id"] == runs[3]["trace"][1]["query_id"] == "b"
    assert runs[2]["status"] == "INFEASIBLE" and runs[3]["status"] == "DECIDED"
    with pytest.raises(TypeError):
        decide(problem, truth_world_id="11")


def test_jointly_necessary_facts_do_not_become_unsupported_early_decisions():
    problem = load_problem(fixture_payload(lambda a, b: "same" if a == b else "different"))
    for policy in ("exact", "decision_split", "information"):
        assert decide(problem, policy=policy)["status"] == "QUERY"
        assert decide(problem, [observation()], policy)["status"] == "QUERY"
        assert run_episode(problem, "11", policy, budget=1)["status"] == "BUDGET_EXHAUSTED"


def test_budget_exhaustion_is_never_labeled_infeasibility():
    problem = load_problem(fixture_payload())
    deferred = run_episode(problem, "11", budget=1)
    assert deferred["status"] == "BUDGET_EXHAUSTED" and deferred["decision"] is None
    assert deferred["spent"] == 1 and deferred["possible_worlds"] == 2
    assert run_episode(problem, "00", budget=1)["status"] == "INFEASIBLE"
    assert run_episode(problem, "11", budget=0)["inspections"] == 0


def test_changed_goal_reuses_versioned_facts_but_recomputes_decision():
    payload = fixture_payload(lambda a, b: f"old-{a}")
    old = load_problem(payload)
    evidence = [observation(value="0")]
    assert decide(old, evidence)["decision"] == "old-0"
    payload["revision"] = "2"
    for world in payload["worlds"]:
        world["decision"] = f"new-{world['answers']['b']}"
    revised = load_problem(payload)
    kept, discarded = carry_evidence(evidence, revised)
    assert kept == evidence and discarded == []
    action = decide(revised, kept)
    assert action["query_id"] == "b" and action["problem_revision"] == "2"
    with pytest.raises(ProblemError, match="another problem revision"):
        decide(revised, evidence, reference=ExactReference(old))


def test_source_revision_discards_stale_observation_and_reacquires_it():
    payload = fixture_payload(lambda a, b: f"basket-{a}")
    payload["queries"][0]["version"] = "2"
    revised = load_problem(payload)
    kept, discarded = carry_evidence([observation(), observation("b", "0")], revised)
    assert kept == [observation("b", "0")] and discarded == [observation()]
    action = decide(revised, [observation(), observation("b", "0")])
    assert action["query_id"] == "a" and action["version"] == "2"
    assert action["discarded_observations"] == 1


def test_empty_and_contradictory_posteriors_fail_closed():
    problem = load_problem(fixture_payload())
    for evidence in ([observation(value="not-in-model")], [observation(value="0"), observation(value="1")]):
        assert posterior(problem, evidence)[0] == ()
        for policy in ("exact", "decision_split", "information", "full_census"):
            action = decide(problem, evidence, policy)
            assert action["status"] == "CONFLICT" and action["decision"] is None
    # A duplicate identical observation is idempotent, not a conflict.
    assert len(carry_evidence([observation(), observation()], problem)[0]) == 1


def test_constant_irrelevant_evidence_is_skipped_by_all_selective_policies():
    payload = fixture_payload(lambda a, b: f"basket-{a}")
    # b's values vary but cannot affect the decision; a already decides it.
    problem = load_problem(payload)
    for policy in ("exact", "decision_split", "information"):
        run = run_episode(problem, "11", policy)
        assert [step["query_id"] for step in run["trace"]] == ["a"]
    assert run_episode(problem, "11", "full_census")["inspections"] == 2


def test_policy_ties_and_input_permutations_are_deterministic():
    payload = fixture_payload(lambda a, b: f"basket-{a}-{b}")
    payload["queries"][1]["cost"] = 1
    for world in payload["worlds"]:
        world["weight"] = 1
    reordered = copy.deepcopy(payload)
    reordered["queries"].reverse()
    reordered["worlds"].reverse()
    for policy in ("exact", "decision_split", "information", "full_census"):
        original_run = run_episode(load_problem(payload), "11", policy)
        assert original_run == run_episode(load_problem(reordered), "11", policy)
        assert original_run["trace"][0]["query_id"] == "a"


def test_strict_schema_bounds_and_indistinguishable_inconsistent_worlds():
    for change in (lambda p: p.update(extra=True),
                   lambda p: p.update(schema="future/9"),
                   lambda p: p["queries"][0].update(cost=True),
                   lambda p: p["queries"][0].update(cost=0),
                   lambda p: p["worlds"][0].update(weight=0),
                   lambda p: p["worlds"][0]["answers"].update(extra="0"),
                   lambda p: p["worlds"][0].update(decision={"unknown": True}),
                   lambda p: p.update(queries=p["queries"] * MAX_QUERIES),
                   lambda p: p.update(worlds=p["worlds"] * MAX_WORLDS),
                   lambda p: p.update(initial_evidence=[observation(version="stale")])):
        payload = fixture_payload()
        change(payload)
        with pytest.raises(ProblemError):
            load_problem(payload)
    payload = fixture_payload()
    payload["worlds"].append({**payload["worlds"][0], "id": "extra", "decision": "contradiction"})
    with pytest.raises(ProblemError, match="Observationally identical"):
        load_problem(payload)


def test_exact_compute_limit_fails_explicitly_without_fake_reference_result():
    problem = load_problem(fixture_payload())
    with pytest.raises(StateLimit):
        ExactReference(problem, max_states=1).solve()
    with pytest.raises(ProblemError):
        decide(problem, policy="invented")
    with pytest.raises(ProblemError):
        decide(problem, remaining_budget=True)
    with pytest.raises(ProblemError):
        run_episode(problem, "not-a-world")


def test_frozen_catalog_cases_have_distinct_structures_and_reference_cost_identity():
    root = Path(__file__).resolve().parents[1]
    frozen_path = root / "intentcart/data/acquisition-cases.json"
    assert frozen_path.exists(), "Freeze reviewed acquisition cases before running release tests"
    data = json.loads(frozen_path.read_text())
    development = {case["family"] for case in data["cases"] if case["split"] == "development"}
    structural = {case["family"] for case in data["cases"] if case["split"] == "structural_check"}
    assert development and structural and not development.intersection(structural)
    for case in data["cases"]:
        problem = load_problem(case["problem"])
        reference = ExactReference(problem)
        mass = sum(world.weight for world in problem.worlds)
        spent, expected = 0, Fraction(0)
        for world in problem.worlds:
            prior = case["prior_observations_by_world"][world.id]
            state = posterior(problem, prior)[0]
            expected += Fraction(world.weight, mass) * reference.solve(state)[0]
            run = run_episode(problem, world.id, observations=prior, reference=reference)
            assert run["decision"] == world.decision
            assert run["status"] == ("INFEASIBLE" if world.decision is None else "DECIDED")
            spent += world.weight * run["spent"]
        assert Fraction(spent, mass) == expected


def test_hypothetical_observations_keep_matching_provenance_and_intentional_conflict(monkeypatch):
    from scripts import evaluate_acquisition as experiment
    original_best = experiment.oracle.best
    checked = []
    conflicts = []

    def check_then_grade(*args, **kwargs):
        data = experiment.oracle.DATA
        for item in data["products"]:
            for record in item["observations"]:
                source = data["sources"][record["source_id"]]
                assert source["product_id"] == item["id"]
                assert source["variant"] == item["variant"]
                assert source["field"] == record["field"]
                assert source["value"] == record["value"]
        conflict_dock = next(item for item in data["products"] if item["id"] == "dock-conflict")
        conflict_values = {record["value"] for record in conflict_dock["observations"] if record["field"] == "displays"}
        conflicts.append(len(conflict_values) > 1)
        checked.append(True)
        return original_best(*args, **kwargs)

    original_data, original_items = experiment.oracle.DATA, experiment.oracle.ITEMS
    monkeypatch.setattr(experiment.oracle, "best", check_then_grade)
    protocol = json.loads(experiment.PROTOCOL.read_text())
    generated = experiment.generate_cases(protocol)
    assert generated == json.loads(experiment.CASES.read_text())
    assert len(checked) == 122 and any(conflicts) and not all(conflicts)
    assert experiment.oracle.DATA is original_data and experiment.oracle.ITEMS is original_items
