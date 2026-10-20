"""Freeze/reproduce the CPU-only adaptive-inspection fixture experiment.

No app, configuration, database, credential, network or provider imports. World
decisions are generated with the separate Missions oracle, not acquisition.py.
"""
import argparse
import copy
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
from itertools import product
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart.acquisition import (ExactReference, carry_evidence, load_problem, run_episode)
from scripts import missions_oracle as oracle

PROTOCOL = ROOT / "intentcart/data/acquisition-protocol.json"
CASES = ROOT / "intentcart/data/acquisition-cases.json"
REPORT = ROOT / "intentcart/data/acquisition-evaluation.json"
DEFAULT_GOAL = {"laptop_id": "studio-pro", "budget_cents": 35000, "displays": 2,
                "height": 1080, "hz": 60, "reuse_monitor": True, "allow_driver": False}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def query_id(spec):
    return f"{spec['product']}.{spec['field']}"


def generate_cases(protocol):
    """Derive all hypothetical decisions from the actual fictional catalog.

    Each query changes one catalog field, price or availability. All other
    hidden catalog observations are explicitly known in this experiment. A
    CONFLICT option keeps the catalog's two contradictory display observations;
    it never picks one as truth. Values are synthetic declared alternatives.
    """
    original_data, original_items = oracle.DATA, oracle.ITEMS
    cases = []
    try:
        for spec in protocol["scenario_specs"]:
            goal = {**DEFAULT_GOAL, **spec["goal"]}
            queries = [{"id": query_id(query), "cost": query["cost"],
                        "version": "2" if query_id(query) in spec.get("stale_queries", []) else "1"}
                       for query in spec["queries"]]
            worlds, observations_by_world = [], {}
            for wi, selected in enumerate(product(*(range(len(query["values"])) for query in spec["queries"]))):
                data = copy.deepcopy(original_data)
                items = {item["id"]: item for item in data["products"]}
                excluded = list(spec.get("excluded", []))
                answers, observations, weight = {}, [], 1
                for query, option in zip(spec["queries"], selected):
                    key, value = query_id(query), query["values"][option]
                    answers[key] = canonical(value)
                    weight *= query["weights"][option]
                    item = items[query["product"]]
                    if query["field"] == "price_cents":
                        item["price_cents"] = value
                    elif query["field"] == "available":
                        if not value:
                            excluded.append(item["id"])
                    elif value != "CONFLICT":
                        matches = [obs for obs in item["observations"] if obs["field"] == query["field"]]
                        if not matches:
                            raise ValueError(f"Unknown fixture field {key}")
                        for observation in matches:
                            observation["value"] = value
                            source = data["sources"][observation["source_id"]]
                            source["value"] = value
                            source["excerpt"] = f"Declared hypothetical fixture / {query['field']}: {value}."
                    if key in spec.get("cached_queries", []):
                        prior_value = query["values"][(option + 1) % len(query["values"])] if key in spec.get("stale_queries", []) else value
                        observations.append({"query_id": key, "version": "1", "value": canonical(prior_value)})
                oracle.DATA, oracle.ITEMS = data, items
                inspected = [obs["source_id"] for item in items.values() for obs in item["observations"]]
                best = oracle.best(goal, inspected, excluded)
                decision = canonical({"items": best[1], "total_cents": best[0][1]}) if best else None
                world_id = f"w{wi:03d}"
                worlds.append({"id": world_id, "weight": weight, "answers": answers, "decision": decision})
                observations_by_world[world_id] = observations
            payload = {"schema": "intentcart-acquisition/1", "id": spec["id"],
                       "revision": "2" if spec.get("previous_goal") else "1",
                       "queries": queries, "worlds": worlds, "initial_evidence": []}
            load_problem(payload)
            cases.append({"family": spec["family"], "split": spec["split"], "goal": goal,
                          "previous_goal": ({**DEFAULT_GOAL, **spec["previous_goal"]} if spec.get("previous_goal") else None),
                          "excluded": spec.get("excluded", []), "problem": payload,
                          "prior_observations_by_world": observations_by_world,
                          "prior_observation_cost": sum(query["cost"] for query in spec["queries"]
                                                         if query_id(query) in spec.get("cached_queries", []))})
    finally:
        oracle.DATA, oracle.ITEMS = original_data, original_items
    return {"schema": "intentcart-acquisition-cases/1", "protocol_sha256": sha(PROTOCOL),
            "catalog_sha256": sha(ROOT / "intentcart/data/missions-catalog.json"),
            "oracle_sha256": sha(ROOT / "scripts/missions_oracle.py"), "cases": cases}


