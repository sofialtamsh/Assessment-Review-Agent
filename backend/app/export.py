"""Export the cleaned (approved) question set and the review report."""
from __future__ import annotations

import csv
import io
import json

from .schemas import Finding, Judgment, Question, SetReport

APPROVED_STATUSES = {"approved"}

_FIELDS = ["question_id", "session_id", "source_set", "type", "question",
           "option_a", "option_b", "option_c", "option_d",
           "correct_key", "explanation", "difficulty", "topic", "subtopics"]


def _row(q: Question) -> dict:
    opts = {f"option_{chr(97 + i)}": (q.options[i].text if i < len(q.options) else "")
            for i in range(4)}
    return {
        "question_id": q.question_id, "session_id": q.session_id,
        "source_set": q.source_set, "type": q.qtype, "question": q.stem, **opts,
        "correct_key": ";".join(q.correct_keys), "explanation": q.explanation or "",
        "difficulty": q.difficulty or "", "topic": q.topic or "",
        "subtopics": ";".join(q.subtopics),
    }


def export_cleaned_csv(questions: list[Question]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_FIELDS)
    w.writeheader()
    for q in questions:
        w.writerow(_row(q))
    return buf.getvalue().encode("utf-8")


def export_cleaned_json(questions: list[Question]) -> bytes:
    return json.dumps({"questions": [_row(q) for q in questions]},
                      indent=2, ensure_ascii=False).encode("utf-8")


def export_cleaned_xlsx(questions: list[Question]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "approved"
    ws.append(_FIELDS)
    for q in questions:
        r = _row(q)
        ws.append([r[f] for f in _FIELDS])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_report_markdown(report: SetReport, findings: list[Finding],
                           judgments: list[Judgment], questions: list[Question]) -> bytes:
    qmap = {q.question_id: q for q in questions}
    jmap = {j.question_id: j for j in judgments}
    lines: list[str] = []
    a = lines.append
    a(f"# Review Report — Session {report.session_id}\n")
    a("## Summary\n")
    a(f"- Total questions: **{report.total_questions}**")
    a(f"- Approval (pass) rate: **{report.pass_rate:.0%}**")
    a(f"- Verdicts: {report.verdict_counts}")
    a(f"- Answer-key balance: {report.key_balance}")
    a(f"- Difficulty: {report.difficulty_distribution}")
    a(f"- Bloom's distribution: {report.bloom_distribution}")
    a(f"- Scenario vs recall ratio: **{report.scenario_vs_recall_ratio:.0%}**")
    if report.duplicate_clusters:
        a("\n### Duplicate clusters")
        for c in report.duplicate_clusters:
            a(f"- ({c.kind}) {', '.join(c.question_ids)}")
    if report.out_of_scope_ids:
        a(f"\n### Out of scope: {', '.join(report.out_of_scope_ids)}")
    if report.verbatim_lift_ids:
        a(f"### Verbatim lifts: {', '.join(report.verbatim_lift_ids)}")
    gaps = [st for st, c in report.subtopic_coverage.items() if c == 0]
    if gaps:
        a(f"### Coverage gaps (zero questions): {', '.join(gaps)}")

    if report.rubric_applied:
        a("\n## Marking-scheme compliance")
        if report.rubric_compliance:
            for c in report.rubric_compliance:
                detail = ("review manually" if c.status == "manual"
                          else f"{c.actual} vs {c.comparator} {c.target}")
                a(f"- **{c.status.upper()}** — {c.name} ({detail})")
        else:
            a("- A written rubric guided the review agents (no structured criteria).")

    a("\n## Per-question findings\n")
    by_q: dict[str, list[Finding]] = {}
    for f in findings:
        by_q.setdefault(f.question_id, []).append(f)
    for qid, q in qmap.items():
        j = jmap.get(qid)
        verdict = j.verdict if j else "—"
        a(f"### {qid} — {verdict}")
        a(f"> {q.stem}")
        if j and j.reason:
            a(f"- **Reason:** {j.reason}")
        for f in by_q.get(qid, []):
            if f.verdict != "PASS":
                a(f"- `{f.phase}` **{f.verdict}** {f.check_name}: {f.evidence}")
        a("")
    return "\n".join(lines).encode("utf-8")
