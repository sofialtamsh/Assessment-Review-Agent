"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { bulkApprove, exportUrl, getReport, listInstructions, reportExportUrl } from "@/lib/api";
import type { Instruction, PhaseSummary, QuestionRow, ReportResponse } from "@/lib/types";
import { BarChart, Donut } from "./charts";
import FeedbackPanel from "./FeedbackPanel";
import QuestionDrawer from "./QuestionDrawer";
import { Stat, StatusPill, VerdictChip } from "./ui";

const BLOOM_COLORS: Record<string, string> = {
  Remember: "#c7d2fe",
  Understand: "#818cf8",
  Apply: "#6366f1",
  Analyze: "#4f46e5",
  Evaluate: "#4338ca",
  Create: "#312e81",
};

const FILTERS = ["ALL", "APPROVE", "REVISE", "DELETE"] as const;
type Filter = (typeof FILTERS)[number];

export default function Dashboard({ runId }: { runId: string }) {
  const [data, setData] = useState<ReportResponse | null>(null);
  const [filter, setFilter] = useState<Filter>("ALL");
  const [typeFilter, setTypeFilter] = useState<string>("ALL");
  const [open, setOpen] = useState<QuestionRow | null>(null);
  const [instr, setInstr] = useState<Instruction[]>([]);
  const [err, setErr] = useState("");

  const loadInstr = useCallback(async () => {
    try {
      const r = await listInstructions();
      setInstr(r.instructions);
    } catch {
      /* ignore */
    }
  }, []);
  useEffect(() => {
    loadInstr();
  }, [loadInstr]);

  const instrCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const it of instr) {
      const targets = it.phase === "all"
        ? ["phase2_language", "phase3_ambiguity", "phase4_scope", "phase5_pedagogy", "phase6_judge"]
        : [it.phase];
      for (const t of targets) m[t] = (m[t] || 0) + 1;
    }
    return m;
  }, [instr]);

  const load = useCallback(async () => {
    try {
      const r = await getReport(runId);
      setData(r);
      // keep drawer in sync after an action
      setOpen((prev) =>
        prev ? r.questions.find((q) => q.question_id === prev.question_id) || null : null
      );
    } catch (e: any) {
      setErr(e.message || "Failed to load report");
    }
  }, [runId]);

  useEffect(() => {
    load();
    const t = setInterval(() => {
      if (data && data.run.status !== "completed" && data.run.status !== "budget_stopped") load();
    }, 1500);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, data?.run.status]);

  const report = data?.report;
  const questions = data?.questions || [];

  const filtered = useMemo(
    () =>
      questions.filter(
        (q) =>
          (filter === "ALL" || q.judgment?.verdict === filter) &&
          (typeFilter === "ALL" || q.qtype === typeFilter)
      ),
    [questions, filter, typeFilter]
  );

  const pendingApprove = questions.filter(
    (q) => q.judgment?.verdict === "APPROVE" && q.status !== "approved" && q.status !== "deleted"
  );

  async function approveAll() {
    if (!pendingApprove.length) return;
    if (!confirm(`Approve all ${pendingApprove.length} questions the reviewer recommended APPROVE?`))
      return;
    await bulkApprove(runId, "approve_verdict");
    await load();
  }

  if (err) return <p className="text-rose-600">{err}</p>;
  if (!data) return <p className="text-black/40">Loading review…</p>;

  const bloom = Object.entries(report?.bloom_distribution || {}).map(([label, value]) => ({
    label,
    value,
    color: BLOOM_COLORS[label] || "#9aa",
  }));
  // always show A–D (plus any other keys present) so a missing key reads as 0, not absent
  const kb = report?.key_balance || {};
  const keyBalance = Array.from(new Set(["A", "B", "C", "D", ...Object.keys(kb)]))
    .sort()
    .map((label) => ({ label, value: kb[label] || 0 }));
  const dupCount = report?.duplicate_clusters.reduce((s, c) => s + c.question_ids.length, 0) || 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Review Dashboard</h1>
          <p className="text-sm text-black/50">
            Session <b>{data.run.session_id}</b> · {data.run.source_set} ·{" "}
            <span className="capitalize">{data.run.status.replace("_", " ")}</span>
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <Link href="/" className="btn-ghost">
            New run
          </Link>
          <a className="btn-ghost" href={reportExportUrl(runId)}>
            Review report
          </a>
          <a className="btn-primary" href={exportUrl(runId, "csv")}>
            Export approved CSV
          </a>
        </div>
      </div>

      {data.run.errors.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {data.run.errors.join(" · ")}
        </div>
      )}

      {/* summary cards */}
      <section className="grid gap-4 md:grid-cols-4">
        <Stat
          label="Pass rate"
          value={`${Math.round((report?.pass_rate || 0) * 100)}%`}
          sub={`${report?.verdict_counts?.APPROVE || 0}/${report?.total_questions || 0} approve`}
        />
        <Stat label="Duplicates" value={dupCount} sub={`${report?.duplicate_clusters.length || 0} clusters`} />
        <Stat label="Out of scope" value={report?.out_of_scope_ids.length || 0} sub={`${report?.verbatim_lift_ids.length || 0} verbatim lifts`} />
        <Stat
          label="Scenario ratio"
          value={`${Math.round((report?.scenario_vs_recall_ratio || 0) * 100)}%`}
          sub="higher-order vs recall"
        />
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="card">
          <div className="label mb-3">Bloom&apos;s taxonomy</div>
          {bloom.length ? <Donut data={bloom} /> : <p className="text-sm text-black/40">No data</p>}
        </div>
        <div className="card">
          <div className="label mb-3">Answer-key balance</div>
          {keyBalance.length ? (
            <BarChart data={keyBalance} />
          ) : (
            <p className="text-sm text-black/40">No data</p>
          )}
        </div>
      </section>

      <PhasePanel phases={data.phase_summary || []} instrCounts={instrCounts} />

      <CostPanel data={data} />

      {/* question table */}
      <section className="card p-0 overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-black/[0.06] px-4 py-3">
          <span className="label">Questions</span>
          <div className="ml-2 flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f}
                className={`chip ${filter === f ? "bg-accent-600 text-white" : "bg-black/[0.04] text-black/50"}`}
                onClick={() => setFilter(f)}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            {pendingApprove.length > 0 && (
              <button
                className="btn bg-emerald-600 text-white hover:bg-emerald-700 px-3 py-1.5 text-xs"
                onClick={approveAll}
                title="Approve every question the reviewer recommended APPROVE"
              >
                ✓ Approve all recommended ({pendingApprove.length})
              </button>
            )}
            <select
              className="rounded-lg border border-black/10 px-2 py-1 text-xs"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="ALL">All types</option>
              <option value="single">single</option>
              <option value="multi">multi</option>
              <option value="binary">binary</option>
            </select>
          </div>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-black/40">
              <th className="px-4 py-2 font-medium">ID</th>
              <th className="px-4 py-2 font-medium">Question</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Issues</th>
              <th className="px-4 py-2 font-medium">Verdict</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((q) => {
              const issues = q.findings.filter((f) => f.verdict !== "PASS").length;
              return (
                <tr
                  key={q.question_id}
                  onClick={() => setOpen(q)}
                  className="cursor-pointer border-t border-black/[0.04] hover:bg-accent-50/50"
                >
                  <td className="px-4 py-2.5 font-mono text-xs text-black/40">{q.question_id}</td>
                  <td className="px-4 py-2.5 max-w-md truncate">{q.stem}</td>
                  <td className="px-4 py-2.5 text-xs text-black/50">{q.qtype}</td>
                  <td className="px-4 py-2.5">
                    {issues > 0 ? (
                      <span className="chip bg-amber-50 text-amber-700">{issues}</span>
                    ) : (
                      <span className="text-black/30">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {q.judgment ? <VerdictChip v={q.judgment.verdict} /> : <span className="text-black/30">—</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusPill status={q.status} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <FeedbackPanel />

      {open && (
        <QuestionDrawer
          q={open}
          runId={runId}
          onClose={() => setOpen(null)}
          onChanged={load}
        />
      )}
    </div>
  );
}

function PhasePanel({
  phases,
  instrCounts,
}: {
  phases: PhaseSummary[];
  instrCounts: Record<string, number>;
}) {
  if (!phases.length) return null;
  return (
    <section className="card">
      <div className="label mb-3">Review stages — every phase &amp; its checks</div>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {phases.map((p) => {
          const pass = p.verdict_counts.PASS || 0;
          const warn = p.verdict_counts.WARN || 0;
          const fail = p.verdict_counts.FAIL || 0;
          const isJudge = p.phase === "phase6_judge";
          return (
            <div key={p.phase} className="rounded-xl border border-black/[0.06] p-3">
              <div className="flex items-center gap-2">
                <span
                  className={`grid h-5 w-5 place-items-center rounded-full text-[10px] ${
                    p.ran ? "bg-emerald-500 text-white" : "bg-black/[0.08] text-black/40"
                  }`}
                  title={p.ran ? "ran" : "did not run"}
                >
                  {p.ran ? "✓" : "–"}
                </span>
                <span className="text-sm font-medium leading-tight">{p.label}</span>
                {instrCounts[p.phase] > 0 && (
                  <span
                    className="chip bg-accent-50 text-accent-700"
                    title="Reviewer instructions applied to this agent"
                  >
                    ★ {instrCounts[p.phase]}
                  </span>
                )}
                <span className="ml-auto text-[10px] uppercase text-black/30">
                  {p.uses_llm ? "LLM" : "python"}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                {isJudge ? (
                  Object.entries(p.verdict_counts).map(([k, v]) => (
                    <span key={k} className="chip bg-black/[0.04] text-black/60">
                      {k} {v}
                    </span>
                  ))
                ) : (
                  <>
                    <span className="chip bg-emerald-50 text-emerald-600">PASS {pass}</span>
                    {warn > 0 && <span className="chip bg-amber-50 text-amber-700">WARN {warn}</span>}
                    {fail > 0 && <span className="chip bg-rose-50 text-rose-700">FAIL {fail}</span>}
                  </>
                )}
              </div>
              <div className="mt-2 text-[11px] leading-relaxed text-black/45">
                {p.checks.length ? p.checks.join(", ") : "no checks fired"}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

const COST_LABELS: Record<string, string> = {
  phase2_language: "Phase 2 · Language",
  phase3_ambiguity: "Phase 3 · Ambiguity",
  phase4_scope: "Phase 4 · Scope",
  phase5_pedagogy: "Phase 5 · Pedagogy",
  phase6_judge: "Phase 6 · Judge",
  phase7_fixer: "Regeneration (fixer)",
  regeneration: "Regeneration + re-review",
  edit_recheck: "Edit re-review",
};
const HUMAN_KEYS = new Set(["regeneration", "edit_recheck", "phase7_fixer"]);

function CostPanel({ data }: { data: ReportResponse }) {
  const cost = data.run.cost;
  const budget = data.run.budget;
  if (!cost) return null;
  const entries = Object.values(cost.per_phase);
  const review = entries.filter((p) => !HUMAN_KEYS.has(p.phase));
  const human = entries.filter((p) => HUMAN_KEYS.has(p.phase));
  const reviewUsd = review.reduce((s, p) => s + p.usd, 0);
  const humanUsd = human.reduce((s, p) => s + p.usd, 0);

  const Row = ({ label, tokens, usd }: { label: string; tokens: number; usd: number }) => (
    <div className="flex items-center justify-between py-1 text-sm">
      <span className="text-black/55">{label}</span>
      <span className="tabular-nums text-black/70">
        {tokens.toLocaleString()}t · <b>${usd.toFixed(4)}</b>
      </span>
    </div>
  );

  return (
    <section className="card">
      {/* prominent total */}
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <div className="label">Total cost this run</div>
          <div className="mt-1 text-3xl font-semibold tracking-tight tabular-nums">
            ${cost.total_usd.toFixed(4)}
          </div>
          <div className="text-xs text-black/40">
            {cost.total_tokens.toLocaleString()} tokens
          </div>
        </div>
        <div className="ml-auto grid grid-cols-2 gap-x-6 text-right text-sm">
          <div>
            <div className="label">Review</div>
            <div className="tabular-nums font-medium">${reviewUsd.toFixed(4)}</div>
          </div>
          <div>
            <div className="label">Human actions</div>
            <div className="tabular-nums font-medium">${humanUsd.toFixed(4)}</div>
          </div>
        </div>
      </div>

      {budget && budget.limit > 0 && (
        <div className="mt-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-black/[0.06]">
            <div
              className="h-full rounded-full bg-accent-500"
              style={{ width: `${Math.min(100, (budget.spent / budget.limit) * 100)}%` }}
            />
          </div>
          <div className="mt-1 text-xs text-black/40">
            {budget.spent.toLocaleString()} / {budget.limit.toLocaleString()} token budget
          </div>
        </div>
      )}

      <div className="mt-4 grid gap-x-8 md:grid-cols-2">
        <div>
          <div className="label mb-1">Per phase (review)</div>
          {review.map((p) => (
            <Row
              key={p.phase}
              label={COST_LABELS[p.phase] || p.phase}
              tokens={p.tokens_in + p.tokens_out}
              usd={p.usd}
            />
          ))}
        </div>
        {human.length > 0 && (
          <div>
            <div className="label mb-1">Human actions (edits & regenerations)</div>
            {human.map((p) => (
              <Row
                key={p.phase}
                label={`${COST_LABELS[p.phase] || p.phase} ×${p.calls}`}
                tokens={p.tokens_in + p.tokens_out}
                usd={p.usd}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
