"""Append-only audit log — every verdict, edit, approval, and regeneration."""
from __future__ import annotations

from sqlmodel import select

from .db import get_session
from .models import AuditLog


def log(action: str, *, actor: str = "system", run_id: str | None = None,
        question_id: str | None = None, detail: dict | None = None) -> None:
    with get_session() as db:
        db.add(AuditLog(action=action, actor=actor, run_id=run_id,
                        question_id=question_id, detail=detail or {}))
        db.commit()


def get_log(run_id: str | None = None, question_id: str | None = None) -> list[dict]:
    with get_session() as db:
        stmt = select(AuditLog).order_by(AuditLog.ts.desc())
        if run_id:
            stmt = stmt.where(AuditLog.run_id == run_id)
        if question_id:
            stmt = stmt.where(AuditLog.question_id == question_id)
        rows = db.exec(stmt).all()
        return [{
            "id": r.id, "ts": r.ts.isoformat(), "action": r.action, "actor": r.actor,
            "run_id": r.run_id, "question_id": r.question_id, "detail": r.detail,
        } for r in rows]
