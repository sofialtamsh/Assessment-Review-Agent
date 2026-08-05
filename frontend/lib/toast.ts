// Tiny dependency-free toast store (pub/sub). Used for STATUS + SUCCESS messages
// only — errors/warnings stay inline (they often carry a link to fix).

export type ToastType = "success" | "info" | "warning";
export interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

let toasts: Toast[] = [];
let listeners: ((t: Toast[]) => void)[] = [];
let nextId = 1;

function emit() {
  for (const l of listeners) l(toasts);
}

function push(type: ToastType, message: string, ttl = 4000) {
  const id = nextId++;
  toasts = [...toasts, { id, type, message }];
  emit();
  if (typeof window !== "undefined") window.setTimeout(() => dismiss(id), ttl);
}

export function dismiss(id: number) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function subscribe(listener: (t: Toast[]) => void) {
  listeners.push(listener);
  listener(toasts);
  return () => {
    listeners = listeners.filter((l) => l !== listener);
  };
}

export const toast = {
  success: (m: string) => push("success", m),
  info: (m: string) => push("info", m),
  warning: (m: string) => push("warning", m, 6000),
  // fire at most once per browser session (for connection / storage status)
  once: (key: string, type: ToastType, m: string) => {
    if (typeof window === "undefined") return;
    const k = `arp_toast_once_${key}`;
    if (window.sessionStorage.getItem(k)) return;
    window.sessionStorage.setItem(k, "1");
    push(type, m);
  },
};
