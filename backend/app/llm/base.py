"""LLM contract + budget-aware runner.

Every phase's agent produces the same shape: a list of raw finding dicts plus a
token count. Providers differ only in *how* they produce them (real model call vs
deterministic mock). The runner owns model routing, cost accounting, and the
per-run token budget hard stop so agent nodes stay thin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..config import Settings
from ..schemas import CostAccumulator, TokenBudget


@dataclass
class AgentResult:
    findings: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    extra: dict = field(default_factory=dict)  # phase-specific payload (e.g. new question)


class BudgetExceeded(Exception):
    """Raised when a call would push the run past its token limit."""


class LLMProvider(Protocol):
    def run_agent(self, phase: str, model: str, system_prompt: str, payload: dict) -> AgentResult:
        ...


def estimate_tokens(system_prompt: str, payload_text: str) -> int:
    # rough proxy (~4 chars/token) + a fixed output allowance
    return int((len(system_prompt) + len(payload_text)) / 4) + 600


class LLMRunner:
    """Wraps a provider with routing, cost tracking, and budget enforcement."""

    def __init__(self, provider: LLMProvider, settings: Settings,
                 budget: TokenBudget, cost: CostAccumulator):
        self.provider = provider
        self.settings = settings
        self.budget = budget
        self.cost = cost

    def run(self, phase: str, system_prompt: str, payload: dict,
            payload_text: str = "") -> AgentResult:
        model = self.settings.model_for(phase)
        projected = estimate_tokens(system_prompt, payload_text or str(payload))
        if self.budget.would_exceed(projected):
            self.budget.hard_stop = True
            raise BudgetExceeded(
                f"Token budget {self.budget.limit} would be exceeded "
                f"(spent {self.budget.spent}, projected +{projected})."
            )

        result = self.provider.run_agent(phase, model, system_prompt, payload)

        # record cost + budget
        price = self.settings.price_for(model)
        usd = (result.tokens_in / 1e6) * price.get("input", 0.0) + \
              (result.tokens_out / 1e6) * price.get("output", 0.0)
        self.cost.add(phase, model, result.tokens_in, result.tokens_out, usd)
        self.budget.spent += result.tokens_in + result.tokens_out
        if (not self.budget.warned and self.budget.limit > 0
                and self.budget.spent >= self.budget.limit * self.budget.warn_at):
            self.budget.warned = True
        return result

    @property
    def model_for(self):
        return self.settings.model_for
