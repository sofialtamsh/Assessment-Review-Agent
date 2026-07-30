"""Marking-scheme (rubric) ingestion, deterministic compliance, and prompt injection."""
from __future__ import annotations

from conftest import read

from app.ingestion.rubric import (
    parse_criteria_sheet,
    rubric_from_bytes,
    rubric_from_text,
)
from app.report import build_report, evaluate_rubric
from app.schemas import Judgment, Option, Question, RubricCriterion


# --- ingestion ------------------------------------------------------------- #
def test_parse_structured_criteria_sheet():
    criteria = parse_criteria_sheet(read("marking_scheme.csv"), "marking_scheme.csv")
    by_metric = {c.metric: c for c in criteria}
    assert "higher_order_pct" in by_metric
    assert by_metric["higher_order_pct"].comparator == ">="
    assert by_metric["higher_order_pct"].target == "30"
    # a fail-gated hard check
    assert by_metric["out_of_scope_count"].gate == "fail"
    # an unknown metric stays guidance-only (blank metric)
    assert any(c.metric == "" for c in criteria)


def test_rubric_from_bytes_sheet_has_text_summary():
    r = rubric_from_bytes(read("marking_scheme.csv"), "marking_scheme.csv")
    assert r.criteria
    assert "Marking-scheme criteria" in r.text  # summary injected into prompts too


def test_rubric_from_written_text():
    r = rubric_from_text("Every question must map to a CO.", source="pasted")
    assert r.criteria == []
    assert "map to a CO" in r.text


# --- deterministic compliance --------------------------------------------- #
def test_evaluate_rubric_pass_fail_warn_manual():
    criteria = [
        RubricCriterion(name="hots", metric="higher_order_pct", comparator=">=",
                        target="30", gate="warn"),
        RubricCriterion(name="no oos", metric="out_of_scope_count", comparator="==",
                        target="0", gate="fail"),
        RubricCriterion(name="easy cap", metric="easy_pct", comparator="<=",
                        target="50", gate="warn"),
        RubricCriterion(name="CO mapping", metric="", comparator="", target="", gate="info"),
    ]
    values = {"higher_order_pct": 40.0, "out_of_scope_count": 2.0, "easy_pct": 80.0}
    checks = {c.name: c for c in evaluate_rubric(criteria, values)}
    assert checks["hots"].status == "pass"        # 40 >= 30
    assert checks["no oos"].status == "fail"       # 2 != 0, fail-gated
    assert checks["easy cap"].status == "warn"     # 80 > 50, warn-gated
    assert checks["CO mapping"].status == "manual"  # no computable metric


def test_between_comparator():
    c = [RubricCriterion(name="mix", metric="medium_pct", comparator="between", target="30-50")]
    assert evaluate_rubric(c, {"medium_pct": 40.0})[0].status == "pass"
    assert evaluate_rubric(c, {"medium_pct": 10.0})[0].status == "warn"


# --- integration into the report ------------------------------------------ #
def _q(qid, difficulty):
    return Question(question_id=qid, session_id="eval", stem=f"stem {qid}",
                    options=[Option(key="A", text="a"), Option(key="B", text="b")],
                    correct_keys=["A"], difficulty=difficulty, source_set="examination")


def test_build_report_applies_rubric():
    questions = [_q("q1", "easy"), _q("q2", "easy")]
    judgments = [Judgment(question_id="q1", verdict="APPROVE"),
                 Judgment(question_id="q2", verdict="APPROVE")]
    rubric = {"text": "follow these", "criteria": [
        {"name": "easy cap", "metric": "easy_pct", "comparator": "<=",
         "target": "50", "gate": "warn"},
    ]}
    rpt = build_report("eval", questions, [], judgments, rubric=rubric)
    assert rpt.rubric_applied is True
    assert len(rpt.rubric_compliance) == 1
    # both questions easy -> 100% easy -> exceeds the 50% cap -> warn
    assert rpt.rubric_compliance[0].status == "warn"
    assert rpt.rubric_compliance[0].actual == "100"


def test_report_without_rubric_is_unaffected():
    rpt = build_report("eval", [_q("q1", "easy")], [], [])
    assert rpt.rubric_applied is False
    assert rpt.rubric_compliance == []


# --- prompt injection ------------------------------------------------------ #
def test_prompt_injects_saved_rubric():
    from app import store
    from app.instructions import rubric_block
    from app.schemas import Rubric

    store.save_rubric("eval_rubric_test", Rubric(text="AUTH RULES HERE", source="pasted"))
    block = rubric_block("eval_rubric_test")
    assert "Marking scheme" in block
    assert "AUTH RULES HERE" in block
    # a session with no rubric yields nothing
    assert rubric_block("no_such_session") == ""
