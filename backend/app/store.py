"""Repository helpers: convert between DB rows and domain schemas, and the CRUD
the API + job runner need. Keeps SQL out of the route/graph code.
"""
from __future__ import annotations

import hashlib

from sqlmodel import select

from .db import get_session
from .models import (
    ChunkRow,
    FindingRow,
    JudgmentRow,
    QuestionRow,
    ReviewSummary,
    RunRow,
    SessionRow,
)
from .schemas import Chunk, Finding, Judgment, Option, Question, Session, UnitSpec


# ---- Session -------------------------------------------------------------- #
def save_sessions(sessions: list[Session], owner: str = "") -> None:
    with get_session() as db:
        for s in sessions:
            row = db.get(SessionRow, s.session_id) or SessionRow(session_id=s.session_id)
            row.owner = owner or row.owner
            row.course, row.module, row.unit = s.course, s.module, s.unit
            row.topic, row.subtopics = s.topic, s.subtopics
            row.content_path = s.content_path
            db.add(row)
        db.commit()


def get_session_schema(session_id: str) -> Session | None:
    with get_session() as db:
        r = db.get(SessionRow, session_id)
        if not r:
            return None
        return Session(session_id=r.session_id, course=r.course, module=r.module,
                       unit=r.unit, topic=r.topic, subtopics=list(r.subtopics or []),
                       content_path=r.content_path)


def list_sessions(owner: str | None = None) -> list[Session]:
    with get_session() as db:
        rows = db.exec(select(SessionRow)).all()
    rows = _owned(rows, owner)
    return [Session(session_id=r.session_id, course=r.course, module=r.module,
                    unit=r.unit, topic=r.topic, subtopics=list(r.subtopics or []),
                    content_path=r.content_path) for r in rows]


def _owned(rows: list, owner: str | None):
    """Filter session rows to a reviewer's own uploads. owner=None => no scoping (all).

    Legacy rows with no owner stay visible to everyone so pre-scoping data isn't lost.
    """
    if not owner:
        return rows
    return [r for r in rows if r.owner == owner or not r.owner]


# ---- Units (mastersheet-sourced) ----------------------------------------- #
def save_units(units: list[UnitSpec], owner: str = "") -> None:
    with get_session() as db:
        for u in units:
            row = db.get(SessionRow, u.unit_id) or SessionRow(session_id=u.unit_id)
            row.owner = owner or row.owner
            row.course, row.module, row.unit = u.course, u.module, u.unit
            row.topic = u.unit
            row.subtopics = u.subtopics
            row.content_path = u.content_url
            row.tutorial_url = u.tutorial_url
            row.mcq_doc_url = u.mcq_doc_url
            row.quiz_doc_url = u.quiz_doc_url
            db.add(row)
        db.commit()


def list_units(owner: str | None = None) -> list[dict]:
    with get_session() as db:
        rows = db.exec(select(SessionRow)).all()
        out = []
        for r in _owned(rows, owner):
            out.append({
                "unit_id": r.session_id, "course": r.course, "module": r.module,
                "unit": r.unit, "subtopics": list(r.subtopics or []),
                "has_content": bool(r.content_path),
                "content_parsed": r.content_parsed,
                "has_tutorial": bool(r.tutorial_url),
                "has_mcq_assignment": bool(r.mcq_doc_url),
                "has_in_class_quiz": bool(r.quiz_doc_url),
                "prepared_sets": list(r.prepared_sets or []),
            })
        return out


def get_unit_row(unit_id: str) -> SessionRow | None:
    with get_session() as db:
        return db.get(SessionRow, unit_id)


# ---- Batches (multiple units reviewed separately in one action) ----------- #
def save_batch(batch_id: str, source_set: str, items: list[dict]) -> None:
    from .models import BatchRow
    with get_session() as db:
        db.add(BatchRow(batch_id=batch_id, source_set=source_set, items=items))
        db.commit()


def get_batch(batch_id: str) -> dict | None:
    from .models import BatchRow
    with get_session() as db:
        r = db.get(BatchRow, batch_id)
        if not r:
            return None
        return {"batch_id": r.batch_id, "source_set": r.source_set,
                "items": list(r.items or []), "created_at": r.created_at.isoformat()}


def save_rubric(session_id: str, rubric) -> None:
    """Attach a marking scheme (Rubric) to a session/evaluation row."""
    with get_session() as db:
        r = db.get(SessionRow, session_id) or SessionRow(session_id=session_id)
        r.rubric_text = rubric.text or None
        r.rubric_criteria = [c.model_dump() for c in rubric.criteria]
        r.rubric_source = rubric.source or None
        db.add(r)
        db.commit()


def get_rubric(session_id: str) -> dict | None:
    """Return {text, criteria, source} for a session, or None if no rubric attached."""
    with get_session() as db:
        r = db.get(SessionRow, session_id)
        if not r:
            return None
        text = r.rubric_text or ""
        criteria = list(r.rubric_criteria or [])
        if not text and not criteria:
            return None
        return {"text": text, "criteria": criteria, "source": r.rubric_source or ""}


