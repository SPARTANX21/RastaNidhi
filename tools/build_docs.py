r"""Build the RastaNidhi product & technical documentation (.docx).

    python tools/capture_screens.py http://127.0.0.1:8077   # optional: refresh docs/screens/*.png first
    python tools/build_docs.py                               # writes ../RastaNidhi_Documentation.docx

Headline numbers are computed live from the dataset, so the document always matches the app.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT  # noqa: F401  (kept for easy landscape tweaks)
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCREENS = ROOT / "docs" / "screens"
LOGO = ROOT / "web" / "img" / "bmc-logo.png"
OUT = ROOT.parent / "RastaNidhi_Documentation.docx"

BLUE = RGBColor(0x1A, 0x56, 0xDB)
NAVY = RGBColor(0x0F, 0x17, 0x2A)
SLATE = RGBColor(0x64, 0x74, 0x8B)


# ------------------------------------------------------------------ live numbers
def live_stats() -> dict:
    from core import audit, planner
    from core.data import inr
    from core.engine import build
    from core.oversight import RISK_WEIGHTS

    E = build()
    d, f = E["d"], E["flags"]
    money = audit.money_at_risk(f)  # same de-duplicated figure the homepage shows
    return dict(
        spend=inr(d.work_orders.cost_inr.sum()), work_orders=f"{len(d.work_orders):,}", complaints=f"{len(d.complaints):,}",
        wards=len(d.wards), contractors=len(d.contractors), issues=f"{len(E['issues']):,}",
        flags=f.rule.value_counts().to_dict(), at_risk=inr(money.amount_at_risk_inr.sum()),
        at_risk_wos=len(money), reopen=f"{(d.work_orders.reopened_within_30d == 'Y').mean():.0%}",
        weights=planner.WEIGHTS, road_weights=RISK_WEIGHTS, cv_auc=E["fm"].metrics["cv_auc"],
        mae=E["dm"].metrics["mae_ward_week"], mae_base=E["dm"].metrics["mae_baseline"],
    )


# ------------------------------------------------------------------ docx helpers
def shade(cell, hex_fill: str) -> None:
    tc = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hex_fill)
    tc.append(sh)


def table(doc, header: list[str], rows: list[list], widths: list[float] | None = None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h); r.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF); r.font.size = Pt(9.5)
        shade(c, "1A56DB")
    for n, row in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v)); r.font.size = Pt(9.5)
            if i == 0:
                r.bold = True
            if n % 2:
                shade(cells[i], "F1F5F9")
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph()
    return t


def bullets(doc, items: list[str]) -> None:
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        if it.startswith("**") and "**" in it[2:]:
            head, rest = it[2:].split("**", 1)
            p.add_run(head).bold = True
            p.add_run(rest)
        else:
            p.add_run(it)


def para(doc, text: str, *, italic=False, color=None, size=None, bold=False, align=None):
    p = doc.add_paragraph()
    r = p.add_run(text); r.italic = italic; r.bold = bold
    if color is not None:
        r.font.color.rgb = color
    if size:
        r.font.size = Pt(size)
    if align is not None:
        p.alignment = align
    return p


def shot(doc, name: str, caption: str) -> None:
    f = SCREENS / f"{name}.png"
    if not f.exists():
        para(doc, f"[Screenshot missing: {name}.png. Run tools/capture_screens.py]", italic=True, color=SLATE)
        return
    from io import BytesIO

    from PIL import Image
    buf = BytesIO()  # embed as JPEG: same sharpness at print size, a fraction of the file size
    Image.open(f).convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
    buf.seek(0)
    doc.add_picture(buf, width=Inches(6.4))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    para(doc, caption, italic=True, color=SLATE, size=9, align=WD_ALIGN_PARAGRAPH.CENTER)


def page_number_footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("RastaNidhi · Product & technical documentation · Synthetic data · Page ")
    r.font.size = Pt(8); r.font.color.rgb = SLATE
    run = p.add_run(); run.font.size = Pt(8); run.font.color.rgb = SLATE
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = text
        run._r.append(el)


def style_doc(doc) -> None:
    st = doc.styles["Normal"]; st.font.name = "Segoe UI"; st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Segoe UI")
    for name, size, color in (("Heading 1", 18, BLUE), ("Heading 2", 13.5, NAVY), ("Heading 3", 11.5, NAVY), ("Title", 34, BLUE)):
        s = doc.styles[name]; s.font.name = "Segoe UI"; s.font.size = Pt(size); s.font.color.rgb = color; s.font.bold = True
        s.element.rPr.rFonts.set(qn("w:eastAsia"), "Segoe UI")
    for s in doc.sections:
        s.left_margin = s.right_margin = Inches(0.9)
        s.top_margin = s.bottom_margin = Inches(0.8)


# ------------------------------------------------------------------ document
def build_doc(S: dict) -> Document:
    doc = Document()
    style_doc(doc)
    page_number_footer(doc.sections[0])
    fl = S["flags"]

    # ---------- cover
    for _ in range(3):
        doc.add_paragraph()
    if LOGO.exists():
        doc.add_picture(str(LOGO), width=Inches(1.6)); doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    t = doc.add_paragraph("RastaNidhi", style="Title"); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para(doc, "Follow the money. Verify the work.", size=16, color=NAVY, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, "Mumbai monsoon roads: budget, repair and accountability platform", size=12, color=SLATE, align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_paragraph()
    para(doc, "Product & technical documentation", size=12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, f"Claude Impact Lab Mumbai · {date.today():%d %B %Y}", size=11, color=SLATE, align=WD_ALIGN_PARAGRAPH.CENTER)
    for _ in range(4):
        doc.add_paragraph()
    para(doc, "All data in this document and in the app is synthetic and all contractors are fictional. It is not BMC data and must not "
              "be used to judge any real person, contractor or department. RastaNidhi is an unofficial hackathon demo and is not "
              "affiliated with or endorsed by the Brihanmumbai Municipal Corporation.",
         italic=True, size=9, color=SLATE, align=WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_page_break()

    # ---------- contents
    doc.add_heading("Contents", 1)
    for line in ["1. Executive summary", "2. The problem", "3. How RastaNidhi works", "4. Users and roles",
                 "5. Role-by-role walkthrough", "6. Feature modules", "7. How the numbers are computed",
                 "8. Claude in RastaNidhi", "9. Admin controls and settings", "10. Architecture",
                 "11. Running the app", "12. Data, privacy and limitations", "13. Credits and licences"]:
        para(doc, line, size=11)
    doc.add_page_break()

    # ---------- 1
    doc.add_heading("1. Executive summary", 1)
    para(doc, "Every monsoon, Mumbai spends crores fixing the same roads. Citizens complain, repairs get logged and the potholes come back. "
              "RastaNidhi connects ward budgets, repair work orders, the rate card and citizen complaints into one traceable chain, so that "
              "anyone can answer three questions: where did the money go, did the fix last, and who is responsible. It then recommends "
              "where each ward's next rupee should go.")
    table(doc, ["Season at a glance (Jun–Oct 2025, synthetic)", "Value"], [
        ["Repair spend tracked", S["spend"]], ["Work orders", S["work_orders"]], ["Citizen complaints", S["complaints"]],
        ["Clean issues after de-duplication", S["issues"]], ["BMC wards covered", S["wards"]], ["Contractors (fictional)", S["contractors"]],
        ["Money needing review (over-billing, double billing, DLP)", f"{S['at_risk']} on {S['at_risk_wos']} work orders"],
        ["Repairs re-opened within 30 days", S["reopen"]],
    ], [4.2, 2.3])
    para(doc, "What makes it different", bold=True)
    bullets(doc, [
        "**One chain, end to end.** Budget → work order → contractor → bill vs rate card → did it hold → citizen feedback.",
        "**Six role-based views.** Admin, Ward Officer, Contractor, Auditor, Citizen and Researcher each see what they need, enforced by the server.",
        "**Evidence, not accusations.** Every flag carries a one-line reason and the work order IDs behind it. Auditors confirm or dismiss with a note.",
        "**Fair scorecards.** Contractors are compared against peers doing the same kind of work in the same conditions.",
        "**Works without AI.** Every number is computed in code. Claude only explains the numbers, and an admin can switch it off.",
    ])

    # ---------- 2
    doc.add_heading("2. The problem", 1)
    para(doc, "The challenge: build a tool that shows where each ward's road repair money went, whether the work held up, and where the next rupee should go.")
    table(doc, ["Step", "What it means", "Where in RastaNidhi"], [
        ["Connect", "Turn messy, duplicated, multilingual complaints into clean issues and link them to the work orders that fixed them (or didn't).", "Complaint linker, Track status"],
        ["Audit", "Check repairs against SLAs, the rate card and how long the fix held. Flag anything that doesn't add up.", "Repair auditor, Review queue, Audit report"],
        ["Hold to account", "A fair, plain-language scorecard for every contractor and every ward.", "Scorecards, Ward money trail"],
        ["Budget smarter", "Recommend where each ward should spend next, based on rain, flooding, tides, traffic, accidents, schools and hospitals.", "Next-rupee planner, Roads & risk"],
    ], [1.2, 3.4, 1.9])

    # ---------- 3
    doc.add_heading("3. How RastaNidhi works", 1)
    shot(doc, "home_hero", "Figure 1. RastaNidhi homepage. Live numbers come straight from the dataset.")
    bullets(doc, [
        "**1. Ingest.** Ward budgets, work orders, rate card, roads, complaints, social posts, rainfall, tides, traffic, accidents and facilities are loaded from CSV and GeoJSON.",
        "**2. Clean and link.** Complaints are geocoded (including Devanagari and short names), re-categorised, de-duplicated into issues and linked to work orders.",
        "**3. Audit.** Rule-based checks flag over-billing, double billing, repairs paid during the Defect Liability Period (DLP) and wrong SLA records.",
        "**4. Score.** Contractor and ward scorecards are adjusted for job mix, flood exposure and rain.",
        "**5. Plan.** Open issues are ranked by risk, the most durable method is chosen, and the list is fitted to the ward's remaining budget.",
        "**6. Act.** Auditors review flags, officers issue recovery notices, contractors respond with evidence, and citizens track their complaints.",
    ])

    # ---------- 4
    doc.add_heading("4. Users and roles", 1)
    para(doc, "Sign in by picking a role. The demo OTP is 1234. Sessions are per browser tab, so several roles can be open side by side. "
              "Scope is enforced on the server: a Ward Officer can only ever load their own ward.")
    table(doc, ["Role", "Sees", "Can do"], [
        ["Admin", "Everything", "Change and lock roles, deactivate users, set the Claude API key, switch Claude on/off, change platform settings, view the activity log"],
        ["Ward Officer", "Own ward only", "Money trail, ward flags, next-rupee planner, roads & risk, complaints and citizen reports, recovery notices, notes for auditors"],
        ["Contractor", "Own jobs and flags; peers anonymised", "Post progress updates, submit evidence on flags, read their own scorecard"],
        ["Auditor / Verifier", "City-wide audit", "Confirm, dismiss, request evidence or escalate each flag with a reason; build the audit report"],
        ["Citizen", "Their ward's spending", "Track a complaint, ask the help bot in four languages, report a problem"],
        ["Researcher", "Analytics, scorecards, findings, ML model card", "Compare wards, explore patterns, build a report, export CSV"],
    ], [1.3, 1.7, 3.5])

    # ---------- 5
    doc.add_heading("5. Role-by-role walkthrough", 1)
    walk = [
        ("5.1 Admin", "The control room for the whole platform.",
         [("admin_overview", "City overview: spend vs complaints, flag breakdown, contractor fair scores."),
          ("admin_users", "Users & roles: change roles, lock roles, deactivate accounts, switch Claude on or off."),
          ("admin_settings", "Settings: audit sensitivity what-if sliders and platform toggles.")],
         ["**City overview** with KPIs that count up, a ward map and the flag breakdown.",
          "**Alerts** (critical, warning, info) generated from the data and from user activity, with a count badge.",
          "**Users & roles**: every account, its sessions, role lock and active status, plus the recent activity log.",
          "**Settings**: move the over-billing threshold and duplicate window to see every count recomputed; platform toggles are saved for everyone.",
          "**Use Claude** switch: on the Users page, in Settings, or by clicking the Claude chip in the header."]),
        ("5.2 Ward Officer", "Everything about one ward, and where its next rupee should go.",
         [("officer_ward", "My ward dashboard: budget headroom, utilisation, spend vs complaints and rank against other wards."),
          ("officer_planner", "Budget & next rupee: open issues ranked by risk and fitted to the remaining budget."),
          ("officer_map", "Ward map: zoom, pan, drop pins and open details for issues, hotspots and work orders.")],
         ["**My ward dashboard**: headroom banner, budget bar, spend vs complaints by month, rank, top unresolved complaints.",
          "**Budget & next rupee**: change the budget and see which issues get funded; DLP roads go back to the original contractor at no cost.",
          "**Methods & chronic roads**: which repair method lasts, and which roads should be resurfaced instead of patched again.",
          "**Work orders & recovery**: draft a recovery notice for a flagged job, copy it and record it as issued.",
          "**Citizens**: complaints list and citizen reports, with status updates."]),
        ("5.3 Contractor", "A fair view of their own work.",
         [("contractor_jobs", "My jobs: every work order, billed amount, cost ratio, SLA and re-open status, with progress updates."),
          ("contractor_scorecard", "My scorecard: context-adjusted grade, with peers anonymised.")],
         ["**My jobs**: post a progress update on any job; it appears on the public tracking timeline.",
          "**My flags & evidence**: see each flag raised on their work and reply with evidence for the auditor.",
          "**My scorecard**: A–E grade adjusted for job mix and conditions, compared with anonymised peers."]),
        ("5.4 Auditor / Verifier", "Reviews every suspicious bill, quickly and with evidence.",
         [("auditor_review", "Review queue: list and detail side by side; decide with a reason and the next item opens."),
          ("auditor_dashboard", "Review dashboard: progress, decisions so far and flags by type.")],
         ["**Review queue**: Confirm, Dismiss, Request evidence or Escalate, each with a reason. Keyboard shortcuts: ↑/↓, C, D, E, X.",
          "**Decisions are saved on the server**, so they show on the work order history, the contractor's notifications and the alerts.",
          "**Audit report**: only confirmed findings, grouped by contractor; copy or download as text."]),
        ("5.5 Citizen", "Simple, multilingual access to what happened to their complaint.",
         [("citizen_track", "Track my complaint: enter a complaint, report or work order ID to see the full timeline."),
          ("citizen_ask", "Ask the help bot (Mera Complaint) in English, Hinglish, Marathi or Hindi."),
          ("citizen_report", "Report a problem: describe it in any language; it is placed in a ward automatically.")],
         ["**Track my complaint** from report to repair to the 30-day check on whether the fix held.",
          "**Ask the help bot**: answers come from the data (work order, contractor, cost, SLA, did it hold), in the citizen's language.",
          "**Report a problem** and follow its status. My ward's spending shows a plain-language summary of the ward's budget."]),
        ("5.6 Researcher", "Season-wide analysis for journalists, academics and civil society.",
         [("researcher_season", "Season overview: one-paragraph summary, spend vs complaints and SLA vs re-open rate."),
          ("researcher_findings", "Patterns & findings: ten findings computed live; the wording never claims more than the numbers show.")],
         ["**Ward comparisons**: complaints per 1,000 residents, days to fix, jobs per crew, SLA, re-open rate, money needing review.",
          "**Report builder**: pick facts, edit the headline and byline, copy or download the draft brief.",
          "**Export CSV** from every table."]),
    ]
    for title, intro, shots, items in walk:
        doc.add_heading(title, 2)
        para(doc, intro, italic=True, color=SLATE)
        bullets(doc, items)
        for name, cap in shots:
            shot(doc, name, cap)
        doc.add_paragraph()

    # ---------- 6
    doc.add_heading("6. Feature modules", 1)
    table(doc, ["Module", "What it does", "Used by"], [
        ["City overview & ward map", "Budget vs spend, audit totals, interactive Leaflet map with pins and ward details", "Admin, Officer, Auditor, Researcher"],
        ["Ward money trail", "Spend by contractor, method and month, plus spend on fixes that failed", "Admin, Officer, Citizen"],
        ["Repair auditor & review queue", "Rule-based flags with reasons and evidence; human decisions with notes", "Admin, Auditor, Officer, Contractor"],
        ["Scorecards", "Context-adjusted contractor and ward grades (A–E)", "Admin, Auditor, Contractor, Researcher"],
        ["Next-rupee planner", "Risk ranking, durable method, budget fit, DLP routing, chronic roads", "Admin, Officer, Researcher"],
        ["Roads & risk", "Every road ranked by accidents, flooding, traffic, critical access, re-opens and repair frequency", "Admin, Officer, Researcher"],
        ["Complaint linker", "Geocoding, category correction, de-duplication, link to work orders", "Admin, Officer, Auditor, Researcher"],
        ["Mera Complaint & Track status", "Citizen help bot in four languages and end-to-end tracking", "Citizen, Officer, Admin"],
        ["Social pulse", "Classifies posts and finds online reports with no official complaint", "Admin, Researcher"],
        ["Alerts & data health", "Live alerts; missing GPS/ward, late links, unlinked work orders, channel and language mix", "Admin, Auditor, Researcher"],
        ["Floating assistant", "Answers questions within the user's role scope", "All roles"],
    ], [1.7, 3.3, 1.5])

    # ---------- 7
    doc.add_heading("7. How the numbers are computed", 1)
    doc.add_heading("7.1 Audit rules", 2)
    table(doc, ["Rule", "Logic", "Flags"], [
        ["OVERBILLED", "Cost is more than 1.4× the rate card. Normal jobs are 0.8–1.3×; amount at risk is the excess over 1.3×.", fl.get("OVERBILLED", 0)],
        ["DOUBLE_BILLED", "No linked complaint, same road and method as another work order within 14 days.", fl.get("DOUBLE_BILLED", 0)],
        ["DLP_PAID", "BMC paid for a repair on a road still under its Defect Liability Period. Fully recoverable.", fl.get("DLP_PAID", 0)],
        ["SLA_FLAG_WRONG", "Recorded SLA result doesn't match the time from first complaint to completion.", fl.get("SLA_FLAG_WRONG", 0)],
        ["SLA_MISSED", "Performance flag with context (rain, NOC delays). Not an accusation.", fl.get("SLA_MISSED", 0)],
        ["REOPENED", "Fix failed within 30 days; labelled with heavy-rain context where relevant.", fl.get("REOPENED", 0)],
    ], [1.4, 4.3, 0.8])
    doc.add_heading("7.2 Fair scorecards", 2)
    para(doc, "Indirect standardisation: each job's expected re-open and SLA-miss rates come from peer jobs with the same work type, the same "
              "low-lying ward band and the same rain conditions. A contractor's actual results are compared with what was expected for their "
              "mix of jobs, and small samples are pulled toward \"as expected\" so a few unlucky jobs don't sink a grade.")
    doc.add_heading("7.3 Complaint linker", 2)
    para(doc, "Evidence order was measured against 4,948 linked complaints: photo descriptions matched the true work type 100% of the time, the "
              "citizen's own category 83.5% and free-text keywords 78.5%. RastaNidhi trusts the photo first, then the category, and uses the "
              "text only when the category is vague. This raises category accuracy from 83.5% to 93.1%.")
    doc.add_heading("7.4 Next-rupee planner (rule-based)", 2)
    para(doc, "Each open issue gets a risk score from 0 to 100. The planner then picks the repair method with the lowest failure rate for "
              "high-risk spots (best cost per lasting fix elsewhere), and funds issues in risk order until the ward budget runs out. Roads "
              "still under DLP are sent back to the original contractor at no cost.")
    table(doc, ["Risk factor", "Points (of 100)"], [[k.replace("_", " ").title(), v] for k, v in S["weights"].items()], [4.0, 2.0])
    doc.add_heading("7.5 Roads & risk", 2)
    table(doc, ["Road risk factor", "Weight %"], [[k.replace("_", " ").title(), v] for k, v in S["road_weights"].items()], [4.0, 2.0])
    doc.add_heading("7.6 ML model card (research only)", 2)
    para(doc, f"Two experimental models are shown to Admins and Researchers on the ML model card. They are not used by the planner. "
              f"A repair-failure logistic regression reaches a cross-validated AUC of {S['cv_auc']:.2f}. A Poisson rain-demand model "
              f"predicts new issues per ward-week with an error of {S['mae']:.2f}, against {S['mae_base']:.2f} for the ward-average baseline. "
              "A third model (where will the next complaint be) was dropped because it did no better than each road's history.")

    # ---------- 8
    doc.add_heading("8. Claude in RastaNidhi", 1)
    bullets(doc, [
        "**Explains, never computes.** All numbers come from pandas. Claude writes ward memos, citizen scorecards, flag explanations and plan summaries for corporators.",
        "**Four languages.** English, Marathi, Hindi and Hinglish.",
        "**Guardrails.** The system prompt requires evidence (work order IDs), context and no accusations.",
        "**On/off switch.** An Admin can switch Claude off for every user. When off, narratives and the assistant fall back to rule-based text and templates, and all numbers still work.",
        "**API key** is held in server memory only and never written to disk.",
    ])

    # ---------- 9
    doc.add_heading("9. Admin controls and settings", 1)
    table(doc, ["Setting", "Effect"], [
        ["Use Claude", "Turns all Claude writing on or off for every user."],
        ["Auto-flag DLP repairs", "Flags any paid work order on a road still under warranty. When off, DLP flags are hidden from audit queues."],
        ["Human review before citizens see a flag", "The citizen bot only mentions flags an auditor has verified."],
        ["Multilingual complaint parsing", "Parses and geocodes Hinglish, Marathi and Hindi descriptions."],
        ["Weekly ward officer digest", "Saved preference; email sending is not connected in this demo."],
        ["Audit sensitivity sliders", "What-if: recompute every count with a different over-billing threshold and duplicate window."],
    ], [2.4, 4.1])

    # ---------- 10
    doc.add_heading("10. Architecture", 1)
    table(doc, ["Layer", "Component", "Notes"], [
        ["Web front end", "web/index.html, dashboard.html, app.js, app.css, driftbar.css, map.js", "Plain HTML, CSS and JavaScript; Leaflet for the ward map"],
        ["API server", "server.py (FastAPI)", "Role-based endpoints; scope enforced per request"],
        ["Analytics engine", "core/ (audit, scorecard, planner, linker, oversight, research, social, ml)", "pandas; built once at start-up"],
        ["Claude layer", "core/llm.py", "Anthropic SDK; refusal fallback; switchable"],
        ["Shared state", "store.json", "Users, sessions, decisions, evidence, reports, notices, settings, activity"],
        ["Analyst workbench", "app.py (Streamlit)", "Single-user exploration of every module"],
        ["Data", "Claude-Impact-Labs-data-2/data", "Synthetic CSV and GeoJSON files"],
    ], [1.4, 2.8, 2.3])

    # ---------- 11
    doc.add_heading("11. Running the app", 1)
    for step in ["pip install -r requirements.txt",
                 "python server.py        →  http://localhost:8000  (or run_web.bat)",
                 "streamlit run app.py    →  http://localhost:8501  (or run.bat)",
                 "Sign in: pick a role, OTP 1234",
                 "Optional: set ANTHROPIC_API_KEY or paste a key as Admin to enable Claude",
                 "Reset the demo: delete store.json",
                 "After editing the homepage prototype: python tools/build_homepage.py"]:
        p = doc.add_paragraph(style="List Number"); r = p.add_run(step); r.font.name = "Consolas"; r.font.size = Pt(9.5)
    para(doc, "Restart server.py after any code change; the running process keeps the old code until restarted.", italic=True, color=SLATE)

    # ---------- 12
    doc.add_heading("12. Data, privacy and limitations", 1)
    bullets(doc, [
        "**Synthetic data.** Ward codes, locality names, arterial roads and hospitals are real names used for realism; every amount, date, record and boundary is made up.",
        "**Fictional contractors.** No real firm is assessed.",
        "**Demo authentication.** OTP 1234 for every user; not suitable for production.",
        "**Flags are leads, not verdicts.** Performance flags carry context; financial flags need human review before action.",
        "**Indicative estimates.** Resurfacing estimates assume ₹1,100/sqm and 3.5 m lanes and are not from the rate card.",
    ])

    # ---------- 13
    doc.add_heading("13. Credits and licences", 1)
    bullets(doc, [
        "**Dataset:** Claude Impact Lab Mumbai, \"Follow the Rupee: Mumbai Monsoon Roads\" (synthetic).",
        "**Logo:** Brihanmumbai Municipal Corporation emblem, supplied by the team for this demo. RastaNidhi is not affiliated with BMC.",
        "**Footer photo:** \"Mumbai 03-2016 46 evening at Marine Drive\" by A.Savin, Wikimedia Commons, Free Art License.",
        "**City photos:** Wikimedia Commons; authors and licences listed on the homepage and in web/img/credits.json.",
        "**Map:** Leaflet (BSD-2-Clause); ward polygons are approximate.",
    ])
    return doc


if __name__ == "__main__":
    stats = live_stats()
    build_doc(stats).save(OUT)
    print("wrote", OUT)
