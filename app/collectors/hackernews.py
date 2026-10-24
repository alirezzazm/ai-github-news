"""Hacker News collector.

Three interchangeable transports, tried in order (the official Firebase API is
blocked on some networks, e.g. inside Iran):

1. Firebase API  (hacker-news.firebaseio.com)  -> top + best stories with full text
2. HTML pages    (news.ycombinator.com/news, /best)  -> parsed with BeautifulSoup
3. HNPWA JSON    (api.hnpwa.com)               -> community mirror, news pages
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.collectors.base import IngestResult, RawItem, ingest
from app.collectors.http import make_client, plain_get
from app.collectors.prescore import is_ai_related
from app.config import get_settings
from app.models import KIND_HACKERNEWS, Source
from app.settings_store import get_setting
from app.utils import parse_dt, strip_html

log = logging.getLogger(__name__)
FIREBASE = "https://hacker-news.firebaseio.com/v0"
HN_SITE = "https://news.ycombinator.com"
HNPWA = "https://api.hnpwa.com/v0"
_NUM = re.compile(r"\d+")


def _flags(title: str, text: str = "") -> list[str]:
    return ["ai"] if is_ai_related(title + " " + text[:300]) else []


def story_to_raw(story: dict) -> RawItem | None:
    """Firebase item dict -> RawItem."""
    if not story or story.get("type") != "story" or story.get("dead") or story.get("deleted"):
        return None
    sid = story["id"]
    title = story.get("title") or ""
    hn_url = f"{HN_SITE}/item?id={sid}"
    url = story.get("url") or hn_url
    text = strip_html(story.get("text") or "")
    return RawItem(
        kind=KIND_HACKERNEWS,
        external_id=f"hn:{sid}",
        url=url,
        title=title,
        original_text=text,
        source_label="Hacker News",
        points=story.get("score") or 0,
        comments_count=story.get("descendants") or 0,
        comments_url=hn_url,
        author=story.get("by") or "",
        flags=_flags(title, text),
        published_at=datetime.fromtimestamp(story["time"], tz=timezone.utc).replace(tzinfo=None) if story.get("time") else None,
        raw={"hn_id": sid},
    )


def parse_hn_html(html: str) -> list[dict]:
    """Parse a news.ycombinator.com listing page into plain dicts (unit-tested)."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for row in soup.select("tr.athing"):
        sid = row.get("id")
        if not sid or not sid.isdigit():
            continue
        link = row.select_one("span.titleline > a") or row.select_one("a.titlelink")
        if link is None:
            continue
        href = (link.get("href") or "").strip()
        if href.startswith("item?id="):
            href = f"{HN_SITE}/{href}"
        title = link.get_text(" ", strip=True)
        sub = row.find_next_sibling("tr")
        points = comments = 0
        author = ""
        published = None
        if sub is not None:
            score = sub.select_one("span.score")
            if score is not None:
                m = _NUM.search(score.get_text())
                points = int(m.group(0)) if m else 0
            user = sub.select_one("a.hnuser")
            author = user.get_text(strip=True) if user else ""
            age = sub.select_one("span.age")
            if age is not None and age.get("title"):
                published = parse_dt(str(age["title"]).split(" ")[0])
            for a in sub.select("a[href^='item?id=']"):
                txt = a.get_text(" ", strip=True).replace("\xa0", " ")
                if "comment" in txt:
                    m = _NUM.search(txt)
                    comments = int(m.group(0)) if m else 0
        out.append(
            {
                "id": int(sid),
                "title": title,
                "url": href or f"{HN_SITE}/item?id={sid}",
                "points": points,
                "comments": comments,
                "author": author,
                "published_at": published,
            }
        )
    return out


def listing_to_raw(entry: dict) -> RawItem:
    """HTML / HNPWA listing dict -> RawItem."""
    sid = entry["id"]
    title = entry.get("title") or ""
    hn_url = f"{HN_SITE}/item?id={sid}"
    return RawItem(
        kind=KIND_HACKERNEWS,
        external_id=f"hn:{sid}",
        url=entry.get("url") or hn_url,
        title=title,
        original_text="",
        source_label="Hacker News",
        points=int(entry.get("points") or 0),
        comments_count=int(entry.get("comments") or 0),
        comments_url=hn_url,
        author=entry.get("author") or "",
        flags=_flags(title),
        published_at=entry.get("published_at"),
        raw={"hn_id": sid},
    )


