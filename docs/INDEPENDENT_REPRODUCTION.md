# Reproduce IntentCart without provider credentials

Use a fresh checkout of the complete source, Python 3.12 and Node.js. The public README-only commit is not the complete source release. Record the actual Git revision (or source manifest), OS, interpreter versions and lockfile hash. Independence requires a different person to run the procedure; a second local container does not qualify.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock.txt
EXTERNAL_CALL_LIMIT=0 python scripts/verify.py
python scripts/evaluate_missions.py --output /tmp/missions.json
python scripts/evaluate_agent.py --output /tmp/agent.json
python scripts/evaluate_budget_roadmap.py --output /tmp/budget.json
python scripts/evaluate_preference_workbench.py --output /tmp/preferences.json
```

Do not copy `.env`, saved databases, account images or participant feedback from another checkout. The canonical verifier uses temporary storage, blanks provider credentials and keeps external calls at zero. Compare correctness checks and explicit denominators, rather than requiring wall-clock timings to match across machines. Retain failures, commands, exit codes and environment details. Inspect negative learning results as carefully as successful constraint checks.

For an interactive review, run `python -m intentcart`, open the exact configured local origin, start a reviewed `/agent` task, and use `/workbench` for sources, inventory, price uncertainty and exports. `/research` reads saved source-bound offline results. Changed source files can intentionally invalidate old saved reports; rerun the named evaluation instead of bypassing hash checks. `/missions` remains the separate fictional sandbox merchant.

## Minimal reproduction report

- Reviewer chooses whether to share their name; do not solicit private contact data.
- Actual revision/source hashes, OS and dependency versions.
- Exact commands, pass/fail counts and failures; no edited or omitted negative results.
- Whether provider credentials were absent and external calls stayed zero.
- Whether setup, tests and observed workflows reproduced.
- Any differences, unclear assumptions or unsupported claims.

No external reviewer has completed this procedure merely because this guide exists.
