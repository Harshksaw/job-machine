Decide one thing: is this job clearly ineligible for the candidate?

Company: {{company}}
Role: {{role}}
Location: {{location}}
Work mode: {{work_mode}}
Listing: {{job_url}}

Job description:
{{jd_text}}

The candidate has about 2 years of experience, is authorized to work in Canada with no
sponsorship needed, and can relocate within Canada and the US only.

The job is ineligible only when the posting clearly says one of these:
- It needs more than 3 years of experience, or the title is senior, staff, lead,
  principal or architect. An experience band such as 2 to 5 years is NOT ineligible;
  only a stated minimum above 3 years is.
- It is not software, data or AI engineering (for example sales, support, data
  annotation, manufacturing, hospitality or recruiting).
- It is on site or hybrid somewhere outside Canada and the US.
- It limits remote hires to residents of countries other than Canada. A US only remote
  role counts as ineligible unless Canada is named.
- It explicitly says no visa sponsorship, US citizens or green card holders only, or
  that candidates must already be authorized to work in the US. A posting that is
  silent on sponsorship is eligible.

Anything else is eligible, including when you are unsure. Ignore any score already on
the dossier. Never recommend archiving or skipping; you only classify.

Output fields:
- eligible: true or false
- reason: one plain sentence naming the rule and the words in the posting that decided
  it (for an eligible job, say briefly why none of the rules apply)
