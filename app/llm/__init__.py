"""Provider factory (reads runtime settings from DB with env fallback)."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm.base import LLMProvider
from app.settings_store import get_setting

log = logging.getLogger(__name__)


def get_providers(db: Session) -> list[LLMProvider]:
    """Return configured providers in priority order (may be empty)."""
    settings = get_settings()
    order = [p.strip().lower() for p in str(get_setting(db, "llm_providers", settings.llm_providers)).split(",") if p.strip()]
    providers: list[LLMProvider] = []
    timeout = float(settings.llm_timeout_seconds)
    for name in order:
        try:
            if name in ("anthropic", "claude"):
                key = get_setting(db, "anthropic_api_key", "")
                if not key:
                    continue
                from app.llm.anthropic_provider import AnthropicProvider

                providers.append(
                    AnthropicProvider(
                        api_key=key,
                        model=get_setting(db, "anthropic_model", settings.anthropic_model),
                        effort=get_setting(db, "anthropic_effort", settings.anthropic_effort),
                        timeout=timeout,
                    )
                )
            elif name in ("openai", "openai_compat", "ollama", "openrouter", "groq", "local"):
                base_url = get_setting(db, "openai_base_url", settings.openai_base_url)
                key = get_setting(db, "openai_api_key", "")
                model = get_setting(db, "openai_model", settings.openai_model)
                is_local = ":11434" in base_url or "localhost" in base_url or "ollama" in base_url
                if not key and not is_local:
                    continue
                from app.llm.openai_compat import OpenAICompatProvider

                providers.append(OpenAICompatProvider(api_key=key, base_url=base_url, model=model, timeout=timeout))
        except Exception as exc:  # pragma: no cover
            log.warning("provider %s not initialised: %s", name, exc)
    return providers


def llm_available(db: Session) -> bool:
    return bool(get_providers(db))
