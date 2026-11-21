"""Project & work tracking (REQUIREMENTS.md §5, §7.1–7.4).

* A **project** = one ward's seasonal budget allocation (seeded from wards.csv, admins can add more).
* Any complaint (BMC25-…), work order (WO25-…), citizen report (CP-…) or issue (ISS-…) can be tracked
  through a delivery-style stage list built from the dataset timestamps + shared actions in the store
  (contractor submissions, officer sign-off, auditor decisions, recovery notices).
"""
from __future__ import annotations

import pandas as pd

from .data import inr

AS_OF = pd.Timestamp("2025-10-05")          # dataset snapshot date
SEASON = "2025 Monsoon"
LIFECYCLE = ["Open", "In Progress", "Work order linked", "Resolved", "Closed"]   # REQUIREMENTS §7.4
LEGACY = {"Received": "Open", "Inspected": "In Progress", "Work order raised": "Work order linked",
          "Rejected – not BMC road": "Rejected"}


def _t(x) -> str | None:
    return None if x is None or pd.isna(x) else pd.Timestamp(x).strftime("%d %b %Y, %H:%M")


def _stage(key, label, state, at=None, detail=""):
    return {"key": key, "label": label, "state": state, "at": at, "detail": detail}


def _progress(stages) -> int:
    done = sum(s["state"] in ("done", "warn") for s in stages)
    return round(100 * done / max(1, len(stages)))


def _events(db: dict, wid: str, citizen: bool) -> list[dict]:
    ev = []
    for s in db.get("submissions", []):
        if s["work_order_id"] == wid:
            ev.append({"at": s["at"], "icon": "🧰", "who": s["by"], "text": f"Contractor update: {s['status']} — {s['note']}"})
            if s.get("reviewed_at"):
                ev.append({"at": s["reviewed_at"], "icon": "✅" if s["review"] == "Approved" else "↩️", "who": s["reviewed_by"],
                           "text": f"Officer {s['review'].lower()}" + (f": {s['review_note']}" if s.get("review_note") else "")})
    if not citizen:
        for r in db.get("reviews", {}).get(wid, []):
            ev.append({"at": r["at"], "icon": "⚖️", "who": r["by"], "text": f"Audit decision: {r['status']}" + (f" — {r['note']}" if r.get("note") else "")})
        for e in db.get("evidence", {}).get(wid, []):
            ev.append({"at": e["at"], "icon": "📎", "who": e["by"], "text": e["note"]})
    for n in db.get("notices", []):
        if n.get("target") == wid:
            ev.append({"at": n["at"], "icon": "📨", "who": n["by"], "text": "Recovery notice issued to the contractor (demo: not actually sent)"})
    return sorted(ev, key=lambda x: x["at"])


