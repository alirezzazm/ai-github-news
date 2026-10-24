"""Anthropic Claude provider (official SDK)."""
from __future__ import annotations

import logging

from app.llm.base import LLMError, LLMProvider, LLMResponse, price_for

log = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str = "low", timeout: float = 180.0):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self.model = model
        self.effort = effort if effort in ("low", "medium", "high", "xhigh", "max") else "low"

    def complete(self, system: str, user: str, *, max_tokens: int, json_schema: dict | None = None) -> LLMResponse:
        anthropic = self._anthropic
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
        }
        output_config: dict = {}
        if self.model.startswith(("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable", "claude-opus-4-7", "claude-opus-4-8", "claude-opus-4-6", "claude-sonnet-4-6")):
            output_config["effort"] = self.effort
        if json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if output_config:
            kwargs["output_config"] = output_config
        try:
            resp = self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMError(f"کلید Anthropic نامعتبر است: {exc.message}", provider=self.name) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("محدودیت نرخ Anthropic", retryable=True, provider=self.name) from exc
        except anthropic.BadRequestError as exc:
            # e.g. output_config unsupported on this model -> retry without it once
            if json_schema is not None and "output_config" in str(exc.message):
                log.warning("output_config rejected by %s; retrying without schema", self.model)
                kwargs.pop("output_config", None)
                try:
                    resp = self.client.messages.create(**kwargs)
                except anthropic.APIError as exc2:
                    raise LLMError(str(exc2), provider=self.name) from exc2
            else:
                raise LLMError(f"درخواست نامعتبر: {exc.message}", provider=self.name) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"خطای Anthropic {exc.status_code}", retryable=exc.status_code >= 500, provider=self.name) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("اتصال به Anthropic برقرار نشد", retryable=True, provider=self.name) from exc

        if resp.stop_reason == "refusal":
            raise LLMError("مدل از پاسخ خودداری کرد (refusal)", provider=self.name)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        usage = resp.usage
        in_tok = (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0) + (
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )
        return LLMResponse(
            text=text,
            input_tokens=in_tok,
            output_tokens=usage.output_tokens or 0,
            model=resp.model or self.model,
            provider=self.name,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return price_for(self.model, input_tokens, output_tokens)
