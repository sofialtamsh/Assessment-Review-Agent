"""Parse MCQs out of a Markdown / plain-text document (as exported from a Google
Doc). Handles the two formats used in the curriculum docs:

  Assignment style:            Tutorial in-class style:
  **1. Question text**         1. Question text
  A. option                    A. option
  B. option                    B. option
  ...                          ...
  **Answer: D**                Answer: B
  explanation paragraph
  ---                          ---

Robust to backslash-escaped markdown (\\*\\*, \\., \\---), CRLF/LF line endings,
bold or plain markers, and "Answer: X — explanation" on one line.
"""
from __future__ import annotations

import re

from ..schemas import Option, Question

# A question starts with an optional **, a number, then . or )
_Q_START = re.compile(r"^\**\s*(\d+)\s*[.)]\s*(.*?)\s*\**\s*$")
_OPTION = re.compile(r"^\**\s*([A-Ha-h])\s*[.)]\s*(.+?)\s*\**\s*$")
_ANSWER = re.compile(r"^\**\s*Answer\s*[:\-]?\s*\**\s*([A-Ha-h])\b(.*)$", re.I)


def parse_mcq_text(text: str, session_id: str, source_set: str,
                   default_topic: str | None = None) -> list[Question]:
    lines = _normalize(text).splitlines()

    # find question-start line indices
    starts = [i for i, ln in enumerate(lines) if _Q_START.match(ln) and not _OPTION.match(ln)]
    if not starts:
        return []
    starts.append(len(lines))

    questions: list[Question] = []
    for b in range(len(starts) - 1):
        block = lines[starts[b]:starts[b + 1]]
        q = _parse_block(block, session_id, source_set, default_topic)
        if q:
            questions.append(q)
    return questions


def _parse_block(block: list[str], session_id: str, source_set: str,
                 topic: str | None) -> Question | None:
    m = _Q_START.match(block[0])
    if not m:
        return None
    num, stem = m.group(1), m.group(2).strip()

    options: list[Option] = []
    correct: list[str] = []
    explanation_parts: list[str] = []
    answer_seen = False

    for ln in block[1:]:
        s = ln.strip()
        if not s or _is_separator(s):
            continue
        am = _ANSWER.match(s)
        if am:
            answer_seen = True
            correct = [am.group(1).upper()]
            tail = am.group(2).strip(" -—:").strip()
            if tail and not _looks_like_key_echo(tail):
                explanation_parts.append(tail)
            continue
        om = _OPTION.match(s)
        if om and not answer_seen:
            options.append(Option(key=om.group(1).upper(), text=om.group(2).strip()))
            continue
        # stem continuation before options, or explanation after answer
        if answer_seen:
            explanation_parts.append(s)
        elif not options:
            stem = f"{stem} {s}".strip()

    if not options or not correct:
        return None

    qid = Question.make_id(session_id, stem + f"|{num}", source_set)
    return Question(
        question_id=qid,
        session_id=session_id,
        source_set=source_set,  # type: ignore[arg-type]
        qtype="single",
        stem=stem,
        options=options,
        correct_keys=[k for k in correct if k in {o.key for o in options}] or correct,
        explanation=" ".join(explanation_parts).strip() or None,
        topic=topic,
        raw={"source": "mastersheet_doc", "number": num},
    )


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    # unescape backslash-escaped markdown punctuation: \*  \.  \-  \(  \)
    text = re.sub(r"\\([*._\-()#>])", r"\1", text)
    return text


def _is_separator(s: str) -> bool:
    return bool(re.fullmatch(r"[-*_]{3,}", s))


def _looks_like_key_echo(tail: str) -> bool:
    # e.g. "Answer: B — Place → Multiply" tail begins repeating the option text;
    # keep it as explanation. Only drop if it's just the letter again.
    return len(tail) <= 2
