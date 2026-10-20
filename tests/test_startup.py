"""Storage opens at application startup, never during inspection/import."""
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from intentcart import app as module, config


def test_import_does_not_open_or_create_storage(tmp_path):
    # An inaccessible database parent must not prevent documentation or test
    # collection from importing the app. The previous import-time init failed.
    parent = tmp_path / 'not-a-directory'
    parent.write_text('leave this file alone')
    env = dict(os.environ, DATABASE_PATH=str(parent / 'app.sqlite3'),
               PYTHONDONTWRITEBYTECODE='1', EXTERNAL_CALL_LIMIT='0',
               PAYPAL_CLIENT_ID='', PAYPAL_CLIENT_SECRET='', CHANNEL3_API_KEY='')
    result = subprocess.run([sys.executable, '-c', 'import intentcart.app'],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert parent.read_text() == 'leave this file alone'


def test_server_startup_initializes_fresh_storage(tmp_path, monkeypatch):
    destination = tmp_path / 'new-install' / 'app.sqlite3'
    monkeypatch.setattr(config, 'DATABASE_PATH', str(destination))
    module.RATES.clear()
    assert not destination.exists()
    with TestClient(module.app) as client:
        response = client.get('/api/session')
        assert response.status_code == 200
        assert response.json()['csrf_token']
        assert destination.is_file()
