"""Collector registry and orchestration."""
from __future__ import annotations

import logging
import traceback
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors import github_releases, github_search, github_trending, hackernews, huggingface, rss
from app.collectors.base import IngestResult
from app.models import SRC_HF, SRC_HN, SRC_RELEASES, SRC_RSS, SRC_SEARCH, SRC_TRENDING, Source, utcnow

log = logging.getLogger(__name__)

COLLECTORS: dict[str, Callable[[Session, Source], IngestResult]] = {
    SRC_TRENDING: github_trending.collect,
    SRC_SEARCH: github_search.collect,
    SRC_RELEASES: github_releases.collect,
    SRC_HN: hackernews.collect,
    SRC_RSS: rss.collect,
    SRC_HF: huggingface.collect,
}

KIND_LABELS = {
    SRC_TRENDING: "ترند گیت‌هاب",
    SRC_SEARCH: "جست‌وجوی گیت‌هاب",
    SRC_RELEASES: "ریلیزهای گیت‌هاب",
    SRC_HN: "Hacker News",
    SRC_RSS: "فید RSS",
    SRC_HF: "Hugging Face",
}


def run_source(db: Session, source: Source) -> IngestResult:
    fn = COLLECTORS.get(source.kind)
    if fn is None:
        raise ValueError(f"unknown source kind {source.kind}")
    source.last_run_at = utcnow()
    db.commit()
    try:
        res = fn(db, source)
        source.last_status = "ok"
        source.last_error = ""
        source.items_last_run = res.total
        log.info("source %s: +%d new, %d updated", source.key, res.created, res.updated)
    except Exception as exc:
        db.rollback()
        source.last_status = "error"
        source.last_error = f"{exc.__class__.__name__}: {exc}"[:1000]
        log.error("source %s failed: %s\n%s", source.key, exc, traceback.format_exc())
        res = IngestResult()
    finally:
        source.last_run_at = utcnow()
        db.commit()
    return res


def run_kinds(db: Session, kinds: list[str] | None = None, only_enabled: bool = True) -> dict:
    q = select(Source)
    if kinds:
        q = q.where(Source.kind.in_(kinds))
    if only_enabled:
        q = q.where(Source.enabled.is_(True))
    sources = db.scalars(q.order_by(Source.id)).all()
    stats: dict[str, dict] = {}
    for s in sources:
        res = run_source(db, s)
        stats[s.key] = {"created": res.created, "updated": res.updated, "status": s.last_status}
    return stats
