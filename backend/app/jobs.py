"""Async review-run manager.

A run executes the LangGraph pipeline in a worker thread and streams phase-by-phase
progress to any number of SSE subscribers. Findings/judgments/report/cost are
persisted incrementally so a report is available even if a later phase fails or the
token budget hard-stops. Event history is buffered per run so a dashboard that
connects mid-run still sees the full checklist.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from .config import get_settings
from .db import get_session
from .graph.build import PHASE_LABELS, PHASE_ORDER, build_graph
from .graph.state import GraphContext
from .llm import make_runner
from .models import RunRow
from .schemas import CostAccumulator, TokenBudget
from . import audit, store

_settings = get_settings()


class _RunState:
    def __init__(self):
        self.history: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self.done = False


class RunManager:
    def __init__(self):
        self._runs: dict[str, _RunState] = {}

    # -- lifecycle --------------------------------------------------------- #
    def create_run(self, session_id: str, source_set: str,
                   token_limit: int | None = None, reviewer: str = "") -> str:
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        limit = _settings.budget.token_limit if token_limit is None else token_limit
        with get_session() as db:
            db.add(RunRow(run_id=run_id, session_id=session_id, source_set=source_set,
                          reviewer=reviewer or "unknown", status="queued",
                          budget={"limit": limit, "spent": 0}))
            db.commit()
        self._runs[run_id] = _RunState()
        audit.log("run_created", run_id=run_id,
                  detail={"session_id": session_id, "source_set": source_set,
                          "reviewer": reviewer or "unknown"})
        return run_id

    async def start(self, run_id: str, token_limit: int | None = None) -> None:
        loop = asyncio.get_running_loop()
        asyncio.create_task(self._run_async(run_id, loop, token_limit))

    async def _run_async(self, run_id: str, loop, token_limit: int | None) -> None:
        try:
            await asyncio.to_thread(self._run_sync, run_id, loop, token_limit)
        except Exception as e:  # noqa: BLE001
            self._update_run(run_id, status="failed", errors=[str(e)])
            self._publish(loop, run_id, {"type": "error", "message": str(e)})
            self._finish(run_id, loop)

    # -- the actual pipeline (runs in a worker thread) --------------------- #
    def _run_sync(self, run_id: str, loop, token_limit: int | None) -> None:
        run = self._get_run_row(run_id)
        session_id, source_set = run.session_id, run.source_set

        questions = store.load_questions(session_id, source_set, include_deleted=False)
        quiz = [q for q in store.load_questions(session_id, "in_class_quiz",
                                                include_deleted=False)
                if source_set != "in_class_quiz"]
        chunks = store.load_chunks(session_id)
        sess = store.get_session_schema(session_id)
        taught = sess.subtopics if sess else []

        limit = run.budget.get("limit", 0) if run.budget else 0
        if token_limit is not None:
            limit = token_limit
        budget = TokenBudget(limit=limit, warn_at=_settings.budget.warn_at)
        cost = CostAccumulator()
        runner = make_runner(budget, cost)
        graph = build_graph(GraphContext(runner, quiz, chunks, taught))

        self._update_run(run_id, status="running")
        self._publish(loop, run_id, {"type": "start", "phases": [
            {"key": k, "label": v} for k, v in PHASE_LABELS.items()]})

        completed: list[str] = []
        errors: list[str] = []
        final_report: dict | None = None
        state = {"run_id": run_id, "session_id": session_id,
                 "questions": questions, "findings": []}

        for update in graph.stream(state, stream_mode="updates"):
            for node_name, delta in update.items():
                if delta.get("findings"):
                    store.save_findings(run_id, delta["findings"])
                if delta.get("judgments"):
                    store.save_judgments(run_id, delta["judgments"])
                    for j in delta["judgments"]:
                        audit.log("verdict", run_id=run_id, question_id=j.question_id,
                                  detail={"verdict": j.verdict, "reason": j.reason})
                if delta.get("set_report") is not None:
                    final_report = delta["set_report"].model_dump()
                    self._update_run(run_id, report=final_report)
                for pe in delta.get("errors", []):
                    errors.append(f"{pe.phase}: {pe.message}")
                completed.append(node_name)
                self._update_run(run_id, current_phase=node_name,
                                 completed_phases=completed.copy(), errors=errors.copy())
                self._persist_cost(run_id, cost, budget)
                self._publish(loop, run_id, {
                    "type": "phase", "phase": node_name,
                    "label": PHASE_LABELS.get(node_name, node_name),
                    "completed": completed.copy(),
                    "budget": budget.model_dump(),
                    "cost": self._cost_dump(cost),
                })

        status = "budget_stopped" if budget.hard_stop else "completed"
        self._update_run(run_id, status=status, completed_phases=completed,
                         errors=errors, cost=self._cost_dump(cost),
                         budget=budget.model_dump())
        # record a compact summary so a later reviewer is warned this was already reviewed
        if final_report is not None:
            try:
                store.save_review_summary(
                    run_id=run_id, session_id=session_id, source_set=source_set,
                    title=store.db_session_title(session_id), reviewer=run.reviewer,
                    report=final_report, questions=questions)
            except Exception:  # noqa: BLE001 - summary is best-effort, never fail the run
                pass
        self._publish(loop, run_id, {
            "type": "done", "status": status,
            "cost": self._cost_dump(cost), "budget": budget.model_dump(),
        })
        audit.log("run_completed", run_id=run_id, detail={"status": status})
        self._finish(run_id, loop)

    # -- SSE pub/sub ------------------------------------------------------- #
    def _publish(self, loop, run_id: str, event: dict) -> None:
        state = self._runs.get(run_id)
        if state is None:
            return
        state.history.append(event)
        for q in list(state.subscribers):
            loop.call_soon_threadsafe(q.put_nowait, event)

    def _finish(self, run_id: str, loop) -> None:
        state = self._runs.get(run_id)
        if state is None:
            return
        state.done = True
        for q in list(state.subscribers):
            loop.call_soon_threadsafe(q.put_nowait, {"type": "_close"})

    async def subscribe(self, run_id: str):
        state = self._runs.get(run_id)
        if state is None:
            # run already finished or unknown: emit a terminal snapshot
            row = self._get_run_row(run_id)
            if row:
                yield {"type": "done", "status": row.status,
                       "cost": row.cost, "budget": row.budget}
            return
        q: asyncio.Queue = asyncio.Queue()
        for ev in state.history:  # replay so late subscribers see the full checklist
            yield ev
        if state.done:
            return
        state.subscribers.append(q)
        try:
            while True:
                ev = await q.get()
                if ev.get("type") == "_close":
                    break
                yield ev
        finally:
            if q in state.subscribers:
                state.subscribers.remove(q)

    # -- persistence helpers ---------------------------------------------- #
    def _get_run_row(self, run_id: str) -> RunRow | None:
        with get_session() as db:
            return db.get(RunRow, run_id)

    def _update_run(self, run_id: str, **fields) -> None:
        with get_session() as db:
            row = db.get(RunRow, run_id)
            if not row:
                return
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = datetime.now(timezone.utc)
            db.add(row)
            db.commit()

    def _persist_cost(self, run_id: str, cost: CostAccumulator, budget: TokenBudget) -> None:
        self._update_run(run_id, cost=self._cost_dump(cost), budget=budget.model_dump())

    @staticmethod
    def _cost_dump(cost: CostAccumulator) -> dict:
        return {
            "per_phase": {k: v.model_dump() for k, v in cost.per_phase.items()},
            "total_tokens": cost.total_tokens,
            "total_usd": cost.total_usd,
        }


manager = RunManager()
