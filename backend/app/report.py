"""Assemble the set-level report from questions, findings, and judgments."""
from __future__ import annotations

import re
from collections import Counter

from .schemas import (
    DuplicateCluster,
    Finding,
    Judgment,
    Question,
    RubricCheck,
    RubricCriterion,
    SetReport,
)

# Canonical phase order + labels for the per-phase verification view.
PHASE_META = [
    ("phase1_precheck", "Phase 1 — Deterministic pre-checks", False),
    ("phase2_language", "Phase 2 — Language & Logic", True),
    ("phase3_ambiguity", "Phase 3 — Ambiguity & Overlap", True),
    ("phase4_scope", "Phase 4 — Scope & Source (RAG)", True),
    ("phase5_pedagogy", "Phase 5 — Pedagogy", True),
    ("phase6_judge", "Phase 6 — Judge / Aggregator", True),
]


def build_phase_summary(findings: list[Finding], judgments: list[Judgment]) -> list[dict]:
    """Per-phase breakdown so a reviewer can confirm every phase ran and see
    which checks fired. Phases 1-5 come from findings; phase 6 from judgments.
    """
    by_phase: dict[str, list[Finding]] = {}
    for f in findings:
        by_phase.setdefault(f.phase, []).append(f)

    summary: list[dict] = []
    for key, label, uses_llm in PHASE_META:
        if key == "phase6_judge":
            counts = Counter(j.verdict for j in judgments)
            summary.append({
                "phase": key, "label": label, "uses_llm": uses_llm,
                "ran": bool(judgments),
                "verdict_counts": dict(counts),
                "checks": sorted({"APPROVE", "REVISE", "DELETE"} & set(counts)),
                "total_findings": sum(counts.values()),
                "questions_flagged": counts.get("REVISE", 0) + counts.get("DELETE", 0),
            })
            continue

        fs = by_phase.get(key, [])
        vcounts = Counter(f.verdict for f in fs)
        check_breakdown: dict[str, dict] = {}
        for f in fs:
            cb = check_breakdown.setdefault(f.check_name, {"PASS": 0, "WARN": 0, "FAIL": 0})
            cb[f.verdict] = cb.get(f.verdict, 0) + 1
        flagged = {f.question_id for f in fs
                   if f.verdict != "PASS" and f.question_id != "__set__"}
        summary.append({
            "phase": key, "label": label, "uses_llm": uses_llm,
            "ran": bool(fs),
            "verdict_counts": dict(vcounts),
            "checks": sorted(check_breakdown.keys()),
            "check_breakdown": check_breakdown,
            "total_findings": len(fs),
            "questions_flagged": len(flagged),
        })
    return summary

_DUP_CHECKS = {
    "exact_duplicate": "exact",
    "near_duplicate": "fuzzy",
    "semantic_duplicate": "semantic",
    "cross_set_overlap": "cross_set",
}


def build_report(session_id: str, questions: list[Question],
                 findings: list[Finding], judgments: list[Judgment],
                 rubric: dict | None = None) -> SetReport:
    n = len(questions)
    verdicts = Counter(j.verdict for j in judgments)
    approve = verdicts.get("APPROVE", 0)

    # key balance (A-D), single/multi only
    key_balance: Counter[str] = Counter()
    for q in questions:
        if q.qtype != "binary":
            for k in q.correct_keys:
                key_balance[k] += 1

    difficulty = Counter(q.difficulty or "unspecified" for q in questions)

    # bloom distribution from phase-5 findings
    bloom = Counter(f.bloom for f in findings if f.bloom)

    # duplicate clusters, grouped transitively across dup-type findings
    clusters = _cluster_duplicates(findings)

    out_of_scope = sorted({
        f.question_id for f in findings if f.check_name == "out_of_scope"
    })
    verbatim = sorted({
        f.question_id for f in findings if f.check_name == "verbatim_lift"
    })

    # subtopic coverage from questions (0 = gap); the taught set drives this in phase 5
    coverage: Counter[str] = Counter()
    for q in questions:
        for st in q.subtopics:
            coverage[st] += 1

    over_tested = [
        f.evidence for f in findings if f.check_name == "over_tested"
    ]

    # scenario ratio
    higher = sum(1 for b in bloom.elements()
                 if b in {"Apply", "Analyze", "Evaluate", "Create"})
    total_bloom = sum(bloom.values())
    ratio = round(higher / total_bloom, 3) if total_bloom else 0.0

    # marking-scheme compliance (deterministic checks over the metrics above)
    metric_values = _metric_values(
        n, ratio, difficulty, clusters, out_of_scope, verbatim, key_balance,
        approve, findings,
    )
    criteria = [RubricCriterion(**c) for c in (rubric or {}).get("criteria", [])]
    compliance = evaluate_rubric(criteria, metric_values)
    rubric_applied = bool((rubric or {}).get("text") or criteria)

    dup_questions = len({qid for c in clusters for qid in c.question_ids})
    q_score, q_grade, q_breakdown = _quality_score(
        n, approve, dup_questions, len(verbatim), len(out_of_scope), compliance)

    return SetReport(
        session_id=session_id,
        total_questions=n,
        pass_rate=round(approve / n, 3) if n else 0.0,
        verdict_counts=dict(verdicts),
        key_balance=dict(key_balance),
        difficulty_distribution=dict(difficulty),
        bloom_distribution=dict(bloom),
        duplicate_clusters=clusters,
        out_of_scope_ids=out_of_scope,
        verbatim_lift_ids=verbatim,
        subtopic_coverage=dict(coverage),
        over_tested_subtopics=over_tested,
        scenario_vs_recall_ratio=ratio,
        rubric_applied=rubric_applied,
        rubric_compliance=compliance,
        quality_score=q_score,
        quality_grade=q_grade,
        quality_breakdown=q_breakdown,
    )


