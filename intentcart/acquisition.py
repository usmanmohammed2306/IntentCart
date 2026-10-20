"""Bounded, deterministic acquisition over an explicitly supplied finite world model.

This module has no provider, storage, model, random, or mission-solver dependency.
A controller sees hypotheses and observations, never the environment's truth ID.
Consensus is a certificate inside the supplied closed world, not source truth.
"""
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import math
import re

SCHEMA = "intentcart-acquisition/1"
MAX_QUERIES = 12
MAX_WORLDS = 128
MAX_STATES = 20_000
POLICIES = ("exact", "decision_split", "information", "full_census")


class ProblemError(ValueError):
    """Invalid or ambiguous experiment input; callers must fail closed."""


class StateLimit(ProblemError):
    """The exact reference exceeded its declared compute bound."""


@dataclass(frozen=True)
class Query:
    id: str
    cost: int
    version: str


@dataclass(frozen=True)
class World:
    id: str
    weight: int
    answers: tuple[str, ...]
    decision: str | None


@dataclass(frozen=True)
class Problem:
    id: str
    revision: str
    queries: tuple[Query, ...]
    worlds: tuple[World, ...]
    initial_evidence: tuple[tuple[str, str, str], ...]


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ProblemError(f"{label} must contain exactly {sorted(expected)}")


def _text(value, label, maximum=160, identifier=False):
    if type(value) is not str or not value or len(value) > maximum:
        raise ProblemError(f"Invalid {label}")
    if identifier and not re.fullmatch(r"[a-zA-Z0-9:._/-]+", value):
        raise ProblemError(f"Invalid {label}")
    return value


