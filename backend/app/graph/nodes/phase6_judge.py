"""Phase 6 — Judge / Aggregator agent.

Merges every finding per question into a single verdict (APPROVE / REVISE /
DELETE) with a one-line reason and a consolidated fix list. Set-level findings
(question_id == "__set__") are excluded from per-question judgment.
"""
from __future__ import annotations

import json

from ...config import load_prompt
from ...llm.base import LLMRunner
from ...schemas import Finding, Judgment, Question

PHASE = "phase6_judge"


def run(questions: list[Question], findings: list[Finding],
        runner: LLMRunner) -> list[Judgment]:
    prompt = load_prompt(PHASE)
    serial_findings = [
        {
            "question_id": f.question_id, "phase": f.phase, "check_name": f.check_name,
            "verdict": f.verdict, "evidence": f.evidence, "suggested_fix": f.suggested_fix,
        }
        for f in findings if f.question_id != "__set__"
    ]
    payload = {
        "questions": [q.question_id for q in questions],
        "findings": serial_findings,
    }
    result = runner.run(PHASE, prompt, payload, json.dumps(payload))

    judgments: list[Judgment] = []
    for d in result.findings:
        try:
            judgments.append(Judgment(
                question_id=str(d["question_id"]),
                verdict=d.get("verdict", "REVISE"),
                reason=str(d.get("reason", "")),
                consolidated_fixes=list(d.get("consolidated_fixes") or []),
            ))
        except Exception:  # noqa: BLE001
            continue

    # Safety net: any question the judge skipped defaults to REVISE if it has a
    # non-PASS finding, else APPROVE — nothing silently disappears.
    judged = {j.question_id for j in judgments}
    bad_ids = {f.question_id for f in findings if f.verdict in {"WARN", "FAIL"}}
    for q in questions:
        if q.question_id not in judged:
            verdict = "REVISE" if q.question_id in bad_ids else "APPROVE"
            judgments.append(Judgment(question_id=q.question_id, verdict=verdict,
                                      reason="Auto-filled (judge returned no verdict)."))
    return judgments
