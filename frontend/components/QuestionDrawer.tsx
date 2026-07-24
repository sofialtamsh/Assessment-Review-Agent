"use client";

import { useState } from "react";
import {
  applyRegeneration,
  editQuestion,
  questionAction,
  regenerateQuestion,
} from "@/lib/api";
import type { Finding, QuestionRow } from "@/lib/types";
import { FindingBadge, PHASE_PRETTY, StatusPill, VerdictChip } from "./ui";

function OptionList({ q }: { q: QuestionRow }) {
  return (
    <ul className="mt-3 space-y-1.5">
      {q.options.map((o) => {
        const correct = q.correct_keys.includes(o.key);
        return (
          <li
            key={o.key}
            className={`flex gap-2 rounded-lg px-3 py-2 text-sm ${
              correct ? "bg-emerald-50 text-emerald-800" : "bg-black/[0.02]"
            }`}
          >
            <span className="font-semibold">{o.key}.</span>
            <span>{o.text}</span>
            {correct && <span className="ml-auto text-xs font-semibold">correct</span>}
          </li>
        );
      })}
    </ul>
  );
}

function FindingItem({ f }: { f: Finding }) {
  return (
    <div className="rounded-lg border border-black/[0.06] p-3">
      <div className="flex items-center gap-2">
        <FindingBadge v={f.verdict} />
        <span className="text-xs font-medium text-black/50">
          {PHASE_PRETTY[f.phase] || f.phase} · {f.check_name}
        </span>
        {f.bloom && <span className="chip bg-accent-50 text-accent-700">{f.bloom}</span>}
        {f.model && <span className="ml-auto text-[10px] text-black/30">{f.model}</span>}
      </div>
      <p className="mt-1.5 text-sm text-black/70">{f.evidence}</p>
      {f.related_ids.length > 0 && (
        <p className="mt-1 text-xs text-black/40">Related: {f.related_ids.join(", ")}</p>
      )}
      {f.suggested_fix && (
        <p className="mt-1 text-xs text-accent-700">→ {f.suggested_fix}</p>
      )}
    </div>
  );
}

