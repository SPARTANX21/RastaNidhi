"""ML models for the next-rupee planner.

1. FailureModel  – P(fix fails within 30 days | method, contractor, road, ward, season).
   Used to choose the method *and* contractor with the lowest expected cost per lasting fix.
   Only features known at assignment time are used (no post-repair rain), so it can be applied to open issues.
2. DemandModel   – expected new issues per ward per week given a rain scenario (Poisson GLM).
   Used to size a monsoon reserve: "if 250 mm falls next week, keep ₹X ready in ward L".

A road-level "where will the next complaint be" model was tried and dropped: on a time-based
hold-out it ranked roads no better than their historical average (Spearman 0.32 vs 0.32).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.compose import make_column_transformer
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.metrics import brier_score_loss, mean_poisson_deviance, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .data import Data

CAT = ["work_type", "repair_method", "contractor_id", "ward_code", "road_type", "surface", "under_dlp", "bus_route"]
NUM = ["low_lying_index", "congestion_index_0_10", "peak_hour_vehicles", "road_age_y", "prior_jobs_road", "month", "severity"]


def _road_feats(d: Data) -> pd.DataFrame:
    return d.roads[["road_id", "surface", "congestion_index_0_10", "peak_hour_vehicles"]]


def failure_frame(d: Data) -> pd.DataFrame:
    wo = d.work_orders.merge(_road_feats(d), on="road_id", how="left")
    wo["road_age_y"] = (wo.assigned_at - wo.last_resurfaced).dt.days / 365
    wo = wo.sort_values("assigned_at")
    wo["prior_jobs_road"] = wo.groupby("road_id").cumcount()
    wo["month"] = wo.assigned_at.dt.month
    wo["y"] = (wo.reopened_within_30d == "Y").astype(int)
    return wo


def _pipe(cat, num):
    pre = make_column_transformer((OneHotEncoder(handle_unknown="ignore"), cat), (StandardScaler(), num))
    return make_pipeline(pre, LogisticRegression(max_iter=3000, C=0.5))


@dataclass
class FailureModel:
    model: object = None
    metrics: dict = field(default_factory=dict)
    coefs: pd.DataFrame | None = None
    contractor_cost_ratio: pd.Series | None = None
    ward_contractors: dict | None = None

    @classmethod
    def train(cls, d: Data) -> "FailureModel":
        f = failure_frame(d)
        X, y = f[CAT + NUM], f.y
        cv = StratifiedKFold(5, shuffle=True, random_state=0)
        p = cross_val_predict(_pipe(CAT, NUM), X, y, cv=cv, method="predict_proba")[:, 1]
        p_base = cross_val_predict(_pipe(["work_type", "repair_method"], []), X, y, cv=cv, method="predict_proba")[:, 1]
        m = _pipe(CAT, NUM).fit(X, y)
        names = m[0].get_feature_names_out()
        coefs = pd.DataFrame({"feature": names, "coef": m[-1].coef_[0]})
        coefs["feature"] = coefs.feature.str.replace(r"^(onehotencoder|standardscaler)__", "", regex=True)
        # calibration table (deciles of predicted risk vs observed)
        calib = pd.DataFrame({"p": p, "y": y}).assign(bin=lambda x: pd.qcut(x.p, 5, labels=False, duplicates="drop"))
        calib = calib.groupby("bin").agg(predicted=("p", "mean"), observed=("y", "mean"), jobs=("y", "size")).reset_index(drop=True)
        return cls(
            model=m,
            metrics=dict(
                cv_auc=roc_auc_score(y, p), baseline_auc=roc_auc_score(y, p_base),
                cv_brier=brier_score_loss(y, p), base_rate=y.mean(), n=len(y), calibration=calib,
            ),
            coefs=coefs,
            contractor_cost_ratio=f.groupby("contractor_id").cost_ratio.median(),
            ward_contractors=f.groupby("ward_code").contractor_id.apply(lambda s: sorted(set(s))).to_dict(),
        )

    def options_for(self, d: Data, issue: pd.Series, methods: pd.DataFrame) -> pd.DataFrame:
        """Score every (method, contractor) combination available for this issue."""
        road = d.roads.set_index("road_id").loc[issue.road_id] if issue.road_id in set(d.roads.road_id) else None
        if road is None:
            return pd.DataFrame()
        meths = methods[methods.work_type == issue.category]
        contractors = self.ward_contractors.get(issue.ward_code, [])
        prior = int((d.work_orders.road_id == issue.road_id).sum())
        rows = []
        for mrow in meths.itertuples():
            for ct in contractors:
                rows.append(dict(
                    work_type=issue.category, repair_method=mrow.repair_method, contractor_id=ct,
                    ward_code=issue.ward_code, road_type=road.road_type, surface=road.surface,
                    under_dlp=road.under_dlp, bus_route=road.bus_route, low_lying_index=issue.low_lying_index,
                    congestion_index_0_10=road.congestion_index_0_10, peak_hour_vehicles=road.peak_hour_vehicles,
                    road_age_y=(issue.first_reported - road.last_resurfaced).days / 365, prior_jobs_road=prior,
                    month=issue.first_reported.month, severity=_sev(issue.category),
                    standard_cost_inr=mrow.standard_cost_inr,
                ))
        o = pd.DataFrame(rows)
        if o.empty:
            return o
        o["p_fail"] = self.model.predict_proba(o[CAT + NUM])[:, 1]
        o["expected_bill_inr"] = o.standard_cost_inr * o.contractor_id.map(self.contractor_cost_ratio)
        o["cost_per_lasting_fix_inr"] = o.expected_bill_inr / (1 - o.p_fail)
        names = d.contractors.set_index("contractor_id").contractor_name
        o["contractor_name"] = o.contractor_id.map(names)
        return o.sort_values("cost_per_lasting_fix_inr")

    def recommend_all(self, d: Data, ranked: pd.DataFrame, methods: pd.DataFrame, capacity_factor: float = 1.5) -> pd.DataFrame:
        """Greedy assignment in risk order. Each contractor can take at most `capacity_factor` × its historical
        share of jobs, so the best performer isn't handed the whole city."""
        share = d.work_orders.contractor_id.value_counts(normalize=True)
        cap = np.ceil(share * len(ranked) * capacity_factor).to_dict()
        load: dict[str, int] = {}
        out = []
        for _, r in ranked.iterrows():
            o = self.options_for(d, r, methods)
            if o.empty:
                out.append({}); continue
            free = o[o.contractor_id.map(lambda c: load.get(c, 0) < cap.get(c, 0))]
            o = free if not free.empty else o
            hi_risk = r.risk_score >= ranked.risk_score.quantile(0.6)
            best = o.sort_values(["p_fail", "expected_bill_inr"]).iloc[0] if hi_risk else o.iloc[0]
            load[best.contractor_id] = load.get(best.contractor_id, 0) + 1
            cheapest = o.sort_values("expected_bill_inr").iloc[0]
            out.append(dict(
                ml_method=best.repair_method, ml_contractor=best.contractor_name, ml_p_fail=best.p_fail,
                ml_bill_inr=best.expected_bill_inr, ml_cost_per_lasting_fix_inr=best.cost_per_lasting_fix_inr,
                cheapest_option=f"{cheapest.repair_method} / {cheapest.contractor_name}",
                cheapest_p_fail=cheapest.p_fail, options=len(o),
            ))
        return pd.concat([ranked.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def _sev(cat):
    from .data import CATEGORY_SEVERITY
    return CATEGORY_SEVERITY.get(cat, 3)


# ---------------------------------------------------------------------------- demand


def demand_frame(d: Data, clean: pd.DataFrame) -> pd.DataFrame:
    c = clean[(clean.category_clean != "Not a road issue") & clean.ward_clean.notna()]
    first = c.sort_values("received_at").groupby("issue_id").first()  # one row per issue, at first report
    first["week"] = first.received_at.dt.to_period("W-SUN").dt.start_time
    weeks = pd.date_range(first.week.min(), first.week.max(), freq="W-MON")
    grid = pd.MultiIndex.from_product([d.wards.ward_code, weeks], names=["ward_code", "week"])
    y = first.groupby(["ward_clean", "week"]).size().rename_axis(["ward_code", "week"]).reindex(grid, fill_value=0)
    df = y.rename("issues").reset_index()
    rain = d.rainfall.groupby("date").rainfall_mm.max()
    rw = rain.resample("W-MON", label="left", closed="left").agg(["sum", "max"])
    tide = d.tides.groupby("date").big_tide_flag.apply(lambda s: (s == "Y").any()).resample("W-MON", label="left", closed="left").sum()
    df["rain_week_mm"] = df.week.map(rw["sum"]).fillna(0)
    df["rain_peak_day_mm"] = df.week.map(rw["max"]).fillna(0)
    df["big_tide_days"] = df.week.map(tide).fillna(0)
    return df.merge(d.wards[["ward_code", "low_lying_index"]], on="ward_code")


def _demand_X(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.get_dummies(df.ward_code, prefix="w", dtype=float)
    lr = np.log1p(df.rain_week_mm)
    X["log_rain"] = lr
    X["log_rain_x_lowlying"] = lr * df.low_lying_index
    X["log_peak"] = np.log1p(df.rain_peak_day_mm)
    X["big_tide_days"] = df.big_tide_days
    return X


@dataclass
class DemandModel:
    model: object = None
    columns: list | None = None
    metrics: dict = field(default_factory=dict)
    cost_per_issue: pd.Series | None = None
    history: pd.DataFrame | None = None

    @classmethod
    def train(cls, d: Data, clean: pd.DataFrame) -> "DemandModel":
        df = demand_frame(d, clean)
        X = _demand_X(df)
        cut = pd.Timestamp("2025-08-25")  # train Jun–Aug, test Sep onward
        tr, te = df.week < cut, df.week >= cut
        m = PoissonRegressor(alpha=1e-3, max_iter=2000).fit(X[tr], df.issues[tr])
        p = m.predict(X[te])
        base = df[tr].groupby("ward_code").issues.mean().reindex(df[te].ward_code).values
        city = pd.DataFrame({"week": df.week[te], "y": df.issues[te], "p": p}).groupby("week").sum()
        metrics = dict(
            test_deviance=mean_poisson_deviance(df.issues[te], np.clip(p, 1e-6, None)),
            baseline_deviance=mean_poisson_deviance(df.issues[te], np.clip(base, 1e-6, None)),
            city_weekly_corr=np.corrcoef(city.y, city.p)[0, 1],
            mae_ward_week=np.abs(df.issues[te] - p).mean(),
            mae_baseline=np.abs(df.issues[te] - base).mean(),
            backtest=city.reset_index(),
        )
        m = PoissonRegressor(alpha=1e-3, max_iter=2000).fit(X, df.issues)  # refit on all data
        wo = d.work_orders
        cpi = wo.groupby("ward_code").cost_inr.sum() / wo.groupby("ward_code").size()
        return cls(model=m, columns=list(X.columns), metrics=metrics, cost_per_issue=cpi, history=df)

    def scenario(self, d: Data, rain_week_mm: float, peak_day_mm: float, big_tide_days: int) -> pd.DataFrame:
        df = d.wards[["ward_code", "ward_name", "low_lying_index"]].copy()
        df["rain_week_mm"], df["rain_peak_day_mm"], df["big_tide_days"] = rain_week_mm, peak_day_mm, big_tide_days
        X = _demand_X(df).reindex(columns=self.columns, fill_value=0)
        df["expected_issues"] = self.model.predict(X)
        df["reserve_inr"] = df.expected_issues * df.ward_code.map(self.cost_per_issue)
        return df.sort_values("expected_issues", ascending=False)
