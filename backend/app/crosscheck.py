"""Cross-set duplicate check for multi-set exams.

Universities often ship one exam as several sets (Set 1 / Set 2 / Set 3) over the
SAME syllabus — the sets are meant to be DIFFERENT so students can't copy. This
checks the opposite failure: a question accidentally repeated across sets.

Given N uploaded sets, we pull each set's question texts (structured MCQ files parse
cleanly; docx/pdf/txt exam papers are split heuristically) and compare every question
against those in the OTHER sets — exact match or fuzzy near-match (rapidfuzz). We never
compare a set against itself (that's the normal within-set duplicate check).
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from .ingestion.questions import parse_questions


def extract_items(data: bytes, filename: str) -> list[str]:
    """A set's question texts. Structured question files parse to stems; exam papers
    (docx/pdf/txt/md) are split into question-like segments."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".csv", ".json")):
        qs = parse_questions(data, filename)
        if qs:
            return [q.searchable_text() for q in qs if q.stem]
    from .ingestion.content import extract_segments

    text = "\n".join(t for _ref, t in extract_segments(data, filename))
    return split_questions(text)


_Q_MARK = re.compile(r"(?m)^\s*(?:Q\.?\s*)?\d+\s*[.)]|\b\d+\s*[a-e]\s*\)")


def split_questions(text: str) -> list[str]:
    """Best-effort split of an exam paper's text into individual questions."""
    if not text:
        return []
    marks = [m.start() for m in _Q_MARK.finditer(text)]
    if len(marks) >= 2:
        blocks = [text[a:b] for a, b in zip(marks, marks[1:] + [len(text)])]
    else:
        blocks = re.split(r"\n{2,}", text)
    out = []
    for b in blocks:
        s = re.sub(r"\s+", " ", b).strip()
        if len(s) >= 20:                     # skip headers / stray lines
            out.append(s[:400])
    return out


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", (t or "").lower())).strip()


def cross_set_duplicates(sets: list[tuple[str, list[str]]],
                         threshold: int = 85) -> list[dict]:
    """Return cross-set duplicate/near-duplicate pairs. `sets` is [(name, [texts])].

    Only pairs from DIFFERENT sets are reported. Exact matches score 100; otherwise a
    fuzzy token-set ratio must clear `threshold` (default 85%)."""
    flat = [(name, _norm(t), t) for name, items in sets for t in items]
    matches: list[dict] = []
    for i in range(len(flat)):
        na, norm_a, ta = flat[i]
        if not norm_a:
            continue
        for k in range(i + 1, len(flat)):
            nb, norm_b, tb = flat[k]
            if na == nb or not norm_b:        # same set, or empty -> skip
                continue
            score = 100 if norm_a == norm_b else int(fuzz.token_set_ratio(norm_a, norm_b))
            if score >= threshold:
                matches.append({
                    "set_a": na, "set_b": nb, "similarity": score,
                    "exact": norm_a == norm_b,
                    "question_a": ta[:240], "question_b": tb[:240],
                })
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    return matches
