"""FastAPI app — upload, run (async + SSE), report, per-question human actions,
and exports. The frontend talks to this via a configurable base URL.
"""
from __future__ import annotations

import json

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from . import audit, export, service, store
from .config import get_settings
from .db import get_session, init_db
from .ingestion.content import parse_content
from .ingestion.mastersheet import parse_mastersheet
from .ingestion.questions import parse_questions
from .jobs import manager
from .models import RunRow
from .schemas import Judgment, Option, Question

settings = get_settings()
app = FastAPI(title="Assessment Review Pipeline", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_provider": settings.llm.provider}


# --------------------------------------------------------------------------- #
# Uploads / ingestion
# --------------------------------------------------------------------------- #
@app.post("/upload/mastersheet")
async def upload_mastersheet(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    # XLSX preserves hyperlinks -> aggregate into units with content/question links
    if (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        from .ingestion.mastersheet_xlsx import parse_mastersheet_xlsx
        units = parse_mastersheet_xlsx(data)
        if units:
            store.save_units(units)
            return {"mode": "units", "ingested": len(units),
                    "units": [u.model_dump() for u in units]}
    sessions = parse_mastersheet(data, file.filename)
    store.save_sessions(sessions)
    return {"mode": "sessions", "ingested": len(sessions),
            "sessions": [s.model_dump() for s in sessions]}


@app.get("/units")
def list_units() -> dict:
    return {"units": store.list_units()}


@app.post("/units/{unit_id}/prepare_and_run")
async def prepare_and_run(unit_id: str, body: dict = Body(...)) -> dict:
    """One call: fetch this unit's content + questions from the mastersheet links,
    then start the review. `set` is 'mcq_assignment' or 'in_class_quiz'."""
    from .ingestion.fetch import fetch_content, fetch_doc_text
    from .ingestion.mcq_text import parse_mcq_text

    source_set = body.get("set", "mcq_assignment")
    row = store.get_unit_row(unit_id)
    if not row:
        raise HTTPException(404, "unit not found")

    doc_url = row.mcq_doc_url if source_set == "mcq_assignment" else row.quiz_doc_url
    if not doc_url:
        raise HTTPException(400, f"This unit has no {source_set} document in the mastersheet.")

    warnings: list[str] = []

    # 1) content (session slides) — fetch once
    if row.content_path and str(row.content_path).lower().startswith("http") \
            and not store.load_chunks(unit_id):
        try:
            store.save_chunks(fetch_content(unit_id, row.content_path))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"content fetch failed: {e}")

    # 2) questions for the requested set
    try:
        text = fetch_doc_text(doc_url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not fetch the {source_set} document: {e}")
    questions = parse_mcq_text(text, unit_id, source_set, default_topic=row.unit)
    if not questions:
        raise HTTPException(422, "Fetched the document but found no parseable MCQs.")
    store.save_questions(questions)

    # 3) for an assignment, also pull the in-class quiz (cross-set overlap check)
    if source_set == "mcq_assignment" and row.quiz_doc_url:
        try:
            qtext = fetch_doc_text(row.quiz_doc_url)
            quiz = parse_mcq_text(qtext, unit_id, "in_class_quiz", default_topic=row.unit)
            if quiz:
                store.save_questions(quiz)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"in-class quiz fetch skipped: {e}")

    store.mark_prepared(unit_id, source_set)
    audit.log("prepared_from_mastersheet", detail={
        "unit_id": unit_id, "set": source_set, "questions": len(questions)})

    run_id = manager.create_run(unit_id, source_set)
    await manager.start(run_id)
    return {"run_id": run_id, "status": "running", "questions": len(questions),
            "warnings": warnings}


@app.post("/upload/questions")
async def upload_questions(file: UploadFile = File(...),
                           session_id: str = Form("")) -> dict:
    questions = parse_questions(await file.read(), file.filename, default_session=session_id)
    store.save_questions(questions)
    summary: dict[str, dict[str, int]] = {}
    for q in questions:
        summary.setdefault(q.session_id, {}).setdefault(q.source_set, 0)
        summary[q.session_id][q.source_set] += 1
    return {"ingested": len(questions), "by_session": summary}


@app.post("/upload/content")
async def upload_content(file: UploadFile = File(...),
                         session_id: str = Form(...)) -> dict:
    chunks = parse_content(session_id, await file.read(), file.filename)
    store.save_chunks(chunks)
    with get_session() as db:
        from .models import SessionRow
        row = db.get(SessionRow, session_id) or SessionRow(session_id=session_id)
        row.content_parsed = True
        row.content_path = file.filename
        db.add(row)
        db.commit()
    return {"session_id": session_id, "chunks": len(chunks),
            "refs": sorted({c.source_ref for c in chunks})}


@app.post("/sessions/{session_id}/fetch_content")
def fetch_session_content(session_id: str, body: dict = Body(default={})) -> dict:
    """Fetch this session's content from its mastersheet link (Google Slides / S3),
    parse + chunk it — no upload needed. Pass {"url": "..."} to override the link.
    """
    from .ingestion.fetch import fetch_content

    sess = store.get_session_schema(session_id)
    url = (body or {}).get("url") or (sess.content_path if sess else None)
    if not url:
        raise HTTPException(400, "No content link for this session (mastersheet had none).")
    if not str(url).lower().startswith("http"):
        raise HTTPException(400, "Session content is a local file — use /upload/content instead.")
    try:
        chunks = fetch_content(session_id, url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not fetch content: {e}")
    if not chunks:
        raise HTTPException(422, "Fetched the link but found no extractable slide text.")
    store.save_chunks(chunks)
    with get_session() as db:
        from .models import SessionRow
        row = db.get(SessionRow, session_id) or SessionRow(session_id=session_id)
        row.content_parsed = True
        row.content_path = url
        db.add(row)
        db.commit()
    audit.log("content_fetched", run_id=None, question_id=None,
              detail={"session_id": session_id, "chunks": len(chunks), "url": url[:120]})
    return {"session_id": session_id, "chunks": len(chunks), "source": url,
            "refs": sorted({c.source_ref for c in chunks})}


@app.get("/sessions")
def list_sessions() -> dict:
    sessions = store.list_sessions()
    out = []
    for s in sessions:
        qs = store.load_questions_by_session(s.session_id)
        by_set: dict[str, int] = {}
        for q in qs:
            by_set[q.source_set] = by_set.get(q.source_set, 0) + 1
        out.append({**s.model_dump(), "question_counts": by_set})
    return {"sessions": out}


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
@app.post("/runs")
async def create_run(body: dict = Body(...)) -> dict:
    session_id = body.get("session_id")
    source_set = body.get("source_set", "mcq_assignment")
    token_limit = body.get("token_limit")
    if not session_id:
        raise HTTPException(400, "session_id is required")
    if not store.load_questions(session_id, source_set, include_deleted=False):
        raise HTTPException(400, f"No '{source_set}' questions for session {session_id}")
    run_id = manager.create_run(session_id, source_set, token_limit)
    await manager.start(run_id, token_limit)
    return {"run_id": run_id, "status": "running"}


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    async def gen():
        async for event in manager.subscribe(run_id):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    with get_session() as db:
        row = db.get(RunRow, run_id)
        if not row:
            raise HTTPException(404, "run not found")
        return _run_dict(row)


@app.get("/runs/{run_id}/report")
def get_report(run_id: str) -> dict:
    with get_session() as db:
        row = db.get(RunRow, run_id)
        if not row:
            raise HTTPException(404, "run not found")
    questions = store.load_questions(row.session_id, row.source_set)
    status_map = {q.question_id: (store.get_question(q.question_id) or (q, "pending"))[1]
                  for q in questions}
    findings = store.load_findings(run_id)
    judgments = {j.question_id: j for j in store.load_judgments(run_id)}

    findings_by_q: dict[str, list] = {}
    for f in findings:
        findings_by_q.setdefault(f.question_id, []).append(f.model_dump())

    q_out = []
    for q in questions:
        j = judgments.get(q.question_id)
        q_out.append({
            **q.model_dump(),
            "status": status_map.get(q.question_id, "pending"),
            "judgment": j.model_dump() if j else None,
            "findings": findings_by_q.get(q.question_id, []),
        })
    from .report import build_phase_summary
    return {
        "run": _run_dict(row),
        "questions": q_out,
        "set_findings": findings_by_q.get("__set__", []),
        "report": row.report,
        "phase_summary": build_phase_summary(findings, list(judgments.values())),
    }


@app.get("/runs/{run_id}/phases")
def get_phases(run_id: str) -> dict:
    """Per-phase verification: did each phase run, which checks fired, verdict counts."""
    with get_session() as db:
        row = db.get(RunRow, run_id)
        if not row:
            raise HTTPException(404, "run not found")
    from .report import build_phase_summary
    findings = store.load_findings(run_id)
    judgments = store.load_judgments(run_id)
    return {
        "run_id": run_id,
        "status": row.status,
        "completed_phases": list(row.completed_phases or []),
        "errors": list(row.errors or []),
        "phases": build_phase_summary(findings, judgments),
        "set_findings": [f.model_dump() for f in findings if f.question_id == "__set__"],
    }


def _run_dict(row: RunRow) -> dict:
    return {
        "run_id": row.run_id, "session_id": row.session_id, "source_set": row.source_set,
        "status": row.status, "current_phase": row.current_phase,
        "completed_phases": list(row.completed_phases or []),
        "report": row.report, "cost": row.cost, "budget": row.budget,
        "errors": list(row.errors or []),
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


# --------------------------------------------------------------------------- #
# Per-question human actions (all audited)
# --------------------------------------------------------------------------- #
@app.post("/questions/{question_id}/approve")
def approve_question(question_id: str, run_id: str = Query(...)) -> dict:
    _require_question(question_id)
    store.set_question_status(question_id, "approved")
    store.upsert_judgment(run_id, Judgment(question_id=question_id, verdict="APPROVE",
                                           reason="Approved by reviewer."))
    audit.log("approve", actor="human", run_id=run_id, question_id=question_id)
    return {"question_id": question_id, "status": "approved"}


@app.post("/questions/{question_id}/delete")
def delete_question(question_id: str, run_id: str = Query(...)) -> dict:
    _require_question(question_id)
    store.set_question_status(question_id, "deleted")
    store.upsert_judgment(run_id, Judgment(question_id=question_id, verdict="DELETE",
                                           reason="Deleted by reviewer."))
    audit.log("delete", actor="human", run_id=run_id, question_id=question_id)
    return {"question_id": question_id, "status": "deleted"}


@app.post("/questions/{question_id}/edit")
def edit_question(question_id: str, run_id: str = Query(...),
                  body: dict = Body(...)) -> dict:
    q, _status = _require_question(question_id)
    if "stem" in body:
        q.stem = body["stem"]
    if "options" in body:
        q.options = [Option(**o) for o in body["options"]]
    if "correct_keys" in body:
        q.correct_keys = body["correct_keys"]
    if "explanation" in body:
        q.explanation = body["explanation"]
    if "qtype" in body:
        q.qtype = body["qtype"]
    store.upsert_question(q, status="pending", edited=True)
    findings, judgment = service.re_review_question(run_id, q)
    audit.log("edit", actor="human", run_id=run_id, question_id=question_id,
              detail={"new_verdict": judgment.verdict})
    return {"question": q.model_dump(), "judgment": judgment.model_dump(),
            "findings": [f.model_dump() for f in findings]}


@app.post("/questions/{question_id}/regenerate")
def regenerate_question(question_id: str, run_id: str = Query(...)) -> dict:
    q, _status = _require_question(question_id)
    candidate, recheck = service.regenerate_question(run_id, q)
    audit.log("regenerate_proposed", actor="human", run_id=run_id, question_id=question_id,
              detail={"candidate_id": candidate.question_id})
    return {
        "original": q.model_dump(),
        "candidate": candidate.model_dump(),
        "recheck_findings": [f.model_dump() for f in recheck],
    }


@app.post("/questions/{question_id}/apply_regeneration")
def apply_regeneration(question_id: str, run_id: str = Query(...),
                       body: dict = Body(...)) -> dict:
    original, _status = _require_question(question_id)
    spec = body.get("candidate", {})
    new_q = Question(
        question_id=question_id,  # replace in place, keep id continuity
        session_id=original.session_id, course=original.course, module=original.module,
        unit=original.unit, source_set=original.source_set,
        qtype=spec.get("qtype", original.qtype),
        stem=spec.get("stem", original.stem),
        options=[Option(**o) for o in spec.get("options", [])] or original.options,
        correct_keys=spec.get("correct_keys", original.correct_keys),
        explanation=spec.get("explanation"), difficulty=original.difficulty,
        topic=original.topic, subtopics=original.subtopics,
        raw={"regenerated_from": question_id},
    )
    store.upsert_question(new_q, status="pending", edited=True)
    findings, judgment = service.re_review_question(run_id, new_q, category="regeneration")
    audit.log("regenerate_applied", actor="human", run_id=run_id, question_id=question_id,
              detail={"new_verdict": judgment.verdict})
    return {"question": new_q.model_dump(), "judgment": judgment.model_dump(),
            "findings": [f.model_dump() for f in findings]}


def _require_question(question_id: str):
    res = store.get_question(question_id)
    if not res:
        raise HTTPException(404, "question not found")
    return res


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #
@app.get("/runs/{run_id}/export")
def export_cleaned(run_id: str, format: str = Query("csv")) -> Response:
    with get_session() as db:
        row = db.get(RunRow, run_id)
        if not row:
            raise HTTPException(404, "run not found")
    approved = [q for q in store.load_questions(row.session_id, row.source_set)
                if (store.get_question(q.question_id) or (q, ""))[1] == "approved"]
    audit.log("export_cleaned", run_id=run_id, detail={"format": format,
                                                        "count": len(approved)})
    if format == "json":
        return Response(export.export_cleaned_json(approved),
                        media_type="application/json",
                        headers=_dl(f"cleaned_{run_id}.json"))
    if format == "xlsx":
        return Response(export.export_cleaned_xlsx(approved),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers=_dl(f"cleaned_{run_id}.xlsx"))
    return Response(export.export_cleaned_csv(approved), media_type="text/csv",
                    headers=_dl(f"cleaned_{run_id}.csv"))


@app.get("/runs/{run_id}/report/export")
def export_report(run_id: str, format: str = Query("md")) -> Response:
    with get_session() as db:
        row = db.get(RunRow, run_id)
        if not row or not row.report:
            raise HTTPException(404, "run/report not found")
    from .schemas import SetReport
    report = SetReport(**row.report)
    questions = store.load_questions(row.session_id, row.source_set)
    findings = store.load_findings(run_id)
    judgments = store.load_judgments(run_id)
    md = export.export_report_markdown(report, findings, judgments, questions)
    audit.log("export_report", run_id=run_id, detail={"format": "md"})
    return Response(md, media_type="text/markdown", headers=_dl(f"report_{run_id}.md"))


@app.get("/runs/{run_id}/audit")
def get_audit(run_id: str) -> dict:
    return {"log": audit.get_log(run_id=run_id)}


# --------------------------------------------------------------------------- #
# Agent instructions (reviewer feedback the agents remember on future runs)
# --------------------------------------------------------------------------- #
@app.get("/instructions")
def get_instructions(session_id: str | None = Query(None)) -> dict:
    from . import instructions
    return {
        "instructions": instructions.list_instructions(session_id),
        "targetable": [
            {"phase": p, "label": lbl, "description": desc}
            for p, lbl, desc in instructions.TARGETABLE
        ],
    }


@app.post("/instructions")
def create_instruction(body: dict = Body(...)) -> dict:
    from . import instructions
    phase = body.get("phase", "all")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "instruction text is required")
    try:
        row = instructions.add_instruction(phase, text, body.get("session_id"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.log("instruction_added", detail={"phase": phase, "text": text[:120]})
    return row


@app.delete("/instructions/{instruction_id}")
def remove_instruction(instruction_id: int) -> dict:
    from . import instructions
    instructions.delete_instruction(instruction_id)
    audit.log("instruction_removed", detail={"id": instruction_id})
    return {"deleted": instruction_id}


def _dl(name: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{name}"'}
