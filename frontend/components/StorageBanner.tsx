"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

/** Shows storage status: a warning when temporary (data lost on restart), or a small
 *  green confirmation when permanent. */
export default function StorageBanner() {
  const [state, setState] = useState<{ persistent: boolean; storage: string } | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/health`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        if (d && typeof d.persistent === "boolean") {
          setState({ persistent: d.persistent, storage: d.storage || "" });
        }
      })
      .catch(() => {});
  }, []);

  if (!state) return null;

  if (state.persistent) {
    return (
      <div className="mb-4 flex items-center gap-2">
        <span className="chip bg-emerald-50 text-emerald-700">
          ✓ Permanent storage{state.storage ? ` · ${state.storage}` : ""}
        </span>
      </div>
    );
  }

  return (
    <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
      ⚠ <b>Temporary storage.</b> Reviewed content will be lost when the server sleeps or
      restarts. To make it permanent, set a <b>DATABASE_URL</b> (a free Neon Postgres) in the
      backend&apos;s environment and redeploy. Until then, the already-reviewed guardrail and
      history reset on each restart.
    </div>
  );
}
