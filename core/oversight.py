"""Admin + Ward Officer oversight features (ported from civicproof_admin.html / civicproof_officer.html prototypes):
alerts, data health, audit-sensitivity what-if, monthly trends, road risk, recovery notices, rule-based assistant.
All numbers come from the same engine as the rest of the app so pages reconcile.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import audit
from .data import Data, haversine_m, inr

AS_OF = pd.Timestamp("2025-10-05")  # snapshot date used for "age" of open complaints
OPEN = ["Open", "In Progress"]
ROAD_CAUSES = {"Pothole", "Waterlogged road", "Uneven road / open chamber"}


# ---------------------------------------------------------------------------- trends
def monthly_trend(d: Data, ward: str | None = None) -> dict:
    wo, cp = d.work_orders, d.complaints.drop_duplicates("complaint_id")
    if ward:
        wo, cp = wo[wo.ward_code == ward], cp[cp.ward_code == ward]
    s = wo.set_index("assigned_at").resample("MS").cost_inr.sum() / 1e5
    c = cp.set_index("received_at").resample("MS").size()
    months = sorted(set(s.index) | set(c.index))
    return {"labels": [m.strftime("%b") for m in months],
            "spend_lakh": [round(float(s.get(m, 0)), 1) for m in months],
            "complaints": [int(c.get(m, 0)) for m in months]}


def flag_breakdown(flags: pd.DataFrame, n_wo: int) -> list[dict]:
    sus = flags[flags.category == "Suspicious billing"]
    out = [{"label": r, "value": int((sus.rule == r).sum())} for r in ["OVERBILLED", "DOUBLE_BILLED", "DLP_PAID"]]
    out.append({"label": "Clean", "value": int(n_wo - sus.work_order_id.nunique())})
    return out


# ---------------------------------------------------------------------------- data health
def data_health(d: Data) -> dict:
    cp = d.complaints.drop_duplicates("complaint_id")
    wo = d.work_orders
    open_cp = cp[cp.status.isin(OPEN)]
    link = wo[["work_order_id", "completed_at", "linked_list"]].explode("linked_list").dropna()
    late = link.merge(cp[["complaint_id", "received_at"]], left_on="linked_list", right_on="complaint_id")
    return {
        "complaints_total": int(len(cp)),
        "missing_ward_pct": round(cp.ward_code.isna().mean() * 100, 1),
        "missing_gps_pct": round(cp.lat.isna().mean() * 100, 1),
        "open_unresolved": int(len(open_cp)),
        "avg_open_age_days": int((AS_OF - open_cp.received_at).dt.days.mean()),
        "late_linked": int((late.received_at > late.completed_at).sum()),
        "wo_unlinked_pct": round((wo.n_linked == 0).mean() * 100, 1),
        "dlp_tag_to_verify": int(((d.roads.under_dlp == "N") & (d.roads.last_resurfaced >= "2023-01-01")).sum()),
        "vague_category_pct": round(cp.category_reported.isin(["Other", "Road related"]).mean() * 100, 1),
        "non_english_pct": round((cp.language != "en").mean() * 100, 1),
        "channels": cp.channel.value_counts().to_dict(),
        "languages": cp.language.map({"en": "English", "hi-en": "Hinglish", "mr": "Marathi", "hi": "Hindi"}).value_counts().to_dict(),
        "statuses": cp.status.value_counts().to_dict(),
    }


# ---------------------------------------------------------------------------- alerts
def alerts(E: dict, db: dict) -> list[dict]:
    d, flags, wsc, csc = E["d"], E["flags"], E["wsc"], E["csc"]
    risk = audit.money_at_risk(flags)
    dh = data_health(d)
    top_w = wsc.sort_values("budget_used_pct", ascending=False).iloc[0]
    worst_c = csc.sort_values("overall_score").iloc[0]
    over = flags[flags.rule == "OVERBILLED"].sort_values("amount_at_risk_inr", ascending=False)
    dlp = flags[flags.rule == "DLP_PAID"]
    dbl = flags[flags.rule == "DOUBLE_BILLED"]
    sus_ids = set(flags[flags.category == "Suspicious billing"].work_order_id)
    reviewed = {w for w, v in db.get("reviews", {}).items() if v and v[-1]["status"] != "Pending"}
    pending = len(sus_ids - reviewed)
    out = [
        dict(severity="critical", page="ward", ward=top_w.ward_code,
             title=f"Ward {top_w.ward_code} has spent {top_w.budget_used_pct:.0f}% of its monsoon budget",
             detail=f"{inr(top_w.spend_inr)} against {inr(top_w.monsoon_repair_budget_inr_2025)}. "
                    f"{inr(top_w.money_at_risk_inr)} of its spend needs review."),
        dict(severity="critical", page="scorecards",
             title=f"{worst_c.contractor_name} has the lowest fair score (grade {worst_c.grade}, {worst_c.overall_score:.0f}/100)",
             detail=f"Re-open {worst_c.reopen_rate:.0%} vs {worst_c.exp_reopen_rate:.0%} expected for its job mix; "
                    f"{int(worst_c.overbilled)} over-billed and {int(worst_c.double_billed)} double-billed jobs."),
        dict(severity="critical", page="audit",
             title=f"{len(dlp)} repairs were paid for on roads still under warranty (DLP)",
             detail=f"{inr(dlp.amount_at_risk_inr.sum())} that should have been the original contractor's cost, not BMC's."),
        dict(severity="warning", page="audit",
             title=f"{len(dbl)} likely double bills",
             detail=f"Same road and method billed again within {audit.DOUBLE_BILL_WINDOW_DAYS} days with no complaint linked, "
                    f"worth {inr(dbl.amount_at_risk_inr.sum())}."),
        dict(severity="warning", page="audit",
             title=f"{pending} suspicious work orders still await an auditor decision",
             detail=f"{len(reviewed & sus_ids)} of {len(sus_ids)} have been verified, cleared or escalated so far. "
                    f"Total needing review: {inr(risk.amount_at_risk_inr.sum())}."),
        dict(severity="warning", page="issues",
             title=f"{dh['open_unresolved']} complaints are still open",
             detail=f"Average age {dh['avg_open_age_days']} days as of {AS_OF:%d %b %Y}; no work order has been raised yet."),
        dict(severity="info", page="datahealth",
             title=f"{dh['dlp_tag_to_verify']} roads resurfaced in 2023 or later are marked DLP = N",
             detail="Worth a manual check: they may be mis-tagged and wrongly outside warranty protection."),
    ]
    if len(over):
        b = over.iloc[0]
        out.append(dict(severity="info", page="audit", wo=b.work_order_id,
                        title=f"Biggest single over-billed job: {b.work_order_id}",
                        detail=f"{b.contractor_name} billed {inr(b.cost_inr)}; {b.reason}"))
    reps = [r for r in db.get("reports", []) if r.get("status") == "Received"]
    if reps:
        out.append(dict(severity="info", page="reports", title=f"{len(reps)} new citizen reports filed through RastaNidhi",
                        detail="Waiting for the ward officer to pick them up."))
    return out


# ---------------------------------------------------------------------------- sensitivity what-if
def sensitivity(d: Data, ratio: float, dup_days: int) -> dict:
    """Recount flags at other thresholds (prototype default 1.5× / 7 days; app default 1.4× / 14 days)."""
    wo = d.work_orders.sort_values("assigned_at")
    over = wo[wo.cost_ratio > ratio]
    gap = wo.groupby(["road_id", "repair_method"]).assigned_at.diff().dt.total_seconds() / 86400
    dup = wo[(gap <= dup_days) & (wo.n_linked == 0)]
    dlp = wo[(wo.under_dlp == "Y") & (wo.completed_at >= wo.last_resurfaced)]
    excess = float((over.cost_inr - over.expected_cost_inr).sum())
    ids = set(over.work_order_id) | set(dup.work_order_id) | set(dlp.work_order_id)
    return {"ratio": ratio, "dup_days": dup_days, "over_count": int(len(over)), "over_excess": excess,
            "dup_count": int(len(dup)), "dup_value": float(dup.cost_inr.sum()),
            "dlp_count": int(len(dlp)), "dlp_value": float(dlp.cost_inr.sum()),
            "flagged_work_orders": len(ids), "total_at_risk": excess + float(dup.cost_inr.sum()) + float(dlp.cost_inr.sum())}


# ---------------------------------------------------------------------------- road risk (officer "Roads & risk")
RISK_WEIGHTS = {"accidents": 25, "flood": 20, "traffic": 15, "critical_access": 15, "reopen": 15, "repair_frequency": 10}


def road_risk(E: dict, ward: str | None = None) -> pd.DataFrame:
    d = E["d"]
    r = d.roads.copy()
    acc = d.accidents[d.accidents.probable_cause.isin(ROAD_CAUSES)].road_id.value_counts()
    wo = d.work_orders
    g = wo.groupby("road_id").agg(prior_jobs=("work_order_id", "size"),
                                  reopen_rate=("reopened_within_30d", lambda s: (s == "Y").mean()),
                                  spend=("cost_inr", "sum"))
    amb = set(d.facilities.ambulance_entry_road.dropna())
    hs = d.hotspots
    dist = []
    for row in r.itertuples():
        h = hs[hs.ward_code == row.ward_code]
        dist.append(float(haversine_m(row.mid_lat, row.mid_lon, h.lat.values, h.lon.values).min()) / 1000 if len(h) else np.nan)
    r["flood_dist_km"] = dist
    r["accidents"] = r.road_id.map(acc).fillna(0).astype(int)
    r = r.merge(g, on="road_id", how="left").fillna({"prior_jobs": 0, "reopen_rate": 0, "spend": 0})
    r["critical_access"] = r.road_id.isin(amb)

    def n(s):
        s = s.astype(float).fillna(s.max() if s.notna().any() else 0)
        return (s - s.min()) / (s.max() - s.min()) if s.max() > s.min() else s * 0
    r["risk_score"] = (RISK_WEIGHTS["accidents"] * n(r.accidents) + RISK_WEIGHTS["flood"] * n(-r.flood_dist_km.fillna(99))
                       + RISK_WEIGHTS["traffic"] * n(r.peak_hour_vehicles.fillna(0) + r.bus_routes_count.fillna(0) * 100)
                       + RISK_WEIGHTS["critical_access"] * r.critical_access.astype(float)
                       + RISK_WEIGHTS["reopen"] * n(r.reopen_rate) + RISK_WEIGHTS["repair_frequency"] * n(r.prior_jobs)).round(1)
    # recommended durable patch per surface: lowest re-open rate among patch methods on that surface
    pw = wo[wo.work_type == "Pothole"].merge(d.roads[["road_id", "surface"]], on="road_id")
    by = pw.groupby(["surface", "repair_method"]).reopened_within_30d.apply(lambda s: (s == "Y").mean())
    ms = E["methods"].set_index("repair_method")

    def rec(surface):
        if surface == "Paver blocks":
            m = "Paver blocks relaid"
            rr = float(ms.loc[m, "reopen_rate"])
        else:
            opts = by.get(surface)
            m = opts.idxmin() if opts is not None and len(opts) else "Hot mix patch"
            rr = float(opts.min()) if opts is not None and len(opts) else 0.25
        cost = float(ms.loc[m, "standard_cost_inr"]) if m in ms.index else 20000
        return m, rr, cost / max(1 - rr, 0.3)
    recs = r.surface.map(rec)
    r["rec_method"] = [x[0] for x in recs]
    r["rec_reopen_rate"] = [x[1] for x in recs]
    r["rec_cost_inr"] = [x[2] for x in recs]
    dlp_paid = E["flags"][E["flags"].rule == "DLP_PAID"].groupby("road_id").agg(
        dlp_jobs=("work_order_id", "size"), dlp_paid_inr=("amount_at_risk_inr", "sum"))
    r = r.merge(dlp_paid, on="road_id", how="left").fillna({"dlp_jobs": 0, "dlp_paid_inr": 0})
    if ward:
        r = r[r.ward_code == ward]
    return r.sort_values("risk_score", ascending=False)[[
        "road_id", "road_name", "ward_code", "road_type", "surface", "under_dlp", "last_resurfaced", "risk_score", "accidents",
        "flood_dist_km", "critical_access", "prior_jobs", "reopen_rate", "spend", "rec_method", "rec_reopen_rate", "rec_cost_inr",
        "dlp_jobs", "dlp_paid_inr"]]


# ---------------------------------------------------------------------------- ward officer extras
def ward_extras(E: dict, ward: str) -> dict:
    d, flags = E["d"], E["flags"]
    cp = d.complaints.drop_duplicates("complaint_id")
    cp = cp[cp.ward_code == ward]
    open_cp = cp[cp.status.isin(OPEN)].assign(age_days=lambda x: (AS_OF - x.received_at).dt.days)
    wo = d.work_orders[d.work_orders.ward_code == ward]
    f = flags[flags.ward_code == ward]
    con = wo.groupby("contractor_name").agg(jobs=("work_order_id", "size"), spend_inr=("cost_inr", "sum"),
                                            sla_rate=("sla_met", lambda s: (s == "Y").mean()),
                                            reopen_rate=("reopened_within_30d", lambda s: (s == "Y").mean())).reset_index()
    for rule, col in [("OVERBILLED", "overbilled"), ("DOUBLE_BILLED", "double_billed"), ("DLP_PAID", "dlp_paid")]:
        con[col] = con.contractor_name.map(f[f.rule == rule].groupby("contractor_name").size()).fillna(0).astype(int)
    con["needs_review_inr"] = con.contractor_name.map(
        audit.money_at_risk(f).groupby("contractor_name").amount_at_risk_inr.sum()).fillna(0)
    rr = road_risk(E, ward)
    return {
        "avg_open_age_days": int(open_cp.age_days.mean()) if len(open_cp) else 0,
        "trend": monthly_trend(d, ward),
        "rank": E["wsc"][["ward_code", "budget_used_pct"]].sort_values("budget_used_pct", ascending=False),
        "top_unresolved": open_cp.sort_values(["upvotes", "age_days"], ascending=False).head(8)[
            ["complaint_id", "category_reported", "locality_text", "description", "language", "upvotes", "status", "age_days", "channel"]],
        "contractors": con.sort_values("spend_inr", ascending=False),
        "recovery_roads": rr[(rr.under_dlp == "Y") & (rr.dlp_jobs > 0)].sort_values("dlp_paid_inr", ascending=False).head(10),
    }


# ---------------------------------------------------------------------------- recovery notices
def notice_for_work_order(E: dict, wid: str, officer: str) -> str:
    w = E["d"].work_orders.set_index("work_order_id").loc[wid]
    f = E["flags"]
    f = f[(f.work_order_id == wid) & (f.category == "Suspicious billing")]
    ward = E["d"].wards.set_index("ward_code").ward_name[w.ward_code]
    label = {"OVERBILLED": "Over-billing", "DOUBLE_BILLED": "Double billing", "DLP_PAID": "DLP violation",
             "SLA_FLAG_WRONG": "SLA record mismatch"}
    reasons = "\n".join(f"  • {label.get(r.rule, r.rule)}: {r.reason}" for r in f.itertuples()) or "  • Flagged on review."
    claim = f.amount_at_risk_inr.max() if len(f) else w.cost_inr
    return (f"To: {w.contractor_name}\nFrom: Office of the Ward Officer, Ward {w.ward_code} ({ward}) — {officer}\n"
            f"Re: Work order {wid} — {w.repair_method} on {w.road_name}\n\n"
            f"Work order {wid} (assigned {w.assigned_at:%d %b %Y}, completed {w.completed_at:%d %b %Y}) has been flagged on review:\n"
            f"{reasons}\n\nBilled amount: ₹{w.cost_inr:,.0f} · Rate-card expectation: ₹{w.expected_cost_inr:,.0f}\n\n"
            f"Please respond within 7 working days with supporting documents (measurement book, site photos), "
            f"or process a refund/adjustment of ₹{claim:,.0f}.\n\n— Draft generated by RastaNidhi. Review before sending.")


def notice_for_road(E: dict, road_id: str, officer: str) -> str:
    rd = E["d"].roads.set_index("road_id").loc[road_id]
    f = E["flags"]
    jobs = f[(f.road_id == road_id) & (f.rule == "DLP_PAID")]
    ward = E["d"].wards.set_index("ward_code").ward_name[rd.ward_code]
    lines = "\n".join(f"  • {r.work_order_id} — {r.repair_method}, {r.contractor_name}, ₹{r.cost_inr:,.0f}" for r in jobs.itertuples())
    return (f"To: Original resurfacing contractor of record — {rd.road_name} ({road_id})\n"
            f"From: Office of the Ward Officer, Ward {rd.ward_code} ({ward}) — {officer}\n"
            f"Re: Defect Liability Period — {rd.road_name}, segment {rd.segment_no}\n\n"
            f"This segment was last resurfaced on {rd.last_resurfaced:%d %b %Y} and remains within its Defect Liability Period. "
            f"Repairs on it are the original contractor's responsibility, at no cost to BMC.\n\n"
            f"BMC has nevertheless paid for {len(jobs)} repair(s) on this segment this monsoon:\n{lines or '  • none recorded'}\n"
            f"Total: ₹{jobs.cost_inr.sum():,.0f}\n\nPlease inspect and remedy this segment within 7 working days, and confirm "
            f"how the amount above will be recovered. No further work order will be released for payment on this segment "
            f"while it remains under DLP.\n\n— Draft generated by RastaNidhi. Review before sending.")


# ---------------------------------------------------------------------------- assistant (rule-based, role-scoped)
def assistant(E: dict, user: dict, q: str) -> tuple[str, dict]:
    d, flags, wsc, csc = E["d"], E["flags"], E["wsc"], E["csc"]
    ql = q.lower()
    role = user["role"]
    risk = audit.money_at_risk(flags)
    if role == "Ward Officer":
        w = wsc.set_index("ward_code").loc[user["ward"]]
        ex = ward_extras(E, user["ward"])
        f = flags[flags.ward_code == user["ward"]]
        ctx = {"ward": user["ward"], "budget": w.monsoon_repair_budget_inr_2025, "spent": w.spend_inr,
               "remaining": w.remaining_budget_inr}
        if any(k in ql for k in ("budget", "remaining", "headroom", "left")):
            rem = w.remaining_budget_inr
            return (f"Ward **{user['ward']}** has spent {inr(w.spend_inr)} of {inr(w.monsoon_repair_budget_inr_2025)} "
                    f"({w.budget_used_pct:.0f}%). " + (f"{inr(rem)} is left." if rem > 0 else
                    f"It is **{inr(-rem)} over budget**, so recover money before spending more.")), ctx
        if "road" in ql or "risk" in ql:
            r = road_risk(E, user["ward"]).iloc[0]
            return (f"Highest-risk road: **{r.road_name}** ({r.road_id}), risk {r.risk_score:.0f}/100: {r.accidents} road-condition "
                    f"accidents, {'on an ambulance route, ' if r.critical_access else ''}"
                    + ("under DLP, so the original contractor should fix it." if r.under_dlp == "Y" else f"recommended fix {r.rec_method}.")), ctx
        if "recover" in ql or "dlp" in ql:
            dl = f[f.rule == "DLP_PAID"]
            return (f"{len(dl)} work orders in {user['ward']} were paid on DLP roads, worth **{inr(dl.amount_at_risk_inr.sum())}** "
                    f"to recover. Everything needing review in this ward adds up to {inr(audit.money_at_risk(f).amount_at_risk_inr.sum())}."), ctx
        if "contractor" in ql:
            c = ex["contractors"].sort_values("reopen_rate", ascending=False).iloc[0]
            return (f"**{c.contractor_name}** has the highest re-open rate here: {c.reopen_rate:.0%} across {c.jobs} jobs, "
                    f"{c.overbilled} over-billed, {c.dlp_paid} DLP payments."), ctx
        if "oldest" in ql or "complaint" in ql or "open" in ql:
            t = ex["top_unresolved"]
            if t.empty:
                return f"No open complaints in {user['ward']} right now.", ctx
            o = t.sort_values("age_days", ascending=False).iloc[0]
            return (f"{len(t)} high-attention complaints are open (average age {ex['avg_open_age_days']} days). Oldest: "
                    f"**{o.category_reported}** at {o.locality_text}, {o.age_days} days old, {o.upvotes} upvotes ({o.complaint_id})."), ctx
        if "sla" in ql:
            return f"Ward {user['ward']} met its SLA on {w.sla_rate:.0%} of jobs; {w.reopen_rate:.0%} of fixes re-opened within 30 days.", ctx
        return ("I can answer about this ward's **budget**, **riskiest road**, **recovery/DLP**, **contractors**, "
                "**open complaints** or **SLA**."), ctx

    if role == "Contractor":
        r = csc[csc.contractor_id == user["contractor_id"]].iloc[0]
        f = flags[(flags.contractor_id == user["contractor_id"]) & (flags.category == "Suspicious billing")]
        ctx = {"contractor": r.contractor_name}
        return (f"**{r.contractor_name}**: grade **{r.grade}** ({r.overall_score:.0f}/100). Re-open rate {r.reopen_rate:.0%} vs "
                f"{r.exp_reopen_rate:.0%} expected, SLA met {r.sla_rate:.0%}. {f.work_order_id.nunique()} of your jobs have billing "
                f"flags; open one under *My flags & evidence* to respond."), ctx

    # Admin / Auditor / Researcher: city scope
    ctx = {"scope": "city"}
    wm = next((w for w in wsc.itertuples() if f" {w.ward_code.lower()} " in f" {ql} " or f"ward {w.ward_code.lower()}" in ql), None)
    cm = next((c for c in csc.itertuples() if c.contractor_name.lower().split()[0] in ql), None)
    if "worst ward" in ql or ("ward" in ql and ("budget" in ql or "over" in ql) and not wm):
        w = wsc.sort_values("budget_used_pct", ascending=False).iloc[0]
        return (f"**{w.ward_code} – {w.ward_name}** has spent {w.budget_used_pct:.0f}% of its budget "
                f"({inr(w.spend_inr)} of {inr(w.monsoon_repair_budget_inr_2025)}); {inr(w.money_at_risk_inr)} needs review."), ctx
    if "riskiest" in ql or "worst contractor" in ql or ("contractor" in ql and not cm):
        c = csc.sort_values("overall_score").iloc[0]
        return (f"**{c.contractor_name}** has the lowest fair score: grade {c.grade} ({c.overall_score:.0f}/100), re-open "
                f"{c.reopen_rate:.0%} vs {c.exp_reopen_rate:.0%} expected, {c.overbilled} over-billed, {c.double_billed} double-billed."), ctx
    if wm:
        return (f"**{wm.ward_code} – {wm.ward_name}**: budget {inr(wm.monsoon_repair_budget_inr_2025)}, spent {inr(wm.spend_inr)} "
                f"({wm.budget_used_pct:.0f}%). {inr(wm.money_at_risk_inr)} needs review, {wm.open_complaints} open complaints, "
                f"re-open rate {wm.reopen_rate:.0%}."), ctx
    if cm:
        return (f"**{cm.contractor_name}**: grade {cm.grade}, {cm.jobs} jobs, {inr(cm.spend_inr)} billed, SLA {cm.sla_rate:.0%}, "
                f"re-open {cm.reopen_rate:.0%} (expected {cm.exp_reopen_rate:.0%}), {cm.overbilled} over-billed, {cm.dlp_paid} DLP payments."), ctx
    if "risk" in ql or "how much" in ql:
        s = flags[flags.category == "Suspicious billing"]
        parts = ", ".join(f"{inr(s[s.rule == r].amount_at_risk_inr.sum())} {lbl}" for r, lbl in
                          [("OVERBILLED", "over-billed excess"), ("DOUBLE_BILLED", "double bills"), ("DLP_PAID", "paid on DLP roads")])
        return f"**{inr(risk.amount_at_risk_inr.sum())}** needs review across {len(risk)} work orders: {parts}.", ctx
    if "dlp" in ql:
        dl = flags[flags.rule == "DLP_PAID"]
        return f"{len(dl)} repairs were paid on roads under DLP, worth **{inr(dl.amount_at_risk_inr.sum())}** to recover from the original contractors.", ctx
    if "duplicate" in ql or "double" in ql:
        dl = flags[flags.rule == "DOUBLE_BILLED"]
        return f"{len(dl)} likely double bills worth **{inr(dl.amount_at_risk_inr.sum())}**: same road and method within {audit.DOUBLE_BILL_WINDOW_DAYS} days, no complaint linked.", ctx
    if "overbill" in ql or "over-bill" in ql:
        dl = flags[flags.rule == "OVERBILLED"]
        return f"{len(dl)} jobs billed above {audit.OVERBILL_RATIO}× the rate card; excess above the normal band is {inr(dl.amount_at_risk_inr.sum())}.", ctx
    if "open" in ql or "complaint" in ql:
        dh = data_health(d)
        return f"{dh['open_unresolved']} complaints are still open or in progress (average age {dh['avg_open_age_days']} days).", ctx
    if "sla" in ql:
        return f"City-wide, {(d.work_orders.sla_met == 'Y').mean():.0%} of jobs met their SLA.", ctx
    return ("Ask me about the **worst ward**, the **riskiest contractor**, **money at risk**, **DLP**, **double bills**, "
            "**over-billing**, **open complaints**, **SLA**, a ward (e.g. *ward L*) or a contractor (e.g. *Mahalaxmi*)."), ctx
