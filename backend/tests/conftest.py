# backend/tests/conftest.py
# Test setup for the backend smoke suite.
# Requires pytest (dev tool only; intentionally not added to requirements.txt).
# No external LLM provider, network service, or production database is used.
import importlib
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# A fixed signing key avoids writing a secret file during tests.
os.environ.setdefault("APP_SECRET_KEY", "pytest-only-secret-key-with-at-least-32-bytes-0123456789")
os.environ.setdefault("RATE_LIMIT_SHARED", "0")

# Modules that may capture DB_PATH at import time. Missing modules are ignored safely.
_DB_MODULE_CANDIDATES = (
    "backend.database.dataset_store",
    "backend.database.db_connector",
    "backend.auth.user_store",
    "backend.auth.auth",
    "backend.auth.account_deletion",
    "backend.auth.verification",
    "backend.utils.ai_gate",
    "backend.utils.rate_limiter",
    "backend.agents.orchestrator",
    "backend.scheduling.schedule_store",
    "backend.scheduling.runner",
)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """
    Points every loaded backend module's DB_PATH at a fresh temporary SQLite file for each test.
    This avoids touching the real development database.
    """
    for name in _DB_MODULE_CANDIDATES:
        try:
            importlib.import_module(name)
        except ImportError:
            pass

    db_path = tmp_path / "test_app_data.db"
    db_str = str(db_path)

    for name, module in list(sys.modules.items()):
        if not name.startswith("backend."):
            continue
        if not hasattr(module, "DB_PATH"):
            continue

        original = getattr(module, "DB_PATH")
        replacement = db_path if isinstance(original, Path) else db_str
        monkeypatch.setattr(module, "DB_PATH", replacement, raising=False)

    yield db_str


@pytest.fixture
def make_user(isolated_database):
    """Creates a real user record and returns its id."""
    import uuid

    from backend.auth.user_store import UserStore

    def _make(label: str = "user") -> str:
        email = f"{label}-{uuid.uuid4().hex[:10]}@example.test"
        result = UserStore.create_user(email, "Password123!")

        if isinstance(result, dict):
            result = result.get("user_id") or result.get("id")

        return str(result)

    return _make