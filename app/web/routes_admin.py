"""Admin panel (password protected)."""
from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors import KIND_LABELS
from app.config import RUNTIME_KEYS, get_settings
from app.db import get_db
from app.llm import get_providers
from app.llm.enrich import test_provider, today_totals
from app.models import ENRICH_DONE, ENRICH_FAILED, ENRICH_NONE, ENRICH_PENDING, ENRICH_SKIPPED, Command, Item, LlmUsage, RunLog, Source, utcnow
from app.notify import notify_configured, send_message
from app.settings_store import all_runtime_settings, set_setting
from app.web.auth import COOKIE, MAX_AGE, check_credentials, current_admin, make_token, require_admin

router = APIRouter(prefix="/admin", include_in_schema=False)


def render(request: Request, name: str, ctx: dict, **kw) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("is_admin", True)
    ctx.setdefault("flash", request.query_params.get("msg", ""))
    ctx.setdefault("flash_kind", request.query_params.get("kind", "ok"))
    return templates.TemplateResponse(request, name, ctx, **kw)


def _redirect(path: str, msg: str = "", kind: str = "ok") -> RedirectResponse:
    from urllib.parse import urlencode

    if msg:
        path = f"{path}?{urlencode({'msg': msg, 'kind': kind})}"
    return RedirectResponse(path, status_code=303)


def queue(db: Session, name: str, payload: dict | None = None) -> Command:
    cmd = Command(name=name, payload=payload or {})
    db.add(cmd)
    db.commit()
    return cmd


# --------------------------------------------------------------------------- auth
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if current_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return render(request, "admin/login.html", {"title": "ورود مدیر", "error": "", "is_admin": False})


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/admin")):
    ip = request.client.host if request.client else "?"
    if not check_credentials(username, password, ip):
        return render(request, "admin/login.html", {"title": "ورود مدیر", "error": "نام کاربری یا رمز نادرست است (یا تلاش‌های زیاد).", "is_admin": False}, status_code=401)
    resp = RedirectResponse(next if next.startswith("/") else "/admin", status_code=303)
    secure = request.url.scheme == "https"
    resp.set_cookie(COOKIE, make_token(username), max_age=MAX_AGE, httponly=True, samesite="lax", secure=secure)
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# --------------------------------------------------------------------------- dashboard
@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    settings = get_settings()
    counts = dict(db.execute(select(Item.enrich_status, func.count(Item.id)).group_by(Item.enrich_status)).all())
    used_items, used_tokens = today_totals(db)
    recent_runs = db.scalars(select(RunLog).order_by(RunLog.id.desc()).limit(12)).all()
    pending_cmds = db.scalars(select(Command).where(Command.status.in_(["queued", "running"])).order_by(Command.id.desc())).all()
    last_cmds = db.scalars(select(Command).where(Command.status.in_(["done", "error"])).order_by(Command.id.desc()).limit(5)).all()
    sources = db.scalars(select(Source).order_by(Source.kind, Source.id)).all()
    providers = get_providers(db)
    last_worker_seen = db.scalar(select(func.max(RunLog.started_at)))
    worker_alive = last_worker_seen is not None and (utcnow() - last_worker_seen) < timedelta(hours=max(settings.enrich_every_min, 30) / 60 * 3)
    ctx = {
        "title": "پیشخوان مدیریت",
        "counts": {
            "total": sum(counts.values()),
            "done": counts.get(ENRICH_DONE, 0),
            "pending": counts.get(ENRICH_PENDING, 0),
            "failed": counts.get(ENRICH_FAILED, 0),
            "skipped": counts.get(ENRICH_SKIPPED, 0) + counts.get(ENRICH_NONE, 0),
        },
        "used_items": used_items,
        "used_tokens": used_tokens,
        "limit_items": settings.llm_daily_item_limit,
        "limit_tokens": settings.llm_daily_token_limit,
        "recent_runs": recent_runs,
        "pending_cmds": pending_cmds,
        "last_cmds": last_cmds,
        "sources": sources,
        "providers": [f"{p.name} / {p.model}" for p in providers],
        "notify_on": notify_configured(db),
        "worker_alive": worker_alive,
        "last_worker_seen": last_worker_seen,
        "kind_labels": KIND_LABELS,
    }
    return render(request, "admin/dashboard.html", ctx)


