# Complex fictional workstation personas

**Authored simulation. Zero human participants.**

The identities and circumstances below are invented design hypotheses. The software outcomes come from executing the real local controller and workbench, with scripted decisions and a frozen scenario date.

Snapshot: 2026-10-19. 8 fictional profiles × three authored conditions = 24 correlated journeys; 223 steps; 648/648 specified checks passed. These counts are software coverage, not people or a usability success rate.

Each profile runs with a declared zero additional-cost allowance, a USD 15 cost surprise, and a USD 5 allowance plus a scripted snapshot/resume interruption. These are hypothetical planning allowances, not live tax estimates. Branching thresholds are authored, not estimated from human behavior.

## Mira — independent video editor — fictional

Her paid work and household use the same laptop. A client revision is due soon, while the second display is borrowed and must go back. She initially describes the budget as about four hundred dollars, then remembers a reimbursement ceiling of USD 350.

**Goal.** Keep the existing Full HD monitor and add a second usable screen without a surprise out-of-pocket bill.

**Competing priorities.** Avoid losing work time; Respect the reimbursement ceiling; Reuse equipment instead of replacing it; Get a reassuring answer quickly without hiding uncertainty.

**Starting mental model.** The displayed subtotal is the amount she will pay; a recommendation means the remaining details have been settled.

**Scripted decision rule.** Starts permissively, tightens the budget after a recommendation, then treats unknown tax as a blocker. She may explicitly add up to USD 5 of her own discretionary allowance after reviewing the total; a USD 15 discrepancy makes her defer.

**Correction trigger.** The all-in total exceeds the ceiling or shipping/tax becomes unknown.

**Recovery.** Separate the declared scenario allowance from a live merchant quote; revise the ceiling explicitly only within her USD 5 discretionary allowance.

**Stopping boundary.** The declared all-in total cannot fit her explicit ceiling.

**Outside this simulation.** Actual editing performance; Time pressure as an observed psychological effect; Willingness to pay in a real purchase.

| Condition | Executed steps | Passed checks | Final software state |
|---|---:|---:|---|
| baseline | 8 | 26/26 | RECOMMENDED; 1 supported baskets |
| cost-shock | 7 | 22/22 | DEFERRED; 0 supported baskets |
| interrupted | 9 | 28/28 | RECOMMENDED; 1 supported baskets |

One executed path (baseline):

1. Initial scripted planning request → RECOMMENDED, 1 supported baskets.
2. Record the scenario cost allowance → ACTIVE, 1 supported baskets.
3. Request a fresh recommendation after the allowance change → RECOMMENDED, 1 supported baskets.
4. Remember the reimbursement ceiling after seeing a plan → ACTIVE, 1 supported baskets.
5. Notice tax has not actually been settled → ACTIVE, 0 supported baskets.
6. Enter an explicitly hypothetical reviewed tax allowance → ACTIVE, 1 supported baskets.
7. Explicitly confirm the ceiling with at most USD 5 discretionary allowance → ACTIVE, 1 supported baskets.
8. Resolve the current budget without claiming a merchant quote → RECOMMENDED, 1 supported baskets.

## Noah — analyst on a managed laptop — fictional

He is comfortable with spreadsheets but cannot install system software. A colleague says all USB-C docks are interchangeable. He can request a larger hardware allowance, but he cannot approve a driver exception on behalf of IT.

**Goal.** Use two displays while staying inside the software restriction.

**Competing priorities.** Follow the installation restriction; Avoid appearing unhelpful to his manager; Reuse a monitor already at home; Avoid buying a more expensive item that has the same limitation.

**Starting mental model.** A higher-priced dock or a bigger budget will remove the need for software.

**Scripted decision rule.** Declines every driver request. Tries a larger budget after the first deferral, then retries an explicit no-driver goal. Does not interpret another request as permission.

**Correction trigger.** The represented laptop/dock combination still needs the restricted driver.

**Recovery.** Keep the unresolved constraint visible and defer instead of manufacturing a compatible alternative.

**Stopping boundary.** No driver-free represented basket supports the requested two-display setup.

