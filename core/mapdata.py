"""Everything the interactive ward map shows, in one payload (GeoJSON-ready), optionally scoped to one ward."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import audit, oversight
from .data import inr

ROAD_CAUSES = {"Pothole", "Waterlogged road", "Uneven road / open chamber", "Skid on wet road"}


def _fc(features: list) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _pt(lon, lat, props) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(float(lon), 6), round(float(lat), 6)]}, "properties": props}


def _clean(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, (np.integer,)):
            v = int(v)
        elif isinstance(v, (np.floating, float)):
            v = None if pd.isna(v) else round(float(v), 4)
        elif isinstance(v, (pd.Timestamp,)):
            v = v.strftime("%Y-%m-%d")
        elif isinstance(v, (np.bool_,)):
            v = bool(v)
        out[k] = v
    return out


def map_payload(E: dict, db: dict, ward: str | None = None) -> dict:
    d, flags, wsc = E["d"], E["flags"], E["wsc"]
    keep = lambda df, col="ward_code": df if not ward else df[df[col] == ward]

    # --- wards: polygons + every metric we have
    metrics = wsc.set_index("ward_code")
    cen = d.wards.set_index("ward_code")[["centroid_lat", "centroid_lon"]]
    wfeat, labels = [], []
    for f in d.wards_geo["features"]:
        code = f["properties"]["ward_code"]
        if ward and code != ward:
            continue
        m = _clean(metrics.loc[code].to_dict())
        wfeat.append({"type": "Feature", "id": code, "geometry": f["geometry"], "properties": {"ward_code": code, **m}})
        labels.append(_pt(cen.at[code, "centroid_lon"], cen.at[code, "centroid_lat"], {"ward_code": code, "name": m["ward_name"].split(",")[0]}))

    # --- roads: risk, DLP, money flagged
    rr = oversight.road_risk(E, ward).set_index("road_id")
    sus = flags[flags.category == "Suspicious billing"]
    rflag = sus.groupby("road_id").agg(flag_jobs=("work_order_id", "nunique"), flagged_inr=("amount_at_risk_inr", "sum"))
    rfeat = []
    for f in d.roads_geo["features"]:
        rid = f["properties"]["road_id"]
        if rid not in rr.index:
            continue
        r = rr.loc[rid]
        rfeat.append({"type": "Feature", "geometry": f["geometry"], "properties": _clean({
            "road_id": rid, "name": r.road_name, "ward": r.ward_code, "type": r.road_type, "surface": r.surface,
            "dlp": r.under_dlp == "Y", "risk": r.risk_score, "accidents": r.accidents, "jobs": r.prior_jobs, "spend": r.spend,
            "reopen": r.reopen_rate, "rec": r.rec_method, "ambulance": bool(r.critical_access),
            "flag_jobs": rflag.flag_jobs.get(rid, 0), "flagged_inr": rflag.flagged_inr.get(rid, 0.0)})})

    hs = keep(d.hotspots)
    hot = [_pt(r.lon, r.lat, _clean({"name": r.name, "ward": r.ward_code, "threshold": r.flood_threshold_mm_per_day,
                                    "tide": r.tide_sensitive == "Y", "depth": r.avg_water_depth_cm, "recession": r.avg_recession_hours,
                                    "pump": r.pumping_station_nearby == "Y", "years": r.years_flagged_last_5})) for r in hs.itertuples()]
    fa = keep(d.facilities)
    fac = [_pt(r.lon, r.lat, _clean({"name": r.name, "type": r.type, "ward": r.ward_code, "size": r.beds_or_students,
                                    "emergency": r.emergency_services == "Y", "road": r.ambulance_entry_road})) for r in fa.itertuples()]
    ac = keep(d.accidents)
    acc = [_pt(r.lon, r.lat, _clean({"severity": r.severity, "cause": r.probable_cause, "vehicle": r.vehicle_type,
                                    "date": str(r.occurred_at)[:10], "road_cond": r.probable_cause in ROAD_CAUSES, "ward": r.ward_code}))
           for r in ac.itertuples() if pd.notna(r.lat)]

    # --- open issues from the planner, pinned at their road midpoint (spread a little so pins don't stack)
    ranked = keep(E["ranked"])
    mids = d.roads.set_index("road_id")[["mid_lat", "mid_lon"]]
    iss, seen = [], {}
    for i, r in enumerate(ranked.itertuples(), 1):
        if r.road_id not in mids.index:
            continue
        k = seen.get(r.road_id, 0); seen[r.road_id] = k + 1
        ang = k * 2.4
        lat = mids.at[r.road_id, "mid_lat"] + 0.0011 * k ** .5 * np.sin(ang)
        lon = mids.at[r.road_id, "mid_lon"] + 0.0011 * k ** .5 * np.cos(ang)
        iss.append(_pt(lon, lat, _clean({"rank": i, "issue_id": r.issue_id, "ward": r.ward_code, "locality": r.locality,
                                         "category": r.category, "road": r.road_name, "risk": r.risk_score, "method": r.repair_method,
                                         "cost": r.cost_to_bmc_inr, "dlp": r.under_dlp == "Y", "reports": r.reports,
                                         "reasons": r.reasons})))

    # --- citizen reports filed in RastaNidhi (placed at their matched locality)
    loc = d.localities.drop_duplicates("locality").set_index("locality")
    reps = [r for r in db.get("reports", []) if r.get("locality_matched") in loc.index and (not ward or r.get("ward_code") == ward)]
    rep = [_pt(loc.at[r["locality_matched"], "lon"], loc.at[r["locality_matched"], "lat"],
               {"id": r["report_id"], "category": r["category"], "status": r["status"], "text": r["description"][:140],
                "locality": r["locality_matched"], "at": r["at"][:16].replace("T", " ")}) for r in reps]

    pins = [p for p in db.get("pins", []) if not ward or p.get("ward") in (None, ward)]
    risk = audit.money_at_risk(flags if not ward else flags[flags.ward_code == ward])
    bounds = None
    if ward:
        xs = [c[0] for f in wfeat for c in f["geometry"]["coordinates"][0]]
        ys = [c[1] for f in wfeat for c in f["geometry"]["coordinates"][0]]
        bounds = [[min(xs), min(ys)], [max(xs), max(ys)]]
    return {
        "scope": ward, "bounds": bounds,
        "wards": _fc(wfeat), "labels": _fc(labels), "roads": _fc(rfeat), "hotspots": _fc(hot), "facilities": _fc(fac),
        "accidents": _fc(acc), "issues": _fc(iss), "reports": _fc(rep), "pins": pins,
        "summary": {"spend": inr(float(wsc.spend_inr.sum() if not ward else metrics.at[ward, "spend_inr"])),
                    "at_risk": inr(float(risk.amount_at_risk_inr.sum())), "issues": len(iss), "hotspots": len(hot),
                    "facilities": len(fac), "accidents": len(acc)},
    }
