# Job Machine: Claude Code

**Read `AGENTS.md` first.** It is the canonical brief for every agent in this repo: hard
rules, eligibility policy, the dossier API contract, sheet logging, browser setup, and a
table of which file owns which fact. Nothing in this file repeats it.

## Claude-only notes

- **Routing:** Claude Code, Cursor, and any subagent must read `AGENTS.md` and
  `docs/AGENT-PLAYBOOK.md` for which file owns which fact. Do not paste the
  playbook into this file.
- **Personal answers** (address, salary, exact work status, DOB, French, start date) are in
  `docs/PERSONAL-ANSWERS.md`, which is gitignored because `origin` is a PUBLIC repo. If a
  blank there is unfilled, it is a rule 5 pause. Never invent one.
- **Private memory** lives in `~/.claude/projects/-Users-harshsaw-job-machine/memory/`.
  Cursor and every other agent cannot read it, so durable repo knowledge does not belong
  there. When you learn a reusable technique or gotcha, write it to
  `docs/AGENT-PLAYBOOK.md` and keep memory for Claude-session bookkeeping only.
- **Headless `claude -p`** (used by `generate-kit` and `/tailor` via
  `resume-tailor-service/app/claude_cli.py`) inherits the global
  `~/.claude/settings.json` `defaultMode`. If that is `plan`, every call returns prose and
  502s. The required isolation flags and the schema gotcha are in
  `docs/AGENT-PLAYBOOK.md` under "Headless Claude subprocesses".
- **`/graphify`** comes from the global config at `~/.claude/skills/graphify/SKILL.md`.
  Invoke the Skill tool with `skill: "graphify"` before anything else when Harsh types it.
