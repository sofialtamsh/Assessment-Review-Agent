"""SQLModel persistence tables.

We keep the store simple: normalized questions/sessions/chunks, an embedding
cache, run records with serialized report + cost, findings, judgments, and an
append-only audit log. JSON columns hold the richer nested structures.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SessionRow(SQLModel, table=True):
    __tablename__ = "sessions"
    session_id: str = Field(primary_key=True)
    course: str = ""
    module: str = ""
    unit: str = ""
    topic: str = ""
    subtopics: list = Field(default_factory=list, sa_column=Column(JSON))
    content_path: Optional[str] = None
    content_parsed: bool = False
    # links harvested from the mastersheet for auto-sourcing questions
    tutorial_url: Optional[str] = None   # Tutorial cheat-sheet (extra reference content)
    mcq_doc_url: Optional[str] = None
    quiz_doc_url: Optional[str] = None
    prepared_sets: list = Field(default_factory=list, sa_column=Column(JSON))
    # marking scheme / rubric (used by evaluation runs): written guidance + structured
    # criteria + a provenance label. Empty on ordinary units/sessions.
    rubric_text: Optional[str] = None
    rubric_criteria: list = Field(default_factory=list, sa_column=Column(JSON))
    rubric_source: Optional[str] = None


class QuestionRow(SQLModel, table=True):
    __tablename__ = "questions"
    question_id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    source_set: str = "mcq_assignment"
    qtype: str = "single"
    stem: str = ""
    options: list = Field(default_factory=list, sa_column=Column(JSON))
    correct_keys: list = Field(default_factory=list, sa_column=Column(JSON))
    explanation: Optional[str] = None
    difficulty: Optional[str] = None
    topic: Optional[str] = None
    subtopics: list = Field(default_factory=list, sa_column=Column(JSON))
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # human-in-the-loop status: pending | approved | deleted | revised
    status: str = "pending"
    edited: bool = False


class ChunkRow(SQLModel, table=True):
    __tablename__ = "chunks"
    chunk_id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    text: str = ""
    source_ref: str = ""
    embedding: Optional[list] = Field(default=None, sa_column=Column(JSON))


class EmbeddingCache(SQLModel, table=True):
    __tablename__ = "embedding_cache"
    # key = sha1(backend|model|text)
    key: str = Field(primary_key=True)
    vector: list = Field(default_factory=list, sa_column=Column(JSON))


class RunRow(SQLModel, table=True):
    __tablename__ = "runs"
    run_id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    source_set: str = "mcq_assignment"
    status: str = "queued"            # queued | running | completed | failed | budget_stopped
    current_phase: str = ""
    completed_phases: list = Field(default_factory=list, sa_column=Column(JSON))
    report: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    cost: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    budget: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    errors: list = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class FindingRow(SQLModel, table=True):
    __tablename__ = "findings"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    question_id: str = Field(index=True)
    phase: str = ""
    check_name: str = ""
    verdict: str = "PASS"
    evidence: str = ""
    suggested_fix: Optional[str] = None
    related_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    bloom: Optional[str] = None
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0


class JudgmentRow(SQLModel, table=True):
    __tablename__ = "judgments"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    question_id: str = Field(index=True)
    verdict: str = "APPROVE"
    reason: str = ""
    consolidated_fixes: list = Field(default_factory=list, sa_column=Column(JSON))


class BatchRow(SQLModel, table=True):
    __tablename__ = "batches"
    batch_id: str = Field(primary_key=True)
    source_set: str = ""
    items: list = Field(default_factory=list, sa_column=Column(JSON))  # [{unit_id,unit,run_id,...}]
    created_at: datetime = Field(default_factory=_now)


class AgentInstruction(SQLModel, table=True):
    __tablename__ = "agent_instructions"
    id: Optional[int] = Field(default=None, primary_key=True)
    phase: str = Field(index=True)     # phase2_language ... phase6_judge, or "all"
    text: str = ""
    session_id: Optional[str] = Field(default=None, index=True)  # None = global
    active: bool = True
    created_at: datetime = Field(default_factory=_now)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=_now, index=True)
    run_id: Optional[str] = Field(default=None, index=True)
    question_id: Optional[str] = Field(default=None, index=True)
    action: str = ""                 # e.g. verdict, approve, delete, edit, regenerate
    actor: str = "system"            # "system" | "human"
    detail: dict = Field(default_factory=dict, sa_column=Column(JSON))
