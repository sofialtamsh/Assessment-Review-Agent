"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  createRun,
  fetchSessionContent,
  listSessions,
  streamUrl,
  uploadFile,
} from "@/lib/api";
import type { SessionInfo } from "@/lib/types";
import { PHASE_LABELS, PHASE_ORDER } from "./ui";

type Step = "idle" | "uploading" | "running" | "done" | "error";

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
  const [master, setMaster] = useState<File | null>(null);
  const [questions, setQuestions] = useState<File | null>(null);
  const [quiz, setQuiz] = useState<File | null>(null);
  const [content, setContent] = useState<File | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [sourceSet, setSourceSet] = useState("mcq_assignment");
  const [step, setStep] = useState<Step>("idle");
  const [msg, setMsg] = useState("");
  const [completed, setCompleted] = useState<string[]>([]);
  const [current, setCurrent] = useState("");

  async function refreshSessions() {
    try {
      const r = await listSessions();
      setSessions(r.sessions);
      if (!sessionId && r.sessions[0]) setSessionId(r.sessions[0].session_id);
    } catch {
      /* backend maybe not up yet */
    }
  }

  useEffect(() => {
    refreshSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function doUpload() {
    setStep("uploading");
    setMsg("");
    try {
      if (master) await uploadFile("/upload/mastersheet", master);
      if (questions) await uploadFile("/upload/questions", questions);
      if (quiz) await uploadFile("/upload/questions", quiz);
      let sid = sessionId;
      if (content) {
        if (!sid) throw new Error("Pick or ingest a session before uploading content.");
        await uploadFile("/upload/content", content, { session_id: sid });
      }
      await refreshSessions();
      setStep("idle");
      setMsg("Uploaded. Pick a session and run the review.");
    } catch (e: any) {
      setStep("error");
      setMsg(e.message || "Upload failed");
    }
  }

  async function runReview() {
    if (!sessionId) {
      setMsg("Select a session first.");
      return;
    }
    setStep("running");
    setCompleted([]);
    setCurrent(PHASE_ORDER[0]);
    setMsg("");
    try {
      const { run_id } = await createRun(sessionId, sourceSet);
      const es = new EventSource(streamUrl(run_id));
      es.onmessage = (ev) => {
        const data = JSON.parse(ev.data);
        if (data.type === "phase") {
          setCompleted(data.completed || []);
          setCurrent(data.phase);
        } else if (data.type === "done") {
          es.close();
          setStep("done");
          router.push(`/dashboard/${run_id}`);
        } else if (data.type === "error") {
          es.close();
          setStep("error");
          setMsg(data.message || "Run failed");
        }
      };
      es.onerror = () => {
        // stream ended; navigate anyway (run persisted)
        es.close();
        router.push(`/dashboard/${run_id}`);
      };
    } catch (e: any) {
      setStep("error");
      setMsg(e.message || "Could not start run");
    }
  }

  const selected = sessions.find((s) => s.session_id === sessionId);
  const hasLink = !!selected?.content_path?.toLowerCase().startsWith("http");
  const [fetching, setFetching] = useState(false);

  async function fetchFromLink() {
    if (!sessionId) return;
    setFetching(true);
    setMsg("");
    try {
      const r = await fetchSessionContent(sessionId);
      setMsg(`Fetched ${r.chunks} content chunks from the session's link.`);
      await refreshSessions();
    } catch (e: any) {
      setMsg(e.message || "Could not fetch content from the link");
    } finally {
      setFetching(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Upload &amp; Run</h1>
        <p className="mt-1 text-black/50">
          Ingest the mastersheet, question set, and session content, then run the multi-agent review.
        </p>
      </div>

      <section className="grid gap-4 md:grid-cols-2">
        <DropZone label="Mastersheet" hint="CSV / XLSX — one row per session (ground truth)" file={master} onFile={setMaster} />
        <DropZone label="Question set" hint="CSV / XLSX / JSON — the questions to review" file={questions} onFile={setQuestions} />
        <DropZone label="In-class quiz (optional)" hint="CSV / XLSX / JSON — enables cross-set overlap checks" file={quiz} onFile={setQuiz} />
        <DropZone label="Session content" hint=".pptx / .pdf / .md — enables scope & verbatim checks" file={content} onFile={setContent} />
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-primary" onClick={doUpload} disabled={step === "uploading"}>
          {step === "uploading" ? "Uploading…" : "Ingest files"}
        </button>
        {msg && <span className="text-sm text-black/50">{msg}</span>}
      </div>

      <section className="card">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <div className="label mb-1">Session</div>
            <select
              className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
            >
              <option value="">— select —</option>
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.session_id} · {s.topic || s.unit}
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="label mb-1">Set to review</div>
            <select
              className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm"
              value={sourceSet}
              onChange={(e) => setSourceSet(e.target.value)}
            >
              <option value="mcq_assignment">MCQ assignment</option>
              <option value="in_class_quiz">In-class quiz</option>
              <option value="examination">Examination</option>
            </select>
          </div>
          {selected && (
            <div className="text-sm text-black/50">
              {Object.entries(selected.question_counts).map(([k, v]) => (
                <span key={k} className="mr-3">
                  {k}: <b>{v}</b>
                </span>
              ))}
            </div>
          )}
          {hasLink && (
            <button className="btn-ghost" onClick={fetchFromLink} disabled={fetching}>
              {fetching ? "Fetching…" : "Fetch content from link"}
            </button>
          )}
          <button className="btn-primary ml-auto" onClick={runReview} disabled={step === "running"}>
            {step === "running" ? "Reviewing…" : "Run review"}
          </button>
        </div>
        {hasLink && (
          <p className="mt-2 text-xs text-black/40">
            This session has a content link in the mastersheet — click “Fetch content from link”
            to pull the slide text for scope &amp; verbatim checks (no upload needed).
          </p>
        )}

        {(step === "running" || step === "done") && (
          <div className="mt-6 space-y-2">
            {PHASE_ORDER.map((p) => {
              const done = completed.includes(p);
              const active = current === p && !done;
              return (
                <div key={p} className="flex items-center gap-3 animate-fadein">
                  <span
                    className={`grid h-6 w-6 place-items-center rounded-full text-xs ${
                      done
                        ? "bg-emerald-500 text-white"
                        : active
                        ? "bg-accent-600 text-white"
                        : "bg-black/[0.06] text-black/40"
                    }`}
                  >
                    {done ? "✓" : active ? "…" : ""}
                  </span>
                  <span className={done || active ? "text-ink" : "text-black/40"}>
                    {PHASE_LABELS[p]}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
