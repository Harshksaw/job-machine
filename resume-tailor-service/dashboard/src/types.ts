// Shapes mirror the resume-tailor-service FastAPI contract exactly.
// Do not add keys the backend does not send.

export interface JobSelection {
  job_id: string;
  bullet_ids: string[];
}

export interface ProjectSelection {
  project_id: string;
  bullet_ids: string[];
}

export interface Manifest {
  summary: string;
  job_selections: JobSelection[];
  project_selections: ProjectSelection[];
  achievement_ids: string[];
  skill_ids: string[];
  job_trim_priority: string[];
}

export interface TailoredResumeMeta {
  company: string;
  role: string;
  jd_text: string;
  pdf_path: string; // server path — intentionally unused by the UI
  pages: number;
  created_at: string;
  job_url: string | null;
  manifest: Manifest;
}

export interface TailorResponse {
  pdf_path: string;
  manifest: Manifest;
  pages: number;
  resume_id: string | null;
}

export interface BankBullet {
  id: string;
  text: string;
}

export interface BankJob {
  id: string;
  company: string;
  title: string;
  bullets: BankBullet[];
}

export interface BankProject {
  id: string;
  name: string;
  bullets: BankBullet[];
}

export interface ResumeBank {
  jobs: BankJob[];
  projects: BankProject[];
  achievements: BankBullet[];
  skills: BankSkill[];
}

export interface BankSkill {
  id: string;
  category: string;
  items: string;
}

export interface Link {
  label: string;
  url: string;
}

export interface PersonInput {
  name: string;
  title: string;
  company: string;
  role: string | null;
  job_id: string;
  linkedin_url: string;
  links: Link[];
  status: string;
  hook: string;
  message: string;
  notes: string;
}

