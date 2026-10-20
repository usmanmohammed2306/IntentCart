# Local human pilot instrument — implemented, not conducted

October 10, 2026. `/study` and `intentcart/study.py` implement a usability pilot. No recruitment or human results. Automated records use disposable storage and must never count as people. Operator review and actual consenting adults are required before a human report.

This supersedes the previous proposed four-arm protocol with five arms: intake-only, random, uncertainty, original decision-aware, experimental adaptive. Assignment is independently uniform using secure randomness; small counts may be unequal. One owned record per browser session does not verify unique humans across browsers.

## Procedure

1. Explain fictional products, no payments, voluntary adult participation, private local storage, withdrawal and expected 5–10 minutes. Obtain explicit consent/adult self-attestation, not verified age. No names, credentials or sensitive personal information.
2. Freeze source before recruitment. Records bind controller configuration and hashes for app, learner, pilot engine, HTML/JS and catalog. Changed source refuses continuation; export/withdraw remain available. Do not mix revisions.
3. All arms use $90 all-in, a 14-inch laptop, no capacity minimum. Randomly reserve four feasible comparison pairs. Randomize A/B orientation once, then shuffle pair order for the later phase. Orientation stays the same across phases; position/recall effects remain limitations.
4. Collect four initial comparisons without recommendations. These answers never update the learner. Initial prior is uniform, unlike the synthetic study's hidden-derived intake.
5. Present learning comparisons from the assigned arm: none for static; four non-skip answers / eight attempts for fixed policies; adaptive may stop earlier. Reserved pairs cannot be acquired. Assignment and recommendations stay hidden during comparisons. Visible progress makes blinding incomplete: static participants can notice no learning phase.
6. Collect the same four independent pairs again, shuffled, without recommendations or posterior updates. Events record phase/elapsed time. No human utility regret is inferred.
7. Show the estimated front-runner, total and feasible manual alternatives. Collect chosen product or none, burden 1–5, entered total and approval-understanding response. Wrong answers remain outcomes. No quote, order or payment is created.
8. Offer owned JSON download and withdrawal deletion. Withdrawal removes the pilot row; downloaded copies require separate deletion. Session expiry does not delete records. Operator deletes raw data within 30 days; no automatic purge is claimed.

## Reporting

An initial 12–20 consenting-adult pilot can identify usability/feasibility issues. Five arms at that size are not powered for efficacy comparison. Report recruitment, assigned/completed/incomplete, source revision, failures and exclusions by arm. Separate declared duplicates and automated tests before human counts. Retain skips, ties, poor ratings and wrong-understanding answers. Deleted withdrawals may be unavailable for aggregate counting; maintain any recruitment/withdrawal tally separately with consent and no identity.

Run `python scripts/analyze_pilot.py --database PRIVATE_PATH --output output/pilot-aggregate.json`. It reads SQLite read-only and exports aggregate counts without IDs/free text. Rows are records, not verified humans. It reports record-level questions, burden, time, total understanding, and final-model agreement on binary post-phase reserved comparisons. Ties/skips are excluded only from that binary denominator, reported explicitly. Correlated pairs aggregate within records first. No significance or causal improvement claim is produced. Raw pre/post stability is available for separately reviewed analysis.

Raw data stays private; no public upload, recruitment or automatic launch follows from readiness. Optional feedback is not randomized participation. Synthetic hidden-utility regret is not a human metric.
