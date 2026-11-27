Read the real application form for this job and list its fields. Read only.

Company: {{company}}
Role: {{role}}
Application page: {{apply_url}}
Listing (when there is no application page): {{job_url}}

Browser rules (Ego Lite, from AGENTS.md):
- Create exactly one TaskSpace named "pipeline {{run_id}} form". Never reuse or hand off
  a space, and never use one that belongs to someone else.
- Read only: open the application page and read what it asks. Never type into any field,
  never upload a file, never sign in or enter a password, never solve a captcha, and
  never click Submit, Apply or any button that sends the application.
- If the page needs a sign in or a captcha to show the form, stop and report what you
  could see.
- Close your TaskSpace when done.
- If no browser is available, read the page over plain HTTP instead.

Output fields:
- url: the page you read
- fields: one entry per form field, in page order:
  - label: the question or field label exactly as shown
  - kind: one of text, textarea, select, radio, checkbox, file, email, phone, url, date,
    number, other
  - required: true when the form marks it required
  - options: the choices for select, radio or checkbox fields, else empty
- note: anything that blocked a full read, else empty
