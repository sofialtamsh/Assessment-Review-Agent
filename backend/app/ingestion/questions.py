"""Question-set ingestion (CSV / XLSX / JSON) -> normalized Question records.

Handles the common layouts:
  * option columns:  option_a / option_b ... or a / b / c / d, OR a JSON `options` list
  * correct key(s):  correct_key / answer / correct_keys (comma/pipe separated for multi)
  * type:            single / multi / multiple / binary / true_false  (inferred if absent)
"""
from __future__ import annotations

import json
import string
from typing import Any

from ..schemas import Option, Question
from .common import first, read_table, split_list

_LETTERS = list(string.ascii_uppercase)


def parse_questions(data: bytes, filename: str, default_session: str = "") -> list[Question]:
    name = (filename or "").lower()
    if name.endswith(".json"):
        rows = _rows_from_json(data)
    else:
        rows = read_table(data, filename)
    questions: list[Question] = []
    for row in rows:
        q = _row_to_question(row, default_session)
        if q is not None:
            questions.append(q)
    return questions


def _rows_from_json(data: bytes) -> list[dict[str, Any]]:
    payload = json.loads(data.decode("utf-8-sig", errors="replace"))
    if isinstance(payload, dict):
        payload = payload.get("questions", payload.get("data", []))
    out = []
    for item in payload or []:
        out.append({str(k).strip().lower().replace(" ", "_"): v for k, v in item.items()})
    return out


def _extract_options(row: dict[str, Any]) -> list[Option]:
    # 1) explicit JSON/list `options`
    raw = row.get("options")
    if isinstance(raw, list) and raw:
        opts = []
        for i, o in enumerate(raw):
            if isinstance(o, dict):
                key = str(o.get("key") or o.get("id") or _LETTERS[i]).strip()
                text = str(o.get("text") or o.get("value") or "").strip()
            else:
                key, text = _LETTERS[i], str(o).strip()
            opts.append(Option(key=key, text=text))
        return opts
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            return _extract_options({"options": json.loads(raw)})
        except json.JSONDecodeError:
            pass

    # 2) columnar option_a.. / a.. / opt_a..
    opts = []
    for letter in _LETTERS:
        low = letter.lower()
        val = first(row, f"option_{low}", f"opt_{low}", low, f"option{low}", default=None)
        if val is None or str(val).strip() == "":
            continue
        opts.append(Option(key=letter, text=str(val).strip()))
    return opts


def _infer_type(row: dict[str, Any], options: list[Option], correct: list[str]) -> str:
    raw = str(first(row, "type", "qtype", "question_type")).strip().lower()
    if raw in {"binary", "true_false", "truefalse", "tf", "boolean"}:
        return "binary"
    if raw in {"multi", "multiple", "multiple_correct", "multi_correct"}:
        return "multi"
    if raw in {"single", "single_correct", "mcq"}:
        return "single"
    # infer
    opt_texts = {o.text.strip().lower() for o in options}
    if opt_texts and opt_texts <= {"true", "false"}:
        return "binary"
    if len(correct) > 1:
        return "multi"
    return "single"


def _row_to_question(row: dict[str, Any], default_session: str) -> Question | None:
    stem = str(first(row, "question", "stem", "question_text", "text")).strip()
    if not stem:
        return None
    session_id = str(first(row, "session_id", "session", "unit", default=default_session)).strip()
    source_set = _norm_source_set(str(first(row, "source_set", "set", "assessment_type")))
    options = _extract_options(row)

    correct = split_list(
        first(row, "correct_keys", "correct_key", "answer", "answers", "correct", "key")
    )
    correct = [_norm_correct_token(c, options) for c in correct]
    correct = [c for c in correct if c]

    qtype = _infer_type(row, options, correct)
    if qtype == "binary" and not options:
        options = [Option(key="True", text="True"), Option(key="False", text="False")]

    qid = str(first(row, "question_id", "id", "qid", default="")).strip()
    if not qid:
        qid = Question.make_id(session_id, stem, source_set)

    difficulty = str(first(row, "difficulty", "level")).strip().lower() or None
    if difficulty not in {"easy", "medium", "hard", None}:
        difficulty = None

    return Question(
        question_id=qid,
        session_id=session_id,
        course=str(first(row, "course")).strip(),
        module=str(first(row, "module")).strip(),
        unit=str(first(row, "unit")).strip(),
        source_set=source_set,
        qtype=qtype,
        stem=stem,
        options=options,
        correct_keys=correct,
        explanation=str(first(row, "explanation", "rationale", "solution")).strip() or None,
        difficulty=difficulty,
        topic=str(first(row, "topic")).strip() or None,
        subtopics=split_list(first(row, "subtopics", "subtopic", "sub_topics")),
        raw=row,
    )


def _norm_source_set(value: str) -> str:
    v = value.strip().lower()
    if v in {"in_class_quiz", "quiz", "in_class", "inclass"}:
        return "in_class_quiz"
    if v in {"examination", "exam", "test"}:
        return "examination"
    return "mcq_assignment"


def _norm_correct_token(token: str, options: list[Option]) -> str:
    """Map an answer cell to an option key. Accepts 'A', 'a', 'True', or option text."""
    t = token.strip()
    if not t:
        return ""
    # already a key?
    keys = {o.key.lower(): o.key for o in options}
    if t.lower() in keys:
        return keys[t.lower()]
    # single letter answer where options use letter keys
    if len(t) == 1 and t.upper() in keys:
        return keys[t.upper()]
    # match by option text
    for o in options:
        if o.text.strip().lower() == t.lower():
            return o.key
    # true/false fallback
    if t.lower() in {"true", "false"}:
        return t.capitalize()
    return t
