"""Reviewer feedback / standing instructions for the agents.

A reviewer can teach an agent something ("distractors must be plausible", "treat
code-output questions as in-scope", ...) targeted at a specific phase. Stored
instructions are appended to that phase's prompt on every future run, so the agent
"remembers" them. `phase="all"` applies to every LLM phase.
"""
from __future__ import annotations

from sqlmodel import select

from .config import load_prompt
from .db import get_session
from .models import AgentInstruction

# phases a reviewer can target, with a short description shown in the UI
TARGETABLE = [
    ("phase2_language", "Language & Logic", "grammar, clarity, option quality, answerability"),
    ("phase3_ambiguity", "Ambiguity & Overlap", "duplicates, cross-set overlap, defensible options"),
    ("phase4_scope", "Scope & Source", "out-of-scope, verbatim lifts vs the session content"),
    ("phase5_pedagogy", "Pedagogy", "Bloom's level, coverage, scenario vs recall"),
    ("phase6_judge", "Judge / Aggregator", "final APPROVE / REVISE / DELETE decision"),
    ("all", "All agents", "applies to every phase above"),
]
_VALID = {p for p, _, _ in TARGETABLE}


def add_instruction(phase: str, text: str, session_id: str | None = None) -> dict:
    if phase not in _VALID:
        raise ValueError(f"unknown phase '{phase}'")
    with get_session() as db:
        row = AgentInstruction(phase=phase, text=text.strip(), session_id=session_id)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _dump(row)


def list_instructions(session_id: str | None = None) -> list[dict]:
    with get_session() as db:
        rows = db.exec(select(AgentInstruction).where(AgentInstruction.active == True)).all()  # noqa: E712
    out = []
    for r in rows:
        if session_id is None or r.session_id is None or r.session_id == session_id:
            out.append(_dump(r))
    return sorted(out, key=lambda d: d["created_at"], reverse=True)


def delete_instruction(instruction_id: int) -> None:
    with get_session() as db:
        row = db.get(AgentInstruction, instruction_id)
        if row:
            row.active = False
            db.add(row)
            db.commit()


def instructions_for(phase: str, session_id: str | None = None) -> list[str]:
    """Active instruction texts that apply to a phase (phase-specific + 'all')."""
    texts = []
    for d in list_instructions(session_id):
        if d["phase"] == phase or d["phase"] == "all":
            texts.append(d["text"])
    return texts


def prompt_for(phase: str, session_id: str | None = None) -> str:
    """Base prompt for a phase + the evaluation's marking scheme + reviewer instructions."""
    base = load_prompt(phase)
    rubric = rubric_block(session_id)
    if rubric:
        base = f"{base}\n\n{rubric}"
    extra = instructions_for(phase, session_id)
    if not extra:
        return base
    lines = "\n".join(f"- {t}" for t in extra)
    return (
        f"{base}\n\n## Reviewer instructions (follow these — they override defaults "
        f"on conflict)\n{lines}\n"
    )


def rubric_block(session_id: str | None) -> str:
    """The evaluation's marking scheme, formatted as an authoritative prompt section.

    Empty when the session has no rubric attached (ordinary units/sessions).
    """
    if not session_id:
        return ""
    from . import store  # lazy: avoids an import cycle at module load

    rubric = store.get_rubric(session_id)
    if not rubric:
        return ""
    text = (rubric.get("text") or "").strip()
    if not text:
        return ""
    return (
        "## Marking scheme (AUTHORITATIVE — evaluate every question against these "
        "criteria; they override the defaults on conflict)\n"
        f"{text}\n"
    )


def _dump(r: AgentInstruction) -> dict:
    return {
        "id": r.id, "phase": r.phase, "text": r.text,
        "session_id": r.session_id, "created_at": r.created_at.isoformat(),
    }
