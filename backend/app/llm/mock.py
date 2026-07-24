"""Mock LLM provider — deterministic, $0, no API key.

Each phase runs light heuristics over the *already-computed* candidate payload
that the agent node hands it (real embeddings / retrieval happen in the node, not
here). That makes the offline demo genuinely catch the seeded defects: the node
surfaces candidates, the mock "confirms" them the way a real model would. Flip
llm.provider to `openrouter` in config.yaml to swap in real Claude judgments with
zero changes to the node code.
"""
from __future__ import annotations

import json
import re

from .base import AgentResult

_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


class MockProvider:
    def run_agent(self, phase: str, model: str, system_prompt: str, payload: dict) -> AgentResult:
        handler = getattr(self, f"_{phase}", None)
        findings, extra = handler(payload) if handler else ([], {})
        text = json.dumps(payload)
        return AgentResult(
            findings=findings,
            tokens_in=int(len(text) / 4) + len(system_prompt) // 4,
            tokens_out=max(1, len(findings)) * 30,
            extra=extra,
        )

    # ---- Phase 2: language & logic -------------------------------------- #
    def _phase2_language(self, payload: dict):
        out = []
        for q in payload.get("questions", []):
            qid = q["question_id"]
            opts = q.get("options", [])
            texts = [o.get("text", "") for o in opts]
            lower = [t.lower() for t in texts]
            issues = []

            # "all/none of the above" giveaways
            if any("of the above" in t for t in lower):
                issues.append(_f(qid, "phase2_language", "option_giveaway", "WARN",
                                 "Contains an 'all/none of the above' style option, "
                                 "which weakens the distractors.",
                                 "Replace with a concrete distractor."))

            # length leak: correct option markedly longer than distractors
            keyset = set(q.get("correct_keys", []))
            correct = [o.get("text", "") for o in opts if o.get("key") in keyset]
            distractors = [o.get("text", "") for o in opts if o.get("key") not in keyset]
            if correct and distractors:
                clen = max(len(c) for c in correct)
                davg = sum(len(d) for d in distractors) / len(distractors)
                if davg > 0 and clen > 1.7 * davg and clen - davg > 20:
                    issues.append(_f(qid, "phase2_language", "answer_length_leak", "WARN",
                                     "The correct option is substantially longer than the "
                                     "distractors, which can leak the answer.",
                                     "Balance option lengths."))

            # unanswerable / too-short stem
            if len(q.get("stem", "").split()) < 4:
                issues.append(_f(qid, "phase2_language", "unclear_stem", "WARN",
                                 "Stem is very short and may be ambiguous or unanswerable.",
                                 "Expand the stem so it is self-contained."))

            if not issues:
                issues.append(_f(qid, "phase2_language", "language_ok", "PASS",
                                 "Grammar, clarity, and option quality look acceptable."))
            out.extend(issues)
        return out, {}

    # ---- Phase 3: ambiguity & overlap ----------------------------------- #
    def _phase3_ambiguity(self, payload: dict):
        out = []
        for c in payload.get("dup_candidates", []):
            out.append(_f(c["b_id"], "phase3_ambiguity", "semantic_duplicate", "WARN",
                          f"Tests the same concept as {c['a_id']} "
                          f"(similarity {c['similarity']:.2f}): \"{c['a_stem'][:70]}\"",
                          "Keep one; drop or repurpose the other.",
                          related_ids=[c["a_id"]]))
        for c in payload.get("cross_set_candidates", []):
            out.append(_f(c["b_id"], "phase3_ambiguity", "cross_set_overlap", "WARN",
                          f"Effectively the same as in-class quiz question {c['a_id']} "
                          f"(similarity {c['similarity']:.2f}).",
                          "Differentiate the assignment question from the quiz.",
                          related_ids=[c["a_id"]]))
        for c in payload.get("ambiguity_candidates", []):
            out.append(_f(c["question_id"], "phase3_ambiguity", "option_ambiguity", "WARN",
                          c.get("reason", "Two or more options could be defended as correct."),
                          "Reword the stem or the options so exactly one answer is correct."))
        # explicit PASS markers for everything not flagged
        flagged = {f["question_id"] for f in out}
        for qid in payload.get("all_ids", []):
            if qid not in flagged:
                out.append(_f(qid, "phase3_ambiguity", "ambiguity_ok", "PASS",
                              "No duplicate or ambiguity detected."))
        return out, {}

    # ---- Phase 4: scope & source (RAG) ---------------------------------- #
    def _phase4_scope(self, payload: dict):
        out = []
        for item in payload.get("items", []):
            qid = item["question_id"]
            top_ref = item.get("top_ref", "")
            grounded = item.get("tag_in_scope") or \
                item.get("content_overlap", 0.0) >= item.get("min_overlap", 0.33)
            if not grounded:
                out.append(_f(qid, "phase4_scope", "out_of_scope", "FAIL",
                              f"Not covered by what was taught this session "
                              f"(tag not in scope; only {item.get('content_overlap', 0):.0%} "
                              f"of terms appear in the content; closest chunk {top_ref}).",
                              "Remove, or replace with a question grounded in this session."))
                continue
            if (item.get("numeric_overlap", 0) >= 2
                    and item.get("shared_phrase", 0) >= item.get("verbatim_phrase_min", 3)):
                out.append(_f(qid, "phase4_scope", "verbatim_lift", "WARN",
                              f"Copies a specific worked example from {top_ref} "
                              f"(shares {item.get('numeric_overlap')} numbers and a "
                              f"{item.get('shared_phrase')}-word phrase); tests memory, "
                              "not understanding.",
                              "Change the numbers or scenario so it tests understanding."))
                continue
            out.append(_f(qid, "phase4_scope", "in_scope", "PASS",
                          f"Answerable from the session content (see {top_ref})."))
        return out, {}

    # ---- Phase 5: pedagogy ---------------------------------------------- #
    def _phase5_pedagogy(self, payload: dict):
        out = []
        taught = payload.get("taught_subtopics", [])
        covered: dict[str, int] = {t: 0 for t in taught}
        blooms: list[str] = []
        for q in payload.get("questions", []):
            qid = q["question_id"]
            bloom = _bloom(q.get("stem", ""))
            blooms.append(bloom)
            for st in q.get("subtopics", []):
                for t in taught:
                    if t.lower() == st.lower():
                        covered[t] += 1
            code = _has_code(q)
            if code:
                out.append(_f(qid, "phase5_pedagogy", "unexpected_code", "WARN",
                              "Concept question contains code but is not tagged as a "
                              "code question.", "Remove the code or mark it as code-type."))
            out.append(_f(qid, "phase5_pedagogy", "bloom_classified", "PASS",
                          f"Bloom level: {bloom}.", bloom=bloom))

        gaps = [t for t, c in covered.items() if c == 0]
        if gaps:
            out.append(_f("__set__", "phase5_pedagogy", "coverage_gap", "WARN",
                          f"Taught subtopics with zero questions: {gaps}.",
                          "Add questions covering the missing subtopics."))
        if covered:
            mean = sum(covered.values()) / max(1, len(covered))
            over = [t for t, c in covered.items() if mean > 0 and c > 1.5 * mean and c >= 3]
            if over:
                out.append(_f("__set__", "phase5_pedagogy", "over_tested", "WARN",
                              f"Over-tested subtopics: {over}."))
        higher = sum(1 for b in blooms if b in {"Apply", "Analyze", "Evaluate", "Create"})
        ratio = higher / len(blooms) if blooms else 0.0
        verdict = "WARN" if ratio < 0.2 else "PASS"
        out.append(_f("__set__", "phase5_pedagogy", "scenario_ratio", verdict,
                      f"Scenario/higher-order questions: {ratio:.0%} "
                      f"({higher}/{len(blooms)})."
                      + (" Set is mostly recall." if verdict == "WARN" else "")))
        return out, {}

    # ---- Phase 6: judge / aggregator ------------------------------------ #
    def _phase6_judge(self, payload: dict):
        by_q: dict[str, list[dict]] = {}
        for f in payload.get("findings", []):
            by_q.setdefault(f["question_id"], []).append(f)

        delete_checks = {"out_of_scope", "exact_duplicate"}
        judgments = []
        for qid in payload.get("questions", []):
            fs = by_q.get(qid, [])
            bad = [f for f in fs if f.get("verdict") in {"WARN", "FAIL"}]
            fixes = [f.get("suggested_fix") for f in bad if f.get("suggested_fix")]
            if not bad:
                judgments.append(_judgment(qid, "APPROVE",
                                            "All checks passed.", []))
                continue
            checks = {f.get("check_name") for f in bad}
            if checks & delete_checks:
                reason = next(f["evidence"] for f in bad
                              if f.get("check_name") in delete_checks)
                judgments.append(_judgment(qid, "DELETE", reason, fixes))
            else:
                reason = next((f["evidence"] for f in bad if f.get("verdict") == "FAIL"),
                              bad[0]["evidence"])
                judgments.append(_judgment(qid, "REVISE", reason, fixes))
        return judgments, {}

    # ---- Phase 7: fixer -------------------------------------------------- #
    def _phase7_fixer(self, payload: dict):
        """Generate a replacement question grounded in the provided chunks."""
        chunks = payload.get("chunks", [])
        target = payload.get("target", {})
        subtopic = (target.get("subtopics") or ["this topic"])[0]
        base = chunks[0]["text"] if chunks else ""
        # deterministic, content-grounded replacement
        new_q = {
            "stem": f"Based on the session, which statement about {subtopic} is correct?",
            "options": [
                {"key": "A", "text": _first_sentence(base) or f"A true statement about {subtopic}."},
                {"key": "B", "text": f"{subtopic} is unrelated to linear regression."},
                {"key": "C", "text": f"{subtopic} only applies to classification."},
                {"key": "D", "text": f"{subtopic} requires no training data."},
            ],
            "correct_keys": ["A"],
            "explanation": f"Grounded in the session content on {subtopic}.",
            "qtype": "single",
        }
        return [], {"question": new_q}


