"""Job implementations shared by the scheduler and the admin command queue."""
from __future__ import annotations

import logging
import traceback
from datetime import timedelta
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.collectors import run_kinds, run_source
from app.collectors.star_tracker import track_stars
from app.collectors.stars import check_spikes
from app.config import get_settings
from app.db import session_scope
from app.llm.editorial import generate_editorial
from app.llm.enrich import run_enrichment
from app.models import (
    SRC_HN,
    SRC_RELEASES,
    SRC_RSS,
    SRC_SEARCH,
    SRC_TRENDING,
    Command,
    HttpCache,
    Item,
    RunLog,
    Source,
    StarSnapshot,
    utcnow,
)
from app.notify import send_alerts, send_daily_digest

log = logging.getLogger(__name__)


def _logged(job: str, fn: Callable[[Session], dict]) -> dict:
    """Run fn inside a session and record a RunLog row."""
    with session_scope() as db:
        run = RunLog(job=job, status="running")
        db.add(run)
        db.commit()
        run_id = run.id
    stats: dict = {}
    status, message = "ok", ""
    try:
        with session_scope() as db:
            stats = fn(db) or {}
            if stats.get("error"):
                status = "warn"
                message = str(stats["error"])
    except Exception as exc:
        status = "error"
        message = f"{exc.__class__.__name__}: {exc}"
        log.error("job %s failed: %s\n%s", job, exc, traceback.format_exc())
    with session_scope() as db:
        run = db.get(RunLog, run_id)
        if run is not None:
            run.finished_at = utcnow()
            run.status = status
            run.message = message[:2000]
            run.stats = _jsonable(stats)
    return stats


def _jsonable(obj):
    import json

    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return json.loads(json.dumps(obj, default=str))


# --------------------------------------------------------------------------- jobs
def job_collect_github() -> dict:
    return _logged("collect_github", lambda db: run_kinds(db, [SRC_TRENDING, SRC_SEARCH]))


def job_collect_releases() -> dict:
    return _logged("collect_releases", lambda db: run_kinds(db, [SRC_RELEASES]))


def job_collect_hn() -> dict:
    return _logged("collect_hn", lambda db: run_kinds(db, [SRC_HN]))


def job_collect_rss() -> dict:
    return _logged("collect_rss", lambda db: run_kinds(db, [SRC_RSS]))


def job_collect_all() -> dict:
    return _logged("collect_all", lambda db: run_kinds(db, None))


def job_collect_source(source_id: int) -> dict:
    def _run(db: Session) -> dict:
        src = db.get(Source, source_id)
        if src is None:
            return {"error": "source not found"}
        res = run_source(db, src)
        return {"created": res.created, "updated": res.updated, "status": src.last_status, "error": src.last_error or ""}

    return _logged("collect_source", _run)


def job_spikes() -> dict:
    return _logged("spikes", lambda db: {"flagged": check_spikes(db)})


def job_enrich(item_ids: list[int] | None = None, force: bool = False, max_items: int | None = None) -> dict:
    def _run(db: Session) -> dict:
        stats = run_enrichment(db, item_ids=item_ids, force=force, max_items=max_items)
        if stats.get("enriched"):
            try:
                stats["alerts"] = send_alerts(db)
            except Exception as exc:  # alerts are best-effort
                stats["alerts"] = {"error": str(exc)[:200]}
        return stats

    return _logged("enrich", _run)


def job_track_stars() -> dict:
    stats = _logged("track_stars", lambda db: track_stars(db))
    stats["spikes"] = job_spikes()
    return stats


def job_editorial(force: bool = False) -> dict:
    def _run(db: Session) -> dict:
        res = generate_editorial(db, force=force)
        if not res.get("ok"):
            res["error"] = res.get("error") or res.get("message")
        return res

    return _logged("editorial", _run)


def job_digest() -> dict:
    return _logged("digest", lambda db: send_daily_digest(db))


def job_cleanup() -> dict:
    def _run(db: Session) -> dict:
        settings = get_settings()
        cutoff = utcnow() - timedelta(days=settings.item_retention_days)
        removed = db.execute(delete(Item).where(Item.last_seen_at < cutoff, Item.importance < 8)).rowcount
        snaps = db.execute(delete(StarSnapshot).where(StarSnapshot.taken_at < utcnow() - timedelta(days=60))).rowcount
        cache = db.execute(delete(HttpCache).where(HttpCache.fetched_at < utcnow() - timedelta(days=30))).rowcount
        logs = db.execute(delete(RunLog).where(RunLog.started_at < utcnow() - timedelta(days=30))).rowcount
        cmds = db.execute(delete(Command).where(Command.created_at < utcnow() - timedelta(days=7))).rowcount
        return {"items": removed, "snapshots": snaps, "http_cache": cache, "run_logs": logs, "commands": cmds}

    return _logged("cleanup", _run)


def job_full_cycle() -> dict:
    """Collect everything, detect spikes, then enrich (used by 'run now')."""
    stats = {"collect": job_collect_all(), "stars": job_track_stars(), "enrich": job_enrich(), "editorial": job_editorial()}
    return stats


# --------------------------------------------------------------------------- command queue
COMMANDS: dict[str, Callable[[dict], dict]] = {
    "collect_all": lambda p: job_collect_all(),
    "collect_github": lambda p: job_collect_github(),
    "collect_releases": lambda p: job_collect_releases(),
    "collect_hn": lambda p: job_collect_hn(),
    "collect_rss": lambda p: job_collect_rss(),
    "collect_source": lambda p: job_collect_source(int(p["source_id"])),
    "spikes": lambda p: job_spikes(),
    "enrich": lambda p: job_enrich(p.get("item_ids"), bool(p.get("force")), p.get("max_items")),
    "digest": lambda p: job_digest(),
    "track_stars": lambda p: job_track_stars(),
    "editorial": lambda p: job_editorial(bool(p.get("force", True))),
    "full_cycle": lambda p: job_full_cycle(),
    "cleanup": lambda p: job_cleanup(),
}


def process_commands() -> int:
    """Execute queued commands one at a time. Returns number processed."""
    processed = 0
    while True:
        with session_scope() as db:
            cmd = db.scalars(select(Command).where(Command.status == "queued").order_by(Command.id).limit(1)).first()
            if cmd is None:
                return processed
            cmd.status = "running"
            cmd.started_at = utcnow()
            cmd_id, name, payload = cmd.id, cmd.name, dict(cmd.payload or {})
        fn = COMMANDS.get(name)
        result = ""
        status = "done"
        try:
            if fn is None:
                raise ValueError(f"unknown command {name}")
            out = fn(payload)
            import json

            result = json.dumps(_jsonable(out), ensure_ascii=False)[:4000]
        except Exception as exc:
            status = "error"
            result = f"{exc.__class__.__name__}: {exc}"
            log.error("command %s failed: %s", name, exc)
        with session_scope() as db:
            cmd = db.get(Command, cmd_id)
            if cmd is not None:
                cmd.status = status
                cmd.result = result
                cmd.finished_at = utcnow()
        processed += 1
