"""Deterministic repair auditor. Every flag points to a work order and has a one-line reason."""
from __future__ import annotations

import pandas as pd

from .data import Data, inr

# Normal jobs vary ~20-30% around the rate card (README). Data shows a clean gap between 1.3x and 1.5x.
OVERBILL_RATIO = 1.4
NORMAL_BAND_TOP = 1.3
DOUBLE_BILL_WINDOW_DAYS = 14

RULES = {
    "OVERBILLED": "Billed well above the rate card",
    "DOUBLE_BILLED": "Same road and same job billed again within days, with no complaint linked",
    "DLP_PAID": "BMC paid for a repair on a road still under its Defect Liability Period",
    "SLA_MISSED": "Fixed later than the SLA promised",
    "REOPENED": "Fix failed within 30 days",
    "SLA_FLAG_WRONG": "Recorded 'SLA met' doesn't match the complaint and completion timestamps",
}
# Suspicious = money questions. Performance = speed/durability (context matters, not wrongdoing).
SUSPICIOUS = {"OVERBILLED", "DOUBLE_BILLED", "DLP_PAID", "SLA_FLAG_WRONG"}


def run_audit(d: Data) -> pd.DataFrame:
    wo = d.work_orders
    flags: list[dict] = []

    def add(r, rule, severity, at_risk, reason, evidence=""):
        flags.append(dict(
            work_order_id=r.work_order_id, rule=rule, severity=severity,
            ward_code=r.ward_code, road_id=r.road_id, road_name=r.road_name,
            contractor_id=r.contractor_id, contractor_name=r.contractor_name,
            repair_method=r.repair_method, completed_at=r.completed_at,
            cost_inr=r.cost_inr, amount_at_risk_inr=float(at_risk), reason=reason,
            evidence=evidence,
        ))

    # 1. Over-billing vs rate card
    for r in wo[wo.cost_ratio > OVERBILL_RATIO].itertuples():
        excess = r.cost_inr - r.expected_cost_inr * NORMAL_BAND_TOP
        unit = f"{r.area_sqm:g} sqm × ₹{r.standard_rate_inr:,.0f}" if r.unit == "per sqm" else f"₹{r.standard_rate_inr:,.0f} per job"
        add(r, "OVERBILLED", "High" if r.cost_ratio >= 2 else "Medium", excess,
            f"Billed {inr(r.cost_inr)} vs expected {inr(r.expected_cost_inr)} ({unit}) = {r.cost_ratio:.1f}× rate card.")

    # 2. Double billing: unlinked WO on same road+method shortly after another WO
    s = wo.sort_values("assigned_at")
    for r in s[s.n_linked == 0].itertuples():
        prior = s[(s.road_id == r.road_id) & (s.repair_method == r.repair_method)
                  & (s.work_order_id != r.work_order_id)
                  & (s.assigned_at < r.assigned_at)
                  & (r.assigned_at - s.assigned_at <= pd.Timedelta(days=DOUBLE_BILL_WINDOW_DAYS))]
        if prior.empty:
            continue
        p = prior.iloc[-1]
        gap = (r.assigned_at - p.assigned_at).days
        same = [k for k in ("contractor_id", "area_sqm") if p[k] == getattr(r, k)]
        add(r, "DOUBLE_BILLED", "High", r.cost_inr,
            f"Repeats {p.work_order_id} ({r.repair_method}, {r.road_name}) {gap} days later with no complaint"
            + (f"; same {' & '.join(x.replace('_id', '').replace('_sqm', '') for x in same)}." if same else "."),
            evidence=p.work_order_id)

    # 3. DLP: original contractor should fix at no cost to BMC
    dlp = wo[(wo.under_dlp == "Y") & (wo.completed_at >= wo.last_resurfaced)]
    for r in dlp.itertuples():
        add(r, "DLP_PAID", "Medium", r.cost_inr,
            f"{r.road_name} was resurfaced {r.last_resurfaced:%d %b %Y} and is still under DLP; "
            f"{inr(r.cost_inr)} should be recovered from the original contractor.")

    # 4. SLA flag sanity check against timestamps
    chk = wo.dropna(subset=["hours_to_fix"])
    calc = (chk.hours_to_fix <= chk.sla_hours).map({True: "Y", False: "N"})
    for r in chk[calc != chk.sla_met].itertuples():
        add(r, "SLA_FLAG_WRONG", "Low", 0,
            f"Recorded sla_met={r.sla_met} but took {r.hours_to_fix:.0f}h against a {r.sla_hours}h SLA.")

    # 5. Performance flags (context, not accusation)
    for r in wo[wo.sla_met == "N"].itertuples():
        late = f"{r.hours_to_fix:.0f}h vs {r.sla_hours}h SLA" if pd.notna(r.hours_to_fix) else f"{r.sla_hours}h SLA"
        ctx = " Engineer notes rain/traffic delay." if any(k in str(r.engineer_remark) for k in ("Rain", "NOC")) else ""
        add(r, "SLA_MISSED", "Low", 0, f"Took {late}.{ctx}")
    for r in wo[wo.reopened_within_30d == "Y"].itertuples():
        ctx = f" {r.rain_7d_after_mm:.0f} mm of rain fell in the week after." if r.heavy_rain_after else ""
        add(r, "REOPENED", "Medium" if r.repair_method == "Cold mix patch" else "Low", r.cost_inr,
            f"{r.repair_method} failed within 30 days; {inr(r.cost_inr)} spent on a fix that didn't hold.{ctx}")

    f = pd.DataFrame(flags)
    f["category"] = f.rule.map(lambda x: "Suspicious billing" if x in SUSPICIOUS else "Performance")
    return f


def money_at_risk(flags: pd.DataFrame) -> pd.DataFrame:
    """Per work order, take the largest suspicious amount (no double counting across rules)."""
    s = flags[flags.category == "Suspicious billing"]
    return s.sort_values("amount_at_risk_inr").groupby("work_order_id").tail(1)
