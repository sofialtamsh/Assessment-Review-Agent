"""Question-set ingestion (CSV / XLSX / JSON) -> normalized Question records.

Handles the common layouts:
  * option columns:  option_a / option_b ... or a / b / c / d, OR a JSON `options` list
  * correct key(s):  correct_key / answer / correct_keys (comma/pipe separated for multi)
  * type:            single / multi / multiple / binary / true_false  (inferred if absent)
"""
from __future__ import annotations

import json
import re
import string
from typing import Any

from ..schemas import Option, Question
from .common import first, read_all_tables, split_list

_LETTERS = list(string.ascii_uppercase)

# Inline-option format (a Google-Sheet / xlsx "question pool"): the whole MCQ lives
# in one "Questions" cell — stem, then " a) ... b) ... c) ... d) ..." — and the key
# is given in a "Solution" cell as "Option c) ...". The option markers must sit at a
# word boundary (start of line / after whitespace) so LaTeX like "$P(A) + P(B)$" in a
# fill-in-the-blank cell is NOT mistaken for options.
_INLINE_OPT = re.compile(r"(?<![^\s])([a-hA-H])\)(?=\s)")
_SOLUTION_KEY = re.compile(r"option\s*([a-hA-H])\s*\)", re.I)
_HEADER_ECHO = {"question", "questions", "stem", "question_text"}


def parse_questions(data: bytes, filename: str, default_session: str = "") -> list[Question]:
    name = (filename or "").lower()
    if name.endswith(".json"):
        sheets: list[tuple[str, list[dict[str, Any]]]] = [("", _rows_from_json(data))]
    else:
        sheets = read_all_tables(data, filename)
    questions: list[Question] = []
    for _sheet, rows in sheets:
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


# column-name words that MEAN "the correct answer" (any of these, in any combination)
_ANSWER_HINTS = ("answer", "correct", "key", "solution", "ans", "right")
# ...but never these (they're not the answer even if they contain a hint word). Note we do
# NOT exclude "option" — "Correct Option" IS an answer column, and "option_a" has no hint.
_ANSWER_EXCLUDE = ("question", "explanation", "rationale", "distractor")


def _answer_by_meaning(row: dict[str, Any]) -> str:
    """Return the value of the first column whose NAME means 'the answer/key', regardless
    of exact wording — so 'Correct Answer', 'Answer Key', 'Ans', 'Key' all work."""
    for k, v in row.items():
        kl = str(k).lower()
        if any(x in kl for x in _ANSWER_EXCLUDE):
            continue
        if any(h in kl for h in _ANSWER_HINTS) and str(v).strip():
            return str(v)
    return ""


def _field(row: dict[str, Any], *prefixes: str) -> str:
    """Like `first`, but matches a header that STARTS WITH a prefix — for pool sheets
    whose headers carry a parenthetical hint (e.g. 'Difficulty level (Easy, Medium…)'
    normalizes to 'difficulty_level_(easy,…)')."""
    for p in prefixes:
        for k, v in row.items():
            if k.startswith(p) and str(v).strip() != "":
                return str(v).strip()
    return ""


def _split_inline_options(text: str) -> tuple[str, list[Option]]:
    """Split a "stem … a) opt b) opt c) opt" cell into (stem, options).

    Only the longest consecutive run starting at 'a' counts as the option list, so a
    stray 'c)' inside the stem doesn't start it. Returns ('', []) when there's no run.
    """
    seq = []
    expected = 0
    for m in _INLINE_OPT.finditer(text):
        if ord(m.group(1).lower()) - ord("a") == expected:
            seq.append(m)
            expected += 1
    if len(seq) < 2:
        return text.strip(), []
    stem = text[: seq[0].start()].strip()
    options: list[Option] = []
    for i, m in enumerate(seq):
        end = seq[i + 1].start() if i + 1 < len(seq) else len(text)
        options.append(Option(key=m.group(1).upper(), text=text[m.end():end].strip(" .;,\n")))
    return stem, options


