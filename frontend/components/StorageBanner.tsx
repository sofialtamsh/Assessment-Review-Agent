"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

/** Warns loudly when the backend is on temporary (non-persistent) storage, so it's
 *  obvious WHY reviewed data disappears after a restart — and how to fix it. */
export default function StorageBanner() {
  const [temporary, setTemporary] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/health`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        if (d && d.persistent === false) setTemporary(true);
      })
      .catch(() => {});
  }, []);

  if (!temporary) return null;

  return (
    <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
      ⚠ <b>Temporary storage.</b> Reviewed content will be lost when the server sleeps or
      restarts. To make it permanent, set a <b>DATABASE_URL</b> (a free Neon Postgres) in the
      backend&apos;s environment and redeploy. Until then, the already-reviewed guardrail and
      history reset on each restart.
    </div>
  );
}
