import type {
  Instruction,
  ReportResponse,
  RunInfo,
  SessionInfo,
  TargetablePhase,
  UnitInfo,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

/** fetch that turns "Failed to fetch" into a clear, diagnosable message. */
async function safeFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  try {
    return await fetch(url, init);
  } catch (e) {
    throw new Error(
      `Cannot reach the backend at ${API_BASE}. Is the API running and is ` +
        `NEXT_PUBLIC_API_BASE_URL correct? (${(e as Error).message})`
    );
  }
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} — ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function checkHealth(): Promise<{ ok: boolean; detail: string }> {
  try {
    const r = await safeFetch("/health", { cache: "no-store" });
    if (!r.ok) return { ok: false, detail: `backend returned ${r.status}` };
    const d = await r.json();
    return { ok: true, detail: `provider: ${d.llm_provider}` };
  } catch (e) {
    return { ok: false, detail: (e as Error).message };
  }
}

export async function uploadFile(
  path: string,
  file: File,
  extra: Record<string, string> = {}
): Promise<any> {
  const fd = new FormData();
  fd.append("file", file);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  return j(await safeFetch(path, { method: "POST", body: fd }));
}

export async function listSessions(): Promise<{ sessions: SessionInfo[] }> {
  return j(await safeFetch("/sessions", { cache: "no-store" }));
}

export async function listUnits(): Promise<{ units: UnitInfo[] }> {
  return j(await safeFetch("/units", { cache: "no-store" }));
}

export async function prepareAndRun(
  unitId: string,
  set: string
): Promise<{ run_id: string; status: string; questions: number; warnings: string[] }> {
  return j(
    await safeFetch(`/units/${unitId}/prepare_and_run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ set }),
    })
  );
}

export async function createEvaluation(
  unitIds: string[],
  set: string,
  title?: string
): Promise<{ run_id: string; status: string; units: number; questions: number; warnings: string[] }> {
  return j(
    await safeFetch("/units/evaluation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit_ids: unitIds, set, title }),
    })
  );
}

export async function fetchSessionContent(
  sessionId: string,
  url?: string
): Promise<{ session_id: string; chunks: number; refs: string[] }> {
  return j(
    await safeFetch(`/sessions/${sessionId}/fetch_content`, {
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
    await safeFetch("/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id, source_set, token_limit }),
    })
  );
}

export async function getRun(runId: string): Promise<RunInfo> {
  return j(await safeFetch(`/runs/${runId}`, { cache: "no-store" }));
}

export async function getReport(runId: string): Promise<ReportResponse> {
  return j(await safeFetch(`/runs/${runId}/report`, { cache: "no-store" }));
}

export async function bulkApprove(
  runId: string,
  scope: "approve_verdict" | "all_pending" = "approve_verdict"
): Promise<{ approved: number; question_ids: string[] }> {
  return j(
    await safeFetch(`/runs/${runId}/bulk_approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope }),
    })
  );
}

export async function questionAction(
  action: "approve" | "delete",
  questionId: string,
  runId: string
): Promise<any> {
  return j(
    await safeFetch(`/questions/${questionId}/${action}?run_id=${runId}`, { method: "POST" })
  );
}

export async function editQuestion(
  questionId: string,
  runId: string,
  body: Record<string, unknown>
): Promise<any> {
  return j(
    await safeFetch(`/questions/${questionId}/edit?run_id=${runId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function regenerateQuestion(questionId: string, runId: string): Promise<any> {
  return j(await safeFetch(`/questions/${questionId}/regenerate?run_id=${runId}`, { method: "POST" }));
}

export async function applyRegeneration(
  questionId: string,
  runId: string,
  candidate: unknown
): Promise<any> {
  return j(
    await safeFetch(`/questions/${questionId}/apply_regeneration?run_id=${runId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate }),
    })
  );
}

export async function listInstructions(): Promise<{
  instructions: Instruction[];
  targetable: TargetablePhase[];
}> {
  return j(await safeFetch("/instructions", { cache: "no-store" }));
}

export async function addInstruction(phase: string, text: string): Promise<Instruction> {
  return j(
    await safeFetch("/instructions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phase, text }),
    })
  );
}

export async function deleteInstruction(id: number): Promise<any> {
  return j(await safeFetch(`/instructions/${id}`, { method: "DELETE" }));
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
