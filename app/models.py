"""ORM models."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Item kinds
KIND_GITHUB_REPO = "github_repo"  # trending / search / spike (one item per repo)
KIND_GITHUB_RELEASE = "github_release"
KIND_HACKERNEWS = "hackernews"
KIND_RSS = "rss"
KIND_HF_MODEL = "hf_model"
KIND_HF_PAPER = "hf_paper"
ITEM_KINDS = [KIND_GITHUB_REPO, KIND_GITHUB_RELEASE, KIND_HACKERNEWS, KIND_RSS, KIND_HF_MODEL, KIND_HF_PAPER]

# Source kinds
SRC_TRENDING = "github_trending"
SRC_SEARCH = "github_search"
SRC_RELEASES = "github_releases"
SRC_HN = "hackernews"
SRC_RSS = "rss"
SRC_HF = "huggingface"

# Enrichment states
ENRICH_PENDING = "pending"
ENRICH_DONE = "done"
ENRICH_SKIPPED = "skipped"  # below threshold / over budget
ENRICH_FAILED = "failed"
ENRICH_NONE = "none"  # no LLM configured

CATEGORIES: dict[str, str] = {
    "llm": "مدل زبانی",
    "agent": "ایجنت",
    "devtools": "ابزار توسعه",
    "vision": "بینایی ماشین",
    "audio": "صدا و گفتار",
    "data": "داده و زیرساخت",
    "security": "امنیت",
    "robotics": "رباتیک",
    "science": "علم و پژوهش",
    "web": "وب و موبایل",
    "business": "کسب‌وکار و صنعت",
    "other": "دیگر",
}


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    items_last_run: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    items: Mapped[list["Item"]] = relationship(back_populates="source")


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    external_id: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True, index=True)
    source_label: Mapped[str] = mapped_column(String(120), default="")

    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str] = mapped_column(Text, default="")
    readme_excerpt: Mapped[str] = mapped_column(Text, default="")

    # enrichment (LLM)
    title_fa: Mapped[str] = mapped_column(Text, default="")
    summary_fa: Mapped[str] = mapped_column(Text, default="")
    readme_summary_fa: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(30), default="", index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    ideas: Mapped[list] = mapped_column(JSON, default=list)
    importance: Mapped[int] = mapped_column(Integer, default=0, index=True)
    prescore: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    enrich_status: Mapped[str] = mapped_column(String(12), default=ENRICH_PENDING, index=True)
    enrich_error: Mapped[str] = mapped_column(Text, default="")
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enrich_model: Mapped[str] = mapped_column(String(80), default="")

    # github specifics
    repo_full_name: Mapped[str] = mapped_column(String(200), default="", index=True)
    language: Mapped[str] = mapped_column(String(60), default="", index=True)
    stars: Mapped[int] = mapped_column(Integer, default=0, index=True)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    stars_delta_day: Mapped[int] = mapped_column(Integer, default=0)
    stars_delta_week: Mapped[int] = mapped_column(Integer, default=0)
    stars_delta_month: Mapped[int] = mapped_column(Integer, default=0)
    spike_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    spike_delta: Mapped[int] = mapped_column(Integer, default=0)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    release_tag: Mapped[str] = mapped_column(String(120), default="")
    repo_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    repo_pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # hn / rss specifics
    points: Mapped[int] = mapped_column(Integer, default=0)
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    comments_url: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")

    flags: Mapped[list] = mapped_column(JSON, default=list)  # trending_daily, spike, search:llm ...
    rank: Mapped[int] = mapped_column(Integer, default=0)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)

    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    source: Mapped[Source | None] = relationship(back_populates="items")

    @property
    def is_translated(self) -> bool:
        return self.enrich_status == ENRICH_DONE and bool(self.summary_fa)

    @property
    def display_title(self) -> str:
        return self.title_fa or self.title

    @property
    def category_fa(self) -> str:
        return CATEGORIES.get(self.category or "", "")


Index("ix_items_kind_lastseen", Item.kind, Item.last_seen_at)
Index("ix_items_hidden_importance", Item.hidden, Item.importance)


class StarSnapshot(Base):
    __tablename__ = "star_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(String(200), index=True)
    stars: Mapped[int] = mapped_column(Integer)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    taken_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


Index("ix_snap_repo_time", StarSnapshot.repo_full_name, StarSnapshot.taken_at)


class HttpCache(Base):
    """ETag / Last-Modified memory for conditional requests."""

    __tablename__ = "http_cache"
    url: Mapped[str] = mapped_column(String(600), primary_key=True)
    etag: Mapped[str] = mapped_column(String(300), default="")
    last_modified: Mapped[str] = mapped_column(String(100), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LlmUsage(Base):
    __tablename__ = "llm_usage"
    __table_args__ = (UniqueConstraint("day", "provider", "model", name="uq_usage_day_provider_model"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    requests: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class RunLog(Base):
    __tablename__ = "run_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(60), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|ok|error
    message: Mapped[str] = mapped_column(Text, default="")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


class Command(Base):
    """Commands queued by the web process and executed by the worker."""

    __tablename__ = "commands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|done|error
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Editorial(Base):
    """LLM-written daily editorial shown on the home page and sent as digest."""

    __tablename__ = "editorials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True, index=True)
    title_fa: Mapped[str] = mapped_column(Text, default="")
    body_fa: Mapped[str] = mapped_column(Text, default="")
    item_ids: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
