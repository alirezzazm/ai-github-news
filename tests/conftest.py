import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Must be set before any app import so Settings picks it up.
_DB_FILE = ROOT / "data" / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_FILE.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASSWORD"] = "pw"
os.environ["LLM_PROVIDERS"] = ""
os.environ["GITHUB_TOKEN"] = ""
os.environ["NOTIFY_BOT_TOKEN"] = ""

from app.db import Base, get_engine, get_sessionmaker, init_db, reset_engine_for_tests  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    _DB_FILE.parent.mkdir(exist_ok=True)
    if _DB_FILE.exists():
        _DB_FILE.unlink()
    reset_engine_for_tests(os.environ["DATABASE_URL"])
    init_db()
    yield
    get_engine().dispose()


@pytest.fixture()
def db():
    """Fresh tables for every test."""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    from app.settings_store import clear_cache

    clear_cache()
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def fixtures_dir() -> Path:
    return ROOT / "tests" / "fixtures"
