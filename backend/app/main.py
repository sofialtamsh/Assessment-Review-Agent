"""FastAPI app — upload, run (async + SSE), report, per-question human actions,
and exports. The frontend talks to this via a configurable base URL.
"""
from __future__ import annotations

import json

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from . import audit, auth, export, service, store
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
# Auth (lightweight shared-password login) + activity feed
# --------------------------------------------------------------------------- #
@app.post("/auth/login")
def auth_login(body: dict = Body(...)) -> dict:
    try:
        return auth.login(body.get("name", ""), body.get("password", ""))
    except ValueError as e:
        raise HTTPException(401, str(e))


@app.get("/activity")
def activity(limit: int = Query(25)) -> dict:
    """Recent reviews (in-progress + completed) with who ran them — the activity feed."""
    return {"activity": store.list_activity(limit)}


@app.get("/review_status")
def review_status(session_id: str = Query(...),
                  source_set: str = Query("mcq_assignment")) -> dict:
    """Prior completed reviews for this unit + set (used to warn before re-reviewing)."""
    return {"prior": store.find_prior_reviews(session_id, source_set)}


@app.post("/rubric/infer")
async def infer_rubric_endpoint(
    file: UploadFile | None = File(None),
    questions_url: str = Form(""),
    text: str = Form(""),
) -> dict:
    """Reverse-engineer a marking scheme from a reference (gold/approved) question set.

    Provide a reference set as a file (.xlsx/.csv/.json/.md/.txt/.zip), a link, or pasted
    MCQ text. Returns an inferred rubric (written guidance + structured criteria) the
    reviewer can edit and attach to an evaluation.
    """
    from .ingestion.fetch import fetch_questions
    from .ingestion.mcq_text import parse_mcq_text
    from .rubric_infer import infer_rubric

    source = ""
    try:
        if file is not None:
            data = await file.read()
            source = file.filename or "reference set"
            questions = _parse_eval_upload(data, file.filename or "", "infer", "reference")
        elif questions_url.strip():
            source = questions_url.strip()
            questions = fetch_questions("infer", source, "examination", default_topic="reference")
        elif text.strip():
            source = "pasted reference"
            questions = parse_mcq_text(text, "infer", "examination", default_topic="reference")
        else:
            raise HTTPException(400, "Provide a reference set (file, link, or pasted text).")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Could not parse the reference set: {e}")

    if not questions:
        raise HTTPException(422, "Parsed the reference set but found no questions to learn from.")

    rubric = infer_rubric(questions, source=source)
    return {
        "n_questions": len(questions),
        "n_criteria": len(rubric.criteria),
        "rubric": rubric.model_dump(),
    }


