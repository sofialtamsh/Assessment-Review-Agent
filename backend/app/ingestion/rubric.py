"""Marking-scheme (rubric) ingestion for an evaluation.

A rubric combines two shapes into one `Rubric`:
  * a WRITTEN rubric — a Google Doc / PDF / .md / .txt / pasted text — kept as
    `text` and injected verbatim into the review prompts as authoritative criteria.
  * a STRUCTURED sheet — .xlsx / .csv / Google Sheet with columns like
    criterion / metric / comparator / target / gate — parsed into `criteria`
    the deterministic checker evaluates against the reviewed set.

A structured sheet ALSO yields a readable text summary, so its numeric criteria
reach the LLM phases too. Anything we can't map to a known metric is kept as
guidance-only text (and shows up as a 'manual' compliance check).
"""
from __future__ import annotations

import re
from typing import Any

from ..schemas import Rubric, RubricCriterion
from .common import first, read_all_tables

# --------------------------------------------------------------------------- #
# Metric vocabulary — canonical key -> the phrases a reviewer might write. The
# deterministic checker in report.py knows how to compute each canonical key.
# --------------------------------------------------------------------------- #
_METRIC_ALIASES: dict[str, set[str]] = {
    "higher_order_pct": {
        "higher_order_pct", "higher order pct", "higher order", "hots", "bloom_l3_plus_pct",
        "bloom l3", "bloom l3+", "application pct", "apply/analyze pct", "scenario pct",
        "scenario_vs_recall", "higher order percentage", "higher_order",
    },
    "easy_pct": {"easy_pct", "easy pct", "easy %", "easy percentage", "difficulty_easy_pct", "easy"},
    "medium_pct": {"medium_pct", "medium pct", "medium %", "difficulty_medium_pct", "medium"},
    "hard_pct": {"hard_pct", "hard pct", "hard %", "difficulty_hard_pct", "hard"},
    "duplicate_count": {
        "duplicate_count", "duplicates", "duplicate clusters", "dup_count", "duplicate questions",
    },
    "out_of_scope_count": {
        "out_of_scope_count", "out of scope", "oos", "scope violations", "out-of-scope",
    },
    "verbatim_lift_count": {
        "verbatim_lift_count", "verbatim", "verbatim lifts", "copied from slides", "lifted",
    },
    "approve_rate_pct": {
        "approve_rate_pct", "approve rate", "approval rate", "pass rate", "pass_rate", "approval",
    },
    "uncovered_subtopics": {
        "uncovered_subtopics", "coverage gaps", "uncovered", "missing subtopics", "coverage",
    },
    "max_key_share_pct": {
        "max_key_share_pct", "key balance", "answer balance", "max key share", "option balance",
    },
    "total_questions": {
        "total_questions", "question count", "num questions", "number of questions", "count",
    },
}
_ALIAS_TO_METRIC = {alias: key for key, aliases in _METRIC_ALIASES.items() for alias in aliases}

# how the reviewer might phrase a comparator (column value or embedded in target)
_COMPARATOR_WORDS = {
    "at least": ">=", "minimum": ">=", "min": ">=", "no less than": ">=", "greater than or equal": ">=",
    "at most": "<=", "maximum": "<=", "max": "<=", "no more than": "<=", "less than or equal": "<=",
    "exactly": "==", "equals": "==", "equal": "==", "=": "==",
    "between": "between", "range": "between",
    "no": "==", "none": "==", "zero": "==",
}
_GATES = {"fail", "warn", "info"}


def rubric_from_text(text: str, source: str = "pasted") -> Rubric:
    """A written-only rubric (no structured criteria)."""
    return Rubric(text=(text or "").strip(), criteria=[], source=source)


def rubric_from_bytes(data: bytes, filename: str, source: str = "") -> Rubric:
    """Dispatch by file type: a criteria sheet -> structured criteria (+ summary text);
    anything else (pdf / md / txt) -> written text."""
    name = (filename or "").lower()
    src = source or filename or ""
    if name.endswith((".xlsx", ".xlsm", ".csv")):
        criteria = parse_criteria_sheet(data, filename)
        if criteria:
            return Rubric(text=summary_text(criteria), criteria=criteria, source=src)
        # a sheet with no recognizable criteria columns: fall back to a text dump
    text = _extract_text(data, filename)
    return Rubric(text=text.strip(), criteria=[], source=src)


def merge(written: Rubric | None, structured: Rubric | None) -> Rubric:
    """Combine a written rubric and a structured one into a single Rubric."""
    written = written or Rubric()
    structured = structured or Rubric()
    text = "\n\n".join(t for t in (written.text, structured.text) if t).strip()
    source = " + ".join(s for s in (written.source, structured.source) if s)
    return Rubric(text=text, criteria=structured.criteria + written.criteria, source=source)


