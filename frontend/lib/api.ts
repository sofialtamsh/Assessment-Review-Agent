import type {
  Instruction,
  ReportResponse,
  Rubric,
  RunInfo,
  SessionInfo,
  TargetablePhase,
  UnitInfo,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";

// ---- lightweight auth (shared-password login) --------------------------- //
const AUTH_KEY = "arp_auth";

export interface AuthUser {
  name: string;
  token: string;
}

export function getAuth(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function setAuth(user: AuthUser): void {
  if (typeof window !== "undefined") window.localStorage.setItem(AUTH_KEY, JSON.stringify(user));
}

export function clearAuth(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(AUTH_KEY);
}

function authHeaders(): Record<string, string> {
  const a = getAuth();
  return a ? { "X-Reviewer-Name": a.name, "X-Reviewer-Token": a.token } : {};
}

/** Error that preserves the HTTP status + parsed body (so callers can read a 409). */
export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, message: string, body: any) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/** fetch that turns "Failed to fetch" into a clear, diagnosable message and adds auth. */
async function safeFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const headers = { ...(init?.headers as Record<string, string>), ...authHeaders() };
  try {
    return await fetch(url, { ...init, headers });
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
    let body: any = text;
    try {
      body = JSON.parse(text);
    } catch {
      /* not json */
    }
    const msg = typeof body?.detail === "string" ? body.detail : text;
    throw new ApiError(res.status, `${res.status} ${res.statusText} — ${msg}`, body);
  }
  return res.json() as Promise<T>;
}

// ---- auth + activity ---------------------------------------------------- //
export async function login(name: string, password: string): Promise<AuthUser> {
  const user = await j<AuthUser>(
    await safeFetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, password }),
    })
  );
  setAuth(user);
  return user;
}

export interface PriorReview {
  run_id: string;
  session_id: string;
  source_set: string;
  title: string;
  reviewer: string;
  total_questions: number;
  pass_rate: number;
  verdict_counts: Record<string, number>;
  rubric: { applied?: boolean; fails?: number; warns?: number };
  created_at: string;
}

export interface ActivityItem {
  run_id: string;
  session_id: string;
  source_set: string;
  reviewer: string;
  status: string;
  title: string;
  total_questions: number;
  verdict_counts: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export async function getActivity(limit = 25): Promise<{ activity: ActivityItem[] }> {
  return j(await safeFetch(`/activity?limit=${limit}`, { cache: "no-store" }));
}

export async function getReviewStatus(
  sessionId: string,
  sourceSet: string
): Promise<{ prior: PriorReview[] }> {
  return j(
    await safeFetch(
      `/review_status?session_id=${encodeURIComponent(sessionId)}&source_set=${sourceSet}`,
      { cache: "no-store" }
    )
  );
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

export async function ingestMastersheetLink(url: string): Promise<{
  mode: string;
  ingested: number;
  units?: UnitInfo[];
}> {
  return j(
    await safeFetch("/ingest/mastersheet_link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
  );
}

export async function listSessions(): Promise<{ sessions: SessionInfo[] }> {
  return j(await safeFetch("/sessions", { cache: "no-store" }));
}

export async function listUnits(): Promise<{ units: UnitInfo[] }> {
  return j(await safeFetch("/units", { cache: "no-store" }));
}

export async function prepareAndRun(
  unitId: string,
  set: string,
  force = false
): Promise<{ run_id: string; status: string; questions: number; warnings: string[] }> {
  return j(
    await safeFetch(`/units/${unitId}/prepare_and_run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ set, force }),
    })
  );
}

export interface RubricInput {
  text?: string;
  url?: string;
  file?: File | null;
  criteria?: unknown[]; // reverse-engineered structured criteria
}

/** Reverse-engineer a marking scheme from a reference (gold) question set. */
export async function inferRubric(opts: {
  file?: File | null;
  url?: string;
  text?: string;
}): Promise<{ n_questions: number; n_criteria: number; rubric: Rubric }> {
  const fd = new FormData();
  if (opts.file) fd.append("file", opts.file);
  if (opts.url) fd.append("questions_url", opts.url);
  if (opts.text) fd.append("text", opts.text);
  return j(await safeFetch("/rubric/infer", { method: "POST", body: fd }));
}

export async function createEvaluation(
  unitIds: string[],
  set: string,
  title?: string,
  questionsUrl?: string,
  rubric?: RubricInput,
  force = false
): Promise<{ run_id: string; status: string; units: number; questions: number; warnings: string[] }> {
  return j(
    await safeFetch("/units/evaluation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        unit_ids: unitIds,
        set,
        title,
        questions_url: questionsUrl,
        rubric_text: rubric?.text || "",
        rubric_url: rubric?.url || "",
        rubric_criteria: rubric?.criteria || undefined,
        force,
      }),
    })
  );
}

export async function createEvaluationUpload(
  unitIds: string[],
  examFile: File | null,
  title?: string,
  questionsUrl?: string,
  rubric?: RubricInput,
  force = false
): Promise<{ run_id: string; status: string; units: number; questions: number; warnings: string[] }> {
  const fd = new FormData();
  fd.append("unit_ids", unitIds.join(","));
  if (examFile) fd.append("file", examFile);
  if (questionsUrl) fd.append("questions_url", questionsUrl);
  if (title) fd.append("title", title);
  if (rubric?.text) fd.append("rubric_text", rubric.text);
  if (rubric?.url) fd.append("rubric_url", rubric.url);
  if (rubric?.file) fd.append("rubric_file", rubric.file);
  if (rubric?.criteria?.length) fd.append("rubric_criteria", JSON.stringify(rubric.criteria));
  if (force) fd.append("force", "true");
  return j(await safeFetch("/units/evaluation/upload", { method: "POST", body: fd }));
}

export async function createBatch(
  unitIds: string[],
  set: string
): Promise<{ batch_id: string; source_set: string; items: any[] }> {
  return j(
    await safeFetch("/units/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit_ids: unitIds, set }),
    })
  );
}

export async function getBatch(batchId: string): Promise<{
  batch_id: string;
  source_set: string;
  items: {
    unit_id: string;
    unit: string;
    run_id: string | null;
    status?: string;
    questions?: number;
    error?: string;
    warnings?: string[];
    verdict_counts?: Record<string, number>;
    total_questions?: number;
  }[];
  combined: { total: number; APPROVE: number; REVISE: number; DELETE: number };
}> {
  return j(await safeFetch(`/batch/${batchId}`, { cache: "no-store" }));
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
