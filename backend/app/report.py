"""Assemble the set-level report from questions, findings, and judgments."""
from __future__ import annotations

from collections import Counter

from .schemas import DuplicateCluster, Finding, Judgment, Question, SetReport

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
                 findings: list[Finding], judgments: list[Judgment]) -> SetReport:
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
    )


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