# --------------------------------------------------------------------------- #
# Uploads / ingestion
# --------------------------------------------------------------------------- #
@app.post("/upload/mastersheet")
async def upload_mastersheet(file: UploadFile = File(...), request: Request = None) -> dict:
    owner = auth.reviewer_from_request(request)
    data = await file.read()
    # XLSX preserves hyperlinks -> aggregate into units with content/question links
    if (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        from .ingestion.mastersheet_xlsx import parse_mastersheet_xlsx
        units = parse_mastersheet_xlsx(data)
        if units:
            store.save_units(units, owner=owner)
            return {"mode": "units", "ingested": len(units),
                    "units": [u.model_dump() for u in units]}
    sessions = parse_mastersheet(data, file.filename)
    store.save_sessions(sessions, owner=owner)
    return {"mode": "sessions", "ingested": len(sessions),
            "sessions": [s.model_dump() for s in sessions]}


@app.post("/ingest/mastersheet_link")
async def ingest_mastersheet_link(body: dict = Body(...), request: Request = None) -> dict:
    """Ingest the mastersheet straight from a Google Sheet (or .xlsx) link — no download.

    The sheet is exported as .xlsx so its cell hyperlinks (slide / doc / zip links) are
    preserved, exactly like uploading the .xlsx. If the export drops the hyperlinks (a
    known Google Sheets quirk for HYPERLINK()-formula cells), no units survive and we tell
    the reviewer to fall back to uploading the .xlsx.
    """
    from .ingestion.fetch import fetch_spreadsheet_bytes
    from .ingestion.mastersheet_xlsx import parse_mastersheet_xlsx

    url = (body.get("url") or "").strip()
    if not url.lower().startswith("http"):
        raise HTTPException(400, "Paste a Google Sheet or .xlsx URL.")
    try:
        data = fetch_spreadsheet_bytes(url, what="mastersheet")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not fetch the mastersheet link: {e}")

    units = parse_mastersheet_xlsx(data)
    if not units:
        raise HTTPException(422,
            "Fetched the sheet but found no units with links. The Google Sheet export may "
            "have dropped the cell hyperlinks (a known quirk for HYPERLINK()-formula cells). "
            "Download the sheet as .xlsx (File > Download > Microsoft Excel) and upload it.")
    store.save_units(units, owner=auth.reviewer_from_request(request))
    return {"mode": "units", "ingested": len(units),
            "units": [u.model_dump() for u in units]}


@app.get("/units")
def list_units(request: Request) -> dict:
    return {"units": store.list_units(auth.reviewer_from_request(request))}


# --------------------------------------------------------------------------- #
# Fetch error reporting — name WHICH source failed (+ its link) so the reviewer
# knows exactly which mastersheet link to fix (e.g. share it publicly).
# --------------------------------------------------------------------------- #
_SET_LABEL = {
    "mcq_assignment": "MCQ assignment",
    "in_class_quiz": "in-class quiz",
    "examination": "evaluation",
}


def _source_error(source: str, err: object, url: str = "") -> str:
    """Consistent, actionable message: which source failed, why, and its link."""
    loc = f" [{url}]" if url else ""
    return f"{source} — {err}{loc}"


# --------------------------------------------------------------------------- #
# Evaluation (combined) — shared helpers
# --------------------------------------------------------------------------- #
def _resolve_eval_units(unit_ids: list[str]) -> list:
    """Validate the selected units and return their rows (raises on empty / missing)."""
    if len(unit_ids) < 1:
        raise HTTPException(400, "Select the unit(s) this evaluation covers.")
    rows = [store.get_unit_row(u) for u in unit_ids]
    if any(r is None for r in rows):
        raise HTTPException(404, "one or more units not found")
    return rows


def _eval_id_for(unit_ids: list[str], salt: str) -> str:
    """Stable id for an evaluation over a set of units (salt distinguishes sources)."""
    import hashlib

    return "eval_" + hashlib.sha1(
        ("|".join(sorted(unit_ids)) + salt).encode()).hexdigest()[:8]


def _save_eval_session(eval_id: str, title: str, rows: list, owner: str = "") -> None:
    """Persist the synthetic session carrying the union of the units' taught subtopics."""
    from .models import SessionRow

    subtopics: list[str] = []
    for r in rows:
        subtopics += list(r.subtopics or [])
    with get_session() as db:
        srow = db.get(SessionRow, eval_id) or SessionRow(session_id=eval_id)
        srow.owner = owner or srow.owner
        srow.unit = srow.topic = title
        srow.course = rows[0].course
        srow.module = rows[0].module
        srow.subtopics = subtopics
        db.add(srow)
        db.commit()


def _fetch_eval_content(eval_id: str, rows: list) -> tuple[list, list[str]]:
    """Reference content (scope basis): each unit's slides + tutorial, combined."""
    from .ingestion.fetch import fetch_content, fetch_tutorial_content

    warnings: list[str] = []
    all_chunks: list = []
    for r in rows:
        if r.content_path and str(r.content_path).lower().startswith("http"):
            try:
                chunks = fetch_content(eval_id, r.content_path)
                for c in chunks:
                    c.source_ref = f"{r.unit[:22]} · {c.source_ref}"
                all_chunks += chunks
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{r.unit}: " + _source_error("slides (PPT)", e, r.content_path))
        if r.tutorial_url and str(r.tutorial_url).lower().startswith("http"):
            try:
                tchunks = fetch_tutorial_content(eval_id, r.tutorial_url)
                for c in tchunks:
                    c.source_ref = f"{r.unit[:22]} · {c.source_ref}"
                all_chunks += tchunks
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{r.unit}: " + _source_error("tutorial", e, r.tutorial_url))
    return all_chunks, warnings


def _attach_rubric(eval_id: str, warnings: list[str], *, text: str = "", url: str = "",
                   file_bytes: bytes | None = None, filename: str = "",
                   criteria: list | None = None) -> None:
    """Assemble a marking scheme from any of pasted text / uploaded file / link /
    reverse-engineered criteria and attach it. Fetch/parse failures are non-fatal."""
    from .ingestion.fetch import fetch_rubric
    from .ingestion.rubric import rubric_from_bytes, rubric_from_text
    from .schemas import Rubric, RubricCriterion

    parts: list = []
    if text and text.strip():
        parts.append(rubric_from_text(text, source="pasted"))
    if criteria:
        try:
            crits = [RubricCriterion(**c) for c in criteria]
            parts.append(Rubric(text="", criteria=crits, source="reverse-engineered"))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"marking scheme criteria — {e}")
    if file_bytes:
        try:
            parts.append(rubric_from_bytes(file_bytes, filename or "rubric", source=filename))
        except Exception as e:  # noqa: BLE001
            warnings.append(_source_error("marking scheme file", e, filename))
    if url and url.strip():
        try:
            parts.append(fetch_rubric(url.strip()))
        except PermissionError as e:
            warnings.append(_source_error("marking scheme", e, url))
        except Exception as e:  # noqa: BLE001
            warnings.append(_source_error("Could not fetch marking scheme", e, url))

    parts = [p for p in parts if p and (p.text or p.criteria)]
    if not parts:
        return
    combined = Rubric(
        text="\n\n".join(p.text for p in parts if p.text).strip(),
        criteria=[c for p in parts for c in p.criteria],
        source=" + ".join(p.source for p in parts if p.source),
    )
    store.save_rubric(eval_id, combined)
    audit.log("rubric_attached", detail={
        "eval_id": eval_id, "criteria": len(combined.criteria),
        "has_text": bool(combined.text), "source": combined.source[:120]})


