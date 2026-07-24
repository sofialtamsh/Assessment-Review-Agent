"""Phase 2 — Language & Logic agent (small model). Batched.

Grammar/clarity of the stem, internal logic (answerable, key consistent with the
explanation), and option quality (parallel lengths, no giveaways, plausible
distractors). Questions are batched (config batch_size) to keep cost low.
"""
from __future__ import annotations

import json

from ...config import load_prompt
from ...llm.base import LLMRunner
from ...schemas import Finding, Question
from .util import q_public, to_findings

PHASE = "phase2_language"


def run(questions: list[Question], runner: LLMRunner) -> list[Finding]:
    prompt = load_prompt(PHASE)
    batch_size = runner.settings.llm.batch_size
    model = runner.model_for(PHASE)
    findings: list[Finding] = []
    for start in range(0, len(questions), batch_size):
        batch = questions[start:start + batch_size]
        payload = {"questions": [q_public(q) for q in batch]}
        result = runner.run(PHASE, prompt, payload, json.dumps(payload))
        findings.extend(to_findings(result.findings, model, PHASE))
    return findings
