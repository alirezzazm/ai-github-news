"""RSS / Atom collector (one Source row per feed)."""
from __future__ import annotations

import logging
import time
from datetime import datetime

import feedparser
from sqlalchemy.orm import Session

from app.collectors.base import IngestResult, RawItem, ingest
from app.collectors.http import make_client, plain_get
from app.config import get_settings
from app.models import KIND_RSS, Source
from app.utils import normalize_url, sha1, strip_html, truncate

log = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    {"key": "rss_techcrunch_ai", "name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "weight": 1.0},
    {"key": "rss_verge_ai", "name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "weight": 1.0},
    {"key": "rss_hf_blog", "name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "weight": 1.2},
    {"key": "rss_openai", "name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "weight": 1.3},
    {"key": "rss_google_ai", "name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "weight": 1.1},
    {"key": "rss_deepmind", "name": "Google DeepMind", "url": "https://deepmind.google/blog/rss.xml", "weight": 1.1},
    {"key": "rss_simonw", "name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/", "weight": 1.0},
    {"key": "rss_mit_tr_ai", "name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "weight": 1.0},
    {"key": "rss_github_blog", "name": "GitHub Blog", "url": "https://github.blog/feed/", "weight": 1.0},
    {"key": "rss_arxiv_ai", "name": "arXiv cs.AI", "url": "https://rss.arxiv.org/rss/cs.AI", "weight": 0.5, "max_items": 25},
    {"key": "rss_arxiv_cl", "name": "arXiv cs.CL", "url": "https://rss.arxiv.org/rss/cs.CL", "weight": 0.5, "max_items": 25},
    {"key": "rss_arxiv_lg", "name": "arXiv cs.LG", "url": "https://rss.arxiv.org/rss/cs.LG", "weight": 0.5, "max_items": 25},
    {"key": "rss_ars_ai", "name": "Ars Technica AI", "url": "https://arstechnica.com/ai/feed/", "weight": 1.0},
    {"key": "rss_reddit_localllama", "name": "Reddit r/LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day", "weight": 0.9, "max_items": 25, "enabled": False},
    {"key": "rss_reddit_ml", "name": "Reddit r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/top/.rss?t=day", "weight": 0.8, "max_items": 20, "enabled": False},
    {"key": "rss_devto_ai", "name": "dev.to #ai", "url": "https://dev.to/feed/tag/ai", "weight": 0.7, "max_items": 20},
    {"key": "rss_lobsters_ai", "name": "Lobsters AI", "url": "https://lobste.rs/t/ai.rss", "weight": 0.8},
    {"key": "rss_producthunt_ai", "name": "Product Hunt AI", "url": "https://www.producthunt.com/feed?category=artificial-intelligence", "weight": 0.8, "max_items": 20},
    {"key": "rss_nvidia_blog", "name": "NVIDIA Technical Blog", "url": "https://developer.nvidia.com/blog/feed", "weight": 0.9, "max_items": 20},
    {"key": "rss_dotnet_blog", "name": ".NET Blog", "url": "https://devblogs.microsoft.com/dotnet/feed/", "weight": 0.9},
    {"key": "rss_vercel", "name": "Vercel Blog", "url": "https://vercel.com/atom", "weight": 0.8},
]


def parse_feed(content: bytes | str, source_name: str, max_items: int = 40) -> list[RawItem]:
    parsed = feedparser.parse(content)
    out: list[RawItem] = []
    for entry in parsed.entries[:max_items]:
        link = entry.get("link") or ""
        if not link:
            continue
        title = strip_html(entry.get("title") or "").strip()
        summary = entry.get("summary") or ""
        if not summary and entry.get("content"):
            summary = entry["content"][0].get("value", "")
        text = truncate(strip_html(summary), 3000)
        published = None
        for key in ("published_parsed", "updated_parsed"):
            tp = entry.get(key)
            if tp:
                try:
                    published = datetime(*tp[:6])
                except Exception:
                    published = None
                break
        tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]
        author = entry.get("author") or ""
        out.append(
            RawItem(
                kind=KIND_RSS,
                external_id=f"rss:{sha1(normalize_url(link))[:24]}",
                url=link,
                title=title or link,
                original_text=text,
                source_label=source_name,
                author=author[:200],
                topics=tags[:10],
                published_at=published,
                raw={"feed": source_name},
            )
        )
    return out


def collect(db: Session, source: Source) -> IngestResult:
    settings = get_settings()
    cfg = source.config or {}
    url = cfg.get("url")
    if not url:
        raise ValueError("RSS source has no url")
    max_items = int(cfg.get("max_items", settings.rss_max_items_per_feed))
    with make_client(timeout=30) as client:
        headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"}
        if "reddit.com" in url:
            headers["User-Agent"] = "linux:ai-github-news:1.0 (by /u/alirezzazm)"
            time.sleep(3)
        resp = plain_get(client, url, browser="reddit.com" not in url, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    raws = parse_feed(resp.content, source.name, max_items)
    res = ingest(db, source, raws)
    db.commit()
    time.sleep(0.5)
    return res