**Outside this simulation.** A real employer policy; IT approval; Unrepresented products or laptop capabilities.

| Condition | Executed steps | Passed checks | Final software state |
|---|---:|---:|---|
| baseline | 6 | 15/15 | DEFERRED; 0 supported baskets |
| cost-shock | 6 | 15/15 | DEFERRED; 0 supported baskets |
| interrupted | 7 | 17/17 | DEFERRED; 0 supported baskets |

One executed path (baseline):

1. Initial scripted planning request → DEFERRED, 0 supported baskets.
2. Record the scenario cost allowance → ACTIVE, 0 supported baskets.
3. Request a fresh recommendation after the allowance change → DEFERRED, 0 supported baskets.
4. Try a larger hardware allowance without granting installation permission → ACTIVE, 0 supported baskets.
5. Decline again when the same installation issue returns → DEFERRED, 0 supported baskets.
6. Stop because a hardware allowance cannot override the restriction → DEFERRED, 0 supported baskets.

## Leena — meticulous comparison shopper — fictional

She keeps several product tabs open and copies offer details between them. She distrusts promotional language but can mistake a visually similar model suffix for the selected variant. She dislikes losing a bargain more than spending extra time checking it.

**Goal.** Use the lowest reviewed all-in allowance while preserving the exact selected product identity.

**Competing priorities.** Keep the discount; Avoid the wrong variant; Know whether a price is stale; Avoid being forced to repeat every previous inspection.

**Starting mental model.** A copied offer for a similar-looking model is close enough, and last week's price is probably still available.

**Scripted decision rule.** Attempts the mismatched variant, corrects it after rejection, declares a discounted offer, encounters its expiry, refreshes the declaration, then resolves shipping and tax separately.

**Correction trigger.** Exact-variant rejection or an expired offer removes support.

**Recovery.** Correct the identity and review date explicitly; never treat the copied declaration as an independently fetched live price.

**Stopping boundary.** An exact current declaration and known allowances cannot support the basket.

**Outside this simulation.** Real retailer availability; A fetched promotional price; Actual purchase or savings.

| Condition | Executed steps | Passed checks | Final software state |
|---|---:|---:|---|
| baseline | 9 | 28/28 | RECOMMENDED; 1 supported baskets |
| cost-shock | 9 | 28/28 | RECOMMENDED; 1 supported baskets |
| interrupted | 10 | 30/30 | RECOMMENDED; 1 supported baskets |

One executed path (baseline):

1. Initial scripted planning request → RECOMMENDED, 1 supported baskets.
2. Record the scenario cost allowance → ACTIVE, 1 supported baskets.
3. Request a fresh recommendation after the allowance change → RECOMMENDED, 1 supported baskets.
4. Copy a similar-looking but wrong variant from another tab → RECOMMENDED, 1 supported baskets.
5. Correct the identity but use an eight-day-old discount → ACTIVE, 0 supported baskets.
6. Refresh the explicit declaration, without a retailer lookup → ACTIVE, 1 supported baskets.
7. Discover shipping is still unknown → ACTIVE, 0 supported baskets.
8. Resolve shipping using a scenario allowance → ACTIVE, 1 supported baskets.
9. Request a fresh plan after identity, date and all-in cost review → RECOMMENDED, 1 supported baskets.

## Jules — developer sharing a work and gaming desk — fictional

The same desk serves work during the day and games in the evening. Jules begins with a productivity request, remembers the gaming use after seeing a plan, then asks about protected video. Accepting software for work does not mean every entertainment requirement is satisfied.

**Goal.** Understand which parts of the desired mixed-use desk are actually supported.

**Competing priorities.** Keep the work setup affordable; Avoid buying twice; Preserve gaming and video expectations; Finish a useful work-only plan if the mixed-use plan is unsupported.

**Starting mental model.** Two displays at the requested resolution imply gaming suitability and protected-video support.

**Scripted decision rule.** Adds gaming and HDCP together, removes gaming first, notices HDCP is still unresolved, then explicitly changes scope to work-only and requests a fresh recommendation.

**Correction trigger.** Removing one requirement does not resolve the other unsupported requirement.

