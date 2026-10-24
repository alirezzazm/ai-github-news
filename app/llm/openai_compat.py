"""OpenAI-compatible chat completions provider.

Works with OpenAI, OpenRouter, Groq, Together, DeepSeek, Ollama (``/v1``),
LM Studio, vLLM, LiteLLM proxies, and any other compatible endpoint.
"""
from __future__ import annotations

import logging

import httpx

from app.llm.base import LLMError, LLMProvider, LLMResponse, price_for

log = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 180.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        if "ollama" in self.base_url or ":11434" in self.base_url:
            self.name = "ollama"
        elif "openrouter" in self.base_url:
            self.name = "openrouter"
        elif "groq" in self.base_url:
            self.name = "groq"

    def complete(self, system: str, user: str, *, max_tokens: int, json_schema: dict | None = None) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }
        if json_schema is not None:
            # json_object is the most widely supported mode; the prompt already demands JSON
            body["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=20.0)) as client:
                resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
                if resp.status_code == 400 and json_schema is not None and "response_format" in resp.text:
                    body.pop("response_format", None)
                    resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"اتصال به {self.name} برقرار نشد: {exc}", retryable=True, provider=self.name) from exc
        if resp.status_code == 401:
            raise LLMError(f"کلید {self.name} نامعتبر است", provider=self.name)
        if resp.status_code == 429:
            raise LLMError(f"محدودیت نرخ {self.name}", retryable=True, provider=self.name)
        if resp.status_code >= 400:
            raise LLMError(f"خطای {self.name} {resp.status_code}: {resp.text[:200]}", retryable=resp.status_code >= 500, provider=self.name)
        data = resp.json()
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError) as exc:
            raise LLMError(f"پاسخ نامعتبر از {self.name}", provider=self.name) from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            model=data.get("model") or self.model,
            provider=self.name,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        if self.name == "ollama":
            return 0.0
        return price_for(self.model, input_tokens, output_tokens)
