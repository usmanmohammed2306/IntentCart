# Model transport clarification — October 19, 2026

Model actions accept one complete JSON object or one complete JSON code fence with no surrounding prose. This removes transport formatting only: strict fields/types/lengths and state-dependent action validation still run. Multiple values, prose, invented actions, stale revisions, unauthorized clarification and unsupported basket IDs fail. Actual model testing retained rejected replies, including an overlength reason; failures keep their durable reservations and do not trigger automatic retries. Temporary live allowances never changed the permanent cap from zero. Raw credentials, buyer data, model diagnostics and payment responses remain private; published evidence is explicitly sanitized.

# 4.3 workbench boundaries

Workbench mutation endpoints are human-triggered, exact-revision/Origin/CSRF/session checked and absent from the model tool schema. A per-task reviewed catalog cannot overwrite the shared catalog. A source proposal binds the exact product/variant/field, validates types/units/origins/review date, and needs a separate exact-ID acceptance. It is a human declaration, not an authenticity check. Changed observations and old preference evidence are removed. Offers bind merchant/offer/product/variant identity; duplicate cross-product offer IDs are rejected. Missing all-in costs and expired observations cannot support a plan. CSV export neutralizes common spreadsheet formula prefixes.

The research cost preview admits only six queries, 32 worlds and total cost 64, with bounded exact search; it changes no task or provider state. Saved report endpoints require complete expected source identities. Offline importers bound input size, avoid URL fetching, preserve duplicate/repeat identities and never enable payments or inference. Transcript claims remain imported/unverified, with unknown billed cost preserved. Workstation pilot preparation collects no records or participants by itself. Current permanent cap remains zero. Existing single-worker, sandbox-only and lack-of-account-authentication limits remain.

# 4.2 agent boundaries

Agent actions cannot write product facts, confirm scenario assumptions, grant driver permission or execute payments. Strict schemas, owned state, source identities and exact revisions protect mutations and exports. Inspections require a discovered exact variant and reject duplicate work; operation/inspection bounds stop runaway local behavior. Model dispatch requires existing configured credit-only/rate/budget gates and durable shared reservation before the request. Failed parsing, HTTP errors and stale concurrent replies retain reservations; no automatic retries occur. Human comparisons retain hard constraints and invalidate stale quotes. Current configuration remains default-off with zero external calls.

Manufacturer field validation is not authenticity or a hardware guarantee. Public display uses text escaping; raw task text is private, and model invocation would transmit the explicit task and observed evidence to Astropods when enabled. The new agent does not have a retailer purchase tool. Existing sandbox checkout remains independently approved. Human studies, arbitrary prompt-injection resistance and production certification remain unproven.

# Missions 4.1 security additions

The Decision lab serves fixed local public fixture artifacts only. It requires the expected schema and complete matching source identities; unsupported/stale reports are refused. Trace downloads select allowlisted report IDs and never accept an execution payload. Public certificates omit server caches and hidden observation values. Their approval field always grants no consent and their execution field does not infer payment status.

The CLI replay tool strictly validates bounded source-bound action traces, uses temporary application/provider databases, blanks credentials, keeps external-call and model budgets zero, and blocks production HTTP transports. Deliberate insecure mutants exist only inside those child test processes. A restart is an actual new interpreter after a simulated exception boundary, not an operating-system kill. Trailing/consecutive empty restarts are rejected. The tool is not a sandbox for arbitrary Python, a universal payment guarantee, or an externally callable fault injector. Source hashes identify contents; they are not authenticity signatures.

All payment authority, retention and single-instance limitations below remain applicable. No new real-money or live-model capability is enabled by this release.

The new workstation planner uses existing session ownership, exact Origin/CSRF, strict bounded schemas, versioning and serialized SQLite writes. Source identities invalidate saved missions/quotes after catalog/compiler changes. A canonical complete basket with authoritative quantities/prices and resolved facts must pass the payment gate. Discovery/model proposals cannot modify specifications, price or consent. Quote receipt/export is private and records no approval.

Astropods dispatch is optional and default-off: positive shared external call cap, operator-reviewed price ceilings, positive local budget, credit-only account confirmation and server-side credentials are required. Reservations persist before dispatch; failures retain reservations; no retries, redirects, page-load model calls or autonomous tools. Gateway responses are streamed with a 64 KiB ceiling and strict Goal validation. Driver permission resets to false. Local budget accounting is not a provider billing guarantee; leave disabled on unknown pricing/ancillary charges. No secret or gateway host is returned by public status.

The built-in fixture inspector performs no network request. It does not establish real source truth. Retailer discovery remains distinct from fictional merchant checkout. Exported goal text may be personal; no automatic upload. The retained production limitations below apply to Missions: one worker, sandbox only, no account authentication, distributed locks, real inventory, fulfillment or independent audit.

## Retained controls and limitations

# Security and operations

## Version 3 experiment and pilot boundaries

Optional decision control is advisory and uncalibrated. Deferral does not certify safety; synthetic recall was low. Humans can manually select feasible products under existing exact-quote/payment checks. Default classic mode stays. Stress evaluation imports no provider/storage module and makes no external requests.

