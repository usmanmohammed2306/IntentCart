# IntentCart Missions 4.0 — implementation and evidence

Implemented October 11–12, 2026. A bounded workstation outcome compiler runs alongside the retained preference-learning lab. It compiles explicit reviewed fields into a complete basket, identifies consequential missing specifications, diagnoses infeasibility, and repairs inventory/requirement changes. The project remains single-instance and sandbox-only.

## Run and reproduce

```sh
python -m intentcart
# Open http://127.0.0.1:4000/ (Missions), /learn (preference lab).
python scripts/verify.py
python scripts/evaluate_missions.py --output /tmp/missions-evaluation.json
```

The core requires no credentials, GPU, external model, cash payment or hosting. Keep EXTERNAL_CALL_LIMIT=0. The evaluation has no provider or storage imports; it cannot debit sponsor accounts. Node.js is required for the verification command. The non-root Docker image includes the evaluation runner and independent oracle.

## System

`intentcart/missions.py` defines the strict Goal schema and pure planning functions. `data/missions-catalog.json` supplies 17 fictional components, three fictional laptop profiles and source excerpts. The four purchasable slots are dock, monitor(s), cable pair and power supply; the reused monitor is fixed at Full HD/60 Hz/HDMI. All modeled displays and docks use HDMI. Supported resolution/refresh fields describe the declared fixture envelope; this is not electrical simulation or real hardware certification.

The local text interpreter recognizes a narrow set of budget/display/resolution/refresh expressions. It returns suggestions only. The reviewed form is the authoritative goal; unsupported prose is not silently enforced. Permission to install a driver is never inferred from text or a model proposal. Structured proposals pass the same Goal schema, reset driver permission, and require explicit review.

Each product observation binds field, value, product variant and source. Sources include observation date, units, excerpt, and deliberately invalid fixture URLs. No observed value means unknown; multiple disagreeing values mean conflict. Neither state is admitted as a verified fact. Inspecting a hidden fixture is an explicit local operation, not a web request. Contradictory variants are not merged or automatically resolved.

The solver enumerates a bounded complete-basket universe (up to 192 candidates per goal) and checks eight constraints: all-in budget, laptop transport, driver permission, independent-display count, resolution, refresh, charging and cables. Initial planning/inspection minimizes cents, then a stable basket identity. Requirement or availability repair minimizes changed component slots (product ID or quantity), then cents, then identity. Optimality applies to this finite universe and these objectives only.

Targeted investigation considers missing facts in baskets with no known contradiction, orders them by optimistic basket price and affected-candidate count, and stops when no missing fact could improve cost. Several unknowns may jointly block a basket. This is a deterministic acquisition heuristic, not a learned policy, probabilistic information-gain estimate or new statistical method. One explicit “inspect relevant fixtures” action performs at most five local inspections. The ordinary UI also exposes each inspection individually.

Infeasibility diagnosis uses deletion to return a subset-minimal conflict among the displayed constraints and current candidate universe. It is not minimum cardinality, universal impossibility, or proof about unknown real-world products. Suggested single-field relaxations are independently recomputed and require a user choice. If no single-field relaxation works, none is fabricated.

## Execution boundary

Missions are owned by the existing opaque session and use optimistic revision checks, Origin/CSRF validation, strict schemas, bounded bodies and the existing single-process SQLite lock. Changes invalidate prior quotes. Catalog/compiler identities invalidate stale saved missions and quotes; the old mission remains privately exportable. Planning is retained even when infeasible.

The bundle quote contains exact quantities, authoritative fixture prices, USD, $0 fixture shipping/tax, expiry, revision, source identity and frozen decision evidence. Creation/capture reuse the existing PayPal sandbox provider, persistent retry keys and reconciliation. A shared dispatch gate recomputes complete-basket eligibility before provider access. No client/model price, approval, missing component, stale version or unknown compatibility can authorize checkout. Completed captures remain reconcilable after later plan changes. Quote review/receipt export alone records no consent and creates no payment.

Real Channel3 discovery remains separately labelled; arbitrary retailer listings cannot enter the fictional merchant's basket. No retailer purchase, shipment, inventory reservation or delivery date is promised. Local and historical sandbox evidence remain distinct.

## Optional Astropods model adapter

