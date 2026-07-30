export type Verdict = "PASS" | "WARN" | "FAIL";
export type JudgeVerdict = "APPROVE" | "REVISE" | "DELETE";

export interface Option {
  key: string;
  text: string;
}

export interface Finding {
  question_id: string;
  phase: string;
  check_name: string;
  verdict: Verdict;
  evidence: string;
  suggested_fix?: string | null;
  related_ids: string[];
  bloom?: string | null;
  model?: string | null;
}

export interface Judgment {
  question_id: string;
  verdict: JudgeVerdict;
  reason: string;
  consolidated_fixes: string[];
}

export interface QuestionRow {
  question_id: string;
  session_id: string;
  source_set: string;
  qtype: string;
  stem: string;
  options: Option[];
  correct_keys: string[];
  explanation?: string | null;
  difficulty?: string | null;
  topic?: string | null;
  subtopics: string[];
  status: string;
  judgment: Judgment | null;
  findings: Finding[];
}

export interface DuplicateCluster {
  question_ids: string[];
  kind: string;
  detail: string;
}

export interface SetReport {
  session_id: string;
  total_questions: number;
  pass_rate: number;
  verdict_counts: Record<string, number>;
  key_balance: Record<string, number>;
  difficulty_distribution: Record<string, number>;
  bloom_distribution: Record<string, number>;
  duplicate_clusters: DuplicateCluster[];
  out_of_scope_ids: string[];
  verbatim_lift_ids: string[];
  subtopic_coverage: Record<string, number>;
  over_tested_subtopics: string[];
  scenario_vs_recall_ratio: number;
  rubric_applied?: boolean;
  rubric_compliance?: RubricCheck[];
}

export interface RubricCheck {
  name: string;
  metric: string;
  comparator: string;
  target: string;
  actual: string;
  gate: "fail" | "warn" | "info";
  status: "pass" | "warn" | "fail" | "manual";
  detail: string;
}

export interface Rubric {
  text: string;
  criteria: unknown[];
  source: string;
}

export interface PhaseCost {
  phase: string;
  model?: string | null;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  usd: number;
}

export interface Cost {
  per_phase: Record<string, PhaseCost>;
  total_tokens: number;
  total_usd: number;
}

export interface RunInfo {
  run_id: string;
  session_id: string;
  source_set: string;
  status: string;
  current_phase: string;
  completed_phases: string[];
  report: SetReport | null;
  cost: Cost | null;
  budget: { limit: number; spent: number } | null;
  errors: string[];
}

export interface PhaseSummary {
  phase: string;
  label: string;
  uses_llm: boolean;
  ran: boolean;
  verdict_counts: Record<string, number>;
  checks: string[];
  check_breakdown?: Record<string, Record<string, number>>;
  total_findings: number;
  questions_flagged: number;
}

export interface ReportResponse {
  run: RunInfo;
  questions: QuestionRow[];
  set_findings: Finding[];
  report: SetReport | null;
  rubric: Rubric | null;
  phase_summary: PhaseSummary[];
}

export interface SessionInfo {
  session_id: string;
  course: string;
  module: string;
  unit: string;
  topic: string;
  subtopics: string[];
  content_path?: string | null;
  question_counts: Record<string, number>;
}

export interface Instruction {
  id: number;
  phase: string;
  text: string;
  session_id: string | null;
  created_at: string;
}

export interface TargetablePhase {
  phase: string;
  label: string;
  description: string;
}

export interface UnitInfo {
  unit_id: string;
  course: string;
  module: string;
  unit: string;
  subtopics: string[];
  has_content: boolean;
  content_parsed: boolean;
  has_tutorial: boolean;
  has_mcq_assignment: boolean;
  has_in_class_quiz: boolean;
  prepared_sets: string[];
}
