"""Phase 4 — Scope & Source agent (mid model, RAG over session content).

Scope grounding must be robust regardless of embedding quality (the offline
fallback is lexical), so for each question we compute several deterministic
signals against the taught content and hand them to the agent:
  * tag_in_scope   — the question's tagged subtopic/topic was taught this session
  * content_overlap — fraction of the question's salient terms present in the content
  * max_sim        — best embedding cosine to any chunk (auxiliary)
  * numeric_overlap — distinct numbers shared with the best chunk
  * shared_phrase  — longest shared token n-gram with the best chunk
The agent then classifies each question out_of_scope / verbatim_lift / in_scope.
"""
from __future__ import annotations

import json
import re

from ...config import get_settings, load_prompt
from ...embeddings import cosine, embed_texts
from ...llm.base import LLMRunner
from ...schemas import Chunk, Finding, Question
from .util import to_findings

PHASE = "phase4_scope"
_settings = get_settings()
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")
_STOP = {
    "the", "a", "an", "of", "to", "in", "is", "are", "and", "or", "for", "on",
    "what", "which", "does", "do", "with", "that", "this", "as", "by", "be",
    "it", "its", "from", "at", "if", "will", "can", "how", "when", "following",
    "select", "all", "apply", "true", "false", "value", "values", "model",
    "question", "given", "using", "into", "not", "no", "one", "two", "more",
    "than", "each", "any", "about", "toward", "set", "used", "use",
}


def run(questions: list[Question], chunks: list[Chunk],
        taught_subtopics: list[str], runner: LLMRunner) -> list[Finding]:
    prompt = load_prompt(PHASE)
    model = runner.model_for(PHASE)

    if not chunks:
        raw = [{
            "question_id": q.question_id, "phase": PHASE, "check_name": "no_content",
            "verdict": "WARN",
            "evidence": "No session content was provided, so scope cannot be verified.",
            "suggested_fix": "Upload the session PPT/PDF to enable scope checking.",
        } for q in questions]
        return to_findings(raw, None)

    taught = {t.lower().strip() for t in (taught_subtopics or [])}
    content_tokens = set()
    for c in chunks:
        content_tokens |= _salient(c.text)

    chunk_texts = [c.text for c in chunks]
    chunk_vecs = embed_texts(chunk_texts)
    q_vecs = embed_texts([q.searchable_text() for q in questions])
    chunk_token_sets = [_tokens(t) for t in chunk_texts]
    chunk_num_sets = [set(_NUM_RE.findall(t)) for t in chunk_texts]

    items = []
    for qi, q in enumerate(questions):
        # best chunk by lexical overlap (robust) with embedding cosine as tiebreak
        q_tokens = _tokens(q.searchable_text())
        best_ci, best_lex = 0, -1.0
        for ci in range(len(chunks)):
            lex = len(q_tokens & chunk_token_sets[ci])
            sim = cosine(q_vecs[qi], chunk_vecs[ci])
            score = lex + sim  # lexical dominates, cosine breaks ties
            if score > best_lex:
                best_lex, best_ci = score, ci
        top = chunks[best_ci]

        q_salient = _salient(q.searchable_text())
        content_overlap = (len(q_salient & content_tokens) / len(q_salient)) if q_salient else 0.0
        tag_in_scope = _tag_in_scope(q, taught)
        q_nums = set(_NUM_RE.findall(q.searchable_text()))
        numeric_overlap = len(q_nums & chunk_num_sets[best_ci])
        shared_phrase = _longest_shared_ngram(
            _seq(q.searchable_text()), _seq(top.text)
        )
        items.append({
            "question_id": q.question_id, "stem": q.stem,
            "top_ref": top.source_ref, "top_text": top.text[:400],
            "max_sim": round(max(cosine(q_vecs[qi], v) for v in chunk_vecs), 3),
            "content_overlap": round(content_overlap, 3),
            "tag_in_scope": tag_in_scope,
            "numeric_overlap": numeric_overlap,
            "shared_phrase": shared_phrase,
            "min_overlap": 0.33,
            "verbatim_phrase_min": 3,
            "_q": q,  # kept local; stripped before sending
        })

    payload = {"items": [_strip(i) for i in items]}
    result = runner.run(PHASE, prompt, payload, json.dumps(payload))
    return to_findings(result.findings, model, PHASE)


def _tag_in_scope(q: Question, taught: set[str]) -> bool:
    tags = {t.lower().strip() for t in (q.subtopics or [])}
    if q.topic:
        tags.add(q.topic.lower().strip())
    return bool(tags & taught)


def _strip(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _salient(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall(text.lower()) if t not in _STOP and len(t) > 1}


def _seq(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _longest_shared_ngram(a: list[str], b: list[str]) -> int:
    """Longest contiguous token run shared between a and b (classic DP)."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best
