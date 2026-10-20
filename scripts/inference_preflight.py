"""Read-only, secret-free inference configuration and durable-budget preflight."""
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intentcart import config

def inspect():
    url = urlsplit(config.ASTRO_URL)
    gates = {'https_gateway_configured': bool(url.scheme == 'https' and url.hostname and not url.username and not url.password and not url.query and not url.fragment),
             'credential_present': bool(config.ASTRO_KEY), 'credit_only_reviewed': config.ASTRO_CREDIT_ONLY,
             'external_call_cap_positive': config.CALL_LIMIT > 0, 'local_budget_positive': config.ASTRO_BUDGET > 0,
             'positive_reviewed_rates': config.ASTRO_INPUT_RATE > 0 and config.ASTRO_OUTPUT_RATE > 0}
    result = {'gates': gates, 'configured_enabled': all(gates.values()), 'live_connectivity_verified': False,
              'notice': 'Read-only configuration check. No network, model call, account change or secret output. Positive configuration does not prove provider access or a hard billing cap.'}
    path = Path(config.DATABASE_PATH).resolve()
    if path.is_file():
        try:
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
                rows = dict(db.execute('SELECT name,count FROM calls'))
            used = rows.get('astro', 0) + rows.get('channel3', 0)
            result['remaining_local_calls'] = max(0, config.CALL_LIMIT - used)
            result['reserved_microusd'] = rows.get('astro_reserved_microusd', 0)
        except sqlite3.Error:
            result['budget_storage'] = 'unavailable; do not enable inference'
    else:
        result['budget_storage'] = 'not initialized'
    return result

if __name__ == '__main__':
    print(json.dumps(inspect(), indent=2))
