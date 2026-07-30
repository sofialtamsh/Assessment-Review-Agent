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
    # a full SQLAlchemy URL (e.g. a hosted Postgres) — set via DATABASE_URL to make
    # review data DURABLE across deploys/restarts. When unset, we use a local SQLite
    # file (fine for dev, but WIPED on ephemeral hosts like Render's free tier).
    database_url: str | None = None

    # secrets from env, never from yaml
    openrouter_api_key: str | None = None
    voyage_api_key: str | None = None
    # lightweight shared-password login (identity/attribution, not hard security)
    shared_password: str = "admin@123"
    auth_secret: str = "arp-dev-secret"
    # external archive of reviewed content (github now, s3 later). Credentials via ENV.
    archive_backend: str = "none"        # none | github | s3
    archive_dir: str = "reviews"
    github_token: str | None = None
    github_repo: str | None = None       # owner/name
    github_branch: str = "main"
    s3_bucket: str | None = None

    def model_for(self, phase: str) -> str:
        return self.models.get(phase, "anthropic/claude-sonnet-4.5")

    def price_for(self, model: str) -> dict[str, float]:
        return self.pricing.get(model, {"input": 0.0, "output": 0.0})

    @property
    def db_url(self) -> str:
        # A hosted database (Postgres) wins — this is what makes data permanent.
        if self.database_url:
            url = self.database_url.strip()
            # normalize the postgres://... form some providers hand out
            if url.startswith("postgres://"):
                url = "postgresql+psycopg2://" + url[len("postgres://"):]
            elif url.startswith("postgresql://"):
                url = "postgresql+psycopg2://" + url[len("postgresql://"):]
            return url
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
    settings.shared_password = os.getenv("ARP_SHARED_PASSWORD", settings.shared_password)
    settings.auth_secret = os.getenv("ARP_AUTH_SECRET", settings.auth_secret)
    settings.database_url = os.getenv("DATABASE_URL") or os.getenv("ARP_DATABASE_URL")
    settings.archive_backend = os.getenv("ARCHIVE_BACKEND", settings.archive_backend)
    settings.archive_dir = os.getenv("ARCHIVE_DIR", settings.archive_dir)
    settings.github_token = os.getenv("GITHUB_TOKEN")
    settings.github_repo = os.getenv("GITHUB_REPO")
    settings.github_branch = os.getenv("GITHUB_BRANCH", settings.github_branch)
    settings.s3_bucket = os.getenv("S3_BUCKET")
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
