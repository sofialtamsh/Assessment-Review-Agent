"""Internal domain schemas — the single normalized shape everything flows through.

Every input format (CSV/XLSX/JSON mastersheet + question set, PPT/PDF content)
normalizes into these Pydantic models. Every agent emits `Finding`s (never prose).
"""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["PASS", "WARN", "FAIL"]
JudgeVerdict = Literal["APPROVE", "REVISE", "DELETE"]
QType = Literal["single", "multi", "binary"]
SourceSet = Literal["in_class_quiz", "mcq_assignment", "examination"]
Difficulty = Literal["easy", "medium", "hard"]
BloomLevel = Literal[
    "Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"
]


# --------------------------------------------------------------------------- #
# Ground truth: what was taught (one row per session/unit in the mastersheet)
# --------------------------------------------------------------------------- #
class Session(BaseModel):
    session_id: str
    course: str = ""
    module: str = ""
    unit: str = ""
    topic: str = ""
    subtopics: list[str] = Field(default_factory=list)
    content_path: str | None = None  # link/path to PPT/PDF/notes


class UnitSpec(BaseModel):
    """A logical unit aggregated from the mastersheet's rows (Session + Tutorial +
    MCQ Practice), carrying the links to fetch content and questions from."""
    unit_id: str
    course: str = ""
    module: str = ""            # from the "Topic" column
    unit: str = ""             # the "Unit" column (the session name)
    subtopics: list[str] = Field(default_factory=list)  # from "What to Cover"
    content_url: str | None = None       # session slides (Embedded links / PPT)
    mcq_doc_url: str | None = None        # MCQ Practice doc (the assignment)
    quiz_doc_url: str | None = None       # Tutorial doc (in-class MCQs at the end)
    s_id: str | None = None


# --------------------------------------------------------------------------- #
# The question under review (normalized)
# --------------------------------------------------------------------------- #
class Option(BaseModel):
    key: str        # "A".."D", or "True"/"False" for binary
    text: str


class Question(BaseModel):
    question_id: str
    session_id: str
    course: str = ""
    module: str = ""
    unit: str = ""
    source_set: SourceSet = "mcq_assignment"
    qtype: QType = "single"
    stem: str = ""
    options: list[Option] = Field(default_factory=list)
    correct_keys: list[str] = Field(default_factory=list)
    explanation: str | None = None
    difficulty: Difficulty | None = None
    topic: str | None = None
    subtopics: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)  # original row, for lossless export

    def option_text(self) -> str:
        return " | ".join(f"{o.key}. {o.text}" for o in self.options)

    def searchable_text(self) -> str:
        """Text used for duplicate / semantic comparison."""
        return f"{self.stem} {self.option_text()}".strip()

    @staticmethod
    def make_id(session_id: str, stem: str, source_set: str) -> str:
        h = hashlib.sha1(f"{session_id}|{source_set}|{stem}".encode()).hexdigest()
        return f"q_{h[:10]}"


# --------------------------------------------------------------------------- #
# Session content chunk (RAG over the PPT/PDF)
# --------------------------------------------------------------------------- #
class Chunk(BaseModel):
    chunk_id: str
    session_id: str
    text: str
    source_ref: str = ""            # e.g. "Slide 4" or "PDF p.3"
    embedding: list[float] | None = None


# --------------------------------------------------------------------------- #
# Structured agent output
# --------------------------------------------------------------------------- #
class Finding(BaseModel):
    question_id: str
    phase: str
    check_name: str
    verdict: Verdict
    evidence: str = ""
    suggested_fix: str | None = None
    related_ids: list[str] = Field(default_factory=list)  # sibling Qs (dupes/overlap)
    bloom: BloomLevel | None = None   # phase 5 tags bloom level here
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


class Judgment(BaseModel):
    question_id: str
    verdict: JudgeVerdict
    reason: str = ""
    consolidated_fixes: list[str] = Field(default_factory=list)


class DuplicateCluster(BaseModel):
    question_ids: list[str]
    kind: Literal["exact", "fuzzy", "semantic", "cross_set"]
    detail: str = ""


class SetReport(BaseModel):
    session_id: str
    total_questions: int = 0
    pass_rate: float = 0.0                        # fraction APPROVE
    verdict_counts: dict[str, int] = Field(default_factory=dict)
    key_balance: dict[str, int] = Field(default_factory=dict)
    difficulty_distribution: dict[str, int] = Field(default_factory=dict)
    bloom_distribution: dict[str, int] = Field(default_factory=dict)
    duplicate_clusters: list[DuplicateCluster] = Field(default_factory=list)
    out_of_scope_ids: list[str] = Field(default_factory=list)
    verbatim_lift_ids: list[str] = Field(default_factory=list)
    subtopic_coverage: dict[str, int] = Field(default_factory=dict)   # 0 = gap
    over_tested_subtopics: list[str] = Field(default_factory=list)
    scenario_vs_recall_ratio: float = 0.0


# --------------------------------------------------------------------------- #
# Cost + budget bookkeeping
# --------------------------------------------------------------------------- #
class PhaseCost(BaseModel):
    phase: str
    model: str | None = None
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0


class CostAccumulator(BaseModel):
    per_phase: dict[str, PhaseCost] = Field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return sum(p.tokens_in + p.tokens_out for p in self.per_phase.values())

    @property
    def total_usd(self) -> float:
        return round(sum(p.usd for p in self.per_phase.values()), 6)

    def add(self, phase: str, model: str | None, tin: int, tout: int, usd: float) -> None:
        pc = self.per_phase.setdefault(phase, PhaseCost(phase=phase, model=model))
        pc.model = model or pc.model
        pc.calls += 1
        pc.tokens_in += tin
        pc.tokens_out += tout
        pc.usd = round(pc.usd + usd, 6)


class TokenBudget(BaseModel):
    limit: int = 0            # 0 = unlimited
    spent: int = 0
    warn_at: float = 0.8
    hard_stop: bool = False
    warned: bool = False

    def remaining(self) -> float:
        if self.limit <= 0:
            return float("inf")
        return max(0, self.limit - self.spent)

    def would_exceed(self, projected: int) -> bool:
        if self.limit <= 0:
            return False
        return self.spent + projected > self.limit


class PhaseError(BaseModel):
    phase: str
    message: str