def _guardrail(session_id: str, source_set: str, questions: list, force: bool) -> None:
    """Warn (via 409) if this unit/eval + set — or an identical question set — was
    already reviewed. The caller retries with force=true to review again anyway."""
    if force:
        return
    chash = store.question_set_hash(questions) if questions else ""
    prior = store.find_prior_reviews(session_id, source_set, content_hash=chash)
    if prior:
        p = prior[0]
        raise HTTPException(status_code=409, detail={
            "already_reviewed": True,
            "message": f"Already reviewed by {p['reviewer']} on {p['created_at'][:10]}.",
            "prior": prior[:3],
        })


async def _finalize_evaluation(eval_id: str, unit_ids: list[str], all_chunks: list,
                               all_questions: list, warnings: list[str],
                               reviewer: str = "", force: bool = False) -> dict:
    """Persist the assembled evaluation, kick off the review, return the run payload."""
    if not all_questions:
        raise HTTPException(422, "No questions could be assembled for this evaluation. "
                            + " | ".join(warnings))
    _guardrail(eval_id, "examination", all_questions, force)
    store.save_chunks(all_chunks)
    store.save_questions(all_questions)
    store.mark_prepared(eval_id, "examination")
    audit.log("evaluation_created", detail={
        "eval_id": eval_id, "units": unit_ids, "questions": len(all_questions),
        "reviewer": reviewer or "unknown"})

    run_id = manager.create_run(eval_id, "examination", reviewer=reviewer)
    await manager.start(run_id)
    return {"run_id": run_id, "status": "running", "units": len(unit_ids),
            "questions": len(all_questions), "warnings": warnings}


