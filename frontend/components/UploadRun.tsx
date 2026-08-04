"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  API_BASE,
  ApiError,
  checkHealth,
  createBatch,
  createEvaluation,
  createEvaluationUpload,
  createRun,
  inferRubric,
  ingestMastersheetLink,
  listUnits,
  prepareAndRun,
  streamUrl,
  uploadFile,
} from "@/lib/api";
import type { PriorReview } from "@/lib/api";
import type { UnitInfo } from "@/lib/types";
import CrossSetCheck from "./CrossSetCheck";
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
  const [masterUrl, setMasterUrl] = useState("");
  const [units, setUnits] = useState<UnitInfo[]>([]);
  const [unitId, setUnitId] = useState("");
  const [set, setSet] = useState("mcq_assignment");

  // multi-unit evaluation / batch
  const [mode, setMode] = useState<"single" | "eval" | "batch">("single");
  const [evalUnits, setEvalUnits] = useState<string[]>([]);
  const [evalTitle, setEvalTitle] = useState("");
  const [questionsUrl, setQuestionsUrl] = useState("");
  const [evalFile, setEvalFile] = useState<File | null>(null);
  // marking scheme / rubric for this evaluation (file and/or link and/or pasted text)
  const [rubricFile, setRubricFile] = useState<File | null>(null);
  const [rubricUrl, setRubricUrl] = useState("");
  const [rubricText, setRubricText] = useState("");
  const [showRubric, setShowRubric] = useState(false);
  // reverse-engineered structured criteria (learned from a reference set)
  const [rubricCriteria, setRubricCriteria] = useState<unknown[]>([]);
  const [inferBusy, setInferBusy] = useState(false);
  const [inferNote, setInferNote] = useState("");

  // manual (advanced) flow
  // already-reviewed guardrail banner (prior summary + "review again anyway")
  const [guard, setGuard] = useState<{ prior: PriorReview[]; retry: () => void } | null>(null);

  const [showManual, setShowManual] = useState(false);
  const [mQuestions, setMQuestions] = useState<File | null>(null);
  const [mContent, setMContent] = useState<File | null>(null);
  const [mSessionId, setMSessionId] = useState("");

  // backend connectivity — retry to wake a sleeping free-tier backend (cold start)
  const [health, setHealth] = useState<{ ok: boolean; detail: string } | null>(null);
  const [waking, setWaking] = useState(true);
  const pingHealth = useCallback(async (attempts = 8) => {
    setWaking(true);
    for (let i = 0; i < attempts; i++) {
      const h = await checkHealth();
      setHealth(h);
      if (h.ok) {
        setWaking(false);
        return;
      }
      await new Promise((r) => setTimeout(r, 4000)); // give the backend time to wake
    }
    setWaking(false);
  }, []);
  useEffect(() => {
    pingHealth();
  }, [pingHealth]);

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

  async function ingestMasterLink() {
    if (!masterUrl.trim()) {
      setMsg("Paste the mastersheet Google Sheet / .xlsx link first.");
      return;
    }
    setStep("uploading");
    setMsg("Exporting the sheet & reading its links…");
    try {
      const r = await ingestMastersheetLink(masterUrl.trim());
      await refreshUnits();
      setMsg(`Ingested ${r.ingested} units from the link. Pick one and review — content & questions load from the sheet.`);
      setStep("idle");
    } catch (e: any) {
      setStep("error");
      setMsg(e.message || "Could not fetch the mastersheet link");
    }
  }

  // Run a review start, catching the already-reviewed 409 so we can offer a
  // "review again anyway" banner instead of just erroring.
  async function runGuarded(
    start: (force: boolean) => Promise<{ run_id: string; warnings?: string[] }>,
    failMsg: string
  ) {
    setGuard(null);
    setStep("preparing");
    try {
      const r = await start(false);
      if (r.warnings?.length) setMsg(r.warnings.join(" · "));
      attachStream(r.run_id);
    } catch (e: any) {
      const detail = e instanceof ApiError ? e.body?.detail : null;
      if (e instanceof ApiError && e.status === 409 && detail?.already_reviewed) {
        setStep("idle");
        setMsg("");
        setGuard({
          prior: detail.prior || [],
          retry: async () => {
            setGuard(null);
            setStep("preparing");
            try {
              const r = await start(true);
              if (r.warnings?.length) setMsg(r.warnings.join(" · "));
              attachStream(r.run_id);
            } catch (e2: any) {
              setStep("error");
              setMsg(e2.message || failMsg);
            }
          },
        });
      } else {
        setStep("error");
        setMsg(e.message || failMsg);
      }
    }
  }

  async function reviewFromUnit() {
    if (!unitId) {
      setMsg("Select a unit first.");
      return;
    }
    setMsg("Fetching slides & questions from the mastersheet links…");
    await runGuarded((force) => prepareAndRun(unitId, set, force), "Could not prepare this unit");
  }

  async function reviewEvaluation() {
    if (evalUnits.length < 1) {
      setMsg("Select the unit(s) this evaluation covers.");
      return;
    }
    setMsg(
      evalFile
        ? "Parsing the uploaded evaluation & fetching the selected units' content…"
        : "Fetching the evaluation & the selected units' content…"
    );
    const rubric = { text: rubricText, url: rubricUrl, file: rubricFile, criteria: rubricCriteria };
    // any uploaded file (exam and/or marking scheme) needs the multipart endpoint
    await runGuarded(
      (force) =>
        evalFile || rubricFile
          ? createEvaluationUpload(evalUnits, evalFile, evalTitle, questionsUrl, rubric, force)
          : createEvaluation(evalUnits, "mcq_assignment", evalTitle, questionsUrl, rubric, force),
      "Could not build the evaluation"
    );
  }

  async function reverseEngineer(file: File) {
    setInferBusy(true);
    setInferNote("");
    try {
      const r = await inferRubric({ file });
      setRubricText(r.rubric.text || "");
      setRubricCriteria((r.rubric.criteria as unknown[]) || []);
      setInferNote(
        `Learned ${r.n_criteria} criteria from ${r.n_questions} reference questions — edit below, then review.`
      );
      setShowRubric(true);
    } catch (e: any) {
      setInferNote(e.message || "Could not learn from that reference set.");
    } finally {
      setInferBusy(false);
    }
  }

  async function reviewBatch() {
    if (evalUnits.length < 2) {
      setMsg("Select at least two units to review as a batch.");
      return;
    }
    setStep("preparing");
    setMsg(`Starting ${evalUnits.length} separate reviews…`);
    try {
      const r = await createBatch(evalUnits, set);
      router.push(`/batch/${r.batch_id}`);
    } catch (e: any) {
      setStep("error");
      setMsg(e.message || "Could not start the batch");
    }
  }

  async function runManual() {
    setStep("uploading");
    setMsg("");
    try {
      // auto-generate a storage id if the reviewer didn't name one
      const sid = mSessionId.trim() || `manual_${Date.now().toString(36)}`;
      if (mQuestions) await uploadFile("/upload/questions", mQuestions, { session_id: sid });
      if (mContent) await uploadFile("/upload/content", mContent, { session_id: sid });
      const { run_id } = await createRun(sid, "mcq_assignment");
      attachStream(run_id);
    } catch (e: any) {
      setStep("error");
      setMsg(e.message || "Manual run failed");
    }
  }

  const selected = units.find((u) => u.unit_id === unitId);
  const busy = step === "uploading" || step === "preparing" || step === "running";

  // Which units are selectable in the current mode/source (same rule the list uses).
  const unitAvailable = (u: UnitInfo) =>
    mode === "eval"
      ? evalFile || questionsUrl
        ? !!u.has_content
        : !!u.has_mcq_assignment
      : set === "mcq_assignment"
      ? !!u.has_mcq_assignment
      : !!u.has_in_class_quiz;
  const availableUnitIds = units.filter(unitAvailable).map((u) => u.unit_id);
  const allAvailableSelected =
    availableUnitIds.length > 0 && availableUnitIds.every((id) => evalUnits.includes(id));

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Upload &amp; Run</h1>
        <p className="mt-1 text-black/50">
          Upload the mastersheet once — pick a unit and the pipeline fetches its slides and
          questions straight from the sheet&apos;s links. No repeated uploads.
        </p>
      </div>

      {waking && !health?.ok && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500 align-middle" />{" "}
          Waking the backend… (a free Render server sleeps after 15 min and takes ~30–60s to start)
        </div>
      )}
      {!waking && health && !health.ok && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <div className="flex items-center gap-3">
            <span className="font-semibold">⚠️ Can&apos;t reach the backend</span>
            <button className="btn-ghost ml-auto px-3 py-1 text-xs" onClick={() => pingHealth()}>
              Retry
            </button>
          </div>
          <div className="mt-1">{health.detail}</div>
          <div className="mt-2 text-rose-700/80">
            Calling <code className="rounded bg-white/60 px-1">{API_BASE}</code>. Open{" "}
            <code className="rounded bg-white/60 px-1">{API_BASE}/health</code> in a tab — if that shows
            JSON, click Retry (it was just asleep). Otherwise check the Render logs / start command
            (<code className="rounded bg-white/60 px-1">--host 0.0.0.0 --port $PORT</code>).
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

        <div className="flex items-center gap-3 text-xs text-black/35">
          <span className="h-px flex-1 bg-black/[0.06]" /> or paste a link{" "}
          <span className="h-px flex-1 bg-black/[0.06]" />
        </div>
        <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
          <div>
            <div className="label mb-1">Mastersheet Google Sheet / .xlsx link</div>
            <input
              className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm"
              placeholder="https://docs.google.com/spreadsheets/d/…  (shared 'Anyone with the link')"
              value={masterUrl}
              onChange={(e) => setMasterUrl(e.target.value)}
            />
            <div className="mt-1 text-xs text-black/35">
              Exported as .xlsx so cell links are kept. If links don&apos;t come through, download &amp; upload the .xlsx instead.
            </div>
          </div>
          <button className="btn-primary md:mb-1" onClick={ingestMasterLink} disabled={busy}>
            {step === "uploading" ? "Ingesting…" : "Ingest from link"}
          </button>
        </div>

        {units.length > 0 && (
          <>
            <div className="flex items-center gap-2 pt-2">
              <span className="grid h-6 w-6 place-items-center rounded-full bg-accent-600 text-xs text-white">2</span>
              <span className="font-medium">Pick a unit and what to review</span>
              <div className="ml-auto flex rounded-lg bg-black/[0.04] p-0.5 text-xs">
                <button
                  className={`rounded-md px-2.5 py-1 ${mode === "single" ? "bg-white shadow-sm" : "text-black/50"}`}
                  onClick={() => setMode("single")}
                >
                  Single unit
                </button>
                <button
                  className={`rounded-md px-2.5 py-1 ${mode === "batch" ? "bg-white shadow-sm" : "text-black/50"}`}
                  onClick={() => setMode("batch")}
                >
                  Batch (separate)
                </button>
                <button
                  className={`rounded-md px-2.5 py-1 ${mode === "eval" ? "bg-white shadow-sm" : "text-black/50"}`}
                  onClick={() => setMode("eval")}
                >
                  Evaluation (combined)
                </button>
              </div>
            </div>

            {mode === "single" && (
              <>
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
                <Avail ok={selected.has_tutorial} label="tutorial reference" />
                <Avail ok={selected.has_mcq_assignment} label="MCQ assignment" />
                <Avail ok={selected.has_in_class_quiz} label="in-class quiz" />
                {selected.subtopics.length > 0 && (
                  <span className="text-black/40">· {selected.subtopics.length} taught subtopics</span>
                )}
              </div>
            )}
              </>
            )}

            {(mode === "eval" || mode === "batch") && (
              <div className="space-y-3">
                <p className="text-sm text-black/50">
                  {mode === "eval"
                    ? "Review ONE evaluation against the units it covers. Its content is combined from the units you select, so duplicate, scope & coverage checks span the whole exam. Give the exam questions in any of three ways: upload the exam file, paste its Google Doc/Slides/Sheet link, or leave both blank to assemble the set from the units' own documents."
                    : "Review MULTIPLE units separately in one go — each gets its own review. You'll get a combined summary plus a link into each unit's own dashboard."}
                </p>
                <div className="flex flex-wrap items-end gap-3">
                  {mode === "eval" && (
                    <>
                      <input
                        className="w-52 rounded-xl border border-black/10 px-3 py-2 text-sm"
                        placeholder="Evaluation title"
                        value={evalTitle}
                        onChange={(e) => setEvalTitle(e.target.value)}
                      />
                      <div>
                        <div className="label mb-1">Upload exam file</div>
                        <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-black/10 bg-white px-3 py-2 text-sm hover:border-black/20">
                          <input
                            type="file"
                            className="hidden"
                            onChange={(e) => e.target.files?.[0] && setEvalFile(e.target.files[0])}
                          />
                          {evalFile ? (
                            <span className="chip bg-accent-50 text-accent-700">✓ {evalFile.name}</span>
                          ) : (
                            <span className="text-black/40">.zip / .md / .csv / .xlsx / .json</span>
                          )}
                        </label>
                      </div>
                      {evalFile && (
                        <button
                          className="btn-ghost px-2 py-1 text-xs"
                          onClick={() => setEvalFile(null)}
                        >
                          Clear file
                        </button>
                      )}
                      <input
                        className="w-72 rounded-xl border border-black/10 px-3 py-2 text-sm disabled:opacity-40"
                        placeholder="…or paste exam Google Doc/Slides/Sheet link"
                        value={questionsUrl}
                        disabled={!!evalFile}
                        onChange={(e) => setQuestionsUrl(e.target.value)}
                      />
                    </>
                  )}
                  {mode === "eval" ? (
                    // an evaluation is always assembled from the MCQ assignment (no
                    // in-class variant), so this is fixed — not a choice.
                    <div className={evalFile || questionsUrl ? "opacity-40" : ""}>
                      <div className="label mb-1">…or assemble from</div>
                      <div className="rounded-xl border border-black/10 bg-black/[0.02] px-3 py-2 text-sm text-black/60">
                        each unit&apos;s MCQ assignment
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="label mb-1">Question source</div>
                      <select
                        className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm"
                        value={set}
                        onChange={(e) => setSet(e.target.value)}
                      >
                        <option value="mcq_assignment">each unit&apos;s MCQ assignment</option>
                        <option value="in_class_quiz">each unit&apos;s in-class quiz</option>
                      </select>
                    </div>
                  )}
                  <button
                    className="btn-primary ml-auto"
                    onClick={mode === "eval" ? reviewEvaluation : reviewBatch}
                    disabled={busy || evalUnits.length < (mode === "eval" ? 1 : 2)}
                  >
                    {step === "preparing"
                      ? mode === "eval" ? "Building…" : "Starting…"
                      : step === "running"
                      ? "Reviewing…"
                      : mode === "eval"
                      ? "Fetch & review evaluation"
                      : `Review all separately (${evalUnits.length})`}
                  </button>
                </div>
                {mode === "eval" && (
                  <div className="rounded-xl border border-black/[0.06] bg-black/[0.015] p-3">
                    <button
                      type="button"
                      className="flex w-full items-center justify-between text-sm font-medium text-black/70"
                      onClick={() => setShowRubric((v) => !v)}
                    >
                      <span>
                        Marking scheme / criteria{" "}
                        <span className="font-normal text-black/40">(optional)</span>
                        {(rubricFile || rubricUrl || rubricText || rubricCriteria.length > 0) && (
                          <span className="ml-2 chip bg-accent-50 text-accent-700">attached</span>
                        )}
                      </span>
                      <span className="text-black/40">{showRubric ? "−" : "+"}</span>
                    </button>
                    {showRubric && (
                      <div className="mt-3 space-y-3">
                        <p className="text-xs text-black/45">
                          Tell the reviewers how to judge THIS set: a rubric document (criteria the
                          agents must follow) and/or a structured criteria sheet (.csv/.xlsx with
                          columns like criterion / metric / comparator / target / gate) that also
                          drives pass/fail compliance checks. Provide a file, a link, or paste text.
                        </p>

                        {/* reverse-engineer a scheme from a reference (gold) set */}
                        <div className="rounded-lg border border-dashed border-accent-300 bg-accent-50/40 p-2.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs font-medium text-accent-800">
                              ✨ Reverse-engineer from a reference set
                            </span>
                            <label className="cursor-pointer rounded-lg border border-accent-300 bg-white px-2.5 py-1 text-xs hover:border-accent-400">
                              {inferBusy ? "Learning…" : "Upload good/approved questions"}
                              <input
                                type="file"
                                className="hidden"
                                disabled={inferBusy}
                                onChange={(e) =>
                                  e.target.files?.[0] && reverseEngineer(e.target.files[0])
                                }
                              />
                            </label>
                            {rubricCriteria.length > 0 && (
                              <span className="chip bg-accent-100 text-accent-800">
                                {rubricCriteria.length} learned criteria
                              </span>
                            )}
                          </div>
                          {inferNote && (
                            <p className="mt-1.5 text-xs text-accent-800/80">{inferNote}</p>
                          )}
                          <p className="mt-1 text-[11px] text-black/40">
                            Analyzes a sample set (.xlsx/.csv/.md/.zip) and fills the criteria +
                            guidance below — edit anything before you review.
                          </p>
                        </div>

                        <div className="flex flex-wrap items-end gap-3">
                          <div>
                            <div className="label mb-1">Upload marking scheme</div>
                            <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-black/10 bg-white px-3 py-2 text-sm hover:border-black/20">
                              <input
                                type="file"
                                className="hidden"
                                onChange={(e) => e.target.files?.[0] && setRubricFile(e.target.files[0])}
                              />
                              {rubricFile ? (
                                <span className="chip bg-accent-50 text-accent-700">✓ {rubricFile.name}</span>
                              ) : (
                                <span className="text-black/40">.csv / .xlsx / .md / .txt / .pdf</span>
                              )}
                            </label>
                          </div>
                          {rubricFile && (
                            <button
                              className="btn-ghost px-2 py-1 text-xs"
                              onClick={() => setRubricFile(null)}
                            >
                              Clear
                            </button>
                          )}
                          <input
                            className="w-72 rounded-xl border border-black/10 px-3 py-2 text-sm"
                            placeholder="…or paste marking-scheme Doc/Sheet link"
                            value={rubricUrl}
                            onChange={(e) => setRubricUrl(e.target.value)}
                          />
                        </div>
                        <textarea
                          className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm"
                          rows={3}
                          placeholder="…or paste the criteria directly (e.g. 'Every question maps to a CO; ≥30% higher-order; no verbatim lifts; easy ≤50%')"
                          value={rubricText}
                          onChange={(e) => setRubricText(e.target.value)}
                        />
                      </div>
                    )}
                  </div>
                )}
                <div className="flex items-center justify-between px-1">
                  <button
                    type="button"
                    className="text-xs font-medium text-accent-700 hover:underline disabled:opacity-40 disabled:no-underline"
                    disabled={availableUnitIds.length === 0}
                    onClick={() =>
                      setEvalUnits(allAvailableSelected ? [] : availableUnitIds)
                    }
                  >
                    {allAvailableSelected
                      ? "Clear all"
                      : `Select all available (${availableUnitIds.length})`}
                  </button>
                  {evalUnits.length > 0 && !allAvailableSelected && (
                    <button
                      type="button"
                      className="text-xs text-black/40 hover:text-black/70"
                      onClick={() => setEvalUnits([])}
                    >
                      Clear
                    </button>
                  )}
                </div>
                <div className="max-h-64 overflow-y-auto rounded-xl border border-black/[0.06] p-2">
                  {units.map((u) => {
                    const checked = evalUnits.includes(u.unit_id);
                    const avail = unitAvailable(u);
                    return (
                      <label
                        key={u.unit_id}
                        className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm ${
                          avail ? "hover:bg-accent-50/60 cursor-pointer" : "opacity-40"
                        }`}
                      >
                        <input
                          type="checkbox"
                          disabled={!avail}
                          checked={checked}
                          onChange={(e) =>
                            setEvalUnits(
                              e.target.checked
                                ? [...evalUnits, u.unit_id]
                                : evalUnits.filter((x) => x !== u.unit_id)
                            )
                          }
                        />
                        <span className="flex-1">{u.unit}</span>
                        <span className="text-xs text-black/35">{u.module}</span>
                      </label>
                    );
                  })}
                </div>
                <div className="text-xs text-black/40">
                  {evalUnits.length} unit{evalUnits.length === 1 ? "" : "s"} selected (need at least{" "}
                  {mode === "eval" ? 1 : 2}).
                </div>
                {mode === "eval" && <CrossSetCheck />}
              </div>
            )}
          </>
        )}

        {guard && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">
            <div className="font-medium text-amber-900">⚠ Already reviewed</div>
            <div className="mt-2 space-y-2">
              {guard.prior.map((p) => (
                <div
                  key={p.run_id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 text-amber-900/90"
                >
                  <span className="font-medium">{p.title}</span>
                  <span className="text-amber-800/70">
                    reviewed by <b>{p.reviewer}</b> on {p.created_at.slice(0, 10)}
                  </span>
                  <span className="tabular-nums text-xs text-amber-800/70">
                    {p.verdict_counts?.APPROVE || 0} approve · {p.verdict_counts?.REVISE || 0} revise
                    · {p.verdict_counts?.DELETE || 0} delete
                  </span>
                  <a
                    className="text-accent-700 underline"
                    href={`/dashboard/${p.run_id}`}
                  >
                    Open previous review
                  </a>
                </div>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <button className="btn-primary" onClick={() => guard.retry()}>
                Review again anyway
              </button>
              <button className="btn-ghost" onClick={() => setGuard(null)}>
                Cancel
              </button>
            </div>
          </div>
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
              For a one-off review from your own files (a CSV/JSON/.md question set and a
              .pptx/.pdf/.md content file). The name below is just a label to group them —
              leave it blank and one is generated for you.
            </p>
            <input
              className="w-64 rounded-xl border border-black/10 px-3 py-2 text-sm"
              placeholder="Name for this review (optional)"
              value={mSessionId}
              onChange={(e) => setMSessionId(e.target.value)}
            />
            <div className="grid gap-4 md:grid-cols-2">
              <DropZone label="Question set" hint="CSV / XLSX / JSON / .md (MCQ doc)" file={mQuestions} onFile={setMQuestions} />
              <DropZone label="Session content" hint=".pptx / .pdf / .md" file={mContent} onFile={setMContent} />
            </div>
            <button className="btn-primary" onClick={runManual} disabled={busy || (!mQuestions && !mContent)}>
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
