"use client";

import { useEffect, useState } from "react";
import { ApiError, clearAuth, getAuth, login } from "@/lib/api";
import type { AuthUser } from "@/lib/api";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setUser(getAuth());
    setReady(true);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      setUser(await login(name.trim(), pw));
    } catch (e: any) {
      setErr(e instanceof ApiError ? e.body?.detail || e.message : e.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    clearAuth();
    setUser(null);
    setName("");
    setPw("");
  }

  // avoid a hydration flash before we've read localStorage
  if (!ready) return null;

  if (!user) {
    return (
      <div className="mx-auto max-w-sm py-16">
        <div className="card">
          <h1 className="text-xl font-semibold tracking-tight">Sign in to review</h1>
          <p className="mt-1 text-sm text-black/50">
            Use your name so your reviews are attributed to you. Everyone shares the same
            team password.
          </p>
          <form onSubmit={submit} className="mt-4 space-y-3">
            <div>
              <div className="label mb-1">Your name</div>
              <input
                autoFocus
                className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm"
                placeholder="e.g. Sofi"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <div className="label mb-1">Team password</div>
              <input
                type="password"
                className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm"
                placeholder="••••••••"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
              />
            </div>
            {err && <div className="text-sm text-rose-600">{err}</div>}
            <button className="btn-primary w-full" disabled={busy || !name.trim() || !pw}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="mb-6 flex items-center justify-end gap-3 text-sm">
        <span className="text-black/50">
          Signed in as <b className="text-ink">{user.name}</b>
        </span>
        <button className="btn-ghost px-2 py-1 text-xs" onClick={logout}>
          Log out
        </button>
      </div>
      {children}
    </>
  );
}
