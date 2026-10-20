# Executable reliability replay

The replay harness exercises the real Missions and sandbox payment API endpoints with `TestClient`, disposable application storage, and a separately persisted SQLite fake-provider ledger. It records what the app accepted and what the fake provider actually committed. It can export a sanitized executable trace and reduce a deliberately failing trace by deleting unnecessary events.

This is a finite local fault-injection and mutation-testing artifact. It is not a live PayPal experiment, a population reliability estimate, proof of arbitrary fault tolerance, a prompt-injection benchmark, or a production certification.

## Reproduce and inspect

Use the project's installed Python environment:

```sh
.venv/bin/python scripts/evaluate_reliability.py
.venv/bin/python scripts/evaluate_reliability.py --export-trace create-after --trace-output /tmp/create-after.json
.venv/bin/python scripts/evaluate_reliability.py --replay /tmp/create-after.json
.venv/bin/python scripts/evaluate_reliability.py --export-trace minimal-mutant-fresh-retry-id --trace-output /tmp/retry-defect.json
.venv/bin/python scripts/evaluate_reliability.py --replay /tmp/retry-defect.json
.venv/bin/python -m pytest -q tests/test_replay.py
```

The first command generates `intentcart/data/reliability-evaluation.json`; `--output PATH` selects another report location. The next commands export and execute one report trace. Exported mutation traces retain their explicit `mutant` field, so one replay command reproduces the injected failure. A successful command executing such a trace means the recorded failure was reproduced, not that the mutated system is safe. The output names its invariant violations.

The evidence page reads saved public evidence. It never executes a trace, accepts a trace upload, or activates a mutation over HTTP. All mutation execution belongs to the local tool, in new isolated child interpreters.

A trace binds the supported source files with SHA-256 and contains an expected normalized outcome digest after evaluation. Source changes reject old traces. Preserve the prior report, then generate fresh evidence after editing; changing a saved hash alone is not a reproduction. A source edit during reduction also aborts, rather than falsely treating unsuccessful candidates as evidence of minimality.

## Declared cases and denominators

The suite contains **two valid controls and nine fault cases**, each replayed twice for **22 baseline executions**:

| Family | Cases | Expected intact behavior |
|---|---:|---|
| Valid completion | 2 | Complete a fake capture across restart, or complete capture and refund |
| Before-dispatch interruption | 3 | Create/capture/refund retries retain their saved identities and eventually complete |
| After-commit response loss | 3 | Provider truth survives separately; restarting and retrying/reconciling does not duplicate the operation |
| Obsolete quote approval | 1 | Reject creation after the reviewed goal changes |
| Absent approval | 1 | Reject creation without explicit approval |
| Order-level completion without a capture | 1 | Reject completion lacking a verified capture |

There are **six interruption points**, not six types of all possible failures. The three injected defects each run against one designated scenario, followed by bounded trace reduction. Candidate replays used during reduction are separately counted; they are not additional independent reliability trials. Exact outcomes, counts, source identities and checks belong to the generated report.

The deliberate mutations are:

1. **`stale-approval`**: bypass the actual quote validation and spending gate in the disposable process. Detect a new fake provider order dispatched against a changed mission revision.
2. **`fresh-retry-id`**: replace the persisted create request identity when an uncertain request is retried. Detect two independent provider order commitments for one quote.
3. **`order-completed`**: substitute an unsafe verifier that accepts an order-level `COMPLETED` response without capture evidence. Detect a locally recorded completion unsupported by the independent provider ledger.

These are known introduced faults in testing wrappers. They are not claims that three production bugs were discovered. The unmodified app runs the same scenario families with successful completion controls so an implementation that always blocks does not pass.

## What a restart means

The fake provider commits its result to its own SQLite file before raising a declared `ProviderError`. The app handles that exception using its real request path. A `restart` event then closes the client and interpreter; a new interpreter imports the application and reconstructs its provider using the durable files and the same private test session. This verifies persistence across actual process replacement.

The interruption is exception injection at declared boundaries followed by orderly interpreter replacement, **not an operating-system kill at arbitrary instructions**. The matrix does not cover all SQLite crash behavior, concurrent requests, machines losing both stores, webhook races, or provider retention windows. Fake-provider behavior is deliberately narrow: identical request identities deduplicate, while distinct create identities may create two orders. It is not a complete PayPal emulator.

## Safe trace language

`intentcart.replay.Trace` is a strict versioned Pydantic schema. A trace contains:

- `schema_version`: `intentcart-replay-v1`;
- a bounded identifier, an allowlisted mutation name, and exact supported source hashes;
- two to forty typed events;
- an optional expected normalized replay digest.

Allowed events are start, read, quote, revise, explicitly approved/unapproved create, capture, status, refund, restart, one of six declared interruption points, and the declared malformed-provider-response fixture. Start creates the fixed fictional workstation goal. Revision changes its budget to the fixed fixture value. The trace cannot supply arbitrary user text, prices, HTTP bodies, URLs, Python code, commands, database paths, or credentials. Unknown fields, wrong types, unknown versions, invalid prerequisites and files over 64 KiB are rejected.

The runner creates temporary storage, blanks PayPal/Channel3/Astropods credentials, sets all external call ceilings to zero, and blocks real synchronous/asynchronous HTTP transports plus the production PayPal request boundary. Each child process has a bounded timeout. It does not import application configuration in the caller, modify `.env`, open the configured user database, or schedule work. A private worker refuses startup without the expected temporary-storage and blank-credential environment.

Only normalized public observations leave the runner: event types, HTTP/status results, declared uncertainty, operation/attempt/distinct-identity counts, invariant failures and digest. Session cookies, CSRF values, retry keys, quote UUIDs, raw responses and voluntary text remain within temporary execution state. Random identities and clock values are omitted instead of being claimed reproducible. There is no timing performance claim.

## Reduction and its limits

The reducer preserves the exact observed set of violation names. It greedily tries deleting one event at a time, retaining event order. Each candidate must pass the trace's causal prerequisites and execute the real endpoints. It repeats until a full pass finds no deletion preserving that violation set, or the candidate-attempt limit is reached.

`removal_minimal: true` means no **single-event deletion allowed by this schema** preserved that failure in the final pass. It does not mean globally shortest, independently validated root cause, or minimal under changes to arguments, reordered events or joint deletions. A limit-exhausted run reports `false`. Runtime errors and source changes abort reduction instead of silently counting as non-reproducing candidates.

The independent ledger and successful controls strengthen these tests, but the trace fixtures, fake provider and checker are still project-authored and can share blind spots. No human outcomes, new sandbox receipts, live model trajectories, GPU training or sponsor credit usage are implied.