**Recovery.** Make the scope change explicit instead of claiming the original mixed-use need was met.

**Stopping boundary.** A work-only plan may proceed; the original entertainment requirements remain unverified.

**Outside this simulation.** Game latency; Protected-media playback; Physical hardware testing.

| Condition | Executed steps | Passed checks | Final software state |
|---|---:|---:|---|
| baseline | 8 | 25/25 | RECOMMENDED; 1 supported baskets |
| cost-shock | 8 | 25/25 | RECOMMENDED; 1 supported baskets |
| interrupted | 9 | 27/27 | RECOMMENDED; 1 supported baskets |

One executed path (baseline):

1. Initial scripted planning request → RECOMMENDED, 1 supported baskets.
2. Record the scenario cost allowance → ACTIVE, 1 supported baskets.
3. Request a fresh recommendation after the allowance change → RECOMMENDED, 1 supported baskets.
4. Remember evening gaming and protected-video needs → ACTIVE, 0 supported baskets.
5. Drop gaming but keep protected-video support as a hard requirement → ACTIVE, 0 supported baskets.
6. Check that resolving one requirement does not resolve the other → DEFERRED, 0 supported baskets.
7. Explicitly narrow the scenario to productivity only → ACTIVE, 1 supported baskets.
8. Request a work-only recommendation → RECOMMENDED, 1 supported baskets.

## Sam — operations lead replacing a failed desk component — fictional

The rest of the workstation is useful, so replacing everything would be disruptive. Sam removes the chosen dock when a seller marks it unavailable. Later a product listing returns, but the particular reviewed offer is still unavailable.

**Goal.** Recover the represented workstation while preserving unaffected components and avoiding stale acceptance.

**Competing priorities.** Minimize replacement work; Recover quickly; Do not confuse a catalog listing with an available offer; Preserve useful evidence without silently approving a purchase.

**Starting mental model.** Restoring a product in the list also restores its availability and the previous recommendation.

**Scripted decision rule.** Removes the dock, declares its offer unavailable, restores the product, checks the still-blocked basket, then explicitly marks the scenario offer available before requesting a fresh recommendation.

**Correction trigger.** Restoring the product does not override the unavailable offer.

**Recovery.** Keep catalog presence, reviewed offer availability and recommendation acceptance separate.

**Stopping boundary.** The offer remains unavailable or recovery would require an unsupported substitute.

**Outside this simulation.** A real hardware failure; Live stock changes; A physical replacement or refund.

| Condition | Executed steps | Passed checks | Final software state |
|---|---:|---:|---|
| baseline | 9 | 26/26 | RECOMMENDED; 1 supported baskets |
| cost-shock | 9 | 26/26 | RECOMMENDED; 1 supported baskets |
| interrupted | 10 | 28/28 | RECOMMENDED; 1 supported baskets |

One executed path (baseline):

1. Initial scripted planning request → RECOMMENDED, 1 supported baskets.
2. Record the scenario cost allowance → ACTIVE, 1 supported baskets.
3. Request a fresh recommendation after the allowance change → RECOMMENDED, 1 supported baskets.
4. Remove the selected dock while preserving the other component plan → ACTIVE, 0 supported baskets.
5. Record the reviewed offer as unavailable → ACTIVE, 0 supported baskets.
6. Restore the catalog listing while its offer is still unavailable → ACTIVE, 0 supported baskets.
7. Explicitly revise the scenario offer availability → ACTIVE, 1 supported baskets.
8. Request a fresh supported repair plan → RECOMMENDED, 1 supported baskets.
9. Check that recovery did not replace unaffected component slots → RECOMMENDED, 1 supported baskets.

## Ari — engineer auditing a disputed specification — fictional

Ari finds conflicting display-count information while reviewing the setup. They are technically confident but have several tabs open and can return to an obsolete review identifier after an interruption. They want the evidence trail preserved even when their own proposed correction turns out to be wrong.

**Goal.** Test a disputed specification without turning a proposal into accepted evidence.

