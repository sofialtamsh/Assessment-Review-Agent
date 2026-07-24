"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  API_BASE,
  checkHealth,
  createRun,
  listUnits,
  prepareAndRun,
  streamUrl,
  uploadFile,
} from "@/lib/api";
import type { UnitInfo } from "@/lib/types";
import { PHASE_LABELS, PHASE_ORDER } from "./ui";

type Step = "idle" | "uploading" | "preparing" | "running" | "done" | "error";

function DropZone({
  label,
  hint,
  file,
  onFile,
}: {
  label: string;
  hint: string;
  file: File | null;
  onFile: (f: File) => void;
}) {
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (e.dataTransfer.files?.[0]) onFile(e.dataTransfer.files[0]);
      }}
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer rounded-2xl border-2 border-dashed p-5 transition-colors ${
        over ? "border-accent-500 bg-accent-50" : "border-black/10 hover:border-black/20 bg-white"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
      />
      <div className="text-sm font-medium">{label}</div>
      <div className="mt-0.5 text-xs text-black/40">{hint}</div>
      <div className="mt-2 text-sm">
        {file ? (
          <span className="chip bg-accent-50 text-accent-700">✓ {file.name}</span>
        ) : (
          <span className="text-black/35">Drop file or click to browse</span>
        )}
      </div>
    </div>
  );
}