def _parse_eval_upload(data: bytes, filename: str, eval_id: str, title: str) -> list:
    """Parse an uploaded evaluation file into questions tagged as the 'examination' set.

    Accepts the same shapes the assignment/quiz sources use: a .zip LMS export, a
    Google-Doc-style .md/.txt, or a CSV/XLSX/JSON question set.
    """
    name = filename.lower()
    if name.endswith(".zip"):
        from .ingestion.mcq_zip import parse_mcq_zip
        qs = parse_mcq_zip(data, eval_id, "examination", default_topic=title)
    elif name.endswith((".md", ".markdown", ".txt")):
        from .ingestion.mcq_text import parse_mcq_text
        qs = parse_mcq_text(data.decode("utf-8", errors="replace"), eval_id,
                            "examination", default_topic=title)
    else:
        qs = parse_questions(data, filename, default_session=eval_id)
    # everything in this set belongs to the one evaluation, reviewed as "examination"
    for q in qs:
        q.session_id = eval_id
        q.source_set = "examination"
    return qs


def _questions_from_url(eval_id: str, questions_url: str, title: str) -> list:
    """Fetch the whole evaluation from one link (a Doc/Slides link, MCQ zip, or Sheet)."""
    from .ingestion.fetch import fetch_questions

    try:
        return fetch_questions(eval_id, questions_url, "examination", default_topic=title)
    except PermissionError as e:
        raise HTTPException(403, _source_error("evaluation document", e, questions_url))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            502, _source_error("Could not fetch the evaluation document", e, questions_url))


def _assemble_unit_questions(eval_id: str, rows: list, source_set: str,
                             warnings: list[str]) -> list:
    """Assemble one evaluation set from each selected unit's chosen document."""
    from .ingestion.fetch import fetch_questions

    label = _SET_LABEL.get(source_set, source_set)
    all_questions: list = []
    for r in rows:
        doc_url = r.mcq_doc_url if source_set == "mcq_assignment" else r.quiz_doc_url
        if not doc_url:
            warnings.append(f"{r.unit}: no {label} document")
            continue
        try:
            qs = fetch_questions(eval_id, doc_url, "examination", default_topic=r.unit)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{r.unit}: " + _source_error(label, e, doc_url))
            continue
        for q in qs:
            q.question_id = f"{r.session_id[:6]}_{q.question_id}"
            q.subtopics = list(r.subtopics or [])[:3]
        all_questions += qs
    return all_questions


@app.post("/units/evaluation")
async def create_evaluation(body: dict = Body(...), request: Request = None) -> dict:
    """Build a single evaluation set spanning MULTIPLE units and review it as one.

    Content and questions are fetched from each selected unit's mastersheet links and
    combined, so duplicate/scope/coverage checks run ACROSS the whole exam.
    `set` chooses the question source per unit ('mcq_assignment' or 'in_class_quiz').
    """
    unit_ids = body.get("unit_ids") or []
    source_set = body.get("set", "mcq_assignment")
    questions_url = (body.get("questions_url") or "").strip()  # existing eval doc/link
    title = (body.get("title") or "").strip() or f"Evaluation ({len(unit_ids)} units)"
    rows = _resolve_eval_units(unit_ids)

    eval_id = _eval_id_for(unit_ids, source_set + ("|url" if questions_url else ""))
    _save_eval_session(eval_id, title, rows, owner=auth.reviewer_from_request(request))
    all_chunks, warnings = _fetch_eval_content(eval_id, rows)
    _attach_rubric(eval_id, warnings,
                   text=body.get("rubric_text", ""), url=body.get("rubric_url", ""),
                   criteria=body.get("rubric_criteria"))

    if questions_url:
        all_questions = _questions_from_url(eval_id, questions_url, title)
    else:
        all_questions = _assemble_unit_questions(eval_id, rows, source_set, warnings)

    return await _finalize_evaluation(
        eval_id, unit_ids, all_chunks, all_questions, warnings,
        reviewer=auth.reviewer_from_request(request), force=bool(body.get("force")))


