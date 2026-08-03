"use client";

import { useState } from "react";
import { crossCheckSets } from "@/lib/api";
import type { CrossCheckResult } from "@/lib/api";

export default function CrossSetCheck() {
  const [files, setFiles] = useState<File[]>([]);
  const [res, setRes] = useState<CrossCheckResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);

  async function run() {
    if (files.length < 2) {
      setErr("Add at least 2 set files to compare.");
      return;
    }
    setBusy(true);
    setErr("");
    setRes(null);
    try {
      setRes(await crossCheckSets(files));
    } catch (e: any) {
      setErr(e.message || "Cross-set check failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <button
        type="button"
        className="flex w-full items-center justify-between text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span>
          <span className="label">Cross-set duplicate check</span>
          <span className="ml-2 text-xs text-black/40">
            · make sure Set 1 / 2 / 3 don&apos;t repeat questions
          </span>
        </span>
        <span className="text-black/40">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-black/10 bg-white px-3 py-2 text-sm hover:border-black/20">
              <input
                type="file"
                multiple
                className="hidden"
                onChange={(e) => setFiles(Array.from(e.target.files || []))}
              />
              <span className="text-black/50">
                {files.length ? `${files.length} set files selected` : "Select 2+ set files (.xlsx / .csv / .docx / .pdf)"}
              </span>
            </label>
            <button className="btn-primary" onClick={run} disabled={busy || files.length < 2}>
              {busy ? "Checking…" : "Check for repeats"}
            </button>
          </div>

          {err && <div className="text-sm text-rose-600">{err}</div>}

          {res && (
            <div className="space-y-2 text-sm">
              <div className="flex flex-wrap gap-2">
                {res.sets.map((s) => (
                  <span key={s.name} className="chip bg-black/[0.04]">
                    {s.name} · {s.questions} Qs
                  </span>
                ))}
              </div>
              {res.summary.pairs === 0 ? (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-emerald-800">
                  ✓ No repeated questions across the sets.
                </div>
              ) : (
                <>
                  <div className="rounded-xl border border-amber-200 bg-amber-50 p-2.5 text-amber-900">
                    ⚠ {res.summary.pairs} repeat{res.summary.pairs === 1 ? "" : "s"} found
                    ({res.summary.exact} exact, {res.summary.near} near-duplicate).
                  </div>
                  <div className="divide-y divide-black/[0.05]">
                    {res.duplicates.slice(0, 30).map((d, i) => (
                      <div key={i} className="py-2">
                        <div className="flex items-center gap-2 text-xs text-black/45">
                          <span className="chip bg-black/[0.05]">
                            {d.set_a} ↔ {d.set_b}
                          </span>
                          <span>{d.exact ? "exact" : `${d.similarity}% similar`}</span>
                        </div>
                        <div className="mt-1 text-black/70">{d.question_a}</div>
                        <div className="text-black/45">{d.question_b}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
