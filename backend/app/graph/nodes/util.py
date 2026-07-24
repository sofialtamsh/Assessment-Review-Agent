"""Shared helpers for agent nodes: dict->Finding conversion + payload builders."""
from __future__ import annotations

from ...schemas import Finding, Question


def to_findings(raw: list[dict], model: str | None, phase: str | None = None) -> list[Finding]:
    out: list[Finding] = []
    for d in raw:
        try:
            out.append(Finding(
                question_id=str(d.get("question_id", "__set__")),
                phase=phase or str(d.get("phase", "")),
                check_name=str(d.get("check_name", "check")),
                verdict=d.get("verdict", "WARN"),
                evidence=str(d.get("evidence", "")),
                suggested_fix=d.get("suggested_fix") or None,
                related_ids=list(d.get("related_ids") or []),
                bloom=d.get("bloom") or None,
                model=model,
            ))
        except Exception:  # noqa: BLE001 - skip malformed model output, keep the run alive
            continue
    return out


def q_public(q: Question) -> dict:
    """Compact question view sent to agents (no raw dump)."""
    return {
        "question_id": q.question_id,
        "qtype": q.qtype,
        "stem": q.stem,
        "options": [{"key": o.key, "text": o.text} for o in q.options],
        "correct_keys": q.correct_keys,
        "explanation": q.explanation,
        "subtopics": q.subtopics,
    }