export interface Person extends PersonInput {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface FitEvidence {
  requirement: string;
  strength: "strong" | "partial" | "gap";
  proof: string;
  source_ids: string[];
}

export interface FitAnalysis {
  score: number;
  recommendation: "apply" | "review" | "skip";
  verdict: string;
  role_thesis: string;
  keywords: string[];
  evidence: FitEvidence[];
  gaps: string[];
  positioning: string[];
}

export interface ApplicationAnswerInput {
  question: string;
  answer: string;
  constraints: string;
  status: "draft" | "approved" | "submitted";
  source_ids: string[];
  needs_user_input: boolean;
  clarification: string;
}

export interface ApplicationAnswer extends ApplicationAnswerInput {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface JobActivityInput {
  kind: string;
  title: string;
  detail: string;
  session: string;
  occurred_at: string | null;
  external_id: string | null;
}

export interface JobActivity extends JobActivityInput {
  id: string;
  created_at: string;
}

export interface JobWorkspaceInput {
  company: string;
  role: string;
  job_url: string;
  source: string;
  location: string;
  work_mode: string;
  compensation: string;
  status: string;
  priority: string;
  fit_score: number | null;
  jd_text: string;
  company_context: string;
  why_this_role: string;
  research_brief: string;
  apply_url: string;
  notes: string;
  next_action: string;
  deadline: string;
  fit_analysis: FitAnalysis | null;
  cover_letter: string;
  application_answers: ApplicationAnswer[];
  tailored_resume_id: string | null;
}

export interface JobRevision {
  id: string;
  reason: string;
  changed_fields: string[];
  snapshot: Record<string, unknown>;
  created_at: string;
}

export interface JobWorkspace extends JobWorkspaceInput {
  id: string;
  activities: JobActivity[];
  revisions: JobRevision[];
  created_at: string;
  updated_at: string;
}

export interface JobSummary {
  id: string;
  company: string;
  role: string;
  job_url: string;
  source: string;
  location: string;
  work_mode: string;
  status: string;
  priority: string;
  fit_score: number | null;
  recommendation: "apply" | "review" | "skip" | null;
  next_action: string;
  deadline: string;
  notes: string;
  tailored_resume_id: string | null;
  has_cover_letter: boolean;
  needs_user_input: boolean;
  person_count: number;
  queued_person_count: number;
  answer_count: number;
  activity_count: number;
  revision_count: number;
  created_at: string;
  updated_at: string;
}

export interface FollowUpNudge {
  job_id: string;
  company: string;
  role: string;
  application_date: string;
  age_days: number;
  state: "due" | "overdue";
  draft: string;
  approval_required: boolean;
}

export type JobDecision = "approve" | "hold" | "applied";

// Agent orchestrator settings (/api/pipeline/*). Keys never appear here: an adapter
// names the env var that holds its key, and the API only says whether it is set.
export type PipelineCapability = "cheap" | "reason" | "web" | "browser_read";

export interface AdapterSpec {
  name: string;
  type: "cli" | "api" | "sdk";
  command: string[];
  output: "file" | "stdout";
  isolation: string;
  provider: string;
  model: string;
  key_env: string;
  env: Record<string, string>;
  capabilities: PipelineCapability[];
  cost_tier: number;
  max_parallel: number;
  enabled: boolean;
  timeouts: Partial<Record<PipelineCapability, number>>;
  family: string;
}

export interface StepCanary {
  adapter: string;
  share: number;
}

export interface StepPrefs {
  prefer: string[];
  canary: StepCanary | null;
}

export interface TaskSchedule {
  every_minutes: number;
  enabled: boolean;
}

export interface PipelineConfig {
  workers: number;
  adapters: Record<string, AdapterSpec>;
  capability_caps: Partial<Record<PipelineCapability, number>>;
  steps: Record<string, StepPrefs>;
  // Task pipelines the worker enqueues on a timer; absent means off.
  schedules?: Record<string, TaskSchedule>;
  // The dossier Research button enqueues a packet run instead of the research CLI.
  research_via_pipeline?: boolean;
  version: number;
  updated_at: string;
}

export interface AdapterHealth {
  healthy: boolean;
  reason: string;
  until: string | null;
}

export interface AdapterTestResult {
  outcome: string;
  error: string;
  model: string;
  at: string;
  duration_ms: number;
}

export interface AdapterStatus extends AdapterSpec {
  key_set: boolean;
  health: AdapterHealth;
  last_test: AdapterTestResult | null;
}

export interface PipelineVersion {
  version: number;
  updated_at: string;
  note: string;
}

export interface PipelineStep {
  step: string;
  capability: PipelineCapability;
}

// Pipeline runs and the attempt ledger (/api/pipeline/runs, /stats, /worker).
export type PipelineStepStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface PipelineRunSummary {
  id: string;
  job_id: string;
  pipeline: string;
  status: string;
  terminal_reason: string;
  created_at: string;
  updated_at: string;
  steps: Record<string, PipelineStepStatus>;
}

export interface PipelineStepState {
  status: PipelineStepStatus;
  output: Record<string, unknown> | null;
  error: string;
  started_at: string;
  finished_at: string;
}

export interface PipelineAttempt {
  id: string;
  run_id: string;
  job_id: string;
  step: string;
  adapter: string;
  model: string;
  prompt_version: string;
  started_at: string;
  duration_ms: number;
  outcome: string;
  error: string;
  tokens_in: number | null;
  tokens_out: number | null;
  cost: number | null;
  output_ref: string;
}

export interface PipelineRunDetail {
  id: string;
  job_id: string;
  pipeline: string;
  status: string;
  order: string[];
  steps: Record<string, PipelineStepState>;
  terminal_reason: string;
  lease_owner: string;
  lease_until: string;
  created_at: string;
  updated_at: string;
  attempts: PipelineAttempt[];
}

export interface PipelineStatsRow {
  attempts: number;
  ok: number;
  pass_rate: number;
  p50_ms: number | null;
  p90_ms: number | null;
  cost: number | null;
  last_error: string;
  last_error_at: string;
  last_at: string;
}

export interface PipelineStats {
  since: string;
  steps: (PipelineStatsRow & { step: string; adapter: string })[];
  models: (PipelineStatsRow & { model: string })[];
  runs: Record<string, number>;
}

export interface PipelineWorkerStatus {
  running: boolean;
  // Workers claiming runs now (Settings `workers`), at most max_workers (PIPELINE_WORKERS).
  workers: number;
  max_workers: number;
}

export interface PipelineEnqueueResult {
  queued: PipelineRunDetail[];
  skipped: string[];
}

// GET /api/pipeline/funnel, the Flow tab.
export type FunnelNodeKind = "source" | "tier" | "dropped" | "reason" | "stage" | "job";

export interface FunnelJob {
  id: string;
  company: string;
  role: string;
  fit_score: number | null;
  status: string;
  /** false for a research item that is not a dossier yet */
  dossier: boolean;
}

export interface FunnelNode {
  key: string;
  label: string;
  kind: FunnelNodeKind;
  count: number;
  children: FunnelNode[];
  /** source: listings the last harvest fetched and dropped */
  fetched?: number;
  dropped?: number;
  /** tier: kept by the last harvest */
  kept?: number;
  /** tier: classified from the location at read time, not stored by the harvest */
  provisional?: boolean;
  job?: FunnelJob;
}

export interface PipelineFunnel {
  since: string;
  until: string;
  generated_at: string;
  total: number;
  stages: Record<string, number>;
  stage_labels: Record<string, string>;
  tiers: Record<string, number>;
  harvest: { run_at: string; fetched: number; kept: number; dropped: number } | null;
  events: Record<string, number>;
  tree: FunnelNode[];
}
