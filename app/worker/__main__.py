"""Worker process: APScheduler + command queue poller.

Run with ``python -m app.worker``.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.collectors.seed import seed_sources
from app.config import get_settings
from app.db import init_db, session_scope
from app.settings_store import get_setting
from app.worker import jobs

log = logging.getLogger("worker")


def _digest_hour() -> int:
    with session_scope() as db:
        return int(get_setting(db, "digest_hour", get_settings().digest_hour))


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    init_db()
    with session_scope() as db:
        added = seed_sources(db)
        if added:
            log.info("seeded %d default sources", added)

    sched = BackgroundScheduler(timezone=settings.timezone, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    m = 60
    sched.add_job(jobs.job_collect_github, IntervalTrigger(seconds=settings.collect_github_every_min * m), id="collect_github", name="GitHub trending+search")
    sched.add_job(jobs.job_collect_releases, IntervalTrigger(seconds=settings.collect_releases_every_min * m), id="collect_releases", name="GitHub releases")
    sched.add_job(jobs.job_collect_hn, IntervalTrigger(seconds=settings.collect_hn_every_min * m), id="collect_hn", name="Hacker News")
    sched.add_job(jobs.job_collect_rss, IntervalTrigger(seconds=settings.collect_rss_every_min * m), id="collect_rss", name="RSS")
    sched.add_job(jobs.job_spikes, IntervalTrigger(seconds=settings.spike_check_every_min * m), id="spikes", name="Star spikes")
    sched.add_job(jobs.job_enrich, IntervalTrigger(seconds=settings.enrich_every_min * m), id="enrich", name="LLM enrichment")
    sched.add_job(jobs.job_track_stars, CronTrigger(hour=2, minute=15), id="track_stars", name="Star tracker")
    sched.add_job(jobs.job_editorial, CronTrigger(hour=max(0, _digest_hour() - 1), minute=30), id="editorial", name="Daily editorial")
    sched.add_job(jobs.job_digest, CronTrigger(hour=_digest_hour(), minute=0), id="digest", name="Daily digest")
    sched.add_job(jobs.job_cleanup, CronTrigger(hour=4, minute=20), id="cleanup", name="Cleanup")
    sched.start()
    log.info("scheduler started (%d jobs); tz=%s", len(sched.get_jobs()), settings.timezone)

    # Commands interrupted by a restart go back to the queue
    with session_scope() as db:
        from sqlalchemy import select

        from app.models import Command

        for cmd in db.scalars(select(Command).where(Command.status == "running")).all():
            cmd.status = "queued"
            cmd.started_at = None
            log.info("re-queued interrupted command %s (#%d)", cmd.name, cmd.id)
        from app.models import RunLog, utcnow

        for run in db.scalars(select(RunLog).where(RunLog.status == "running")).all():
            run.status = "error"
            run.message = "interrupted by worker restart"
            run.finished_at = utcnow()

    # First full cycle shortly after boot if the DB is empty-ish
    with session_scope() as db:
        from sqlalchemy import func, select

        from app.models import Item

        count = db.scalar(select(func.count(Item.id))) or 0
    if count == 0:
        log.info("empty database -> queuing initial full cycle")
        with session_scope() as db:
            from app.models import Command

            db.add(Command(name="full_cycle", payload={}))

    running = {"on": True}

    def _stop(*_):
        running["on"] = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    poll = max(5, settings.command_poll_seconds)
    heartbeat = Path(os.environ.get("WORKER_HEARTBEAT_FILE", "/tmp/worker.heartbeat"))
    while running["on"]:
        try:
            heartbeat.touch()
        except OSError:
            pass
        try:
            n = jobs.process_commands()
            if n:
                log.info("processed %d command(s)", n)
        except Exception as exc:  # keep the loop alive
            log.error("command loop error: %s", exc)
        for _ in range(poll):
            if not running["on"]:
                break
            time.sleep(1)
    sched.shutdown(wait=False)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
