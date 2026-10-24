"""Heuristic pre-score (0..100) used to decide what deserves an LLM call."""
from __future__ import annotations

import math
import re

from app.models import KIND_GITHUB_RELEASE, KIND_GITHUB_REPO, KIND_HACKERNEWS, KIND_HF_MODEL, KIND_HF_PAPER, KIND_RSS, Item, Source

AI_KEYWORDS = re.compile(
    r"\b(ai|a\.i\.|llm|llms|gpt|claude|openai|anthropic|gemini|mistral|llama|agent|agents|agentic|"
    r"rag|mcp|transformer|diffusion|stable diffusion|machine learning|deep learning|neural|"
    r"copilot|cursor|coding assistant|model|models|inference|fine-?tun|embedding|vector|"
    r"whisper|tts|speech|vision|multimodal|robot|hugging ?face|pytorch|tensorflow|jax|"
    r"vllm|ollama|langchain|llamaindex|prompt|chatbot|chatgpt|deepseek|qwen|nvidia|cuda|gpu)\b",
    re.IGNORECASE,
)


def is_ai_related(text: str) -> bool:
    return bool(AI_KEYWORDS.search(text or ""))


def compute_prescore(item: Item, source: Source | None = None) -> float:
    weight = float(source.weight) if source is not None and source.weight else 1.0
    text = f"{item.title or ''} {(item.original_text or '')[:400]} {' '.join(item.topics or [])}"
    ai_bonus = 12.0 if is_ai_related(text) else 0.0
    flags = set(item.flags or [])

    if item.kind == KIND_GITHUB_REPO:
        score = 10.0
        score += min(25.0, 5.0 * math.log10(max(item.stars or 0, 1)))  # 1k->15, 10k->20, 100k->25
        delta = max(item.stars_delta_day or 0, (item.stars_delta_week or 0) / 5, (item.stars_delta_month or 0) / 20)
        score += min(30.0, 6.0 * math.log10(max(delta, 1)))  # 100/day -> 12, 1000 -> 18
        if "trending_daily" in flags:
            score += 8
        if "trending_weekly" in flags:
            score += 5
        if "trending_monthly" in flags:
            score += 3
        if "spike" in flags:
            score += 15
        if item.rank and item.rank <= 5:
            score += 6
        if any(f.startswith("search:") for f in flags):
            score += 4
        if "hn_discussed" in flags or "in_news" in flags:
            score += 8
        score += ai_bonus
    elif item.kind == KIND_GITHUB_RELEASE:
        score = 45.0 + min(25.0, 5.0 * math.log10(max(item.stars or 0, 1)))
        tag = (item.release_tag or "").lower()
        if re.search(r"(rc|alpha|beta|nightly|dev|preview)", tag):
            score -= 20
        if re.match(r"v?\d+\.0(\.0)?$", tag):
            score += 10  # major release
        score += ai_bonus / 2
    elif item.kind == KIND_HACKERNEWS:
        score = 20.0 + min(40.0, (item.points or 0) / 10.0) + min(10.0, (item.comments_count or 0) / 30.0)
        score += ai_bonus
    elif item.kind == KIND_RSS:
        score = 30.0 + ai_bonus
    elif item.kind == KIND_HF_MODEL:
        likes = item.points or 0
        downloads = item.comments_count or 0
        score = 25.0 + min(25.0, 6.0 * math.log10(max(likes, 1))) + min(15.0, 3.0 * math.log10(max(downloads, 1)))
    elif item.kind == KIND_HF_PAPER:
        score = 22.0 + min(25.0, 2.0 * (item.points or 0)) + (8.0 if item.repo_full_name else 0.0)
    else:
        score = 20.0
    return round(max(0.0, min(100.0, score * weight)), 2)
