"""Review-quality fixes: meaning-based answer-column detection, length-leak, ipynb."""
from __future__ import annotations

import io
import json

from app.graph.nodes.phase1_precheck import run_precheck
from app.ingestion.content import extract_segments
from app.ingestion.questions import parse_questions
from app.schemas import Option, Question


# --- answer column recognized by meaning ---------------------------------- #
def _csv(headers, row):
    return (",".join(headers) + "\n" + ",".join(row)).encode()


def test_answer_key_column_variants_are_recognized():
    for col in ["Correct Answer", "Answer Key", "Ans", "Key", "Correct Option"]:
        data = _csv(
            ["question", "option_a", "option_b", "option_c", "option_d", col],
            ["What is 2+2?", "3", "4", "5", "6", "B"],
        )
        qs = parse_questions(data, "set.csv", default_session="s")
        assert qs and qs[0].correct_keys == ["B"], f"failed for column '{col}'"


def test_answer_column_ignores_explanation_like_names():
    # a column that merely contains 'answer' in an explanation sense must not be used
    data = _csv(
        ["question", "option_a", "option_b", "answer explanation", "key"],
        ["Q?", "x", "y", "because y is right", "B"],
    )
    qs = parse_questions(data, "set.csv", default_session="s")
    assert qs[0].correct_keys == ["B"]  # 'key' wins, not 'answer explanation'


# --- answer-length leak flagged deterministically -------------------------- #
def test_answer_length_leak_flagged():
    q = Question(
        question_id="q1", session_id="s", stem="Pick the right one",
        options=[
            Option(key="A", text="Yes"),
            Option(key="B", text="No"),
            Option(key="C", text="This is by far the most complete and clearly correct choice"),
            Option(key="D", text="Maybe"),
        ],
        correct_keys=["C"], qtype="single", source_set="examination",
    )
    checks = {f.check_name for f in run_precheck([q])}
    assert "answer_length_leak" in checks


def test_no_length_leak_when_balanced():
    q = Question(
        question_id="q1", session_id="s", stem="Pick one",
        options=[Option(key="A", text="alpha term"), Option(key="B", text="beta value"),
                 Option(key="C", text="gamma thing"), Option(key="D", text="delta point")],
        correct_keys=["A"], qtype="single", source_set="examination",
    )
    checks = {f.check_name for f in run_precheck([q])}
    assert "answer_length_leak" not in checks


# --- ipynb (Colab) code files read as content ------------------------------ #
def test_ipynb_cells_extracted():
    nb = {"cells": [
        {"cell_type": "markdown", "source": ["# Pandas basics"]},
        {"cell_type": "code", "source": ["import pandas as pd\n", "df = pd.read_csv('x.csv')"]},
        {"cell_type": "code", "source": []},
    ]}
    segs = extract_segments(json.dumps(nb).encode(), "session.ipynb")
    text = "\n".join(t for _r, t in segs)
    assert "Pandas basics" in text and "read_csv" in text
    assert len(segs) == 2  # empty cell skipped