@app.post("/units/evaluation/upload")
async def create_evaluation_upload(
    request: Request,
    unit_ids: str = Form(...),
    file: UploadFile | None = File(None),
    questions_url: str = Form(""),
    set: str = Form("mcq_assignment"),
    title: str = Form(""),
    rubric_file: UploadFile | None = File(None),
    rubric_text: str = Form(""),
    rubric_url: str = Form(""),
    rubric_criteria: str = Form(""),
    force: str = Form(""),
) -> dict:
    """Multipart evaluation entry: like /units/evaluation but able to carry uploaded
    FILES (an exam file and/or a marking-scheme file).

    Questions come from (in order): the uploaded exam `file`, else `questions_url`, else
    assembled from each unit's `set` document. A marking scheme (rubric doc / criteria
    sheet / link / pasted text) can be attached; the agents must follow it and it drives
    deterministic compliance checks. Their slides + tutorials form the scope basis.
    """
    ids = [u.strip() for u in unit_ids.split(",") if u.strip()]
    title = (title or "").strip() or f"Evaluation ({len(ids)} units)"
    questions_url = (questions_url or "").strip()
    rows = _resolve_eval_units(ids)

    eval_id = _eval_id_for(ids, "upload")
    _save_eval_session(eval_id, title, rows, owner=auth.reviewer_from_request(request))
    all_chunks, warnings = _fetch_eval_content(eval_id, rows)
    rubric_bytes = await rubric_file.read() if rubric_file is not None else None
    try:
        parsed_criteria = json.loads(rubric_criteria) if rubric_criteria.strip() else None
    except json.JSONDecodeError:
        parsed_criteria = None
    _attach_rubric(eval_id, warnings, text=rubric_text, url=rubric_url,
                   file_bytes=rubric_bytes,
                   filename=(rubric_file.filename if rubric_file is not None else ""),
                   criteria=parsed_criteria)

    if file is not None:
        data = await file.read()
        try:
            questions = _parse_eval_upload(data, file.filename or "", eval_id, title)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(
                422, f"Could not parse the uploaded evaluation file '{file.filename}': {e}")
        if not questions:
            raise HTTPException(422, "Parsed the file but found no MCQs. Check the format "
                                "(a .zip LMS export, a Google-Doc .md/.txt, or a CSV/XLSX/JSON set).")
    elif questions_url:
        questions = _questions_from_url(eval_id, questions_url, title)
    else:
        questions = _assemble_unit_questions(eval_id, rows, set, warnings)

    return await _finalize_evaluation(
        eval_id, ids, all_chunks, questions, warnings,
        reviewer=auth.reviewer_from_request(request),
        force=str(force).lower() in ("1", "true", "yes"))


@app.post("/units/{unit_id}/prepare_and_run")
async def prepare_and_run(unit_id: str, body: dict = Body(...), request: Request = None) -> dict:
    """One call: fetch this unit's content + questions from the mastersheet links,
    then start the review. `set` is 'mcq_assignment' or 'in_class_quiz'."""
    source_set = body.get("set", "mcq_assignment")
    reviewer = auth.reviewer_from_request(request)
    n, warnings = _fetch_unit(unit_id, source_set)
    questions = store.load_questions(unit_id, source_set, include_deleted=False)
    _guardrail(unit_id, source_set, questions, bool(body.get("force")))
    audit.log("prepared_from_mastersheet",
              detail={"unit_id": unit_id, "set": source_set, "questions": n,
                      "reviewer": reviewer})
    run_id = manager.create_run(unit_id, source_set, reviewer=reviewer)
    await manager.start(run_id)
    return {"run_id": run_id, "status": "running", "questions": n, "warnings": warnings}


