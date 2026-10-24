"""Fetch repository metadata + README excerpt for items about to be enriched."""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.collectors.http import RateLimited, github_get, make_client
from app.config import get_settings
from app.models import KIND_GITHUB_RELEASE, KIND_GITHUB_REPO, Item
from app.utils import parse_dt, truncate

log = logging.getLogger(__name__)


def _clean_readme(text: str) -> str:
    import re

    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)  # html badges etc
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # images
    text = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)  # links -> text
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_details(db: Session, items: list[Item]) -> int:
    """Populate stars/topics/created_at and readme_excerpt. Returns count fetched."""
    settings = get_settings()
    count = 0
    targets = [it for it in items if it.kind in (KIND_GITHUB_REPO, KIND_GITHUB_RELEASE) and it.repo_full_name]
    if not targets:
        return 0
    with make_client() as client:
        for it in targets:
            full = it.repo_full_name
            try:
                meta = github_get(client, db, f"{settings.github_api_url}/repos/{full}", use_cache=False)
                if meta.status == 200 and isinstance(meta.data, dict):
                    d = meta.data
                    if it.kind == KIND_GITHUB_REPO:
                        it.stars = d.get("stargazers_count", it.stars) or it.stars
                        it.forks = d.get("forks_count", it.forks) or it.forks
                        it.language = d.get("language") or it.language
                        if d.get("description") and not it.original_text:
                            it.original_text = d["description"]
                    else:
                        it.stars = d.get("stargazers_count", it.stars) or it.stars
                    topics = list(d.get("topics") or [])
                    if topics:
                        it.topics = list(dict.fromkeys([*(it.topics or []), *topics]))[:20]
                    it.repo_created_at = parse_dt(d.get("created_at")) or it.repo_created_at
                    it.repo_pushed_at = parse_dt(d.get("pushed_at")) or it.repo_pushed_at
                    raw = dict(it.raw or {})
                    raw["license"] = (d.get("license") or {}).get("spdx_id", "")
                    raw["homepage"] = d.get("homepage") or ""
                    raw["open_issues"] = d.get("open_issues_count", 0)
                    it.raw = raw
                if not it.readme_excerpt:
                    rd = github_get(
                        client,
                        db,
                        f"{settings.github_api_url}/repos/{full}/readme",
                        use_cache=False,
                        accept="application/vnd.github.raw+json",
                    )
                    if rd.status == 200:
                        text = rd.text if rd.text else (rd.data if isinstance(rd.data, str) else "")
                        it.readme_excerpt = truncate(_clean_readme(text or ""), settings.github_readme_max_chars)
                count += 1
                time.sleep(0.3)
            except RateLimited as exc:
                log.warning("details: rate limited (reset %s)", exc.reset_at)
                break
            except Exception as exc:
                log.warning("details failed for %s: %s", full, exc)
    db.commit()
    return count
