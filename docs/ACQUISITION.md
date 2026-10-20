# Finite adaptive inspection — October 12, 2026

The acquisition library chooses which fictional specification to investigate next, stops when every remaining hypothesis agrees on the cheapest complete basket and exact total (or infeasibility), and reuses observations only while their source version remains current. It is an executable CPU research component and reproducible Decision lab evidence. It does **not** replace the main Missions inspector, introduce a live model tool loop, certify real specifications, or grant purchase consent.

`intentcart/acquisition.py` uses only the Python standard library. `scripts/evaluate_acquisition.py` imports the separately implemented `scripts/missions_oracle.py` to derive hypothetical outcomes from the existing 17-component fictional Missions catalog. No app, database, credential, provider, network, GPU or training process is involved. The external-call ceiling remains zero.

## Question and scope

Can selective investigation and current-version evidence reuse reduce the cost of reaching a supported decision when workstation requirements or source facts change?

The experiment supplies an explicit finite set of possible worlds, query answers, positive integer prior weights and integer acquisition costs. Decisions are known *conditional on each hypothesis*; the controller does not know which world is real. This is a planning-under-uncertainty problem, not an experiment measuring an LLM's ability to discover or reason about these hypotheses. A finite consensus certificate is only as complete and truthful as the supplied world model and observations.

Every world changes fields, prices or availability of actual fictional catalog components. The independent basket oracle derives the exact cheapest compatible basket and its total for that world. A contradictory-source option retains the conflicting observations and excludes unsupported hardware through the oracle's normal rules. All catalog facts outside the declared uncertainty variables are explicitly known in this experiment, including the original catalog's hidden observations. These research cases therefore differ from the main UI's initial observation state.

Ten hand-authored structures cover jointly necessary dock capabilities, competing prices, irrelevant specifications, cross-component substitutions, stock, tight budgets, three-way source conflict, revised display requirements, replaced sources and charging/transport interactions. Four are development structures; six form the newly frozen structural check. The protocol and controllers were written before the first evaluation, and no policy was tuned after viewing its results. Authors have now inspected the results: this is subsequently diagnostic evidence, not a permanently untouched test set or broad generalization study.

## Exact adaptive reference

Let `S` be the worlds consistent with current observations and `w(s)` the declared positive prior weight. If every world in `S` has the same decision, `V(S) = 0`. Otherwise:

```text
V(S) = min over informative queries q:
       cost(q) + sum over answers a: P(a | S) V(S where q = a)
```

An informative query has at least two possible answers in `S`. The positive query costs make a constant-answer query unnecessary. Dynamic programming memoizes posterior subsets and uses exact rational arithmetic. Equal costs break ties by query ID. It receives the possible-world model and observations, **never the actual-world ID**. The environment uses the actual world only after an action has been chosen, to return the query answer.

This minimizes unrestricted **expected** cost under the declared prior. It is neither clairvoyant nor optimal for every individual world, worst-case cost, or completion probability at every finite budget. For the budget curves, each policy follows its unrestricted policy and stops before its next selected query would exceed the remaining budget. It does not switch to another affordable query merely to improve that plotted cutoff.

Worst-case search remains exponential. Validation limits a problem to 12 queries and 128 worlds, each with a positive cost/weight at most 1,000,000. An exact reference has a hard limit of 20,000 visited posterior states. It raises `StateLimit` on exhaustion rather than returning a heuristic result labelled optimal. A separate brute-force tiny-tree implementation in the tests checks exact costs; exhaustive realized costs also match the reference expectation across the frozen cases.

## Comparisons

| Controller | Behavior |
|---|---|
| `exact` | Minimum expected adaptive cost under the supplied prior, with matching-version observation reuse. |
| `decision_split` | Greedily maximizes the reduction in decision-label Gini impurity per cost; breaks ties by hypothesis-answer entropy per cost, then query ID. This fallback handles jointly necessary facts with zero immediate decision gain. Reuses current observations. |
| `information` | Competent uncertainty baseline: maximizes conditional query-answer entropy per cost, then decision gain, then query ID. Reuses the same observations and stops on the same decision consensus. |
| `restart_decision_split` | Evidence-reuse ablation: the same decision splitter intentionally discards all prior observations after the declared revision. |
| `full_census` | Secondary census baseline: inspects every unobserved current query in query-ID order, including irrelevant facts. |

All controllers use the same declared prior, queries, costs, source versions, outcomes and terminal consensus gate. The comparison is among deterministic inspection policies, not different models. The full-census result is secondary; the primary comparison is against the conditional information controller with evidence reuse.

## Frozen result

The dataset contains **10 scenario structures and 122 hypothetical worlds**. Five controllers at five budget cutoffs produce **3,050 paired records**, not 3,050 independent tasks. The six structural-check scenarios contribute **76 worlds: 50 solvable and 26 infeasible**. The 46 development worlds remain separate. All worlds are exhaustively enumerated; no population significance, confidence interval, human benefit or public-benchmark superiority is claimed.

At unrestricted budget, all five policies reach the correct supported outcome on all 76 structural-check worlds. The cost below first averages within each scenario using its declared prior, then averages the six scenario structures equally. Units are fictional inspection-work units, not latency, tokens, dollars, provider requests or human effort.