# ---- Review history / guardrail ------------------------------------------ #
def unit_key(session_id: str, source_set: str) -> str:
    return f"{session_id}:{source_set}"


def question_set_hash(questions: list[Question]) -> str:
    """Order-independent fingerprint of a question set (stems + option texts)."""
    parts = []
    for q in questions:
        opts = "|".join(sorted((o.text or "").strip().lower() for o in q.options))
        parts.append((q.stem or "").strip().lower() + "::" + opts)
    return hashlib.sha1("\n".join(sorted(parts)).encode()).hexdigest()


def save_review_summary(*, run_id: str, session_id: str, source_set: str, title: str,
                        reviewer: str, report: dict | None,
                        questions: list[Question]) -> None:
    report = report or {}
    rubric = {
        "applied": bool(report.get("rubric_applied")),
        "fails": sum(1 for c in report.get("rubric_compliance", []) if c.get("status") == "fail"),
        "warns": sum(1 for c in report.get("rubric_compliance", []) if c.get("status") == "warn"),
    }
    with get_session() as db:
        db.add(ReviewSummary(
            unit_key=unit_key(session_id, source_set),
            content_hash=question_set_hash(questions),
            run_id=run_id, session_id=session_id, source_set=source_set,
            title=title or session_id, reviewer=reviewer or "unknown",
            total_questions=report.get("total_questions", len(questions)),
            pass_rate=report.get("pass_rate", 0.0),
            verdict_counts=report.get("verdict_counts", {}),
            rubric=rubric,
        ))
        db.commit()


def _summary_dict(r: ReviewSummary) -> dict:
    return {
        "run_id": r.run_id, "session_id": r.session_id, "source_set": r.source_set,
        "title": r.title, "reviewer": r.reviewer, "total_questions": r.total_questions,
        "pass_rate": r.pass_rate, "verdict_counts": dict(r.verdict_counts or {}),
        "rubric": dict(r.rubric or {}), "created_at": r.created_at.isoformat(),
    }


def find_prior_reviews(session_id: str, source_set: str,
                       content_hash: str = "", exclude_run_id: str = "") -> list[dict]:
    """Prior COMPLETED reviews that match this unit+set OR the identical question set."""
    key = unit_key(session_id, source_set)
    with get_session() as db:
        rows = db.exec(select(ReviewSummary)).all()
    hits = [
        r for r in rows
        if r.run_id != exclude_run_id
        and (r.unit_key == key or (content_hash and r.content_hash == content_hash))
    ]
    hits.sort(key=lambda r: r.created_at, reverse=True)
    return [_summary_dict(r) for r in hits]


def list_activity(limit: int = 25) -> list[dict]:
    """Recent reviews (in-progress + completed) for the activity feed."""
    with get_session() as db:
        rows = db.exec(select(RunRow)).all()
    rows.sort(key=lambda r: r.updated_at, reverse=True)
    out = []
    for r in rows[:limit]:
        report = r.report or {}
        sess = db_session_title(r.session_id)
        out.append({
            "run_id": r.run_id, "session_id": r.session_id, "source_set": r.source_set,
            "reviewer": r.reviewer or "unknown", "status": r.status,
            "title": sess, "total_questions": report.get("total_questions", 0),
            "verdict_counts": report.get("verdict_counts", {}),
            "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
        })
    return out


def db_session_title(session_id: str) -> str:
    with get_session() as db:
        r = db.get(SessionRow, session_id)
        if not r:
            return session_id
        return r.unit or r.topic or session_id


def mark_prepared(unit_id: str, source_set: str) -> None:
    with get_session() as db:
        r = db.get(SessionRow, unit_id)
        if not r:
            return
        prepared = list(r.prepared_sets or [])
        if source_set not in prepared:
            prepared.append(source_set)
        r.prepared_sets = prepared
        r.content_parsed = True
        db.add(r)
        db.commit()


# ---- Questions ------------------------------------------------------------ #
def _q_to_row(q: Question) -> QuestionRow:
    return QuestionRow(
        question_id=q.question_id, session_id=q.session_id, source_set=q.source_set,
        qtype=q.qtype, stem=q.stem,
        options=[o.model_dump() for o in q.options], correct_keys=q.correct_keys,
        explanation=q.explanation, difficulty=q.difficulty, topic=q.topic,
        subtopics=q.subtopics, raw=q.raw,
    )


def _row_to_q(r: QuestionRow) -> Question:
    return Question(
        question_id=r.question_id, session_id=r.session_id, source_set=r.source_set,
        qtype=r.qtype, stem=r.stem,
        options=[Option(**o) for o in (r.options or [])], correct_keys=list(r.correct_keys or []),
        explanation=r.explanation, difficulty=r.difficulty, topic=r.topic,
        subtopics=list(r.subtopics or []), raw=r.raw or {},
    )


def save_questions(questions: list[Question]) -> None:
    with get_session() as db:
        for q in questions:
            existing = db.get(QuestionRow, q.question_id)
            row = _q_to_row(q)
            if existing:
                row.status = existing.status
                row.edited = existing.edited
                db.merge(row)
            else:
                db.add(row)
        db.commit()


