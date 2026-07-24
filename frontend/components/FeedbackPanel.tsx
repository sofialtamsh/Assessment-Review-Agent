"use client";

import { useCallback, useEffect, useState } from "react";
import { addInstruction, deleteInstruction, listInstructions } from "@/lib/api";
import type { Instruction, TargetablePhase } from "@/lib/types";

export default function FeedbackPanel({ onChange }: { onChange?: () => void }) {
  const [items, setItems] = useState<Instruction[]>([]);
  const [phases, setPhases] = useState<TargetablePhase[]>([]);
  const [phase, setPhase] = useState("all");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await listInstructions();
      setItems(r.instructions);
      setPhases(r.targetable);
    } catch (e: any) {
      setErr(e.message || "");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const labelFor = (p: string) => phases.find((x) => x.phase === p)?.label || p;
  const descFor = (p: string) => phases.find((x) => x.phase === p)?.description || "";

  async function save() {
    if (!text.trim()) return;
    setBusy(true);
    setErr("");
    try {
      await addInstruction(phase, text.trim());
      setText("");
      await load();
      onChange?.();
    } catch (e: any) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: number) {
    await deleteInstruction(id);
    await load();
    onChange?.();
  }

  return (
    <section className="card">
      <div className="label mb-1">Teach the agents (feedback &amp; standing instructions)</div>
      <p className="mb-3 text-sm text-black/50">
        Give an instruction and choose which agent should follow it. It&apos;s appended to that
        agent&apos;s prompt on <b>every future run</b>, so it &quot;remembers&quot; your preference.
      </p>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <div className="sm:w-56">
          <select
            className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-sm"
            value={phase}
            onChange={(e) => setPhase(e.target.value)}
          >
            {phases.map((p) => (
              <option key={p.phase} value={p.phase}>
                {p.label}
              </option>
            ))}
          </select>
          <div className="mt-1 px-1 text-xs text-black/40">{descFor(phase)}</div>
        </div>
        <textarea
          className="min-h-[42px] flex-1 rounded-xl border border-black/10 p-2 text-sm"
          rows={2}
          placeholder="e.g. Distractors must be plausible to a student who studied the topic; never approve if the explanation contradicts the key."
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button className="btn-primary" onClick={save} disabled={busy || !text.trim()}>
          {busy ? "Saving…" : "Teach agent"}
        </button>
      </div>
      {err && <p className="mt-2 text-sm text-rose-600">{err}</p>}

      {items.length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="label">Active instructions ({items.length})</div>
          {items.map((it) => (
            <div
              key={it.id}
              className="flex items-start gap-3 rounded-lg border border-black/[0.06] p-2.5"
            >
              <span className="chip bg-accent-50 text-accent-700 whitespace-nowrap">
                {labelFor(it.phase)}
              </span>
              <span className="flex-1 text-sm text-black/70">{it.text}</span>
              <button
                className="text-xs text-black/30 hover:text-rose-500"
                onClick={() => remove(it.id)}
                title="Remove"
              >
                remove
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
