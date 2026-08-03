"""Quality score, cross-set duplicate check, docx extraction, and PDF report."""
from __future__ import annotations

import io
import zipfile

from app import crosscheck
from app.export import export_report_pdf
from app.ingestion.content import extract_segments
from app.report import build_report
from app.schemas import Judgment, Option, Question


def _q(qid, stem, difficulty="easy"):
    return Question(question_id=qid, session_id="s", stem=stem,
                    options=[Option(key="A", text="a"), Option(key="B", text="b")],
                    correct_keys=["A"], difficulty=difficulty, source_set="examination")


# --- quality score --------------------------------------------------------- #
def test_quality_score_clean_set_scores_high():
    qs = [_q(f"q{i}", f"question {i}") for i in range(5)]
    js = [Judgment(question_id=q.question_id, verdict="APPROVE") for q in qs]
    r = build_report("s", qs, [], js)
    assert r.quality_score >= 90 and r.quality_grade == "A"
    assert "formula" in r.quality_breakdown


def test_quality_score_drops_with_problems():
    qs = [_q(f"q{i}", f"question {i}") for i in range(5)]
    js = [Judgment(question_id="q0", verdict="APPROVE")] + \
         [Judgment(question_id=f"q{i}", verdict="DELETE") for i in range(1, 5)]
    r = build_report("s", qs, [], js)
    assert r.quality_score < 60 and r.quality_grade in {"D", "F"}


# --- cross-set duplicate check --------------------------------------------- #
def test_cross_set_flags_repeats_only_across_sets():
    set1 = ("Set 1", ["What is the capital of France?", "Define an integer."])
    set2 = ("Set 2", ["what is the capital of france?",   # exact (normalized) repeat
                       "Explain recursion with an example."])
    dups = crosscheck.cross_set_duplicates([set1, set2])
    assert len(dups) == 1
    d = dups[0]
    assert d["exact"] is True and {d["set_a"], d["set_b"]} == {"Set 1", "Set 2"}
    # a within-set pair is never reported
    assert all(x["set_a"] != x["set_b"] for x in dups)


def test_cross_set_fuzzy_near_duplicate():
    a = ("A", ["Find the GCD of 24 and 16 using the Euclidean Algorithm."])
    b = ("B", ["Find GCD (24, 16) using the Euclidean algorithm."])
    dups = crosscheck.cross_set_duplicates([a, b], threshold=80)
    assert dups and dups[0]["similarity"] >= 80 and not dups[0]["exact"]


# --- docx extraction ------------------------------------------------------- #
def test_docx_text_extraction():
    doc_xml = ("<?xml version='1.0'?><w:document xmlns:w='x'><w:body>"
               "<w:p><w:r><w:t>Question one text</w:t></w:r></w:p>"
               "<w:p><w:r><w:t>Question two &amp; more</w:t></w:r></w:p>"
               "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc_xml)
    segs = extract_segments(buf.getvalue(), "exam.docx")
    text = " ".join(t for _r, t in segs)
    assert "Question one text" in text and "Question two & more" in text


# --- pdf report ------------------------------------------------------------ #
def test_pdf_report_is_valid_pdf():
    qs = [_q("q1", "stem one")]
    js = [Judgment(question_id="q1", verdict="APPROVE", reason="clean")]
    r = build_report("s", qs, [], js)
    pdf = export_report_pdf(r, [], js, qs)
    assert pdf[:4] == b"%PDF" and len(pdf) > 500
