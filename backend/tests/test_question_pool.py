"""Ingestion of Google-Sheet / xlsx MCQ "question pools".

Covers the inline-option format (stem + " a) … b) …" in one cell, key in a separate
"Solution" cell) and multi-tab workbooks where only the MCQ-shaped tabs are ingested.
"""
from __future__ import annotations

from conftest import read

from app.ingestion.fetch import looks_like_spreadsheet_source
from app.ingestion.questions import parse_questions


def test_single_sheet_pool_parsed():
    qs = parse_questions(read("Exam_Question_Set.xlsx"), "Exam_Question_Set.xlsx",
                         default_session="eval")
    assert len(qs) > 50
    # every question came out as a real MCQ: options + a resolved answer key
    assert all(q.options for q in qs)
    assert all(q.correct_keys for q in qs)
    # the duplicate header row ("Questions"/"Solution") is not ingested as a question
    assert not any(q.stem.strip().lower() in {"questions", "question"} for q in qs)
    # metadata lifted from the pool columns
    assert all(q.topic for q in qs)
    assert {q.difficulty for q in qs} <= {"easy", "medium", "hard", None}


def test_inline_options_split_from_stem():
    qs = parse_questions(read("Exam_Question_Set.xlsx"), "Exam_Question_Set.xlsx",
                         default_session="eval")
    q = qs[0]
    assert "a)" not in q.stem.lower()          # options were stripped out of the stem
    assert [o.key for o in q.options] == ["A", "B"]
    assert q.qtype == "binary"                  # True/False -> binary
    assert q.correct_keys == ["A"]


def test_multi_tab_pool_ingests_only_mcqs():
    """The pool workbook has MCQs + short/long-answer + fill-in-the-blank tabs;
    only the MCQ tab yields questions (subjective tabs have no options)."""
    qs = parse_questions(read("Prob & Stats Mid exam Question Pool.xlsx"),
                         "Prob & Stats Mid exam Question Pool.xlsx", default_session="eval")
    assert len(qs) > 50
    assert all(q.options for q in qs)
    # a fill-in-the-blank LaTeX cell like "$P(A) + P(B)$" must not fake options
    assert all(len(q.options) >= 2 for q in qs)


def test_spreadsheet_source_routing():
    assert looks_like_spreadsheet_source("https://docs.google.com/spreadsheets/d/ABC/edit#gid=0")
    assert looks_like_spreadsheet_source("https://example.com/questions.xlsx")
    assert not looks_like_spreadsheet_source("https://docs.google.com/document/d/ABC/edit")
    assert not looks_like_spreadsheet_source("https://drive.google.com/file/d/XYZ/view")
