from datetime import timedelta

from sqlalchemy import func, select

from app.collectors.base import RawItem, ingest
from app.collectors.seed import seed_sources
from app.collectors.stars import check_spikes, detect_spike
from app.models import ENRICH_PENDING, KIND_GITHUB_REPO, KIND_HACKERNEWS, Item, Source, StarSnapshot, utcnow


def _repo(**kw) -> RawItem:
    base = dict(
        kind=KIND_GITHUB_REPO,
        external_id="gh:acme/widget",
        url="https://github.com/acme/widget",
        title="acme/widget",
        original_text="A widget",
        repo_full_name="acme/widget",
        language="Python",
        stars=1000,
        forks=10,
        flags=["trending_daily"],
    )
    base.update(kw)
    return RawItem(**base)


def test_ingest_dedupes_by_external_id(db):
    seed_sources(db)
    src = db.scalar(select(Source).where(Source.key == "github_trending"))
    r1 = ingest(db, src, [_repo(), _repo()])  # duplicate inside one batch
    db.commit()
    assert r1.created == 1 and r1.updated == 0
    r2 = ingest(db, src, [_repo(stars=1500, flags=["trending_weekly"], stars_delta_week=400)])
    db.commit()
    assert r2.created == 0 and r2.updated == 1
    assert db.scalar(select(func.count(Item.id))) == 1
    item = db.scalar(select(Item))
    assert item.stars == 1500
    assert set(item.flags) == {"trending_daily", "trending_weekly"}
    assert item.stars_delta_week == 400
    assert item.enrich_status == ENRICH_PENDING
    assert item.prescore > 0
    # snapshot rule: one row per 6h window, value refreshed
    snaps = db.scalars(select(StarSnapshot)).all()
    assert len(snaps) == 1 and snaps[0].stars == 1500


def test_ingest_links_news_to_repo(db):
    hn = RawItem(
        kind=KIND_HACKERNEWS,
        external_id="hn:1",
        url="https://github.com/acme/widget/blob/main/README.md",
        title="Show HN: Widget",
        points=300,
        comments_count=40,
    )
    ingest(db, None, [hn])
    db.commit()
    item = db.scalar(select(Item))
    assert item.repo_full_name == "acme/widget"
    assert "links_repo" in item.flags


def test_detect_spike_rules():
    now = utcnow()
    hist = [(now - timedelta(days=6), 1000), (now - timedelta(days=3), 1200), (now, 1700)]
    assert detect_spike(hist, now) == (700, 0.7)
    flat = [(now - timedelta(days=6), 1000), (now, 1100)]
    assert detect_spike(flat, now) is None  # +100 < MIN_DELTA
    old = [(now - timedelta(days=20), 100), (now, 5000)]
    assert detect_spike(old, now) is None  # outside the 7-day window
    assert detect_spike([(now, 10)], now) is None


def test_check_spikes_flags_items(db):
    ingest(db, None, [_repo(stars=5000)])
    db.commit()
    item = db.scalar(select(Item))
    db.add(StarSnapshot(repo_full_name="acme/widget", stars=3000, taken_at=utcnow() - timedelta(days=5)))
    db.commit()
    flagged = check_spikes(db)
    assert flagged == 1
    db.refresh(item)
    assert "spike" in item.flags and item.spike_delta == 2000
    # second run does not re-flag
    assert check_spikes(db) == 0
