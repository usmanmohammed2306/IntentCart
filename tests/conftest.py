
# Manufacturer regression fixtures describe the October 19 reviewed snapshot.
# Runtime expiry uses the actual Phoenix date; explicit age-boundary tests pass
# their own dates. This prevents future CI from silently testing a different task.
import pytest
from datetime import date
@pytest.fixture(autouse=True)
def reviewed_catalog_clock(monkeypatch):
    from intentcart import workbench
    monkeypatch.setattr(workbench,'current_day',lambda:date(2026,10,19))