def _quality_score(n: int, approve: int, dup_questions: int, verbatim: int,
                   out_of_scope: int, compliance: list) -> tuple[int, str, dict]:
    """A single 0-100 quality score for the set, blended from two transparent parts:

      * Approval  (60%) - the share of questions the Judge approved.
      * Cleanliness (40%) - how free the set is of problems (duplicates, out-of-scope,
        verbatim lifts, and any failed marking-scheme criteria), as a share of the set.

    Kept deliberately simple so a reviewer can read the number and understand WHY.
    """
    if not n:
        return 0, "N/A", {}
    approval = 100 * approve / n
    rubric_fails = sum(1 for c in compliance if getattr(c, "status", "") == "fail")
    problems = dup_questions + verbatim + out_of_scope + rubric_fails
    clean = max(0.0, 100 * (1 - problems / n))
    score = round(0.6 * approval + 0.4 * clean)
    grade = ("A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70
             else "D" if score >= 60 else "F")
    breakdown = {
        "approval_pct": round(approval, 1),
        "cleanliness_pct": round(clean, 1),
        "problems": problems,
        "formula": "0.6 x approval% + 0.4 x cleanliness%",
        "explains": (
            f"{approve}/{n} approved; {problems} flagged "
            f"({dup_questions} duplicate, {out_of_scope} out-of-scope, "
            f"{verbatim} verbatim, {rubric_fails} rubric-fail)."),
    }
    return score, grade, breakdown


# --------------------------------------------------------------------------- #
# Marking-scheme (rubric) compliance
# --------------------------------------------------------------------------- #
def _metric_values(n, ratio, difficulty, clusters, out_of_scope, verbatim,
                   key_balance, approve, findings) -> dict[str, float]:
    """Compute each supported rubric metric from the set-level tallies."""
    pct = lambda c: round(100 * c / n, 1) if n else 0.0
    total_keys = sum(key_balance.values())
    coverage_gaps = sum(1 for f in findings if f.check_name in
                        {"coverage_gap", "subtopic_gap", "uncovered_subtopic"})
    return {
        "total_questions": float(n),
        "higher_order_pct": round(ratio * 100, 1),
        "easy_pct": pct(difficulty.get("easy", 0)),
        "medium_pct": pct(difficulty.get("medium", 0)),
        "hard_pct": pct(difficulty.get("hard", 0)),
        "duplicate_count": float(len(clusters)),
        "out_of_scope_count": float(len(out_of_scope)),
        "verbatim_lift_count": float(len(verbatim)),
        "approve_rate_pct": pct(approve),
        "max_key_share_pct": round(100 * max(key_balance.values()) / total_keys, 1)
        if total_keys else 0.0,
        "uncovered_subtopics": float(coverage_gaps),
    }


def evaluate_rubric(criteria: list[RubricCriterion],
                    values: dict[str, float]) -> list[RubricCheck]:
    checks: list[RubricCheck] = []
    for c in criteria:
        if not c.metric or c.metric not in values:
            checks.append(RubricCheck(
                name=c.name, metric=c.metric, comparator=c.comparator, target=c.target,
                actual="", gate=c.gate, status="manual",
                detail="No automatic metric for this criterion — review manually.",
            ))
            continue
        actual = values[c.metric]
        ok = _compare(actual, c.comparator, c.target)
        if ok:
            status = "pass"
        elif c.gate == "fail":
            status = "fail"
        else:
            status = "warn"
        checks.append(RubricCheck(
            name=c.name, metric=c.metric, comparator=c.comparator, target=c.target,
            actual=_fmt(actual), gate=c.gate, status=status,
            detail=f"actual {_fmt(actual)} vs {c.comparator} {c.target}",
        ))
    return checks


def _compare(actual: float, comparator: str, target: str) -> bool:
    if comparator == "between":
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)", target or "")
        if not m:
            return True  # unparseable target -> don't fail the set
        lo, hi = float(m.group(1)), float(m.group(2))
        return lo <= actual <= hi
    t = _first_num(target)
    if t is None:
        return True
    if comparator == ">=":
        return actual >= t
    if comparator == "<=":
        return actual <= t
    if comparator == ">":
        return actual > t
    if comparator == "<":
        return actual < t
    if comparator in {"==", "="}:
        return abs(actual - t) < 1e-9
    return actual >= t


def _first_num(text: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(round(v, 1))


def _cluster_duplicates(findings: list[Finding]) -> list[DuplicateCluster]:
    # union-find over question ids linked by any duplicate/overlap finding
    parent: dict[str, str] = {}
    kinds: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    edge_kind: dict[tuple[str, str], str] = {}
    for f in findings:
        kind = _DUP_CHECKS.get(f.check_name)
        if not kind:
            continue
        for rel in f.related_ids:
            union(f.question_id, rel)
            edge_kind[(f.question_id, rel)] = kind

    groups: dict[str, list[str]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)

    clusters: list[DuplicateCluster] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        # pick the "strongest" kind present in the group
        member_set = set(members)
        present = [k for (a, b), k in edge_kind.items()
                   if a in member_set and b in member_set]
        kind = _dominant_kind(present)
        clusters.append(DuplicateCluster(
            question_ids=sorted(members), kind=kind,
            detail=f"{len(members)} questions linked as {kind} duplicates/overlap.",
        ))
    return clusters


def _dominant_kind(kinds: list[str]) -> str:
    for k in ("exact", "cross_set", "semantic", "fuzzy"):
        if k in kinds:
            return k
    return "semantic"
