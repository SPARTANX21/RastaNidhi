"""Social pulse: classify noisy multilingual posts and find issues people report online but not to BMC."""
from __future__ import annotations

import pandas as pd

from .linker import build_gazetteer, classify
from .data import Data, norm

def post_type(text: str) -> str:
    t = str(text).lower()
    if any(k in t for k in ("fwd", "forward", "unverified", "as received")):
        return "Forward / unverified"
    if any(k in t for k in ("thank", "thanks", "dhanyavad", "धन्यवाद", "great work", "kudos", "fixed overnight")):
        return "Thank-you"
    if any(k in t for k in ("again", "phir se", "back", "har saal", "every year", "same story", "🙄", "wah", "slow clap")):
        return "Repeat / sarcasm"
    if any(k in t for k in ("good morning", "gm all", "school band")) and "flood" not in t:
        return "Chatter"
    return "Fresh report"


def find_locality(text: str, gaz: pd.DataFrame):
    k = " " + norm(text) + " "
    hits = gaz[gaz.key.map(lambda g: len(g) >= 4 and f" {g} " in k)]
    if hits.empty:
        return None, None
    h = hits.loc[hits.key.str.len().idxmax()]
    return h.locality, h.ward_code


def analyse_posts(d: Data, clean_c: pd.DataFrame) -> pd.DataFrame:
    s = d.social.copy()
    gaz = build_gazetteer(d.localities)
    s["post_type"] = s.text.map(post_type)
    cls = s.text.map(lambda t: classify(t, None))
    s["issue_category"] = [c[0] for c in cls]
    locs = s.text.map(lambda t: find_locality(t, gaz))
    s["locality"] = [l[0] for l in locs]
    s["ward_code"] = [l[1] for l in locs]

    # Was there an official complaint for the same locality + category within ±2 days?
    cc = clean_c.dropna(subset=["locality_clean"])
    idx = cc.groupby(["locality_clean", "category_clean"]).received_at.apply(list).to_dict()

    def matched(r):
        times = idx.get((r.locality, r.issue_category), [])
        return any(abs((t - r.posted_at).total_seconds()) <= 2 * 86400 for t in times)
    s["official_complaint_nearby"] = s.apply(lambda r: matched(r) if r.locality and r.issue_category else None, axis=1)
    s["blind_spot"] = (s.post_type.isin(["Fresh report", "Repeat / sarcasm"]) & s.issue_category.notna()
                       & s.locality.notna() & (s.official_complaint_nearby == False))  # noqa: E712
    return s
