"""Run the full 7-phase review on the sample data (or your own files) and print a
detailed per-phase breakdown — a quick way to confirm every phase and check fires.

Usage (from the backend/ directory):
    python scripts/check_phases.py                       # uses sample_data/
    python scripts/check_phases.py path/to/master.csv path/to/questions.csv path/to/content.pptx

Runs entirely offline with the mock provider ($0, no API key). To exercise the real
models instead, set config.yaml -> llm.provider: openrouter and OPENROUTER_API_KEY,
then run this script the same way.
"""
from __future__ import annotations

import sys
from pathlib import Path

# make Windows consoles print UTF-8 without crashing on non-cp1252 characters
_reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(_reconfigure):
    try:
        _reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

# make `app` importable when run as `python scripts/check_phases.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import init_db  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.graph.state import GraphContext  # noqa: E402
from app.ingestion.content import parse_content  # noqa: E402
from app.ingestion.mastersheet import parse_mastersheet  # noqa: E402
from app.ingestion.questions import parse_questions  # noqa: E402
from app.llm import make_runner  # noqa: E402
from app.report import build_phase_summary  # noqa: E402
from app.schemas import CostAccumulator, TokenBudget  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[2] / "sample_data"

BOLD, DIM, GREEN, AMBER, RED, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m",
)
VCOLOR = {"PASS": GREEN, "WARN": AMBER, "FAIL": RED,
          "APPROVE": GREEN, "REVISE": AMBER, "DELETE": RED}


def _c(v: str) -> str:
    return f"{VCOLOR.get(v, '')}{v}{RESET}"


def main() -> None:
    args = sys.argv[1:]
    master = Path(args[0]) if len(args) > 0 else SAMPLE / "mastersheet.csv"
    qfile = Path(args[1]) if len(args) > 1 else SAMPLE / "assignment_session_ds_07.csv"
    cfile = Path(args[2]) if len(args) > 2 else SAMPLE / "session_ds_07.pptx"
    quizfile = SAMPLE / "in_class_quiz_ds_07.csv" if len(args) < 2 else None

    init_db()

    sessions = parse_mastersheet(master.read_bytes(), master.name)
    taught = sessions[0].subtopics if sessions else []
    session_id = sessions[0].session_id if sessions else "session"
    questions = parse_questions(qfile.read_bytes(), qfile.name, default_session=session_id)
    quiz = parse_questions(quizfile.read_bytes(), quizfile.name) if quizfile and quizfile.exists() else []
    chunks = parse_content(session_id, cfile.read_bytes(), cfile.name) if cfile.exists() else []

    print(f"\n{BOLD}Reviewing {len(questions)} questions for session '{session_id}'{RESET}")
    print(f"{DIM}taught subtopics: {taught}{RESET}")
    print(f"{DIM}content chunks: {len(chunks)} | quiz questions (cross-set): {len(quiz)}{RESET}\n")

    runner = make_runner(TokenBudget(limit=0), CostAccumulator())
    graph = build_graph(GraphContext(runner, quiz, chunks, taught))
    state = {"run_id": "cli", "session_id": session_id,
             "questions": questions, "findings": []}
    final = graph.invoke(state)

    findings = final["findings"]
    judgments = final["judgments"]

    # ---- per-phase summary ---------------------------------------------- #
    print(f"{BOLD}== PER-PHASE SUMMARY =={RESET}")
    for p in build_phase_summary(findings, judgments):
        ran = f"{GREEN}ran{RESET}" if p["ran"] else f"{RED}did NOT run{RESET}"
        vc = "  ".join(f"{_c(k)}:{v}" for k, v in p["verdict_counts"].items())
        tag = f"{DIM}(LLM){RESET}" if p["uses_llm"] else f"{DIM}(python){RESET}"
        print(f"\n{BOLD}{p['label']}{RESET} {tag}  [{ran}]  {vc}")
        print(f"  {DIM}flagged questions: {p['questions_flagged']} | "
              f"checks: {', '.join(p['checks']) or '—'}{RESET}")

    # ---- every non-PASS finding, grouped by phase ----------------------- #
    print(f"\n{BOLD}== FINDINGS (issues only), by phase =={RESET}")
    by_phase: dict[str, list] = {}
    for f in findings:
        by_phase.setdefault(f.phase, []).append(f)
    for phase in ["phase1_precheck", "phase2_language", "phase3_ambiguity",
                  "phase4_scope", "phase5_pedagogy"]:
        issues = [f for f in by_phase.get(phase, []) if f.verdict != "PASS"]
        if not issues:
            continue
        print(f"\n{BOLD}{phase}{RESET}")
        for f in issues:
            rel = f" (related: {', '.join(f.related_ids)})" if f.related_ids else ""
            print(f"  {_c(f.verdict)} {f.question_id:8} {f.check_name:20} "
                  f"{f.evidence[:80]}{rel}")

    # ---- final verdicts -------------------------------------------------- #
    print(f"\n{BOLD}== FINAL JUDGE VERDICTS =={RESET}")
    for j in sorted(judgments, key=lambda x: x.question_id):
        print(f"  {_c(j.verdict):20} {j.question_id:8} {j.reason[:70]}")

    r = final["set_report"]
    print(f"\n{BOLD}== SET REPORT =={RESET}")
    print(f"  pass rate: {r.pass_rate:.0%}  |  verdicts: {r.verdict_counts}")
    print(f"  key balance: {r.key_balance}")
    print(f"  bloom: {r.bloom_distribution}")
    print(f"  duplicate clusters: {[(c.kind, c.question_ids) for c in r.duplicate_clusters]}")
    print(f"  out of scope: {r.out_of_scope_ids}  |  verbatim lifts: {r.verbatim_lift_ids}")
    print(f"\n{BOLD}cost:{RESET} {runner.cost.total_tokens} tokens, "
          f"${runner.cost.total_usd:.4f}  {DIM}(provider={runner.settings.llm.provider}){RESET}")
    if final.get("errors"):
        print(f"{RED}errors: {[str(e) for e in final['errors']]}{RESET}")
    print()


if __name__ == "__main__":
    main()
