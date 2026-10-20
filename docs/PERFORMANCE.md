# CPU performance — IntentCart 2.2.0

Measured October 10, 2026, on local Darwin arm64, Python 3.12.14, NumPy 2.5.3. BLAS/OpenMP/Accelerate thread ceilings were one. No provider keys, sponsor calls, paid services or user database were used. The original 2.1 source/kit/video remains privately archived; `scripts/benchmarks/learning_v2_1.py` is a byte-identical snapshot of its learning implementation, identified in `PROVENANCE.json`.

## Measured results

| Workload | Previous median | Optimized median | Median reduction | Speedup | Paired measurements |
|---|---:|---:|---:|---:|---:|
| Decision-aware comparison acquisition | 4.755 ms | 1.285 ms | 72.98% | 3.701× | 96 workloads × 7 = 672 pairs |
| Four-world rehearsal, in-process API | 7.456 ms | 2.197 ms | 70.53% | 3.394× | 16 fixtures × 7 = 112 pairs |

Median means the median across per-workload medians, not the minimum observed time. P95 across timed calls was 23.648 → 4.801 ms for acquisition and 29.955 → 3.098 ms for rehearsal. Workload-bootstrap 95% intervals for the median speedup were [2.819, 4.063]× and [1.111, 11.767]× respectively. The broad rehearsal interval reflects heterogeneous fixtures: after four answers, the old path already skips questions and benefits little.

## What changed

The old acquisition loop copied the feasible utility matrix twice per candidate pair and performed a separate matrix-vector product for each binary outcome. The new path materializes the feasible matrix once, processes at most 64 pairs together, and uses `right = expected − left` because the two binary likelihoods partition expected utility. It preserves candidate traversal and the existing 1e-12 tie tolerance; no new recommendation policy, model or approximation is introduced.

Rehearsal previews return rankings and scenario outcomes, not follow-up questions. They now request ranking-only computation instead of running unused acquisition for the baseline and each projected world. Normal mission/session/answer flows still select questions. Server constraints, pricing, quote versions, approval and payment operations are unchanged.

## Method and parity

`python scripts/benchmark_learning.py --workloads 96 --repeats 7 --seed 20261010 --output /tmp/performance.json` reproduces timing. It uses the actual 24-product catalog and 2,048 hypotheses, 4/8/16/24-product subsets crossed with 0/1/2/3-observation histories, and six states per combination. Kernel setup/posterior computation is excluded from the query timer. Two warmups precede seven paired repetitions in randomized order. Bootstrap units are workloads, not correlated repetitions. Raw timing records, hardware/runtime metadata and source hashes are in `intentcart/data/performance.json`. Timing-only development compared batch sizes 16/32/64/128/all before the final seed; 64 was chosen to bound temporary arrays with nearly the full-batch latency.

The API benchmark uses FastAPI TestClient, disposable SQLite, four budgets crossed with 0/1/3/4 answers, routing and JSON serialization. Its baseline restores the previous unused-question computation and original kernel within the same route. All measured response JSON is identical. Harness rate-limit counters are cleared outside timers; the application's production limiter is unchanged. This measures **in-process requests**, not TCP/network latency, production throughput or concurrent user load. The provider stub fails on any access; measured calls and created orders are zero.

`python scripts/verify_learning_parity.py --output /tmp/performance-parity.json` compares all **1,440 question selections** across the original **120-persona × 4-policy = 480-session** synthetic study. Every selected pair matches; maximum gain error is below 3e-15. Policy outcomes and paired intervals match the original artifact exactly. That original study still does not establish decision-policy superiority. The timing benchmark separately preserves all 672 timed query results and 96 untimed uncertainty-policy selections.

Twelve new regressions bring the suite to **75 Python tests (66 IntentCart + 9 legacy)**, plus **6 JavaScript tests**. They cover diffuse/concentrated/equal utilities, feasible subsets, used pairs, seeded random choice, exhaustion, full-vs-ranking-only rehearsal parity across answer histories, and the absence of unused query selection. The saved fake recovery run was regenerated after source changes: **8/8 scripted assertions**, one fake capture, zero live calls.

## Trade-offs and limits

Batching spends temporary memory to save CPU work: a separate 24-product allocation probe measured **433,752 → 4,618,328 traced bytes** (about 0.43 → 4.62 MB). This is Python/NumPy traced peak allocation for one call, not process RSS, and it is excluded from latency timing. The 64-pair batch bounds these intermediates independently of the number of candidate pairs; the candidate list itself is still quadratic. Faster queries do not establish better preference fidelity, user outcomes, scalability, or a service SLA. No new human study, provider transaction, public deployment or independently observed personal mastery is claimed.

A first regression run correctly rejected stale saved recovery evidence with HTTP 409 after the source changed (74 passed, one failed); regenerating that source-bound artifact restored all 75 passes. The negative policy result and earlier release failures remain in the career handoff.
