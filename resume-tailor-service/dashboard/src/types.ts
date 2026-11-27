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

export interface PipelineConfig {
  workers: number;
  adapters: Record<string, AdapterSpec>;
  capability_caps: Partial<Record<PipelineCapability, number>>;
  steps: Record<string, StepPrefs>;
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
