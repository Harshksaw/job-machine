# Live auto-apply queue — Canada-eligible, CLEAN_DIRECT, per-posting liveness-verified
Rebuilt 2026-08-01 (apply-loop). Old top25-derived rows were stale; replaced. All URLs below verified live at build time (Greenhouse job JSON 200 / Ashby isListed:true addressCountry:Canada / Lever hostedUrl live).

## Proven auto-submit method (submitted 6+ today)
1. Navigate to apply URL (Ashby: append /application; Rippling: click "Apply now"; Greenhouse: form is on-page).
2. Read-only JS check (iframes, /recaptcha|hcaptcha|grecaptcha/i, enumerate fields). Invisible reCAPTCHA v3 badge with no challenge = fine.
3. Upload ./resume.pdf via file_upload to the file-input ref (from find). ATS auto-parses name/email/phone.
4. Fill remaining with the form_input TOOL ONLY (ref from find) — NOT scripted JS / keyboard batches (classifier blocks those).
5. Standing answers: work-auth CA=Yes, sponsorship=No, salary=Negotiable, relocation="based Kelowna, open to relocating", start-date=blank, SMS consent=No, EEO=blank. Answer skill/experience questions honestly (no fabrication). Education: Okanagan College, BCIS, grad Dec 2026, current student.
6. Submit; confirm success. Log dossier (capture status=applied + activity) + Google Sheet (ok:true).
- Ashby / Lever = reliable clean submit. Greenhouse sometimes triggers an 8-char EMAIL "confirm you're human" verify code after Submit → HANDOFF (do NOT enter/bypass the code; save answers for Harsh to finalize).

## SUBMITTED this session (do not re-apply)
Reailize, Fleetio, Certa, Tiny Health, Cresta, Cerebras (Tools & Infra/DevOps).

## IN-FLIGHT (apply agent running now)
Pogo (Ashby), Chainlink Labs (Ashby), Vivid Seats (Greenhouse).

## READY QUEUE — apply next (Ashby/Lever first = most reliable; Greenhouse may hit verify-gate)
| Company | Role | Fit | Location | ATS | Apply URL |
|---|---|---|---|---|---|
| Jobber | Intermediate Software Engineer | 8 | Toronto | Ashby | https://jobs.ashbyhq.com/jobber/cf26b34b-33b0-487c-bdfa-4dd4c59d53e9 |
| Float | Full Stack Development (Remote Canada) | 8 | Toronto / Remote CA | Ashby | https://jobs.ashbyhq.com/float/732ea90e-c7e1-4623-ac69-0cddc71aac88 |
| Achievers | Intermediate Software Engineer | 7 | Toronto | Lever | https://jobs.lever.co/achievers/d943cdf8-99a7-4e5f-b310-159970f95903 |
| Stripe | Software Engineer, New Grad, Dev & End User Experience | 9 | Toronto | Greenhouse | https://job-boards.greenhouse.io/stripe/jobs/7991718 |
| Faire | Product Engineer – Brand (Fullstack) | 9 | KW / Toronto | Greenhouse | https://boards.greenhouse.io/faire/jobs/8654106002 |
| Faire | Product Engineer – Retailer Experience & Growth | 8 | KW / Toronto | Greenhouse | https://boards.greenhouse.io/faire/jobs/8603123002 |
| Stripe | Full Stack Engineer, Support Experience | 8 | Toronto | Greenhouse | https://job-boards.greenhouse.io/stripe/jobs/8062708 |
| Stripe | Backend/API Engineer, Metronome (Billing) | 8 | Toronto | Greenhouse | https://job-boards.greenhouse.io/stripe/jobs/7737237 |
| Stripe | Backend Engineer, Financial Connections | 8 | Toronto | Greenhouse | https://job-boards.greenhouse.io/stripe/jobs/8062299 |
| Stripe | Backend Engineer, Data | 7 | Canada (remote) | Greenhouse | https://job-boards.greenhouse.io/stripe/jobs/7913700 |
| Stripe | Machine Learning Engineer | 7 | Toronto | Greenhouse | https://job-boards.greenhouse.io/stripe/jobs/8014859 |
| Tenstorrent | Software Engineer, Metal Runtime (API & Abstractions) | 6 | Toronto | Greenhouse | https://job-boards.greenhouse.io/tenstorrent/jobs/5192671007 |
| Tenstorrent | Software Engineer, TT-Fabric | 6 | Toronto | Greenhouse | https://job-boards.greenhouse.io/tenstorrent/jobs/4645584007 |

Caution: Planet (Missions Software) has an EAR/ITAR US-person clause — skip; Planet "Platform Operations" (jobs/7593419) is remote-CA but verify no export clause before applying.

## QUEUE ADDITIONS — batch 3 (mined 2026-08-02, per-posting verified live)
| Company | Role | Fit | Location | ATS | Apply URL |
|---|---|---|---|---|---|
| MongoDB | Software Engineer 3, Atlas Search Systems | 7 | Toronto | Greenhouse | https://job-boards.greenhouse.io/mongodb/jobs/7662950 |
| MongoDB | Software Engineer, Code Generation | 7 | BC / Calgary | Greenhouse | https://job-boards.greenhouse.io/mongodb/jobs/7311708 |
| Planet | Software Engineer, Platform Operations | 7 | Canada, Remote | Greenhouse | https://job-boards.greenhouse.io/planetlabs/jobs/7593419 |
| Wikimedia Foundation | Software Engineer, Wikidata Platform | 6 | Remote (Canada listed) | Greenhouse | https://job-boards.greenhouse.io/wikimedia/jobs/8060261 |
(MongoDB Documentation Platform 8054993 held back to avoid over-applying to one company. Planet mission/flight-software reqs SKIPPED — EAR/US-person export risk.)
NOTE: relevant_jobs.csv is exhausted for Canada public-ATS roles; next source = direct Greenhouse/Ashby/Lever board scans for Toronto / Remote-Canada startups.

