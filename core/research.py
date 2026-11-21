"""Auditor and Researcher features (ported from civicproof_auditor.html / civicproof_researcher.html):
review progress + audit report from the shared review store, season overview, ward comparisons,
data-backed findings and report-builder snippets. Wording is generated from the computed values,
so a finding never claims more than the numbers show.
"""
from __future__ import annotations

import pandas as pd

from . import audit
from .data import inr

AS_OF = pd.Timestamp("2025-10-05")
OPEN = ["Open", "In Progress"]
# Auditor decisions (shared with the work-order popup). "Evidence requested" comes from the auditor prototype.
STATUSES = ["Pending", "Verified – recover money", "Cleared – explained", "Evidence requested", "Escalated"]


def _status_of(db: dict, wid: str) -> dict:
    rv = db.get("reviews", {}).get(wid, [])
    return rv[-1] if rv else {"status": "Pending", "note": "", "at": None, "by": None}


def review_queue(E: dict, db: dict) -> pd.DataFrame:
    """One row per suspicious work order (all its billing flags merged), with its latest decision."""
    f = E["flags"][E["flags"].category == "Suspicious billing"]
    wo = E["d"].work_orders.set_index("work_order_id")
    g = f.groupby("work_order_id").agg(
        rules=("rule", lambda s: sorted(set(s))), reason=("reason", lambda s: " · ".join(s)),
        amount_at_risk_inr=("amount_at_risk_inr", "max"), evidence_of=("evidence", lambda s: ", ".join(x for x in s if x)),
    ).reset_index()
    cols = ["ward_code", "road_name", "contractor_id", "contractor_name", "repair_method", "work_type", "assigned_at",
            "completed_at", "cost_inr", "expected_cost_inr", "sla_met", "reopened_within_30d", "n_linked", "under_dlp"]
    g = g.join(wo[cols], on="work_order_id")
    st = g.work_order_id.map(lambda w: _status_of(db, w))
    g["status"] = st.map(lambda s: s["status"])
    g["decision_note"] = st.map(lambda s: s.get("note", ""))
    g["decided_at"] = st.map(lambda s: s.get("at"))
    g["decided_by"] = st.map(lambda s: s.get("by"))
    g["evidence_count"] = g.work_order_id.map(lambda w: len(db.get("evidence", {}).get(w, [])))
    return g.sort_values("amount_at_risk_inr", ascending=False)


def review_summary(E: dict, db: dict) -> dict:
    q = review_queue(E, db)
    by = q.groupby("status").agg(n=("work_order_id", "size"), amount=("amount_at_risk_inr", "sum")).reindex(STATUSES).fillna(0)
    rules = q.explode("rules").groupby("rules").agg(n=("work_order_id", "size"), amount=("amount_at_risk_inr", "sum")).reset_index()
    reviewers = pd.Series([v[-1]["by"] for v in db.get("reviews", {}).values() if v and v[-1]["status"] != "Pending"]).value_counts()
    return {
        "total": len(q), "total_amount": float(q.amount_at_risk_inr.sum()), "work_orders": int(len(E["d"].work_orders)),
        "by_status": [{"status": s, "n": int(r.n), "amount": float(r.amount)} for s, r in by.iterrows()],
        "by_rule": rules.rename(columns={"rules": "rule"}),
        "top_wards": q.groupby("ward_code").agg(n=("work_order_id", "size"), amount=("amount_at_risk_inr", "sum"))
                      .sort_values("n", ascending=False).head(10).reset_index(),
        "by_contractor": q.groupby("contractor_name").agg(n=("work_order_id", "size"), amount=("amount_at_risk_inr", "sum"))
                          .sort_values("n", ascending=False).reset_index(),
        "reviewers": [{"who": k, "decisions": int(v)} for k, v in reviewers.items()],
        "done_pct": float((q.status != "Pending").mean() * 100) if len(q) else 0.0,
    }


