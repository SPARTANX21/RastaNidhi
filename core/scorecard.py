"""Fair, context-adjusted scorecards for contractors and wards.

Fairness method: indirect standardisation. For every job we compute the *expected* re-open
and SLA-miss probability from jobs of the same type, in similarly flood-prone wards, under
similar rain. A contractor's score compares what happened to what was expected for *their*
mix of jobs, so working in Hindmata in July isn't punished like working in Colaba in October.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .audit import money_at_risk
from .data import Data

PRIOR_JOBS = 30  # shrink small samples toward "as expected"


def _with_expectations(d: Data) -> pd.DataFrame:
    wo = d.work_orders.copy()
    wo["low_lying_band"] = pd.cut(wo.low_lying_index, [-1, 0.4, 0.65, 2], labels=["low", "mid", "high"])
    # rain while the job was open (crews can't lay asphalt in a downpour)
    rain = d.rainfall.groupby("date").rainfall_mm.max()
    wo["rain_during_mm"] = [
        rain.loc[a.normalize():c.normalize()].sum() for a, c in zip(wo.assigned_at, wo.completed_at)
    ]
    wo["rain_during_job"] = wo.rain_during_mm >= 64.5  # IMD "heavy" day
    wo["reopen"] = (wo.reopened_within_30d == "Y").astype(int)
    wo["sla_miss"] = (wo.sla_met == "N").astype(int)
    keys_r = ["work_type", "low_lying_band", "heavy_rain_after"]
    keys_s = ["work_type", "sla_hours", "rain_during_job"]
    wo["exp_reopen"] = wo.groupby(keys_r, observed=True).reopen.transform("mean")
    wo["exp_sla_miss"] = wo.groupby(keys_s, observed=True).sla_miss.transform("mean")
    return wo


def _grade(score: float) -> str:
    return "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 35 else "E"


def contractor_scorecards(d: Data, flags: pd.DataFrame) -> pd.DataFrame:
    wo = _with_expectations(d)
    risk = money_at_risk(flags)
    g = wo.groupby(["contractor_id", "contractor_name"])
    sc = g.agg(
        jobs=("work_order_id", "size"), spend_inr=("cost_inr", "sum"),
        wards=("ward_code", "nunique"),
        reopen_rate=("reopen", "mean"), exp_reopen_rate=("exp_reopen", "mean"),
        reopens=("reopen", "sum"), exp_reopens=("exp_reopen", "sum"),
        sla_rate=("sla_miss", lambda s: 1 - s.mean()),
        sla_misses=("sla_miss", "sum"), exp_sla_misses=("exp_sla_miss", "sum"),
        median_cost_ratio=("cost_ratio", "median"),
        avg_low_lying=("low_lying_index", "mean"),
        heavy_rain_share=("heavy_rain_after", "mean"),
    ).reset_index()
    sus = flags[flags.category == "Suspicious billing"]
    for rule in ("OVERBILLED", "DOUBLE_BILLED", "DLP_PAID"):
        sc[rule.lower()] = sc.contractor_id.map(sus[sus.rule == rule].groupby("contractor_id").size()).fillna(0).astype(int)
    sc["money_at_risk_inr"] = sc.contractor_id.map(risk.groupby("contractor_id").amount_at_risk_inr.sum()).fillna(0)

    # Shrunk observed/expected ratios (1.0 = exactly as expected for this job mix)
    sc["durability_oe"] = (sc.reopens + PRIOR_JOBS * sc.exp_reopen_rate) / (sc.exp_reopens + PRIOR_JOBS * sc.exp_reopen_rate)
    sc["speed_oe"] = (sc.sla_misses + PRIOR_JOBS * 0.5) / (sc.exp_sla_misses + PRIOR_JOBS * 0.5)
    # Billing integrity: overbilled + double-billed share of jobs (DLP is partly a BMC process failure)
    sc["billing_issue_rate"] = (sc.overbilled + sc.double_billed) / sc.jobs

    def to_score(oe):  # oe 0.5 -> 100, 1.0 -> 60, 1.5 -> 20
        return np.clip(100 - (oe - 0.5) * 80, 0, 100)
    sc["durability_score"] = to_score(sc.durability_oe).round()
    sc["speed_score"] = to_score(sc.speed_oe).round()
    sc["cost_score"] = np.clip(100 - sc.billing_issue_rate * 600 - (sc.median_cost_ratio - 1).clip(lower=0) * 100, 0, 100).round()
    sc["overall_score"] = (0.4 * sc.durability_score + 0.3 * sc.speed_score + 0.3 * sc.cost_score).round()
    sc["grade"] = sc.overall_score.map(_grade)
    return sc.sort_values("overall_score", ascending=False)


def ward_scorecards(d: Data, flags: pd.DataFrame) -> pd.DataFrame:
    wo = d.work_orders
    risk = money_at_risk(flags)
    c = d.complaints
    w = d.wards[["ward_code", "ward_name", "zone", "population_est", "low_lying_index",
                 "engineering_crews", "monsoon_repair_budget_inr_2025"]].copy()
    g = wo.groupby("ward_code")
    w["spend_inr"] = w.ward_code.map(g.cost_inr.sum()).fillna(0)
    w["jobs"] = w.ward_code.map(g.size()).fillna(0).astype(int)
    w["budget_used_pct"] = 100 * w.spend_inr / w.monsoon_repair_budget_inr_2025
    w["remaining_budget_inr"] = w.monsoon_repair_budget_inr_2025 - w.spend_inr
    w["failed_fix_spend_inr"] = w.ward_code.map(wo[wo.reopened_within_30d == "Y"].groupby("ward_code").cost_inr.sum()).fillna(0)
    w["money_at_risk_inr"] = w.ward_code.map(risk.groupby("ward_code").amount_at_risk_inr.sum()).fillna(0)
    w["sla_rate"] = w.ward_code.map(g.sla_met.apply(lambda s: (s == "Y").mean()))
    w["reopen_rate"] = w.ward_code.map(g.reopened_within_30d.apply(lambda s: (s == "Y").mean()))
    open_c = c[c.status.isin(["Open", "In Progress"])]
    w["open_complaints"] = w.ward_code.map(open_c.groupby("ward_code").size()).fillna(0).astype(int)
    w["complaints"] = w.ward_code.map(c.groupby("ward_code").size()).fillna(0).astype(int)
    w["top_contractor"] = w.ward_code.map(wo.groupby("ward_code").apply(
        lambda x: x.groupby("contractor_name").cost_inr.sum().idxmax(), include_groups=False))
    w["spend_per_lakh_pop"] = w.spend_inr / (w.population_est / 1e5)
    return w


def ward_money_trail(d: Data, ward: str) -> dict[str, pd.DataFrame]:
    wo = d.work_orders[d.work_orders.ward_code == ward]
    return {
        "by_contractor": wo.groupby("contractor_name").agg(
            jobs=("work_order_id", "size"), spend_inr=("cost_inr", "sum"),
            reopen_rate=("reopened_within_30d", lambda s: (s == "Y").mean()),
            sla_rate=("sla_met", lambda s: (s == "Y").mean()),
        ).sort_values("spend_inr", ascending=False).reset_index(),
        "by_method": wo.groupby(["work_type", "repair_method"]).agg(
            jobs=("work_order_id", "size"), spend_inr=("cost_inr", "sum"),
            failed_spend_inr=("cost_inr", lambda s: s[wo.loc[s.index, "reopened_within_30d"] == "Y"].sum()),
        ).sort_values("spend_inr", ascending=False).reset_index(),
        "by_month": wo.assign(month=wo.completed_at.dt.to_period("M").astype(str)).groupby("month").cost_inr.sum().reset_index(),
        "work_orders": wo,
    }
