# Ask, recommend or defer — October 10, 2026

IntentCart 3.0 adds an opt-in experimental controller, a two-stage synthetic stress evaluation and a local consented pilot instrument. The original shopping path remains default. **The primary result is negative/inconclusive; this is not a demonstrated quality improvement.**

## Controller

`decision.py` replays likelihoods with exponential forgetting: an observation of age k contributes `decay**k * log(likelihood)`. The intake prior remains unchanged. Skips neither update nor age evidence. Decay 1 reproduces the original posterior, including heuristic ties. Development chose **0.5** from **1, 0.8, 0.5**. This standard heuristic is not change-point detection or a novel algorithm.

Ask if binary one-step expected gain exceeds **0.002 normalized utility**, subject to four non-skip answers and eight attempts. Otherwise recommend if expected posterior regret is at most **0.025**, and defer if larger. Expected regret integrates each hypothesis's best feasible utility minus the candidate utility. Model probability of regret above 0.05 is not calibrated. Acquisition still assumes binary answers; tie handling remains a mismatch. This is not optimal stopping.

Thresholds are illustrative utility, never dollars. Deferral pauses the agent recommendation; a human may manually choose a feasible pack. Exact quote approval/payment checks remain mandatory. No model quantity grants spending authority. Read-only rehearsal omits acquisition and is not a stopping decision.

## Protocol and split

`robustness-protocol.json` was written before development: seeds, counts, three decay candidates, selection criterion, primary comparison, thresholds and sensitivity points. This is local pre-specification, not independent/public preregistration. Source hashes identify what ran, not an external trust root.

Development: **20 × seven families = 140 personas**, three decays, **420 sessions**. Lowest pooled fixed-four-answer candidate regret wins, declaration-order ties favoring decay 1. Held-out: **40 × seven = 280 independent personas**, nine policies (**2,520 sessions**), plus nine predeclared operating points (**2,520 sensitivity sessions**). These share 280 personas; they are not 5,040 independent people. Held-out did not select/revise decay. Its negative result led to opt-in release, not another tuning search.

Each case uses `SeedSequence([split_seed, family_index, persona_index])`. Hidden weights are Dirichlet(1.4); binary response beta is 12. Shared draws by step pair policies, not identical questions/answers. Budgets $80/$90/$115; laptop 14/16 inches; no capacity minimum. Up to six unique pairs are withheld from acquisition, leaving at least four learning pairs. Final model sign agreement uses hidden final utilities on those pairs, not human responses. Intake exposes hidden top two attributes, except misleading intake exposes bottom two; this favorable synthetic elicitation limits realism.

| Known family | Intervention |
|---|---|
| Linear | Original utility family, independent profiles |
| Nonlinear | 0.55 linear utility + 0.45 minimum of rain protection and comfort |
| Noisy | 10% skip; otherwise 35% fair-random response mixture |
| Ties | Tie if hidden utility difference < 0.03; otherwise logistic choice |
| Misleading intake | Hidden bottom two attributes become intake |
| Drift | Independently drawn weights replace initial weights after two non-skip answers; final evaluation uses changed weights even if a policy stopped earlier |
| Corrupted features | Learner features receive normal SD-0.18 noise clipped to [0,1]; hidden utility, authoritative prices, shipping and fit stay original |

These are known families with independent held-out personas, not unseen-domain or human generalization. A controller cannot detect unobserved future drift. Feature corruption is not a malicious-pricing/tool-attack study.

## Held-out results

| Policy | All-persona candidate regret ↓ | Mean asked comparisons | Recommended / 280 |
|---|---:|---:|---:|
| Intake only | 0.037126 | 0.000 | 280 |
| Random | 0.031975 | 4.032 | 280 |
| Uncertainty | 0.029543 | 4.032 | 280 |
| Original decision-aware | 0.024277 | 4.032 | 280 |
| Recency, fixed-four-answer | 0.026430 | 4.032 | 280 |
| Adaptive | 0.032133 | 1.186 | 219 |
| Adaptive, no deferral | 0.032133 | 1.186 | 280 |
| Adaptive, no stopping | 0.026430 | 4.032 | 183 |
| Adaptive, no forgetting | 0.031305 | 1.061 | 227 |

“Fixed-four” means four non-skip answers, at most eight attempts. Skips explain the mean above four. Candidate regret includes every persona before deferral, so conditional selection cannot hide errors.

Primary reduction, original minus fixed-four recency: **−0.002153**, 95% stratified persona-bootstrap CI **[−0.005630, 0.001035]**. Point estimate worsens; interval includes zero. **No pooled improvement established.** Development regret decreased 0.024516 → 0.022644; that did not generalize to this held-out sample.

Adaptive asks **70.6% fewer comparisons** (4.032 → 1.186) at worse candidate regret (0.024277 → 0.032133), **78.2% coverage**, and conditional recommended regret **0.032517**. Of 72 adaptive candidates with hidden regret >0.05, deferral catches only **15/72 (20.8%)**, unnecessarily defers **46** others, and still recommends **57/219** candidates above that threshold. It is not a reliable general safety guarantee.

Illustrative loss uses candidate regret when recommended, **0.03** when deferred, plus **0.002 per question**. Deferral cost is chosen, not learned from humans or money. Original minus adaptive loss: **−0.001999**, 95% CI **[−0.005272, 0.000878]**. Nine predeclared cost/risk sensitivity summaries expose dependence on thresholds; none selected a new test-tuned setting.

Bootstrap: 2,000 persona resamples within families, equal family weights. Questions are not independent samples. Subgroup means are descriptive, with no multiplicity-corrected superiority claims. Raw traces, family results, ablations, sensitivity and model-risk Brier scores remain in `robustness-heldout.json`.

Timing is descriptive one-thread CPU session work, excluding case/utility-matrix construction, with rotated policy order. No speedup or throughput inference. One clean-family adaptive simulation's traced peak is **3,198,744 bytes**, not RSS or comparative memory efficiency. The separate 2.2 performance study remains historical, source-bound evidence.

## Reproduce and validate

```sh
python scripts/evaluate_robustness.py --stage development --output /tmp/intentcart-development.json
python scripts/evaluate_robustness.py --stage heldout --development /tmp/intentcart-development.json --output /tmp/intentcart-heldout.json
python scripts/verify.py
```

No storage/payment provider is imported by the stress runner; zero external requests. Held-out rejects changed development source. Compare case identities/traces/outcomes/intervals, not timestamps/timings. `/api/robustness` rejects source/config mismatches and omits large raw traces. `decision-config.json` binds deployed opt-in decay to development evidence.

`/study` implements consent, five random arms, blinded pre/post reserved pairs, learning-only updates, survey, owned private export and withdrawal. See `HUMAN_STUDY.md`. No recruitment or human outcome. Automated browser/API records use disposable storage and are not people.

Initial regressions caught a local variable shadowing the new posterior function: **88 passed / one failed** (`UnboundLocalError`). Renaming it fixed the issue; added revision/aggregation checks yield **91 Python + six JS tests**, three JS syntax checks. Failure retained in ignored `output/verify-3.0-initial-failed.txt`. The first restricted localhost bind failed; authorized restart succeeded.
