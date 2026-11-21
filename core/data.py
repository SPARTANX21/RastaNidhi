"""Load and enrich the Follow-the-Rupee dataset. Everything downstream reads from `load_all()`."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(os.environ.get(
    "RUPEE_DATA_DIR",
    Path(__file__).resolve().parents[2] / "Claude-Impact-Labs-data-2" / "data",
))

# Severity implied by the SLA hours (24h = sev 5 ... 168h = sev 1), per the data dictionary.
SLA_TO_SEVERITY = {24: 5, 48: 4, 72: 3, 120: 2, 168: 1}
# Default severity when we only know the category (open complaints have no SLA yet).
CATEGORY_SEVERITY = {
    "Road cave-in": 5,
    "Open or broken manhole": 5,
    "Waterlogging": 4,
    "Choked drain / nullah overflow": 3,
    "Pothole": 3,
    "Broken paver blocks": 2,
}


@dataclass
class Data:
    wards: pd.DataFrame
    work_orders: pd.DataFrame
    rate_card: pd.DataFrame
    contractors: pd.DataFrame
    complaints: pd.DataFrame
    social: pd.DataFrame
    roads: pd.DataFrame
    localities: pd.DataFrame
    hotspots: pd.DataFrame
    rainfall: pd.DataFrame
    tides: pd.DataFrame
    traffic: pd.DataFrame
    accidents: pd.DataFrame
    facilities: pd.DataFrame
    wards_geo: dict
    roads_geo: dict


def _read(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name, encoding="utf-8", **kw)


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6_371_000 * 2 * np.arcsin(np.sqrt(a))


def nearest_road(lat: float, lon: float, roads: pd.DataFrame, ward: str | None = None) -> tuple[str | None, float]:
    """Nearest road segment midpoint, optionally restricted to a ward."""
    r = roads if not ward else roads[roads.ward_code == ward]
    if r.empty or pd.isna(lat):
        return None, np.nan
    d = haversine_m(lat, lon, r.mid_lat.values, r.mid_lon.values)
    i = int(np.argmin(d))
    return r.road_id.iloc[i], float(d[i])


@lru_cache(maxsize=1)
def load_all() -> Data:
    wards = _read("wards.csv")
    rate = _read("rate_card.csv")
    contractors = _read("contractors.csv")
    roads = _read("roads.csv", parse_dates=["last_resurfaced"])
    roads["mid_lat"] = (roads.start_lat + roads.end_lat) / 2
    roads["mid_lon"] = (roads.start_lon + roads.end_lon) / 2
    traffic = _read("traffic.csv")
    roads = roads.merge(traffic, on="road_id", how="left")

    complaints = _read("complaints.csv", parse_dates=["received_at", "resolved_at"])
    wo = _read("work_orders.csv", parse_dates=["assigned_at", "work_started_at", "completed_at"])

    # --- enrich work orders ---------------------------------------------------
    wo = wo.merge(rate, on="repair_method", how="left")
    wo["expected_cost_inr"] = np.where(
        wo.unit == "per sqm", wo.area_sqm * wo.standard_rate_inr, wo.standard_rate_inr
    )
    wo["cost_ratio"] = wo.cost_inr / wo.expected_cost_inr
    wo["severity"] = wo.sla_hours.map(SLA_TO_SEVERITY)
    wo["linked_list"] = wo.linked_complaint_ids.fillna("").map(lambda s: [x for x in s.split("|") if x])
    wo["n_linked"] = wo.linked_list.map(len)
    first_rx = complaints.set_index("complaint_id").received_at
    wo["first_complaint_at"] = wo.linked_list.map(lambda ids: min((first_rx[i] for i in ids if i in first_rx), default=pd.NaT))
    wo["hours_to_fix"] = (wo.completed_at - wo.first_complaint_at).dt.total_seconds() / 3600
    wo = wo.merge(
        roads[["road_id", "road_name", "road_type", "under_dlp", "last_resurfaced", "bus_route"]],
        on="road_id", how="left",
    )
    wo = wo.merge(wards[["ward_code", "low_lying_index"]], on="ward_code", how="left")

    rainfall = _read("rainfall_daily.csv", parse_dates=["date"])
    rain_city = rainfall.groupby("date").rainfall_mm.max()  # worst of the two stations
    # Rain in the 7 days after completion = stress on the fresh repair.
    roll7 = rain_city[::-1].rolling(7, min_periods=1).sum()[::-1]
    wo["rain_7d_after_mm"] = wo.completed_at.dt.normalize().map(roll7).fillna(0)
    wo["heavy_rain_after"] = wo.rain_7d_after_mm >= 200

    # --- complaint -> work order back-link -----------------------------------
    link = wo[["work_order_id", "linked_list"]].explode("linked_list").dropna()
    link = link.rename(columns={"linked_list": "complaint_id"})
    complaints = complaints.merge(link, on="complaint_id", how="left")

    return Data(
        wards=wards, work_orders=wo, rate_card=rate, contractors=contractors,
        complaints=complaints, social=_read("social_posts.csv", parse_dates=["posted_at"]),
        roads=roads, localities=_read("localities.csv"), hotspots=_read("flood_hotspots.csv"),
        rainfall=rainfall, tides=_read("tides.csv", parse_dates=["date"]), traffic=traffic,
        accidents=_read("accidents.csv", parse_dates=["occurred_at"]),
        facilities=_read("facilities.csv"),
        wards_geo=json.loads((DATA_DIR / "wards.geojson").read_text(encoding="utf-8")),
        roads_geo=json.loads((DATA_DIR / "roads.geojson").read_text(encoding="utf-8")),
    )


def inr(x: float) -> str:
    """Format rupees the Indian way: ₹1.23 Cr / ₹4.5 L / ₹12,345."""
    if pd.isna(x):
        return "-"
    x = float(x)
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:.2f} Cr"
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:.1f} L"
    return f"₹{x:,.0f}"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(s).lower())).strip()