def _fetch_unit(unit_id: str, source_set: str) -> tuple[int, list[str]]:
    """Fetch a unit's content + questions from its mastersheet links and save them.
    Returns (num_questions, warnings). Raises HTTPException on hard failure.

    Reference content is the union of the session SLIDES and the TUTORIAL cheat-sheet
    (both keyed to this unit), so the scope/coverage agent grounds questions against
    the slides AND the tutorial together. Questions come from the MCQ link (a Drive
    .zip export, or a Google Doc), chosen automatically by link type.
    """
    from .ingestion.fetch import fetch_content, fetch_questions, fetch_tutorial_content

    row = store.get_unit_row(unit_id)
    if not row:
        raise HTTPException(404, "unit not found")
    label = _SET_LABEL.get(source_set, source_set)
    doc_url = row.mcq_doc_url if source_set == "mcq_assignment" else row.quiz_doc_url
    if not doc_url:
        raise HTTPException(400, f"This unit has no {label} document in the mastersheet.")

    warnings: list[str] = []
    # --- reference content: slides + tutorial cheat-sheet, combined under this unit ---
    if not store.load_chunks(unit_id):
        chunks = []
        if row.content_path and str(row.content_path).lower().startswith("http"):
            try:
                chunks += fetch_content(unit_id, row.content_path)
            except Exception as e:  # noqa: BLE001
                warnings.append(_source_error("slides (PPT)", e, row.content_path))
        if row.tutorial_url and str(row.tutorial_url).lower().startswith("http"):
            try:
                chunks += fetch_tutorial_content(unit_id, row.tutorial_url)
            except Exception as e:  # noqa: BLE001
                warnings.append(_source_error("tutorial", e, row.tutorial_url))
        if chunks:
            store.save_chunks(chunks)

    # --- questions to review ---
    try:
        questions = fetch_questions(unit_id, doc_url, source_set, default_topic=row.unit)
    except PermissionError as e:
        raise HTTPException(403, _source_error(label, e, doc_url))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, _source_error(f"Could not fetch the {label}", e, doc_url))
    if not questions:
        raise HTTPException(422, f"Fetched the {label} but found no parseable MCQs. [{doc_url}]")
    store.save_questions(questions)

    store.mark_prepared(unit_id, source_set)
    return len(questions), warnings


@app.post("/units/batch")
async def batch_review(body: dict = Body(...), request: Request = None) -> dict:
    """Review multiple units SEPARATELY in one action — each gets its own run.
    Returns a batch id and one entry per unit (run_id, or an error if it failed).
    Batch never blocks on the already-reviewed guardrail; each item is annotated instead."""
    import uuid as _uuid

    unit_ids = body.get("unit_ids") or []
    source_set = body.get("set", "mcq_assignment")
    reviewer = auth.reviewer_from_request(request)
    if len(unit_ids) < 2:
        raise HTTPException(400, "Select at least two units for a batch review.")
    items: list[dict] = []
    for uid in unit_ids:
        row = store.get_unit_row(uid)
        unit_name = row.unit if row else uid
        try:
            n, warnings = _fetch_unit(uid, source_set)
            prior = store.find_prior_reviews(uid, source_set)
            run_id = manager.create_run(uid, source_set, reviewer=reviewer)
            await manager.start(run_id)
            items.append({"unit_id": uid, "unit": unit_name, "run_id": run_id,
                          "questions": n, "warnings": warnings,
                          "already_reviewed": bool(prior),
                          "prior": prior[:1]})
        except HTTPException as e:
            items.append({"unit_id": uid, "unit": unit_name, "run_id": None,
                          "error": str(e.detail)})
    batch_id = "batch_" + _uuid.uuid4().hex[:10]
    store.save_batch(batch_id, source_set, items)
    audit.log("batch_review", detail={"batch_id": batch_id, "units": len(unit_ids)})
    return {"batch_id": batch_id, "source_set": source_set, "items": items}


@app.get("/batch/{batch_id}")
def get_batch(batch_id: str) -> dict:
    b = store.get_batch(batch_id)
    if not b:
        raise HTTPException(404, "batch not found")
    out_items = []
    combined = {"total": 0, "APPROVE": 0, "REVISE": 0, "DELETE": 0}
    for it in b["items"]:
        entry = dict(it)
        rid = it.get("run_id")
        if rid:
            with get_session() as db:
                rr = db.get(RunRow, rid)
            if rr:
                entry["status"] = rr.status
                report = rr.report or {}
                vc = report.get("verdict_counts") or {}
                entry["verdict_counts"] = vc
                entry["total_questions"] = report.get("total_questions", 0)
                combined["total"] += entry["total_questions"]
                for k in ("APPROVE", "REVISE", "DELETE"):
                    combined[k] += vc.get(k, 0)
        out_items.append(entry)
    return {"batch_id": batch_id, "source_set": b["source_set"],
            "items": out_items, "combined": combined}