# --------------------------------------------------------------------------- #
def _f(qid, phase, check, verdict, evidence, fix=None, related_ids=None, bloom=None):
    return {
        "question_id": qid, "phase": phase, "check_name": check, "verdict": verdict,
        "evidence": evidence, "suggested_fix": fix,
        "related_ids": related_ids or [], "bloom": bloom,
    }


def _judgment(qid, verdict, reason, fixes):
    return {"question_id": qid, "verdict": verdict, "reason": reason,
            "consolidated_fixes": fixes}


def _bloom(stem: str) -> str:
    s = stem.lower()
    if any(k in s for k in ["calculate", "compute", "predict", "what is the predicted",
                            "if the", "what is likely", "what will happen"]):
        return "Apply"
    if any(k in s for k in ["why", "compare", "which metric is best", "analyze",
                            "best for", "most appropriate"]):
        return "Analyze"
    if any(k in s for k in ["what does", "what is", "which of the following is",
                            "indicate", "suggest", "control", "measure", "stand for"]):
        return "Understand"
    if any(k in s for k in ["denote", "symbol", "define", "list"]):
        return "Remember"
    return "Understand"


def _has_code(q: dict) -> bool:
    blob = q.get("stem", "") + " " + " ".join(o.get("text", "") for o in q.get("options", []))
    return bool(re.search(r"\b(def |import |print\(|for .* in |lambda |```)", blob))


def _first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return parts[0] if parts else ""