# --------------------------------------------------------------------------- #
# Structured criteria sheet
# --------------------------------------------------------------------------- #
def parse_criteria_sheet(data: bytes, filename: str) -> list[RubricCriterion]:
    criteria: list[RubricCriterion] = []
    for _sheet, rows in read_all_tables(data, filename):
        for row in rows:
            c = _row_to_criterion(row)
            if c is not None:
                criteria.append(c)
    return criteria


def _row_to_criterion(row: dict[str, Any]) -> RubricCriterion | None:
    name = str(first(row, "criterion", "name", "rule", "requirement", "check")).strip()
    metric_raw = str(first(row, "metric", "measure", "field")).strip()
    if not name and not metric_raw:
        return None
    if name.lower() in {"criterion", "name", "rule"}:  # header echo
        return None

    metric = _normalize_metric(metric_raw or name)
    comparator = str(first(row, "comparator", "operator", "op", "condition")).strip()
    target = str(first(row, "target", "value", "threshold", "expected", "goal")).strip()
    comparator, target = _resolve_comparator_target(comparator, target, name)

    gate = str(first(row, "gate", "severity", "level", "action")).strip().lower()
    gate = gate if gate in _GATES else ("fail" if metric else "info")

    weight_raw = str(first(row, "weight", "points")).strip()
    try:
        weight = float(weight_raw) if weight_raw else 1.0
    except ValueError:
        weight = 1.0

    return RubricCriterion(
        name=name or metric_raw,
        metric=metric,
        comparator=comparator,
        target=target,
        gate=gate,  # type: ignore[arg-type]
        weight=weight,
        note=name or metric_raw,
    )


def _normalize_metric(raw: str) -> str:
    s = re.sub(r"\s+", " ", (raw or "").strip().lower())
    if not s:
        return ""
    if s in _ALIAS_TO_METRIC:
        return _ALIAS_TO_METRIC[s]
    # substring match: "at least 30% higher-order questions" -> higher_order_pct
    for alias, key in _ALIAS_TO_METRIC.items():
        if alias in s:
            return key
    return ""  # unknown -> guidance-only (manual)


def _resolve_comparator_target(comparator: str, target: str, name: str) -> tuple[str, str]:
    """Normalize the comparator, pulling it from the target or the criterion name if the
    comparator column is blank. Returns (comparator, cleaned_target)."""
    comp = (comparator or "").strip().lower()
    comp = _COMPARATOR_WORDS.get(comp, comp)

    blob = " ".join(x for x in (target, name) if x).lower()
    # explicit range "40-50" / "40 to 50"
    rng = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", blob)
    if rng and (comp in {"", "between"}):
        return "between", f"{rng.group(1)}-{rng.group(2)}"

    # comparator embedded in the target cell, e.g. ">= 30", "<=0"
    m = re.search(r"(>=|<=|==|=|>|<)\s*", target or "")
    if m and comp in {"", "=="}:
        sym = m.group(1)
        comp = "==" if sym == "=" else sym

    if not comp:
        # phrases like "no more than 2" / "at least 30%" in the name
        for word, sym in _COMPARATOR_WORDS.items():
            if word in blob:
                comp = sym
                break
    if not comp:
        comp = ">="

    num = _first_number(target) or _first_number(name)
    return comp, (num if num is not None else (target or "").strip())


def _first_number(text: str) -> str | None:
    m = re.search(r"(\d+(?:\.\d+)?)", text or "")
    return m.group(1) if m else None


def summary_text(criteria: list[RubricCriterion]) -> str:
    lines = []
    for c in criteria:
        tgt = f"{c.comparator} {c.target}".strip()
        lines.append(f"- {c.name}: {tgt} [{c.gate}]")
    return "## Marking-scheme criteria\n" + "\n".join(lines) if lines else ""


# --------------------------------------------------------------------------- #
# Written rubric text extraction
# --------------------------------------------------------------------------- #
def _extract_text(data: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith((".md", ".markdown", ".txt", "")):
        return data.decode("utf-8-sig", errors="replace")
    # pdf / pptx via the content extractor; other types -> best-effort decode
    from .content import extract_segments

    try:
        segments = extract_segments(data, filename)
        joined = "\n\n".join(t for _ref, t in segments if t).strip()
        if joined:
            return joined
    except Exception:  # noqa: BLE001
        pass
    return data.decode("utf-8-sig", errors="replace")
