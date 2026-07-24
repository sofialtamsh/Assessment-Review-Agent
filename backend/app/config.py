"""Loads config.yaml and environment overrides into a typed settings object."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BACKEND_DIR / "config.yaml"
PROMPTS_DIR = BACKEND_DIR / "prompts"


class LLMConfig(BaseModel):
    provider: str = "mock"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    batch_size: int = 5
    max_retries: int = 4
    retry_base_delay: float = 1.0


class BudgetConfig(BaseModel):
    token_limit: int = 200_000
    warn_at: float = 0.8


class EmbeddingsConfig(BaseModel):
    backend: str = "local"
    local_model: str = "all-MiniLM-L6-v2"
    voyage_model: str = "voyage-3-lite"
    chunk_tokens: int = 220
    chunk_overlap: int = 40


class Thresholds(BaseModel):
    exact_dup: float = 1.0
    fuzzy_dup: float = 0.90
    semantic_dup: float = 0.86
    scope_retrieval_k: int = 4
    scope_min_similarity: float = 0.30
    verbatim_lift: float = 0.82


class Settings(BaseModel):
    llm: LLMConfig = LLMConfig()
    models: dict[str, str] = {}
    pricing: dict[str, dict[str, float]] = {}
    budget: BudgetConfig = BudgetConfig()
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    thresholds: Thresholds = Thresholds()
    db_path: str = "review.db"

    # secrets from env, never from yaml
    openrouter_api_key: str | None = None
    voyage_api_key: str | None = None

    def model_for(self, phase: str) -> str:
        return self.models.get(phase, "anthropic/claude-sonnet-4.5")

    def price_for(self, model: str) -> dict[str, float]:
        return self.pricing.get(model, {"input": 0.0, "output": 0.0})

    @property
    def db_url(self) -> str:
        path = self.db_path
        if not os.path.isabs(path):
            path = str(BACKEND_DIR / path)
        return f"sqlite:///{path}"


def _load_yaml() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Load backend/.env if present so OPENROUTER_API_KEY etc. can live in a file
    # instead of being exported in the shell each time.
    try:
        from dotenv import load_dotenv

        load_dotenv(BACKEND_DIR / ".env")
    except Exception:  # noqa: BLE001 - dotenv is optional
        pass

    data = _load_yaml()
    settings = Settings(**data)
    settings.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    settings.voyage_api_key = os.getenv("VOYAGE_API_KEY")
    if os.getenv("ARP_DB_PATH"):
        settings.db_path = os.environ["ARP_DB_PATH"]
    # Allow env to force the mock provider (handy for CI / no-key demos).
    forced = os.getenv("LLM_PROVIDER")
    if forced:
        settings.llm.provider = forced
    return settings


def load_prompt(name: str) -> str:
    """Read a prompt file from backend/prompts/ (without the .md extension)."""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
