"""Complaint clean-up: geocode, fix categories (multilingual), de-duplicate into issues, link to work orders."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Data, haversine_m, nearest_road, norm

# (keyword, weight). Specific nouns beat generic "water" words, which helpline notes append to everything.
KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "Open or broken manhole": [("manhole", 3), ("मैनहोल", 3), ("dhakkan", 3), ("ढक्कन", 3), ("झाकण", 4), ("chamber", 2)],
    "Road cave-in": [("cave", 3), ("sunk", 3), ("sinkhole", 3), ("collapsed", 3), ("dhas", 3), ("dhans", 3),
                     ("धंस", 3), ("खचल", 3), ("pipeline", 2), ("exposed pipe", 3)],
    "Choked drain / nullah overflow": [("drain", 3), ("nullah", 3), ("nala", 2), ("नाला", 3), ("गटार", 2),
                                       ("choked", 3), ("garbage", 2), ("overflow", 2)],
    "Waterlogging": [("waterlog", 3), ("flood", 3), ("paani bhar", 3), ("पानी भर", 3), ("पाणी साच", 3),
                     ("knee", 2), ("ghutne", 2), ("itna paani", 3), ("wading", 3), ("under brown water", 3),
                     ("पंप", 1), ("pump", 1)],
    "Pothole": [("pothole", 3), ("gaddha", 3), ("gadda", 3), ("khadda", 3), ("खड्डा", 3), ("गड्ढा", 3), ("crater", 3)],
    "Broken paver blocks": [("paver", 3), ("block", 2), ("ब्लॉक", 3)],
}
NOISE = ["mosquito", "asdf", "test", "garbage collection", "street light", "noise", "dog"]
ISSUE_WINDOW_H = 72
VAGUE = {"Other", "Road related"}


def build_gazetteer(loc: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in loc.itertuples():
        names = [r.locality] + ([a.strip() for a in str(r.aliases).split(";")] if pd.notna(r.aliases) else [])
        for n in names:
            rows.append(dict(key=norm(n), locality=r.locality, ward_code=r.ward_code, lat=r.lat, lon=r.lon))
    return pd.DataFrame(rows).drop_duplicates("key")


def geocode_text(text: str, gaz: pd.DataFrame, ward: str | None = None) -> pd.Series | None:
    """Exact name/alias match, else prefix match on shortened names ('Vile' -> Vile Parle), preferring the given ward."""
    k = norm(text)
    if not k:
        return None
    hit = gaz[gaz.key == k]
    if hit.empty:
        hit = gaz[gaz.key.str.startswith(k + " ") | gaz.key.str.startswith(k)]
    if hit.empty:  # locality mentioned inside free text
        hit = gaz[gaz.key.map(lambda g: len(g) > 4 and g in k)]
    if hit.empty:
        return None
    if ward and (hit.ward_code == ward).any():
        hit = hit[hit.ward_code == ward]
    return hit.iloc[0]


def classify(desc: str, photo: str) -> tuple[str | None, float]:
    text, ph = str(desc).lower(), str(photo).lower() if pd.notna(photo) else ""
    if any(n in text for n in NOISE) and not any(k in text for kws in KEYWORDS.values() for k, _ in kws):
        return "Not a road issue", 1.0
    scores = {cat: 2 * sum(w for k, w in kws if k in text) + sum(w for k, w in kws if k in ph)
              for cat, kws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    return (best, scores[best] / total) if scores[best] > 0 else (None, 0.0)


def clean_complaints(d: Data) -> pd.DataFrame:
    c = d.complaints.copy()
    gaz = build_gazetteer(d.localities)

    # --- geocode ---
    cache: dict = {}

    def geo(text, ward, desc):
        key = (text, ward)
        if key not in cache:
            cache[key] = geocode_text(text, gaz, ward)
        hit = cache[key]
        return hit if hit is not None else geocode_text(desc, gaz)
    locs = [geo(t, w if pd.notna(w) else None, ds) for t, w, ds in zip(c.locality_text, c.ward_code, c.description)]
    c["locality_clean"] = [l.locality if l is not None else None for l in locs]
    c["ward_clean"] = c.ward_code.fillna(pd.Series([l.ward_code if l is not None else None for l in locs], index=c.index))
    c["geo_source"] = np.where(c.lat.notna(), "GPS", np.where(c.locality_clean.notna(), "Gazetteer", "Unknown"))
    c["lat_clean"] = c.lat.fillna(pd.Series([l.lat if l is not None else np.nan for l in locs], index=c.index))
    c["lon_clean"] = c.lon.fillna(pd.Series([l.lon if l is not None else np.nan for l in locs], index=c.index))
    # GPS points without a ward: snap to nearest locality
    miss = c.ward_clean.isna() & c.lat_clean.notna()
    for i in c[miss].index:
        dist = haversine_m(c.at[i, "lat_clean"], c.at[i, "lon_clean"], d.localities.lat.values, d.localities.lon.values)
        j = int(np.argmin(dist))
        c.at[i, "ward_clean"] = d.localities.ward_code.iloc[j]
        c.at[i, "locality_clean"] = c.at[i, "locality_clean"] or d.localities.locality.iloc[j]

    # --- category correction ---
    # Evidence order, measured against work-order work_type on 4,948 linked complaints:
    #   photo description 100% · citizen-picked category 83.5% · free-text keywords 78.5%.
    # So: trust the photo; otherwise keep the citizen's pick unless it is vague; use text only as last resort.
    cats, srcs = [], []
    for rep, desc, photo in zip(c.category_reported, c.description, c.photo_description):
        p = classify("", photo)[0] if pd.notna(photo) else None
        if p:
            cats.append(p); srcs.append("Photo")
        elif rep not in VAGUE:
            cats.append(rep); srcs.append("Citizen category")
        else:
            t = classify(desc, None)[0]
            cats.append(t or "Unclassified"); srcs.append("Text (multilingual keywords)" if t else "None")
    c["category_clean"], c["category_source"] = cats, srcs
    c["category_changed"] = c.category_clean != c.category_reported

    # --- road: from linked work order if any, else nearest segment ---
    wo_road = d.work_orders.set_index("work_order_id").road_id
    c["road_id_clean"] = c.work_order_id.map(wo_road)
    need = c.road_id_clean.isna() & c.lat_clean.notna()
    c.loc[need, "road_id_clean"] = [nearest_road(r.lat_clean, r.lon_clean, d.roads, r.ward_clean)[0]
                                   for r in c[need].itertuples()]
    return assign_issues(c, d)


def assign_issues(c: pd.DataFrame, d: Data) -> pd.DataFrame:
    """Group complaints about the same thing (ward + locality + category, within 72h of the last report)."""
    c = c.sort_values("received_at").copy()
    c["issue_id"] = None
    key = c.ward_clean.fillna("?") + "|" + c.locality_clean.fillna(c.locality_text.map(norm)) + "|" + c.category_clean
    # complaints BMC already linked to one work order are one issue by definition
    n = 0
    open_issue: dict[str, tuple[str, pd.Timestamp]] = {}
    wo_issue: dict[str, str] = {}
    for i, k, t, w in zip(c.index, key, c.received_at, c.work_order_id):
        if pd.notna(w) and w in wo_issue:
            iid = wo_issue[w]
        elif k in open_issue and (t - open_issue[k][1]).total_seconds() <= ISSUE_WINDOW_H * 3600:
            iid = open_issue[k][0]
        else:
            n += 1
            iid = f"ISS-{n:05d}"
        open_issue[k] = (iid, t)
        if pd.notna(w):
            wo_issue.setdefault(w, iid)
        c.at[i, "issue_id"] = iid
    return c.sort_index()


def issues_table(c: pd.DataFrame, d: Data) -> pd.DataFrame:
    wo = d.work_orders.set_index("work_order_id")
    g = c.groupby("issue_id")
    iss = g.agg(
        ward_code=("ward_clean", "first"), locality=("locality_clean", "first"),
        category=("category_clean", lambda s: s.mode().iat[0]), road_id=("road_id_clean", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
        first_reported=("received_at", "min"), last_reported=("received_at", "max"),
        reports=("complaint_id", "size"), channels=("channel", lambda s: ", ".join(sorted(set(s)))),
        upvotes=("upvotes", "sum"), languages=("language", lambda s: ", ".join(sorted(set(s)))),
        work_order_id=("work_order_id", lambda s: s.dropna().iat[0] if s.notna().any() else None),
        statuses=("status", lambda s: ", ".join(sorted(set(s)))),
        complaint_ids=("complaint_id", lambda s: "|".join(s)),
    ).reset_index()

    def outcome(r):
        if r.work_order_id:
            return "Fixed – failed within 30d" if wo.at[r.work_order_id, "reopened_within_30d"] == "Y" else "Fixed – held"
        if "Not a road issue" == r.category or "Rejected" in r.statuses:
            return "Rejected / not BMC"
        if "Forwarded" in r.statuses:
            return "Forwarded to other agency"
        return "Never fixed (open)"
    iss["outcome"] = iss.apply(outcome, axis=1)
    return iss


def dedup_quality(c: pd.DataFrame, d: Data) -> dict:
    """How well our issue grouping agrees with BMC's own links and duplicate closures."""
    linked = c.dropna(subset=["work_order_id"])
    wt = linked.work_order_id.map(d.work_orders.set_index("work_order_id").work_type)
    per_wo = linked.groupby("work_order_id").issue_id.nunique()
    dup = c[c.status == "Closed - Duplicate"]
    dup_merged = dup.issue_id.map(c.issue_id.value_counts()).gt(1).mean()
    return dict(
        complaints=len(c), issues=c.issue_id.nunique(),
        wo_kept_together_pct=100 * (per_wo == 1).mean(),
        bmc_duplicates_merged_pct=100 * dup_merged,
        categories_corrected=int(c.category_changed.sum()),
        category_accuracy_raw_pct=100 * (linked.category_reported == wt).mean(),
        category_accuracy_clean_pct=100 * (linked.category_clean == wt).mean(),
        geocoded_pct=100 * c.ward_clean.notna().mean(),
    )
