"""RastaNidhi web server: the homepage + role-based dashboards on top of the Follow-the-Rupee engine.

Run:  python server.py        → http://localhost:8000
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import audit, citizen, llm, mapdata, oversight, planner, rag_chatbot, research, scorecard, store, tracking
from core.data import CATEGORY_SEVERITY, inr
from core.engine import build

WEB = Path(__file__).parent / "web"
app = FastAPI(title="RastaNidhi API")
app.mount("/static", StaticFiles(directory=WEB), name="static")

ADMIN, WARD, CONTRACTOR, AUDITOR, CITIZEN, RESEARCHER = store.ROLES
ALL = set(store.ROLES)


# ------------------------------------------------------------------ helpers
def jsonable(o):
    if isinstance(o, pd.DataFrame):
        return json.loads(o.to_json(orient="records", date_format="iso"))
    if isinstance(o, pd.Series):
        return jsonable(o.to_dict())
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(o) or math.isinf(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return None if pd.isna(o) else o.isoformat()
    if o is pd.NaT:
        return None
    return o


def E() -> dict:
    return build()


def current_user(authorization: str | None = Header(default=None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    u = store.user_for(token)
    if not u:
        raise HTTPException(401, "Please sign in.")
    return u | {"_token": token}


def require(*roles):
    def dep(u: dict = Depends(current_user)) -> dict:
        if u["role"] not in roles:
            raise HTTPException(403, f"{u['role']} can't access this.")
        return u
    return dep


def scope_ward(u: dict, ward: str | None) -> str | None:
    """Ward Officers are locked to their own ward."""
    if u["role"] == WARD:
        if ward and ward != u["ward"]:
            raise HTTPException(403, f"You can only see ward {u['ward']}.")
        return u["ward"]
    return ward


def claude_on() -> bool:
    """Claude runs only when a key is set AND the admin switch is on."""
    return llm.has_credentials() and bool(store.get_settings().get("claude_enabled", True))


def claude_or_none(fn, *args) -> dict:
    if not llm.has_credentials():
        return {"text": None, "error": "Claude is off. An admin can add an Anthropic API key under Users & settings."}
    if not claude_on():
        return {"text": None, "error": "Claude has been switched off by an admin. All numbers still work without it."}
    return {"text": fn(*args)}


# ------------------------------------------------------------------ pages
@app.get("/")
def home():
    return FileResponse(WEB / "index.html")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(WEB / "img" / "bmc-favicon.png", media_type="image/png")


@app.get("/dashboard")
def dashboard():
    return FileResponse(WEB / "dashboard.html")


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    email: str
    role: str
    otp: str
    ward: str | None = None
    contractor_id: str | None = None


@app.post("/api/login")
def login(body: LoginIn):
    if "@" not in body.email:
        raise HTTPException(400, "Enter a valid email address.")
    try:
        return store.login(body.email.strip().lower(), body.role, body.otp, body.ward, body.contractor_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))


@app.post("/api/logout")
def logout(u: dict = Depends(current_user)):
    store.logout(u["_token"])
    return {"ok": True}


@app.get("/api/me")
def me(u: dict = Depends(current_user)):
    d = E()["d"]
    extra = {}
    if u.get("contractor_id"):
        extra["contractor_name"] = d.contractors.set_index("contractor_id").contractor_name.get(u["contractor_id"])
    if u.get("ward"):
        extra["ward_name"] = d.wards.set_index("ward_code").ward_name.get(u["ward"])
    return {k: v for k, v in u.items() if k != "_token"} | extra | {"claude": claude_on(),
                                                                    "claude_enabled": bool(store.get_settings().get("claude_enabled", True))}


@app.get("/api/options")
def options():
    d = E()["d"]
    return {"roles": store.ROLES,
            "wards": jsonable(d.wards[["ward_code", "ward_name"]]),
            "contractors": jsonable(d.contractors[["contractor_id", "contractor_name"]])}


# ------------------------------------------------------------------ public homepage numbers
@app.get("/api/public/stats")
def public_stats():
    e = E()
    d, flags, wsc, iss = e["d"], e["flags"], e["wsc"], e["issues"]
    wo = d.work_orders
    risk = audit.money_at_risk(flags)
    dlp = flags[flags.rule == "DLP_PAID"]
    worst = wsc.sort_values("money_at_risk_inr", ascending=False).iloc[0]
    cold = wo[wo.repair_method == "Cold mix patch"]
    return jsonable(dict(
        spend=inr(wo.cost_inr.sum()), complaints=f"{len(d.complaints):,}", wards=len(d.wards),
        at_risk=inr(risk.amount_at_risk_inr.sum()), at_risk_wos=len(risk),
        dlp_count=len(dlp), dlp_amount=inr(dlp.amount_at_risk_inr.sum()),
        reopen_rate=f"{(wo.reopened_within_30d == 'Y').mean():.0%}",
        never_fixed=int((iss.outcome == "Never fixed (open)").sum()), issues=len(iss),
        cold_mix_reopen=f"{(cold.reopened_within_30d == 'Y').mean():.0%}",
        double_billed=int((flags.rule == "DOUBLE_BILLED").sum()),
        worst_ward=worst.ward_code, worst_ward_risk=inr(worst.money_at_risk_inr),
        worst_ward_flags=int(((flags.ward_code == worst.ward_code) & (flags.category == "Suspicious billing")).sum()),
        work_orders=f"{len(wo):,}", hotspots=len(d.hotspots),
    ))


# ------------------------------------------------------------------ city overview
@app.get("/api/city")
def city(u: dict = Depends(require(ADMIN, AUDITOR, RESEARCHER))):
    e = E()
    d, flags, wsc = e["d"], e["flags"], e["wsc"]
    wo = d.work_orders
    risk = audit.money_at_risk(flags)
    summ = flags.groupby(["category", "rule"]).agg(work_orders=("work_order_id", "nunique"),
                                                   amount=("amount_at_risk_inr", "sum")).reset_index()
    summ["meaning"] = summ.rule.map(audit.RULES)
    return jsonable(dict(
        kpis=dict(spend=wo.cost_inr.sum(), budget=d.wards.monsoon_repair_budget_inr_2025.sum(), work_orders=len(wo),
                  sla_rate=(wo.sla_met == "Y").mean(), failed_spend=wo.loc[wo.reopened_within_30d == "Y", "cost_inr"].sum(),
                  reopen_rate=(wo.reopened_within_30d == "Y").mean(), at_risk=risk.amount_at_risk_inr.sum(),
                  at_risk_wos=len(risk), never_fixed=int((e["issues"].outcome == "Never fixed (open)").sum())),
        wards=wsc, audit_summary=summ, geo=d.wards_geo,
        trend=oversight.monthly_trend(d), flag_breakdown=oversight.flag_breakdown(flags, len(wo)),
        alerts=oversight.alerts(e, store.all_data())[:3],
        contractors=e["csc"][["contractor_name", "grade", "overall_score"]],
    ))


# ------------------------------------------------------------------ ward money trail
@app.get("/api/ward/{code:path}")
def ward(code: str, u: dict = Depends(current_user)):
    code = scope_ward(u, code)
    e = E()
    w = e["wsc"].set_index("ward_code")
    if code not in w.index:
        raise HTTPException(404, "Unknown ward")
    trail = scorecard.ward_money_trail(e["d"], code)
    out = dict(ward=jsonable(w.loc[code]) | {"ward_code": code},
               by_contractor=trail["by_contractor"], by_method=trail["by_method"], by_month=trail["by_month"])
    if u["role"] != CITIZEN:  # citizens see the summary, not every bill
        out["extras"] = oversight.ward_extras(e, code)
        out["work_orders"] = trail["work_orders"][["work_order_id", "completed_at", "road_name", "work_type", "repair_method",
                                                   "contractor_name", "cost_inr", "cost_ratio", "sla_met",
                                                   "reopened_within_30d", "engineer_remark"]]
    return jsonable(out)


# ------------------------------------------------------------------ audit
def _flags_view(u: dict, category: str | None, rule: str | None, ward: str | None, contractor: str | None) -> pd.DataFrame:
    f = E()["flags"]
    if u["role"] == CONTRACTOR:
        contractor = u["contractor_id"]
    ward = scope_ward(u, ward)
    if not store.get_settings()["auto_flag_dlp"]:  # admin setting
        f = f[f.rule != "DLP_PAID"]
    if category:
        f = f[f.category == category]
    if rule:
        f = f[f.rule == rule]
    if ward:
        f = f[f.ward_code == ward]
    if contractor:
        f = f[f.contractor_id == contractor]
    db = store.all_data()
    f = f.copy()
    f["review_status"] = f.work_order_id.map(lambda w: db["reviews"].get(w, [{}])[-1].get("status", "Pending"))
    f["evidence_count"] = f.work_order_id.map(lambda w: len(db["evidence"].get(w, [])))
    return f.sort_values("amount_at_risk_inr", ascending=False)


@app.get("/api/flags")
def flags(category: str | None = None, rule: str | None = None, ward: str | None = None, contractor: str | None = None,
          limit: int = 500, u: dict = Depends(require(ADMIN, AUDITOR, WARD, CONTRACTOR))):
    f = _flags_view(u, category, rule, ward, contractor)
    cols = ["work_order_id", "rule", "category", "severity", "ward_code", "road_name", "contractor_id", "contractor_name",
            "repair_method", "cost_inr", "amount_at_risk_inr", "reason", "evidence", "review_status", "evidence_count"]
    by_rule = f.groupby("rule").agg(flags=("work_order_id", "size"), amount=("amount_at_risk_inr", "sum")).reset_index()
    heat = f.pivot_table(index="contractor_name", columns="rule", values="work_order_id", aggfunc="count", fill_value=0)
    return jsonable(dict(total=len(f), work_orders=f.work_order_id.nunique(), amount=f.amount_at_risk_inr.sum(),
                         by_rule=by_rule, heat={"rows": list(heat.index), "cols": list(heat.columns),
                                                "values": heat.values.tolist()},
                         rows=f[cols].head(limit), rules=audit.RULES))


@app.get("/api/flags.csv")
def flags_csv(category: str | None = None, rule: str | None = None, ward: str | None = None,
              contractor: str | None = None, token: str = Query(...)):
    u = store.user_for(token)
    if not u or u["role"] not in (ADMIN, AUDITOR, WARD, CONTRACTOR, RESEARCHER):
        raise HTTPException(401)
    return PlainTextResponse(_flags_view(u, category, rule, ward, contractor).to_csv(index=False), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=audit_flags.csv"})


@app.get("/api/workorder/{wid}")
def workorder(wid: str, u: dict = Depends(require(ADMIN, AUDITOR, WARD, CONTRACTOR))):
    e = E()
    wo = e["d"].work_orders
    r = wo[wo.work_order_id == wid]
    if r.empty:
        raise HTTPException(404, "Unknown work order")
    r = r.iloc[0]
    if u["role"] == CONTRACTOR and r.contractor_id != u["contractor_id"]:
        raise HTTPException(403, "Not your work order.")
    scope_ward(u, r.ward_code)
    db = store.all_data()
    keep = ["work_order_id", "ward_code", "road_id", "road_name", "under_dlp", "last_resurfaced", "work_type", "repair_method",
            "contractor_name", "assigned_at", "completed_at", "area_sqm", "cost_inr", "expected_cost_inr", "cost_ratio",
            "sla_hours", "hours_to_fix", "sla_met", "reopened_within_30d", "engineer_remark", "linked_complaint_ids"]
    same = wo[wo.road_id == r.road_id][["work_order_id", "assigned_at", "repair_method", "contractor_name", "cost_inr",
                                        "linked_complaint_ids"]].sort_values("assigned_at")
    return jsonable(dict(wo=r[keep], flags=e["flags"][e["flags"].work_order_id == wid][["rule", "category", "reason"]],
                         same_road=same, reviews=db["reviews"].get(wid, []), evidence=db["evidence"].get(wid, [])))


class ReviewIn(BaseModel):
    status: str
    note: str = ""


@app.post("/api/workorder/{wid}/review")
def review(wid: str, body: ReviewIn, u: dict = Depends(require(ADMIN, AUDITOR))):
    if body.status not in set(research.STATUSES):
        raise HTTPException(400, "Unknown status")
    return store.add_review(wid, u["email"], body.status, body.note)


class NoteIn(BaseModel):
    note: str


@app.post("/api/workorder/{wid}/evidence")
def evidence(wid: str, body: NoteIn, u: dict = Depends(require(CONTRACTOR, WARD, ADMIN))):
    workorder(wid, u)  # permission check
    if not body.note.strip():
        raise HTTPException(400, "Write something first.")
    return store.add_evidence(wid, u["email"], u["role"], body.note.strip())


# ------------------------------------------------------------------ scorecards
@app.get("/api/scorecards")
def scorecards(u: dict = Depends(require(ADMIN, AUDITOR, RESEARCHER, CONTRACTOR))):
    e = E()
    cols = ["contractor_id", "grade", "overall_score", "contractor_name", "jobs", "spend_inr", "reopen_rate", "exp_reopen_rate",
            "durability_score", "sla_rate", "speed_score", "median_cost_ratio", "overbilled", "double_billed", "dlp_paid",
            "cost_score", "money_at_risk_inr", "reopens", "exp_reopens", "sla_misses", "exp_sla_misses", "billing_issue_rate"]
    c = e["csc"][cols]
    if u["role"] == CONTRACTOR:  # own card + anonymised peers
        c = c.copy()
        mask = c.contractor_id != u["contractor_id"]
        c.loc[mask, "contractor_name"] = [f"Peer {i + 1}" for i in range(mask.sum())]
        c.loc[mask, "contractor_id"] = None
    return jsonable(dict(contractors=c, wards=e["wsc"]))


@app.get("/api/contractor/jobs")
def contractor_jobs(u: dict = Depends(require(CONTRACTOR))):
    wo = E()["d"].work_orders
    mine = wo[wo.contractor_id == u["contractor_id"]].sort_values("completed_at", ascending=False)
    return jsonable(mine[["work_order_id", "ward_code", "road_name", "work_type", "repair_method", "completed_at", "area_sqm",
                          "cost_inr", "cost_ratio", "sla_hours", "sla_met", "reopened_within_30d", "engineer_remark"]])


# ------------------------------------------------------------------ planner (rule-based) + ML model card
@app.get("/api/planner/{code:path}")
def plan(code: str, budget: float | None = None, u: dict = Depends(require(ADMIN, WARD, RESEARCHER))):
    code = scope_ward(u, code)
    e = E()
    row = e["wsc"].set_index("ward_code").loc[code]
    remaining = float(row.remaining_budget_inr)
    if budget is None:
        budget = remaining if remaining > 0 else 500_000.0
    p = planner.allocate(e["ranked"], code, budget)
    cols = ["issue_id", "fits_budget", "risk_score", "locality", "category", "road_name", "repair_method", "cost_to_bmc_inr",
            "why", "reasons", "reports", "first_reported", "under_dlp"] + [f"f_{k}" for k in planner.WEIGHTS]
    return jsonable(dict(
        ward=code, budget=budget, remaining=remaining, weights=planner.WEIGHTS, plan=p[cols] if not p.empty else [],
        methods=e["methods"][["work_type", "repair_method", "jobs", "reopen_rate", "standard_cost_inr", "cost_per_lasting_fix"]],
        chronic=e["chronic"][e["chronic"].ward_code == code],
    ))


@app.get("/api/models")
def models(u: dict = Depends(require(ADMIN, RESEARCHER))):
    e = E()
    fm, dm = e["fm"], e["dm"]
    names = e["d"].contractors.set_index("contractor_id").contractor_name
    co = fm.coefs[fm.coefs.feature.str.startswith(("contractor_id", "repair_method"))].copy()
    co["feature"] = co.feature.map(lambda x: names.get(x.replace("contractor_id_", ""), x.replace("repair_method_", "")))
    return jsonable(dict(
        failure={k: v for k, v in fm.metrics.items() if k != "calibration"}, calibration=fm.metrics["calibration"],
        coefs=co.sort_values("coef"),
        demand={k: v for k, v in dm.metrics.items() if k != "backtest"}, backtest=dm.metrics["backtest"],
    ))


# ------------------------------------------------------------------ complaints / issues
@app.get("/api/issues")
def issues(outcome: str | None = None, ward: str | None = None, limit: int = 400,
           u: dict = Depends(require(ADMIN, AUDITOR, WARD, RESEARCHER))):
    e = E()
    ward = scope_ward(u, ward)
    iss = e["issues"]
    v = iss
    if outcome:
        v = v[v.outcome == outcome]
    if ward:
        v = v[v.ward_code == ward]
        iss = iss[iss.ward_code == ward]
    cl = e["clean"] if not ward else e["clean"][e["clean"].ward_clean == ward]
    lang = cl.groupby("language").agg(complaints=("complaint_id", "size"), recategorised=("category_changed", "sum")).reset_index()
    return jsonable(dict(quality=e["quality"], outcomes=iss.outcome.value_counts().to_dict(), languages=lang,
                         rows=v.sort_values("reports", ascending=False)[[
                             "issue_id", "ward_code", "locality", "category", "reports", "channels", "languages",
                             "first_reported", "work_order_id", "outcome"]].head(limit)))


@app.get("/api/issue/{iid}")
def issue(iid: str, u: dict = Depends(require(ADMIN, AUDITOR, WARD, RESEARCHER))):
    c = E()["clean"]
    rows = c[c.issue_id == iid]
    if rows.empty:
        raise HTTPException(404, "Unknown issue")
    scope_ward(u, rows.ward_clean.iloc[0])
    return jsonable(rows[["complaint_id", "received_at", "channel", "language", "category_reported", "category_clean",
                          "category_source", "description", "locality_text", "locality_clean", "status", "work_order_id"]])


# ------------------------------------------------------------------ social
@app.get("/api/social")
def social_(u: dict = Depends(require(ADMIN, RESEARCHER))):
    p = E()["posts"]
    bs = p[p.blind_spot].groupby(["ward_code", "locality", "issue_category"]).agg(
        posts=("post_id", "size"), engagement=("likes_or_forwards", "sum")).reset_index().sort_values("engagement", ascending=False)
    return jsonable(dict(n=len(p), located=p.locality.notna().mean(), blind_spots=int(p.blind_spot.sum()),
                         types=p.post_type.value_counts().to_dict(), top_blind=bs.head(15),
                         rows=p[["post_id", "posted_at", "source", "text", "post_type", "issue_category", "locality",
                                 "official_complaint_nearby", "blind_spot", "likes_or_forwards"]].head(400)))


# ------------------------------------------------------------------ citizen
class AskIn(BaseModel):
    q: str


@app.post("/api/citizen/ask")
def ask(body: AskIn, u: dict = Depends(current_user)):
    ctx = citizen.lookup(E(), body.q)
    if store.get_settings()["human_review_before_publish"] and u["role"] == CITIZEN:
        # citizens only hear about flags an auditor has verified
        reviews = store.all_data()["reviews"]
        wos = [c.get("work_order") for c in ctx.get("complaints", [])] + [i.get("work_order") for i in ctx.get("recent_issues", [])]
        for w in filter(None, wos):
            rv = reviews.get(w["work_order_id"], [])
            if not (rv and rv[-1]["status"].startswith("Verified")):
                w["audit_flags"] = []
    ans = llm.citizen_answer(body.q, jsonable(ctx)) if claude_on() else citizen.template(ctx)
    return jsonable({"answer": ans, "evidence": ctx, "by": "claude" if claude_on() else "template"})


class ReportIn(BaseModel):
    locality: str
    category: str
    description: str


@app.post("/api/citizen/report")
def report(body: ReportIn, u: dict = Depends(require(CITIZEN, ADMIN))):
    if body.category not in CATEGORY_SEVERITY:
        raise HTTPException(400, "Pick a category")
    if len(body.description.strip()) < 5:
        raise HTTPException(400, "Describe the problem in a few words.")
    from core import linker
    loc = linker.geocode_text(body.locality, E()["gazetteer"])
    extra = {"ward_code": loc.ward_code, "locality_matched": loc.locality} if loc is not None else {"ward_code": None}
    return store.add_report(u["email"], body.model_dump() | extra)


@app.get("/api/citizen/reports")
def my_reports(u: dict = Depends(current_user)):
    reps = store.all_data()["reports"]
    if u["role"] == CITIZEN:
        reps = [r for r in reps if r["by"] == u["email"]]
    elif u["role"] == WARD:
        reps = [r for r in reps if r.get("ward_code") == u["ward"]]
    elif u["role"] != ADMIN:
        raise HTTPException(403)
    return reps[::-1]


# ------------------------------------------------------------------ Claude narratives
@app.post("/api/claude/ward/{code:path}")
def claude_ward(code: str, lang: str = "English", u: dict = Depends(require(ADMIN, WARD, AUDITOR, RESEARCHER))):
    code = scope_ward(u, code)
    e = E()
    row = jsonable(e["wsc"].set_index("ward_code").loc[code]) | {"ward_code": code}
    trail = scorecard.ward_money_trail(e["d"], code)
    f = e["flags"]
    wf = f[(f.ward_code == code) & (f.category == "Suspicious billing")]
    top = e["ranked"][e["ranked"].ward_code == code]
    return claude_or_none(llm.ward_memo, row, {k: jsonable(v.head(15)) for k, v in trail.items() if k != "work_orders"},
                          jsonable(wf[["work_order_id", "rule", "reason", "amount_at_risk_inr"]].head(12)),
                          jsonable(top[["locality", "category", "road_name", "risk_score", "repair_method",
                                        "cost_to_bmc_inr", "reasons"]].head(6)), lang)


@app.post("/api/claude/contractor/{cid}")
def claude_contractor(cid: str, lang: str = "English", u: dict = Depends(require(ADMIN, AUDITOR, RESEARCHER, CONTRACTOR))):
    if u["role"] == CONTRACTOR:
        cid = u["contractor_id"]
    e = E()
    r = e["csc"][e["csc"].contractor_id == cid]
    if r.empty:
        raise HTTPException(404)
    f = e["flags"]
    ex = f[(f.contractor_id == cid) & (f.category == "Suspicious billing")]
    return claude_or_none(llm.contractor_card, jsonable(r.iloc[0]), jsonable(ex[["work_order_id", "rule", "reason"]].head(8)), lang)


@app.post("/api/claude/flags")
def claude_flags(category: str | None = None, rule: str | None = None, ward: str | None = None, contractor: str | None = None,
                 u: dict = Depends(require(ADMIN, AUDITOR, WARD))):
    f = _flags_view(u, category, rule, ward, contractor)
    return claude_or_none(llm.explain_flags, jsonable(f[["work_order_id", "rule", "ward_code", "contractor_name", "cost_inr",
                                                          "amount_at_risk_inr", "reason"]].head(25)))


@app.post("/api/claude/plan/{code:path}")
def claude_plan(code: str, budget: float | None = None, lang: str = "English", u: dict = Depends(require(ADMIN, WARD, RESEARCHER))):
    p = plan(code, budget, u)
    rows = [{k: r.get(k) for k in ("fits_budget", "risk_score", "locality", "category", "road_name", "repair_method",
                                   "cost_to_bmc_inr", "why", "reasons")} for r in p["plan"][:12]]
    return claude_or_none(llm.plan_explainer, p["ward"], p["budget"], rows, p["chronic"][:5], lang)



# ------------------------------------------------------------------ auditor (ported from civicproof_auditor.html)
@app.get("/api/review/queue")
def review_queue(status: str | None = None, rule: str | None = None, ward: str | None = None, q: str | None = None,
                 u: dict = Depends(require(ADMIN, AUDITOR))):
    rows = research.review_queue(E(), store.all_data())
    if not store.get_settings()["auto_flag_dlp"]:
        rows = rows[rows.rules.map(lambda r: r != ["DLP_PAID"])]
    counts = rows.status.value_counts().to_dict()
    if status:
        rows = rows[rows.status == status]
    if rule:
        rows = rows[rows.rules.map(lambda r: rule in r)]
    if ward:
        rows = rows[rows.ward_code == ward]
    if q:
        ql = q.lower()
        rows = rows[rows.work_order_id.str.lower().str.contains(ql) | rows.contractor_name.str.lower().str.contains(ql)
                    | rows.road_name.str.lower().str.contains(ql)]
    return jsonable({"counts": counts, "statuses": research.STATUSES, "total": len(rows), "rows": rows.head(400)})


@app.get("/api/review/summary")
def review_summary(u: dict = Depends(require(ADMIN, AUDITOR))):
    return jsonable(research.review_summary(E(), store.all_data()))


@app.get("/api/review/report")
def review_report(u: dict = Depends(require(ADMIN, AUDITOR))):
    rep = research.audit_report(E(), store.all_data())
    return jsonable(rep | {"text": research.report_text(rep)})


# ------------------------------------------------------------------ researcher (ported from civicproof_researcher.html)
@app.get("/api/research/season")
def research_season(u: dict = Depends(require(ADMIN, RESEARCHER, AUDITOR))):
    return jsonable(research.season(E()))


@app.get("/api/research/wards")
def research_wards(u: dict = Depends(require(ADMIN, RESEARCHER))):
    return jsonable(research.ward_compare(E()))


@app.get("/api/research/findings")
def research_findings(u: dict = Depends(require(ADMIN, RESEARCHER))):
    return jsonable(research.findings(E()))


@app.get("/api/research/snippets")
def research_snippets(u: dict = Depends(require(ADMIN, RESEARCHER))):
    return jsonable(research.brief_snippets(E()))



# ------------------------------------------------------------------ simple SVG ward map (all roles)
@app.get("/api/wardmap")
def wardmap(u: dict = Depends(current_user)):
    """Ward polygons + per-ward metrics + flood hotspots + top open issues, small enough to draw instantly.
    Ward Officers get numbers for their own ward only; other wards come back as outlines."""
    e = E()
    d = e["d"]
    cols = ["ward_code", "ward_name", "zone", "population_est", "low_lying_index", "monsoon_repair_budget_inr_2025", "spend_inr",
            "budget_used_pct", "remaining_budget_inr", "failed_fix_spend_inr", "money_at_risk_inr", "sla_rate", "reopen_rate",
            "open_complaints", "complaints", "jobs", "top_contractor", "engineering_crews"]
    w = e["wsc"][cols].copy()
    if u["role"] == WARD:
        w.loc[w.ward_code != u["ward"], cols[3:]] = None
    if u["role"] == CITIZEN:   # citizens see the public summary, not audit amounts
        w["money_at_risk_inr"] = None
    mids = d.roads.set_index("road_id")[["mid_lat", "mid_lon"]]
    ranked = e["ranked"]
    if u["role"] == WARD:
        ranked = ranked[ranked.ward_code == u["ward"]]
    issues = [] if u["role"] == CITIZEN else [
        {"rank": i, "ward": r.ward_code, "lat": float(mids.at[r.road_id, "mid_lat"]), "lon": float(mids.at[r.road_id, "mid_lon"]),
         "category": r.category, "locality": r.locality, "risk": float(r.risk_score), "road": r.road_name}
        for i, r in enumerate(ranked.head(40).itertuples(), 1) if r.road_id in mids.index]
    hs = d.hotspots[["name", "ward_code", "lat", "lon", "flood_threshold_mm_per_day"]].rename(columns={"flood_threshold_mm_per_day": "threshold"})
    return jsonable({"geo": d.wards_geo, "wards": w, "hotspots": hs, "issues": issues, "my_ward": u.get("ward")})

# ------------------------------------------------------------------ interactive ward map
@app.get("/api/map")
def map_(ward: str | None = None, u: dict = Depends(require(ADMIN, AUDITOR, RESEARCHER, WARD))):
    ward = scope_ward(u, ward)  # Ward Officers only ever get their own ward
    return jsonable(mapdata.map_payload(E(), store.all_data(), ward))


class PinIn(BaseModel):
    lat: float
    lon: float
    title: str
    note: str = ""
    kind: str = "note"


@app.post("/api/pins")
def add_pin(body: PinIn, u: dict = Depends(require(ADMIN, AUDITOR, RESEARCHER, WARD))):
    if not (18.8 < body.lat < 19.35 and 72.7 < body.lon < 73.1):
        raise HTTPException(400, "Pins must be inside Mumbai.")
    if not body.title.strip():
        raise HTTPException(400, "Give the pin a title.")
    if body.kind not in {"note", "inspection", "hazard", "recovery"}:
        raise HTTPException(400, "Unknown pin type")
    from shapely.geometry import Point, shape
    ward = next((f["properties"]["ward_code"] for f in E()["d"].wards_geo["features"]
                 if shape(f["geometry"]).contains(Point(body.lon, body.lat))), None)
    if u["role"] == WARD and ward != u["ward"]:
        raise HTTPException(403, f"You can only pin inside ward {u['ward']}.")
    return store.add_pin(u["email"], u["role"], body.model_dump() | {"title": body.title.strip()[:80], "note": body.note.strip()[:400], "ward": ward})


@app.delete("/api/pins/{pin_id}")
def del_pin(pin_id: str, u: dict = Depends(require(ADMIN, AUDITOR, RESEARCHER, WARD))):
    try:
        return {"ok": store.delete_pin(u["email"], u["role"], pin_id)}
    except KeyError:
        raise HTTPException(404, "No such pin")
    except PermissionError as e:
        raise HTTPException(403, str(e))

# ------------------------------------------------------------------ oversight (ported from admin/officer prototypes)
@app.get("/api/alerts")
def alerts_(u: dict = Depends(require(ADMIN, AUDITOR, RESEARCHER))):
    return jsonable(oversight.alerts(E(), store.all_data()))


@app.get("/api/datahealth")
def datahealth(u: dict = Depends(require(ADMIN, RESEARCHER, AUDITOR))):
    e = E()
    return jsonable(oversight.data_health(e["d"]) | {"trend": oversight.monthly_trend(e["d"])})


@app.get("/api/sensitivity")
def sensitivity(ratio: float = 1.5, dup_days: int = 7, u: dict = Depends(require(ADMIN, AUDITOR, RESEARCHER))):
    d = E()["d"]
    return jsonable({"now": oversight.sensitivity(d, ratio, dup_days),
                     "app_default": oversight.sensitivity(d, audit.OVERBILL_RATIO, audit.DOUBLE_BILL_WINDOW_DAYS),
                     "prototype_default": oversight.sensitivity(d, 1.5, 7)})


@app.get("/api/roads")
def roads(ward: str | None = None, u: dict = Depends(require(ADMIN, WARD, RESEARCHER, AUDITOR))):
    ward = scope_ward(u, ward)
    return jsonable({"weights": oversight.RISK_WEIGHTS, "rows": oversight.road_risk(E(), ward).head(300)})


@app.get("/api/complaints")
def complaints(ward: str | None = None, status: str | None = None, q: str | None = None, limit: int = 400,
               u: dict = Depends(require(ADMIN, WARD, AUDITOR, RESEARCHER))):
    ward = scope_ward(u, ward)
    c = E()["clean"].drop_duplicates("complaint_id")
    if ward:
        c = c[c.ward_clean == ward]
    if status:
        c = c[c.status == status]
    if q:
        ql = q.lower()
        c = c[c.locality_text.str.lower().str.contains(ql, na=False) | c.category_clean.str.lower().str.contains(ql, na=False)
              | c.complaint_id.str.lower().str.contains(ql, na=False)]
    cols = ["complaint_id", "received_at", "channel", "language", "category_reported", "category_clean", "locality_text",
            "ward_clean", "upvotes", "status", "issue_id", "work_order_id", "description"]
    return jsonable({"total": len(c), "statuses": c.status.value_counts().to_dict(),
                     "rows": c.sort_values("received_at", ascending=False)[cols].head(limit)})


@app.post("/api/notice/workorder/{wid}")
def notice_wo(wid: str, issue: bool = False, u: dict = Depends(require(ADMIN, WARD, AUDITOR))):
    workorder(wid, u)  # permission + existence check
    text = oversight.notice_for_work_order(E(), wid, u["email"])
    return {"text": text, "issued": store.add_notice(wid, "work_order", u["email"], text) if issue else None}


@app.post("/api/notice/road/{road_id}")
def notice_road(road_id: str, issue: bool = False, u: dict = Depends(require(ADMIN, WARD, AUDITOR))):
    rd = E()["d"].roads
    r = rd[rd.road_id == road_id]
    if r.empty:
        raise HTTPException(404, "Unknown road")
    scope_ward(u, r.ward_code.iloc[0])
    text = oversight.notice_for_road(E(), road_id, u["email"])
    return {"text": text, "issued": store.add_notice(road_id, "road", u["email"], text) if issue else None}


@app.get("/api/notices")
def notices(u: dict = Depends(require(ADMIN, WARD, AUDITOR))):
    items = store.all_data().get("notices", [])
    if u["role"] == WARD:
        wo = E()["d"].work_orders.set_index("work_order_id").ward_code
        rd = E()["d"].roads.set_index("road_id").ward_code
        items = [n for n in items if (wo.get(n["target"]) or rd.get(n["target"])) == u["ward"]]
    return items[::-1]


class StatusIn(BaseModel):
    status: str
    work_order_id: str | None = None
    note: str = ""


@app.post("/api/citizen/reports/{rid}/status")
def report_status(rid: str, body: StatusIn, u: dict = Depends(require(WARD, ADMIN, AUDITOR))):
    """REQUIREMENTS §7.4: Open -> In Progress -> Work order linked -> Resolved -> Closed (or Rejected)."""
    status = tracking.norm_status(body.status)
    if status not in set(tracking.LIFECYCLE) | {"Rejected"}:
        raise HTTPException(400, "Unknown status")
    rep = next((r for r in store.all_data()["reports"] if r["report_id"] == rid), None)
    if not rep:
        raise HTTPException(404)
    if u["role"] == WARD and rep.get("ward_code") != u["ward"]:
        raise HTTPException(403, "Not your ward's report.")
    wid = (body.work_order_id or "").strip().upper() or None
    if status == "Work order linked":
        wid = wid or rep.get("work_order_id")
        if not wid:
            raise HTTPException(400, "Give the work order ID to link (e.g. WO25-00012).")
        wo = E()["d"].work_orders
        row = wo[wo.work_order_id == wid]
        if row.empty:
            raise HTTPException(404, f"No work order {wid}")
        if rep.get("ward_code") and row.ward_code.iloc[0] != rep["ward_code"]:
            raise HTTPException(400, f"{wid} is in ward {row.ward_code.iloc[0]}, not {rep['ward_code']}.")
    return store.update_report(u["email"], rid, status, wid, body.note.strip()[:300])


# ------------------------------------------------------------------ tracking (REQUIREMENTS.md section 7)
@app.get("/api/track")
def track_(q: str, u: dict = Depends(current_user)):
    db = store.all_data()
    q = q.strip()
    if q.upper().startswith("CP-") and u["role"] == CITIZEN:
        rep = next((r for r in db.get("reports", []) if r["report_id"] == q.upper()), None)
        if rep and rep["by"] != u["email"]:
            raise HTTPException(403, "You can only track your own RastaNidhi reports (dataset complaints BMC25-... are public).")
    if q.upper().startswith("WO") and u["role"] == CONTRACTOR:
        wo = E()["d"].work_orders
        row = wo[wo.work_order_id == q.upper()]
        if len(row) and row.contractor_id.iloc[0] != u["contractor_id"]:
            raise HTTPException(403, "Not your work order.")
    t = tracking.track(E(), db, q, u["role"])
    if not t:
        raise HTTPException(404, "Nothing found. Use an ID like BMC25-000005, WO25-00012, CP-00001 or ISS-00012.")
    if u["role"] == WARD and t.get("ward") and t["ward"] != u["ward"]:
        raise HTTPException(403, f"That is in ward {t['ward']}; you can track ward {u['ward']} only.")
    return jsonable(t)


@app.get("/api/track/suggest")
def track_suggest(u: dict = Depends(current_user)):
    """Starting points for the tracker, per role."""
    e, db = E(), store.all_data()
    wo = e["d"].work_orders
    mine = [r for r in db.get("reports", []) if u["role"] != CITIZEN or r["by"] == u["email"]]
    if u["role"] == WARD:
        mine = [r for r in mine if r.get("ward_code") == u["ward"]]
        wo = wo[wo.ward_code == u["ward"]]
    if u["role"] == CONTRACTOR:
        wo = wo[wo.contractor_id == u["contractor_id"]]
        mine = []
    recent = wo.sort_values("completed_at", ascending=False).head(6)
    c = e["clean"]
    if u["role"] == WARD:
        c = c[c.ward_clean == u["ward"]]
    open_c = c[c.status.isin(["Open", "In Progress"])].drop_duplicates("complaint_id").sort_values("upvotes", ascending=False).head(4)
    return jsonable({
        "reports": [{"id": r["report_id"], "label": f"{r['category']} · {r.get('locality_matched') or r['locality']}",
                     "status": tracking.norm_status(r["status"])} for r in mine[::-1][:8]],
        "work_orders": [{"id": r.work_order_id, "label": f"{r.work_type} · {r.road_name}"} for r in recent.itertuples()],
        "complaints": [] if u["role"] == CONTRACTOR else
        [{"id": r.complaint_id, "label": f"{r.category_clean} · {r.locality_clean}"} for r in open_c.itertuples()]
        + ([] if u["role"] == WARD else [{"id": "BMC25-000005", "label": "Example: resolved manhole complaint"}]),
    })


@app.get("/api/projects")
def projects_(u: dict = Depends(current_user)):
    ps = tracking.projects(E(), store.all_data())
    if u["role"] == WARD:
        ps = [p for p in ps if p["ward_code"] == u["ward"]]
    if u["role"] == CITIZEN:   # public view: no audit internals
        ps = [{k: v for k, v in p.items() if k not in {"flags_pending_review", "created_by", "submissions_pending"}} for p in ps]
    return jsonable(ps)


@app.get("/api/projects/{pid}")
def project_(pid: str, u: dict = Depends(current_user)):
    d = tracking.project_detail(E(), store.all_data(), pid)
    if not d:
        raise HTTPException(404, "No such project")
    if u["role"] == WARD:
        scope_ward(u, d["project"]["ward_code"])
    if u["role"] == CITIZEN:
        d["project"] = {k: v for k, v in d["project"].items() if k not in {"flags_pending_review", "created_by", "submissions_pending"}}
    return jsonable(d)


class ProjectIn(BaseModel):
    ward_code: str
    season: str = tracking.SEASON
    allocated_inr: float
    notes: str = ""
    status: str = "active"


@app.post("/api/projects")
def create_project(body: ProjectIn, u: dict = Depends(require(ADMIN))):
    if body.ward_code not in set(E()["d"].wards.ward_code):
        raise HTTPException(400, "Unknown ward")
    if body.allocated_inr <= 0:
        raise HTTPException(400, "Allocation must be more than zero")
    return store.upsert_project(u["email"], body.model_dump() | {"notes": body.notes.strip()[:300],
                                                                 "season": body.season.strip()[:40] or tracking.SEASON})


class ProjectPatch(BaseModel):
    allocated_inr: float | None = None
    status: str | None = None
    notes: str | None = None


@app.patch("/api/projects/{pid}")
def patch_project(pid: str, body: ProjectPatch, u: dict = Depends(require(ADMIN))):
    cur = next((p for p in tracking.projects(E(), store.all_data()) if p["id"] == pid), None)
    if not cur:
        raise HTTPException(404, "No such project")
    if body.status and body.status not in {"active", "closed"}:
        raise HTTPException(400, "Status must be active or closed")
    if body.allocated_inr is not None and body.allocated_inr <= 0:
        raise HTTPException(400, "Allocation must be more than zero")
    base = {k: cur[k] for k in ("id", "ward_code", "season", "allocated_inr", "notes", "status", "created_by", "created_at")}
    return store.upsert_project(u["email"], base | {k: v for k, v in body.model_dump().items() if v is not None})


class SubmissionIn(BaseModel):
    work_order_id: str
    status: str
    note: str


@app.post("/api/work-submissions")
def submit_work(body: SubmissionIn, u: dict = Depends(require(CONTRACTOR))):
    wo = E()["d"].work_orders
    row = wo[wo.work_order_id == body.work_order_id.strip().upper()]
    if row.empty or row.contractor_id.iloc[0] != u["contractor_id"]:
        raise HTTPException(403, "You can only update your own work orders.")
    if body.status not in {"In progress", "Completed – awaiting sign-off"}:
        raise HTTPException(400, "Unknown status")
    if len(body.note.strip()) < 5:
        raise HTTPException(400, "Describe the work in a few words.")
    return store.add_submission(u["email"], {"work_order_id": row.work_order_id.iloc[0], "ward_code": row.ward_code.iloc[0],
                                             "contractor_id": u["contractor_id"], "status": body.status, "note": body.note.strip()[:400]})


@app.get("/api/work-submissions")
def list_submissions(pending: bool = False, u: dict = Depends(require(CONTRACTOR, WARD, ADMIN, AUDITOR))):
    subs = store.all_data().get("submissions", [])
    if u["role"] == WARD:
        subs = [s for s in subs if s["ward_code"] == u["ward"]]
    if u["role"] == CONTRACTOR:
        subs = [s for s in subs if s["contractor_id"] == u["contractor_id"]]
    if pending:
        subs = [s for s in subs if not s.get("review")]
    wo = E()["d"].work_orders.set_index("work_order_id")
    return jsonable([s | {"road": wo.road_name.get(s["work_order_id"]), "method": wo.repair_method.get(s["work_order_id"]),
                          "contractor": wo.contractor_name.get(s["work_order_id"])} for s in subs[::-1]])


class ReviewSubIn(BaseModel):
    decision: str
    note: str = ""


@app.patch("/api/work-submissions/{sid}")
def review_sub(sid: str, body: ReviewSubIn, u: dict = Depends(require(WARD, ADMIN))):
    if body.decision not in {"Approved", "Sent back"}:
        raise HTTPException(400, "Decision must be Approved or Sent back")
    s = next((x for x in store.all_data().get("submissions", []) if x["id"] == sid), None)
    if not s:
        raise HTTPException(404)
    if u["role"] == WARD and s["ward_code"] != u["ward"]:
        raise HTTPException(403, "Not your ward.")
    return store.review_submission(u["email"], sid, body.decision, body.note.strip()[:300])


@app.post("/api/assistant")
def assistant(body: AskIn, u: dict = Depends(require(ADMIN, WARD, CONTRACTOR, AUDITOR, RESEARCHER))):
    text, ctx = oversight.assistant(E(), u, body.q)
    if claude_on():
        sys_ = llm.FAIRNESS + (f" You are the RastaNidhi assistant for a {u['role']}. Answer the question in at most 80 words using "
                               "ONLY the FACTS line (computed by the platform). If the facts don't answer it, say what you can answer.")
        text = llm.ask(sys_, f"QUESTION: {body.q}\nFACTS: {text}\nSCOPE: {jsonable(ctx)}", effort="low", max_tokens=2000)
    return {"answer": text, "by": "claude" if claude_on() else "rules"}


@app.get("/api/badges")
def badges(u: dict = Depends(current_user)):
    """Small counts for the sidebar menu."""
    e = E()
    db = store.all_data()
    out = {}
    if u["role"] in (ADMIN, AUDITOR, RESEARCHER):
        out["alerts"] = sum(a["severity"] == "critical" for a in oversight.alerts(e, db))
    if u["role"] in (ADMIN, AUDITOR):
        sus = set(e["flags"][e["flags"].category == "Suspicious billing"].work_order_id)
        out["audit"] = len([w for w in sus if not db["reviews"].get(w) or db["reviews"][w][-1]["status"] == "Pending"])
    if u["role"] == WARD:
        f = e["flags"]
        out["audit"] = int(f[(f.ward_code == u["ward"]) & (f.category == "Suspicious billing")].work_order_id.nunique())
        out["reports"] = sum(r.get("ward_code") == u["ward"] and tracking.norm_status(r.get("status", "")) == "Open" for r in db["reports"])
        out["complaints"] = int(((e["d"].complaints.ward_code == u["ward"]) & e["d"].complaints.status.isin(oversight.OPEN)).sum())
    subs = db.get("submissions", [])
    if u["role"] == WARD:
        out["submissions"] = sum(1 for x in subs if x["ward_code"] == u["ward"] and not x.get("review"))
    if u["role"] == ADMIN:
        out["submissions"] = sum(1 for x in subs if not x.get("review"))
    if u["role"] == CONTRACTOR:
        out["jobs"] = sum(1 for x in subs if x["contractor_id"] == u["contractor_id"] and x.get("review") == "Sent back")
    if u["role"] == ADMIN:
        out["reports"] = sum(tracking.norm_status(r.get("status", "")) == "Open" for r in db["reports"])
        out["wards"] = int((e["wsc"].budget_used_pct > 100).sum())
    if u["role"] == CONTRACTOR:  # what the contractor must act on: evidence requests from auditors
        q = research.review_queue(e, db)
        out["audit"] = int(((q.contractor_id == u["contractor_id"]) & (q.status == "Evidence requested")).sum())
    if u["role"] in (ADMIN, AUDITOR):
        out["queue"] = out.get("audit", 0)
    return out


@app.get("/api/admin/settings")
def get_settings(u: dict = Depends(require(ADMIN))):
    return store.get_settings()


@app.post("/api/admin/settings")
def set_settings(body: dict, u: dict = Depends(require(ADMIN))):
    return store.set_settings(u["email"], body)


# ------------------------------------------------------------------ admin
@app.get("/api/admin/users")
def users(u: dict = Depends(require(ADMIN))):
    db = store.all_data()
    active = {}
    for e in db["sessions"].values():
        active[e] = active.get(e, 0) + 1
    rows = [x | {"sessions": active.get(x["email"], 0)} for x in db["users"].values()]
    return {"users": rows, "activity": db.get("activity", [])[::-1][:60],
            "counts": {"reviews": sum(len(v) for v in db["reviews"].values()),
                       "evidence": sum(len(v) for v in db["evidence"].values()), "reports": len(db["reports"])},
            "claude": claude_on(), "has_key": llm.has_credentials(),
            "claude_enabled": bool(store.get_settings().get("claude_enabled", True)), "model": llm.MODEL}


class UserPatch(BaseModel):
    role: str | None = None
    ward: str | None = None
    contractor_id: str | None = None
    active: bool | None = None
    locked_role: bool | None = None


@app.patch("/api/admin/users/{email}")
def patch_user(email: str, body: UserPatch, u: dict = Depends(require(ADMIN))):
    try:
        return store.update_user(u["email"], email, {k: v for k, v in body.model_dump().items() if v is not None})
    except KeyError:
        raise HTTPException(404, "No such user")


class KeyIn(BaseModel):
    key: str


@app.post("/api/admin/apikey")
def set_key(body: KeyIn, u: dict = Depends(require(ADMIN))):
    """Kept in server memory only (never written to disk)."""
    os.environ["ANTHROPIC_API_KEY"] = body.key.strip()
    llm.reset_client()
    return {"claude": claude_on()}


# ------------------------------------------------------------------ Aamchi Road Audit AI (ChromaDB RAG + DuckDB SQL + Gemini)
ROADBOT_PERSONA = {CITIZEN: "Citizen", WARD: "Ward Officer", AUDITOR: "Judge / Auditor", RESEARCHER: "Judge / Auditor", ADMIN: "Corporator"}
ROADBOT_CHOICES = {ADMIN: list(rag_chatbot.ROLES), RESEARCHER: ["Judge / Auditor", "Corporator"], AUDITOR: ["Judge / Auditor"],
                   WARD: ["Ward Officer", "Corporator"], CITIZEN: ["Citizen"]}


class RoadbotIn(BaseModel):
    message: str
    persona: str | None = None


@app.get("/api/roadbot/status")
def roadbot_status(u: dict = Depends(require(ADMIN, WARD, AUDITOR, RESEARCHER, CITIZEN))):
    return rag_chatbot.status() | {"persona": ROADBOT_PERSONA[u["role"]], "choices": ROADBOT_CHOICES[u["role"]]}


@app.post("/api/roadbot")
def roadbot(body: RoadbotIn, u: dict = Depends(require(ADMIN, WARD, AUDITOR, RESEARCHER, CITIZEN))):
    msg = body.message.strip()
    if not msg:
        raise HTTPException(400, "Ask a question first.")
    persona = body.persona if body.persona in ROADBOT_CHOICES[u["role"]] else ROADBOT_PERSONA[u["role"]]
    scope = ""
    if u["role"] == WARD:
        scope = f"The user is the Ward Officer for ward {u['ward']}. Answer only about ward {u['ward']}; politely decline other wards."
    elif u["role"] == CITIZEN:
        scope = "The user is a citizen: share public repair facts only, not internal audit allegations or recovery amounts."
    return jsonable(rag_chatbot.ask_chatbot(msg[:1500], persona, scope))


@app.post("/api/admin/geminikey")
def set_gemini_key(body: KeyIn, u: dict = Depends(require(ADMIN))):
    """Kept in server memory only (never written to disk)."""
    rag_chatbot.set_api_key(body.key)
    return {"gemini_key": rag_chatbot.has_key()}


if __name__ == "__main__":
    import uvicorn
    print("Warming up the engine (≈15 s)…")
    build()
    rag_chatbot.warm_up_in_background()   # Road Audit AI index (~30 s) builds while the server is already serving
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
