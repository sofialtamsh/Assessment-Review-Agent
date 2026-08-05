"use client";

import { useEffect, useState } from "react";
import { dismiss, subscribe } from "@/lib/toast";
import type { Toast } from "@/lib/toast";

const STYLE: Record<Toast["type"], string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  info: "border-black/10 bg-white text-black/70",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
};
const ICON: Record<Toast["type"], string> = { success: "✓", info: "•", warning: "⚠" };

export default function ToastViewport() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => subscribe(setItems), []);

  if (!items.length) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {items.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-sm shadow-lg animate-fadein ${STYLE[t.type]}`}
          style={{ minWidth: 240, maxWidth: 380 }}
          role="status"
        >
          <span className="mt-0.5 shrink-0">{ICON[t.type]}</span>
          <span className="flex-1 leading-snug">{t.message}</span>
          <button
            className="shrink-0 text-black/30 hover:text-black/60"
            onClick={() => dismiss(t.id)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
