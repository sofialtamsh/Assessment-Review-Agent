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


# The reviewed-MCQ delivery format (one "MCQs" sheet), matching the curriculum
# team's question-bank layout. `Key` is written as "Option A/B/C/D".
_REVIEW_FIELDS = ["S. No", "question content", "Option A", "Option B", "Option C",
                  "Option D", "Explanation", "Key", "SUB TOPIC", "Difficulty",
                  "pool", "Image (if any)", "Remarks"]


def _key_as_options(q: Question) -> str:
    """Render the correct key(s) as 'Option A/B/…' by option position."""
    labels: list[str] = []
    for ck in q.correct_keys:
        pos = next((i for i, o in enumerate(q.options) if o.key == ck), None)
        if pos is None:
            up = str(ck).strip().upper()
            if len(up) == 1 and "A" <= up <= "Z":
                pos = ord(up) - 65
        if pos is not None and 0 <= pos < 26:
            labels.append(f"Option {chr(65 + pos)}")
    return ", ".join(labels)


def _review_row(q: Question, sno: int) -> list:
    opts = [q.options[i].text if i < len(q.options) else "" for i in range(4)]
    subtopic = "; ".join(q.subtopics) or (q.topic or "")
    return [sno, q.stem, *opts, q.explanation or "", _key_as_options(q),
            subtopic, q.difficulty or "", "", "", ""]


def export_cleaned_xlsx(questions: list[Question]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "MCQs"
    ws.append(_REVIEW_FIELDS)
    for i, q in enumerate(questions, start=1):
        ws.append(_review_row(q, i))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_review_xlsx(questions: list[Question],
                       judgments: list[Judgment] | None = None) -> bytes:
    """Like the approved export, but includes EVERY reviewed question with its verdict
    (+ reason) in the Remarks column — used for the archived snapshot of a review."""
    from openpyxl import Workbook

    jmap = {j.question_id: j for j in (judgments or [])}
    wb = Workbook()
    ws = wb.active
    ws.title = "MCQs"
    ws.append(_REVIEW_FIELDS)
    for i, q in enumerate(questions, start=1):
        row = _review_row(q, i)
        j = jmap.get(q.question_id)
        row[-1] = (f"{j.verdict}: {j.reason}".strip(": ").strip() if j else "")  # Remarks
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_report_pdf(report: SetReport, findings: list[Finding],
                      judgments: list[Judgment], questions: list[Question]) -> bytes:
    """A shareable PDF of the review report — summary, quality score, rubric
    compliance, and per-question verdicts."""
    from xml.sax.saxutils import escape

    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, leading=12,
                           alignment=TA_LEFT)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Review Report",
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm)
    story: list = []
    story.append(Paragraph(f"Review Report — {escape(report.session_id)}", styles["Title"]))
    story.append(Paragraph(
        f"Quality score: <b>{report.quality_score}/100 ({escape(report.quality_grade)})</b>",
        styles["Heading2"]))
    if report.quality_breakdown.get("explains"):
        story.append(Paragraph(escape(str(report.quality_breakdown["explains"])), small))
    story.append(Spacer(1, 8))

    for line in (
        f"Total questions: <b>{report.total_questions}</b>",
        f"Approval rate: <b>{report.pass_rate:.0%}</b>  ·  Verdicts: {escape(str(report.verdict_counts))}",
        f"Difficulty: {escape(str(report.difficulty_distribution))}",
        f"Duplicates: {sum(len(c.question_ids) for c in report.duplicate_clusters)}  ·  "
        f"Out of scope: {len(report.out_of_scope_ids)}  ·  Verbatim lifts: {len(report.verbatim_lift_ids)}",
    ):
        story.append(Paragraph(line, small))

    if report.rubric_applied and report.rubric_compliance:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Marking-scheme compliance", styles["Heading3"]))
        for c in report.rubric_compliance:
            story.append(Paragraph(
                f"[{escape(c.status.upper())}] {escape(c.name)}", small))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Per-question verdicts", styles["Heading3"]))
    jmap = {j.question_id: j for j in judgments}
    for q in questions:
        j = jmap.get(q.question_id)
        verdict = j.verdict if j else "—"
        reason = f" — {escape(j.reason)}" if j and j.reason else ""
        story.append(Paragraph(
            f"<b>{escape(q.question_id)}</b> [{escape(verdict)}]{reason}", small))
        story.append(Paragraph(escape((q.stem or "")[:300]), small))
        story.append(Spacer(1, 4))

    doc.build(story)
    return buf.getvalue()


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
