"""Daily star refresh for every tracked repository (GraphQL batch, REST fallback).

Trending/search only touch repositories that re-appear, so without this job the
star history would have gaps and spikes would be detected late.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import _snapshot  # shared snapshot rule (one per 6h)
from app.collectors.http import RateLimited, github_get, github_headers, make_client
from app.collectors.prescore import compute_prescore
from app.config import get_settings
from app.models import KIND_GITHUB_REPO, Item, utcnow
from app.settings_store import get_setting
from app.utils import parse_dt

log = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.github.com/graphql"
BATCH = 80
MAX_REPOS_PER_RUN = 2000
REST_MAX = 150  # without a token the REST limit is 60/h; keep it tiny


def _gql_batch(client: httpx.Client, headers: dict, repos: list[str]) -> dict[str, dict]:
    parts = []
    for i, full in enumerate(repos):
        owner, name = full.split("/", 1)
        owner = owner.replace('"', "")
        name = name.replace('"', "")
        parts.append(f'r{i}: repository(owner:"{owner}", name:"{name}") {{ nameWithOwner stargazerCount forkCount pushedAt primaryLanguage {{ name }} }}')
    query = "{ rateLimit { remaining resetAt } " + " ".join(parts) + " }"
    resp = client.post(GRAPHQL_URL, headers=headers, json={"query": query})
    if resp.status_code in (401, 403):
        raise RateLimited(None)
    if resp.status_code != 200:
        raise RuntimeError(f"graphql HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    out: dict[str, dict] = {}
    for i, full in enumerate(repos):
        node = (data.get("data") or {}).get(f"r{i}")
        if node:
            out[full.lower()] = node
    rl = (data.get("data") or {}).get("rateLimit") or {}
    if rl and int(rl.get("remaining", 1000)) < 50:
        log.warning("GraphQL rate limit nearly exhausted (reset %s)", rl.get("resetAt"))
        time.sleep(5)
    return out


def track_stars(db: Session, days: int = 30) -> dict:
    settings = get_settings()
    now = utcnow()
    since = now - timedelta(days=days)
    items = db.scalars(
        select(Item)
        .where(Item.kind == KIND_GITHUB_REPO, Item.hidden.is_(False), Item.last_seen_at >= since, Item.repo_full_name != "")
        .order_by(Item.prescore.desc())
        .limit(MAX_REPOS_PER_RUN)
    ).all()
    by_name = {it.repo_full_name.lower(): it for it in items}
    names = list(by_name.keys())
    stats = {"repos": len(names), "updated": 0, "missing": 0, "mode": "graphql"}
    if not names:
        return stats
    token = get_setting(db, "github_token", "") or settings.github_token
    headers = github_headers(db)

    def apply(it: Item, stars: int, forks: int, pushed, lang: str | None):
        it.stars = stars
        it.forks = forks
        if pushed:
            it.repo_pushed_at = pushed
        if lang:
            it.language = lang
        _snapshot(db, it.repo_full_name, stars, forks, now)
        it.prescore = compute_prescore(it, it.source)

    with make_client(timeout=60) as client:
        if token:
            for i in range(0, len(names), BATCH):
                chunk = names[i : i + BATCH]
                try:
                    nodes = _gql_batch(client, headers, [by_name[n].repo_full_name for n in chunk])
                except RateLimited:
                    log.warning("star tracker: GraphQL unauthorised/limited; stopping")
                    stats["error"] = "GraphQL rate limited or token invalid"
                    break
                except Exception as exc:
                    log.warning("star tracker batch failed: %s", exc)
                    stats["error"] = str(exc)[:200]
                    continue
                for n in chunk:
                    node = nodes.get(n)
                    if not node:
                        stats["missing"] += 1
                        continue
                    apply(by_name[n], int(node.get("stargazerCount") or 0), int(node.get("forkCount") or 0), parse_dt(node.get("pushedAt")), (node.get("primaryLanguage") or {}).get("name"))
                    stats["updated"] += 1
                db.commit()
                time.sleep(1)
        else:
            stats["mode"] = "rest"
            for n in names[:REST_MAX]:
                it = by_name[n]
                try:
                    res = github_get(client, db, f"{settings.github_api_url}/repos/{it.repo_full_name}", use_cache=False)
                except RateLimited:
                    stats["error"] = "REST rate limited (set a GitHub token)"
                    break
                except Exception as exc:
                    log.warning("star tracker REST failed %s: %s", it.repo_full_name, exc)
                    continue
                if res.status == 200 and isinstance(res.data, dict):
                    d = res.data
                    apply(it, int(d.get("stargazers_count") or 0), int(d.get("forks_count") or 0), parse_dt(d.get("pushed_at")), d.get("language"))
                    stats["updated"] += 1
                else:
                    stats["missing"] += 1
                time.sleep(1.2)
            db.commit()
    return stats
