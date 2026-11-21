"""Next-rupee planner: rank open issues by risk, pick a durable method, fit to the ward's remaining budget."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import CATEGORY_SEVERITY, Data, haversine_m

WEIGHTS = {  # sums to 100
    "severity": 25, "flood": 15, "traffic": 15, "accidents": 15,
    "facilities": 10, "citizen": 10, "age": 5, "tide": 5,
}
CAT_TO_WORKTYPE = {k: k for k in CATEGORY_SEVERITY}
ROAD_CAUSES = {"Pothole", "Waterlogged road", "Uneven road / open chamber", "Skid on wet road"}


def method_stats(d: Data) -> pd.DataFrame:
    wo = d.work_orders
    m = wo.groupby(["work_type", "repair_method"]).agg(
        jobs=("work_order_id", "size"),
        reopen_rate=("reopened_within_30d", lambda s: (s == "Y").mean()),
        median_cost_inr=("cost_inr", "median"),
        median_area_sqm=("area_sqm", "median"),
        unit=("unit", "first"), rate=("standard_rate_inr", "first"),
    ).reset_index()
    m["standard_cost_inr"] = np.where(m.unit == "per sqm", m.median_area_sqm * m.rate, m.rate)
    m["cost_per_lasting_fix"] = m.standard_cost_inr / (1 - m.reopen_rate)
    return m


def pick_method(ms: pd.DataFrame, work_type: str, high_risk: bool) -> pd.Series:
    opts = ms[ms.work_type == work_type]
    if opts.empty:
        return pd.Series(dict(repair_method="Site inspection", standard_cost_inr=50_000, reopen_rate=np.nan, why="No history"))
    if high_risk:
        best = opts.sort_values(["reopen_rate", "standard_cost_inr"]).iloc[0]
        why = f"lowest failure rate ({best.reopen_rate:.0%}) for a high-risk spot"
    else:
        best = opts.sort_values("cost_per_lasting_fix").iloc[0]
        why = f"best cost per lasting fix (₹{best.cost_per_lasting_fix:,.0f})"
    worst = opts.reopen_rate.max()
    if len(opts) > 1 and worst > best.reopen_rate:
        cheap = opts.sort_values("standard_cost_inr").iloc[0]
        if cheap.repair_method != best.repair_method:
            why += f"; avoid {cheap.repair_method} ({cheap.reopen_rate:.0%} fail)"
    return pd.Series(dict(repair_method=best.repair_method, standard_cost_inr=best.standard_cost_inr,
                          reopen_rate=best.reopen_rate, why=why))


def _road_context(d: Data) -> pd.DataFrame:
    r = d.roads.set_index("road_id")
    acc = d.accidents[d.accidents.probable_cause.isin(ROAD_CAUSES)]
    acc_w = acc.severity.map({"Minor": 1, "Grievous": 3, "Fatal": 10})
    r["accident_points"] = acc_w.groupby(acc.road_id).sum()
    r["road_accidents"] = acc.groupby("road_id").size()
    r["fatal_accidents"] = acc[acc.severity == "Fatal"].groupby("road_id").size()
    f = d.facilities
    r["hospitals"] = f[f.type == "Hospital"].groupby("ambulance_entry_road").size()
    r["emergency_hospitals"] = f[(f.type == "Hospital") & (f.emergency_services == "Y")].groupby("ambulance_entry_road").size()
    r["schools"] = f[f.type == "School"].groupby("ambulance_entry_road").size()
    r["facility_names"] = f.groupby("ambulance_entry_road").name.apply(lambda s: ", ".join(s.head(3)))
    # nearest flood hotspot within 1.5 km
    hs = d.hotspots
    near, near_name, thr, tide = [], [], [], []
    for row in r.itertuples():
        dist = haversine_m(row.mid_lat, row.mid_lon, hs.lat.values, hs.lon.values)
        j = int(np.argmin(dist))
        ok = dist[j] <= 1000
        near.append(dist[j] if ok else np.nan)
        near_name.append(hs.name.iloc[j] if ok else None)
        thr.append(hs.flood_threshold_mm_per_day.iloc[j] if ok else np.nan)
        tide.append(hs.tide_sensitive.iloc[j] == "Y" if ok else False)
    r["hotspot_dist_m"], r["hotspot"], r["hotspot_threshold_mm"], r["tide_sensitive"] = near, near_name, thr, tide
    r = r.fillna({c: 0 for c in ["accident_points", "road_accidents", "fatal_accidents", "hospitals",
                                 "emergency_hospitals", "schools"]})
    return r


def rank_open_issues(d: Data, issues: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    as_of = as_of or d.complaints.received_at.max()
    op = issues[issues.outcome == "Never fixed (open)"].copy()
    op = op[op.category.isin(CATEGORY_SEVERITY)]
    rc = _road_context(d)
    ctx = rc.reindex(op.road_id).reset_index(drop=True)
    op = op.reset_index(drop=True)
    for col in ["road_name", "road_type", "under_dlp", "bus_route", "congestion_index_0_10", "peak_hour_vehicles",
                "accident_points", "road_accidents", "fatal_accidents", "hospitals", "emergency_hospitals",
                "schools", "facility_names", "hotspot", "hotspot_dist_m", "hotspot_threshold_mm", "tide_sensitive"]:
        op[col] = ctx[col].values
    ll = d.wards.set_index("ward_code").low_lying_index
    op["low_lying_index"] = op.ward_code.map(ll)

    def norm01(s):
        s = s.astype(float).fillna(0)
        return (s - s.min()) / (s.max() - s.min()) if s.max() > s.min() else s * 0

    comp = pd.DataFrame(index=op.index)
    comp["severity"] = op.category.map(CATEGORY_SEVERITY) / 5
    flood_hot = np.where(op.hotspot.notna(), 1 - (op.hotspot_threshold_mm.fillna(200) - 50) / 200, 0).clip(0, 1)
    comp["flood"] = 0.6 * flood_hot + 0.4 * op.low_lying_index.fillna(0.5)
    comp["traffic"] = 0.5 * norm01(op.congestion_index_0_10) + 0.3 * norm01(op.peak_hour_vehicles) + 0.2 * (op.bus_route == "Y")
    comp["accidents"] = norm01(np.log1p(op.accident_points))
    comp["facilities"] = np.clip(op.emergency_hospitals * 0.6 + op.hospitals * 0.2 + op.schools * 0.25, 0, 1)
    comp["citizen"] = norm01(np.log1p(op.reports * 3 + op.upvotes))
    comp["age"] = np.clip((as_of - op.first_reported).dt.days / 30, 0, 1)
    comp["tide"] = op.tide_sensitive.astype(float)
    op["risk_score"] = sum(comp[k] * w for k, w in WEIGHTS.items()).round(1)
    for k in WEIGHTS:
        op[f"f_{k}"] = (comp[k] * WEIGHTS[k]).round(1)

    ms = method_stats(d)
    hi = op.risk_score >= op.risk_score.quantile(0.6)
    picks = pd.DataFrame([pick_method(ms, CAT_TO_WORKTYPE[c], h) for c, h in zip(op.category, hi)])
    op = pd.concat([op, picks.reset_index(drop=True)], axis=1)
    op["cost_to_bmc_inr"] = np.where(op.under_dlp == "Y", 0, op.standard_cost_inr)
    op["reasons"] = op.apply(_reasons, axis=1)
    return op.sort_values("risk_score", ascending=False).reset_index(drop=True)


def _reasons(r) -> str:
    out = [f"severity {CATEGORY_SEVERITY.get(r.category, '?')}/5 {r.category.lower()}"]
    if r.hotspot:
        out.append(f"{r.hotspot_dist_m:.0f} m from {r.hotspot} (floods at {r.hotspot_threshold_mm:.0f} mm)")
    if r.tide_sensitive:
        out.append("tide-sensitive")
    if r.emergency_hospitals:
        out.append(f"ambulance route to {r.facility_names}")
    elif r.schools:
        out.append(f"school access road ({r.facility_names})")
    if r.road_accidents:
        out.append(f"{int(r.road_accidents)} road-condition accidents" + (f", {int(r.fatal_accidents)} fatal" if r.fatal_accidents else ""))
    if r.congestion_index_0_10 and r.congestion_index_0_10 >= 7:
        out.append(f"congestion {r.congestion_index_0_10}/10")
    if r.reports > 1:
        out.append(f"{r.reports} reports")
    if r.under_dlp == "Y":
        out.append("under DLP – original contractor must fix free")
    return "; ".join(out)


def allocate(ranked: pd.DataFrame, ward: str, budget: float) -> pd.DataFrame:
    w = ranked[ranked.ward_code == ward].copy()
    left, fits = budget, []
    for c in w.cost_to_bmc_inr:
        ok = c <= left
        fits.append(ok)
        left -= c if ok else 0
    w["fits_budget"] = fits
    w["budget_left_after_inr"] = budget - (w.cost_to_bmc_inr * w.fits_budget).cumsum()
    return w


def chronic_roads(d: Data, min_failures: int = 3) -> pd.DataFrame:
    """Roads where patching keeps failing: candidates for resurfacing instead of another patch."""
    wo = d.work_orders
    g = wo.groupby(["road_id", "road_name", "ward_code"]).agg(
        jobs=("work_order_id", "size"), spend_inr=("cost_inr", "sum"),
        failures=("reopened_within_30d", lambda s: (s == "Y").sum()),
        cold_mix_jobs=("repair_method", lambda s: (s == "Cold mix patch").sum()),
        under_dlp=("under_dlp", "first"),
    ).reset_index()
    g = g[g.failures >= min_failures]
    length = d.roads.set_index("road_id").length_m
    lanes = d.roads.set_index("road_id").lanes
    g["resurface_estimate_inr"] = g.road_id.map(length * lanes * 3.5 * 1100)  # ~3.5 m lanes, ₹1,100/sqm resurfacing (assumption)
    return g.sort_values("spend_inr", ascending=False)
