// Shapes mirror the resume-tailor-service FastAPI contract exactly.
// Do not add keys the backend does not send.

export interface Application {
  company: string;
  role: string;
  source: string;
  job_url: string;
  status: string;
  fit: string;
  people: string;
  hooks: string;
  outreach: string;
  notes: string;
  timestamp: string;
  tailored_resume_id: string | null;
}

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
  answer_count: number;
  activity_count: number;
  revision_count: number;
  created_at: string;
  updated_at: string;
}

export type JobDecision = "approve" | "hold" | "applied";

export interface SheetImportResult {
  imported_rows: number;
  created_jobs: number;
  updated_jobs: number;
  job_ids: string[];
}