# ---------------------------------------------------------------------------- work order
def track_work_order(E: dict, db: dict, wid: str, role: str) -> dict | None:
    wo = E["d"].work_orders
    r = wo[wo.work_order_id == wid]
    if r.empty:
        return None
    r = r.iloc[0]
    citizen = role == "Citizen"
    subs = [s for s in db.get("submissions", []) if s["work_order_id"] == wid]
    last_sub = subs[-1] if subs else None
    st = []
    if pd.notna(r.first_complaint_at):
        st.append(_stage("reported", "Complaint received", "done", _t(r.first_complaint_at), f"{r.n_linked} citizen report(s) linked"))
    else:
        st.append(_stage("reported", "Raised without a complaint", "warn", None, "No citizen complaint is linked to this job"))
    st.append(_stage("assigned", "Work order issued", "done", _t(r.assigned_at), f"to {r.contractor_name} · {r.repair_method}"))
    st.append(_stage("started", "Crew on site", "done", _t(r.work_started_at), r.engineer_remark if isinstance(r.engineer_remark, str) else ""))
    sla_txt = (f"{r.hours_to_fix:.0f} h vs {r.sla_hours} h promised" if pd.notna(r.hours_to_fix) else f"{r.sla_hours} h promised")
    st.append(_stage("completed", "Repair completed", "done" if r.sla_met == "Y" else "warn", _t(r.completed_at),
                     ("On time · " if r.sla_met == "Y" else "Late · ") + sla_txt))
    if last_sub and last_sub.get("review") == "Approved":
        st.append(_stage("signoff", "Officer sign-off", "done", last_sub["reviewed_at"][:16].replace("T", " "), f"by {last_sub['reviewed_by']}"))
    elif last_sub and last_sub.get("review") == "Sent back":
        st.append(_stage("signoff", "Officer sign-off", "warn", last_sub["reviewed_at"][:16].replace("T", " "), "Sent back for rework"))
    elif last_sub:
        st.append(_stage("signoff", "Officer sign-off", "current", None, "Contractor has submitted — waiting for the ward officer"))
    else:
        st.append(_stage("signoff", "Officer sign-off", "todo", None, "No sign-off recorded in RastaNidhi yet"))
    held_by = r.completed_at + pd.Timedelta(days=30)
    if r.reopened_within_30d == "Y":
        st.append(_stage("held", "30-day durability check", "warn", None, "❌ The fix failed and the issue re-opened within 30 days"))
    elif held_by <= AS_OF:
        st.append(_stage("held", "30-day durability check", "done", _t(held_by), "✅ The fix held for 30 days"))
    else:
        st.append(_stage("held", "30-day durability check", "current", None, f"Watching until {held_by:%d %b %Y}"))

    f = E["flags"]
    fl = f[(f.work_order_id == wid) & (f.category == "Suspicious billing")]
    rv = db.get("reviews", {}).get(wid, [])
    review = rv[-1]["status"] if rv else ("Pending" if len(fl) else None)
    show_flags = not citizen or (review or "").startswith("Verified")
    status = ("Fix failed – re-opened" if r.reopened_within_30d == "Y" else "Awaiting sign-off" if last_sub and not last_sub.get("review")
              else "Sent back for rework" if last_sub and last_sub.get("review") == "Sent back" else "Completed · fix held" if held_by <= AS_OF else "Completed · under watch")
    nxt = ("The ward officer reviews the contractor's update." if status == "Awaiting sign-off" else
           "The contractor must redo the work and resubmit." if status.startswith("Sent back") else
           "A new repair is needed — the failed fix is a durability issue for the contractor." if status.startswith("Fix failed") else
           f"RastaNidhi keeps watching the fix until {held_by:%d %b %Y}." if status.endswith("watch") else "Nothing pending. This job is closed.")
    return {
        "kind": "work_order", "id": wid, "title": f"{r.work_type} repair on {r.road_name}", "status": status,
        "tone": "red" if "failed" in status.lower() or status.startswith("Sent") else "amber" if "Awaiting" in status or "watch" in status else "green",
        "ward": r.ward_code, "subtitle": f"Ward {r.ward_code} · {r.road_name} · {r.contractor_name}",
        "stages": st, "progress": _progress(st), "next": nxt,
        "facts": [["Contractor", r.contractor_name], ["Method", r.repair_method], ["Area", f"{r.area_sqm:g} sqm"],
                  ["Cost to BMC", inr(r.cost_inr)], ["Rate-card estimate", inr(r.expected_cost_inr)],
                  ["Deadline (SLA)", f"{r.sla_hours} h · {'met' if r.sla_met == 'Y' else 'missed'}"],
                  ["Road under warranty (DLP)", "Yes" if r.under_dlp == "Y" else "No"]]
                 + ([["Audit review", review]] if review and not citizen else []),
        "flags": fl.reason.tolist() if show_flags else [],
        "complaints": list(r.linked_list), "events": _events(db, wid, citizen),
        "submissions": subs,
    }


# ---------------------------------------------------------------------------- complaint (dataset)
def track_complaint(E: dict, db: dict, cid: str, role: str) -> dict | None:
    c = E["clean"]
    rows = c[c.complaint_id == cid]
    if rows.empty:
        return None
    r = rows.iloc[0]
    same = c[c.issue_id == r.issue_id]
    wid = r.work_order_id if pd.notna(r.work_order_id) else (same.work_order_id.dropna().iloc[0] if same.work_order_id.notna().any() else None)
    st = [_stage("received", "Complaint received", "done", _t(r.received_at), f"via {r.channel} · {r.language}")]
    st.append(_stage("grouped", "Checked & grouped", "done", None,
                     f"Category: {r.category_clean} · {len(same)} report(s) about this spot ({r.issue_id})"))
    out = {"kind": "complaint", "id": cid, "title": f"{r.category_clean} at {r.locality_clean}", "ward": r.ward_clean,
           "subtitle": f"Ward {r.ward_clean} · {r.locality_clean} · {r.upvotes} upvotes", "description": r.description}
    if r.status.startswith("Rejected") or r.status.startswith("Forwarded"):
        st.append(_stage("decision", r.status, "warn", None, "Not a BMC road job" if r.status.startswith("Rejected") else "Sent to the responsible agency"))
        out |= {"status": r.status, "tone": "red", "next": "BMC will not raise a work order for this complaint."}
    elif wid:
        w = track_work_order(E, db, wid, role)
        st += [s for s in w["stages"] if s["key"] != "reported"]
        out |= {"status": w["status"], "tone": w["tone"], "next": w["next"], "work_order": wid, "facts": w["facts"], "flags": w["flags"],
                "events": w["events"]}
    else:
        days = (AS_OF - r.received_at).days
        rk = E["ranked"]
        hit = rk[rk.issue_id == r.issue_id]
        rank = int(hit.index[0]) + 1 if len(hit) else None
        st += [_stage("waiting", "Waiting for a work order", "current", None, f"Open for {days} days"),
               _stage("assigned", "Work order issued", "todo"), _stage("completed", "Repair completed", "todo"), _stage("held", "30-day durability check", "todo")]
        nxt = f"Ranked #{rank} of {len(rk)} open issues city-wide for the next rupee." if rank else "Waiting for the ward to raise a work order."
        if len(hit):
            h = hit.iloc[0]
            nxt += f" Recommended fix: {h.repair_method} (≈ {inr(h.cost_to_bmc_inr)})."
        out |= {"status": f"Open · {days} days", "tone": "amber", "next": nxt}
    out |= {"stages": st, "progress": _progress(st)}
    return out


