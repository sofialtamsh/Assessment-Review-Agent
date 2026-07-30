"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getActivity } from "@/lib/api";
import type { ActivityItem } from "@/lib/api";

const STATUS_STYLE: Record<string, string> = {
  running: "bg-accent-50 text-accent-700",
  queued: "bg-black/[0.06] text-black/50",
  completed: "bg-emerald-50 text-emerald-700",
  budget_stopped: "bg-amber-50 text-amber-700",
  failed: "bg-rose-50 text-rose-700",
};

const SET_LABEL: Record<string, string> = {
  mcq_assignment: "MCQ assignment",
  in_class_quiz: "in-class quiz",
  examination: "evaluation",
};

function timeAgo(iso: string): string {
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} hr ago`;
  return `${Math.floor(secs / 86400)} d ago`;
}

export default function ActivityPanel() {
  const [items, setItems] = useState<ActivityItem[]>([]);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await getActivity(15);
        if (alive) setItems(r.activity);
      } catch {
        /* backend maybe waking */
      }
    };
    load();
    const t = setInterval(load, 5000); // poll — see who's reviewing what
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (!items.length) return null;

  return (
    <section className="card">
      <div className="flex items-center gap-2">
        <span className="label">Team activity</span>
        <span className="text-xs text-black/40">· who&apos;s reviewing what</span>
      </div>
      <div className="mt-3 divide-y divide-black/[0.05]">
        {items.map((a) => {
          const vc = a.verdict_counts || {};
          return (
            <div key={a.run_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
              <span className={`chip ${STATUS_STYLE[a.status] || STATUS_STYLE.queued}`}>
                {a.status === "running" ? "▶ running" : a.status.replace("_", " ")}
              </span>
              <b className="text-ink">{a.reviewer}</b>
              <span className="text-black/40">·</span>
              <span className="text-black/70">{a.title}</span>
              <span className="text-xs text-black/40">({SET_LABEL[a.source_set] || a.source_set})</span>
              {a.status !== "running" && a.status !== "queued" && (
                <span className="tabular-nums text-xs text-black/45">
                  {vc.APPROVE || 0}✓ / {vc.REVISE || 0}~ / {vc.DELETE || 0}✗
                </span>
              )}
              <span className="ml-auto text-xs text-black/35">{timeAgo(a.updated_at)}</span>
              <Link href={`/dashboard/${a.run_id}`} className="text-xs text-accent-700 underline">
                open
              </Link>
            </div>
          );
        })}
      </div>
    </section>
  );
}