## QUEUE ADDITIONS — batch 4 (Canadian ATS board scan, 2026-08-02, per-posting verified live)
Prioritize Ashby/Lever (reliable clean submit) + higher fit. Cap Dialpad at 2 and PolicyMe at 1-2 to avoid over-applying to one company.
| Company | Role | Fit | Location | ATS | Apply URL |
|---|---|---|---|---|---|
| Relay (fintech) | Software Engineer | 8 | Toronto | Ashby | https://jobs.ashbyhq.com/relayfi/c412e8d5-d7fc-4dde-b905-e3e4ceb03c08 |
| Procurify | Full Stack Engineer II | 8 | Canada Remote | Ashby | https://jobs.ashbyhq.com/procurify/c75c2494-8c92-4081-8243-2cb6a87cd0ef |
| PolicyMe | Junior Software Engineer | 8 | Ontario (remote) | Lever | https://jobs.lever.co/policyme/2ce5251f-54b8-4430-bda6-1ca19dabba4e |
| Dialpad | Software Engineer, Developer Platform | 8 | Vancouver | Greenhouse | https://job-boards.greenhouse.io/dialpad/jobs/8636218002 |
| Dialpad | Software Engineer, ML Inference Platform | 8 | Kitchener | Greenhouse | https://job-boards.greenhouse.io/dialpad/jobs/8512122002 |
| 1Password | Developer, Open Source | 7 | Remote US/Canada | Ashby | https://jobs.ashbyhq.com/1password/c22ea4e6-f39b-448c-a9e9-a04445ba18e6 |
| Waabi (AV/AI) | Software Engineer, Labelling/Data/Automation | 7 | Toronto | Lever | https://jobs.lever.co/waabi/09e213fd-70fb-4715-949a-891576309002 |
| PolicyMe | Software Engineer | 7 | Ontario (remote) | Lever | https://jobs.lever.co/policyme/98b4ecb9-93c5-43cd-9d29-977232e343a1 |
| Docebo | Forward Deployed Engineer | 6 | Toronto | Ashby | https://jobs.ashbyhq.com/docebo/273845bc-2e43-4e48-99fe-815ff6188d8a |
| Tucows | Data Platform Engineer | 6 | Canada (remote) | Greenhouse | https://job-boards.greenhouse.io/tucows/jobs/7798189003 |
| KOHO | Analytics Engineer | 6 | Canada (remote) | Ashby | https://jobs.ashbyhq.com/koho/2903b2ea-ae70-4c87-a967-675d3f8dee59 |
| Trulioo | Cloud Application Security Engineer | 6 | Vancouver | Ashby | https://jobs.ashbyhq.com/trulioo/84ffcdae-09d6-403f-899a-0440c06de24f |

## QUEUE ADDITIONS — batch 5 (Canadian ATS board scan #2, 2026-08-02, per-posting verified live)
Konrad = Toronto product consultancy hiring across early-career range (RN is a bullseye for Harsh's 2 prod RN apps); cap Konrad at 3, Instacart at 2, Baseten at 2.
| Company | Role | Fit | Location | ATS | Apply URL |
|---|---|---|---|---|---|
| Konrad Group | Mobile Developer (React Native) | 9 | Toronto | Greenhouse | https://www.konrad.com/careers/job/7571349003?gh_jid=7571349003 |
| Konrad Group | Full Stack Developer | 8 | Toronto | Greenhouse | https://www.konrad.com/careers/job/6545898003?gh_jid=6545898003 |
| Konrad Group | Software Developer (Entry Level) | 8 | Toronto | Greenhouse | https://www.konrad.com/careers/job/7669159003?gh_jid=7669159003 |
| Instacart | Software Engineer II, Technical Search Visibility | 7 | Canada-Remote (ON/AB/BC/NS) | Greenhouse | https://instacart.careers/job/?gh_jid=7963661 |
| Baseten | Software Engineer - AI Enablement | 7 | Toronto/Montreal | Ashby | https://jobs.ashbyhq.com/baseten/b88a68b7-d2bc-4a30-a79a-3ef292ad7c26 |
| Instacart | Forward Deployed Engineer | 6 | Canada-Remote | Greenhouse | https://instacart.careers/job/?gh_jid=8097507 |
| Baseten | Software Engineer - Internal Platform | 6 | Toronto/Montreal | Ashby | https://jobs.ashbyhq.com/baseten/081cb52b-5e88-40a1-8def-1e82c8bc97de |
| Samsara | Business Technology Engineer II | 6 | Remote-Canada | Greenhouse | https://www.samsara.com/company/careers/roles/8031880?gh_jid=8031880 |
(Skipped: Vosyn = equity-only master's internship, conflicts with standing prefs. Extra Konrad Android/iOS/Data/Mobile-Entry + Instacart Detection held to avoid over-applying.)

## HANDOFFS needing Harsh (form filled or blocked; ~2-min finishes)
- Voltus (Lever) — no-AI essay + hCaptcha; draft essay in dossier.
- Ledgebrook (CareerPuck) — cross-origin iframe, resume upload not automatable.
- Spring Financial (BambooHR) — reCAPTCHA + street address; salary posted $74-87k.
- Array (Greenhouse QA) — filled + submitted, blocked on 8-char emailed human-verify code; enter the code Greenhouse emailed to finalize.

## DEAD / do not resurface
PCMI (IC SWE gone), Temporal SE II AI Foundations, Procare SWE, Bloomerang Data Eng, Cerebras ML SW Engineer (new-grad), Dutchie (US work-auth gate).
