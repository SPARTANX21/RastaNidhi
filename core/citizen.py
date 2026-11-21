"""'Mera Complaint' lookup: retrieve evidence in code, then let Claude (or a template) answer."""
from __future__ import annotations

import re

import pandas as pd

from . import linker, social
from .data import inr


def _wo_info(E: dict, wid) -> dict | None:
    if wid is None or (isinstance(wid, float) and pd.isna(wid)):
        return None
    w = E["d"].work_orders.set_index("work_order_id").loc[wid]
    f = E["flags"]
    return dict(work_order_id=wid, contractor=w.contractor_name, method=w.repair_method, cost_inr=float(w.cost_inr),
                rate_card_expected_inr=round(float(w.expected_cost_inr)), completed_at=str(w.completed_at)[:16],
                sla_hours=int(w.sla_hours), sla_met=w.sla_met, fix_failed_within_30d=w.reopened_within_30d,
                engineer_remark=w.engineer_remark, road=w.road_name,
                audit_flags=f[(f.work_order_id == wid) & (f.category == "Suspicious billing")].reason.tolist())


def lookup(E: dict, q: str) -> dict:
    clean = E["clean"]
    ids = re.findall(r"BMC25-\d{6}", q.upper())
    if ids:
        out = []
        for cid in ids:
            r = clean[clean.complaint_id == cid]
            if r.empty:
                out.append(dict(complaint_id=cid, found=False))
                continue
            r = r.iloc[0]
            same = clean[clean.issue_id == r.issue_id]
            wid = r.work_order_id if pd.notna(r.work_order_id) else (
                same.work_order_id.dropna().iloc[0] if same.work_order_id.notna().any() else None)
            out.append(dict(complaint_id=cid, found=True, received_at=str(r.received_at)[:16], locality=r.locality_clean,
                            ward=r.ward_clean, category=r.category_clean, status=r.status,
                            other_reports_of_same_issue=int(len(same) - 1), work_order=_wo_info(E, wid)))
        return {"complaints": out}
    loc, _ = social.find_locality(q, E["gazetteer"])
    if not loc:
        return {"found": False, "hint": "No complaint ID or known locality in the question."}
    cat, _ = linker.classify(q, None)
    iss = E["issues"][E["issues"].locality == loc]
    if cat and cat in set(iss.category):
        iss = iss[iss.category == cat]
    iss = iss.sort_values("last_reported", ascending=False).head(4)
    return {"locality": loc, "category_guess": cat, "recent_issues": [
        dict(issue_id=r.issue_id, category=r.category, first_reported=str(r.first_reported)[:10], reports=int(r.reports),
             outcome=r.outcome, work_order=_wo_info(E, r.work_order_id)) for r in iss.itertuples()]}


def template(ctx: dict) -> str:
    if "complaints" in ctx:
        lines = []
        for c in ctx["complaints"]:
            if not c["found"]:
                lines.append(f"❌ {c['complaint_id']} not found.")
                continue
            w = c["work_order"]
            s = f"**{c['complaint_id']}** ({c['category']}, {c['locality']}): status **{c['status']}**."
            if w:
                s += (f" Fixed under {w['work_order_id']} by {w['contractor']} on {w['completed_at'][:10]} using "
                      f"{w['method']} for {inr(w['cost_inr'])} (rate card ≈ {inr(w['rate_card_expected_inr'])}). "
                      f"SLA {'met ✅' if w['sla_met'] == 'Y' else 'missed ⏱️'}. "
                      f"{'⚠️ The fix failed within 30 days.' if w['fix_failed_within_30d'] == 'Y' else 'The fix held ✅.'}")
            lines.append(s)
        return "\n\n".join(lines)
    if not ctx.get("found", True):
        return "I couldn't find that. Please share your complaint ID (e.g. BMC25-000123) or the locality name."
    return f"Recent issues in **{ctx['locality']}**:\n\n" + "\n".join(
        f"- {i['issue_id']}: {i['category']}, first reported {i['first_reported']}, {i['reports']} reports → **{i['outcome']}**"
        for i in ctx["recent_issues"])
