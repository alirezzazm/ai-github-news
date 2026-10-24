"""Default sources inserted on first run (idempotent)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.github_releases import DEFAULT_WATCH
from app.collectors.github_search import DEFAULT_QUERIES
from app.collectors.rss import DEFAULT_FEEDS
from app.models import SRC_HF, SRC_HN, SRC_RELEASES, SRC_RSS, SRC_SEARCH, SRC_TRENDING, Source


def seed_sources(db: Session) -> int:
    existing = {s.key for s in db.scalars(select(Source)).all()}
    added = 0
    defaults: list[Source] = [
        Source(
            key="github_trending",
            name="GitHub Trending (روزانه/هفتگی/ماهانه)",
            kind=SRC_TRENDING,
            config={"periods": ["daily", "weekly", "monthly"]},
            weight=1.0,
        ),
        Source(
            key="github_search",
            name="GitHub Search (AI / LLM / Agents …)",
            kind=SRC_SEARCH,
            config={"queries": DEFAULT_QUERIES, "modes": ["new", "active"], "per_page": 30},
            weight=1.0,
        ),
        Source(
            key="github_releases",
            name="ریلیز ریپوهای مهم",
            kind=SRC_RELEASES,
            config={"repos": DEFAULT_WATCH, "per_page": 5},
            weight=1.0,
        ),
        Source(
            key="hackernews",
            name="Hacker News (top/best)",
            kind=SRC_HN,
            config={"ai_only": False},
            weight=1.0,
        ),
        Source(
            key="huggingface",
            name="Hugging Face (مدل‌های ترند + مقاله‌های روز)",
            kind=SRC_HF,
            config={"models": 30, "papers": 30},
            weight=1.0,
        ),
    ]
    for f in DEFAULT_FEEDS:
        defaults.append(
            Source(
                key=f["key"],
                name=f["name"],
                kind=SRC_RSS,
                config={"url": f["url"], "max_items": f.get("max_items", 40)},
                weight=f.get("weight", 1.0),
                enabled=f.get("enabled", True),
            )
        )
    for s in defaults:
        if s.key not in existing:
            db.add(s)
            added += 1
    db.commit()
    return added
