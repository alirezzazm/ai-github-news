import os

from app.config import get_settings
from app.settings_store import clear_cache, get_setting, set_setting


def test_env_value_wins_over_caller_default(db, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    get_settings.cache_clear()
    clear_cache()
    try:
        assert get_setting(db, "github_token", "") == "env-token"
        assert get_setting(db, "digest_items", None) == 10
        assert get_setting(db, "unknown_key", "fallback") == "fallback"
        set_setting(db, "github_token", "db-token")
        db.commit()
        assert get_setting(db, "github_token", "") == "db-token"
        set_setting(db, "github_token", "")
        db.commit()
        assert get_setting(db, "github_token", "") == "env-token"  # empty override -> env
        set_setting(db, "llm_batch_size", "7")
        db.commit()
        assert get_setting(db, "llm_batch_size") == 7  # coerced to the Settings field type
    finally:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        get_settings.cache_clear()
        clear_cache()