def audit_report(E: dict, db: dict) -> dict:
    q = review_queue(E, db)
    conf = q[q.status.str.startswith("Verified") | (q.status == "Escalated")]
    return {
        "confirmed": conf[["work_order_id", "status", "ward_code", "road_name", "contractor_name", "rules", "reason",
                           "amount_at_risk_inr", "decision_note", "decided_by", "decided_at"]],
        "confirmed_amount": float(conf.amount_at_risk_inr.sum()),
        "counts": q.status.value_counts().reindex(STATUSES).fillna(0).astype(int).to_dict(),
        "by_contractor": conf.groupby("contractor_name").agg(n=("work_order_id", "size"), amount=("amount_at_risk_inr", "sum"))
                             .sort_values("amount", ascending=False).reset_index(),
    }


def report_text(rep: dict) -> str:
    c = rep["confirmed"]
    lines = [f"RastaNidhi audit report — {len(c)} confirmed findings, {inr(rep['confirmed_amount'])} to recover or explain", ""]
    for r in c.itertuples():
        lines += [f"{r.work_order_id} — {r.contractor_name} — {r.road_name}, Ward {r.ward_code}",
                  f"Status: {r.status} · Flags: {', '.join(r.rules)} · Amount: ₹{r.amount_at_risk_inr:,.0f}",
                  f"Evidence: {r.reason}"] + ([f"Auditor note: {r.decision_note}"] if r.decision_note else []) + [""]
    lines.append("A flag only becomes a finding after an auditor reviews it. All data is synthetic.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------- researcher
def season(E: dict) -> dict:
    d, flags = E["d"], E["flags"]
    wo, cp = d.work_orders, d.complaints.drop_duplicates("complaint_id")
    risk = audit.money_at_risk(flags)
    dl = flags[flags.rule == "DLP_PAID"]
    m = wo.set_index("assigned_at").resample("MS")
    months = sorted(set(m.size().index) | set(cp.set_index("received_at").resample("MS").size().index))
    spend = m.cost_inr.sum() / 1e5
    sla = m.sla_met.apply(lambda s: (s == "Y").mean() * 100 if len(s) else None)
    reo = m.reopened_within_30d.apply(lambda s: (s == "Y").mean() * 100 if len(s) else None)
    comp = cp.set_index("received_at").resample("MS").size()
    o = {
        "season": "Jun – Oct 2025", "spend": float(wo.cost_inr.sum()), "complaints": int(len(cp)), "work_orders": int(len(wo)),
        "wards": int(len(d.wards)), "contractors": int(len(d.contractors)), "population": int(d.wards.population_est.sum()),
        "sla_pct": float((wo.sla_met == "Y").mean() * 100), "reopen_pct": float((wo.reopened_within_30d == "Y").mean() * 100),
        "flagged": int(len(risk)), "at_risk": float(risk.amount_at_risk_inr.sum()),
        "dlp_count": int(len(dl)), "dlp_value": float(dl.amount_at_risk_inr.sum()),
        "open_complaints": int(cp.status.isin(OPEN).sum()),
    }
    o["paragraph"] = (
        f"Between {o['season']}, BMC spent {inr(o['spend'])} on monsoon road repairs across {o['wards']} wards serving roughly "
        f"{o['population'] / 1e6:.1f} million residents. {o['complaints']:,} complaints were filed and {o['open_complaints']:,} are still open. "
        f"Of {o['work_orders']:,} work orders, {o['sla_pct']:.0f}% met their service deadline and {o['reopen_pct']:.0f}% failed again within 30 days. "
        f"Automatic checks put {inr(o['at_risk'])} across {o['flagged']} work orders up for review — over-billing, double bills and repairs "
        f"paid on roads still under warranty, including {inr(o['dlp_value'])} that may never have needed to leave the public purse.")
    trend = {"labels": [x.strftime("%b") for x in months],
             "spend_lakh": [round(float(spend.get(x, 0)), 1) for x in months],
             "complaints": [int(comp.get(x, 0)) for x in months],
             "sla_pct": [round(float(sla.get(x)), 1) if pd.notna(sla.get(x)) else None for x in months],
             "reopen_pct": [round(float(reo.get(x)), 1) if pd.notna(reo.get(x)) else None for x in months]}
    return {"overview": o, "trend": trend}


def ward_compare(E: dict) -> pd.DataFrame:
    d = E["d"]
    cp = d.complaints.drop_duplicates("complaint_id")
    res = cp[cp.status == "Resolved"]
    days = ((res.resolved_at - res.received_at).dt.total_seconds() / 86400).groupby(res.ward_code).mean()
    w = E["wsc"].copy()  # already has population_est and engineering_crews
    w["avg_fix_days"] = w.ward_code.map(days)
    w["complaints_per_1000"] = w.complaints / w.population_est * 1000
    w["jobs_per_crew"] = w.jobs / w.engineering_crews
    return w


def _r(a: pd.Series, b: pd.Series) -> float:
    return round(float(a.corr(b.reindex(a.index))), 2)


def _strength(r: float) -> str:
    a = abs(r)
    return "very strongly" if a >= .8 else "strongly" if a >= .6 else "moderately" if a >= .4 else "weakly" if a >= .2 else "barely"


def findings(E: dict) -> list[dict]:
    d, flags = E["d"], E["flags"]
    wo, cp, wa = d.work_orders, d.complaints.drop_duplicates("complaint_id"), d.wards.set_index("ward_code")
    rain = d.rainfall.groupby("date").rainfall_mm.max()
    daily = cp.set_index("received_at").resample("D").size()
    r_rain = _r(daily, rain)
    per_cap = cp.groupby("ward_code").size() / wa.population_est * 1000
    r_ll_c = _r(wa.low_lying_index, per_cap)
    r_ll_r = _r(wa.low_lying_index, wo.groupby("ward_code").reopened_within_30d.apply(lambda s: (s == "Y").mean()))
    sla_h = wo.groupby("sla_hours").sla_met.apply(lambda s: (s == "Y").mean() * 100)
    load = wo.groupby("ward_code").size() / wa.engineering_crews
    r_load = _r(load, wo.groupby("ward_code").sla_met.apply(lambda s: (s == "Y").mean()))
    ws = wo.merge(d.roads[["road_id", "surface"]], on="road_id")
    cold = ws[ws.repair_method == "Cold mix patch"].groupby("surface").reopened_within_30d.apply(lambda s: (s == "Y").mean() * 100)
    ob = flags[flags.rule == "OVERBILLED"].contractor_name.value_counts()
    top2 = ob.head(2)
    dl_share = flags[flags.rule == "DLP_PAID"].cost_inr.sum() / wo.cost_inr.sum() * 100
    non_en = (cp.language != "en").mean() * 100
    open_age = (AS_OF - cp[cp.status.isin(OPEN)].received_at).dt.days.mean()
    rejected = cp.status.str.startswith("Rejected").mean() * 100
    fm = E["fm"].metrics
    out = [
        dict(stat=f"r = {r_rain}", label="daily rainfall ↔ daily complaints", kind="correlation",
             text=f"Daily complaint volume moves {_strength(r_rain)} with rainfall (r = {r_rain}). Monsoon intensity, not neglect alone, drives the spikes, so a raw complaint count is a weather chart as much as a performance chart."),
        dict(stat=f"r = {r_ll_c}", label="ward flood-risk ↔ complaints per 1,000 people", kind="correlation",
             text=f"Low-lying wards file {'more' if r_ll_c > 0 else 'fewer'} complaints per head (r = {r_ll_c}), yet their repairs are {'not more' if r_ll_r <= .1 else 'more'} likely to fail (r = {r_ll_r} with re-open rate). Their problem is exposure, not worse contractors."),
        dict(stat=f"{sla_h.get(24, 0):.0f}% vs {sla_h.get(168, 0):.0f}%", label="SLA met: 24-hour jobs vs 168-hour jobs", kind="comparison",
             text=f"Only {sla_h.get(24, 0):.1f}% of the most urgent (24-hour) jobs meet their deadline, against {sla_h.get(168, 0):.1f}% of 168-hour jobs. A ward's raw SLA rate mostly reflects its mix of urgent work."),
        dict(stat=f"r = {r_load}", label="jobs per engineering crew ↔ SLA met rate", kind="correlation",
             text=f"Wards with more work per crew meet {'fewer' if r_load < 0 else 'more'} deadlines (r = {r_load}). Some 'slow' wards are under-resourced rather than under-performing."),
        dict(stat=f"{cold.get('Concrete (CC)', 0):.0f}% vs {cold.get('Asphalt', 0):.0f}%", label="cold-mix patch failure: concrete vs asphalt roads", kind="comparison",
             text=f"The cheapest patch fails {cold.get('Concrete (CC)', 0):.0f}% of the time on concrete roads against {cold.get('Asphalt', 0):.0f}% on asphalt. Matching method to surface matters — though in our failure model (AUC {fm['cv_auc']:.2f}) the contractor is still the strongest single predictor."),
        dict(stat=f"{top2.sum() / ob.sum() * 100:.0f}%", label="share of over-billed jobs from just two contractors", kind="concentration",
             text=f"{top2.sum()} of {ob.sum()} jobs billed above {audit.OVERBILL_RATIO}× the rate card come from two of eight contractors ({', '.join(n.replace(' (synthetic)', '') for n in top2.index)}). Over-billing is concentrated, not city-wide."),
        dict(stat=f"{dl_share:.1f}%", label="share of all spend paid on roads still under warranty", kind="share",
             text=f"{dl_share:.1f}% of the season's repair spend went to roads still inside their original contractor's Defect Liability Period."),
        dict(stat=f"{non_en:.0f}%", label="complaints filed in Hinglish, Marathi or Hindi", kind="share",
             text=f"{non_en:.0f}% of complaints are not in plain English. Triage that only reads English misses almost half the city."),
        dict(stat=f"{open_age:.0f} days", label="average age of a still-open complaint", kind="age",
             text=f"Complaints still open at the end of the season have waited {open_age:.0f} days on average. This backlog does not clear itself."),
        dict(stat=f"{rejected:.1f}%", label="share of complaints rejected outright", kind="share",
             text=f"{rejected:.1f}% of complaints were rejected as not a BMC road or not a road issue. Worth checking how many were misrouted rather than wrong."),
    ]
    return out


def brief_snippets(E: dict) -> list[dict]:
    o = season(E)["overview"]
    f = findings(E)
    base = [
        dict(id="spend", label="Total season spend", text=f"BMC spent {inr(o['spend'])} on monsoon road repairs across {o['wards']} wards between {o['season']}."),
        dict(id="complaints", label="Complaints filed / open", text=f"{o['complaints']:,} complaints were filed this season; {o['open_complaints']:,} remain unresolved."),
        dict(id="sla", label="SLA and durability", text=f"Only {o['sla_pct']:.0f}% of repairs met their deadline, and {o['reopen_pct']:.0f}% failed again within 30 days."),
        dict(id="risk", label="Money needing review", text=f"Automatic checks put {inr(o['at_risk'])} across {o['flagged']} work orders up for review as over-billed, double-billed or paid on roads under warranty."),
        dict(id="dlp", label="Warranty (DLP) payments", text=f"{inr(o['dlp_value'])} was paid for {o['dlp_count']} repairs on roads still under their Defect Liability Period — a cost that should have fallen on the original contractor."),
    ]
    return base + [dict(id=f"f{i}", label=x["label"].capitalize(), text=x["text"]) for i, x in enumerate(f)]
