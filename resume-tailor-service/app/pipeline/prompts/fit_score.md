Score how well the candidate fits this job, from 1 to 10.

Company: {{company}}
Role: {{role}}
Location: {{location}} ({{work_mode}})

Job description:
{{jd_text}}

Candidate source ledger (the ONLY facts you may use about the candidate):
{{ledger}}

Rules:
- Judge only from the ledger. Never assume a skill, date or number it does not contain.
- 8 to 10: most core requirements are shown in the ledger. 6 to 7: a real match with
  gaps worth naming. Below 6: the core of the job is missing from the ledger.
- A low score is not a rejection. The dossier stays active for review; you only score.
- Gaps name what the job asks for that the ledger does not show, stated plainly.

Output fields:
- score: whole number 1 to 10
- reason: one or two plain sentences, citing ledger ids where they matter
- gaps: list of short strings, empty when there are none
