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
