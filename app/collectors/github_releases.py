"""Releases of watched repositories."""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.collectors.base import IngestResult, RawItem, ingest
from app.collectors.http import RateLimited, github_get, make_client
from app.config import get_settings
from app.models import KIND_GITHUB_RELEASE, Source
from app.utils import parse_dt, strip_html, truncate

log = logging.getLogger(__name__)

DEFAULT_WATCH = [
    "huggingface/transformers",
    "huggingface/diffusers",
    "langchain-ai/langchain",
    "langchain-ai/langgraph",
    "run-llama/llama_index",
    "vllm-project/vllm",
    "ollama/ollama",
    "ggml-org/llama.cpp",
    "anthropics/anthropic-sdk-python",
    "anthropics/anthropic-sdk-typescript",
    "anthropics/claude-code",
    "openai/openai-python",
    "openai/openai-agents-python",
    "openai/whisper",
    "modelcontextprotocol/python-sdk",
    "modelcontextprotocol/typescript-sdk",
    "pytorch/pytorch",
    "microsoft/semantic-kernel",
    "microsoft/autogen",
    "crewAIInc/crewAI",
    "comfyanonymous/ComfyUI",
    "open-webui/open-webui",
    "lobehub/lobe-chat",
    "Significant-Gravitas/AutoGPT",
    "deepseek-ai/DeepSeek-V3",
    "QwenLM/Qwen3",
    "google-gemini/gemini-cli",
    "n8n-io/n8n",
    "dotnet/extensions",
    "vercel/ai",
    "nodejs/node",
    "vercel/next.js",
    "dotnet/runtime",
    "python/cpython",
]


def collect(db: Session, source: Source) -> IngestResult:
    settings = get_settings()
    cfg = source.config or {}
    repos = cfg.get("repos") or DEFAULT_WATCH
    per_page = int(cfg.get("per_page", 5))
    total = IngestResult()
    with make_client() as client:
        for full in repos:
            full = full.strip().strip("/")
            if not full or "/" not in full:
                continue
            try:
                res = github_get(
                    client,
                    db,
                    f"{settings.github_api_url}/repos/{full}/releases",
                    params={"per_page": per_page},
                )
            except RateLimited as exc:
                log.warning("releases rate limited (reset %s)", exc.reset_at)
                db.commit()
                return total
            except Exception as exc:
                log.warning("releases fetch failed %s: %s", full, exc)
                continue
            if res.not_modified:
                continue
            if res.status != 200 or not isinstance(res.data, list):
                log.info("releases %s -> %s", full, res.status)
                continue
            raws: list[RawItem] = []
            for rel in res.data:
                if rel.get("draft"):
                    continue
                tag = rel.get("tag_name") or ""
                name = rel.get("name") or tag
                body = strip_html(rel.get("body") or "")
                raws.append(
                    RawItem(
                        kind=KIND_GITHUB_RELEASE,
                        external_id=f"rel:{full.lower()}@{tag}",
                        url=rel.get("html_url") or f"https://github.com/{full}/releases",
                        title=f"{full} {name}" if name != tag else f"{full} {tag}",
                        original_text=truncate(body, 6000),
                        source_label="GitHub Releases",
                        repo_full_name=full,
                        release_tag=tag,
                        author=(rel.get("author") or {}).get("login", ""),
                        flags=["prerelease"] if rel.get("prerelease") else ["release"],
                        published_at=parse_dt(rel.get("published_at") or rel.get("created_at")),
                        raw={"prerelease": bool(rel.get("prerelease"))},
                    )
                )
            r = ingest(db, source, raws)
            total.created += r.created
            total.updated += r.updated
            db.commit()
            time.sleep(0.5)
    return total
