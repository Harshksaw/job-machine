import assert from "node:assert/strict";
import test from "node:test";

import { inInboxQueue, inboxBlocker } from "../src/lib/jobs.ts";

test("needs-you includes blocked answers and queued outreach", () => {
  assert.equal(
    inInboxQueue({ status: "applying", needs_user_input: true }, "needs-you"),
    true
  );
  assert.equal(
    inInboxQueue(
      { status: "applied", needs_user_input: false, queued_person_count: 2 },
      "needs-you"
    ),
    true
  );
  assert.equal(
    inInboxQueue(
      { status: "applied", needs_user_input: false, queued_person_count: 0 },
      "needs-you"
    ),
    false
  );
  assert.equal(
    inInboxQueue({ status: "skipped", needs_user_input: true }, "needs-you"),
    false
  );
});

test("inboxBlocker prefers the action a human needs to take", () => {
  assert.equal(
    inboxBlocker({
      needs_user_input: true,
      next_action: "Confirm salary band",
    }),
    "Confirm salary band"
  );
  assert.equal(
    inboxBlocker({ needs_user_input: true, next_action: "" }),
    "Needs your input"
  );
  assert.equal(
    inboxBlocker({ queued_person_count: 2, next_action: "Apply" }),
    "2 outreach waiting approval"
  );
  assert.equal(
    inboxBlocker({ next_action: "Hold for later", notes: "ignored" }),
    "Hold for later"
  );
});
