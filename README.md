# Follow the Rupee – Mumbai Monsoon Roads Management System

One app that shows where each ward's road repair money went, whether the repairs held, who is responsible, and where the next rupee should go.

> All data is synthetic and all contractors are fictional (Claude Impact Lab Mumbai dataset).

## Run

The dataset is not in this repo. Clone it next to this folder first:

```bash
git clone https://github.com/SumeetGDoshi/Claude-Impact-Labs-data-2.git   # sits beside this repo
```

API keys go in your environment or a local `.env` (git-ignored), never in the code.

```bash
pip install -r requirements.txt
python server.py              # RastaNidhi website + role dashboards → http://localhost:8000  (or run_web.bat)
streamlit run app.py          # analyst workbench (single user)          → http://localhost:8501  (or run.bat)
```

### RastaNidhi website (multi-user)

`server.py` (FastAPI) serves the RastaNidhi homepage (`web/index.html`, built from `../civicproof_homepage.html`) and a role-based dashboard (`web/dashboard.html`, `app.js`, `app.css`), written in plain HTML, CSS and JS. To sign in, pick a role and use OTP **1234**. Sessions are stored per browser tab, so you can open several roles side by side.

| Role | Sees | Can do |
|---|---|---|
| Admin | Everything | Change roles, lock roles, deactivate users, set the Claude API key, switch Claude on/off for everyone, view the activity log |
| Ward Officer | Own ward only (enforced by the server) | Money trail, ward audit flags, next-rupee planner, complaints, citizen reports, add notes for auditors |
| Contractor | Own jobs and flags, with peers anonymised | Submit evidence on flags, read their own scorecard |
| Auditor / Verifier | City-wide audit | Mark flags as Verified, Cleared or Escalated, with a note |
| Citizen | Their ward's spending summary | Ask the complaint bot, file a report (placed in a ward automatically) |
| Researcher | Analytics, scorecards, ML model card, social | Export CSV |

**Admin and officer features** (ported from `civicproof_admin.html` and `civicproof_officer.html`, computed live in `core/oversight.py`):
- **Alerts**: critical, warning and info alerts derived from the data and from user activity (e.g. reviews still pending, new citizen reports), with a count badge in the menu.
- **Data health**: missing ward or GPS, complaints linked after the fix, unlinked work orders, DLP tags to verify, and the channel, language and status mix.
- **Settings**: audit-sensitivity sliders that recount everything on the server, compared side by side with the live audit (1.4×, 14 days) and the prototype (1.5×, 7 days). Toggles are saved for everyone. *Auto-flag DLP* and *human review before citizens see a flag* change app behaviour. *Weekly digest* is saved but no email is sent.
- **Ward dashboard**: headroom banner, budget utilisation bar, spend vs complaints by month, rank against other wards, top unresolved complaints, contractor overbilling/DLP columns, and DLP recovery roads.
- **Recovery notices**: draft a notice for a flagged work order or a DLP road, copy it, and record it as issued. It then appears on the work order's trail for the auditor and contractor.
- **Roads & risk**: every road ranked by 25% accidents, 20% flood proximity, 15% traffic, 15% ambulance route, 15% re-open rate and 10% repair frequency, with the most durable method for each surface.
- **Complaints**: the raw complaint list with status filter. Ward Officers can update the status of citizen reports.
- **Floating assistant** (draggable): answers within the user's role, e.g. a Ward Officer only gets answers about their own ward. It uses rules, and Claude rephrases the answer when a key is set.
- **Export** button on every table and **count badges** in the sidebar.

**Auditor and Researcher features** (ported from `civicproof_auditor.html` and `civicproof_researcher.html`, computed in `core/research.py`):
- **Review queue** (Auditor, Admin): the list and the detail open side by side. Each flag can be Confirmed, Dismissed, Evidence requested or Escalated, with a reason. The next item opens automatically after each decision, and there are keyboard shortcuts (↑/↓, C, D, E, X). Decisions are saved on the server, not in the browser as in the prototype, so they appear on the work order's history, in the contractor's 🔔 badge and in the alerts.
- **Review dashboard**: counts and ₹ for each decision status, progress bar, flag types, top wards, contractors and reviewers.
- **Audit report**: only confirmed findings, grouped by contractor, with Copy and Download (.txt).
- **Season overview** (Researcher): a one-paragraph summary, spend vs complaints, and SLA vs re-open rate by month.
- **Ward comparisons**: population, flood risk, complaints per 1,000 residents, average days to fix, jobs per crew, SLA, re-open rate and money needing review.
- **Patterns & findings**: 10 findings computed live. The wording is generated from the numbers, so a finding never claims more than the data shows.
- **Report builder**: pick facts, edit the headline and byline, then copy or download the draft brief.

**Motion & photos**: page transitions, skeleton loaders, KPIs that count up, bars that grow in, click ripples, hover lift, pop-in popups, homepage scroll reveal, a slow zoom on the hero image, and OTP paste/backspace/shake. All of it turns off when the system "reduce motion" setting is on. City photos (Mumbai, plus Delhi, Kolkata, Bengaluru and Chennai) are stored in `web/img/`, downloaded from Wikimedia Commons with author and licence credited on the page. Sources are listed in `web/img/credits.json`.

