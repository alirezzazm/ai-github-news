"""JSON API and RSS feed."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import CATEGORIES, Item
from app.settings_store import get_setting
from app.web import queries

router = APIRouter(prefix="/api", tags=["public"])
feed_router = APIRouter()


def item_to_dict(it: Item, full: bool = False) -> dict:
    d = {
        "id": it.id,
        "kind": it.kind,
        "url": it.url,
        "title": it.title,
        "title_fa": it.title_fa,
        "summary_fa": it.summary_fa,
        "category": it.category,
        "category_fa": it.category_fa,
        "tags": it.tags or [],
        "importance": it.importance,
        "translated": it.is_translated,
        "source": it.source_label,
        "repo": it.repo_full_name or None,
        "language": it.language or None,
        "stars": it.stars or None,
        "stars_delta_day": it.stars_delta_day or None,
        "stars_delta_week": it.stars_delta_week or None,
        "spike_delta": it.spike_delta or None,
        "points": it.points or None,
        "comments_count": it.comments_count or None,
        "flags": it.flags or [],
        "published_at": it.published_at.isoformat() + "Z" if it.published_at else None,
        "first_seen_at": it.first_seen_at.isoformat() + "Z",
        "last_seen_at": it.last_seen_at.isoformat() + "Z",
    }
    if full:
        d.update(
            {
                "original_text": it.original_text,
                "readme_summary_fa": it.readme_summary_fa,
                "ideas": it.ideas or [],
                "topics": it.topics or [],
                "release_tag": it.release_tag or None,
                "comments_url": it.comments_url or None,
                "author": it.author or None,
                "enrich_model": it.enrich_model or None,
            }
        )
    return d


@router.get("/items")
def api_items(request: Request, db: Session = Depends(get_db)):
    """List items. Filters: q, category, lang, kind, period(today|3d|week|month|all), sort, translated, flag, page, per_page, ids."""
    ids_param = request.query_params.get("ids")
    if ids_param:
        try:
            ids = [int(x) for x in ids_param.split(",") if x.strip()][:100]
        except ValueError:
            raise HTTPException(400, "ids must be integers")
        rows = db.scalars(select(Item).where(Item.id.in_(ids), Item.hidden.is_(False))).all()
        by_id = {r.id: r for r in rows}
        return {"items": [item_to_dict(by_id[i]) for i in ids if i in by_id], "total": len(rows)}
    f = queries.Filters.from_params(request.query_params)
    items, total = queries.list_items(db, f)
    return {"items": [item_to_dict(i) for i in items], "total": total, "page": f.page, "per_page": f.per_page}


@router.get("/items/{item_id}")
def api_item(item_id: int, db: Session = Depends(get_db)):
    it = db.get(Item, item_id)
    if it is None or it.hidden:
        raise HTTPException(404)
    return item_to_dict(it, full=True)


@router.get("/trending")
def api_trending(period: str = "weekly", db: Session = Depends(get_db)):
    if period not in ("daily", "weekly", "monthly"):
        raise HTTPException(400, "period must be daily|weekly|monthly")
    return {"period": period, "items": [item_to_dict(i) for i in queries.trending(db, period)]}


@router.get("/releases")
def api_releases(days: int = 14, db: Session = Depends(get_db)):
    return {"items": [item_to_dict(i, full=True) for i in queries.releases(db, min(days, 90))]}


@router.get("/ideas")
def api_ideas(days: int = 2, db: Session = Depends(get_db)):
    return {"items": [{"id": i.id, "title_fa": i.display_title, "url": i.url, "ideas": i.ideas} for i in queries.ideas_today(db, min(days, 30))]}


@router.get("/spikes")
def api_spikes(db: Session = Depends(get_db)):
    return {"items": [item_to_dict(i) for i in queries.spikes(db)]}


@router.get("/categories")
def api_categories(db: Session = Depends(get_db)):
    counts = queries.category_counts(db)
    return {"categories": [{"key": k, "label": v, "count_7d": counts.get(k, 0)} for k, v in CATEGORIES.items()]}


@router.get("/stats")
def api_stats(db: Session = Depends(get_db)):
    return queries.stats(db)


# --------------------------------------------------------------------------- RSS
def _rfc822(dt: datetime | None) -> str:
    dt = dt or datetime.now(timezone.utc).replace(tzinfo=None)
    return format_datetime(dt.replace(tzinfo=timezone.utc))


@feed_router.get("/feed.xml", include_in_schema=False)
@feed_router.get("/rss", include_in_schema=False)
def rss_feed(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    site = str(get_setting(db, "site_url", settings.site_url)).rstrip("/")
    f = queries.Filters.from_params(request.query_params)
    f.per_page = 50
    f.page = 1
    if "translated" not in request.query_params:
        f.translated_only = True
    if "period" not in request.query_params:
        f.period = "week"
    if "sort" not in request.query_params:
        f.sort = "new"
    items, _ = queries.list_items(db, f)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        "<channel>",
        f"<title>{escape(settings.site_name)}</title>",
        f"<link>{escape(site)}/</link>",
        "<description>خبرهای هوش مصنوعی و تکنولوژی از گیت‌هاب با خلاصهٔ فارسی</description>",
        "<language>fa</language>",
        f'<atom:link href="{escape(site)}/feed.xml" rel="self" type="application/rss+xml"/>',
        f"<lastBuildDate>{_rfc822(None)}</lastBuildDate>",
    ]
    for it in items:
        desc = it.summary_fa or it.original_text[:600]
        if it.ideas:
            desc += "\n\nبا این چی می‌شه ساخت؟\n" + "\n".join(f"• {i.get('title', '')}: {i.get('description', '')}" for i in it.ideas)
        meta = []
        if it.stars:
            meta.append(f"⭐ {it.stars:,}")
        if it.language:
            meta.append(it.language)
        if it.category_fa:
            meta.append(it.category_fa)
        if meta:
            desc = " | ".join(meta) + "\n\n" + desc
        parts.append("<item>")
        parts.append(f"<title>{escape(it.display_title)}</title>")
        parts.append(f"<link>{escape(it.url)}</link>")
        parts.append(f'<guid isPermaLink="false">{escape(it.external_id)}</guid>')
        parts.append(f"<pubDate>{_rfc822(it.published_at or it.first_seen_at)}</pubDate>")
        for t in it.tags or []:
            parts.append(f"<category>{escape(str(t))}</category>")
        parts.append(f"<description>{escape(desc)}</description>")
        parts.append(f"<comments>{escape(site)}/item/{it.id}</comments>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    return Response("\n".join(parts), media_type="application/rss+xml; charset=utf-8")

