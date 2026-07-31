"use client";

import { useEffect, useState } from "react";
import { getInsights } from "@/lib/api";
import type { Insights } from "@/lib/api";
import { BarChart } from "./charts";
import { Stat } from "./ui";

// friendly names for the agent check identifiers
const CHECK_LABELS: Record<string, string> = {
  option_ambiguity: "Ambiguous options",
  out_of_scope: "Out of scope",
  verbatim_lift: "Verbatim lift",
  semantic_duplicate: "Duplicate (semantic)",
  exact_duplicate: "Duplicate (exact)",
  near_duplicate: "Duplicate (near)",
  cross_set_overlap: "Cross-set overlap",
  bloom_classified: "Bloom level",
  over_tested: "Over-tested topic",
  bad_key: "Wrong answer key",
  grammar: "Grammar / clarity",
};

function pretty(check: string): string {
  return CHECK_LABELS[check] || check.replace(/_/g, " ");
}

export default function InsightsPanel() {
  const [d, setD] = useState<Insights | null>(null);

  useEffect(() => {
    getInsights()
      .then(setD)
      .catch(() => {});
  }, []);

  if (!d || d.total_reviews === 0) return null;

  const issues = (d.top_issues || []).slice(0, 7).map((i) => ({
    label: pretty(i.check),
    value: i.count,
  }));

  return (
    <section className="card">
      <div className="flex items-center gap-2">
        <span className="label">Team insights</span>
        <span className="text-xs text-black/40">· quality across all reviews</span>
      </div>

      <div className="mt-3 grid gap-4 md:grid-cols-3">
        <Stat label="Reviews" value={d.total_reviews} sub={`${d.total_questions} questions`} />
        <Stat
          label="Avg approval"
          value={`${Math.round(d.avg_approval_pct)}%`}
          sub="across all reviews"
        />
        <Stat label="Reviewers" value={d.by_reviewer?.length || 0} sub="contributing" />
      </div>

      {issues.length > 0 && (
        <div className="mt-5">
          <div className="label mb-2">Most common issues the agents caught</div>
          <BarChart data={issues} />
        </div>
      )}

      {d.by_reviewer?.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2 text-xs text-black/55">
          {d.by_reviewer.map((r) => (
            <span key={r.reviewer} className="chip bg-black/[0.04]">
              {r.reviewer} · {r.reviews}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
