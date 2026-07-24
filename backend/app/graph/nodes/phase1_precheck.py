"""Phase 1 — deterministic pre-checks. Pure Python, no LLM, always runs.

Per-question schema validation + set-level distribution/duplicate checks. Every
issue is emitted as a structured Finding so downstream phases and the Judge treat
it uniformly. Set-level findings attach to the synthetic id "__set__".
"""
from __future__ import annotations

from collections import Counter

from rapidfuzz import fuzz

from ...config import get_settings
from ...schemas import Finding, Question

SET_ID = "__set__"
PHASE = "phase1_precheck"
_settings = get_settings()


def run_precheck(questions: list[Question]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_schema_checks(questions))
    findings.extend(_duplicate_checks(questions))
    findings.extend(_distribution_checks(questions))
    return findings


# --------------------------------------------------------------------------- #
# Per-question schema validation
# --------------------------------------------------------------------------- #
def _schema_checks(questions: list[Question]) -> list[Finding]:
    out: list[Finding] = []
    for q in questions:
        keys = [o.key for o in q.options]
        keyset = set(keys)

        if not q.options:
            out.append(_fail(q, "missing_options", "Question has no options."))
        if not q.correct_keys:
            out.append(_fail(q, "missing_key", "No correct answer key provided."))

        for k in q.correct_keys:
            if k not in keyset:
                out.append(_fail(
                    q, "key_not_in_options",
                    f"Correct key '{k}' is not among the options {sorted(keyset)}.",
                    fix="Set the correct key to one of the listed option keys.",
                ))

        if q.qtype == "multi" and len(q.correct_keys) <= 1:
            out.append(_fail(
                q, "multi_single_key",
                f"Multiple-correct question has only {len(q.correct_keys)} key(s). "
                "Multi-select questions must have at least two correct options.",
                fix="Mark every correct option, or change the type to 'single'.",
            ))
        if q.qtype == "single" and len(q.correct_keys) > 1:
            out.append(_warn(
                q, "single_multi_key",
                f"Single-correct question has {len(q.correct_keys)} keys. "
                "Change type to 'multi' or reduce to one key.",
            ))
        if q.qtype == "binary" and len(q.options) > 2:
            out.append(_fail(
                q, "binary_too_many_options",
                f"True/False question has {len(q.options)} options; expected exactly 2.",
            ))

        # duplicate option text
        texts = [o.text.strip().lower() for o in q.options if o.text.strip()]
        dupes = [t for t, c in Counter(texts).items() if c > 1]
        if dupes:
            out.append(_warn(
                q, "duplicate_options",
                f"Duplicate option text(s): {dupes}.",
            ))

        # everything clean -> a PASS marker so the dashboard can show coverage
        if not any(f.question_id == q.question_id and f.verdict != "PASS" for f in out):
            out.append(Finding(
                question_id=q.question_id, phase=PHASE,
                check_name="schema_ok", verdict="PASS",
                evidence="Schema validation passed.",
            ))
    return out


# --------------------------------------------------------------------------- #
# Duplicate detection (exact + fuzzy) within the set
# --------------------------------------------------------------------------- #
def _duplicate_checks(questions: list[Question]) -> list[Finding]:
    out: list[Finding] = []
    fuzzy_thr = _settings.thresholds.fuzzy_dup * 100
    seen_exact: dict[str, str] = {}
    for i, q in enumerate(questions):
        norm = _normalize(q.searchable_text())
        if norm in seen_exact:
            out.append(Finding(
                question_id=q.question_id, phase=PHASE,
                check_name="exact_duplicate", verdict="FAIL",
                evidence=f"Identical to question {seen_exact[norm]}.",
                related_ids=[seen_exact[norm]],
                suggested_fix="Remove one of the identical questions.",
            ))
        else:
            seen_exact[norm] = q.question_id

    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            a, b = questions[i], questions[j]
            if _normalize(a.searchable_text()) == _normalize(b.searchable_text()):
                continue  # already caught as exact
            score = fuzz.token_sort_ratio(a.stem, b.stem)
            if score >= fuzzy_thr:
                out.append(Finding(
                    question_id=b.question_id, phase=PHASE,
                    check_name="near_duplicate", verdict="WARN",
                    evidence=f"~{int(score)}% textual overlap with {a.question_id}: "
                             f"\"{a.stem[:70]}\"",
                    related_ids=[a.question_id],
                    suggested_fix="Reword or drop one of the near-duplicate questions.",
                ))
    return out


# --------------------------------------------------------------------------- #
# Set-level distribution sanity
# --------------------------------------------------------------------------- #
def _distribution_checks(questions: list[Question]) -> list[Finding]:
    out: list[Finding] = []
    n = len(questions)
    if n == 0:
        return out

    # answer-key balance across A-D (single/multi only; binary excluded)
    key_counter: Counter[str] = Counter()
    mcq = [q for q in questions if q.qtype != "binary"]
    for q in mcq:
        for k in q.correct_keys:
            key_counter[k] += 1
    if mcq:
        total = sum(key_counter.values()) or 1
        top_key, top_count = key_counter.most_common(1)[0]
        share = top_count / total
        verdict = "WARN" if share >= 0.5 else "PASS"
        out.append(Finding(
            question_id=SET_ID, phase=PHASE,
            check_name="key_balance", verdict=verdict,
            evidence=f"Answer-key distribution {dict(key_counter)}; "
                     f"'{top_key}' is {share:.0%} of keys."
                     + (" Consider rebalancing correct answers across options."
                        if verdict == "WARN" else ""),
        ))

    # difficulty distribution
    diff_counter = Counter(q.difficulty or "unspecified" for q in questions)
    missing = diff_counter.get("unspecified", 0)
    only_one_level = len([k for k in diff_counter if k != "unspecified"]) == 1
    verdict = "WARN" if (missing > n / 2 or only_one_level) else "PASS"
    note = ""
    if missing > n / 2:
        note = f" {missing}/{n} questions have no difficulty tag."
    elif only_one_level:
        note = " All questions share a single difficulty level."
    out.append(Finding(
        question_id=SET_ID, phase=PHASE,
        check_name="difficulty_distribution", verdict=verdict,
        evidence=f"Difficulty distribution {dict(diff_counter)}.{note}",
    ))
    return out


# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _fail(q: Question, check: str, evidence: str, fix: str | None = None) -> Finding:
    return Finding(question_id=q.question_id, phase=PHASE, check_name=check,
                   verdict="FAIL", evidence=evidence, suggested_fix=fix)


def _warn(q: Question, check: str, evidence: str, fix: str | None = None) -> Finding:
    return Finding(question_id=q.question_id, phase=PHASE, check_name=check,
                   verdict="WARN", evidence=evidence, suggested_fix=fix)