**Competing priorities.** Correct inaccurate evidence; Keep the original decision trace; Avoid accidental acceptance after an interruption; Recover after reversing a mistaken correction.

**Starting mental model.** Submitting a correction may be enough for the planner to start using it.

**Scripted decision rule.** Proposes a one-display correction, attempts an obsolete acceptance identifier, accepts the exact pending proposal, reinspects the changed field, then proposes a separate two-display reversal and reinspects again.

**Correction trigger.** The pending identifier is rejected or accepted evidence clears the old recommendation.

**Recovery.** Accept only the exact proposal; a reversal is another review operation with another inspection.

**Stopping boundary.** Conflicting or uninspected evidence cannot support the requested display count.

**Outside this simulation.** Independent manufacturer verification; A real conflicting publication; An expert interview.

| Condition | Executed steps | Passed checks | Final software state |
|---|---:|---:|---|
| baseline | 12 | 31/31 | RECOMMENDED; 1 supported baskets |
| cost-shock | 12 | 31/31 | RECOMMENDED; 1 supported baskets |
| interrupted | 13 | 33/33 | RECOMMENDED; 1 supported baskets |

One executed path (baseline):

1. Initial scripted planning request → RECOMMENDED, 1 supported baskets.
2. Record the scenario cost allowance → ACTIVE, 1 supported baskets.
3. Request a fresh recommendation after the allowance change → RECOMMENDED, 1 supported baskets.
4. Propose a hypothetical display-count correction → ACTIVE, 1 supported baskets.
5. Keep proposed evidence separate from accepted evidence → ACTIVE, 1 supported baskets.
6. Return to an obsolete review identifier after switching tabs → ACTIVE, 1 supported baskets.
7. Accept the exact pending correction → ACTIVE, 0 supported baskets.
8. Require the accepted changed field to be inspected again → ACTIVE, 0 supported baskets.
9. Inspect the reduced display count and defer → DEFERRED, 0 supported baskets.
10. Propose a hypothetical display-count correction → ACTIVE, 0 supported baskets.
11. Accept a separately proposed reversal of the mistaken correction → ACTIVE, 0 supported baskets.
12. Reinspect again before recommending the restored specification → RECOMMENDED, 1 supported baskets.

## Tess — consultant reconsidering software permission — fictional

Tess initially agrees to a driver because the setup appears useful. After checking the constraints of a shared client machine, she withdraws that permission. Her personal laptop later becomes an option, so she explores a separate permissive revision before deciding the shared-machine plan is the one she actually needs.

**Goal.** Keep permission attached to the current scenario rather than to a previous answer.

**Competing priorities.** Avoid an installation she cannot authorize; Reuse the same physical desk; Explore a personal-machine alternative; Ensure a previous yes cannot override the final no.

**Starting mental model.** Undoing permission may remove useful evidence, or the old accepted plan may survive in the background.

**Scripted decision rule.** Withdraws permission, runs a fresh refusal, temporarily revises to a driver-allowed scenario, then withdraws again. The final state must reflect the last explicit decision.

**Correction trigger.** A recommendation from the permissive revision conflicts with the final no-driver choice.

**Recovery.** Preserve observations while clearing recommendation authority after each change.

**Stopping boundary.** The final restricted scenario has no supported basket.

**Outside this simulation.** Actual client consent; Consent persistence across real devices; An installation.

| Condition | Executed steps | Passed checks | Final software state |
|---|---:|---:|---|
| baseline | 10 | 30/30 | DEFERRED; 0 supported baskets |
| cost-shock | 10 | 30/30 | DEFERRED; 0 supported baskets |
| interrupted | 11 | 32/32 | DEFERRED; 0 supported baskets |

One executed path (baseline):

1. Initial scripted planning request → RECOMMENDED, 1 supported baskets.
2. Record the scenario cost allowance → ACTIVE, 1 supported baskets.
3. Request a fresh recommendation after the allowance change → RECOMMENDED, 1 supported baskets.
4. Withdraw permission for the shared-machine scenario → ACTIVE, 0 supported baskets.
5. Answer no when the controller revisits permission → DEFERRED, 0 supported baskets.
6. Explore a separately explicit permissive planning revision → ACTIVE, 1 supported baskets.
7. Request a plan under that temporary permissive assumption → RECOMMENDED, 1 supported baskets.
8. Return to the shared machine and withdraw permission again → ACTIVE, 0 supported baskets.
9. Finish with the final explicit refusal → DEFERRED, 0 supported baskets.
10. Retain observations while honoring the latest permission → DEFERRED, 0 supported baskets.

