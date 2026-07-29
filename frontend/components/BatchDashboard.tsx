"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getBatch } from "@/lib/api";
import { Stat } from "./ui";

type Batch = Awaited<ReturnType<typeof getBatch>>;

export default function BatchDashboard({ batchId }: { batchId: string }) {
  const [data, setData] = useState<Batch | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await getBatch(batchId));
    } catch (e: any) {
      setErr(e.message || "Failed to load batch");
    }
  }, [batchId]);

  useEffect(() => {
    load();
    const t = setInterval(load, 2000); // live-refresh while runs complete
    return () => clearInterval(t);
  }, [load]);

  if (err) return <p className="text-rose-600">{err}</p>;
  if (!data) return <p className="text-black/40">Loading batch…</p>;

  const running = data.items.filter((i) => i.run_id && i.status !== "completed" && i.status !== "failed").length;
  const c = data.combined;
  const passRate = c.total ? Math.round((c.APPROVE / c.total) * 100) : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Batch review</h1>
          <p className="text-sm text-black/50">
            {data.items.length} units · {data.source_set}
            {running > 0 && <span className="ml-2 text-accent-600">· {running} still running…</span>}
          </p>
        </div>
        <Link href="/" className="btn-ghost ml-auto">New run</Link>
      </div>

      {/* combined summary across all units */}
      <section className="grid gap-4 md:grid-cols-4">
        <Stat label="Total questions" value={c.total} sub={`${data.items.length} units`} />
        <Stat label="Combined pass rate" value={`${passRate}%`} sub={`${c.APPROVE} approve`} />
        <Stat label="Needs revision" value={c.REVISE} />
        <Stat label="To delete" value={c.DELETE} />
      </section>

      {/* per-unit table */}
      <section className="card p-0 overflow-hidden">
        <div className="border-b border-black/[0.06] px-4 py-3">
          <span className="label">Per-unit results — open any to review its questions</span>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-black/40">
              <th className="px-4 py-2 font-medium">Unit</th>
              <th className="px-4 py-2 font-medium">Questions</th>
              <th className="px-4 py-2 font-medium">Approve</th>
              <th className="px-4 py-2 font-medium">Revise</th>
              <th className="px-4 py-2 font-medium">Delete</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((it) => {
              const vc = it.verdict_counts || {};
              return (
                <tr key={it.unit_id} className="border-t border-black/[0.04]">
                  <td className="px-4 py-2.5 font-medium">
                    {it.unit}
                    {it.warnings && it.warnings.length > 0 && (
                      <div className="mt-0.5 text-xs font-normal text-amber-700">
                        {it.warnings.map((w, i) => (
                          <div key={i} className="break-all">⚠ {w}</div>
                        ))}
                      </div>
                    )}
                  </td>
                  {it.error ? (
                    <td className="px-4 py-2.5 text-rose-600" colSpan={5}>
                      {it.error}
                    </td>
                  ) : (
                    <>
                      <td className="px-4 py-2.5 tabular-nums">{it.total_questions ?? it.questions ?? "—"}</td>
                      <td className="px-4 py-2.5 tabular-nums text-emerald-700">{vc.APPROVE || 0}</td>
                      <td className="px-4 py-2.5 tabular-nums text-amber-700">{vc.REVISE || 0}</td>
                      <td className="px-4 py-2.5 tabular-nums text-rose-700">{vc.DELETE || 0}</td>
                      <td className="px-4 py-2.5">
                        <span className={`chip ${it.status === "completed" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                          {it.status || "queued"}
                        </span>
                      </td>
                    </>
                  )}
                  <td className="px-4 py-2.5 text-right">
                    {it.run_id && (
                      <Link href={`/dashboard/${it.run_id}`} className="text-accent-600 hover:text-accent-700">
                        Open →
                      </Link>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