Shared state (users, sessions, auditor decisions, evidence, citizen reports, recovery notices, settings, activity) is saved in `store.json`. Set `RUPEE_STORE=<path>` to use a different file. Delete that file to reset the demo. The API key is held in memory only.
To rebuild the homepage after editing the prototype, run `python tools/build_homepage.py`.

The app expects the dataset at `../Claude-Impact-Labs-data-2/data`. To use another location, set `RUPEE_DATA_DIR`.
To turn on the Claude features, paste an Anthropic API key in the sidebar or set `ANTHROPIC_API_KEY`. Every number is computed without Claude.
**Claude on/off**: in the website, an Admin can switch Claude off for every user (Settings → *Use Claude*, the toggle on Users & settings, or by clicking the 🟢/⚪ Claude chip in the header). In the Streamlit workbench, use the *Use Claude* toggle in the sidebar. When Claude is off, narratives and the assistant fall back to rule-based text and templates.

## Modules

| Module | What it does | Rubric |
|---|---|---|
| 🏠 City overview | Ward map, budget vs spend, audit totals | Demo |
| 💰 Ward money trail | Spend by contractor, method and month, plus spend on fixes that failed. Claude writes a one-page report in English, Marathi, Hindi or Hinglish | Hold to account |
| 🔍 Repair auditor | Rule-based flags with a one-line reason and evidence for each, CSV export, work order drill-down. Claude says what to check first | Audit accuracy 25% |
| 📋 Scorecards | Contractor and ward scorecards adjusted for context, A–E grades, citizen scorecard written by Claude | Fair accountability 20% |
| 🧭 Next-rupee planner | Ranks open issues by risk, picks the most durable repair method, fits the list to the ward budget, sends DLP roads back to the original contractor, flags chronic roads | Budget recommendation 20% |
| 🔗 Complaint linker | Geocoding (aliases including Devanagari, shortened names), category correction, de-duplication into issues, link to work orders, outcome of each issue | Connects the trail 15% |
| 💬 Mera Complaint | Citizen asks in any of the four languages. The app retrieves the data in code, then Claude answers in the citizen's language with the work order, contractor, cost, SLA and whether the fix held | Usable 10% |
| 📣 Social pulse | Classifies posts (forwards, sarcasm, thank-yous), places them, and finds online reports with no matching official complaint | Extra |

## Method notes

**Audit rules** (`core/audit.py`)
- `OVERBILLED`: cost is more than 1.4× the rate card. Normal jobs fall between 0.8× and 1.3×, and the data has a clean gap at 1.3–1.5×. The amount at risk is the excess over 1.3×.
- `DOUBLE_BILLED`: a work order with no linked complaint, on the same road and repair method as another work order within 14 days. All 45 unlinked work orders match this pattern.
- `DLP_PAID`: BMC paid for a repair on a road still under its Defect Liability Period. The full amount is recoverable.
- `SLA_FLAG_WRONG`: the recorded `sla_met` doesn't match the actual time from first complaint to completion.
- `SLA_MISSED` and `REOPENED`: performance flags, labelled with context (rain or NOC delays, heavy rain after the fix). These are not accusations.

**Fair scorecards** (`core/scorecard.py`): indirect standardisation. Each job's expected re-open and SLA-miss rates come from peer jobs with the same work type, the same low-lying ward band and the same rain conditions. Each contractor's actual results are compared with what was expected for their mix of jobs, and small samples are pulled toward "as expected".

**Category correction** (`core/linker.py`): the evidence order was measured against work-order work types on 4,948 linked complaints. Photo descriptions matched 100% of the time, the citizen's own category 83.5% and free-text keywords 78.5%. So the photo is trusted first, then the citizen's category, and the text is used only when the category is vague. This raises accuracy from 83.5% to 93.1%.

**Planner** (`core/planner.py`): the risk score runs from 0 to 100. It combines severity, flood hotspots and the ward's low-lying index, traffic, road-condition accidents (fatal ones weighted ×10), hospital and school access roads, citizen reports, how long the issue has been open, and tide. For high-risk spots it picks the repair method with the lowest failure rate. Elsewhere it picks the best cost per lasting fix.

**ML** (`core/ml.py`, shown on the ML model card for Admin and Researcher only; the next-rupee planner does **not** use it and is fully rule-based)
- *Failure model*: a logistic regression trained on 2,499 jobs, using only facts known when a job is assigned. 5-fold cross-validated AUC is 0.68, against 0.56 for a model that uses only the repair method, and the predicted rates are well calibrated. Shown for research only.
- *Demand model*: a Poisson model of new issues per ward per week, driven by rainfall, the heaviest day, big tides and how low-lying the ward is. Trained on June–August and tested on September, its error is 1.36 issues per ward-week against 2.37 for the ward-average baseline. Shown for research only.
- *Dropped*: a model predicting which road gets the next complaint did no better than each road's historical average, so the risk ranking stays rule-based.

**Claude** (`core/llm.py`): Claude only explains numbers computed in pandas. The system prompt requires evidence (work order IDs), context and no accusations. Model `claude-opus-5-5` with server-side refusal fallback.