## Dev — household equipment coordinator — fictional

Two people share a desk and describe the old monitor differently. Dev first enters too many owned displays, then corrects the count but copies a lower resolution from an old note. A second requirement for a high-power charger arrives later, and Dev wants to explore a smaller budget without changing the current plan.

**Goal.** Reuse the actual represented monitor and understand the effect of changing requirements without silently changing the live scenario.

**Competing priorities.** Reduce waste; Reconcile conflicting equipment notes; Support charging expectations; Experiment without losing the current setup.

**Starting mental model.** Anything described as a monitor is adequate for the requested resolution, and a budget preview might replace the current plan.

**Scripted decision rule.** Attempts an impossible inventory count, corrects it to one low-resolution monitor, fixes the resolution, adds an unsupported charging target, explicitly removes that target, then previews a low budget and checks that the active record is unchanged.

**Correction trigger.** Inventory rejection, insufficient owned-monitor resolution or an unsupported charging target.

**Recovery.** Correct the inventory explicitly; keep read-only exploration separate from mutation.

**Stopping boundary.** The represented inventory or charging requirement cannot support the requested setup.

**Outside this simulation.** Household interviews; Physical inventory verification; Actual charging performance.

| Condition | Executed steps | Passed checks | Final software state |
|---|---:|---:|---|
| baseline | 10 | 31/31 | RECOMMENDED; 1 supported baskets |
| cost-shock | 10 | 31/31 | RECOMMENDED; 1 supported baskets |
| interrupted | 11 | 33/33 | RECOMMENDED; 1 supported baskets |

One executed path (baseline):

1. Initial scripted planning request → RECOMMENDED, 1 supported baskets.
2. Record the scenario cost allowance → ACTIVE, 1 supported baskets.
3. Request a fresh recommendation after the allowance change → RECOMMENDED, 1 supported baskets.
4. Accidentally enter three owned monitors for a two-display goal → RECOMMENDED, 1 supported baskets.
5. Correct the count but copy a lower resolution from an old note → ACTIVE, 0 supported baskets.
6. Correct the declared monitor resolution → ACTIVE, 1 supported baskets.
7. Add a new high-power charging requirement → ACTIVE, 0 supported baskets.
8. Explicitly remove the unsupported charging target → ACTIVE, 1 supported baskets.
9. Explore a small budget without replacing the active scenario → ACTIVE, 1 supported baskets.
10. Return to the corrected active inventory → RECOMMENDED, 1 supported baskets.

## Interpretation

A deferral is an intended outcome when the represented requirements remain unsupported. An ACTIVE state after an edit is distinct from a fresh recommendation. Nothing in these trajectories grants payment authority.

- Realistic detail is authored fiction; behavioral realism has not been validated with people.
- Names, motivations, mental models and decision thresholds are design hypotheses, not observed traits.
- All variants share one catalog and validator; journeys, steps and checks are correlated, not participant counts.
- Execution is deterministic local policy plus scripted choices, not an autonomous language-model user simulator.
- Only the software states and guard outcomes were measured; no emotions, task times, satisfaction or comprehension scores were measured.
- The interruption is a JSON state round trip, not a browser crash/restart or real observed distraction.
- Direct Python calls do not test UI discoverability, accessibility, session security or sandbox transactions.
- No actual study occurred. Roadmap 88 remains pending; all external gates remain unchanged.

## Reproduce

```sh
.venv/bin/python scripts/rehearse_complex_personas.py --as-of 2026-10-19 --output output/complex-personas.json --markdown output/complex-personas.md
```

The companion JSON contains all scripted inputs, stage snapshots, failed checks if any, full profiles and source hashes. Existing reports are never overwritten.
