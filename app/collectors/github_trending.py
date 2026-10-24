"""GitHub trending (HTML) collector."""
from __future__ import annotations

import logging
import re
import time

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.collectors.base import IngestResult, RawItem, ingest
from app.collectors.http import make_client, plain_get
from app.config import get_settings
from app.models import KIND_GITHUB_REPO, Source
from app.utils import github_lang_slug

log = logging.getLogger(__name__)

PERIODS = ("daily", "weekly", "monthly")
_NUM_RE = re.compile(r"[\d,]+")


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    m = _NUM_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_trending(html: str, period: str = "daily") -> list[dict]:
    """Parse github.com/trending HTML into plain dicts (unit-tested)."""
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("article.Box-row")
    out: list[dict] = []
    for rank, row in enumerate(rows, start=1):
        h2 = row.find("h2")
        link = h2.find("a") if h2 else None
        href = (link.get("href") or "").strip() if link else ""
        full_name = href.strip("/")
        if not full_name or full_name.count("/") != 1:
            continue
        desc_el = row.find("p")
        description = desc_el.get_text(" ", strip=True) if desc_el else ""
        lang_el = row.find(attrs={"itemprop": "programmingLanguage"})
        language = lang_el.get_text(strip=True) if lang_el else ""
        stars = forks = None
        for a in row.select("a.Link--muted"):
            ahref = a.get("href") or ""
            if ahref.endswith("/stargazers"):
                stars = _to_int(a.get_text())
            elif ahref.endswith("/forks"):
                forks = _to_int(a.get_text())
        delta = None
        delta_el = row.select_one("span.float-sm-right")
        if delta_el is not None:
            delta = _to_int(delta_el.get_text())
        authors = [
            (a.get("href") or "").strip("/")
            for a in row.select("span.d-inline-block a[href]")
            if (a.get("href") or "").count("/") == 1 and a.find("img") is not None
        ]
        out.append(
            {
                "full_name": full_name,
                "url": f"https://github.com/{full_name}",
                "description": description,
                "language": language,
                "stars": stars,
                "forks": forks,
                "delta": delta,
                "period": period,
                "rank": rank,
                "built_by": authors[:5],
            }
        )
    return out


def to_raw_items(parsed: list[dict], language_filter: str = "") -> list[RawItem]:
    items: list[RawItem] = []
    for p in parsed:
        period = p["period"]
        kwargs: dict = {}
        if period == "daily":
            kwargs["stars_delta_day"] = p["delta"]
        elif period == "weekly":
            kwargs["stars_delta_week"] = p["delta"]
        else:
            kwargs["stars_delta_month"] = p["delta"]
        flags = [f"trending_{period}"]
        if language_filter:
            flags.append(f"trending_lang:{language_filter}")
        items.append(
            RawItem(
                kind=KIND_GITHUB_REPO,
                external_id=f"gh:{p['full_name'].lower()}",
                url=p["url"],
                title=p["full_name"],
                original_text=p["description"],
                source_label="GitHub Trending",
                repo_full_name=p["full_name"],
                language=p["language"],
                stars=p["stars"],
                forks=p["forks"],
                flags=flags,
                rank=p["rank"] if (period == "daily" and not language_filter) else None,
                author=(p.get("built_by") or [""])[0],
                raw={f"trending_{period}{'_' + language_filter if language_filter else ''}": p["delta"]},
                **kwargs,
            )
        )
    return items


def collect(db: Session, source: Source) -> IngestResult:
    settings = get_settings()
    cfg = source.config or {}
    periods = cfg.get("periods") or list(PERIODS)
    languages = cfg.get("languages")
    if languages is None:
        languages = settings.trending_languages
    total = IngestResult()
    with make_client(timeout=40) as client:
        for period in periods:
            for lang in languages:
                path = f"/trending/{github_lang_slug(lang)}" if lang else "/trending"
                url = f"https://github.com{path}?since={period}"
                try:
                    resp = plain_get(client, url, browser=True)
                except Exception as exc:  # network
                    log.warning("trending fetch failed %s: %s", url, exc)
                    continue
                if resp.status_code != 200:
                    log.warning("trending %s -> %s", url, resp.status_code)
                    time.sleep(2)
                    continue
                parsed = parse_trending(resp.text, period)
                res = ingest(db, source, to_raw_items(parsed, lang))
                total.created += res.created
                total.updated += res.updated
                db.commit()
                time.sleep(1.5)  # be polite
    return total
