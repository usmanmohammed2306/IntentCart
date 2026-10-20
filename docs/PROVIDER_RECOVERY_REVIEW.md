# Actual complete-basket verification — October 19, 2026

The authorized USD 279 complete fictional workstation order was approved by the sandbox buyer, captured and fully refunded. Final separate PayPal API reads verified order identity/reference, completed order, refunded capture, completed full-amount USD refund and application agreement. Ten server API requests (including two OAuth requests) stayed within the authorized twelve-call ceiling; browser-internal SDK/authentication traffic is excluded. No real money or goods. Raw responses and buyer credentials remain private; sanitized report: ../submission/workstation-sandbox-verification.json. No uncertain operation was replaced by a new order. Permanent caps remain zero; the isolated server is stopped. This actual bundle result supersedes the earlier pending bundle gate; prior fake-provider recovery experiments remain separate evidence.

# Provider timeout and uncertain response review

All current checks use fake providers and local API transports. A live timeout exercise and a fresh complete-bundle sandbox receipt remain unverified.

A model request reserves a durable shared call count and maximum local cost before dispatch. Timeout, malformed output, stale revision or response loss keeps that reservation. Refresh the owned task and inspect the provider's authoritative usage before deciding whether another separately authorized request is appropriate. A timeout is not evidence that the provider did no work. Do not retry automatically or convert reserved cost into billed cost.

For PayPal sandbox, use the saved quote/order and reconcile its status after an uncertain capture. Verify the matching capture's ID, reference, USD amount and completed status; order-level completion alone is insufficient. Refund only the matching verified sandbox capture. Preserve the saved retry identity and the application's retry-age ceiling; do not generate a fresh quote to retry a potentially completed payment. The replay tool exercises actual local endpoints with a separate fake ledger and simulated interruption boundaries; it does not establish live universal exactly-once recovery.

For future live evidence retain the task/revision, reported/configured model identity basis, bounded request count, reservations, actual billed usage when known, all errors, uncertain transport outcomes and unattempted trials. The transcript analyzer labels imported claims explicitly and leaves missing billed costs unknown. Never expose raw credentials, account screenshots or private feedback in a public report.