| Policy | Expected new inspection cost | Completion at budget 2 | Completion at budget 4 | Completion at budget 8 |
|---|---:|---:|---:|---:|
| Exact adaptive reference | 3.851852 | 24/76 | 48/76 | 76/76 |
| Decision splitter with reuse | 4.138889 | 16/76 | 36/76 | 76/76 |
| Information baseline with reuse | 5.055556 | 0/76 | 36/76 | 76/76 |
| Decision splitter restarting | 4.972222 | 0/76 | 12/76 | 76/76 |
| Full census with reuse | 5.333333 | 0/76 | 24/76 | 76/76 |

Completion counts combine valid baskets and proven infeasibility. At budget 4, the exact policy returns 24/50 solvable baskets and establishes 24/26 infeasible outcomes; both decision splitting and information return 24/50 baskets and establish 12/26 infeasible outcomes. The restart ablation establishes 12 infeasible outcomes and returns zero baskets at that cutoff. The census returns 24 baskets and establishes no infeasible outcomes. A policy stopping on budget is explicitly `BUDGET_EXHAUSTED`, not a correct infeasibility decision.

All policies have zero unsupported terminal decisions and zero false-infeasibility decisions in this model because they share the consensus gate. That is not comparative evidence of model reliability. The practical decision splitter has greater expected cost than the exact reference on three of six structures. There is no claim that the heuristic always wins or that these cases estimate real-world costs.

Prior observations in the two revision scenarios have a common separately reported acquisition cost. The main table compares **new work after revision**; every raw row also records `prior_observation_cost` and `total_cost_including_prior`. Goal changes retain matching-version observations while recomputing all decisions. A source change increments only that query's version; the previous contradictory value is discarded and the source can be inspected again. These are evidence semantics, not approval reuse: the separate Missions/PayPal consent rules remain authoritative.

## Reproduction and review

```sh
.venv/bin/python scripts/evaluate_acquisition.py --check
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_acquisition.py
```

The evaluator regenerates every world through the independent catalog oracle and compares the frozen case file before running policies. `--check` verifies all raw rows, summaries and source hashes, excluding only `generated_at`. A normal run writes the report; it cannot silently replace frozen cases. `--freeze` creates a missing case file once. When changing a protocol, preserve the old cases/report and explicitly version the experiment instead of silently redefining its test set.

- `intentcart/data/acquisition-protocol.json`: predeclared structures, budgets, comparisons and limitations.
- `intentcart/data/acquisition-cases.json`: complete hypotheses, oracle decisions, explicit priors and per-world prior observations.
- `intentcart/data/acquisition-evaluation.json`: source hashes, aggregate curves, per-structure metrics and all paired action traces.
- `tests/test_acquisition.py`: independent brute-force reference, non-clairvoyance, conjunctions, evidence revision, empty/contradictory posterior, deterministic ties, input permutation, strict schemas, bounds and frozen-case cost identity.

Initial evaluation reached the aggregation stage but failed because an aggregate helper passed a floating expected-cost value into the two-argument `Fraction` constructor. The helper was corrected without changing any controller or cases. A subsequent review corrected hypothetical source values/excerpts to match their modified observations while preserving intentional conflicting sources; the independent oracle does not consume that provenance, so all frozen cases, paired rows and aggregate outcomes remain unchanged. The earlier evaluator/report are preserved privately in `output/acquisition-before-provenance-fix/`; the comparison is recorded there. The subsequent run and exact reproduction pass; 16 focused tests pass, including a provenance-consistency regression over all 122 hypothetical worlds. These development failures and corrections are retained rather than described as a clean first run.

## Library contract

`load_problem(payload) -> Problem` validates an exact `intentcart-acquisition/1` schema:

```json
{
  "schema": "intentcart-acquisition/1",
  "id": "charging",
  "revision": "1",
  "queries": [{"id": "dock.pd_watts", "cost": 2, "version": "1"}],
  "worlds": [
    {"id": "low", "weight": 1, "answers": {"dock.pd_watts": "45"}, "decision": null},
    {"id": "high", "weight": 2, "answers": {"dock.pd_watts": "65"}, "decision": "basket-A"}
  ],
  "initial_evidence": []
}
```

Answers and non-null decisions are bounded strings; the fixture evaluator canonically JSON-encodes richer values. Null is a supported infeasible outcome **only after consensus**. Unknown state is expressed by action/status, never encoded as an outcome label.

`decide(problem, observations=(), policy="exact", remaining_budget=None, reference=None)` returns `QUERY`, `DECIDED`, `INFEASIBLE`, `BUDGET_EXHAUSTED` or `CONFLICT`. It has no actual-world argument. For repeated calls, reuse `ExactReference(problem)` to retain its memoized states. A reference from a different problem is rejected.

Each observation is `{query_id, version, value}`. `carry_evidence(observations, new_problem)` returns retained and discarded lists. Current-version contradictory observations produce an empty posterior and `CONFLICT`; no value silently wins. An unknown answer also produces `CONFLICT`. Identical duplicates are idempotent. Unsupported schemas, missing answers, booleans used as numeric costs, duplicate IDs, indistinguishable worlds with contradictory decisions and bound violations raise `ProblemError`.

`run_episode(problem, truth_world_id, policy, budget, observations=(), reference=None)` is the offline environment and returns a versioned trace. Its truth identifier never enters the policy. The source-version mechanism requires an honest version authority: failing to change a version after a source changes cannot be detected from an unchanged identifier alone. Evidence identifiers and hashes identify data; they do not establish its truth.

No research novelty, trained policy, live inference, future hiring guarantee, personal unaided authorship or general hardware compatibility is established. A useful independent ownership exercise is to derive the two-query expected-cost tree, implement it separately, and explain why greedy information gathering can investigate an irrelevant fact before a consequential one.
