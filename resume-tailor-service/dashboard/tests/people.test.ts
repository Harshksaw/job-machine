import assert from "node:assert/strict";
import test from "node:test";

import { preserveJobAssociation } from "../src/lib/people.ts";

test("editing a legacy company contact does not pin it to the open job", () => {
  const result = preserveJobAssociation(
    {
      name: "Alex Recruiter",
      company: "Acme",
      role: "Backend Engineer",
      job_id: "current-job",
      title: "Recruiter",
      linkedin_url: "",
      links: [],
      status: "sent",
      hook: "",
      message: "",
      notes: "",
    },
    { job_id: "" },
  );

  assert.equal(result.job_id, "");
});

test("editing a pinned contact preserves its original listing", () => {
  const result = preserveJobAssociation(
    {
      name: "Sam Engineer",
      company: "Acme",
      role: "Backend Engineer",
      job_id: "currently-open-job",
      title: "Engineer",
      linkedin_url: "",
      links: [],
      status: "replied",
      hook: "",
      message: "",
      notes: "",
    },
    { job_id: "original-job" },
  );

  assert.equal(result.job_id, "original-job");
});
