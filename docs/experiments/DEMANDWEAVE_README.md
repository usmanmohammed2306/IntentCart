# DemandWeave

DemandWeave is a proposed AI commerce agent for independent makers. It turns buyers' budgets, deadlines, and flexible product preferences into viable production batches, then uses PayPal to authorize and settle the accepted orders. The aim is to make a batch possible when individually reasonable orders would otherwise remain fragmented.

**Current release:** A runnable, dependency-free optimization experiment. It has no live model, browser application, or PayPal integration yet. It is not a complete hackathon submission. This earlier experiment is separate from the implemented [IntentCart project](../../PROJECT_BRIEF.md).

## Run the first experiment

Run from the repository root with Python 3.9 or later. No installation or credentials are required.

```bash
python3 -m demandweave.demo
python3 -m unittest discover -s tests -v
mkdir -p artifacts
python3 -m demandweave.evaluate --markets 200 > artifacts/synthetic_matching.json
```

The demo is a deliberately constructed assignment trap. Two buyers accept either material; two accept only birch. Each production line needs two orders and has capacity for two. The fixed greedy policy uses birch capacity for flexible buyers and leaves the constrained buyers unserved. The exact solver reserves birch for the constrained buyers and puts flexible buyers in the recycled-material batch. It serves four buyers instead of two, with $60 aggregate savings against the fixture's catalog prices. These are synthetic amounts, not customer savings or evidence of AI performance.

The second part marks one substitution as unanswered. A clarification could unlock two additional buyers if the answer is yes. The question ranker evaluates that conditional gain while preserving the current confirmed preferences. It does not predict acceptance or treat an unanswered question as permission.

The seeded benchmark reports raw results for 200 synthetic eight-buyer markets, comparing exact matching with fixed-order greedy and greedy given its best catalog order. It records buyers served, catalog savings, and local solver latency. It does not test language understanding, preference recovery, calibration, payment reliability, or market demand.

## Optimization contract

Each buyer requests one unit and supplies confirmed acceptable offer IDs, an all-in USD budget, and a delivery deadline. Each offer supplies merchant-declared volume tiers, capacity, delivery time, reference retail price, costs, and a minimum contribution. There is one merchant, independent production lines, and one aggregate capacity limit. Shared inventory and scheduling across lines are not modeled.

The exact solver first maximizes the number of buyers served, then their aggregate savings against the declared retail prices. A buyer appears in at most one batch. Each offer appears at most once. All budgets, deadlines, thresholds, and contribution floors are hard constraints. No valid batch produces an empty plan rather than invented economics. Money uses integer cents; delivery uses relative day numbers in this experiment.

The solver enumerates feasible subsets and uses dynamic programming for disjoint batch selection. It is bounded to **12 buyers and six offers**, with worst-case work proportional to offers × 3^buyers. It is a small-instance reference algorithm for evaluating future scalable policies, not a production optimizer. A solver time limit and larger mixed-integer formulation belong in the next implementation.

## Verification

Nine test groups cover matching, clarification, constraints, and equality with a separately implemented assignment oracle over 60 seeded five-buyer markets. The oracle enumerates buyer assignments independently rather than calling the solver's feasibility helper. Clarification checks prove that hypothetical answers leave the current plan and confirmed preferences unchanged.

Source layout:

- `demandweave/core.py`: typed inputs, feasibility checks, exact solver, and greedy baseline.
- `demandweave/clarify.py`: conditional gains from explicitly unresolved substitutions.
- `demandweave/demo.py`: a transparent example with synthetic buyers and offers.
- `demandweave/evaluate.py`: seeded synthetic comparison with raw per-market output.
- `tests/test_core.py`: independent reference checks and constraints.

## Hackathon requirements

The [PayPal AI Hackathon rules](https://paypalaihackathon.devpost.com/rules) require meaningful PayPal and AI functionality, a working build, a public repository with an open-source license, and a public YouTube demo shorter than three minutes. The submission deadline is **November 12, 2026 at 1:00 p.m. in Phoenix** (12:00 p.m. PST). The finished project must demonstrate the complete user journey, including actual PayPal sandbox receipts and model outputs.

MIT licensed. No private profile files, credentials, or research-lab data are included in this project.
