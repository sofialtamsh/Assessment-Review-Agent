"""LLM provider package: pluggable providers behind one contract, plus a
budget-aware runner that tracks cost and enforces the per-run token hard stop.
"""
from __future__ import annotations

from ..config import Settings, get_settings
from .base import AgentResult, BudgetExceeded, LLMProvider, LLMRunner
from .mock import MockProvider

__all__ = [
    "AgentResult",
    "BudgetExceeded",
    "LLMProvider",
    "LLMRunner",
    "get_provider",
    "make_runner",
]


def get_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    provider = settings.llm.provider.lower()
    if provider == "mock":
        return MockProvider()
    if provider == "openrouter":
        from .openrouter import OpenRouterProvider

        return OpenRouterProvider(settings)
    raise ValueError(f"Unknown llm.provider: {settings.llm.provider}")


def make_runner(budget, cost, settings: Settings | None = None) -> LLMRunner:
    settings = settings or get_settings()
    return LLMRunner(get_provider(settings), settings, budget, cost)
