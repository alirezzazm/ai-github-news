"""Hugging Face collector: trending models + daily papers (public API, no key)."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.collectors.base import IngestResult, RawItem, ingest
from app.collectors.http import make_client, plain_get
from app.collectors.linking import extract_repo_full_name
from app.models import KIND_HF_MODEL, KIND_HF_PAPER, Source
from app.utils import parse_dt, strip_html, truncate

log = logging.getLogger(__name__)
API = "https://huggingface.co/api"


def model_to_raw(m: dict) -> RawItem | None:
    mid = m.get("modelId") or m.get("id")
    if not mid or m.get("private"):
        return None
    tags = [t for t in (m.get("tags") or []) if ":" not in t][:12]
    pipeline = m.get("pipeline_tag") or ""
    lib = m.get("library_name") or ""
    desc_parts = []
    if pipeline:
        desc_parts.append(f"task: {pipeline}")
    if lib:
        desc_parts.append(f"library: {lib}")
    if m.get("downloads"):
        desc_parts.append(f"downloads: {m['downloads']:,}")
    if m.get("likes"):
        desc_parts.append(f"likes: {m['likes']:,}")
    return RawItem(
        kind=KIND_HF_MODEL,
        external_id=f"hf:{mid.lower()}",
        url=f"https://huggingface.co/{mid}",
        title=mid,
        original_text=" · ".join(desc_parts),
        source_label="Hugging Face Trending",
        author=mid.split("/")[0] if "/" in mid else "",
        topics=([pipeline] if pipeline else []) + tags,
        points=int(m.get("likes") or 0),
        comments_count=int(m.get("downloads") or 0),
        flags=["hf_trending"],
        published_at=parse_dt(m.get("createdAt")),
        raw={"trending_score": m.get("trendingScore"), "downloads": m.get("downloads"), "likes": m.get("likes"), "pipeline": pipeline, "library": lib},
    )


def paper_to_raw(p: dict) -> RawItem | None:
    paper = p.get("paper") or {}
    pid = paper.get("id")
    if not pid:
        return None
    title = (paper.get("title") or p.get("title") or "").strip()
    summary = paper.get("ai_summary") or paper.get("summary") or ""
    authors = [a.get("name", "") for a in (paper.get("authors") or []) if a.get("name")]
    text = strip_html(summary)
    if paper.get("summary") and paper.get("ai_summary"):
        text = truncate(strip_html(paper["ai_summary"]) + "\n\n" + strip_html(paper["summary"]), 3000)
    repo = extract_repo_full_name(paper.get("githubRepo") or "")
    return RawItem(
        kind=KIND_HF_PAPER,
        external_id=f"hfp:{pid}",
        url=f"https://huggingface.co/papers/{pid}",
        title=title,
        original_text=text,
        source_label="Hugging Face Papers",
        author=", ".join(authors[:3]) + (" و دیگران" if len(authors) > 3 else ""),
        topics=list(paper.get("ai_keywords") or [])[:10],
        points=int(paper.get("upvotes") or 0),
        comments_count=int(p.get("numComments") or 0),
        comments_url=f"https://huggingface.co/papers/{pid}",
        repo_full_name=repo,
        flags=["hf_daily_paper"] + (["links_repo"] if repo else []),
        published_at=parse_dt(paper.get("publishedAt") or p.get("publishedAt")),
        raw={"arxiv": f"https://arxiv.org/abs/{pid}", "project_page": paper.get("projectPage") or "", "github": paper.get("githubRepo") or ""},
    )


def collect(db: Session, source: Source) -> IngestResult:
    cfg = source.config or {}
    limit_models = int(cfg.get("models", 30))
    limit_papers = int(cfg.get("papers", 30))
    total = IngestResult()
    with make_client(timeout=30) as client:
        if limit_models:
            r = plain_get(client, f"{API}/models", params={"sort": "trendingScore", "direction": -1, "limit": limit_models})
            if r.status_code == 200:
                raws = [x for x in (model_to_raw(m) for m in r.json()) if x]
                res = ingest(db, source, raws)
                total.created += res.created
                total.updated += res.updated
                db.commit()
            else:
                log.warning("HF models -> %s", r.status_code)
        if limit_papers:
            r = plain_get(client, f"{API}/daily_papers", params={"limit": limit_papers})
            if r.status_code == 200:
                raws = [x for x in (paper_to_raw(p) for p in r.json()) if x]
                res = ingest(db, source, raws)
                total.created += res.created
                total.updated += res.updated
                db.commit()
            else:
                log.warning("HF papers -> %s", r.status_code)
    return total
