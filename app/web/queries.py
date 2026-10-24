"""Reusable item queries for pages and the JSON API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ENRICH_DONE,
    KIND_GITHUB_RELEASE,
    KIND_GITHUB_REPO,
    KIND_HACKERNEWS,
    KIND_HF_MODEL,
    KIND_HF_PAPER,
    KIND_RSS,
    Item,
    StarSnapshot,
    utcnow,
)

PERIODS = {"today": 1, "3d": 3, "week": 7, "month": 30, "all": None}
PERIOD_LABELS = {"today": "امروز", "3d": "۳ روز", "week": "هفته", "month": "ماه", "all": "همه"}
KIND_LABELS = {
    KIND_GITHUB_REPO: "ریپو",
    KIND_GITHUB_RELEASE: "ریلیز",
    KIND_HACKERNEWS: "Hacker News",
    KIND_RSS: "مقاله",
    KIND_HF_MODEL: "مدل HF",
    KIND_HF_PAPER: "مقالهٔ پژوهشی",
}
SORTS = {"hot": "داغ‌ترین", "new": "تازه‌ترین", "stars": "بیشترین ستاره", "growth": "بیشترین رشد", "importance": "مهم‌ترین"}


@dataclass
class Filters:
    q: str = ""
    category: str = ""
    language: str = ""
    kind: str = ""
    period: str = "3d"
    sort: str = "hot"
    translated_only: bool = False
    flag: str = ""
    page: int = 1
    per_page: int = 30

    @classmethod
    def from_params(cls, params) -> "Filters":
        def g(k, d=""):
            v = params.get(k, d)
            return v if v is not None else d

        try:
            page = max(1, int(g("page", 1)))
        except ValueError:
            page = 1
        try:
            per_page = max(5, min(100, int(g("per_page", 30))))
        except ValueError:
            per_page = 30
        return cls(
            q=str(g("q")).strip()[:100],
            category=str(g("category")).strip()[:30],
            language=str(g("lang")).strip()[:40],
            kind=str(g("kind")).strip()[:30],
            period=g("period", "3d") if g("period", "3d") in PERIODS else "3d",
            sort=g("sort", "hot") if g("sort", "hot") in SORTS else "hot",
            translated_only=str(g("translated", "")).lower() in ("1", "true", "on"),
            flag=str(g("flag")).strip()[:40],
            page=page,
            per_page=per_page,
        )

    def as_query(self, **overrides) -> str:
        from urllib.parse import urlencode

        d = {
            "q": self.q,
            "category": self.category,
            "lang": self.language,
            "kind": self.kind,
            "period": self.period,
            "sort": self.sort,
            "translated": "1" if self.translated_only else "",
            "flag": self.flag,
        }
        d.update(overrides)
        return urlencode({k: v for k, v in d.items() if v not in ("", None, "3d", "hot") or k in overrides})


def apply_filters(stmt, f: Filters):
    stmt = stmt.where(Item.hidden.is_(False))
    days = PERIODS.get(f.period)
    if days:
        stmt = stmt.where(Item.last_seen_at >= utcnow() - timedelta(days=days))
    if f.category:
        stmt = stmt.where(Item.category == f.category)
    if f.language:
        stmt = stmt.where(func.lower(Item.language) == f.language.lower())
    if f.kind:
        stmt = stmt.where(Item.kind == f.kind)
    if f.translated_only:
        stmt = stmt.where(Item.enrich_status == ENRICH_DONE)
    if f.flag:
        stmt = stmt.where(cast(Item.flags, String).like(f'%"{f.flag}"%'))
    if f.q:
        like = f"%{f.q}%"
        stmt = stmt.where(
            or_(
                Item.title.ilike(like),
                Item.title_fa.ilike(like),
                Item.summary_fa.ilike(like),
                Item.original_text.ilike(like),
                Item.repo_full_name.ilike(like),
                cast(Item.tags, String).ilike(like),
                cast(Item.topics, String).ilike(like),
            )
        )
    return stmt


def order_by(stmt, sort: str):
    if sort == "new":
        return stmt.order_by(Item.first_seen_at.desc(), Item.id.desc())
    if sort == "stars":
        return stmt.order_by(Item.stars.desc(), Item.id.desc())
    if sort == "growth":
        return stmt.order_by(Item.stars_delta_day.desc(), Item.stars_delta_week.desc(), Item.id.desc())
    if sort == "importance":
        return stmt.order_by(Item.importance.desc(), Item.prescore.desc(), Item.id.desc())
    # hot: translated & important first, then prescore
    return stmt.order_by((Item.importance * 10 + Item.prescore).desc(), Item.last_seen_at.desc(), Item.id.desc())


def list_items(db: Session, f: Filters) -> tuple[list[Item], int]:
    base = apply_filters(select(Item), f)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    stmt = order_by(base, f.sort).offset((f.page - 1) * f.per_page).limit(f.per_page)
    return list(db.scalars(stmt).all()), int(total)


def languages(db: Session, days: int = 30) -> list[tuple[str, int]]:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(Item.language, func.count(Item.id))
        .where(Item.language != "", Item.hidden.is_(False), Item.last_seen_at >= since)
        .group_by(Item.language)
        .order_by(func.count(Item.id).desc())
        .limit(14)
    ).all()
    return [(r[0], r[1]) for r in rows]


def category_counts(db: Session, days: int = 7) -> dict[str, int]:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(Item.category, func.count(Item.id))
        .where(Item.category != "", Item.hidden.is_(False), Item.last_seen_at >= since)
        .group_by(Item.category)
    ).all()
    return {r[0]: r[1] for r in rows}


def trending(db: Session, period: str = "weekly", limit: int = 40) -> list[Item]:
    flag = f"trending_{period}"
    col = {"daily": Item.stars_delta_day, "weekly": Item.stars_delta_week, "monthly": Item.stars_delta_month}[period]
    days = {"daily": 2, "weekly": 8, "monthly": 32}[period]
    stmt = (
        select(Item)
        .where(
            Item.kind == KIND_GITHUB_REPO,
            Item.hidden.is_(False),
            Item.last_seen_at >= utcnow() - timedelta(days=days),
            cast(Item.flags, String).like(f'%"{flag}"%'),
        )
        .order_by(col.desc(), Item.stars.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def spikes(db: Session, limit: int = 20) -> list[Item]:
    stmt = (
        select(Item)
        .where(Item.kind == KIND_GITHUB_REPO, Item.hidden.is_(False), Item.spike_delta > 0, Item.last_seen_at >= utcnow() - timedelta(days=10))
        .order_by(Item.spike_delta.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def releases(db: Session, days: int = 14, limit: int = 60) -> list[Item]:
    stmt = (
        select(Item)
        .where(Item.kind == KIND_GITHUB_RELEASE, Item.hidden.is_(False), Item.first_seen_at >= utcnow() - timedelta(days=days))
        .order_by(Item.published_at.desc().nullslast(), Item.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def ideas_today(db: Session, days: int = 2, limit: int = 40) -> list[Item]:
    stmt = (
        select(Item)
        .where(Item.hidden.is_(False), Item.enrich_status == ENRICH_DONE, Item.enriched_at >= utcnow() - timedelta(days=days))
        .order_by(Item.importance.desc(), Item.enriched_at.desc())
        .limit(limit)
    )
    return [it for it in db.scalars(stmt).all() if it.ideas]


def stats(db: Session) -> dict:
    now = utcnow()
    day = now - timedelta(days=1)
    total = db.scalar(select(func.count(Item.id)).where(Item.hidden.is_(False))) or 0
    today = db.scalar(select(func.count(Item.id)).where(Item.hidden.is_(False), Item.last_seen_at >= day)) or 0
    translated = db.scalar(select(func.count(Item.id)).where(Item.hidden.is_(False), Item.enrich_status == ENRICH_DONE)) or 0
    repos = db.scalar(select(func.count(Item.id)).where(Item.kind == KIND_GITHUB_REPO, Item.hidden.is_(False))) or 0
    return {"total": int(total), "last_24h": int(today), "translated": int(translated), "repos": int(repos)}


def related(db: Session, item: Item, limit: int = 6) -> list[Item]:
    stmt = select(Item).where(Item.id != item.id, Item.hidden.is_(False))
    if item.category:
        stmt = stmt.where(Item.category == item.category)
    elif item.language:
        stmt = stmt.where(Item.language == item.language)
    stmt = stmt.order_by(Item.importance.desc(), Item.last_seen_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def linked_items(db: Session, item: Item, limit: int = 8) -> list[Item]:
    """Other items (HN threads, articles, papers) that reference the same repository."""
    if not item.repo_full_name:
        return []
    stmt = (
        select(Item)
        .where(Item.id != item.id, Item.hidden.is_(False), func.lower(Item.repo_full_name) == item.repo_full_name.lower())
        .order_by(Item.last_seen_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def star_history(db: Session, repo_full_name: str, days: int = 30) -> list[tuple]:
    if not repo_full_name:
        return []
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(StarSnapshot.taken_at, StarSnapshot.stars)
        .where(StarSnapshot.repo_full_name == repo_full_name, StarSnapshot.taken_at >= since)
        .order_by(StarSnapshot.taken_at.asc())
    ).all()
    return [(r[0], r[1]) for r in rows]


def sparkline_svg(points: list[tuple], width: int = 600, height: int = 120) -> str:
    """Inline SVG line chart of (datetime, value) pairs; no external deps."""
    from app.utils import compact_number, jalali_date

    if len(points) < 2:
        return ""
    xs = [p[0].timestamp() for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 == x0:
        x1 = x0 + 1
    if y1 == y0:
        y1 = y0 + 1
    pad_l, pad_r, pad_t, pad_b = 8, 8, 10, 22
    W, H = width - pad_l - pad_r, height - pad_t - pad_b

    def sx(x):
        return pad_l + (x - x0) / (x1 - x0) * W

    def sy(y):
        return pad_t + H - (y - y0) / (y1 - y0) * H

    coords = [(sx(x), sy(y)) for x, y in zip(xs, ys)]
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)
    area = path + f" L {coords[-1][0]:.1f} {pad_t + H:.1f} L {coords[0][0]:.1f} {pad_t + H:.1f} Z"
    first_label = jalali_date(points[0][0])
    last_label = jalali_date(points[-1][0])
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="روند ستاره‌ها از {compact_number(y0)} تا {compact_number(y1)}" preserveAspectRatio="none">'
        f'<path d="{area}" fill="var(--accent-soft)" opacity=".6"/>'
        f'<path d="{path}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{coords[-1][0]:.1f}" cy="{coords[-1][1]:.1f}" r="4" fill="var(--accent)"/>'
        f'<text x="{pad_l}" y="{height - 6}" font-size="11" fill="var(--fg-muted)">{first_label} · ★{compact_number(ys[0])}</text>'
        f'<text x="{width - pad_r}" y="{height - 6}" font-size="11" text-anchor="end" fill="var(--fg-muted)">{last_label} · ★{compact_number(ys[-1])}</text>'
        "</svg>"
    )
