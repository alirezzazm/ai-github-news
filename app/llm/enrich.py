"""Enrichment pipeline: pick items -> fetch details -> LLM -> store."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.github_details import fetch_details
from app.config import get_settings
from app.llm import get_providers
from app.llm.base import LLMError, LLMProvider, LLMResponse
from app.llm.prompts import JSON_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from app.models import (
    CATEGORIES,
    ENRICH_DONE,
    ENRICH_FAILED,
    ENRICH_NONE,
    ENRICH_PENDING,
    ENRICH_SKIPPED,
    KIND_GITHUB_RELEASE,
    KIND_GITHUB_REPO,
    KIND_HACKERNEWS,
    KIND_HF_MODEL,
    KIND_HF_PAPER,
    KIND_RSS,
    Item,
    LlmUsage,
    utcnow,
)
from app.settings_store import get_setting
from app.utils import truncate

log = logging.getLogger(__name__)

KIND_FA = {
    KIND_GITHUB_REPO: "ریپوی گیت‌هاب",
    KIND_GITHUB_RELEASE: "ریلیز گیت‌هاب",
    KIND_HACKERNEWS: "خبر Hacker News",
    KIND_RSS: "مقاله/پست",
    KIND_HF_MODEL: "مدل Hugging Face",
    KIND_HF_PAPER: "مقالهٔ پژوهشی (Hugging Face Papers)",
}


# --------------------------------------------------------------------------- parsing
def extract_json(text: str) -> dict | list:
    """Tolerant JSON extraction (code fences, leading prose, trailing commas)."""
    if not text:
        raise ValueError("empty response")
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start_obj, start_arr = s.find("{"), s.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if not starts:
        raise ValueError("no JSON found")
    start = min(starts)
    end = max(s.rfind("}"), s.rfind("]"))
    candidate = s[start : end + 1]
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)  # trailing commas
    return json.loads(candidate)


def normalise_result(data: dict | list) -> dict[int, dict]:
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("items missing")
    out: dict[int, dict] = {}
    for entry in items:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        try:
            iid = int(entry["id"])
        except (TypeError, ValueError):
            continue
        cat = str(entry.get("category") or "other").strip().lower()
        if cat not in CATEGORIES:
            cat = "other"
        try:
            imp = int(entry.get("importance") or 5)
        except (TypeError, ValueError):
            imp = 5
        imp = max(1, min(10, imp))
        tags = [str(t).strip() for t in (entry.get("tags") or []) if str(t).strip()][:8]
        ideas = []
        for idea in entry.get("ideas") or []:
            if isinstance(idea, dict) and idea.get("title"):
                ideas.append(
                    {
                        "title": str(idea.get("title", "")).strip()[:140],
                        "description": str(idea.get("description", "")).strip()[:600],
                        "stack": str(idea.get("stack", "")).strip()[:120],
                    }
                )
            elif isinstance(idea, str) and idea.strip():
                ideas.append({"title": idea.strip()[:140], "description": "", "stack": ""})
        out[iid] = {
            "title_fa": str(entry.get("title_fa") or "").strip()[:200],
            "summary_fa": str(entry.get("summary_fa") or "").strip(),
            "readme_summary_fa": str(entry.get("readme_summary_fa") or "").strip(),
            "category": cat,
            "tags": tags,
            "importance": imp,
            "ideas": ideas[:4],
        }
    return out


# --------------------------------------------------------------------------- payload
def item_payload(it: Item) -> dict:
    p: dict = {
        "id": it.id,
        "type": KIND_FA.get(it.kind, it.kind),
        "title": it.title,
        "url": it.url,
        "text": truncate(it.original_text, 2500),
    }
    if it.kind in (KIND_GITHUB_REPO, KIND_GITHUB_RELEASE):
        p["repo"] = it.repo_full_name
        p["stars"] = it.stars
        if it.language:
            p["language"] = it.language
        if it.topics:
            p["topics"] = it.topics[:10]
        if it.stars_delta_day:
            p["stars_today"] = it.stars_delta_day
        if it.stars_delta_week:
            p["stars_this_week"] = it.stars_delta_week
        if "spike" in (it.flags or []):
            p["note"] = f"جهش ستاره: +{it.spike_delta} در یک هفته"
        if it.release_tag:
            p["release_tag"] = it.release_tag
        if it.readme_excerpt:
            p["readme"] = truncate(it.readme_excerpt, 3500)
    elif it.kind == KIND_HACKERNEWS:
        p["points"] = it.points
        p["comments"] = it.comments_count
    elif it.kind == KIND_RSS:
        p["source"] = it.source_label
        if it.published_at:
            p["published"] = it.published_at.date().isoformat()
    elif it.kind == KIND_HF_MODEL:
        p["likes"] = it.points
        p["downloads"] = it.comments_count
        if it.topics:
            p["tags"] = it.topics[:10]
    elif it.kind == KIND_HF_PAPER:
        p["upvotes"] = it.points
        if it.topics:
            p["keywords"] = it.topics[:10]
    if it.kind != KIND_GITHUB_REPO and it.repo_full_name and "repo" not in p:
        p["repo"] = it.repo_full_name
    return p


# --------------------------------------------------------------------------- usage/budget
def _usage_row(db: Session, provider: str, model: str) -> LlmUsage:
    today = date.today()
    row = db.scalar(select(LlmUsage).where(LlmUsage.day == today, LlmUsage.provider == provider, LlmUsage.model == model))
    if row is None:
        row = LlmUsage(day=today, provider=provider, model=model)
        db.add(row)
        db.flush()
    return row


def today_totals(db: Session) -> tuple[int, int]:
    """(items enriched today, tokens used today)"""
    today = date.today()
    row = db.execute(
        select(func.coalesce(func.sum(LlmUsage.items), 0), func.coalesce(func.sum(LlmUsage.input_tokens + LlmUsage.output_tokens), 0)).where(
            LlmUsage.day == today
        )
    ).one()
    return int(row[0]), int(row[1])


def record_usage(db: Session, provider: LLMProvider, resp: LLMResponse | None, items: int, error: bool = False) -> None:
    row = _usage_row(db, provider.name, resp.model if resp else provider.model)
    row.requests += 1
    if error:
        row.errors += 1
    if resp is not None:
        row.input_tokens += resp.input_tokens
        row.output_tokens += resp.output_tokens
        row.items += items
        row.cost_usd = round(row.cost_usd + provider.estimate_cost(resp.input_tokens, resp.output_tokens), 6)
    db.commit()


# --------------------------------------------------------------------------- main
def select_pending(db: Session, limit: int, min_prescore: float, item_ids: list[int] | None = None) -> list[Item]:
    q = select(Item).where(Item.hidden.is_(False))
    if item_ids:
        q = q.where(Item.id.in_(item_ids))
    else:
        recent = utcnow() - timedelta(days=3)
        q = q.where(Item.enrich_status.in_([ENRICH_PENDING, ENRICH_NONE]), Item.last_seen_at >= recent, Item.prescore >= min_prescore)
    q = q.order_by(Item.prescore.desc(), Item.last_seen_at.desc()).limit(limit)
    return list(db.scalars(q).all())


def enrich_batch(db: Session, providers: list[LLMProvider], items: list[Item], max_tokens: int) -> tuple[int, str]:
    """Enrich one batch, trying providers in order. Returns (ok_count, error_message)."""
    payload = [item_payload(it) for it in items]
    user = build_user_prompt(payload)
    last_err = ""
    for provider in providers:
        for attempt in range(2):
            try:
                resp = provider.complete(SYSTEM_PROMPT, user, max_tokens=max_tokens, json_schema=JSON_SCHEMA)
                parsed = normalise_result(extract_json(resp.text))
            except LLMError as exc:
                last_err = f"{provider.name}: {exc}"
                log.warning("LLM error (%s, attempt %d): %s", provider.name, attempt + 1, exc)
                record_usage(db, provider, None, 0, error=True)
                if exc.retryable and attempt == 0:
                    time.sleep(5)
                    continue
                break  # next provider
            except (ValueError, json.JSONDecodeError) as exc:
                last_err = f"{provider.name}: خروجی JSON نامعتبر ({exc})"
                log.warning("bad JSON from %s: %s", provider.name, exc)
                record_usage(db, provider, None, 0, error=True)
                if attempt == 0:
                    continue
                break
            ok = 0
            now = utcnow()
            for it in items:
                data = parsed.get(it.id)
                if not data or not data["summary_fa"]:
                    it.enrich_status = ENRICH_FAILED
                    it.enrich_error = "پاسخ مدل برای این آیتم خالی بود"
                    continue
                it.title_fa = data["title_fa"]
                it.summary_fa = data["summary_fa"]
                it.readme_summary_fa = data["readme_summary_fa"]
                it.category = data["category"]
                it.tags = data["tags"]
                it.importance = data["importance"]
                it.ideas = data["ideas"]
                it.enrich_status = ENRICH_DONE
                it.enrich_error = ""
                it.enriched_at = now
                it.enrich_model = f"{resp.provider}/{resp.model}"
                ok += 1
            record_usage(db, provider, resp, ok)
            return ok, ""
    return 0, last_err or "هیچ ارائه‌دهنده‌ای پاسخ نداد"


def run_enrichment(db: Session, item_ids: list[int] | None = None, force: bool = False, max_items: int | None = None) -> dict:
    """Entry point used by the scheduler and the admin panel."""
    settings = get_settings()
    providers = get_providers(db)
    stats = {"selected": 0, "enriched": 0, "failed": 0, "skipped": 0, "batches": 0, "error": ""}
    if not providers:
        # mark pending as "none" so UI shows the "ترجمه نشده" label without retry storms
        pending = db.scalars(select(Item).where(Item.enrich_status == ENRICH_PENDING)).all()
        for it in pending:
            it.enrich_status = ENRICH_NONE
        db.commit()
        stats["error"] = "هیچ کلید LLM تنظیم نشده است"
        return stats

    daily_items = int(get_setting(db, "llm_daily_item_limit", settings.llm_daily_item_limit))
    daily_tokens = int(get_setting(db, "llm_daily_token_limit", settings.llm_daily_token_limit))
    batch_size = max(1, int(get_setting(db, "llm_batch_size", settings.llm_batch_size)))
    min_prescore = float(get_setting(db, "llm_min_prescore", settings.llm_min_prescore))
    used_items, used_tokens = today_totals(db)
    remaining = daily_items - used_items
    if not force and (remaining <= 0 or used_tokens >= daily_tokens):
        stats["error"] = "سقف روزانهٔ LLM پر شده است"
        return stats
    limit = remaining if not force else (max_items or 1000)
    if max_items:
        limit = min(limit, max_items)
    items = select_pending(db, limit, 0.0 if item_ids else min_prescore, item_ids)
    stats["selected"] = len(items)
    if not items:
        return stats

    # items that fell below the threshold are marked skipped (shown as untranslated)
    if not item_ids:
        stale = utcnow() - timedelta(days=3)
        low = db.scalars(
            select(Item).where(Item.enrich_status == ENRICH_PENDING, Item.prescore < min_prescore, Item.first_seen_at < stale)
        ).all()
        for it in low:
            it.enrich_status = ENRICH_SKIPPED
        if low:
            stats["skipped"] = len(low)
            db.commit()

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        if not force:
            _, used_tokens = today_totals(db)
            if used_tokens >= daily_tokens:
                stats["error"] = "سقف توکن روزانه پر شد"
                break
        try:
            fetch_details(db, batch)
        except Exception as exc:  # details are best-effort
            log.warning("details fetch failed: %s", exc)
        per_item_tokens = 900 + (300 if any(b.readme_excerpt for b in batch) else 0)
        max_tokens = min(settings.llm_max_output_tokens, 400 + per_item_tokens * len(batch))
        ok, err = enrich_batch(db, providers, batch, max_tokens)
        stats["batches"] += 1
        stats["enriched"] += ok
        if err:
            for it in batch:
                if it.enrich_status != ENRICH_DONE:
                    it.enrich_status = ENRICH_FAILED
                    it.enrich_error = err[:500]
            stats["failed"] += len(batch) - ok
            stats["error"] = err
            db.commit()
            if "نامعتبر است" in err or "کلید" in err:
                break  # auth problems: stop burning requests
        else:
            stats["failed"] += len(batch) - ok
            db.commit()
    return stats


def test_provider(db: Session) -> dict:
    """Admin 'test connection': a tiny request to the first provider."""
    providers = get_providers(db)
    if not providers:
        return {"ok": False, "message": "هیچ ارائه‌دهنده‌ای تنظیم نشده است"}
    p = providers[0]
    try:
        resp = p.complete("فقط JSON برگردان.", 'یک شیء JSON با کلید "ok" و مقدار true برگردان.', max_tokens=64, json_schema=None)
        record_usage(db, p, resp, 0)
        return {"ok": True, "message": f"{p.name}/{resp.model} پاسخ داد: {resp.text[:80]}"}
    except LLMError as exc:
        record_usage(db, p, None, 0, error=True)
        return {"ok": False, "message": str(exc)}
