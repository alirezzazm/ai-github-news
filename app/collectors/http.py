"""HTTP helpers: shared client, GitHub auth, conditional requests, rate limits."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import HttpCache, utcnow
from app.settings_store import get_setting

log = logging.getLogger(__name__)

USER_AGENT = "ai-github-news/1.0 (+https://github.com/alirezzazm/ai-github-news)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class RateLimited(Exception):
    def __init__(self, reset_at: float | None):
        super().__init__("rate limited")
        self.reset_at = reset_at


@dataclass
class Fetched:
    status: int
    data: Any = None
    text: str = ""
    not_modified: bool = False
    headers: dict | None = None


def make_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=15.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def github_headers(db: Session | None) -> dict[str, str]:
    token = ""
    if db is not None:
        token = get_setting(db, "github_token", "") or ""
    else:
        token = get_settings().github_token
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_get(
    client: httpx.Client,
    db: Session,
    url: str,
    params: dict | None = None,
    *,
    use_cache: bool = True,
    accept: str | None = None,
    retries: int = 2,
) -> Fetched:
    """GET against the GitHub API with ETag support and rate-limit awareness.

    Returns ``Fetched(not_modified=True)`` on 304 so callers can skip work.
    """
    headers = github_headers(db)
    if accept:
        headers["Accept"] = accept
    cache_key = url + ("?" + httpx.QueryParams(params).__str__() if params else "")
    cache_row = db.get(HttpCache, cache_key) if use_cache else None
    if cache_row is not None:
        if cache_row.etag:
            headers["If-None-Match"] = cache_row.etag
        if cache_row.last_modified:
            headers["If-Modified-Since"] = cache_row.last_modified

    attempt = 0
    while True:
        attempt += 1
        try:
            resp = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            if attempt <= retries:
                time.sleep(2 * attempt)
                continue
            raise
        if resp.status_code == 304:
            return Fetched(status=304, not_modified=True, headers=dict(resp.headers))
        if resp.status_code in (403, 429):
            remaining = resp.headers.get("X-RateLimit-Remaining")
            reset = resp.headers.get("X-RateLimit-Reset")
            retry_after = resp.headers.get("Retry-After")
            if remaining == "0" or retry_after or "rate limit" in resp.text.lower():
                wait = None
                if retry_after:
                    wait = float(retry_after)
                elif reset:
                    wait = max(0.0, float(reset) - time.time())
                if wait is not None and wait <= 90 and attempt <= retries:
                    log.warning("GitHub rate limit; sleeping %.0fs", wait + 1)
                    time.sleep(wait + 1)
                    continue
                raise RateLimited(float(reset) if reset else None)
        if resp.status_code >= 500 and attempt <= retries:
            time.sleep(3 * attempt)
            continue
        if resp.status_code >= 400:
            return Fetched(status=resp.status_code, text=resp.text[:500], headers=dict(resp.headers))
        if use_cache and (resp.headers.get("ETag") or resp.headers.get("Last-Modified")):
            if cache_row is None:
                cache_row = HttpCache(url=cache_key)
                db.add(cache_row)
            cache_row.etag = resp.headers.get("ETag", "") or ""
            cache_row.last_modified = resp.headers.get("Last-Modified", "") or ""
            cache_row.fetched_at = utcnow()
        ctype = resp.headers.get("Content-Type", "")
        if "json" in ctype:
            return Fetched(status=resp.status_code, data=resp.json(), headers=dict(resp.headers))
        return Fetched(status=resp.status_code, text=resp.text, headers=dict(resp.headers))


def plain_get(client: httpx.Client, url: str, *, browser: bool = False, retries: int = 2, **kw) -> httpx.Response:
    headers = kw.pop("headers", {})
    if browser:
        headers.setdefault("User-Agent", BROWSER_UA)
        headers.setdefault("Accept-Language", "en-US,en;q=0.9")
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = client.get(url, headers=headers, **kw)
            if resp.status_code in (429, 502, 503) and attempt <= retries:
                time.sleep(3 * attempt)
                continue
            return resp
        except httpx.HTTPError:
            if attempt <= retries:
                time.sleep(2 * attempt)
                continue
            raise
