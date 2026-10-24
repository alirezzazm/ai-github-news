"""Cookie-based admin authentication."""
from __future__ import annotations

import hmac
import time

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import get_settings

COOKIE = "aign_admin"
MAX_AGE = 60 * 60 * 24 * 14
_attempts: dict[str, list[float]] = {}


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="admin-session")


def make_token(user: str) -> str:
    return _serializer().dumps({"u": user})


def verify_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=MAX_AGE)
        return data.get("u")
    except BadSignature:
        return None


def check_credentials(user: str, password: str, ip: str) -> bool:
    now = time.time()
    hist = [t for t in _attempts.get(ip, []) if now - t < 600]
    _attempts[ip] = hist
    if len(hist) >= 8:
        return False
    settings = get_settings()
    ok = hmac.compare_digest(user.encode(), settings.admin_user.encode()) and hmac.compare_digest(
        password.encode(), settings.admin_password.encode()
    )
    if not ok:
        hist.append(now)
    return ok


def current_admin(request: Request) -> str | None:
    return verify_token(request.cookies.get(COOKIE))


def require_admin(request: Request) -> str:
    user = current_admin(request)
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": f"/admin/login?next={request.url.path}"})
    return user