def aggregate(rows, cases, split, policy, budget_label):
    selected_cases = [case for case in cases if case["split"] == split]
    selected = [row for row in rows if row["split"] == split and row["policy"] == policy and row["budget_label"] == budget_label]
    case_summaries = []
    for case in selected_cases:
        part = [row for row in selected if row["problem_id"] == case["problem"]["id"]]
        mass = sum(row["weight"] for row in part)
        solvable_mass = sum(row["weight"] for row in part if row["solvable"])
        infeasible_mass = mass - solvable_mass
        weighted = lambda key: sum(row["weight"] * row[key] for row in part) / mass
        case_summaries.append({"problem_id": case["problem"]["id"], "family": case["family"],
                               "worlds": len(part), "valid_completion": weighted("valid_completion"),
                               "solvable_completion": (float(Fraction(sum(row["weight"] * row["valid_completion"] for row in part if row["solvable"]), solvable_mass)) if solvable_mass else None),
                               "infeasible_correct": (float(Fraction(sum(row["weight"] * row["valid_completion"] for row in part if not row["solvable"]), infeasible_mass)) if infeasible_mass else None),
                               "expected_cost": weighted("spent"), "expected_inspections": weighted("inspections"),
                               "expected_total_cost_including_prior": weighted("total_cost_including_prior"),
                               "expected_adaptive_reference": weighted("exact_expected_cost"),
                               "false_defer": sum(row["false_defer"] for row in part),
                               "budget_defer_solvable": sum(row["budget_defer_solvable"] for row in part)})
    return {"split": split, "policy": policy, "budget_label": budget_label,
            "scenario_structures": len(selected_cases), "world_episodes": len(selected),
            "solvable_world_episodes": sum(row["solvable"] for row in selected),
            "infeasible_world_episodes": sum(not row["solvable"] for row in selected),
            "valid_completion": sum(row["valid_completion"] for row in selected),
            "unsupported_decisions": sum(row["unsupported_decision"] for row in selected),
            "false_infeasibility": sum(row["false_defer"] for row in selected),
            "budget_defer_solvable": sum(row["budget_defer_solvable"] for row in selected),
            "raw_cost_units": sum(row["spent"] for row in selected),
            "macro_prior_weighted_completion": sum(case["valid_completion"] for case in case_summaries) / len(case_summaries),
            "macro_expected_cost": sum(case["expected_cost"] for case in case_summaries) / len(case_summaries),
            "cases": case_summaries}


