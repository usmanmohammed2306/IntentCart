# Decision validity and selective revalidation

Implemented October 12, 2026. IntentCart now maintains four separate claims about a workstation decision: fixture feasibility, bounded optimality, an advisory approval binding, and execution knowledge. This is a local deterministic implementation; no model, GPU, sponsor call or payment is involved.

## What changes mean

| Change | Computation | Approval and execution |
|---|---|---|
| Display text only | Existing candidate checks can be reused. | Catalog identity changes the advisory binding. |
| A competitor becomes cheaper | Recheck that product's candidate baskets and rerank. The old basket can remain feasible but become suboptimal. | No automatic approval. |
| A selected specification changes or conflicts | Recheck dependent baskets. Unknown/conflicting evidence cannot establish compatibility. | No automatic approval. |
| A selected component becomes unavailable | Remove baskets containing it. Retained baskets can reuse checks. | Previous selected basket is invalid; no automatic substitution approval. |
| Reviewed budget or requirements change | Recheck affected dependencies; all budget checks change after a budget edit. | Goal/revision changes always require a new binding. |
| Source identity or revision changes | Unchanged mathematical checks may be reused. | The advisory binding changes regardless of reused work. |
| A provider response is missing | The planner makes no payment assertion. | The owned receipt and provider reconciliation remain authoritative. |

`intentcart/validity.py` is a bounded snapshot analyzer. `missions.fact`, `candidates`, `evaluate` and `solve` accept an optional catalog argument, so evaluation can change copied snapshots without global mutation. The default catalog and solver objective are unchanged.

## Claims and dependencies

**Feasibility** checks complete canonical structure and eight existing constraints. It reports `verified`, `unresolved`, `invalid` or `no_plan`. Verified means the declared fictional observations support the modeled constraints. It does not certify real specifications or physical compatibility. Source product/variant, field, value and declared units must agree with an observation; mismatches, multiple conflicting values and missing observations fail closed.

**Optimality** reranks the current finite universe by the existing cost objective, or by changed component slots then cents then stable basket ID for repair. A valid old basket can be `superseded` by a better verified basket. A current leader remains `unresolved` when an otherwise admissible basket with missing/conflicting facts could outrank it. `verified` therefore excludes these unresolved better candidates; it applies only to this bounded candidate universe and objective. The analyzer makes no probabilistic claim about how a conflict will resolve.

**Authorization** is `review_required` or `binding_unchanged`. Its content digest covers exact basket, total, currency, goal, catalog, algorithm/source identity, observed evidence and revision. `consent_granted` is always false. Even an unchanged binding cannot bypass quote ownership, expiry, current version, price, explicit approval or the sandbox buyer flow. The existing dispatch gate still independently recomputes eligibility; it does not consume these certificates as authority.

**Execution** is always `unknown`, displayed as **See receipt**. The planner cannot determine whether an existing capture or refund happened. A plan revision must not hide an actual payment; receipt reconciliation remains separate.

Dependencies are recorded per selected constraint, including relevant goal fields, laptop capabilities, product prices/availability, quantities and observed source facts. The analyzer hashes dependencies for every candidate. It reuses a previous candidate's evaluated row only when those dependencies and the algorithm identity agree and the server cache's content fingerprint is intact. Changed objective rankings are recalculated even when compatibility rows are reused. New candidate structures require new evaluations.

This implementation reuses complete candidate rows. It does not selectively execute individual predicates within a changed row or implement a learned acquisition policy. Every snapshot still enumerates candidates, constructs dependency fingerprints, and reranks them. Fewer predicate evaluations do not establish lower latency; hashing, serialization and the cache have costs. No performance superiority claim is made.

The ordinary mission planner still independently recomputes its result during creation/revision before adding this certificate. Existing diagnostics and checkout recomputation are preserved. The paired study counts only the certificate analyzer's work; it does not measure or claim that all application planning work was avoided.

## API and storage

```python
from intentcart import missions, validity

goal = missions.Goal()
before = validity.analyze(goal)
after = validity.analyze(goal, revision=2, previous=before)
reference = validity.analyze(goal, revision=2, previous=before, mode="full")
assert validity.semantic_claims(after) == validity.semantic_claims(reference)
public = validity.public_certificate(after)
```

`items=None` chooses the current best verified basket. Passing an explicit basket audits that exact choice after a change. Passing `[]` means no selected plan. `previous_items` specifies the repair reference. `catalog`, `inspected`, `excluded`, `revision` and `source_sha256` fully describe the analyzed fixture context. `changes` contains typed paths and before/after digests, not raw fact values.

Mission creation/revision stores the reusable certificate under `record['validity']` and a public summary under `record['result']['validity']`. `missions.public_record` returns a copied record stripped of caches and full dependency maps for responses, exports and quote snapshots. The retained bounded cache contains only observed outcomes/IDs/prices and hashes, never hidden observation values. Public `selected_evidence` gives observed source IDs, statuses and digests; source excerpts remain subject to the existing inspection route.

Algorithm, catalog, goal, observations and snapshot identities are reproducible SHA-256 content digests. They are not signatures, proofs of source truth or protection against a malicious person who controls stored state. A previous cache is trusted server state; it must never be accepted as a client-provided authority. Accidental cache corruption or an old algorithm forces full recomputation. Malformed catalogs, unknown source/product references and excessive candidate universes are rejected. The analyzer accepts at most 64 products, 16 laptops, 1,024 sources and 4,096 candidate baskets; the shipping catalog is much smaller.

## Reproduction and evidence

```sh
.venv/bin/python -m pytest tests/test_validity.py tests/test_missions.py -q
.venv/bin/python scripts/evaluate_validity.py --output /tmp/validity-evaluation.json
```

The source-bound report `intentcart/data/validity-evaluation.json` retains every attempt across **16 declared snapshot-change cases / 32 paired mode runs**. It reports **16/16 semantic matches and 94/94 explicit checks**. Selective mode performed **768 candidate evaluations**, while full recomputation performed **2,880**, with **2,112 cached candidate results reused**. Initial, goal-changing and corrupted-cache cases deliberately require full work. Zero external calls and zero human participants.

These cases are a public development/regression set, not held-out tasks or independent trials. Both modes use the same production evaluator. Their agreement checks cache invalidation and semantic preservation; it is not an independent mathematical oracle, a model comparison, measured speedup, web-call saving, cash saving or evidence of generalization. The existing separate Missions oracle still evaluates the original fixture planning task. Raw case records include checks, public certificates, source identities, selected baskets and changed goals; failures are retained and give the runner a nonzero exit status.

Focused tests also cover randomized deterministic sequences of copied-catalog price, inspection, goal, availability and presentation changes; source-provenance conflicts; hidden-value non-disclosure; no mutation of catalog/previous records; repair ranking; and approval/execution separation. They are engineering regressions, not a statistical reliability study.

## Remaining research scope

No optimal adaptive information-acquisition policy, learned controller, generalized real-product import, live-model comparison, formal verification, human study or distributed execution system is claimed here. A future research comparison must freeze its hypothesis, uncertainty assumptions, stronger baselines, task splits and budget separately. The current contribution is an inspectable implementation of scoped claims, dependency reuse and reproducible declared change cases.
