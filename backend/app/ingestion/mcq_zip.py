"""MCQ ingestion from the LMS export zip.

The MCQ Practice link in the mastersheet points to a Drive-hosted `.zip` that holds
`default_questions.json` (the questions with full content) and `exam_questions.json`
(just an exam_id -> question_id mapping). We parse `default_questions.json`, whose
schema is nested and LMS-specific:

    {
      "question_type": "MULTIPLE_CHOICE" | "MORE_THAN_ONE_MULTIPLE_CHOICE",
      "question": {"question_id", "content", "difficulty", "default_tag_names", ...},
      "explanation_for_answer": str | null,
      "answers": [{"content", "is_correct", "order"}, ...]
    }

This is normalized into our internal `Question` model (option keys A, B, C… assigned
by `order`, correct keys from `is_correct`).
"""
from __future__ import annotations

import io
import json
import string
import zipfile
from typing import Any

from ..schemas import Option, Question

_LETTERS = list(string.ascii_uppercase)
_PREFERRED = ("default_questions.json",)


def parse_mcq_zip(data: bytes, session_id: str, source_set: str = "mcq_assignment",
                  default_topic: str = "") -> list[Question]:
    """Read the questions JSON out of the zip and normalize to `Question`s."""
    payload = _load_questions_json(data)
    questions: list[Question] = []
    for item in payload:
        q = _item_to_question(item, session_id, source_set, default_topic)
        if q is not None:
            questions.append(q)
    return questions


def _load_questions_json(data: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        target = None
        for pref in _PREFERRED:
            for n in names:
                if n.lower().endswith(pref):
                    target = n
                    break
            if target:
                break
        if target is None:
            # any json that decodes to a list of question-shaped dicts
            for n in names:
                if not n.lower().endswith(".json"):
                    continue
                try:
                    p = json.loads(zf.read(n).decode("utf-8-sig", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if isinstance(p, list) and p and isinstance(p[0], dict) and "answers" in p[0]:
                    return p
            raise ValueError("No questions JSON found inside the MCQ zip.")
        payload = json.loads(zf.read(target).decode("utf-8-sig", errors="replace"))
    if isinstance(payload, dict):
        payload = payload.get("questions", payload.get("data", []))
    return payload or []


def _item_to_question(item: dict[str, Any], session_id: str, source_set: str,
                      default_topic: str) -> Question | None:
    q = item.get("question") or {}
    stem = str(q.get("content") or item.get("content") or "").strip()
    if not stem:
        return None

    answers = item.get("answers") or []
    answers = sorted(answers, key=lambda a: a.get("order", 0))
    options: list[Option] = []
    correct: list[str] = []
    for i, a in enumerate(answers):
        key = _LETTERS[i] if i < len(_LETTERS) else f"O{i + 1}"
        options.append(Option(key=key, text=str(a.get("content") or "").strip()))
        if a.get("is_correct"):
            correct.append(key)

    qtype = _infer_type(item.get("question_type"), options, correct)

    qid = str(q.get("question_id") or item.get("question_id") or "").strip()
    if not qid:
        qid = Question.make_id(session_id, stem, source_set)

    difficulty = str(q.get("difficulty") or "").strip().lower() or None
    if difficulty not in {"easy", "medium", "hard", None}:
        difficulty = None

    tags = [str(t).strip() for t in (q.get("concept_tag_names") or q.get("default_tag_names") or [])
            if str(t).strip()]

    return Question(
        question_id=qid,
        session_id=session_id,
        source_set=source_set,  # normalized elsewhere; already one of the valid sets
        qtype=qtype,
        stem=stem,
        options=options,
        correct_keys=correct,
        explanation=str(item.get("explanation_for_answer") or "").strip() or None,
        difficulty=difficulty,
        topic=default_topic or None,
        subtopics=tags,
        raw=item,
    )


def _infer_type(question_type: Any, options: list[Option], correct: list[str]) -> str:
    raw = str(question_type or "").strip().upper()
    if raw in {"MORE_THAN_ONE_MULTIPLE_CHOICE", "MULTIPLE_SELECT", "MULTI"}:
        return "multi"
    if len(correct) > 1:
        return "multi"
    opt_texts = {o.text.strip().lower() for o in options}
    if opt_texts and opt_texts <= {"true", "false"}:
        return "binary"
    return "single"