@router.post("/run/{job}")
def run_job(job: str, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    allowed = {"collect_all", "collect_github", "collect_releases", "collect_hn", "collect_rss", "spikes", "enrich", "digest", "full_cycle", "cleanup", "track_stars", "editorial"}
    if job not in allowed:
        raise HTTPException(400, "unknown job")
    payload = {"force": True, "max_items": 40} if job == "enrich" else {}
    queue(db, job, payload)
    return _redirect("/admin", f"کار «{job}» در صف اجرا قرار گرفت؛ worker آن را اجرا می‌کند.")


# --------------------------------------------------------------------------- sources
@router.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    sources = db.scalars(select(Source).order_by(Source.kind, Source.id)).all()
    return render(request, "admin/sources.html", {"title": "منابع", "sources": sources, "kind_labels": KIND_LABELS})


@router.post("/sources/{source_id}/toggle")
def toggle_source(source_id: int, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    src = db.get(Source, source_id)
    if src is None:
        raise HTTPException(404)
    src.enabled = not src.enabled
    db.commit()
    return _redirect("/admin/sources", f"منبع «{src.name}» {'فعال' if src.enabled else 'غیرفعال'} شد.")


@router.post("/sources/{source_id}/run")
def run_source_now(source_id: int, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    src = db.get(Source, source_id)
    if src is None:
        raise HTTPException(404)
    queue(db, "collect_source", {"source_id": source_id})
    return _redirect("/admin/sources", f"جمع‌آوری «{src.name}» در صف قرار گرفت.")


@router.post("/sources/{source_id}/config")
def save_source_config(source_id: int, config: str = Form(...), weight: float = Form(1.0), db: Session = Depends(get_db), user: str = Depends(require_admin)):
    src = db.get(Source, source_id)
    if src is None:
        raise HTTPException(404)
    try:
        parsed = json.loads(config)
        if not isinstance(parsed, dict):
            raise ValueError("config must be an object")
    except ValueError as exc:
        return _redirect("/admin/sources", f"JSON نامعتبر: {exc}", "error")
    src.config = parsed
    src.weight = max(0.1, min(3.0, float(weight)))
    db.commit()
    return _redirect("/admin/sources", f"تنظیمات «{src.name}» ذخیره شد.")


@router.post("/sources/{source_id}/list")
def save_source_list(source_id: int, field: str = Form(...), lines: str = Form(""), db: Session = Depends(get_db), user: str = Depends(require_admin)):
    """Simple textarea editor for repos / queries / languages."""
    src = db.get(Source, source_id)
    if src is None:
        raise HTTPException(404)
    if field not in ("repos", "queries", "languages"):
        raise HTTPException(400, "bad field")
    rows = [ln.strip() for ln in lines.replace("\r", "").split("\n")]
    cfg = dict(src.config or {})
    if field == "repos":
        cfg["repos"] = [r.strip("/ ") for r in rows if r and "/" in r][:300]
    elif field == "languages":
        cfg["languages"] = list(dict.fromkeys(r.lower() for r in rows))[:20] if any(rows) else [""]
    else:
        queries = []
        for r in rows:
            if not r:
                continue
            if "|" in r:
                label, q = [x.strip() for x in r.split("|", 1)]
                queries.append({"q": q, "label": label or q})
            else:
                queries.append({"q": r, "label": r})
        cfg["queries"] = queries[:60]
    src.config = cfg
    db.commit()
    return _redirect("/admin/sources", f"فهرست «{src.name}» ذخیره شد ({len(cfg[field])} مورد).")


@router.get("/items/export.json")
def export_items(db: Session = Depends(get_db), user: str = Depends(require_admin)):
    from fastapi.responses import JSONResponse

    from app.web.routes_api import item_to_dict

    items = db.scalars(select(Item).where(Item.hidden.is_(False)).order_by(Item.id.desc()).limit(2000)).all()
    return JSONResponse({"items": [item_to_dict(i, full=True) for i in items]}, headers={"Content-Disposition": "attachment; filename=items.json"})


@router.post("/sources/add-rss")
def add_rss(name: str = Form(...), url: str = Form(...), db: Session = Depends(get_db), user: str = Depends(require_admin)):
    from app.models import SRC_RSS
    from app.utils import sha1

    key = "rss_" + sha1(url.strip())[:10]
    if db.scalar(select(Source).where(Source.key == key)):
        return _redirect("/admin/sources", "این فید قبلاً اضافه شده است.", "error")
    db.add(Source(key=key, name=name.strip()[:200], kind=SRC_RSS, config={"url": url.strip(), "max_items": 40}, weight=1.0))
    db.commit()
    return _redirect("/admin/sources", "فید اضافه شد.")


@router.post("/sources/{source_id}/delete")
def delete_source(source_id: int, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    src = db.get(Source, source_id)
    if src is None:
        raise HTTPException(404)
    if src.kind != "rss":
        return _redirect("/admin/sources", "فقط فیدهای RSS حذف می‌شوند؛ منابع اصلی را غیرفعال کنید.", "error")
    for it in db.scalars(select(Item).where(Item.source_id == src.id)).all():
        it.source_id = None
    db.delete(src)
    db.commit()
    return _redirect("/admin/sources", "فید حذف شد.")


# --------------------------------------------------------------------------- settings
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    return render(request, "admin/settings.html", {"title": "تنظیمات", "rows": all_runtime_settings(db)})


@router.post("/settings")
async def save_settings(request: Request, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    form = await request.form()
    changed = 0
    for key in RUNTIME_KEYS:
        if key not in form:
            continue
        value = str(form.get(key) or "").strip()
        if RUNTIME_KEYS[key]["secret"] and (value in ("", "••••") or "…" in value):
            if not form.get(f"clear_{key}"):
                continue  # untouched masked value
        if form.get(f"clear_{key}"):
            set_setting(db, key, "")
            changed += 1
            continue
        set_setting(db, key, value)
        changed += 1
    db.commit()
    return _redirect("/admin/settings", f"{changed} تنظیم ذخیره شد. (مقادیر خالی = استفاده از .env)")


@router.post("/settings/test-llm")
def test_llm(db: Session = Depends(get_db), user: str = Depends(require_admin)):
    res = test_provider(db)
    return _redirect("/admin/settings", res["message"], "ok" if res["ok"] else "error")


@router.post("/settings/test-notify")
def test_notify(db: Session = Depends(get_db), user: str = Depends(require_admin)):
    res = send_message(db, "✅ پیام آزمایشی از رادار گیت‌هاب")
    return _redirect("/admin/settings", res["message"], "ok" if res["ok"] else "error")


# --------------------------------------------------------------------------- logs & usage
@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    runs = db.scalars(select(RunLog).order_by(RunLog.id.desc()).limit(150)).all()
    cmds = db.scalars(select(Command).order_by(Command.id.desc()).limit(50)).all()
    return render(request, "admin/logs.html", {"title": "لاگ اجرا", "runs": runs, "cmds": cmds})


@router.get("/usage", response_class=HTMLResponse)
def usage_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    since = date.today() - timedelta(days=30)
    rows = db.scalars(select(LlmUsage).where(LlmUsage.day >= since).order_by(LlmUsage.day.desc(), LlmUsage.provider)).all()
    totals = db.execute(
        select(
            func.coalesce(func.sum(LlmUsage.requests), 0),
            func.coalesce(func.sum(LlmUsage.input_tokens), 0),
            func.coalesce(func.sum(LlmUsage.output_tokens), 0),
            func.coalesce(func.sum(LlmUsage.items), 0),
            func.coalesce(func.sum(LlmUsage.cost_usd), 0.0),
            func.coalesce(func.sum(LlmUsage.errors), 0),
        ).where(LlmUsage.day >= since)
    ).one()
    return render(request, "admin/usage.html", {"title": "مصرف LLM", "rows": rows, "totals": totals})


# --------------------------------------------------------------------------- items
@router.get("/items", response_class=HTMLResponse)
def items_admin(request: Request, status: str = "", db: Session = Depends(get_db), user: str = Depends(require_admin)):
    stmt = select(Item).order_by(Item.id.desc()).limit(100)
    if status:
        stmt = stmt.where(Item.enrich_status == status)
    items = db.scalars(stmt).all()
    return render(request, "admin/items.html", {"title": "آیتم‌ها", "items": items, "status": status})


@router.post("/items/{item_id}/hide")
def hide_item(item_id: int, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    it = db.get(Item, item_id)
    if it is None:
        raise HTTPException(404)
    it.hidden = not it.hidden
    db.commit()
    return _redirect("/admin/items", "وضعیت نمایش آیتم تغییر کرد.")


@router.post("/items/{item_id}/enrich")
def enrich_item(item_id: int, db: Session = Depends(get_db), user: str = Depends(require_admin)):
    it = db.get(Item, item_id)
    if it is None:
        raise HTTPException(404)
    it.enrich_status = ENRICH_PENDING
    db.commit()
    queue(db, "enrich", {"item_ids": [item_id], "force": True})
    return _redirect(f"/item/{item_id}", "ترجمهٔ مجدد در صف قرار گرفت.")