export default function UploadRun() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("idle");
  const [msg, setMsg] = useState("");
  const [completed, setCompleted] = useState<string[]>([]);
  const [current, setCurrent] = useState("");

  // mastersheet-driven flow
  const [master, setMaster] = useState<File | null>(null);
  const [units, setUnits] = useState<UnitInfo[]>([]);
  const [unitId, setUnitId] = useState("");
  const [set, setSet] = useState("mcq_assignment");

  // manual (advanced) flow
  const [showManual, setShowManual] = useState(false);
  const [mQuestions, setMQuestions] = useState<File | null>(null);
  const [mContent, setMContent] = useState<File | null>(null);
  const [mSessionId, setMSessionId] = useState("");

  // backend connectivity
  const [health, setHealth] = useState<{ ok: boolean; detail: string } | null>(null);
  useEffect(() => {
    checkHealth().then(setHealth);
  }, []);

  async function refreshUnits() {
    try {
      const r = await listUnits();
      setUnits(r.units);
      if (!unitId && r.units[0]) setUnitId(r.units[0].unit_id);
    } catch {
      /* backend maybe not reachable yet */
    }
  }

  useEffect(() => {
    refreshUnits();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function attachStream(runId: string) {
    setStep("running");
    setCompleted([]);
    setCurrent(PHASE_ORDER[0]);
    const es = new EventSource(streamUrl(runId));
    es.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.type === "phase") {
        setCompleted(data.completed || []);
        setCurrent(data.phase);
      } else if (data.type === "done") {
        es.close();
        setStep("done");
        router.push(`/dashboard/${runId}`);
      } else if (data.type === "error") {
        es.close();
        setStep("error");
        setMsg(data.message || "Run failed");
      }
    };
    es.onerror = () => {
      es.close();
      router.push(`/dashboard/${runId}`);
    };
  }

  async function ingestMaster() {
    if (!master) {
      setMsg("Choose the mastersheet (.xlsx) first.");
      return;
    }
    setStep("uploading");
    setMsg("");
    try {
      const r = await uploadFile("/upload/mastersheet", master);
      if (r.mode === "units") {
        await refreshUnits();
        setMsg(`Ingested ${r.ingested} units. Pick one and review — content & questions load from the sheet.`);
      } else {
        setMsg(`Ingested ${r.ingested} sessions (CSV has no links — use manual upload, or upload the .xlsx to auto-source content/questions).`);
      }
      setStep("idle");
    } catch (e: any) {
      setStep("error");
      setMsg(e.message || "Upload failed");
    }
  }

  async function reviewFromUnit() {
    if (!unitId) {
      setMsg("Select a unit first.");
      return;
    }
    setStep("preparing");
    setMsg("Fetching slides & questions from the mastersheet links…");
    try {
      const r = await prepareAndRun(unitId, set);
      if (r.warnings?.length) setMsg(r.warnings.join(" · "));
      attachStream(r.run_id);
    } catch (e: any) {
      setStep("error");
      setMsg(e.message || "Could not prepare this unit");
    }
  }

  async function runManual() {
    setStep("uploading");
    setMsg("");
    try {
      if (mQuestions) await uploadFile("/upload/questions", mQuestions, { session_id: mSessionId });
      if (mContent) {
        if (!mSessionId) throw new Error("Enter the session id for the content.");
        await uploadFile("/upload/content", mContent, { session_id: mSessionId });
      }
      const { run_id } = await createRun(mSessionId, "mcq_assignment");
      attachStream(run_id);
    } catch (e: any) {
      setStep("error");
      setMsg(e.message || "Manual run failed");
    }
  }

  const selected = units.find((u) => u.unit_id === unitId);
  const busy = step === "uploading" || step === "preparing" || step === "running";

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Upload &amp; Run</h1>
        <p className="mt-1 text-black/50">
          Upload the mastersheet once — pick a unit and the pipeline fetches its slides and
          questions straight from the sheet&apos;s links. No repeated uploads.
        </p>
      </div>

      {health && !health.ok && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <div className="font-semibold">⚠️ Can&apos;t reach the backend</div>
          <div className="mt-1">{health.detail}</div>
          <div className="mt-2 text-rose-700/80">
            The frontend is calling <code className="rounded bg-white/60 px-1">{API_BASE}</code>.
            Start the backend (<code className="rounded bg-white/60 px-1">uvicorn app.main:app --port 8000</code>)
            or set <code className="rounded bg-white/60 px-1">NEXT_PUBLIC_API_BASE_URL</code> to your
            deployed API URL and restart <code className="rounded bg-white/60 px-1">npm run dev</code>.
          </div>
        </div>
      )}
      {health?.ok && (
        <div className="text-xs text-emerald-600">● Connected to backend ({API_BASE} · {health.detail})</div>
      )}

      {/* ---- primary: mastersheet-driven ---- */}
      <section className="card space-y-5">
        <div className="flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-accent-600 text-xs text-white">1</span>
          <span className="font-medium">Upload the mastersheet (.xlsx)</span>
        </div>
        <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
          <DropZone
            label="Mastersheet (.xlsx)"
            hint="Excel keeps the slide/doc links — CSV loses them. Course → Unit → What to Cover → PPT."
            file={master}
            onFile={setMaster}
          />
          <button className="btn-primary md:mb-1" onClick={ingestMaster} disabled={busy}>
            {step === "uploading" ? "Ingesting…" : "Ingest mastersheet"}
          </button>
        </div>

        {units.length > 0 && (
          <>
            <div className="flex items-center gap-2 pt-2">
              <span className="grid h-6 w-6 place-items-center rounded-full bg-accent-600 text-xs text-white">2</span>
              <span className="font-medium">Pick a unit and what to review</span>
            </div>
            <div className="flex flex-wrap items-end gap-4">
              <div className="min-w-[16rem]">
                <div className="label mb-1">Unit ({units.length})</div>
                <select
                  className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-sm"
                  value={unitId}
                  onChange={(e) => setUnitId(e.target.value)}
                >
                  {units.map((u) => (
                    <option key={u.unit_id} value={u.unit_id}>
                      {u.unit} {u.module ? `· ${u.module}` : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="label mb-1">Review set</div>
                <select
                  className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm"
                  value={set}
                  onChange={(e) => setSet(e.target.value)}
                >
                  <option value="mcq_assignment" disabled={!selected?.has_mcq_assignment}>
                    MCQ assignment{selected && !selected.has_mcq_assignment ? " (none)" : ""}
                  </option>
                  <option value="in_class_quiz" disabled={!selected?.has_in_class_quiz}>
                    In-class quiz{selected && !selected.has_in_class_quiz ? " (none)" : ""}
                  </option>
                </select>
              </div>
              <button
                className="btn-primary ml-auto"
                onClick={reviewFromUnit}
                disabled={busy || !selected}
              >
                {step === "preparing" ? "Fetching…" : step === "running" ? "Reviewing…" : "Fetch & Review"}
              </button>
            </div>

            {selected && (
              <div className="flex flex-wrap gap-2 text-xs">
                <Avail ok={selected.has_content} label="slides content" />
                <Avail ok={selected.has_mcq_assignment} label="MCQ assignment" />
                <Avail ok={selected.has_in_class_quiz} label="in-class quiz" />
                {selected.subtopics.length > 0 && (
                  <span className="text-black/40">· {selected.subtopics.length} taught subtopics</span>
                )}
              </div>
            )}
          </>
        )}

        {msg && <div className="text-sm text-black/55">{msg}</div>}

        {(step === "running" || step === "done") && (
          <div className="space-y-2 pt-2">
            {PHASE_ORDER.map((p) => {
              const done = completed.includes(p);
              const active = current === p && !done;
              return (
                <div key={p} className="flex items-center gap-3 animate-fadein">
                  <span
                    className={`grid h-6 w-6 place-items-center rounded-full text-xs ${
                      done ? "bg-emerald-500 text-white" : active ? "bg-accent-600 text-white" : "bg-black/[0.06] text-black/40"
                    }`}
                  >
                    {done ? "✓" : active ? "…" : ""}
                  </span>
                  <span className={done || active ? "text-ink" : "text-black/40"}>{PHASE_LABELS[p]}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ---- advanced: manual upload ---- */}
      <div>
        <button
          className="text-sm text-black/45 hover:text-black/70"
          onClick={() => setShowManual((v) => !v)}
        >
          {showManual ? "− Hide" : "+ Advanced"}: upload files manually instead
        </button>
        {showManual && (
          <section className="card mt-3 space-y-4">
            <p className="text-sm text-black/50">
              For a one-off review from your own files (a CSV/JSON question set and a
              .pptx/.pdf/.md content file). Enter the session id you want them stored under.
            </p>
            <input
              className="w-64 rounded-xl border border-black/10 px-3 py-2 text-sm"
              placeholder="session id (e.g. ds_07)"
              value={mSessionId}
              onChange={(e) => setMSessionId(e.target.value)}
            />
            <div className="grid gap-4 md:grid-cols-2">
              <DropZone label="Question set" hint="CSV / XLSX / JSON" file={mQuestions} onFile={setMQuestions} />
              <DropZone label="Session content" hint=".pptx / .pdf / .md" file={mContent} onFile={setMContent} />
            </div>
            <button className="btn-primary" onClick={runManual} disabled={busy || !mSessionId}>
              Upload &amp; run
            </button>
          </section>
        )}
      </div>
    </div>
  );
}

function Avail({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`chip ${ok ? "bg-emerald-50 text-emerald-700" : "bg-black/[0.04] text-black/35"}`}>
      {ok ? "✓" : "—"} {label}
    </span>
  );
}
