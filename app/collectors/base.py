"""Common ingestion logic: RawItem -> Item upsert with dedupe and star snapshots."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.linking import extract_repo_full_name
from app.collectors.prescore import compute_prescore
from app.models import (
    ENRICH_PENDING,
    KIND_GITHUB_REPO,
    Item,
    Source,
    StarSnapshot,
    utcnow,
)

log = logging.getLogger(__name__)

SNAPSHOT_MIN_GAP = timedelta(hours=6)


@dataclass
class RawItem:
    kind: str
    external_id: str
    url: str
    title: str
    original_text: str = ""
    source_label: str = ""
    repo_full_name: str = ""
    language: str = ""
    stars: int | None = None
    forks: int | None = None
    stars_delta_day: int | None = None
    stars_delta_week: int | None = None
    stars_delta_month: int | None = None
    topics: list[str] = field(default_factory=list)
    release_tag: str = ""
    repo_created_at: datetime | None = None
    repo_pushed_at: datetime | None = None
    points: int | None = None
    comments_count: int | None = None
    comments_url: str = ""
    author: str = ""
    flags: list[str] = field(default_factory=list)
    rank: int | None = None
    published_at: datetime | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class IngestResult:
    created: int = 0
    updated: int = 0
    ids: list[int] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated


def ingest(db: Session, source: Source | None, raws: list[RawItem]) -> IngestResult:
    """Upsert items by ``external_id``; merge fields; keep star history."""
    result = IngestResult()
    if not raws:
        return result
    ids = [r.external_id for r in raws]
    existing = {
        it.external_id: it for it in db.scalars(select(Item).where(Item.external_id.in_(ids))).all()
    }
    now = utcnow()
    seen: set[str] = set()
    touched: list[Item] = []
    for raw in raws:
        if raw.external_id in seen:
            continue
        seen.add(raw.external_id)
        item = existing.get(raw.external_id)
        if item is None:
            item = Item(
                kind=raw.kind,
                external_id=raw.external_id,
                url=raw.url,
                title=raw.title,
                original_text="",
                readme_excerpt="",
                title_fa="",
                summary_fa="",
                readme_summary_fa="",
                category="",
                tags=[],
                ideas=[],
                topics=[],
                flags=[],
                raw={},
                importance=0,
                stars=0,
                forks=0,
                stars_delta_day=0,
                stars_delta_week=0,
                stars_delta_month=0,
                points=0,
                comments_count=0,
                rank=0,
                first_seen_at=now,
                enrich_status=ENRICH_PENDING,
            )
            db.add(item)
            result.created += 1
        else:
            result.updated += 1
        touched.append(item)
        if raw.kind != KIND_GITHUB_REPO and not raw.repo_full_name:
            linked = extract_repo_full_name(raw.url)
            if linked:
                raw.repo_full_name = linked
                if "links_repo" not in raw.flags:
                    raw.flags = [*raw.flags, "links_repo"]
        _merge(item, raw, source, now)
        item.prescore = compute_prescore(item, source)
        if item.kind == KIND_GITHUB_REPO and raw.stars is not None:
            _snapshot(db, item.repo_full_name, raw.stars, raw.forks or 0, now)
    db.flush()
    result.ids = [it.id for it in touched]
    return result


def _merge(item: Item, raw: RawItem, source: Source | None, now: datetime) -> None:
    item.last_seen_at = now
    if source is not None:
        item.source_id = source.id
    if raw.source_label:
        item.source_label = raw.source_label
    if raw.url:
        item.url = raw.url
    if raw.title:
        item.title = raw.title
    if raw.original_text and (not item.original_text or len(raw.original_text) > len(item.original_text)):
        item.original_text = raw.original_text
    if raw.repo_full_name:
        item.repo_full_name = raw.repo_full_name
    if raw.language:
        item.language = raw.language
    if raw.stars is not None:
        item.stars = raw.stars
    if raw.forks is not None:
        item.forks = raw.forks
    if raw.stars_delta_day is not None:
        item.stars_delta_day = raw.stars_delta_day
    if raw.stars_delta_week is not None:
        item.stars_delta_week = raw.stars_delta_week
    if raw.stars_delta_month is not None:
        item.stars_delta_month = raw.stars_delta_month
    if raw.topics:
        merged = list(dict.fromkeys([*(item.topics or []), *raw.topics]))
        item.topics = merged[:20]
    if raw.release_tag:
        item.release_tag = raw.release_tag
    if raw.repo_created_at:
        item.repo_created_at = raw.repo_created_at
    if raw.repo_pushed_at:
        item.repo_pushed_at = raw.repo_pushed_at
    if raw.points is not None:
        item.points = raw.points
    if raw.comments_count is not None:
        item.comments_count = raw.comments_count
    if raw.comments_url:
        item.comments_url = raw.comments_url
    if raw.author:
        item.author = raw.author
    if raw.rank is not None:
        item.rank = raw.rank
    if raw.published_at and not item.published_at:
        item.published_at = raw.published_at
    if raw.flags:
        flags = list(item.flags or [])
        for f in raw.flags:
            if f not in flags:
                flags.append(f)
        item.flags = flags[:40]
    if raw.raw:
        merged_raw = dict(item.raw or {})
        merged_raw.update(raw.raw)
        item.raw = merged_raw


def _snapshot(db: Session, repo: str, stars: int, forks: int, now: datetime) -> None:
    if not repo:
        return
    last = db.scalars(
        select(StarSnapshot)
        .where(StarSnapshot.repo_full_name == repo)
        .order_by(StarSnapshot.taken_at.desc())
        .limit(1)
    ).first()
    if last is not None and now - last.taken_at < SNAPSHOT_MIN_GAP:
        last.stars = stars
        last.forks = forks
        return
    db.add(StarSnapshot(repo_full_name=repo, stars=stars, forks=forks, taken_at=now))
