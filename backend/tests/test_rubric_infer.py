"""Reverse-engineering a marking scheme from a reference question set."""
from __future__ import annotations

from conftest import read

from app.ingestion.questions import parse_questions
from app.report import build_report, evaluate_rubric
from app.rubric_infer import infer_rubric
from app.schemas import RubricCriterion


def test_infer_from_labelled_set_produces_criteria_and_text():
    qs = parse_questions(read("assignment_session_ds_07.csv"),
                         "assignment_session_ds_07.csv", default_session="ds_07")
    rub = infer_rubric(qs, source="ds_07 assignment")
    metrics = {c.metric for c in rub.criteria}
    # difficulty is labelled in this set -> difficulty bands inferred
    assert {"easy_pct", "medium_pct", "hard_pct"} <= metrics
    # always-on cleanliness + balance criteria
    assert {"max_key_share_pct", "duplicate_count", "verbatim_lift_count"} <= metrics
    assert "reverse-engineered from" in rub.text.lower()
    assert "Marking-scheme criteria" in rub.text  # summary embedded for the LLM phases
    # a fail-gated hard check exists (no duplicates)
    assert any(c.metric == "duplicate_count" and c.gate == "fail" for c in rub.criteria)


def test_infer_from_unlabelled_set_skips_difficulty():
    qs = parse_questions(read("numpy-arithmetic-operators.xlsx"),
                         "numpy-arithmetic-operators.xlsx", default_session="numpy")
    rub = infer_rubric(qs)
    metrics = {c.metric for c in rub.criteria}
    assert "easy_pct" not in metrics          # no difficulty labels -> no difficulty bands
    assert "max_key_share_pct" in metrics     # balance criterion still inferred


def test_inferred_criteria_feed_compliance():
    qs = parse_questions(read("assignment_session_ds_07.csv"),
                         "assignment_session_ds_07.csv", default_session="ds_07")
    rub = infer_rubric(qs)
    # the inferred criteria are consumable by the deterministic checker
    values = {"easy_pct": 40.0, "medium_pct": 40.0, "hard_pct": 20.0,
              "max_key_share_pct": 30.0, "duplicate_count": 0.0,
              "verbatim_lift_count": 0.0, "out_of_scope_count": 0.0}
    checks = evaluate_rubric(rub.criteria, values)
    assert checks and all(c.status in {"pass", "warn", "fail", "manual"} for c in checks)


def test_infer_empty_set():
    assert infer_rubric([]).criteria == []
