# Job-search session handoff — 2026-07-31

Paste this into a **fresh Claude Code session** to continue cheaply. The prior session
grew large (heavy LinkedIn browser automation), so per-action cost climbed to ~$102.
A clean session resets the cost floor. Mandatory workflow in `CLAUDE.md` still applies
(dossier at first touch, kit + tailor per apply, fit-score before apply, sheet log
after external actions, show every outreach for approval before sending, no em-dashes).

## Done this session (2026-07-31)
- **Sent 9 LinkedIn connect requests, all Pending, all logged (dossiers + Google Sheet, every webhook returned `{"ok":true}`):**
  - **Promise Robotics** (fit 8, applied) — people-mining completed. Sent to: Sami Alperen Akgün (Sr Robotics SWE), Farid Mobasser (BD/Product), Ella Morgan (Software Developer), Tilemachos Pechlivanoglou (SW Eng Manager), Sam Dehghan (Robotics SWE), Amirreza Asadzadeh (ML SWE), Milad Abbasi (Robotics/ML SW Dev), Vivek Venugopalan (Robotics SW Dev, actively hiring). **Promise now has 11 pending connects total** (incl. prior Stephanie Lennox, Aniket Joshi (1st), Kody Kou). **Promise accessible 2nd-degree engineers are fully mined — nothing left to mine there.**
  - **StackAdapt** (fit 7, applied) — Taylar Martin (Lead Talent Partner, actively hiring for the exact role). **User-approved fit-7 escalation exception.**
- **Connects this session: 9** (LinkedIn per-session self-cap is 12).
- **Correction logged:** prior-session memory claimed "queued/approved outreach for Sami and Taylar." Inaccurate — no pre-approved queue existed; Sami was an undrafted reserve, StackAdapt had no drafted outreach. Dossiers are the accurate record.

## New roles discovered + dossiered this session (LinkedIn jobs, Canada remote, entry/associate, past week)
Full JDs NOT yet read — read before applying (fit-score-before-apply rule).
- **Cohere — Software Engineer, Adoption** (Canada Remote, fit 7). Dossier id `722de02e8c8c4b0f87c9c2150cec9f90`. Top green-flag (Toronto LLM leader, strong RAG/LLM overlap). Likely forward-deployed/solutions eng — confirm experience bar. Apply likely via Cohere **Greenhouse** (no Easy Apply).
- **Constellation Dealer Group — Software Developer** (Remote Canada, CA$65-85K, fit 6). Dossier id `0e67a4a46a7f490a9bf7d0225cecae1c`. Real salaried FT, **Easy Apply (completable, low friction)**. Auto-dealer vertical software; stack unknown — verify JD.
- **Jobright.ai — Full Stack SWE, New Grad** (new listing 2026-07-31). Logged to existing dossier `a9a6cced36dd4279886d656c4b9910df`. Apply is Jobright-account-gated. **Co-founder Ethan Zheng already messaged (unanswered) — do NOT double-message.**
- **Skipped (contract/staffing/aggregator):** Turing (Sr, contract), DataAnnotation (AI-trainer gig), Spait Infotech (MERN staffing, already viewed), Hired (aggregator repost).

## ▶️ NEXT — run these (user chose to defer applies to a fresh session)
1. **Cohere — Software Engineer, Adoption**: open the LinkedIn listing → find the Cohere careers/Greenhouse link → read full JD. Confirm experience bar (if it wants 3+ yrs or heavy customer-facing, note fit and pause for Harsh). If completable and fit>=6, apply via their ATS with standing answers. Build the evidence kit first: `POST /api/jobs/722de02e8c8c4b0f87c9c2150cec9f90/generate-kit?session=LinkedIn 2026-07-31`.
2. **Constellation Dealer Group — Software Developer**: LinkedIn Easy Apply, completable. Read JD for tech match; if fit>=6, Easy Apply with base `resume.pdf` + standing answers. Kit: `POST /api/jobs/0e67a4a46a7f490a9bf7d0225cecae1c/generate-kit?session=LinkedIn 2026-07-31`.
3. **Optional: check replies.** 11 Promise + 1 StackAdapt connects pending. If any accepted, a warm follow-up message is possible — draft and show Harsh for approval before sending (rule 3).
4. Continue LinkedIn jobs search for more green-flag roles (past-24h filter to avoid re-reviewing the exhausted set). Contract/AI-training gigs dominate — skip them.

## 📌 Standing answers (already user-approved, reuse everywhere)
- **Salary:** "Open / negotiable. Confident we can align within your bands; optimizing for opportunity/mission/growth rather than a number." (No floor.)
- **Work auth:** "Yes — authorized to work in Canada, no visa/immigration sponsorship required." (Never pause on sponsorship.)
- **EEO / demographics:** "Prefer not to say."
- **Location:** Kelowna, BC, Canada; remote + open to relocation.
- **Links:** linkedin.com/in/harsh-kumar-s-32727b247 · github.com/Harshksaw · harshsaw.me
- **Contact:** mister.harshkumar@gmail.com · +1 (778) 583-2260

## 💰 Cost note
Session reached ~$102. Full browser form-filling is the expensive part; prefer text tools (get_page_text/read_page/find) for scouting and reserve screenshots for the click steps of an actual apply. Sheet webhook must be opened in-browser (needs the logged-in Google session); curl gets redirected to sign-in.