def _solution_key(solution: str, options: list[Option]) -> str:
    """Map a 'Solution' cell to an option key: 'Option c) …' -> 'C', a bare leading
    letter, or a match of the solution text against an option's text."""
    if not solution:
        return ""
    keys = {o.key for o in options}
    m = _SOLUTION_KEY.search(solution)
    if m and m.group(1).upper() in keys:
        return m.group(1).upper()
    m2 = re.match(r"\s*([a-hA-H])[).\s]", solution)
    if m2 and m2.group(1).upper() in keys:
        return m2.group(1).upper()
    low = solution.strip().lower()
    for o in options:
        t = o.text.strip().lower()
        if t and (t == low or t in low):
            return o.key
    return ""


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
    stem = str(first(row, "question", "questions", "question_content", "content",
                     "stem", "question_text", "text")).strip()
    if not stem or stem.lower() in _HEADER_ECHO:  # skip blanks and repeated header rows
        return None
    session_id = str(first(row, "session_id", "session", "unit", default=default_session)).strip()
    source_set = _norm_source_set(str(first(row, "source_set", "set", "assessment_type")))
    options = _extract_options(row)

    correct = split_list(
        first(row, "correct_keys", "correct_key", "answer", "answers", "correct", "key")
    )
    correct = [c for c in (_norm_correct_token(c, options) for c in correct) if c]

    # Inline-option "pool" format: no columnar options, but the stem cell holds the
    # options and a "Solution" cell holds the key (a Google-Sheet / xlsx exam pool).
    pool_like = "questions" in row or "solution" in row
    if not options:
        inline_stem, inline_options = _split_inline_options(stem)
        if inline_options:
            stem, options = inline_stem, inline_options
            if not correct:
                key = _solution_key(str(first(row, "solution", "answer_text")), options)
                correct = [key] if key else []
    # Meaning-based fallback (after options are final): ANY column whose name means
    # "answer/key" — varies a lot across sheets ("Correct Answer", "Answer Key", "Ans"…).
    if not correct:
        correct = [c for c in (_norm_correct_token(t, options)
                               for t in split_list(_answer_by_meaning(row))) if c]
    # A row with no options at all isn't an MCQ (e.g. a short-answer pool tab) — skip
    # it, but only for pool-shaped sheets, so plain columnar sets are unaffected.
    if not options and pool_like:
        return None

    qtype = _infer_type(row, options, correct)
    if qtype == "binary" and not options:
        options = [Option(key="True", text="True"), Option(key="False", text="False")]

    qid = str(first(row, "question_id", "id", "qid", default="")).strip()
    if not qid:
        qid = Question.make_id(session_id, stem, source_set)

    difficulty = (str(first(row, "difficulty", "level")).strip()
                  or _field(row, "difficulty")).lower() or None
    if difficulty not in {"easy", "medium", "hard", None}:
        difficulty = None

    return Question(
        question_id=qid,
        session_id=session_id,
        course=str(first(row, "course")).strip(),
        module=(str(first(row, "module")).strip()
                or _field(row, "module", "name_of_the_module")),
        unit=str(first(row, "unit")).strip() or _field(row, "session_name"),
        source_set=source_set,
        qtype=qtype,
        stem=stem,
        options=options,
        correct_keys=correct,
        explanation=str(first(row, "explanation", "rationale", "solution")).strip() or None,
        difficulty=difficulty,
        topic=str(first(row, "topic")).strip() or _field(row, "topic") or None,
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
    keys = {o.key.lower(): o.key for o in options}
    # "Option B" / "option b)" (the exported/question-bank answer style) -> "B"
    m = re.match(r"option\s*([a-h])\b", t, re.I)
    if m and m.group(1).upper() in {o.key for o in options}:
        return m.group(1).upper()
    # already a key?
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
