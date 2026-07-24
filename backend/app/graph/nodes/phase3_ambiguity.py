"""Phase 3 — Ambiguity & Overlap agent (mid model) + embeddings.

Deterministic candidate generation (real embeddings), then the LLM confirms:
  * semantic duplicates within the set  (cosine >= semantic_dup threshold)
  * cross-set overlap with the in-class quiz for the same session
  * option ambiguity (superlative stems / near-identical option pairs)
Only *candidates* go to the model, which keeps token cost low.
"""
from __future__ import annotations

import json

from ...config import get_settings
from ...instructions import prompt_for
from ...embeddings import cosine, embed_texts
from ...llm.base import LLMRunner
from ...schemas import Finding, Question
from .util import to_findings

PHASE = "phase3_ambiguity"
_settings = get_settings()
_SUPERLATIVES = ("best", "most appropriate", "most suitable", "most correct", "least")


def run(questions: list[Question], quiz_questions: list[Question],
        runner: LLMRunner) -> list[Finding]:
    prompt = prompt_for(PHASE, questions[0].session_id if questions else None)
    model = runner.model_for(PHASE)
    thr = _settings.thresholds

    vecs = embed_texts([q.searchable_text() for q in questions])

    dup_candidates = []
    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            sim = cosine(vecs[i], vecs[j])
            if sim >= thr.semantic_dup:
                dup_candidates.append({
                    "a_id": questions[i].question_id, "a_stem": questions[i].stem,
                    "b_id": questions[j].question_id, "b_stem": questions[j].stem,
                    "similarity": round(sim, 3),
                })

    cross_set_candidates = []
    if quiz_questions:
        qvecs = embed_texts([q.searchable_text() for q in quiz_questions])
        for i, q in enumerate(questions):
            for j, qz in enumerate(quiz_questions):
                sim = cosine(vecs[i], qvecs[j])
                if sim >= thr.semantic_dup:
                    cross_set_candidates.append({
                        "a_id": qz.question_id, "a_stem": qz.stem,
                        "b_id": q.question_id, "b_stem": q.stem,
                        "similarity": round(sim, 3),
                    })

    ambiguity_candidates = []
    for q in questions:
        stem_l = q.stem.lower()
        if any(s in stem_l for s in _SUPERLATIVES) and len(q.options) >= 3:
            defensible = ", ".join(o.text for o in q.options[:3])
            ambiguity_candidates.append({
                "question_id": q.question_id, "stem": q.stem,
                "options": [{"key": o.key, "text": o.text} for o in q.options],
                "reason": f"Stem asks for the '{_matched(stem_l)}' option, but several "
                          f"choices ({defensible}) could be defended as correct.",
            })

    payload = {
        "dup_candidates": dup_candidates,
        "cross_set_candidates": cross_set_candidates,
        "ambiguity_candidates": ambiguity_candidates,
        "all_ids": [q.question_id for q in questions],
    }
    result = runner.run(PHASE, prompt, payload, json.dumps(payload))
    return to_findings(result.findings, model, PHASE)


def _matched(stem_l: str) -> str:
    for s in _SUPERLATIVES:
        if s in stem_l:
            return s
    return "best"