@app.post("/upload/questions")
async def upload_questions(file: UploadFile = File(...),
                           session_id: str = Form(""),
                           source_set: str = Form("mcq_assignment")) -> dict:
    data = await file.read()
    name = (file.filename or "").lower()
    if name.endswith((".md", ".markdown", ".txt")):
        # MCQ document format (as exported from a Google Doc): parse questions from text
        from .ingestion.mcq_text import parse_mcq_text
        questions = parse_mcq_text(data.decode("utf-8", errors="replace"),
                                   session_id or "manual", source_set)
    else:
        questions = parse_questions(data, file.filename, default_session=session_id)
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
def list_sessions(request: Request) -> dict:
    sessions = store.list_sessions(auth.reviewer_from_request(request))
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
async def create_run(body: dict = Body(...), request: Request = None) -> dict:
    session_id = body.get("session_id")
    source_set = body.get("source_set", "mcq_assignment")
    token_limit = body.get("token_limit")
    if not session_id:
        raise HTTPException(400, "session_id is required")
    questions = store.load_questions(session_id, source_set, include_deleted=False)
    if not questions:
        raise HTTPException(400, f"No '{source_set}' questions for session {session_id}")
    _guardrail(session_id, source_set, questions, bool(body.get("force")))
    run_id = manager.create_run(session_id, source_set, token_limit,
                                reviewer=auth.reviewer_from_request(request))
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
        "rubric": store.get_rubric(row.session_id),
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
        "title": store.db_session_title(row.session_id), "reviewer": row.reviewer,
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


@app.post("/runs/{run_id}/bulk_approve")
def bulk_approve(run_id: str, body: dict = Body(default={})) -> dict:
    """Approve many at once. scope='approve_verdict' (default) approves every
    non-deleted question the Judge recommended APPROVE; scope='all_pending'
    approves every pending (non-deleted) question."""
    with get_session() as db:
        row = db.get(RunRow, run_id)
        if not row:
            raise HTTPException(404, "run not found")
    scope = (body or {}).get("scope", "approve_verdict")
    judgments = {j.question_id: j.verdict for j in store.load_judgments(run_id)}
    questions = store.load_questions(row.session_id, row.source_set)
    approved: list[str] = []
    for q in questions:
        cur = store.get_question(q.question_id)
        status = cur[1] if cur else "pending"
        if status in ("approved", "deleted"):
            continue
        if scope == "approve_verdict" and judgments.get(q.question_id) != "APPROVE":
            continue
        store.set_question_status(q.question_id, "approved")
        approved.append(q.question_id)
    audit.log("bulk_approve", actor="human", run_id=run_id,
              detail={"scope": scope, "count": len(approved)})
    return {"approved": len(approved), "question_ids": approved}


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


@app.post("/runs/{run_id}/archive")
def archive_run(run_id: str) -> dict:
    """Push this review's current (post-approval) content to the external store
    (GitHub/S3). Returns the written URLs, or {enabled: false} if not configured."""
    from datetime import datetime, timezone

    from . import export, storage

    with get_session() as db:
        row = db.get(RunRow, run_id)
        if not row:
            raise HTTPException(404, "run not found")
    if not storage.get_backend().enabled():
        return {"enabled": False,
                "message": "No archive backend configured (set ARCHIVE_BACKEND=github)."}

    questions = store.load_questions(row.session_id, row.source_set)
    judgments = store.load_judgments(run_id)
    statuses = {q.question_id: (store.get_question(q.question_id) or (q, "pending"))[1]
                for q in questions}
    title = store.db_session_title(row.session_id)
    record = {
        "run_id": run_id, "session_id": row.session_id, "source_set": row.source_set,
        "title": title, "reviewer": row.reviewer,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "report": row.report,
        "questions": [{**q.model_dump(), "status": statuses.get(q.question_id, "pending")}
                      for q in questions],
        "judgments": [j.model_dump() for j in judgments],
    }
    try:
        urls = storage.archive_review(
            session_id=row.session_id, run_id=run_id, source_set=row.source_set,
            title=title, reviewer=row.reviewer, record=record,
            xlsx=export.export_review_xlsx(questions, judgments))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Archive failed: {e}")
    audit.log("archived_manual", run_id=run_id, detail={"urls": urls})
    return {"enabled": True, "urls": urls}


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
