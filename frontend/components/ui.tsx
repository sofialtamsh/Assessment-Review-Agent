"use client";

import type { JudgeVerdict, Verdict } from "@/lib/types";

export const VERDICT_STYLE: Record<JudgeVerdict, { chip: string; dot: string; label: string }> = {
  APPROVE: { chip: "bg-emerald-50 text-emerald-700", dot: "#10b981", label: "Approve" },
  REVISE: { chip: "bg-amber-50 text-amber-700", dot: "#f59e0b", label: "Revise" },
  DELETE: { chip: "bg-rose-50 text-rose-700", dot: "#f43f5e", label: "Delete" },
};

export function VerdictChip({ v }: { v: JudgeVerdict }) {
  const s = VERDICT_STYLE[v];
  return (
    <span className={`chip ${s.chip}`}>
      <span className="mr-1 h-1.5 w-1.5 rounded-full" style={{ background: s.dot }} />
      {s.label}
    </span>
  );
}

const FINDING_STYLE: Record<Verdict, string> = {
  PASS: "bg-emerald-50 text-emerald-600",
  WARN: "bg-amber-50 text-amber-700",
  FAIL: "bg-rose-50 text-rose-700",
};

export function FindingBadge({ v }: { v: Verdict }) {
  return <span className={`chip ${FINDING_STYLE[v]}`}>{v}</span>;
}

export function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    approved: "bg-emerald-50 text-emerald-700",
    deleted: "bg-rose-50 text-rose-700",
    pending: "bg-black/[0.04] text-black/50",
  };
  return <span className={`chip ${map[status] || map.pending}`}>{status}</span>;
}

export function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-black/40">{sub}</div>}
    </div>
  );
}

export const PHASE_LABELS: Record<string, string> = {
  phase1_precheck: "Phase 1 — Deterministic pre-checks",
  phase2_language: "Phase 2 — Language & Logic",
  phase3_ambiguity: "Phase 3 — Ambiguity & Overlap",
  phase4_scope: "Phase 4 — Scope & Source (RAG)",
  phase5_pedagogy: "Phase 5 — Pedagogy",
  phase6_judge: "Phase 6 — Judge / Aggregator",
  report: "Assembling report",
};
export const PHASE_ORDER = Object.keys(PHASE_LABELS);

export const PHASE_PRETTY: Record<string, string> = {
  phase1_precheck: "Pre-checks",
  phase2_language: "Language",
  phase3_ambiguity: "Ambiguity",
  phase4_scope: "Scope",
  phase5_pedagogy: "Pedagogy",
  phase6_judge: "Judge",
};
