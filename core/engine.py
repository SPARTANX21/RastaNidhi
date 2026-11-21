"""Builds every computed table once and keeps it in memory (shared by the web server)."""
from __future__ import annotations

import warnings
from functools import lru_cache

from . import audit, linker, ml, planner, scorecard, social
from .data import load_all

warnings.filterwarnings("ignore")


@lru_cache(maxsize=1)
def build() -> dict:
    d = load_all()
    flags = audit.run_audit(d)
    clean = linker.clean_complaints(d)
    issues = linker.issues_table(clean, d)
    methods = planner.method_stats(d)
    fm = ml.FailureModel.train(d)
    dm = ml.DemandModel.train(d, clean)
    return dict(
        d=d, flags=flags, clean=clean, issues=issues, methods=methods, fm=fm, dm=dm,
        csc=scorecard.contractor_scorecards(d, flags),
        wsc=scorecard.ward_scorecards(d, flags),
        ranked=planner.rank_open_issues(d, issues),
        chronic=planner.chronic_roads(d),
        posts=social.analyse_posts(d, clean),
        quality=linker.dedup_quality(clean, d),
        gazetteer=linker.build_gazetteer(d.localities),
    )
