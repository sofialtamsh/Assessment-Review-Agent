import type { ReportResponse, RunInfo, SessionInfo, UnitInfo } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function uploadFile(
  path: string,
  file: File,
  extra: Record<string, string> = {}
): Promise<any> {
  const fd = new FormData();
  fd.append("file", file);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  return j(await fetch(`${API_BASE}${path}`, { method: "POST", body: fd }));
}

export async function listSessions(): Promise<{ sessions: SessionInfo[] }> {
  return j(await fetch(`${API_BASE}/sessions`, { cache: "no-store" }));
}

export async function listUnits(): Promise<{ units: UnitInfo[] }> {
  return j(await fetch(`${API_BASE}/units`, { cache: "no-store" }));
}

export async function prepareAndRun(
  unitId: string,
  set: string
): Promise<{ run_id: string; status: string; questions: number; warnings: string[] }> {
  return j(
    await fetch(`${API_BASE}/units/${unitId}/prepare_and_run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ set }),
    })
  );
}

export async function fetchSessionContent(
  sessionId: string,
  url?: string
): Promise<{ session_id: string; chunks: number; refs: string[] }> {
  return j(
    await fetch(`${API_BASE}/sessions/${sessionId}/fetch_content`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(url ? { url } : {}),
    })
  );
}

export async function createRun(
  session_id: string,
  source_set: string,
  token_limit?: number
): Promise<{ run_id: string; status: string }> {
  return j(
    await fetch(`${API_BASE}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, source_set, token_limit }),
    })
  );
}

export async function getRun(runId: string): Promise<RunInfo> {
  return j(await fetch(`${API_BASE}/runs/${runId}`, { cache: "no-store" }));
}

export async function getReport(runId: string): Promise<ReportResponse> {
  return j(await fetch(`${API_BASE}/runs/${runId}/report`, { cache: "no-store" }));
}

export async function questionAction(
  action: "approve" | "delete",
  questionId: string,
  runId: string
): Promise<any> {
  return j(
    await fetch(`${API_BASE}/questions/${questionId}/${action}?run_id=${runId}`, {
      method: "POST",
    })
  );
}

export async function editQuestion(
  questionId: string,
  runId: string,
  body: Record<string, unknown>
): Promise<any> {
  return j(
    await fetch(`${API_BASE}/questions/${questionId}/edit?run_id=${runId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function regenerateQuestion(questionId: string, runId: string): Promise<any> {
  return j(
    await fetch(`${API_BASE}/questions/${questionId}/regenerate?run_id=${runId}`, {
      method: "POST",
    })
  );
}

export async function applyRegeneration(
  questionId: string,
  runId: string,
  candidate: unknown
): Promise<any> {
  return j(
    await fetch(`${API_BASE}/questions/${questionId}/apply_regeneration?run_id=${runId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate }),
    })
  );
}

export function streamUrl(runId: string): string {
  return `${API_BASE}/runs/${runId}/stream`;
}

export function exportUrl(runId: string, format: string): string {
  return `${API_BASE}/runs/${runId}/export?format=${format}`;
}

export function reportExportUrl(runId: string): string {
  return `${API_BASE}/runs/${runId}/report/export?format=md`;
}
