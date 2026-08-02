# Clean-ATS continuation queue — fresh, CA-eligible/sponsorship (built 2026-08-01 session 2)

Source: RDS clean-ATS query (Ashby/Greenhouse/Lever/Rippling), excluded all companies already in dashboard. `visa=True` => employer sponsors (Harsh eligible via sponsorship/TN even for US roles).

**Liveness note:** Greenhouse URLs are server-rendered (curl-checkable). **Ashby is a client-side SPA** — curl always returns 200; must open in browser to see 'Job not found'. Capable Labs + PCMI were curl-LIVE but browser-CLOSED. Verify each Ashby in-browser before filling.

**Proven flow (Ashby, short forms like Clera/Cerebras):** open `/application`, `file_upload` resume.pdf to autofill input (fills name/email/education/location), fill LinkedIn, answer work-auth (No if US + they sponsor / handle EAR citizenship truthfully), Submit. Standing answers per [[work-auth-and-application-answers]].

| Company | Role | Score | ATS | Sponsors | URL |
|---|---|---|---|---|---|
| Capable Labs | Software Engineer | 6 | ashbyhq | YES | https://jobs.ashbyhq.com/Capable/5cd1c05e-6631-43cb-b638-dcecc6602610 |
| LatchBio | Software Engineer | 5 | ashbyhq | YES | https://jobs.ashbyhq.com/LatchBio/14900ad1-ffc2-4790-a720-6363c842be46 |
| Elorian | Inference Infrastructure Engineer, Serving | 5 | ashbyhq | YES | https://jobs.ashbyhq.com/elorian-ai-inc/7836158c-eeb6-4d55-95ca-510b1007b41d |
| Kodiak | Software Engineer, UI Tools Infrastructure | 5 | greenhouse | YES | https://job-boards.greenhouse.io/kodiak/jobs/4320932009 |
| Thinking Machines Lab | Software Engineer, Full Stack, Tinker | 5 | greenhouse | YES | https://job-boards.greenhouse.io/thinkingmachines/jobs/5290314008 |
| Profound | Analytics Engineer | 4 | ashbyhq | YES | https://jobs.ashbyhq.com/Profound/a6a442ba-00b4-4c70-b7fd-6a27eca54d8e |
| Dedalus Labs, Inc. | Systems Engineer | 4 | ashbyhq | YES | https://jobs.ashbyhq.com/dedalus-labs/cc865f1c-3c3a-4e89-ab55-0021b0c34970 |
| Resolution | Research Engineer | 4 | ashbyhq | YES | https://jobs.ashbyhq.com/resolution/ee8f984b-dc19-46e6-93a6-ad4ba66f69ae |
| Recraft | Junior  Machine Learning Engineer | 3 | ashbyhq | YES | https://jobs.ashbyhq.com/recraft/f9c15249-88f1-4e68-8eaf-03fff97971e5 |
| HUD | Research Engineer, QC Automation | 3 | ashbyhq | YES | https://jobs.ashbyhq.com/hud/e6f9812e-dcfd-422b-b614-1d1273c16003 |
| Exa | Research Engineer, Generalist | 3 | ashbyhq | YES | https://jobs.ashbyhq.com/exa/913d2b71-39d5-4d3a-ab8d-ffffa34cd069 |
| Sauna | Applied AI Engineer | 2 | ashbyhq | YES | https://jobs.ashbyhq.com/sauna.ai/8b929ad7-204f-4584-bfa5-a356d08fab87 |
| Retell AI | Software Engineer | 2 | ashbyhq | YES | https://jobs.ashbyhq.com/retell-ai/538ecfa9-2315-42a6-89cc-3cae52165526 |
| Augustus | Software Engineer | 2 | ashbyhq | YES | https://jobs.ashbyhq.com/Augustus/bd9bb1b4-9f01-4215-9fa5-e40a64dc087b |
| Tempo | Software Developer | 9 | ashbyhq | - | https://jobs.ashbyhq.com/tempo-io/f71fd16c-bacb-4e90-9568-fcf9eea98a64 |
| Array | Quality Assurance (QA) Engineer | 8 | greenhouse | - | https://boards.greenhouse.io/array/jobs/5633883004?gh_jid=5633883004 |
| Diagrid | Customer Engineer | 6 | ashbyhq | - | https://jobs.ashbyhq.com/Diagrid/6d47dded-b71d-4d21-ba79-842afe66ff21 |
| Jobgether | Machine Learning Engineer, New Grad - Quora | 5 | lever | - | https://jobs.lever.co/jobgether/4d090288-0343-42cd-8be2-956361f014b3 |
| AssetWatch, Inc. | Quality Assurance Engineer | 4 | greenhouse | - | https://job-boards.greenhouse.io/assetwatch/jobs/4718087005 |
| Jerry.ai | Product Owner, AI Agents and Automation | 4 | ashbyhq | - | https://jobs.ashbyhq.com/Jerry.ai/6d607292-141e-47a3-ab28-f75b71602746 |
| PCMI | Software Engineer  | 4 | rippling | - | https://ats.rippling.com/pcmi/jobs/3c0c434c-d6ca-4a54-becf-8db454a6147c |
| Bloomerang | Data Engineer | 4 | greenhouse | - | https://job-boards.greenhouse.io/bloomerang/jobs/4716623005 |
| Nex | Frontend Engineer - Marketing & Digital Expe | 4 | greenhouse | - | https://job-boards.greenhouse.io/nex/jobs/5289228008 |
| Loop | Software Engineer | 4 | lever | - | https://jobs.lever.co/loopreturns/4fc9603b-95c6-4d05-8d5a-4247fa108418 |
| Chainlink Labs | Software Engineer I, CCIP | 3 | ashbyhq | - | https://jobs.ashbyhq.com/chainlink-labs/8485e325-111f-4370-b3c6-0ed95872144f |
| Tenstorrent | Software Engineer, Metal Runtime (API & Abst | 3 | greenhouse | - | https://job-boards.greenhouse.io/tenstorrent/jobs/5192671007 |
| Mercury | Software Engineer - Product | 3 | greenhouse | - | https://job-boards.greenhouse.io/mercury/jobs/6101145004 |
| Campspot | AI Software Developer | 3 | rippling | - | https://ats.rippling.com/campspot/jobs/67d0ee6b-7f5d-4411-a80a-002712cbac5b |
| Pogo Technologies, Inc. | Full Stack Engineer | 2 | ashbyhq | - | https://jobs.ashbyhq.com/joinpogo/264829f1-d5a5-4f82-b32a-a9d7e6e3a1cf |
| Vivid Seats | Software Engineer | 1 | greenhouse | - | https://job-boards.greenhouse.io/vividseatsllc/jobs/5167447007?gh_jid=5167447007 |
| Paxos | Security Operations Engineer | 1 | ashbyhq | - | https://jobs.ashbyhq.com/paxos/f0eece71-5927-4f49-bed2-9932af8edd9f |

## Already handled this session (do NOT redo)
- APPLIED: Cerebras Systems (SWE Tools&Infra/DevOps, Toronto), Clera (AI & Backend Engineer)
- READY (long Greenhouse form, sponsors, complete next): Thinking Machines Lab (SWE Full Stack Tinker)
- CLOSED/dead: Capable Labs, PCMI, Procare, Cerebras new-grad #1
- US-auth-gated (queued for Harsh): Dutchie
- Already-applied earlier: Tiny Health, Certa, Fleetio