export default function QuestionDrawer({
  q,
  runId,
  onClose,
  onChanged,
}: {
  q: QuestionRow;
  runId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [stem, setStem] = useState(q.stem);
  const [keys, setKeys] = useState(q.correct_keys.join(","));
  const [candidate, setCandidate] = useState<any>(null);
  const [recheck, setRecheck] = useState<Finding[]>([]);
  const [err, setErr] = useState("");

  async function act(fn: () => Promise<any>) {
    setBusy(true);
    setErr("");
    try {
      await fn();
      onChanged();
    } catch (e: any) {
      setErr(e.message || "Action failed");
    } finally {
      setBusy(false);
    }
  }

  async function doRegenerate() {
    setBusy(true);
    setErr("");
    try {
      const r = await regenerateQuestion(q.question_id, runId);
      setCandidate(r.candidate);
      setRecheck(r.recheck_findings || []);
    } catch (e: any) {
      setErr(e.message || "Regenerate failed");
    } finally {
      setBusy(false);
    }
  }

  const worst = q.findings.filter((f) => f.verdict !== "PASS");

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <aside className="relative h-full w-full max-w-2xl overflow-y-auto bg-canvas shadow-lift">
        <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-black/[0.06] bg-white/80 px-6 py-4 backdrop-blur">
          <span className="font-mono text-sm text-black/40">{q.question_id}</span>
          {q.judgment && <VerdictChip v={q.judgment.verdict} />}
          <StatusPill status={q.status} />
          <button className="btn-ghost ml-auto" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="space-y-6 p-6">
          <section className="card">
            {editing ? (
              <div className="space-y-3">
                <div>
                  <div className="label mb-1">Stem</div>
                  <textarea
                    className="w-full rounded-lg border border-black/10 p-2 text-sm"
                    rows={3}
                    value={stem}
                    onChange={(e) => setStem(e.target.value)}
                  />
                </div>
                <div>
                  <div className="label mb-1">Correct keys (comma separated)</div>
                  <input
                    className="w-40 rounded-lg border border-black/10 p-2 text-sm"
                    value={keys}
                    onChange={(e) => setKeys(e.target.value)}
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    className="btn-primary"
                    disabled={busy}
                    onClick={() =>
                      act(async () => {
                        await editQuestion(q.question_id, runId, {
                          stem,
                          correct_keys: keys.split(",").map((s) => s.trim()).filter(Boolean),
                        });
                        setEditing(false);
                      })
                    }
                  >
                    Save &amp; re-review
                  </button>
                  <button className="btn-ghost" onClick={() => setEditing(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 text-xs text-black/40">
                  <span className="uppercase">{q.qtype}</span>
                  {q.difficulty && <span>· {q.difficulty}</span>}
                  {q.topic && <span>· {q.topic}</span>}
                </div>
                <p className="mt-2 text-[15px] font-medium leading-snug">{q.stem}</p>
                <OptionList q={q} />
                {q.explanation && (
                  <p className="mt-3 rounded-lg bg-black/[0.02] p-3 text-sm text-black/60">
                    <span className="label">Explanation</span>
                    <br />
                    {q.explanation}
                  </p>
                )}
              </>
            )}
          </section>

          {q.judgment && (
            <section className="card">
              <div className="flex items-center gap-2">
                <span className="label">Judge verdict</span>
                <VerdictChip v={q.judgment.verdict} />
              </div>
              <p className="mt-2 text-sm text-black/70">{q.judgment.reason}</p>
              {q.judgment.consolidated_fixes.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-sm text-black/60">
                  {q.judgment.consolidated_fixes.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <section>
            <div className="label mb-2">Agent findings ({worst.length} issue{worst.length === 1 ? "" : "s"})</div>
            <div className="space-y-2">
              {q.findings.length === 0 && (
                <p className="text-sm text-black/40">No findings recorded.</p>
              )}
              {[...q.findings]
                .sort((a, b) => (a.verdict === "PASS" ? 1 : 0) - (b.verdict === "PASS" ? 1 : 0))
                .map((f, i) => (
                  <FindingItem key={i} f={f} />
                ))}
            </div>
          </section>

          {candidate && (
            <section className="card border-accent-200 bg-accent-50/40">
              <div className="label mb-2">Regenerated candidate (grounded in session content)</div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-lg bg-white p-3">
                  <div className="mb-1 text-xs font-semibold text-black/40">Original</div>
                  <p className="text-sm">{q.stem}</p>
                </div>
                <div className="rounded-lg bg-white p-3">
                  <div className="mb-1 text-xs font-semibold text-accent-700">Candidate</div>
                  <p className="text-sm">{candidate.stem}</p>
                  <ul className="mt-2 space-y-1 text-sm">
                    {(candidate.options || []).map((o: any) => (
                      <li key={o.key} className={candidate.correct_keys?.includes(o.key) ? "text-emerald-700" : ""}>
                        <b>{o.key}.</b> {o.text}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {recheck.map((f, i) => (
                  <span key={i} className="text-xs">
                    <FindingBadge v={f.verdict} /> {f.check_name}
                  </span>
                ))}
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  className="btn-primary"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await applyRegeneration(q.question_id, runId, candidate);
                      setCandidate(null);
                    })
                  }
                >
                  Apply replacement
                </button>
                <button className="btn-ghost" onClick={() => setCandidate(null)}>
                  Discard
                </button>
              </div>
            </section>
          )}

          {err && <p className="text-sm text-rose-600">{err}</p>}

          <section className="sticky bottom-0 flex flex-wrap gap-2 border-t border-black/[0.06] bg-canvas py-4">
            <button
              className="btn bg-emerald-600 text-white hover:bg-emerald-700"
              disabled={busy}
              onClick={() => act(() => questionAction("approve", q.question_id, runId))}
            >
              Approve
            </button>
            <button className="btn-ghost" disabled={busy} onClick={() => setEditing((v) => !v)}>
              Edit
            </button>
            <button className="btn-ghost" disabled={busy} onClick={doRegenerate}>
              Regenerate
            </button>
            <button
              className="btn bg-rose-600 text-white hover:bg-rose-700"
              disabled={busy}
              onClick={() => act(() => questionAction("delete", q.question_id, runId))}
            >
              Delete
            </button>
          </section>
        </div>
      </aside>
    </div>
  );
}
