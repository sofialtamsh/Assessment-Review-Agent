"""Phase 7 — Fixer agent (on-demand, human-triggered).

Regenerates a single question grounded ONLY in that session's content chunks,
then re-runs Phases 2-4 on the new question alone (against its set siblings) so no
unreviewed content can enter an approved set. Returns the candidate question plus
the re-check findings for human side-by-side approval.
"""
from __future__ import annotations

import json

from ...embeddings import cosine, embed_texts
from ...instructions import prompt_for
from ...llm.base import LLMRunner
from ...schemas import Chunk, Finding, Option, Question
from . import phase2_language, phase3_ambiguity, phase4_scope
from .util import to_findings

PHASE = "phase7_fixer"


def run(target: Question, chunks: list[Chunk], siblings: list[Question],
        taught_subtopics: list[str], runner: LLMRunner) -> tuple[Question, list[Finding]]:
    prompt = prompt_for(PHASE, target.session_id)
    model = runner.model_for(PHASE)

    # ground on the chunks most relevant to the target's subtopic/topic
    relevant = _relevant_chunks(target, chunks, k=4)
    payload = {
        "target": {
            "question_id": target.question_id,
            "stem": target.stem,
            "options": [{"key": o.key, "text": o.text} for o in target.options],
            "subtopics": target.subtopics or ([target.topic] if target.topic else []),
        },
        "chunks": [{"ref": c.source_ref, "text": c.text} for c in relevant],
        "siblings": [{"stem": s.stem} for s in siblings if s.question_id != target.question_id],
    }
    result = runner.run(PHASE, prompt, payload, json.dumps(payload))
    new_q = _build_question(target, result.extra.get("question", {}))

    # re-review the candidate on its own before it can be approved
    recheck: list[Finding] = []
    recheck.extend(phase2_language.run([new_q], runner))
    others = [s for s in siblings if s.question_id != target.question_id]
    recheck.extend(phase3_ambiguity.run([new_q] + others, [], runner))
    recheck.extend(phase4_scope.run([new_q], chunks, taught_subtopics, runner))
    return new_q, [f for f in recheck if f.question_id == new_q.question_id]


def _relevant_chunks(q: Question, chunks: list[Chunk], k: int) -> list[Chunk]:
    if not chunks:
        return []
    key = " ".join(q.subtopics) or q.topic or q.stem
    kv = embed_texts([key])[0]
    cv = embed_texts([c.text for c in chunks])
    scored = sorted(zip((cosine(kv, v) for v in cv), chunks),
                    key=lambda t: t[0], reverse=True)
    return [c for _, c in scored[:k]]


def _build_question(target: Question, spec: dict) -> Question:
    options = [Option(key=o.get("key", chr(65 + i)), text=o.get("text", ""))
               for i, o in enumerate(spec.get("options", []))]
    stem = spec.get("stem", "").strip() or target.stem
    new_id = Question.make_id(target.session_id, stem + "|regen", target.source_set)
    return Question(
        question_id=new_id,
        session_id=target.session_id,
        course=target.course, module=target.module, unit=target.unit,
        source_set=target.source_set,
        qtype=spec.get("qtype", target.qtype),
        stem=stem,
        options=options or target.options,
        correct_keys=spec.get("correct_keys", []) or target.correct_keys,
        explanation=spec.get("explanation"),
        difficulty=target.difficulty,
        topic=target.topic,
        subtopics=target.subtopics,
        raw={"regenerated_from": target.question_id},
    )
