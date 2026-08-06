"""Phase 4 (Scope & Source) always reports — deterministic fallback + no-content path."""
from __future__ import annotations

from app.graph.nodes.phase4_scope import _deterministic_scope, run
from app.schemas import Chunk, Option, Question


def _q(qid, stem, subtopics=None):
    return Question(question_id=qid, session_id="s", stem=stem,
                    options=[Option(key="A", text="a"), Option(key="B", text="b")],
                    correct_keys=["A"], subtopics=subtopics or [], source_set="examination")


class _EmptyRunner:
    """A runner whose model returns NO findings — simulates a flaky/empty LLM response."""
    def model_for(self, phase):
        return "mock-model"

    def run(self, phase, prompt, payload, payload_text=""):
        from app.llm.base import AgentResult
        return AgentResult(findings=[], tokens_in=1, tokens_out=1)


def test_deterministic_scope_grounded_vs_out_of_scope():
    items = [
        {"question_id": "q_in", "top_ref": "Slide 2", "content_overlap": 0.9,
         "tag_in_scope": True},
        {"question_id": "q_out", "top_ref": "Slide 5", "content_overlap": 0.0,
         "tag_in_scope": False},
    ]
    by_q = {f.question_id: f for f in _deterministic_scope(items, "m")}
    assert by_q["q_in"].check_name == "in_scope" and by_q["q_in"].verdict == "PASS"
    # the offline fallback is conservative: it WARNs (not FAIL) and never cites percentages
    assert by_q["q_out"].check_name == "out_of_scope" and by_q["q_out"].verdict == "WARN"
    assert "%" not in by_q["q_out"].evidence


def test_scope_fallback_leans_in_scope_on_partial_overlap():
    # a topic mentioned in the content (some overlap) is treated as covered, not flagged
    items = [{"question_id": "q1", "top_ref": "Slide 1", "content_overlap": 0.25,
              "tag_in_scope": False}]
    f = _deterministic_scope(items, "m")[0]
    assert f.check_name == "in_scope" and f.verdict == "PASS"


def test_phase4_falls_back_when_llm_returns_nothing():
    chunks = [Chunk(chunk_id="c1", session_id="s", text="gradient descent learning rate "
                    "cost function mean squared error", source_ref="Slide 1")]
    qs = [_q("q1", "What does the learning rate control in gradient descent?"),
          _q("q2", "What is the capital of France?")]
    findings = run(qs, chunks, taught_subtopics=["learning rate"], runner=_EmptyRunner())
    # even though the LLM returned nothing, Phase 4 still classified every question
    assert {f.question_id for f in findings} == {"q1", "q2"}
    assert all(f.phase == "phase4_scope" for f in findings)


def test_phase4_warns_when_no_content():
    qs = [_q("q1", "anything")]
    findings = run(qs, chunks=[], taught_subtopics=[], runner=_EmptyRunner())
    assert findings and findings[0].check_name == "no_content"


def test_phase3_falls_back_to_pass_when_llm_returns_nothing():
    from app.graph.nodes.phase3_ambiguity import run as run3
    qs = [_q("q1", "What is a tensor?"), _q("q2", "Define a matrix.")]
    findings = run3(qs, quiz_questions=[], runner=_EmptyRunner())
    # a clean set now reports PASS per question instead of an empty "no checks fired"
    assert {f.question_id for f in findings} == {"q1", "q2"}
    assert all(f.check_name == "ambiguity_ok" and f.verdict == "PASS" for f in findings)
