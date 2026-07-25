"""Phase 5 — Pedagogy agent (mid model).

Bloom's taxonomy per question + set-level coverage: which taught subtopics have
zero questions, which are over-tested, scenario-vs-recall ratio, and a check that
concept questions don't smuggle in code.
"""
from __future__ import annotations

import json

from ...instructions import prompt_for
from ...llm.base import LLMRunner
from ...schemas import Finding, Question
from .util import classify_bloom, q_public, to_findings

PHASE = "phase5_pedagogy"


def run(questions: list[Question], taught_subtopics: list[str],
        runner: LLMRunner) -> list[Finding]:
    prompt = prompt_for(PHASE, questions[0].session_id if questions else None)
    model = runner.model_for(PHASE)
    payload = {
        "questions": [q_public(q) for q in questions],
        "taught_subtopics": taught_subtopics,
    }
    result = runner.run(PHASE, prompt, payload, json.dumps(payload))
    findings = to_findings(result.findings, model, PHASE)

    # Guarantee exactly one Bloom level per question — the LLM sometimes omits the
    # `bloom` field, which would leave the dashboard's Bloom chart empty.
    have_bloom: set[str] = set()
    for f in findings:
        if f.check_name == "bloom_classified":
            if not f.bloom:
                q = next((x for x in questions if x.question_id == f.question_id), None)
                f.bloom = classify_bloom(q.stem) if q else "Understand"
            have_bloom.add(f.question_id)
    for q in questions:
        if q.question_id not in have_bloom:
            b = classify_bloom(q.stem)
            findings.append(Finding(
                question_id=q.question_id, phase=PHASE, check_name="bloom_classified",
                verdict="PASS", evidence=f"Bloom level: {b}.", bloom=b, model=model,
            ))
    return findings
