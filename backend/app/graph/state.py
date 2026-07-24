"""LangGraph shared-state schema for a review run.

`findings` and `errors` use append reducers so each phase node contributes without
clobbering earlier phases. The per-run LLMRunner (with its budget + cost) and the
static context (quiz questions, chunks, taught subtopics) are closed over by the
graph nodes rather than living in state, so state stays small and mergeable.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from ..schemas import Chunk, Finding, Judgment, PhaseError, Question, SetReport


class ReviewState(TypedDict, total=False):
    run_id: str
    session_id: str
    questions: list[Question]
    findings: Annotated[list[Finding], operator.add]
    judgments: list[Judgment]
    set_report: SetReport | None
    current_phase: str
    errors: Annotated[list[PhaseError], operator.add]


class GraphContext:
    """Everything the nodes need beyond the mutable state, built once per run."""

    def __init__(self, runner, quiz_questions: list[Question],
                 chunks: list[Chunk], taught_subtopics: list[str]):
        self.runner = runner
        self.quiz_questions = quiz_questions
        self.chunks = chunks
        self.taught_subtopics = taught_subtopics
