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

from ...config import get_settings
from ...instructions import prompt_for
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
    prompt = prompt_for(PHASE, questions[0].session_id if questions else None)
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
    findings = to_findings(result.findings, model, PHASE)
    # Robustness: if the model returns nothing/malformed, don't silently skip scope —
    # classify each question deterministically from the RAG signals we already computed
    # (grounding against the slides + cheat-sheet). Guarantees Phase 4 always reports.
    if not findings:
        findings = _deterministic_scope(items, model)
    return findings


def _deterministic_scope(items: list[dict], model: str | None) -> list[Finding]:
    """Conservative scope fallback used only when the LLM returns nothing. Without the
    model we can't judge meaning, so we DON'T hard-fail on term overlap: a topic named on
    a slide is usually expanded on in the session (e.g. 'pandas' implies reading CSVs,
    loading data). We treat a question as in-scope if its subtopic was taught or it shares
    any real overlap with the content, and only softly WARN when we see essentially none —
    no confusing percentages."""
    raw: list[dict] = []
    for it in items:
        qid = it["question_id"]
        top = it.get("top_ref", "")
        overlap = it.get("content_overlap", 0.0)
        # lenient: tagged-in-scope, OR any meaningful overlap, OR a shared phrase
        grounded = (it.get("tag_in_scope") or overlap >= 0.2
                    or it.get("shared_phrase", 0) >= 3)
        if not grounded and overlap < 0.05:
            raw.append({
                "question_id": qid, "phase": PHASE, "check_name": "out_of_scope",
                "verdict": "WARN",
                "evidence": (f"Could not confirm this is covered by the session content "
                             f"(closest reference: {top}). Please verify against the "
                             f"slides / cheat-sheet / code file."),
                "suggested_fix": "Confirm it's taught this session, or replace it.",
            })
        elif (it.get("numeric_overlap", 0) >= 2
              and it.get("shared_phrase", 0) >= it.get("verbatim_phrase_min", 3)):
            raw.append({
                "question_id": qid, "phase": PHASE, "check_name": "verbatim_lift",
                "verdict": "WARN",
                "evidence": (f"Closely mirrors a worked example in {top} — it may test recall "
                             f"of that example rather than understanding."),
                "suggested_fix": "Change the numbers/scenario so it tests understanding.",
            })
        else:
            raw.append({
                "question_id": qid, "phase": PHASE, "check_name": "in_scope", "verdict": "PASS",
                "evidence": f"Covered by the session content (closest reference: {top}).",
            })
    return to_findings(raw, model, PHASE)


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
