"""Runtime settings: DB value overrides the environment value."""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.config import RUNTIME_KEYS, get_settings
from app.models import Setting

_cache: dict[str, tuple[float, str | None]] = {}
_TTL = 30.0


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    """Return DB override if present (non-empty), else env/config value."""
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        db_val = hit[1]
    else:
        row = db.get(Setting, key)
        db_val = row.value if row is not None else None
        _cache[key] = (now, db_val)
    if db_val not in (None, ""):
        return _coerce(key, db_val)
    settings = get_settings()
    if default is None and hasattr(settings, key):
        return getattr(settings, key)
    return default


def _coerce(key: str, value: str) -> Any:
    settings = get_settings()
    current = getattr(settings, key, None)
    if isinstance(current, bool):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        try:
            return int(value)
        except ValueError:
            return current
    if isinstance(current, float):
        try:
            return float(value)
        except ValueError:
            return current
    return value


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    _cache.pop(key, None)


def clear_cache() -> None:
    _cache.clear()


def all_runtime_settings(db: Session) -> list[dict]:
    """For the admin form: key, label, masked current value, whether overridden."""
    out = []
    settings = get_settings()
    for key, meta in RUNTIME_KEYS.items():
        row = db.get(Setting, key)
        db_val = row.value if row is not None else ""
        env_val = str(getattr(settings, key, ""))
        effective = db_val or env_val
        shown = mask(effective) if meta["secret"] else effective
        out.append(
            {
                "key": key,
                "label": meta["label"],
                "secret": meta["secret"],
                "value": shown,
                "overridden": bool(db_val),
                "has_value": bool(effective),
            }
        )
    return out


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return value[:4] + "…" + value[-4:]
