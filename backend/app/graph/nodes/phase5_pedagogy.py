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
from .util import q_public, to_findings

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
    return to_findings(result.findings, model, PHASE)
