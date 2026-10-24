"""Bale / Telegram notifications: daily digest, editorial and instant alerts."""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ENRICH_DONE, Item, utcnow
from app.settings_store import get_setting
from app.utils import compact_number, fa_digits, jalali_date, truncate

log = logging.getLogger(__name__)

API_BASES = {
    "bale": "https://tapi.bale.ai/bot{token}",
    "telegram": "https://api.telegram.org/bot{token}",
}
MAX_LEN = 3900


def notify_configured(db: Session) -> bool:
    return bool(get_setting(db, "notify_bot_token", "")) and bool(get_setting(db, "notify_chat_id", ""))


def send_message(db: Session, text: str) -> dict:
    provider = str(get_setting(db, "notify_provider", "bale")).lower()
    token = get_setting(db, "notify_bot_token", "")
    chat_id = get_setting(db, "notify_chat_id", "")
    if not token or not chat_id:
        return {"ok": False, "message": "توکن یا chat_id تنظیم نشده"}
    base = API_BASES.get(provider, API_BASES["bale"]).format(token=token)
    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(f"{base}/sendMessage", json={"chat_id": chat_id, "text": text[:MAX_LEN], "disable_web_page_preview": True})
        if r.status_code != 200:
            return {"ok": False, "message": f"HTTP {r.status_code}: {r.text[:200]}"}
        return {"ok": True, "message": "ارسال شد"}
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"خطای شبکه: {exc}"}


def _site(db: Session) -> str:
    return str(get_setting(db, "site_url", get_settings().site_url)).rstrip("/")


def _item_line(db: Session, i: int, it: Item) -> list[str]:
    meta = []
    if it.stars:
        meta.append(f"★ {compact_number(it.stars)}")
    if it.stars_delta_day:
        meta.append(f"+{compact_number(it.stars_delta_day)} امروز")
    if it.spike_delta:
        meta.append(f"جهش +{compact_number(it.spike_delta)}")
    if it.points and it.kind == "hackernews":
        meta.append(f"{fa_digits(it.points)} امتیاز HN")
    head = f"{fa_digits(i)}. {it.display_title}" + (f" ({'، '.join(meta)})" if meta else "")
    lines = [head]
    if it.summary_fa:
        lines.append("   " + truncate(it.summary_fa, 240))
    lines.append(f"   {_site(db)}/item/{it.id}")
    lines.append("")
    return lines


def build_digest(db: Session, hours: int = 24, limit: int | None = None) -> str:
    from app.llm.editorial import latest_editorial

    settings = get_settings()
    limit = limit or int(get_setting(db, "digest_items", settings.digest_items))
    since = utcnow() - timedelta(hours=hours)
    items = db.scalars(
        select(Item)
        .where(Item.hidden.is_(False), Item.last_seen_at >= since, Item.enrich_status == ENRICH_DONE)
        .order_by(Item.importance.desc(), Item.prescore.desc())
        .limit(limit)
    ).all()
    lines = [f"📡 {settings.site_name} — {jalali_date(utcnow())}", ""]
    ed = latest_editorial(db, max_age_days=1)
    if ed is not None and ed.body_fa:
        lines.append(f"✍️ {ed.title_fa}")
        lines.append(truncate(ed.body_fa, 900))
        lines.append("")
    if not items:
        lines.append("امروز آیتم ترجمه‌شده‌ای نداریم.")
    for i, it in enumerate(items, start=1):
        lines.extend(_item_line(db, i, it))
    lines.append(f"همهٔ خبرها: {_site(db)}/")
    return "\n".join(lines).strip()


def send_daily_digest(db: Session) -> dict:
    if not notify_configured(db):
        return {"ok": False, "message": "اعلان پیکربندی نشده"}
    return send_message(db, build_digest(db))


def send_alerts(db: Session) -> dict:
    """Instant alert for freshly enriched items above the importance threshold."""
    if not notify_configured(db):
        return {"sent": 0, "skipped": "notify off"}
    threshold = int(get_setting(db, "alert_min_importance", get_settings().alert_min_importance))
    if threshold <= 0 or threshold > 10:
        return {"sent": 0, "skipped": "alerts off"}
    since = utcnow() - timedelta(hours=12)
    items = db.scalars(
        select(Item)
        .where(Item.hidden.is_(False), Item.enrich_status == ENRICH_DONE, Item.importance >= threshold, Item.alerted_at.is_(None), Item.enriched_at >= since)
        .order_by(Item.importance.desc())
        .limit(5)
    ).all()
    sent = 0
    for it in items:
        text = "\n".join(["🔔 خبر مهم", *_item_line(db, it.importance, it)]).replace(f"{fa_digits(it.importance)}. ", f"[{fa_digits(it.importance)}/۱۰] ", 1)
        res = send_message(db, text)
        it.alerted_at = utcnow()
        if res["ok"]:
            sent += 1
        else:
            log.warning("alert failed: %s", res["message"])
            break
    db.commit()
    return {"sent": sent, "candidates": len(items)}
