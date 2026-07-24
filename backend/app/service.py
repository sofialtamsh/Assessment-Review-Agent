"""Human-in-the-loop actions that re-review edited/regenerated questions.

Nothing here auto-applies: the API layer decides when to persist. Re-review runs
the relevant phases (2-4) on a single question so no unreviewed content can enter
an approved set, and folds the extra token cost back into the run's cost record.
"""
from __future__ import annotations

from .db import get_session
from .graph.nodes import phase2_language, phase3_ambiguity, phase4_scope, phase6_judge, phase7_fixer
from .llm import make_runner
from .models import RunRow
from .schemas import CostAccumulator, Finding, Judgment, Question, TokenBudget
from . import store


def _context(session_id: str, source_set: str, exclude_id: str):
    siblings = [q for q in store.load_questions(session_id, source_set, include_deleted=False)
                if q.question_id != exclude_id]
    quiz = [q for q in store.load_questions(session_id, "in_class_quiz",
                                            include_deleted=False)
            if source_set != "in_class_quiz"]
    chunks = store.load_chunks(session_id)
    sess = store.get_session_schema(session_id)
    taught = sess.subtopics if sess else []
    return siblings, quiz, chunks, taught


def _fresh_runner():
    # Human actions run on a fresh accumulator; their cost is then folded into the
    # run under a dedicated category bucket (so the dashboard shows it separately).
    return make_runner(TokenBudget(limit=0), CostAccumulator())


def _fold_cost(run_id: str, category: str, runner) -> None:
    """Add this action's total token/$ into a labeled bucket on the run's cost."""
    tin = sum(p.tokens_in for p in runner.cost.per_phase.values())
    tout = sum(p.tokens_out for p in runner.cost.per_phase.values())
    usd = runner.cost.total_usd
    calls = sum(p.calls for p in runner.cost.per_phase.values())
    model = next((p.model for p in runner.cost.per_phase.values() if p.model), None)
    import copy

    with get_session() as db:
        row = db.get(RunRow, run_id)
        if not row:
            return
        # deep-copy so reassigning row.cost is a NEW object -> SQLAlchemy marks it dirty
        cost = copy.deepcopy(row.cost) if row.cost else {"per_phase": {}, "total_tokens": 0, "total_usd": 0.0}
        per_phase = cost.setdefault("per_phase", {})
        b = per_phase.setdefault(category, {
            "phase": category, "model": model, "calls": 0,
            "tokens_in": 0, "tokens_out": 0, "usd": 0.0,
        })
        b["calls"] += calls
        b["tokens_in"] += tin
        b["tokens_out"] += tout
        b["usd"] = round(b["usd"] + usd, 6)
        b["model"] = b["model"] or model
        cost["total_tokens"] = sum(v["tokens_in"] + v["tokens_out"] for v in per_phase.values())
        cost["total_usd"] = round(sum(v["usd"] for v in per_phase.values()), 6)
        row.cost = cost
        db.add(row)
        db.commit()


def re_review_question(run_id: str, q: Question,
                       category: str = "edit_recheck") -> tuple[list[Finding], Judgment]:
    """Re-run phases 2-4 on one question, replace its findings, and re-judge it.

    `category` labels the cost bucket ('edit_recheck' or 'regeneration').
    """
    siblings, quiz, chunks, taught = _context(q.session_id, q.source_set, q.question_id)
    runner = _fresh_runner()

    findings: list[Finding] = []
    findings += phase2_language.run([q], runner)
    findings += phase3_ambiguity.run([q] + siblings, quiz, runner)
    findings += phase4_scope.run([q], chunks, taught, runner)
    findings = [f for f in findings if f.question_id == q.question_id]

    store.replace_question_findings(run_id, q.question_id, findings)
    judgment = phase6_judge.run([q], findings, runner)[0]
    store.upsert_judgment(run_id, judgment)
    _fold_cost(run_id, category, runner)
    return findings, judgment


def regenerate_question(run_id: str, q: Question) -> tuple[Question, list[Finding]]:
    """Phase 7 fixer: propose a grounded replacement + its re-check findings.

    Does NOT persist the question — the human approves the candidate first — but the
    generation cost is real, so it is folded into the run's 'regeneration' bucket.
    """
    siblings, quiz, chunks, taught = _context(q.session_id, q.source_set, q.question_id)
    runner = _fresh_runner()
    candidate, recheck = phase7_fixer.run(q, chunks, siblings, taught, runner)
    _fold_cost(run_id, "regeneration", runner)
    return candidate, recheck
