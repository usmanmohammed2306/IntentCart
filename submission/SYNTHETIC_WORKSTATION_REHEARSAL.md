# Synthetic workstation rehearsal

**Fictional personas — zero human participants.**

Snapshot: 2026-10-19; local deterministic policy, no model or payment calls.

| Fictional persona | Scripted scenario | Software checks |
|---|---|---|
| Mira — budget keeper | Two Full HD displays, one retained, USD 350 cap; scripted driver permission. | 3/3 |
| Noah — driver cautious | Decline the driver request. | 3/3 |
| Leena — price skeptic | Replace declared zero tax/shipping allowances with unknown values. | 2/2 |
| Jules — gamer | Require gaming capability without supporting reviewed evidence. | 2/2 |
| Sam — repair planner | Remove the only supporting dock; restore its availability in the scenario. | 3/3 |
| Ari — source reviewer | Propose then script acceptance of a hypothetical two-to-one-display source correction. | 5/5 |
| Tess — permission revoker | Withdraw previously scripted driver permission. | 3/3 |
| Dev — strict budget | Request the same setup under a USD 100 cap. | 2/2 |

Observed software checks: **23/23** across 8 authored scenarios. This is not a participant success rate.

Reproduce:

```sh
.venv/bin/python scripts/rehearse_workstation.py --as-of 2026-10-19 --output output/synthetic-workstation-rehearsal.json --markdown output/synthetic-workstation-rehearsal.md
```

The companion JSON retains each stage, expected check and source hash. A blocked basket is an intended result where support is missing. No usability observation or user feedback is inferred.

- Authored correlated cases share one curated catalog and the same final validator.
- Scripted permissions and source acceptance are simulated inputs, never actual user consent.
- Passing checks establish these specified software behaviors only; usability and human benefit remain unmeasured.
- No fabricated quotes, completion times, satisfaction scores or recruitment records.
- Roadmap 88 remains pending: a consented participant study was not conducted.