def load_questions(session_id: str, source_set: str, include_deleted: bool = True) -> list[Question]:
    with get_session() as db:
        stmt = select(QuestionRow).where(
            QuestionRow.session_id == session_id,
            QuestionRow.source_set == source_set,
        )
        rows = db.exec(stmt).all()
        if not include_deleted:
            rows = [r for r in rows if r.status != "deleted"]
        return [_row_to_q(r) for r in rows]


def load_questions_by_session(session_id: str) -> list[Question]:
    with get_session() as db:
        rows = db.exec(select(QuestionRow).where(QuestionRow.session_id == session_id)).all()
        return [_row_to_q(r) for r in rows]


def get_question(question_id: str) -> tuple[Question, str] | None:
    with get_session() as db:
        r = db.get(QuestionRow, question_id)
        if not r:
            return None
        return _row_to_q(r), r.status


def upsert_question(q: Question, status: str | None = None, edited: bool | None = None) -> None:
    with get_session() as db:
        existing = db.get(QuestionRow, q.question_id)
        row = _q_to_row(q)
        if existing:
            row.status = status if status is not None else existing.status
            row.edited = edited if edited is not None else existing.edited
            db.merge(row)
        else:
            row.status = status or "pending"
            row.edited = bool(edited)
            db.add(row)
        db.commit()


def set_question_status(question_id: str, status: str) -> None:
    with get_session() as db:
        r = db.get(QuestionRow, question_id)
        if r:
            r.status = status
            db.add(r)
            db.commit()


# ---- Chunks --------------------------------------------------------------- #
def save_chunks(chunks: list[Chunk]) -> None:
    with get_session() as db:
        for c in chunks:
            db.merge(ChunkRow(chunk_id=c.chunk_id, session_id=c.session_id,
                              text=c.text, source_ref=c.source_ref))
        db.commit()


def load_chunks(session_id: str) -> list[Chunk]:
    with get_session() as db:
        rows = db.exec(select(ChunkRow).where(ChunkRow.session_id == session_id)).all()
        return [Chunk(chunk_id=r.chunk_id, session_id=r.session_id, text=r.text,
                      source_ref=r.source_ref) for r in rows]


# ---- Findings & judgments (per run) --------------------------------------- #
def save_findings(run_id: str, findings: list[Finding]) -> None:
    with get_session() as db:
        for f in findings:
            db.add(FindingRow(
                run_id=run_id, question_id=f.question_id, phase=f.phase,
                check_name=f.check_name, verdict=f.verdict, evidence=f.evidence,
                suggested_fix=f.suggested_fix, related_ids=f.related_ids,
                bloom=f.bloom, model=f.model,
                tokens_in=f.tokens_in, tokens_out=f.tokens_out,
            ))
        db.commit()


def load_findings(run_id: str) -> list[Finding]:
    with get_session() as db:
        rows = db.exec(select(FindingRow).where(FindingRow.run_id == run_id)).all()
        return [Finding(
            question_id=r.question_id, phase=r.phase, check_name=r.check_name,
            verdict=r.verdict, evidence=r.evidence, suggested_fix=r.suggested_fix,
            related_ids=list(r.related_ids or []), bloom=r.bloom, model=r.model,
            tokens_in=r.tokens_in, tokens_out=r.tokens_out,
        ) for r in rows]


def replace_question_findings(run_id: str, question_id: str, findings: list[Finding]) -> None:
    """Used after a regenerate/edit: drop old findings for the question, add new."""
    with get_session() as db:
        rows = db.exec(select(FindingRow).where(
            FindingRow.run_id == run_id, FindingRow.question_id == question_id)).all()
        for r in rows:
            db.delete(r)
        db.commit()
    save_findings(run_id, findings)


def save_judgments(run_id: str, judgments: list[Judgment]) -> None:
    with get_session() as db:
        for j in judgments:
            db.add(JudgmentRow(run_id=run_id, question_id=j.question_id,
                               verdict=j.verdict, reason=j.reason,
                               consolidated_fixes=j.consolidated_fixes))
        db.commit()


def load_judgments(run_id: str) -> list[Judgment]:
    with get_session() as db:
        rows = db.exec(select(JudgmentRow).where(JudgmentRow.run_id == run_id)).all()
        return [Judgment(question_id=r.question_id, verdict=r.verdict, reason=r.reason,
                         consolidated_fixes=list(r.consolidated_fixes or [])) for r in rows]


def upsert_judgment(run_id: str, judgment: Judgment) -> None:
    with get_session() as db:
        rows = db.exec(select(JudgmentRow).where(
            JudgmentRow.run_id == run_id,
            JudgmentRow.question_id == judgment.question_id)).all()
        for r in rows:
            db.delete(r)
        db.add(JudgmentRow(run_id=run_id, question_id=judgment.question_id,
                           verdict=judgment.verdict, reason=judgment.reason,
                           consolidated_fixes=judgment.consolidated_fixes))
        db.commit()