def evaluate(dataset, protocol):
    rows = []
    for case in dataset["cases"]:
        problem = load_problem(case["problem"])
        reference = ExactReference(problem)
        truth_by_id = {world.id: world for world in problem.worlds}
        for world in problem.worlds:
            prior = case["prior_observations_by_world"][world.id]
            retained, discarded = carry_evidence(prior, problem)
            # Reference is conditioned only on reusable observations, not truth.
            from intentcart.acquisition import posterior
            state, _, _ = posterior(problem, retained)
            expected_reference = float(reference.solve(state)[0])
            for policy in protocol["policies"]:
                selected_observations = [] if policy == "restart_decision_split" else prior
                controller = "decision_split" if policy == "restart_decision_split" else policy
                for label in protocol["budgets"]:
                    budget = sum(query.cost for query in problem.queries) if label == "unlimited" else label
                    run = run_episode(problem, world.id, controller, budget, selected_observations, reference)
                    completed = run["status"] in ("DECIDED", "INFEASIBLE")
                    supported_state, _, _ = posterior(problem, run["observations"])
                    supported = bool(supported_state) and all(problem.worlds[index].decision == run["decision"] for index in supported_state)
                    correct = completed and supported and run["decision"] == truth_by_id[world.id].decision
                    row = {**run, "policy": policy, "family": case["family"], "split": case["split"],
                           "budget_label": str(label), "weight": world.weight,
                           "solvable": world.decision is not None, "valid_completion": correct,
                           "unsupported_decision": completed and not supported,
                           "false_defer": run["status"] == "INFEASIBLE" and world.decision is not None,
                           "budget_defer_solvable": run["status"] == "BUDGET_EXHAUSTED" and world.decision is not None,
                           "retained_prior_observations": 0 if policy == "restart_decision_split" else len(retained),
                           "discarded_prior_observations": len(prior) if policy == "restart_decision_split" else len(discarded),
                           "prior_observation_cost": case["prior_observation_cost"],
                           "total_cost_including_prior": run["spent"] + case["prior_observation_cost"],
                           "exact_expected_cost": expected_reference}
                    # The compact trace carries answers and costs. Initial
                    # observations are reproducible from the frozen case file.
                    del row["observations"]
                    rows.append(row)
    summaries = [aggregate(rows, dataset["cases"], split, policy, str(budget))
                 for split in ("development", "structural_check")
                 for policy in protocol["policies"] for budget in protocol["budgets"]]
    return {"schema": "intentcart-acquisition-evaluation/1", "generated_at": datetime.now(timezone.utc).isoformat(),
            "notice": "Deterministic closed-world fictional fixture experiment. No model, GPU, provider, real inventory, people, or superiority/generalization claim.",
            "protocol": {key: value for key, value in protocol.items() if key != "scenario_specs"},
            "source_sha256": {str(path.relative_to(ROOT)): sha(path) for path in (
                ROOT / "intentcart/acquisition.py", ROOT / "scripts/evaluate_acquisition.py",
                ROOT / "scripts/missions_oracle.py", ROOT / "intentcart/data/missions-catalog.json", PROTOCOL, CASES)},
            "counts": {"scenario_structures": len(dataset["cases"]),
                       "worlds": sum(len(case["problem"]["worlds"]) for case in dataset["cases"]),
                       "policies": len(protocol["policies"]), "budgets": len(protocol["budgets"]), "paired_rows": len(rows)},
            "summary": summaries, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true", help="Create the frozen case file if absent; never silently replace it")
    parser.add_argument("--check", action="store_true", help="Reproduce and compare all fields except generated_at without rewriting")
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    protocol = json.loads(PROTOCOL.read_text())
    generated = generate_cases(protocol)
    if args.freeze:
        if CASES.exists():
            raise SystemExit("Case file already exists; retain it and use --check.")
        CASES.write_text(json.dumps(generated, indent=2) + "\n")
    if not CASES.exists():
        raise SystemExit("No frozen cases; run --freeze once after reviewing the protocol.")
    dataset = json.loads(CASES.read_text())
    if dataset != generated:
        raise SystemExit("Frozen cases do not match protocol/catalog/oracle. Preserve the old evidence and explicitly version a new experiment.")
    report = evaluate(dataset, protocol)
    if args.check:
        previous = json.loads(args.output.read_text())
        if {key: value for key, value in previous.items() if key != "generated_at"} != {key: value for key, value in report.items() if key != "generated_at"}:
            raise SystemExit("Saved acquisition evidence does not reproduce (including source identities).")
        print("All acquisition rows, aggregates, frozen cases and source hashes reproduce; timestamp excluded.")
    else:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"report": str(args.output), **report["counts"]}, indent=2))


if __name__ == "__main__":
    main()
