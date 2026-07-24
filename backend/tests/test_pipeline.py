"""End-to-end pipeline over the seeded sample set (mock provider, $0).

Asserts each specialist phase catches its seeded defect and the Judge produces a
sensible verdict mix.
"""
import pytest

from app.graph.build import build_graph
from app.graph.state import GraphContext
from app.llm import make_runner
from app.schemas import CostAccumulator, TokenBudget


@pytest.fixture(scope="module")
def final_state(sample_questions, sample_quiz, sample_chunks, taught_subtopics):
    runner = make_runner(TokenBudget(limit=0), CostAccumulator())
    graph = build_graph(GraphContext(runner, sample_quiz, sample_chunks, taught_subtopics))
    state = {"run_id": "t", "session_id": "ds_07",
             "questions": sample_questions, "findings": []}
    result = graph.invoke(state)
    result["_cost"] = runner.cost
    return result


def _findings(state, phase=None, check=None, qid=None):
    out = state["findings"]
    if phase:
        out = [f for f in out if f.phase == phase]
    if check:
        out = [f for f in out if f.check_name == check]
    if qid:
        out = [f for f in out if f.question_id == qid]
    return out


def test_semantic_duplicate_caught(final_state):
    # q03 is a paraphrase of q02
    dupes = _findings(final_state, check="semantic_duplicate")
    assert any("q02" in f.related_ids for f in dupes)


def test_cross_set_overlap_caught(final_state):
    overlaps = _findings(final_state, check="cross_set_overlap")
    assert overlaps, "expected the assignment q to overlap the in-class quiz"


def test_ambiguous_question_caught(final_state):
    assert _findings(final_state, check="option_ambiguity", qid="q07")


def test_out_of_scope_caught(final_state):
    oos = _findings(final_state, check="out_of_scope")
    assert any(f.question_id == "q06" for f in oos)  # Ridge regression not taught


def test_verbatim_lift_caught(final_state):
    vb = _findings(final_state, check="verbatim_lift")
    assert any(f.question_id == "q05" for f in vb)  # copies the PPT worked example


def test_bloom_classified_for_all(final_state, sample_questions):
    blooms = {f.question_id for f in _findings(final_state, check="bloom_classified")}
    assert blooms >= {q.question_id for q in sample_questions}


def test_judge_verdicts(final_state):
    verdicts = {j.question_id: j.verdict for j in final_state["judgments"]}
    assert verdicts["q06"] == "DELETE"          # out of scope
    assert verdicts["q05"] in {"REVISE", "DELETE"}   # verbatim lift
    assert verdicts["q12"] == "REVISE"          # bad key
    # a fully-clean question should be approvable
    assert "APPROVE" in verdicts.values()


def test_report_assembled(final_state):
    r = final_state["set_report"]
    assert r.total_questions == 15
    assert "q06" in r.out_of_scope_ids
    assert "q05" in r.verbatim_lift_ids
    assert r.duplicate_clusters
    assert sum(r.bloom_distribution.values()) == 15


def test_cost_tracked(final_state):
    # The mock provider makes no real API calls (zero real spend); the cost
    # accumulator still reports a *simulated* per-phase token + $ estimate using
    # the configured model pricing, so the dashboard's cost panel is populated.
    cost = final_state["_cost"]
    assert cost.total_tokens > 0
    assert cost.total_usd >= 0.0
    assert set(cost.per_phase) >= {"phase2_language", "phase6_judge"}