Pilot rows stay in private SQLite, keyed by owned session. Consent, strict schemas, Origin/CSRF, revision checks and source identities protect collection. Blinded independent responses never update the learner; no pilot endpoint creates quotes/orders. Wrong comprehension answers stay outcomes. Owned export contains private choices/anonymous study ID. Withdrawal deletes the local row, not downloaded copies. Session expiry does not purge records; operator deletes raw data within 30 days. No automated purge, verified age or unique-human verification. Public packaging excludes databases/raw pilot exports.

## Implemented boundaries

- Sandbox-only PayPal host; no live credential switch or live-money route.
- Opaque HttpOnly, SameSite=Lax session cookies; SHA-256 cookie identifiers stored in SQLite. Sessions expire for access after seven days.
- Exact configured Origin plus per-session CSRF token on mutations. No permissive CORS.
- Strict request schemas, bounded fields, a streamed 64 KiB body ceiling, and an in-process 120 requests/IP/minute API limit.
- Server-side products/prices, total-budget constraints, quote ownership, preference versions, and 15-minute expiry.
- Persisted provider retry keys before side effects; order reference and exact USD capture/refund amount checks. No automatic fresh request after a known uncertain result.
- Safe text escaping for dynamic UI content; CSP, frame denial, no-referrer, nosniff, and restricted browser permissions. Secrets are never returned by the configuration endpoint.

## Run safely

Use `.env` only locally; it is excluded from Git and Docker context. `chmod 600 .env`. Do not paste reusable credentials into the public README, video, screenshots, logs, or Devpost description. A PayPal client ID is public by design; the client secret is not. Use a separate sandbox buyer account from the app's merchant account.

For local use, bind to `127.0.0.1`, use `PUBLIC_URL=http://127.0.0.1:4000`, and leave `COOKIE_SECURE=false`. For a deliberately deployed HTTPS build set its exact public origin and `COOKIE_SECURE=true`. Keep a single worker and a persistent SQLite volume. Do not expose this unauthenticated sandbox demo as a real-money storefront.

Back up `var/intentcart.sqlite3` using SQLite's backup API while running, or copy it only while the server is stopped. Protect backups as session/feedback data. Quotes, receipts, and feedback are retained until the operator explicitly removes the local database; session expiry is an access rule, not automatic deletion. Feedback is opt-in and may contain voluntary text. Do not publish its raw export.

## Interrupted operations

If create is interrupted, retry opening the **same quote**; the committed request key is reused. If capture is interrupted, use the saved order's status check first. A completed provider capture is verified and recorded; a still-approved order can be retried under a current quote with its saved capture key. Never create a new quote just to retry a potentially charged order.

Refund has a saved request key and a durable `REFUND_PENDING` state. Its button retries that same request. First-attempt times for create, capture, and refund are persisted independently of status-update times; polling cannot renew a retry window. The application blocks retries after five hours from the first attempt. This is an application ceiling, not a guarantee of provider retention: [PayPal idempotency behavior](https://developer.paypal.com/api/rest/reference/idempotency/) depends on the endpoint. Old pending refunds without a trustworthy first-attempt timestamp require operator review. Provider pending/refunded captures may also require manual dashboard reconciliation. This build does not claim automatic recovery from every provider outage.

Order-level `COMPLETED` is insufficient evidence of payment. Missing/malformed captures are rejected; a pending capture is reported as `CAPTURE_PENDING`. Only a matching completed capture can authorize the refund flow. After an interrupted capture, reconcile first; an order still approved under a valid current quote exposes **Finish approved sandbox payment**, using the same saved capture key.

## Production limitations

No account authentication, webhook settlement, distributed limiter/locks, background reconciliation, inventory reservations, live-mode tax/fulfillment, or independent security audit is included. SQLite storage and session ownership are suitable for the stated single-instance sandbox demonstration. A production financial system requires those additional controls, load testing, monitoring, and operational review. No claim of production certification is made.

Report a reproducible problem to the repository maintainer after the repository is published; do not include secrets in a public issue.

## Rehearsal and decision exports

World previews and challenge checks never authorize spending. Applying a scenario requires CSRF, exact origin, session ownership and the current version. The actual order-creation path also invokes the deterministic proposal gate; its quote/pricing/budget checks cannot be bypassed by a green dry-run label. All products and interventions remain fictional.

Receipt JSON is scoped to an owned quote. Its frozen decision context may include voluntary mission text and comparisons: export only when requested and review before sharing. There is no automatic public upload. The pre-checkout receipt must show approval absent until checkout records consent. Content fingerprints and saved-source hashes help inspection and staleness detection; they are not digital signatures, an independent trust root or an audited security guarantee.

The seven scripted gate cases and single fake lost-response trace cover specific behaviors. They do not demonstrate arbitrary attack resistance, LLM prompt-injection defense, universal exactly-once payments or resilience to every provider failure. Live provider recovery remains subject to the operational limits above.

## Interface controls, 2.1

The command menu contains navigation only and cannot open over an active modal via its keyboard shortcut. Choice shortcuts require explicit opt-in; editable targets, modifier/repeat keys, busy operations and open dialogs are ignored. Native buttons and exact-quote approval remain the primary path. Client explanation arithmetic is not authorization and does not send provider requests. Preference charts and scenario meters derive from actual state and disclose scaling. No external font, image or visual CDN was added. Reduced-motion and responsive checks do not constitute independent accessibility certification.
