"""Daily editorial: one LLM call that turns today's top items into a short Persian column."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import get_providers
from app.llm.base import LLMError
from app.llm.enrich import extract_json, record_usage
from app.models import ENRICH_DONE, Editorial, Item, utcnow
from app.utils import truncate

log = logging.getLogger(__name__)

EDITORIAL_SYSTEM = """تو سردبیر یک خبرنامهٔ فارسی برای توسعه‌دهنده‌های ایرانی دربارهٔ هوش مصنوعی و تکنولوژی هستی.
از فهرست آیتم‌های امروز (که هر کدام خلاصهٔ فارسی دارند) یک «سرمقالهٔ روز» بنویس:
- title_fa: تیتر جذاب و دقیق (حداکثر ۸۰ نویسه)، بدون اغراق.
- body_fa: ۳ تا ۵ پاراگراف کوتاه (در کل ۱۸۰ تا ۳۲۰ کلمه) با لحن تحلیلی و روان: مهم‌ترین اتفاق امروز چیست و چرا، چه روندی دیده می‌شود، و برای توسعه‌دهندهٔ ایرانی چه فرصت یا هشداری دارد. به آیتم‌ها با نام محصول/ریپو (لاتین) اشاره کن. پاراگراف‌ها را با یک خط خالی جدا کن. ایموجی و فهرست بولت نگذار.
- picks: شناسهٔ (id) ۳ تا ۶ آیتمی که در سرمقاله برجسته کردی.
فقط JSON معتبر با کلیدهای title_fa, body_fa, picks برگردان؛ بدون code fence."""

EDITORIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "title_fa": {"type": "string"},
        "body_fa": {"type": "string"},
        "picks": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["title_fa", "body_fa", "picks"],
    "additionalProperties": False,
}


def latest_editorial(db: Session, max_age_days: int = 2) -> Editorial | None:
    since = date.today() - timedelta(days=max_age_days)
    return db.scalars(select(Editorial).where(Editorial.day >= since).order_by(Editorial.day.desc()).limit(1)).first()


def generate_editorial(db: Session, force: bool = False, hours: int = 26, max_items: int = 18) -> dict:
    today = date.today()
    existing = db.scalar(select(Editorial).where(Editorial.day == today))
    if existing is not None and not force:
        return {"ok": True, "message": "سرمقالهٔ امروز قبلاً تولید شده", "id": existing.id}
    providers = get_providers(db)
    if not providers:
        return {"ok": False, "error": "هیچ کلید LLM تنظیم نشده است"}
    since = utcnow() - timedelta(hours=hours)
    items = db.scalars(
        select(Item)
        .where(Item.hidden.is_(False), Item.enrich_status == ENRICH_DONE, Item.last_seen_at >= since)
        .order_by(Item.importance.desc(), Item.prescore.desc())
        .limit(max_items)
    ).all()
    if len(items) < 3:
        return {"ok": False, "error": "آیتم خلاصه‌شدهٔ کافی برای سرمقاله وجود ندارد"}
    payload = [
        {
            "id": it.id,
            "type": it.kind,
            "title": it.display_title,
            "repo": it.repo_full_name or None,
            "stars": it.stars or None,
            "growth_today": it.stars_delta_day or None,
            "importance": it.importance,
            "category": it.category,
            "summary": truncate(it.summary_fa, 500),
        }
        for it in items
    ]
    user = f"تاریخ: {today.isoformat()}\nآیتم‌های امروز:\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n\nخروجی JSON:"
    settings = get_settings()
    last_err = ""
    for provider in providers:
        try:
            resp = provider.complete(EDITORIAL_SYSTEM, user, max_tokens=min(settings.llm_max_output_tokens, 3000), json_schema=EDITORIAL_SCHEMA)
            data = extract_json(resp.text)
            if not isinstance(data, dict) or not data.get("body_fa"):
                raise ValueError("پاسخ ناقص")
        except (LLMError, ValueError, json.JSONDecodeError) as exc:
            last_err = f"{provider.name}: {exc}"
            record_usage(db, provider, None, 0, error=True)
            log.warning("editorial failed on %s: %s", provider.name, exc)
            continue
        record_usage(db, provider, resp, 0)
        picks = [int(p) for p in (data.get("picks") or []) if str(p).isdigit()][:6]
        if existing is None:
            existing = Editorial(day=today)
            db.add(existing)
        existing.title_fa = str(data.get("title_fa") or "").strip()[:200]
        existing.body_fa = str(data.get("body_fa") or "").strip()
        existing.item_ids = picks
        existing.model = f"{resp.provider}/{resp.model}"
        existing.created_at = utcnow()
        db.commit()
        return {"ok": True, "message": "سرمقاله تولید شد", "id": existing.id, "picks": picks}
    return {"ok": False, "error": last_err or "هیچ ارائه‌دهنده‌ای پاسخ نداد"}