# ---------------------------------------------------------------------------- citizen report (RastaNidhi)
def norm_status(s: str) -> str:
    return LEGACY.get(s, s)


def track_report(E: dict, db: dict, rid: str, role: str) -> dict | None:
    rep = next((r for r in db.get("reports", []) if r["report_id"] == rid), None)
    if not rep:
        return None
    hist = rep.get("history") or [{"status": "Open", "at": rep["at"], "by": rep["by"]}]
    if norm_status(rep["status"]) != norm_status(hist[-1]["status"]):
        hist = hist + [{"status": rep["status"], "at": rep.get("updated_at", rep["at"]), "by": rep.get("updated_by", "")}]
    cur = norm_status(rep["status"])
    when = {norm_status(h["status"]): h for h in hist}
    st = []
    if cur == "Rejected":
        st = [_stage("Open", "Report received", "done", when.get("Open", {}).get("at", rep["at"])[:16].replace("T", " ")),
              _stage("Rejected", "Rejected", "warn", when["Rejected"]["at"][:16].replace("T", " "), "Not a BMC road issue")]
    else:
        idx = LIFECYCLE.index(cur) if cur in LIFECYCLE else 0
        labels = {"Open": "Report received", "In Progress": "Officer picked it up", "Work order linked": "Work order linked",
                  "Resolved": "Resolved", "Closed": "Closed"}
        for i, s in enumerate(LIFECYCLE):
            h = when.get(s)
            st.append(_stage(s, labels[s], "done" if i < idx or (i == idx and s in ("Resolved", "Closed")) else "current" if i == idx else "todo",
                             h["at"][:16].replace("T", " ") if h else None, f"by {h['by']}" if h and h.get("by") and i else ""))
    nxt = {"Open": "The ward officer will inspect the spot.", "In Progress": "The officer is checking it and will raise or link a work order.",
           "Work order linked": "The contractor carries out the repair; the officer signs it off.", "Resolved": "Fixed. It will be closed after a final check.",
           "Closed": "This report is closed. Thank you!", "Rejected": "BMC can't act on this (not a BMC road)."}.get(cur, "")
    out = {"kind": "report", "id": rid, "title": f"{rep['category']} at {rep.get('locality_matched') or rep['locality']}",
           "subtitle": f"Ward {rep.get('ward_code') or '?'} · filed {rep['at'][:16].replace('T', ' ')}", "ward": rep.get("ward_code"),
           "description": rep["description"], "status": cur, "tone": "green" if cur in ("Resolved", "Closed") else "red" if cur == "Rejected" else "amber",
           "stages": st, "progress": _progress(st), "next": nxt,
           "events": [{"at": h["at"], "icon": "•", "who": h.get("by", ""), "text": f"Status → {norm_status(h['status'])}"} for h in hist],
           "work_order": rep.get("work_order_id")}
    if rep.get("work_order_id"):
        w = track_work_order(E, db, rep["work_order_id"], role)
        if w:
            out |= {"facts": w["facts"], "linked": {"id": w["id"], "status": w["status"], "stages": w["stages"]}}
    return out


def track(E: dict, db: dict, q: str, role: str) -> dict | None:
    q = q.strip().upper()
    if q.startswith("WO"):
        return track_work_order(E, db, q, role)
    if q.startswith("BMC"):
        return track_complaint(E, db, q, role)
    if q.startswith("CP-"):
        return track_report(E, db, q, role)
    if q.startswith("ISS-"):
        c = E["clean"]
        rows = c[c.issue_id == q]
        return track_complaint(E, db, rows.complaint_id.iloc[0], role) if len(rows) else None
    return None


