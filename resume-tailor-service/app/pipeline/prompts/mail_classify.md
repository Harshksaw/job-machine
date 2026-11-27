Classify job application emails. Each message below was found by an inbox search for
application outcomes and is not a receipt. Read each one and return one event per
message that is about one of the candidate's job applications.

For each such message:

- `id`: the message id exactly as given. Never make up an id.
- `company`: the employer, not the applicant tracking system or job board that sent the
  mail. Mail sent through a hiring platform on behalf of a company is about that company.
- `role`: the job title when the message names it, else an empty string.
- `date`: the message date as given.
- `outcome`, one of:
  - `rejected`: the application will not move forward, including "the role has been
    filled".
  - `interview`: a person will talk to the candidate (a call, an interview, a
    scheduling link).
  - `assessment`: a test, a take home task or a one way video.
  - `reply`: a human wrote back with no decision yet.
- `confident`: false when the text is cut off before the decision or the decision is
  unclear. A phrase such as "if you are not selected" in a receipt is not a rejection.
- `note`: one short line saying what the message asks or decides, including any
  deadline. No dashes used as punctuation.

Leave out anything that is not about an application: receipts, newsletters, job alerts,
security codes, marketing. Do not reply to, label or change any email.

Messages:
{{outputs}}
