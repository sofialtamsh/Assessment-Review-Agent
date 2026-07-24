"""Ingestion normalization + the token-budget hard stop."""
from app.graph.build import build_graph
from app.graph.state import GraphContext
from app.llm import make_runner
from app.schemas import CostAccumulator, TokenBudget


def test_ingestion_normalizes(sample_questions):
    assert len(sample_questions) == 15
    by_id = {q.question_id: q for q in sample_questions}
    # binary type inferred / preserved
    assert by_id["q08"].qtype == "binary"
    # multi type preserved
    assert by_id["q11"].qtype == "multi"
    # options + keys parsed
    assert [o.key for o in by_id["q01"].options] == ["A", "B", "C", "D"]
    assert by_id["q02"].correct_keys == ["A"]


def test_content_chunking(sample_chunks):
    assert len(sample_chunks) >= 5
    assert any("50 + 30" in c.text for c in sample_chunks)  # worked-example slide
    assert all(c.source_ref for c in sample_chunks)


def test_budget_hard_stop(sample_questions, sample_quiz, sample_chunks, taught_subtopics):
    # a tiny limit trips the hard stop; deterministic Phase 1 still completes and
    # the run remains usable (no crash), errors are recorded.
    budget = TokenBudget(limit=200, warn_at=0.8)
    runner = make_runner(budget, CostAccumulator())
    graph = build_graph(GraphContext(runner, sample_quiz, sample_chunks, taught_subtopics))
    state = {"run_id": "b", "session_id": "ds_07",
             "questions": sample_questions, "findings": []}
    result = graph.invoke(state)
    assert budget.hard_stop is True
    # Phase 1 (no LLM) findings survive
    assert any(f.phase == "phase1_precheck" for f in result["findings"])
    # at least one phase recorded a budget error
    assert any("budget" in e.message.lower() for e in result.get("errors", []))