`gateway.py` follows the documented HTTPS `ASTRO_GATEWAY_URL/v1/chat/completions` contract. It requests one JSON Goal with at most 512 output tokens, validates it, resets driver permission and returns a reviewable suggestion. No tool execution or product facts are accepted. Failed or malformed responses leave the mission unchanged; there is no automatic retry, redirect or model dispatch on page load.

Before dispatch the server requires credentials, positive EXTERNAL_CALL_LIMIT, a positive micro-USD budget, operator-reviewed positive input/output price ceilings, and explicit credit-only account confirmation. It reserves the conservative prompt/output allowance and call counter durably before the request. Failed/uncertain calls retain their reservations. Channel3 and Astro share a durable call ceiling. These local reservations are not a provider billing guarantee; unknown ancillary charges require staying disabled. No price assumptions are supplied. Keys and gateway host stay server-side.

The adapter is exercised with fake model output and budget/failure tests. Live gateway connectivity, current token pricing and an actual model trajectory remain unverified. Do not call the local rule compiler an LLM or describe fixture evaluation as a model comparison. Sponsor ceiling and model budget stay zero in the delivered configuration.

## Evaluation

`evaluate_missions.py` runs a fixed Cartesian grid: 3 laptop profiles × 4 budgets × 2 display counts × 2 resolutions × 2 refresh rates × 2 reuse choices × 2 driver choices = **384 synthetic cases**, with deterministic stock exclusions. Three controllers share the exact solver: known facts only, inspect every missing fixture, and constraint-guided inspection. This is a correctness/acquisition comparison; it is not a trained-agent experiment or an external benchmark.

`scripts/missions_oracle.py` separately implements structural validation, compatibility checks, basket enumeration and repair optimization. It does not import the production solver. It checks quantities, missing/duplicate slots, exclusions, conflicting/missing evidence and all eight constraints. The grader still shares the declared task definitions and catalog; agreement cannot certify real product truth. Corrupted/incomplete baskets are tested separately.

The October 12 UTC run reports:

| Controller | Valid complete plans / solvable | Minimum-cost baskets / solvable | Correct deferrals / infeasible | Fixture inspections |
|---|---:|---:|---:|---:|
| Known facts only | 65/73 | 20/73 | 311/311 | 0 |
| Inspect all | 73/73 | 73/73 | 311/311 | 1,920 |
| Constraint-guided | 73/73 | 73/73 | 311/311 | 143 |

No invalid returned basket among the 1,152 controller runs. Targeted inspection uses 92.55% fewer fixture lookups than the complete census baseline, with the same minimum-cost outcomes on this grid. The census inspects even irrelevant/unavailable facts and is not a competent LLM baseline. Do not interpret this reduction as model-token, web-latency, cash savings, human benefit or benchmark leadership. The majority of the grid is infeasible; both solvable and infeasible denominators must be shown. Local measured latency includes solver/diagnosis and is not a service SLA; targeted inspection is not uniformly faster.

Removing each selected component from the 73 solvable full-information baskets gives **272 stock-change cases**: 272/272 match the independent minimum-change/price oracle; 241 have a feasible repaired basket and 31 have none. These reuse the original fixture goals and are not independent human trials. Raw rows, attempts, source hashes and local timings are retained in `data/missions-evaluation.json`; the API rejects stale evidence.

There is no untouched public WebMall score, live-model comparison, learned acquisition policy, human study or real-commerce outcome. Older preference benchmarks retain their negative findings. Independent user implementation/explain-back remains open.

## Resource status

Actual historical use: PayPal sandbox capture/full refund and Channel3 discovery. New local engineering use: a Postman v2.1 collection executed with Newman 6.2.3; five requests/six assertions passed with no payment endpoint. Raw cookie-bearing output stays ignored; a sanitized run summary is public. Official current Postman docs mark Newman unmaintained and prefer Postman CLI; the supplied legacy collection is deliberately versioned for the executed runner.

Astropods: documented optional adapter and fake contract tests, not a live-model claim. Render/public hosting waits for the entrant's source-publication decision. Kernel, Elastic, AG Grid/Studio, Bryntum, APIMatic and Zapier remain reviewed optional resources, not implemented or used integrations. See RESOURCES.md for grants/trials and expiration caveats. Source/collection artifacts can support later contract review, but do not count as actual APIMatic use. Free native UI/core dependencies preserve the working app when trials expire.
