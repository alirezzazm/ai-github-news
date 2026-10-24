"""Star-history based spike detection."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.prescore import compute_prescore
from app.models import ENRICH_DONE, ENRICH_PENDING, KIND_GITHUB_REPO, Item, StarSnapshot, utcnow

log = logging.getLogger(__name__)

WINDOW_DAYS = 7
MIN_DELTA = 300
MIN_RATIO = 0.25


def detect_spike(history: list[tuple], now=None) -> tuple[int, float] | None:
    """history: list of (taken_at, stars) sorted ascending. Returns (delta, ratio) or None."""
    if len(history) < 2:
        return None
    now = now or utcnow()
    cutoff = now - timedelta(days=WINDOW_DAYS)
    window = [h for h in history if h[0] >= cutoff]
    if len(window) < 2:
        return None
    base = window[0][1]
    latest = window[-1][1]
    delta = latest - base
    ratio = delta / max(base, 50)
    if delta >= MIN_DELTA and ratio >= MIN_RATIO:
        return delta, round(ratio, 3)
    return None


def check_spikes(db: Session) -> int:
    now = utcnow()
    since = now - timedelta(days=WINDOW_DAYS)
    repos = db.scalars(
        select(Item).where(Item.kind == KIND_GITHUB_REPO, Item.last_seen_at >= since, Item.hidden.is_(False))
    ).all()
    flagged = 0
    for it in repos:
        snaps = db.execute(
            select(StarSnapshot.taken_at, StarSnapshot.stars)
            .where(StarSnapshot.repo_full_name == it.repo_full_name, StarSnapshot.taken_at >= since)
            .order_by(StarSnapshot.taken_at.asc())
        ).all()
        hit = detect_spike([(s[0], s[1]) for s in snaps], now)
        if hit is None and (it.stars_delta_day or 0) >= 500:
            hit = (it.stars_delta_day, round(it.stars_delta_day / max(it.stars - it.stars_delta_day, 50), 3))
        if hit is None:
            continue
        delta, ratio = hit
        flags = list(it.flags or [])
        newly = "spike" not in flags
        if newly:
            flags.append("spike")
            it.flags = flags
        it.spike_delta = int(delta)
        it.spike_ratio = float(ratio)
        it.prescore = compute_prescore(it, it.source)
        if newly:
            flagged += 1
            it.last_seen_at = now
            if it.enrich_status != ENRICH_DONE:
                it.enrich_status = ENRICH_PENDING
    db.commit()
    return flagged
