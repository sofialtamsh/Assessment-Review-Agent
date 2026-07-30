"""Wire the 7-phase review as a LangGraph StateGraph.

Phases 1-5 append findings, phase 6 judges, then a report node assembles the
set-level report. Each LLM phase is guarded: if the run already hit its token
budget, or a phase raises, we record a PhaseError and continue — a failed phase
never corrupts state, and the deterministic results already gathered survive.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from ..llm.base import BudgetExceeded
from ..report import build_report
from ..schemas import PhaseError
from .nodes import (
    phase2_language,
    phase3_ambiguity,
    phase4_scope,
    phase5_pedagogy,
    phase6_judge,
)
from .nodes.phase1_precheck import run_precheck
from .state import GraphContext, ReviewState

# Human-readable phase labels for the progress checklist (Phase 1 -> 7).
PHASE_LABELS = {
    "phase1_precheck": "Phase 1 — Deterministic pre-checks",
    "phase2_language": "Phase 2 — Language & Logic",
    "phase3_ambiguity": "Phase 3 — Ambiguity & Overlap",
    "phase4_scope": "Phase 4 — Scope & Source (RAG)",
    "phase5_pedagogy": "Phase 5 — Pedagogy",
    "phase6_judge": "Phase 6 — Judge / Aggregator",
    "report": "Assembling report",
}
PHASE_ORDER = list(PHASE_LABELS.keys())


def build_graph(ctx: GraphContext):
    g = StateGraph(ReviewState)

    def phase1(state: ReviewState) -> dict:
        fs = run_precheck(state["questions"])
        return {"findings": fs, "current_phase": "phase1_precheck"}

    def _llm_phase(name: str, fn):
        def node(state: ReviewState) -> dict:
            if ctx.runner.budget.hard_stop:
                return {"current_phase": name,
                        "errors": [PhaseError(phase=name, message="skipped: budget hard stop")]}
            try:
                fs = fn(state)
                return {"findings": fs, "current_phase": name}
            except BudgetExceeded as e:
                return {"current_phase": name,
                        "errors": [PhaseError(phase=name, message=str(e))]}
            except Exception as e:  # noqa: BLE001 - isolate a bad phase
                return {"current_phase": name,
                        "errors": [PhaseError(phase=name, message=f"{type(e).__name__}: {e}")]}
        return node

    phase2 = _llm_phase("phase2_language",
                        lambda s: phase2_language.run(s["questions"], ctx.runner))
    phase3 = _llm_phase("phase3_ambiguity",
                        lambda s: phase3_ambiguity.run(s["questions"], ctx.quiz_questions, ctx.runner))
    phase4 = _llm_phase("phase4_scope",
                        lambda s: phase4_scope.run(s["questions"], ctx.chunks,
                                                   ctx.taught_subtopics, ctx.runner))
    phase5 = _llm_phase("phase5_pedagogy",
                        lambda s: phase5_pedagogy.run(s["questions"], ctx.taught_subtopics, ctx.runner))

    def judge(state: ReviewState) -> dict:
        if ctx.runner.budget.hard_stop:
            return {"judgments": [], "current_phase": "phase6_judge",
                    "errors": [PhaseError(phase="phase6_judge", message="skipped: budget hard stop")]}
        try:
            js = phase6_judge.run(state["questions"], state.get("findings", []), ctx.runner)
            return {"judgments": js, "current_phase": "phase6_judge"}
        except Exception as e:  # noqa: BLE001
            return {"judgments": [], "current_phase": "phase6_judge",
                    "errors": [PhaseError(phase="phase6_judge", message=str(e))]}

    def report(state: ReviewState) -> dict:
        from .. import store
        session_id = state.get("session_id", "")
        rubric = store.get_rubric(session_id) if session_id else None
        rpt = build_report(session_id, state["questions"],
                           state.get("findings", []), state.get("judgments", []),
                           rubric=rubric)
        return {"set_report": rpt, "current_phase": "report"}

    g.add_node("phase1_precheck", phase1)
    g.add_node("phase2_language", phase2)
    g.add_node("phase3_ambiguity", phase3)
    g.add_node("phase4_scope", phase4)
    g.add_node("phase5_pedagogy", phase5)
    g.add_node("phase6_judge", judge)
    g.add_node("report", report)

    g.set_entry_point("phase1_precheck")
    g.add_edge("phase1_precheck", "phase2_language")
    g.add_edge("phase2_language", "phase3_ambiguity")
    g.add_edge("phase3_ambiguity", "phase4_scope")
    g.add_edge("phase4_scope", "phase5_pedagogy")
    g.add_edge("phase5_pedagogy", "phase6_judge")
    g.add_edge("phase6_judge", "report")
    g.add_edge("report", END)
    return g.compile()
