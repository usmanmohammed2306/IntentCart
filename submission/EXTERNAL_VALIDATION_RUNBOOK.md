# External validation: bounded execution and recovery

Current result, October 19, 2026: the approved execution is finished. The temporary inference and PayPal servers and local Astropods bridge are stopped. Permanent `.env` remains `EXTERNAL_CALL_LIMIT=0`. The temporary inference configuration was also disarmed (cap/budget zero, short-lived key removed), and the stopped gateway container removed. No background jobs are authorized.

## Recorded allowance and outcome

The user authorized at most USD 1 of existing free Astropods credits and 48 total model requests, after review of credit-only access and rates. The account had USD 10 free credit and no payment method. The gateway usage limit was reduced to USD 1 and remains protective. The actual run used 17 requests; Astropods reported USD 0.026906 local-development gateway usage, rounded remaining credit USD 9.97 and billed spend USD 0.00. Local conservative reservations were USD 0.131483, including failed replies; reservations are not bills.

Existing CLI authentication was refreshed and a short-lived gateway credential injected into a local Docker bridge. No cloud/GPU deployment, card, subscription or cash purchase was made. The request alias was `claude-haiku-4-5`; actual replies reported `global.anthropic.claude-haiku-4-5-20251001-v1:0`. GPU hardware was not disclosed. The standard reviewed Haiku 4.5 rates were USD 1 input / USD 5 output per million tokens. Sources: [Astropods gateway](https://docs.astropods.com/ai-gateway), [chat interface](https://docs.astropods.com/ai-gateway/chat), [pricing](https://astropods.com/pricing), [Haiku pricing](https://platform.claude.com/docs/en/about-claude/pricing).

Three initial rejected requests exposed prose/fencing and unsupported tool clarification. Instructions were tightened; a single complete JSON fence can now be unwrapped, then the original strict action schema and state-dependent validator still run. Prose, multiple values, extra fields and unauthorized actions remain rejected. No automatic retry was added.

The native fixture completed four matched trials, two per controller. Both controllers repeated the same supported decision. The harder driver task retained one supported trial, one rejected overlength response and two unattempted trials. These are authored fixture diagnostics and scripted permission answers, not human outcomes or proof of comparative superiority. See [live-validation.json](live-validation.json).

## Reproduce safely

Default commands make no provider calls:

```sh
python scripts/run_live_validation.py
python scripts/sandbox_budget_server.py
python scripts/inference_preflight.py
python scripts/audit_external_validation.py
```

Actual execution needs a new specifically authorized allowance and a separate local process configuration, usable existing access, reviewed model alias/canonical identity and rates, and the same durable cumulative ledgers. Do not reset a ledger to recover allowance, edit permanent caps, assume old approvals recur, or run a GPU deployment. Private credentials, request diagnostics, account screenshots and raw payment responses belong in ignored `output/` only.

`run_live_validation.py --execute` requires explicit tasks, expected canonical model, request alias, request ceiling, local server origin and a new private output directory. Its preflight subtracts prior durable usage. Fresh sessions, identical model/tools and counterbalanced controller order are used. Failed, capped and unattempted trials remain outcomes. Phase files are saved before continuing; uncertain responses stop rather than retry. Aggregate account billing does not establish per-trial costs.

## Exact workstation sandbox transaction

The separate authorization covered only the USD 279.00 fictional basket: dock USD 129, display USD 109, cable kit USD 12 and supply USD 29, zero shipping/tax. The isolated server allowed at most twelve server-side PayPal sandbox API calls, including OAuth and failures. It rejected live hosts and changed order totals. Browser authentication and SDK-internal traffic are outside this server-side count.

The existing order was approved by the sandbox buyer, captured and fully refunded. Separate final provider reads verified the same order, capture and refund, USD currency and full amount. Ten server API calls were used. See [workstation-sandbox-verification.json](workstation-sandbox-verification.json). The historical USD 62 backpack receipt is a different transaction. No goods or delivery exists.

After interruption, reconcile the saved order before any capture retry; preserve its idempotency identities. Never create a replacement order to resolve uncertainty. A completed order alone is insufficient: verify the capture. A refund request alone is insufficient: verify its amount, identity and completed status. A changed/expired quote needs a new reviewed journey, not silently altered saved terms.

## Human pilot remains unperformed

The protocol and observation analyzer are ready; no people participated. Fictional personas cannot supply consent, ratings, task times or human outcomes. A future separately authorized pilot must use voluntary adult consent, withdrawal, incomplete outcomes and errors. Private sheets use arbitrary local IDs, no contact/credential/demographic data and local 30-day retention. Optional usability ratings use 1–7, with missing ratings left missing. Raw sheets and even aggregate reports remain private until reviewed. See `docs/WORKSTATION_PILOT.md` and `scripts/analyze_workstation_pilot.py`.

## Publication

Runnable-source commit/push, remote CI, public video URL, hackathon registration/terms and final submission remain entrant-owned. The recorded deadline is November 12, 2026 at noon PST / 1 p.m. Phoenix; keep required access through judging. Packaging is preparation, not publication or acceptance of terms.
