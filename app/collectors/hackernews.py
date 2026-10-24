"""Hacker News collector (official Firebase API)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.collectors.base import IngestResult, RawItem, ingest
from app.collectors.http import make_client
from app.collectors.prescore import is_ai_related
from app.config import get_settings
from app.models import KIND_HACKERNEWS, Source
from app.settings_store import get_setting
from app.utils import strip_html

log = logging.getLogger(__name__)
API = "https://hacker-news.firebaseio.com/v0"


def story_to_raw(story: dict) -> RawItem | None:
    if not story or story.get("type") != "story" or story.get("dead") or story.get("deleted"):
        return None
    sid = story["id"]
    title = story.get("title") or ""
    hn_url = f"https://news.ycombinator.com/item?id={sid}"
    url = story.get("url") or hn_url
    text = strip_html(story.get("text") or "")
    flags = ["ai"] if is_ai_related(title + " " + text[:300]) else []
    return RawItem(
        kind=KIND_HACKERNEWS,
        external_id=f"hn:{sid}",
        url=url,
        title=title,
        original_text=text,
        source_label="Hacker News",
        points=story.get("score") or 0,
        comments_count=story.get("descendants") or 0,
        comments_url=hn_url,
        author=story.get("by") or "",
        flags=flags,
        published_at=datetime.fromtimestamp(story["time"], tz=timezone.utc).replace(tzinfo=None) if story.get("time") else None,
        raw={"hn_id": sid},
    )


def collect(db: Session, source: Source) -> IngestResult:
    settings = get_settings()
    cfg = source.config or {}
    min_points = int(cfg.get("min_points") or get_setting(db, "hn_min_points", settings.hn_min_points))
    max_stories = int(cfg.get("max_stories", settings.hn_max_stories))
    ai_only = bool(cfg.get("ai_only", False))
    with make_client(timeout=20) as client:
        ids: list[int] = []
        for feed in ("topstories", "beststories"):
            r = client.get(f"{API}/{feed}.json")
            if r.status_code == 200:
                ids.extend(r.json()[: max_stories])
        ids = list(dict.fromkeys(ids))

        def fetch(i: int) -> dict | None:
            try:
                rr = client.get(f"{API}/item/{i}.json")
                return rr.json() if rr.status_code == 200 else None
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            stories = list(pool.map(fetch, ids))
    raws: list[RawItem] = []
    for s in stories:
        raw = story_to_raw(s or {})
        if raw is None or (raw.points or 0) < min_points:
            continue
        if ai_only and "ai" not in raw.flags:
            continue
        raws.append(raw)
    res = ingest(db, source, raws)
    db.commit()
    return res