def _integer(value, label, minimum=1, maximum=1_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProblemError(f"Invalid {label}")
    return value


def load_problem(payload):
    """Validate a strict v1 JSON problem and freeze its controller-visible data.

    Positive integer weights define a declared prior, not a learned/calibrated
    probability. All hypotheses must specify every query. ``None`` is the
    infeasible decision; an unknown outcome is never encoded as a decision.
    """
    _keys(payload, ("schema", "id", "revision", "queries", "worlds", "initial_evidence"), "problem")
    if payload["schema"] != SCHEMA:
        raise ProblemError("Unsupported acquisition schema")
    identifier = _text(payload["id"], "problem ID", identifier=True)
    revision = _text(payload["revision"], "revision", identifier=True)
    if type(payload["queries"]) is not list or not 1 <= len(payload["queries"]) <= MAX_QUERIES:
        raise ProblemError(f"Supply 1..{MAX_QUERIES} queries")
    queries = []
    for entry in payload["queries"]:
        _keys(entry, ("id", "cost", "version"), "query")
        queries.append(Query(_text(entry["id"], "query ID", identifier=True),
                             _integer(entry["cost"], "query cost"),
                             _text(entry["version"], "query version", identifier=True)))
    queries.sort(key=lambda query: query.id)
    ids = [query.id for query in queries]
    if len(set(ids)) != len(ids):
        raise ProblemError("Duplicate query ID")
    if type(payload["worlds"]) is not list or not 1 <= len(payload["worlds"]) <= MAX_WORLDS:
        raise ProblemError(f"Supply 1..{MAX_WORLDS} worlds")
    worlds = []
    for entry in payload["worlds"]:
        _keys(entry, ("id", "weight", "answers", "decision"), "world")
        _keys(entry["answers"], ids, "world answers")
        decision = entry["decision"]
        if decision is not None:
            _text(decision, "world decision", maximum=8192)
        worlds.append(World(_text(entry["id"], "world ID", identifier=True),
                            _integer(entry["weight"], "prior weight"),
                            tuple(_text(entry["answers"][key], "answer", maximum=256) for key in ids),
                            decision))
    worlds.sort(key=lambda world: world.id)
    if len({world.id for world in worlds}) != len(worlds):
        raise ProblemError("Duplicate world ID")
    answer_decisions = {}
    for world in worlds:
        if world.answers in answer_decisions and answer_decisions[world.answers] != world.decision:
            raise ProblemError("Observationally identical worlds cannot have different decisions")
        answer_decisions[world.answers] = world.decision
    problem = Problem(identifier, revision, tuple(queries), tuple(worlds), ())
    retained, discarded = carry_evidence(payload["initial_evidence"], problem)
    if discarded:
        raise ProblemError("Initial evidence must refer to current query versions")
    initial = tuple((entry["query_id"], entry["version"], entry["value"]) for entry in retained)
    return Problem(identifier, revision, tuple(queries), tuple(worlds), initial)


def carry_evidence(observations, new_problem):
    """Reuse only matching source IDs and versions across requirement revisions.

    The caller must change a source version when that source changes. A changed
    goal alone may retain observations, but all decisions are recomputed. This
    routine has no purchase/consent semantics and cannot grant authorization.
    """
    if type(observations) not in (list, tuple) or len(observations) > MAX_QUERIES * 2:
        raise ProblemError("Invalid observation list")
    versions = {query.id: query.version for query in new_problem.queries}
    retained, discarded = [], []
    seen = {}
    for entry in observations:
        _keys(entry, ("query_id", "version", "value"), "observation")
        key = _text(entry["query_id"], "observation query ID", identifier=True)
        version = _text(entry["version"], "observation version", identifier=True)
        value = _text(entry["value"], "observation value", maximum=256)
        clean = {"query_id": key, "version": version, "value": value}
        if key not in versions or versions[key] != version:
            discarded.append(clean)
        elif key not in seen:
            retained.append(clean)
            seen[key] = value
        elif seen[key] != value:
            # Preserve contradictory reports. posterior() explicitly reports
            # conflict rather than silently overwriting the earlier evidence.
            retained.append(clean)
    return sorted(retained, key=lambda entry: (entry["query_id"], entry["value"])), discarded


def posterior(problem, observations=()):
    initial = [{"query_id": key, "version": version, "value": value}
               for key, version, value in problem.initial_evidence]
    retained, discarded = carry_evidence([*initial, *observations], problem)
    indices = {query.id: index for index, query in enumerate(problem.queries)}
    possible = tuple(index for index, world in enumerate(problem.worlds)
                     if all(world.answers[indices[entry["query_id"]]] == entry["value"]
                            for entry in retained))
    return possible, retained, discarded


def _partitions(problem, state, query_index):
    groups = {}
    for index in state:
        groups.setdefault(problem.worlds[index].answers[query_index], []).append(index)
    return tuple(tuple(groups[key]) for key in sorted(groups))


def _consensus(problem, state):
    values = {problem.worlds[index].decision for index in state}
    return len(values) == 1, next(iter(values)) if len(values) == 1 else None


class ExactReference:
    """Optimal expected-cost adaptive decision tree for this finite prior.

    Dynamic programming never receives the actual world. The state is the
    posterior hypothesis subset. Positive costs imply a constant-answer query
    is never useful. Exact rational arithmetic gives deterministic tie breaks.
    Exponential worst-case search is bounded and raises instead of approximating.
    """
    def __init__(self, problem, max_states=MAX_STATES):
        self.problem = problem
        self.max_states = _integer(max_states, "state bound", maximum=MAX_STATES)
        self.states = 0
        self._solve = lru_cache(maxsize=None)(self._compute)

    def _compute(self, state):
        self.states += 1
        if self.states > self.max_states:
            raise StateLimit(f"Exact reference exceeds {self.max_states} posterior states")
        if not state:
            raise ProblemError("No hypothesis supports the supplied observations")
        if _consensus(self.problem, state)[0]:
            return Fraction(0), None
        mass = sum(self.problem.worlds[index].weight for index in state)
        candidates = []
        for qi, query in enumerate(self.problem.queries):
            branches = _partitions(self.problem, state, qi)
            if len(branches) < 2:
                continue
            cost = Fraction(query.cost)
            for branch in branches:
                branch_mass = sum(self.problem.worlds[index].weight for index in branch)
                cost += Fraction(branch_mass, mass) * self._solve(branch)[0]
            candidates.append((cost, query.id, qi))
        if not candidates:
            raise ProblemError("Hypotheses cannot be distinguished by the declared queries")
        cost, _, qi = min(candidates)
        return cost, qi

    def solve(self, state=None):
        return self._solve(tuple(range(len(self.problem.worlds))) if state is None else tuple(state))


def _heuristic_query(problem, state, policy):
    weights = {index: problem.worlds[index].weight for index in state}
    mass = sum(weights.values())
    counts = {}
    for index in state:
        decision = problem.worlds[index].decision
        counts[decision] = counts.get(decision, 0) + weights[index]
    before = 1 - sum(Fraction(weight * weight, mass * mass) for weight in counts.values())
    candidates = []
    for qi, query in enumerate(problem.queries):
        branches = _partitions(problem, state, qi)
        if len(branches) < 2:
            continue
        information = 0.0
        remaining_impurity = Fraction(0)
        for branch in branches:
            branch_mass = sum(weights[index] for index in branch)
            ratio = branch_mass / mass
            information -= ratio * math.log2(ratio)
            branch_counts = {}
            for index in branch:
                decision = problem.worlds[index].decision
                branch_counts[decision] = branch_counts.get(decision, 0) + weights[index]
            impurity = 1 - sum(Fraction(weight * weight, branch_mass * branch_mass)
                              for weight in branch_counts.values())
            remaining_impurity += Fraction(branch_mass, mass) * impurity
        gain = (before - remaining_impurity) / query.cost
        # Jointly necessary/XOR facts can have zero one-step decision gain.
        # Conditional hypothesis splitting provides a deterministic fallback.
        score = (gain, information / query.cost) if policy == "decision_split" else (information / query.cost, gain)
        candidates.append((score, query.id, qi))
    if not candidates:
        raise ProblemError("No informative query is available")
    best_score = max(candidate[0] for candidate in candidates)
    return min(candidate for candidate in candidates if candidate[0] == best_score)[2]


def decide(problem, observations=(), policy="exact", remaining_budget=None, reference=None):
    """Choose a query or a supported outcome; deliberately no truth argument.

    Under a finite budget, a policy is truncated before its next query exceeds
    that budget. The exact policy optimizes unrestricted expected total cost,
    not completion probability at every budget. Its label must not imply that.
    """
    if policy not in POLICIES:
        raise ProblemError("Unknown acquisition policy")
    if remaining_budget is not None:
        _integer(remaining_budget, "remaining budget", minimum=0, maximum=12_000_000)
    state, retained, discarded = posterior(problem, observations)
    common = {"possible_worlds": len(state), "retained_observations": len(retained),
              "discarded_observations": len(discarded), "problem_revision": problem.revision}
    if not state:
        return {**common, "status": "CONFLICT", "decision": None,
                "reason": "No declared world supports all current observations."}
    certain, value = _consensus(problem, state)
    observed = {entry["query_id"] for entry in retained}
    if certain and (policy != "full_census" or len(observed) == len(problem.queries)):
        return {**common, "status": "INFEASIBLE" if value is None else "DECIDED", "decision": value}
    expected = None
    if policy == "full_census":
        qi = next(index for index, query in enumerate(problem.queries) if query.id not in observed)
    elif policy == "exact":
        reference = reference or ExactReference(problem)
        if reference.problem != problem:
            raise ProblemError("Exact reference belongs to another problem revision")
        cost, qi = reference.solve(state)
        expected = {"numerator": cost.numerator, "denominator": cost.denominator,
                    "value": float(cost), "objective": "unrestricted expected acquisition cost"}
    else:
        qi = _heuristic_query(problem, state, policy)
    query = problem.queries[qi]
    if remaining_budget is not None and query.cost > remaining_budget:
        return {**common, "status": "BUDGET_EXHAUSTED", "decision": None,
                "next_query": query.id, "next_cost": query.cost, "expected_remaining_cost": expected}
    return {**common, "status": "QUERY", "query_id": query.id, "version": query.version,
            "cost": query.cost, "expected_remaining_cost": expected}


def run_episode(problem, truth_world_id, policy="exact", budget=None, observations=(), reference=None):
    """Offline environment runner. Truth is used only to answer chosen queries.

    The returned trace is a public fictional fixture artifact. Do not pass real
    account data here. No provider, clock, network or purchase action is involved.
    """
    worlds = {world.id: world for world in problem.worlds}
    if truth_world_id not in worlds:
        raise ProblemError("Unknown environment truth world")
    truth = worlds[truth_world_id]
    if budget is None:
        budget = sum(query.cost for query in problem.queries)
    _integer(budget, "episode budget", minimum=0, maximum=12_000_000)
    remaining = budget
    evidence = list(observations)
    trace = []
    if policy == "exact":
        reference = reference or ExactReference(problem)
    query_indices = {query.id: index for index, query in enumerate(problem.queries)}
    for step in range(len(problem.queries) + 1):
        action = decide(problem, evidence, policy, remaining, reference)
        if action["status"] != "QUERY":
            return {"schema": "intentcart-acquisition-episode/1", "problem_id": problem.id,
                    "revision": problem.revision, "world_id": truth_world_id, "policy": policy,
                    "budget": budget, "spent": budget - remaining, "inspections": len(trace),
                    "status": action["status"], "decision": action.get("decision"),
                    "possible_worlds": action["possible_worlds"], "trace": trace,
                    "observations": evidence}
        qi = query_indices[action["query_id"]]
        observation = {"query_id": action["query_id"], "version": action["version"], "value": truth.answers[qi]}
        remaining -= action["cost"]
        evidence.append(observation)
        trace.append({"step": step + 1, "query_id": action["query_id"], "version": action["version"],
                      "cost": action["cost"], "answer": truth.answers[qi],
                      "possible_worlds_before": action["possible_worlds"]})
    raise ProblemError("Controller exceeded the finite query bound")