# ---------------------------------------------------------------------------- projects (ward budget allocations)
def projects(E: dict, db: dict) -> list[dict]:
    """Seeded: one '2025 Monsoon' project per ward (allocation = ward budget). Plus any created by admins."""
    w = E["wsc"].set_index("ward_code")
    seeded = [{"id": f"PRJ-{code.replace('/', '')}-25", "ward_code": code, "season": SEASON, "allocated_inr": float(r.monsoon_repair_budget_inr_2025),
               "notes": "Seeded from the ward's monsoon road repair budget", "status": "active", "created_by": "system", "created_at": "2025-06-01T00:00:00"}
              for code, r in w.iterrows()]
    over = {p["id"]: p for p in db.get("projects", [])}
    items = [over.pop(p["id"], p) | {"seeded": True} for p in seeded] + [p | {"seeded": False} for p in over.values()]
    return [_project_live(E, db, p) for p in items]


def _project_live(E: dict, db: dict, p: dict) -> dict:
    code = p["ward_code"]
    wo = E["d"].work_orders
    in_season = p["season"] == SEASON
    j = wo[wo.ward_code == code] if in_season else wo.iloc[0:0]
    spent = float(j.cost_inr.sum())
    iss = E["issues"][E["issues"].ward_code == code] if in_season else E["issues"].iloc[0:0]
    f = E["flags"]
    sus = f[(f.ward_code == code) & (f.category == "Suspicious billing")].work_order_id.unique() if in_season else []
    reviews = db.get("reviews", {})
    pending_reviews = sum(1 for x in sus if not reviews.get(x) or reviews[x][-1]["status"] == "Pending")
    subs = [s for s in db.get("submissions", []) if s.get("ward_code") == code and not s.get("review")]
    held = int((j.reopened_within_30d != "Y").sum())
    util = 100 * spent / p["allocated_inr"] if p["allocated_inr"] else 0
    health = ("Closed" if p["status"] == "closed" else "Over budget" if util > 100 else "Near limit" if util > 90 else "On track")
    return p | {
        "ward_name": E["wsc"].set_index("ward_code").ward_name.get(code, ""), "spent_inr": spent, "remaining_inr": p["allocated_inr"] - spent,
        "utilization_pct": util, "jobs": int(len(j)), "jobs_held": held, "jobs_failed": int(len(j) - held),
        "sla_met_pct": float((j.sla_met == "Y").mean() * 100) if len(j) else 0.0,
        "issues_total": int(len(iss)), "issues_fixed": int(iss.outcome.str.startswith("Fixed").sum()),
        "issues_open": int((iss.outcome == "Never fixed (open)").sum()),
        "flags_pending_review": pending_reviews, "submissions_pending": len(subs), "health": health,
    }


def project_detail(E: dict, db: dict, pid: str) -> dict | None:
    p = next((x for x in projects(E, db) if x["id"] == pid), None)
    if not p:
        return None
    wo = E["d"].work_orders
    j = wo[wo.ward_code == p["ward_code"]] if p["season"] == SEASON else wo.iloc[0:0]
    m = j.assign(month=j.completed_at.dt.strftime("%b")).groupby("month", sort=False).agg(
        jobs=("work_order_id", "size"), spend=("cost_inr", "sum"), failed=("reopened_within_30d", lambda s: (s == "Y").sum())).reset_index()
    order = {k: i for i, k in enumerate(["Jun", "Jul", "Aug", "Sep", "Oct"])}
    m = m.sort_values("month", key=lambda s: s.map(order))
    subs = {s["work_order_id"]: s for s in db.get("submissions", [])}
    recent = j.sort_values("completed_at", ascending=False).head(60)
    works = [{"work_order_id": r.work_order_id, "road": r.road_name, "type": r.work_type, "method": r.repair_method, "contractor": r.contractor_name,
              "completed": r.completed_at.strftime("%d %b"), "cost": float(r.cost_inr),
              "status": ("Awaiting sign-off" if r.work_order_id in subs and not subs[r.work_order_id].get("review") else
                         "Fix failed" if r.reopened_within_30d == "Y" else "Fix held" if r.completed_at + pd.Timedelta(days=30) <= AS_OF else "Under watch")}
             for r in recent.itertuples()]
    iss = E["issues"][E["issues"].ward_code == p["ward_code"]]
    funnel = [["Issues reported", int(len(iss))], ["Work order raised", int(iss.work_order_id.notna().sum())],
              ["Fix held 30 days", int((iss.outcome == "Fixed – held").sum())]]
    return {"project": p, "monthly": m.to_dict("records"), "works": works, "funnel": funnel}
