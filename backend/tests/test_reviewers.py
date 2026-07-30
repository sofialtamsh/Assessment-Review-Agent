"""Auth (shared password), review-history guardrail, activity feed, and export format."""
from __future__ import annotations

import io

from openpyxl import load_workbook

from app import auth, store
from app.export import export_cleaned_xlsx
from app.schemas import Option, Question


# --- auth ------------------------------------------------------------------ #
def test_login_success_and_token():
    r = auth.login("Sofi", "admin@123")
    assert r["name"] == "Sofi"
    assert auth.verify_token("Sofi", r["token"])
    assert not auth.verify_token("Sofi", "bogus")


def test_login_wrong_password():
    import pytest
    with pytest.raises(ValueError):
        auth.login("Sofi", "nope")


# --- review history / guardrail ------------------------------------------- #
def _q(qid, stem):
    return Question(question_id=qid, session_id="u1", stem=stem,
                    options=[Option(key="A", text="a"), Option(key="B", text="b")],
                    correct_keys=["A"], source_set="mcq_assignment")


def test_summary_and_prior_by_unit_and_content():
    qs = [_q("q1", "what is x"), _q("q2", "what is y")]
    report = {"total_questions": 2, "pass_rate": 0.5,
              "verdict_counts": {"APPROVE": 1, "REVISE": 1}, "rubric_applied": False}
    store.save_review_summary(run_id="run_a", session_id="u1", source_set="mcq_assignment",
                              title="Unit 1", reviewer="Ravi", report=report, questions=qs)

    # same unit + set -> found
    prior = store.find_prior_reviews("u1", "mcq_assignment")
    assert prior and prior[0]["reviewer"] == "Ravi"
    assert prior[0]["verdict_counts"]["APPROVE"] == 1

    # identical question content under a DIFFERENT session id -> still found via hash
    chash = store.question_set_hash(qs)
    prior2 = store.find_prior_reviews("other_unit", "mcq_assignment", content_hash=chash)
    assert prior2 and prior2[0]["run_id"] == "run_a"

    # a genuinely different unit + different content -> nothing
    assert store.find_prior_reviews("u_zzz", "in_class_quiz") == []


def test_question_set_hash_order_independent():
    a = [_q("q1", "alpha"), _q("q2", "beta")]
    b = [_q("q2", "beta"), _q("q1", "alpha")]
    assert store.question_set_hash(a) == store.question_set_hash(b)


def test_activity_lists_runs_with_reviewer():
    from app.jobs import manager
    rid = manager.create_run("u_activity", "mcq_assignment", reviewer="Meena")
    act = store.list_activity(50)
    mine = [a for a in act if a["run_id"] == rid]
    assert mine and mine[0]["reviewer"] == "Meena"


# --- export format --------------------------------------------------------- #
def test_reviewed_export_format():
    qs = [Question(question_id="q1", session_id="u1", stem="Pick the operator",
                   options=[Option(key="A", text="/"), Option(key="B", text="//"),
                            Option(key="C", text="%"), Option(key="D", text="**")],
                   correct_keys=["B"], explanation="floor div", difficulty="easy",
                   subtopics=["arithmetic"], source_set="examination")]
    wb = load_workbook(io.BytesIO(export_cleaned_xlsx(qs)))
    ws = wb.active
    assert ws.title == "MCQs"
    rows = list(ws.iter_rows(values_only=True))
    assert list(rows[0]) == ["S. No", "question content", "Option A", "Option B",
                             "Option C", "Option D", "Explanation", "Key", "SUB TOPIC",
                             "Difficulty", "pool", "Image (if any)", "Remarks"]
    r = rows[1]
    assert r[0] == 1 and r[1] == "Pick the operator"
    assert r[7] == "Option B"          # correct key rendered as "Option B"
    assert r[8] == "arithmetic" and r[9] == "easy"
