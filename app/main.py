"""FastAPI application (web + JSON API + admin)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.templating import Jinja2Templates

from app import __version__
from app.collectors.seed import seed_sources
from app.config import get_settings
from app.db import init_db, session_scope
from app.models import CATEGORIES
from app.utils import compact_number, fa_digits, fa_number, jalali_date, time_ago, to_local, truncate
from app.web import queries

log = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))


def _setup_jinja() -> None:
    env = templates.env
    env.filters["fa"] = fa_digits
    env.filters["fanum"] = fa_number
    env.filters["compact"] = compact_number
    env.filters["ago"] = time_ago
    env.filters["jalali"] = jalali_date
    env.filters["local"] = to_local
    env.filters["truncate_words"] = truncate
    env.globals["CATEGORIES"] = CATEGORIES
    env.globals["KIND_LABELS"] = queries.KIND_LABELS
    env.globals["PERIOD_LABELS"] = queries.PERIOD_LABELS
    env.globals["SORTS"] = queries.SORTS
    env.globals["version"] = __version__
    env.globals["settings"] = get_settings()
    env.autoescape = True


_setup_jinja()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    with session_scope() as db:
        seed_sources(db)
    yield


app = FastAPI(title=get_settings().site_name, version=__version__, lifespan=lifespan, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=1000)


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/static/"):
            resp.headers.setdefault("Cache-Control", "public, max-age=604800, immutable")
        return resp


app.add_middleware(SecurityHeaders)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")

from app.web.routes_admin import router as admin_router  # noqa: E402
from app.web.routes_api import feed_router, router as api_router  # noqa: E402
from app.web.routes_public import router as public_router  # noqa: E402

app.include_router(public_router)
app.include_router(api_router)
app.include_router(feed_router)
app.include_router(admin_router)


@app.exception_handler(404)
async def not_found(request: Request, exc):  # pragma: no cover
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": "not found"}, status_code=404)
    return templates.TemplateResponse(request, "404.html", {"request": request}, status_code=404)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    from sqlalchemy import text

    with session_scope() as db:
        db.execute(text("SELECT 1"))
    return {"ok": True, "version": __version__}
