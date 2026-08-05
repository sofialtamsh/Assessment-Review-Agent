"use client";

import { useEffect } from "react";
import { API_BASE } from "@/lib/api";
import { toast } from "@/lib/toast";

/** Surfaces storage status as a bottom-right toast (once per session): a green
 *  confirmation when permanent, or a warning when temporary. */
export default function StorageBanner() {
  useEffect(() => {
    fetch(`${API_BASE}/health`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        if (!d || typeof d.persistent !== "boolean") return;
        if (d.persistent) {
          toast.once("storage", "success", `Permanent storage · ${d.storage || "database"}`);
        } else {
          toast.once(
            "storage-temp",
            "warning",
            "Temporary storage — reviewed data resets on restart. Set DATABASE_URL (Neon Postgres) to make it permanent."
          );
        }
      })
      .catch(() => {});
  }, []);

  return null;
}
