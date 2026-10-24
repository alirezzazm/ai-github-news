"""Provider-agnostic LLM interface."""
from __future__ import annotations

from dataclasses import dataclass


class LLMError(Exception):
    """Any failure talking to a provider (auth, network, bad output)."""

    def __init__(self, message: str, *, retryable: bool = False, provider: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.provider = provider


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMProvider:
    name: str = "base"
    model: str = ""

    def complete(self, system: str, user: str, *, max_tokens: int, json_schema: dict | None = None) -> LLMResponse:
        raise NotImplementedError

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0


# USD per 1M tokens (input, output). Unknown models cost 0 in the usage report.
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.5, 10.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.0, 8.0),
}


def price_for(model: str, input_tokens: int, output_tokens: int) -> float:
    for key, (pi, po) in PRICES.items():
        if model.startswith(key):
            return round((input_tokens * pi + output_tokens * po) / 1_000_000, 6)
    return 0.0
