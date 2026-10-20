# Combinatorial validation

**Local, offline validation. Fictional/synthetic scenarios; zero human participants.**

Snapshot: 2026-10-19. Saved trace integrity, source identities, case uniqueness and the declared coverage denominators were audited.

| Suite | Executed coverage | Result |
|---|---|---|
| Synthetic hardware matrix | 196,608 distinct configurations across 17 listed axes; 4,374 supported | Zero false acceptances/rejections against the separately stated finite oracle |
| Block and recovery order | 1,728 sequences: 4! blocking orders × 4! recovery orders × three seeds | Input immutability, revision, acceptance invalidation and restored semantics pass |
| Source review order | 240 sequences: 5! events × two display requests | Obsolete/missing acceptance and repeated inspection handled as declared |
| Freshness, OS and cost boundaries | 576 configurations | Exact-boundary, future-date and unknown-cost cases pass |
| Fictional persona chains | 960 journeys; 24 profiles × 40 ordered words | Every declared disruption chain through length three, including repetitions |
| Actual local API guards | 243 combinations + one duplicate-revision request | Expected status and durable-owner-state checks pass |
| Deliberate fault challenge | 11/11 seeded faults detected; one no-op control | Zero no-op false alarms |

These are separate denominators. Repeated per-step assertions are not additional independent configurations, users or benchmark tasks.

## What the matrix covers

Six capability-versus-requirement pairs (display count, resolution, refresh, charging, HDCP and gaming), dock protocol, driver permission, reviewed availability, known versus unknown cost, and a budget one cent below/at/above the independently calculated subtotal.

The fixtures have one synthetic product per component kind and one explicitly declared owned screen. Capabilities are fictional declarations. The reference predicate reads the declared world and request directly and never calls the planner or reuses its check results.

The full Cartesian enumeration implies all 576 declared two-axis assignments and 5,920 three-axis assignments. The audit decodes each numbered trace input and rejects missing/duplicate/reordered IDs; these are projections of the same matrix, not extra executions.

## Ordered persona disruptions

For each of the existing 24 fictional profiles, execute every word of length zero, one, two or three over: late cost ambiguity, conflicting inventory, and an expired offer after a serialized interruption. This is 1 + 3 + 9 + 27 = 40 words per profile. The primary workflow is executed afresh for each word. Repeated disturbances can accumulate unresolved constraints; a later event may reopen a previously stopped fictional scenario.

The persona chains contain 16,570 executed steps and 52,010 repeated contract checks. Those checks are not a measure of human realism or independent trial count.

## Faults challenged

Test-only patches bypass driver permission, display count, the resolution path, refresh, charging target, HDCP, gaming, offer availability and unknown all-in cost. Two further patches incorrectly reject exact-budget equality or always defer. The no-op control preserves behavior. Detecting these eleven constructed faults does not establish detection of arbitrary defects.

## Retained evidence and reproduction

Each suite saves its complete trace, including failures if any, rather than only a success count. Gzip files are streamed, CRC-checked on read and bound by SHA-256. Reports carry source manifests. Existing outputs cannot be overwritten by the runners.

```sh
.venv/bin/python scripts/validate_matrix.py --as-of 2026-10-19 --output output/recheck/combination-matrix.json --trace output/recheck/combination-matrix-cases.jsonl.gz
.venv/bin/python scripts/validate_state_sequences.py --as-of 2026-10-19 --output output/recheck/state-sequence-validation.json --trace output/recheck/state-sequence-cases.jsonl.gz
.venv/bin/python scripts/validate_persona_sequences.py --as-of 2026-10-19 --output output/recheck/persona-sequence-validation.json --trace output/recheck/persona-sequence-cases.jsonl.gz
.venv/bin/python scripts/validate_api_matrix.py --as-of 2026-10-19 --output output/recheck/api-guard-matrix.json
.venv/bin/python scripts/audit_combinations.py --directory output/recheck --output output/recheck/audit.json --markdown output/recheck/REPORT.md
```

## Limits

The finite matrix is exhaustive only for its listed values. Raw constructed states test the validator; the separate in-process API suite tests the listed guards. Neither establishes arbitrary browser flows, real concurrency, load capacity, production authentication, physical compatibility or live payment reliability. Rate buckets are cleared between API guard cases, so that suite does not measure rate limiting.

A frozen snapshot date tests declared source-age boundaries. It is not a claim that current merchant or hardware data was refreshed. JSON round trips are not actual browser restarts. The persona stories and reactions are authored hypotheses, with no measured psychological validity, task times, human satisfaction or usability benefit. Live-model and consented-participant gates remain pending.