# --------------------------------------------------------------------------- transports
def _via_firebase(client, max_stories: int) -> list[RawItem]:
    ids: list[int] = []
    for feed in ("topstories", "beststories"):
        r = client.get(f"{FIREBASE}/{feed}.json", timeout=12)
        r.raise_for_status()
        ids.extend(r.json()[:max_stories])
    ids = list(dict.fromkeys(ids))

    def fetch(i: int) -> dict | None:
        try:
            rr = client.get(f"{FIREBASE}/item/{i}.json", timeout=12)
            return rr.json() if rr.status_code == 200 else None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        stories = list(pool.map(fetch, ids))
    return [x for x in (story_to_raw(s or {}) for s in stories) if x]


def _via_html(client, pages: int = 4) -> list[RawItem]:
    entries: dict[int, dict] = {}
    urls = [f"{HN_SITE}/news?p={p}" for p in range(1, pages + 1)] + [f"{HN_SITE}/best?p={p}" for p in (1, 2)]
    for url in urls:
        resp = plain_get(client, url, browser=True)
        if resp.status_code != 200:
            log.warning("HN html %s -> %s", url, resp.status_code)
            continue
        for e in parse_hn_html(resp.text):
            entries.setdefault(e["id"], e)
        time.sleep(1.0)
    if not entries:
        raise RuntimeError("HN HTML returned no stories")
    return [listing_to_raw(e) for e in entries.values()]


def _via_hnpwa(client, pages: int = 5) -> list[RawItem]:
    entries: dict[int, dict] = {}
    for p in range(1, pages + 1):
        resp = plain_get(client, f"{HNPWA}/news/{p}.json")
        if resp.status_code != 200:
            continue
        for s in resp.json():
            if s.get("type") not in (None, "link", "ask"):
                continue
            entries.setdefault(
                int(s["id"]),
                {
                    "id": int(s["id"]),
                    "title": s.get("title") or "",
                    "url": s.get("url") if str(s.get("url", "")).startswith("http") else None,
                    "points": s.get("points") or 0,
                    "comments": s.get("comments_count") or 0,
                    "author": s.get("user") or "",
                    "published_at": datetime.fromtimestamp(s["time"], tz=timezone.utc).replace(tzinfo=None) if s.get("time") else None,
                },
            )
    if not entries:
        raise RuntimeError("HNPWA returned no stories")
    return [listing_to_raw(e) for e in entries.values()]


TRANSPORTS = (("firebase", _via_firebase), ("html", _via_html), ("hnpwa", _via_hnpwa))


def collect(db: Session, source: Source) -> IngestResult:
    settings = get_settings()
    cfg = source.config or {}
    min_points = int(cfg.get("min_points") or get_setting(db, "hn_min_points", settings.hn_min_points))
    max_stories = int(cfg.get("max_stories", settings.hn_max_stories))
    ai_only = bool(cfg.get("ai_only", False))
    preferred = cfg.get("transport")  # optional: force one transport
    raws: list[RawItem] = []
    errors: list[str] = []
    with make_client(timeout=20) as client:
        for name, fn in TRANSPORTS:
            if preferred and name != preferred:
                continue
            try:
                raws = fn(client, max_stories) if name == "firebase" else fn(client)
                log.info("HN via %s: %d stories", name, len(raws))
                src_cfg = dict(cfg)
                src_cfg["last_transport"] = name
                source.config = src_cfg
                break
            except Exception as exc:
                errors.append(f"{name}: {exc.__class__.__name__}: {str(exc)[:80]}")
                log.warning("HN transport %s failed: %s", name, exc)
    if not raws:
        raise RuntimeError("; ".join(errors) or "no transport produced stories")
    kept = [r for r in raws if (r.points or 0) >= min_points and (not ai_only or "ai" in r.flags)]
    res = ingest(db, source, kept)
    db.commit()
    return res
