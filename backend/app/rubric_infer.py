"""Reverse-engineer a marking scheme from a reference set of (good) questions.

Given a gold/approved question set, derive a `Rubric` that new sets should follow to
match it: structured criteria the deterministic checker can enforce (difficulty mix,
answer-key balance, no duplicates/verbatim lifts) PLUS written guidance describing the
observed conventions (option count, explanation expectation, question-type mix) for the
LLM review phases.

Deterministic only — no LLM, no cost. Everything is computed from the parsed questions.
"""
from __future__ import annotations

from collections import Counter

from .ingestion.rubric import summary_text
from .schemas import Question, Rubric, RubricCriterion


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _band(center: int, spread: int = 15) -> str:
    lo = max(0, center - spread)
    hi = min(100, center + spread)
    return f"{lo}-{hi}"


def infer_rubric(questions: list[Question], source: str = "") -> Rubric:
    n = len(questions)
    if n == 0:
        return Rubric(text="", criteria=[], source=source)

    # --- observed stats ---------------------------------------------------- #
    opt_counts = Counter(len(q.options) for q in questions)
    common_opts = opt_counts.most_common(1)[0][0]

    expl_pct = _pct(sum(1 for q in questions if (q.explanation or "").strip()), n)

    qtypes = Counter(q.qtype for q in questions)
    single_pct, multi_pct, binary_pct = (
        _pct(qtypes.get("single", 0), n), _pct(qtypes.get("multi", 0), n),
        _pct(qtypes.get("binary", 0), n))

    labelled = [q.difficulty for q in questions if q.difficulty in ("easy", "medium", "hard")]
    diff = Counter(labelled)
    have_difficulty = len(labelled) >= max(1, n // 2)

    key_counts: Counter[str] = Counter()
    for q in questions:
        if q.qtype != "binary":
            for k in q.correct_keys:
                key_counts[k] += 1
    total_keys = sum(key_counts.values())
    max_key_share = _pct(max(key_counts.values()), total_keys) if total_keys else 0

    # --- structured criteria (enforced by the compliance checker) ---------- #
    criteria: list[RubricCriterion] = []
    if have_difficulty:
        for level, metric in (("easy", "easy_pct"), ("medium", "medium_pct"),
                              ("hard", "hard_pct")):
            criteria.append(RubricCriterion(
                name=f"Difficulty: {level} share near reference",
                metric=metric, comparator="between",
                target=_band(_pct(diff.get(level, 0), len(labelled))),
                gate="warn", note=f"reference had {_pct(diff.get(level, 0), len(labelled))}% {level}"))
    # answer-key balance: cap the dominant key near what the reference achieved
    key_cap = max(30, min(100, ((max_key_share // 5) + 1) * 5))
    criteria.append(RubricCriterion(
        name="No answer key over-represented", metric="max_key_share_pct",
        comparator="<=", target=str(key_cap), gate="warn",
        note=f"reference max key share was {max_key_share}%"))
    # a clean reference set has no duplicates or lifted content
    criteria.append(RubricCriterion(
        name="No duplicate / near-duplicate questions", metric="duplicate_count",
        comparator="==", target="0", gate="fail"))
    criteria.append(RubricCriterion(
        name="No verbatim lifts from the source material", metric="verbatim_lift_count",
        comparator="==", target="0", gate="warn"))
    criteria.append(RubricCriterion(
        name="No out-of-scope questions", metric="out_of_scope_count",
        comparator="==", target="0", gate="warn"))

    # --- written guidance (fed to the LLM review phases) ------------------- #
    lines = [f"# Marking scheme (reverse-engineered from {n} reference questions)", "",
             "Follow the conventions observed in the reference set:",
             f"- Each question should offer {common_opts} options."]
    if expl_pct >= 70:
        lines.append(f"- Every question must include a clear explanation "
                     f"({expl_pct}% of the reference set had one).")
    elif expl_pct:
        lines.append(f"- Explanations are expected where helpful "
                     f"({expl_pct}% of the reference set had one).")
    mix = ", ".join(f"{p}% {name}" for p, name in
                    ((single_pct, "single-answer"), (multi_pct, "multi-answer"),
                     (binary_pct, "true/false")) if p)
    if mix:
        lines.append(f"- Question-type mix in the reference: {mix}.")
    if have_difficulty:
        lines.append("- Match the reference difficulty mix: "
                     + ", ".join(f"{_pct(diff.get(l, 0), len(labelled))}% {l}"
                                 for l in ("easy", "medium", "hard")) + ".")
    lines += [
        "- Distractors must be plausible, mutually exclusive, and must not give the answer away.",
        "- No duplicate or near-duplicate questions; no text lifted verbatim from the slides.",
        "", summary_text(criteria),
    ]

    return Rubric(text="\n".join(lines).strip(), criteria=criteria,
                  source=source or "reverse-engineered")
