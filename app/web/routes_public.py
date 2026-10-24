"""Public HTML pages."""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.llm import llm_available
from app.llm.editorial import latest_editorial
from app.models import Item
from app.web import queries
from app.web.auth import current_admin

router = APIRouter()


def render(request: Request, name: str, ctx: dict, **kw) -> HTMLResponse:
    from app.main import templates

    ctx.setdefault("request", request)
    ctx.setdefault("is_admin", bool(current_admin(request)))
    return templates.TemplateResponse(request, name, ctx, **kw)


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    f = queries.Filters.from_params(request.query_params)
    items, total = queries.list_items(db, f)
    pages = max(1, math.ceil(total / f.per_page))
    ctx = {
        "filters": f,
        "items": items,
        "total": total,
        "pages": pages,
        "languages": queries.languages(db),
        "cat_counts": queries.category_counts(db),
        "stats": queries.stats(db),
        "llm_on": llm_available(db),
        "spikes": queries.spikes(db, 6) if f.page == 1 and not f.q else [],
        "editorial": latest_editorial(db) if f.page == 1 and not f.q and not f.category and not f.kind else None,
        "title": None,
    }
    return render(request, "index.html", ctx)


@router.get("/item/{item_id}", response_class=HTMLResponse)
def item_page(item_id: int, request: Request, db: Session = Depends(get_db)):
    it = db.get(Item, item_id)
    if it is None or it.hidden:
        raise HTTPException(404)
    history = queries.star_history(db, it.repo_full_name) if it.kind == "github_repo" else []
    return render(
        request,
        "item.html",
        {
            "item": it,
            "related": queries.related(db, it),
            "linked": queries.linked_items(db, it),
            "star_history": history,
            "star_svg": queries.sparkline_svg(history) if len(history) > 1 else "",
            "star_days": 30,
            "title": it.display_title,
        },
    )


@router.get("/trending", response_class=HTMLResponse)
def trending_page(request: Request, period: str = "weekly", db: Session = Depends(get_db)):
    if period not in ("daily", "weekly", "monthly"):
        period = "weekly"
    return render(
        request,
        "trending.html",
        {"period": period, "items": queries.trending(db, period), "spikes": queries.spikes(db, 12), "title": "ترند هفته"},
    )


@router.get("/releases", response_class=HTMLResponse)
def releases_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "releases.html", {"items": queries.releases(db), "title": "ریلیزها"})


@router.get("/ideas", response_class=HTMLResponse)
def ideas_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "ideas.html", {"items": queries.ideas_today(db), "title": "ایده‌های امروز"})


@router.get("/bookmarks", response_class=HTMLResponse)
def bookmarks_page(request: Request):
    return render(request, "bookmarks.html", {"title": "نشان‌شده‌ها"})


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "about.html", {"title": "درباره", "stats": queries.stats(db)})
