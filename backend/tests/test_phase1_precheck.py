"""Phase 1 deterministic checks catch the seeded schema + distribution defects."""
from app.graph.nodes.phase1_precheck import run_precheck


def _checks(findings, qid=None):
    return {f.check_name for f in findings
            if f.verdict != "PASS" and (qid is None or f.question_id == qid)}


def test_key_not_in_options_flagged(sample_questions):
    findings = run_precheck(sample_questions)
    assert "key_not_in_options" in _checks(findings, "q12")


def test_multi_with_single_key_flagged(sample_questions):
    findings = run_precheck(sample_questions)
    assert "multi_single_key" in _checks(findings, "q11")


def test_key_balance_imbalance_flagged(sample_questions):
    findings = run_precheck(sample_questions)
    kb = [f for f in findings if f.check_name == "key_balance"]
    assert kb and kb[0].verdict == "WARN"  # 12/14 answers are 'A'


def test_clean_questions_pass(sample_questions):
    findings = run_precheck(sample_questions)
    assert "schema_ok" in {f.check_name for f in findings if f.question_id == "q01"}
