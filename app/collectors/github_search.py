"""GitHub Search API collector (new + active AI repositories)."""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from sqlalchemy.orm import Session

from app.collectors.base import IngestResult, RawItem, ingest
from app.collectors.http import RateLimited, github_get, make_client
from app.config import get_settings
from app.models import KIND_GITHUB_REPO, Source, utcnow
from app.utils import parse_dt

log = logging.getLogger(__name__)

DEFAULT_QUERIES = [
    {"q": "topic:llm", "label": "llm"},
    {"q": "topic:ai-agents", "label": "agents"},
    {"q": "topic:agents", "label": "agents"},
    {"q": "topic:rag", "label": "rag"},
    {"q": "topic:mcp", "label": "mcp"},
    {"q": "topic:mcp-server", "label": "mcp"},
    {"q": "topic:machine-learning", "label": "ml"},
    {"q": "topic:deep-learning", "label": "ml"},
    {"q": "topic:diffusion-models", "label": "diffusion"},
    {"q": "topic:computer-vision", "label": "vision"},
    {"q": "topic:speech-recognition", "label": "audio"},
    {"q": "topic:artificial-intelligence", "label": "ai"},
    {"q": "claude in:name,description,topics", "label": "claude"},
    {"q": "openai in:name,description,topics", "label": "openai"},
    {"q": "topic:llmops", "label": "llmops"},
    {"q": "topic:fine-tuning", "label": "finetune"},
]


def repo_to_raw(repo: dict, flags: list[str], label: str = "GitHub Search") -> RawItem:
    full = repo.get("full_name") or ""
    return RawItem(
        kind=KIND_GITHUB_REPO,
        external_id=f"gh:{full.lower()}",
        url=repo.get("html_url") or f"https://github.com/{full}",
        title=full,
        original_text=repo.get("description") or "",
        source_label=label,
        repo_full_name=full,
        language=repo.get("language") or "",
        stars=repo.get("stargazers_count"),
        forks=repo.get("forks_count"),
        topics=list(repo.get("topics") or []),
        repo_created_at=parse_dt(repo.get("created_at")),
        repo_pushed_at=parse_dt(repo.get("pushed_at")),
        author=(repo.get("owner") or {}).get("login", ""),
        flags=flags,
        published_at=parse_dt(repo.get("created_at")),
        raw={"license": (repo.get("license") or {}).get("spdx_id", ""), "archived": repo.get("archived", False)},
    )


def collect(db: Session, source: Source) -> IngestResult:
    settings = get_settings()
    cfg = source.config or {}
    queries = cfg.get("queries") or DEFAULT_QUERIES
    days_new = int(cfg.get("days_new", settings.github_search_days_new))
    min_stars_active = int(cfg.get("min_stars_active", settings.github_search_min_stars_active))
    per_page = int(cfg.get("per_page", 30))
    modes = cfg.get("modes") or ["new", "active"]
    total = IngestResult()
    now = utcnow()
    with make_client() as client:
        for q in queries:
            qs = q["q"] if isinstance(q, dict) else str(q)
            label = (q.get("label") if isinstance(q, dict) else None) or qs
            for mode in modes:
                if mode == "new":
                    since = (now - timedelta(days=days_new)).date().isoformat()
                    full_q = f"{qs} created:>{since} stars:>20"
                    flags = [f"search:{label}", "new_repo"]
                else:
                    since = (now - timedelta(days=3)).date().isoformat()
                    full_q = f"{qs} pushed:>{since} stars:>{min_stars_active}"
                    flags = [f"search:{label}"]
                try:
                    res = github_get(
                        client,
                        db,
                        f"{settings.github_api_url}/search/repositories",
                        params={"q": full_q, "sort": "stars", "order": "desc", "per_page": per_page},
                    )
                except RateLimited as exc:
                    log.warning("search rate limited; stopping (reset at %s)", exc.reset_at)
                    db.commit()
                    return total
                except Exception as exc:
                    log.warning("search failed for %r: %s", full_q, exc)
                    continue
                if res.not_modified:
                    continue
                if res.status != 200 or not isinstance(res.data, dict):
                    log.warning("search %r -> %s %s", full_q, res.status, res.text[:120])
                    continue
                raws = [repo_to_raw(r, flags) for r in res.data.get("items", []) if not r.get("archived")]
                r = ingest(db, source, raws)
                total.created += r.created
                total.updated += r.updated
                db.commit()
                time.sleep(2.2)  # search API: 30 req/min authenticated
    return total
