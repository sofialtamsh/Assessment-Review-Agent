"""Embeddings with a SQLite cache and pluggable backend.

Default backend "local" uses sentence-transformers if installed; if it isn't
(e.g. a light demo/CI box with no torch), it transparently falls back to a
deterministic hashing embedding so the whole pipeline still runs offline and
duplicate/scope detection stays meaningful (shared vocabulary -> high cosine).
Backend "voyage" uses the Voyage API. Every vector is cached keyed by
sha1(backend|model|text), so re-runs are near-free.
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

from sqlmodel import select

from .config import get_settings
from .db import get_session
from .models import EmbeddingCache

_settings = get_settings()
_HASH_DIM = 512
_TOKEN_RE = re.compile(r"[a-z0-9]+")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding per input text, using the cache where possible."""
    backend, model = _settings.embeddings.backend, _active_model()
    results: list[list[float] | None] = [None] * len(texts)
    misses: list[tuple[int, str]] = []

    with get_session() as db:
        for i, t in enumerate(texts):
            key = _cache_key(backend, model, t)
            row = db.get(EmbeddingCache, key)
            if row is not None:
                results[i] = row.vector
            else:
                misses.append((i, t))

        if misses:
            fresh = _compute([t for _, t in misses])
            for (i, t), vec in zip(misses, fresh):
                results[i] = vec
                db.add(EmbeddingCache(key=_cache_key(backend, model, t), vector=vec))
        db.commit()

    return [r or [] for r in results]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def backend_label() -> str:
    return f"{_settings.embeddings.backend}:{_active_model()}"


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
def _active_model() -> str:
    if _settings.embeddings.backend == "voyage":
        return _settings.embeddings.voyage_model
    if _local_st_model() is not None:
        return _settings.embeddings.local_model
    return "hashing-fallback"


def _compute(texts: list[str]) -> list[list[float]]:
    backend = _settings.embeddings.backend
    if backend == "voyage":
        return _voyage_embed(texts)
    model = _local_st_model()
    if model is not None:
        return [list(map(float, v)) for v in model.encode(texts, normalize_embeddings=True)]
    return [_hash_embed(t) for t in texts]


@lru_cache(maxsize=1)
def _local_st_model():
    """Load sentence-transformers lazily; return None if unavailable."""
    if _settings.embeddings.backend != "local":
        return None
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(_settings.embeddings.local_model)
    except Exception:  # noqa: BLE001 - any import/load failure -> fallback
        return None


def _hash_embed(text: str) -> list[float]:
    """Deterministic hashed bag-of-words vector, L2-normalized."""
    vec = [0.0] * _HASH_DIM
    for tok in _TOKEN_RE.findall(text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        idx = h % _HASH_DIM
        sign = 1.0 if (h >> 17) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _voyage_embed(texts: list[str]) -> list[list[float]]:
    import httpx

    key = _settings.voyage_api_key
    if not key:
        raise RuntimeError("VOYAGE_API_KEY not set but embeddings.backend=voyage")
    resp = httpx.post(
        "https://api.voyageai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {key}"},
        json={"input": texts, "model": _settings.embeddings.voyage_model},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [item["embedding"] for item in data]


def _cache_key(backend: str, model: str, text: str) -> str:
    return hashlib.sha1(f"{backend}|{model}|{text}".encode()).hexdigest()
