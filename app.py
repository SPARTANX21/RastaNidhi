"""Follow the Rupee – Mumbai Monsoon Roads Management System.

Run:  streamlit run app.py
"""
from __future__ import annotations

import os
import re

import pandas as pd
import plotly.express as px
import streamlit as st

from core import audit, linker, llm, planner, scorecard, social
from core.data import inr, load_all

st.set_page_config(page_title="Follow the Rupee · Mumbai Roads", page_icon="🌧️", layout="wide")


# ------------------------------------------------------------------ engine (cached)
@st.cache_resource(show_spinner="Crunching 2,499 work orders and 6,501 complaints…")
def engine():
    d = load_all()
    flags = audit.run_audit(d)
    clean = linker.clean_complaints(d)
    issues = linker.issues_table(clean, d)
    methods = planner.method_stats(d)
    return dict(
        d=d, flags=flags, clean=clean, issues=issues,
        csc=scorecard.contractor_scorecards(d, flags),
        wsc=scorecard.ward_scorecards(d, flags),
        ranked=planner.rank_open_issues(d, issues),
        methods=methods,
        chronic=planner.chronic_roads(d),
        posts=social.analyse_posts(d, clean),
        quality=linker.dedup_quality(clean, d),
    )


E = engine()
d, flags, wsc, csc = E["d"], E["flags"], E["wsc"], E["csc"]
WARDS = list(d.wards.ward_code)


def recs(df: pd.DataFrame, n: int = 15) -> list[dict]:
    return df.head(n).round(3).to_dict("records")


def plain(row: pd.Series) -> dict:
    """Series -> JSON-friendly dict with floats rounded."""
    out = {}
    for k, v in row.to_dict().items():
        v = v.item() if hasattr(v, "item") else v
        out[k] = round(v, 3) if isinstance(v, float) else v
    return out


def money_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = out[c].map(inr)
    return out


def claude_on() -> bool:
    """Claude runs only when a key is set AND the sidebar switch is on."""
    return llm.has_credentials() and st.session_state.get("use_claude", True)


def claude_box(label: str, key: str, fn, *args):
    """Button that calls Claude and keeps the result in session state."""
    if not llm.has_credentials():
        st.info("🔑 Add an Anthropic API key in the sidebar to generate this with Claude.")
        return
    if not claude_on():
        st.info("Claude is switched off in the sidebar. All numbers on this page still work.")
        return
    if st.button(f"✨ {label}", key=f"btn_{key}"):
        with st.spinner("Claude is writing…"):
            st.session_state[key] = fn(*args)
    if key in st.session_state:
        st.markdown(st.session_state[key])


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("🌧️💰 Follow the Rupee")
    st.caption("Mumbai Monsoon Roads · synthetic data, fictional contractors")
    page = st.radio("Module", [
        "🏠 City overview", "💰 Ward money trail", "🔍 Repair auditor", "📋 Scorecards",
        "🧭 Next-rupee planner", "🔗 Complaint linker", "💬 Mera Complaint (citizen bot)", "📣 Social pulse",
    ])
    st.divider()
    lang = st.selectbox("Report language", ["English", "Marathi (मराठी)", "Hindi (हिंदी)", "Hinglish"])
    key = st.text_input("Anthropic API key", type="password", help="Optional. Enables Claude narratives and the citizen bot.")
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
        llm.reset_client()
    st.toggle("Use Claude", value=True, key="use_claude", help="Switch off to run without Claude. Every number is still computed.")
    st.caption(("🟢 Claude on · " + llm.MODEL) if claude_on() else
               "⚪ Claude switched off – numbers still work" if llm.has_credentials() else "⚪ Claude off (no key) – numbers still work")


# ================================================================== pages
if page == "🏠 City overview":
    st.header("Where did Mumbai's monsoon road money go?")
    risk = audit.money_at_risk(flags)
    wo = d.work_orders
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Spent (Jun–Oct 2025)", inr(wo.cost_inr.sum()), f"of {inr(d.wards.monsoon_repair_budget_inr_2025.sum())} budget")
    c2.metric("Work orders", f"{len(wo):,}", f"{(wo.sla_met == 'Y').mean():.0%} met SLA")
    c3.metric("Spent on fixes that failed ≤30d", inr(wo.loc[wo.reopened_within_30d == 'Y', 'cost_inr'].sum()),
              f"{(wo.reopened_within_30d == 'Y').mean():.0%} re-opened", delta_color="inverse")
    c4.metric("Money needing review", inr(risk.amount_at_risk_inr.sum()), f"{len(risk)} work orders", delta_color="off")
    c5.metric("Open issues (never fixed)", f"{(E['issues'].outcome == 'Never fixed (open)').sum()}",
              f"from {E['quality']['complaints']:,} complaints")

    metric = st.segmented_control("Colour wards by", ["Budget used %", "Money needing review", "Re-open rate", "Open complaints"],
                                  default="Budget used %")
    col = {"Budget used %": "budget_used_pct", "Money needing review": "money_at_risk_inr",
           "Re-open rate": "reopen_rate", "Open complaints": "open_complaints"}[metric or "Budget used %"]
    left, right = st.columns([3, 2])
    with left:
        fig = px.choropleth_map(wsc, geojson=d.wards_geo, locations="ward_code", featureidkey="properties.ward_code",
                                color=col, color_continuous_scale="OrRd", hover_name="ward_name",
                                hover_data={"budget_used_pct": ":.0f", "money_at_risk_inr": ":,.0f", "reopen_rate": ":.0%"},
                                center={"lat": 19.07, "lon": 72.87}, zoom=9.6, opacity=0.65, height=560)
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")
    with right:
        b = wsc.sort_values("budget_used_pct", ascending=True)
        fig = px.bar(b, x="budget_used_pct", y="ward_code", orientation="h", height=560,
                     color=b.budget_used_pct > 100, color_discrete_map={True: "#d62728", False: "#4c78a8"},
                     labels={"budget_used_pct": "% of monsoon budget spent", "ward_code": ""})
        fig.add_vline(x=100, line_dash="dash")
        fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

    st.subheader("What the audit found")
    s = flags.groupby(["category", "rule"]).agg(work_orders=("work_order_id", "nunique"), amount=("amount_at_risk_inr", "sum")).reset_index()
    s["meaning"] = s.rule.map(audit.RULES)
    st.dataframe(money_cols(s, ["amount"]), hide_index=True, width="stretch")


elif page == "💰 Ward money trail":
    ward = st.selectbox("Ward", WARDS, format_func=lambda w: f"{w} – {d.wards.set_index('ward_code').ward_name[w]}")
    row = wsc.set_index("ward_code").loc[ward]
    trail = scorecard.ward_money_trail(d, ward)
    st.header(f"Ward {ward}: {row.ward_name}")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Budget", inr(row.monsoon_repair_budget_inr_2025))
    c2.metric("Spent", inr(row.spend_inr), f"{row.budget_used_pct:.0f}% used",
              delta_color="inverse" if row.budget_used_pct > 100 else "normal")
    c3.metric("Failed-fix spend", inr(row.failed_fix_spend_inr), f"{row.reopen_rate:.0%} re-opened", delta_color="inverse")
    c4.metric("Needs review", inr(row.money_at_risk_inr))
    c5.metric("SLA met", f"{row.sla_rate:.0%}", f"low-lying index {row.low_lying_index}", delta_color="off")

    a, b = st.columns(2)
    with a:
        st.subheader("By contractor")
        fig = px.pie(trail["by_contractor"], names="contractor_name", values="spend_inr", hole=0.5, height=330)
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(money_cols(trail["by_contractor"], ["spend_inr"]).style.format({"reopen_rate": "{:.0%}", "sla_rate": "{:.0%}"}),
                     hide_index=True, width="stretch")
    with b:
        st.subheader("By repair method")
        bm = trail["by_method"].assign(held=lambda x: x.spend_inr - x.failed_spend_inr)
        fig = px.bar(bm, y="repair_method", x=["held", "failed_spend_inr"], orientation="h", height=330,
                     labels={"value": "₹", "repair_method": "", "variable": ""},
                     color_discrete_map={"held": "#4c78a8", "failed_spend_inr": "#d62728"})
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")
        st.subheader("Spend by month")
        st.bar_chart(trail["by_month"].set_index("month"), height=200)

    st.subheader("📝 One-page report for the corporator")
    wf = flags[(flags.ward_code == ward) & (flags.category == "Suspicious billing")]
    top = E["ranked"][E["ranked"].ward_code == ward]
    claude_box("Write ward report", f"memo_{ward}_{lang}", llm.ward_memo,
               plain(row) | {"ward_code": ward},
               {k: recs(v) for k, v in trail.items() if k != "work_orders"},
               recs(wf[["work_order_id", "rule", "reason", "amount_at_risk_inr"]], 12),
               recs(top[["locality", "category", "road_name", "risk_score", "repair_method", "cost_to_bmc_inr", "reasons"]], 6),
               lang)
    with st.expander(f"All {len(trail['work_orders'])} work orders in this ward"):
        st.dataframe(trail["work_orders"][["work_order_id", "completed_at", "road_name", "work_type", "repair_method",
                                           "contractor_name", "cost_inr", "cost_ratio", "sla_met", "reopened_within_30d",
                                           "engineer_remark"]], hide_index=True)


elif page == "🔍 Repair auditor":
    st.header("Repair auditor")
    st.caption("Deterministic rules – every flag links to a work order. Normal jobs vary 20–30% around the rate card; "
               f"we flag only >{audit.OVERBILL_RATIO}×. 'Needs review' is not an accusation.")
    f1, f2, f3, f4 = st.columns(4)
    cat = f1.multiselect("Category", ["Suspicious billing", "Performance"], default=["Suspicious billing"])
    rules = f2.multiselect("Rule", sorted(flags.rule.unique()), default=[])
    wsel = f3.multiselect("Ward", WARDS)
    csel = f4.multiselect("Contractor", sorted(flags.contractor_name.unique()))
    f = flags[flags.category.isin(cat)]
    if rules:
        f = f[f.rule.isin(rules)]
    if wsel:
        f = f[f.ward_code.isin(wsel)]
    if csel:
        f = f[f.contractor_name.isin(csel)]
    c1, c2, c3 = st.columns(3)
    c1.metric("Flags", len(f))
    c2.metric("Work orders", f.work_order_id.nunique())
    c3.metric("Amount involved", inr(f.amount_at_risk_inr.sum()))
    piv = f.pivot_table(index="contractor_name", columns="rule", values="work_order_id", aggfunc="count", fill_value=0)
    if not piv.empty:
        st.plotly_chart(px.imshow(piv, text_auto=True, aspect="auto", color_continuous_scale="Reds", height=330),
                        width="stretch")
    show = f[["work_order_id", "rule", "severity", "ward_code", "road_name", "contractor_name", "repair_method",
              "cost_inr", "amount_at_risk_inr", "reason", "evidence"]].sort_values("amount_at_risk_inr", ascending=False)
    st.dataframe(show, hide_index=True, width="stretch", height=380,
                 column_config={"cost_inr": st.column_config.NumberColumn(format="₹%d"),
                                "amount_at_risk_inr": st.column_config.NumberColumn(format="₹%d")})
    st.download_button("⬇️ Download flags (CSV)", show.to_csv(index=False).encode("utf-8"), "audit_flags.csv", "text/csv")

    st.subheader("Inspect a work order")
    wid = st.selectbox("Work order", show.work_order_id.unique()[:500] if len(show) else d.work_orders.work_order_id)
    if wid:
        w = d.work_orders.set_index("work_order_id").loc[wid]
        a, b = st.columns(2)
        a.json({k: str(w[k]) for k in ["ward_code", "road_name", "under_dlp", "last_resurfaced", "work_type", "repair_method",
                                        "contractor_name", "assigned_at", "completed_at", "area_sqm", "cost_inr",
                                        "expected_cost_inr", "sla_hours", "sla_met", "reopened_within_30d", "engineer_remark",
                                        "linked_complaint_ids"]})
        b.dataframe(flags[flags.work_order_id == wid][["rule", "reason"]], hide_index=True)
        same = d.work_orders[(d.work_orders.road_id == w.road_id)][["work_order_id", "assigned_at", "repair_method",
                                                                     "contractor_name", "cost_inr", "linked_complaint_ids"]]
        b.caption(f"All jobs on {w.road_name} ({w.road_id})")
        b.dataframe(same, hide_index=True, height=220)
    st.subheader("🧑‍💼 What should the ward officer check first?")
    claude_box("Explain these flags", f"explain_{hash(tuple(show.work_order_id.head(25)))}", llm.explain_flags,
               recs(show, 25))


elif page == "📋 Scorecards":
    st.header("Fair scorecards")
    with st.expander("How we keep it fair", expanded=False):
        st.markdown(
            "- **Durability** and **speed** compare each contractor with what was *expected for their job mix*: the same "
            "work type, in equally flood-prone wards, with the same rain in the week after the fix (indirect standardisation).\n"
            "- An observed/expected ratio of **1.0 = as expected**; below 1 is better than peers in the same conditions.\n"
            "- Small samples are shrunk toward 1.0, so a contractor isn't judged on a handful of jobs.\n"
            "- **Cost** counts only over-billing (>1.4× rate card) and double-billing. DLP payments are shown but not "
            "scored, because recovering them is partly BMC's process.\n"
            "- Weights: durability 40%, speed 30%, cost 30%. Grades: A ≥80, B ≥65, C ≥50, D ≥35, E <35.")
    tab1, tab2 = st.tabs(["Contractors", "Wards"])
    with tab1:
        view = csc[["grade", "overall_score", "contractor_name", "jobs", "spend_inr", "reopen_rate", "exp_reopen_rate",
                    "durability_score", "sla_rate", "speed_score", "median_cost_ratio", "overbilled", "double_billed",
                    "dlp_paid", "cost_score", "money_at_risk_inr"]]
        st.dataframe(view, hide_index=True, width="stretch", column_config={
            "spend_inr": st.column_config.NumberColumn("spend", format="₹%d"),
            "money_at_risk_inr": st.column_config.NumberColumn("needs review", format="₹%d"),
            "reopen_rate": st.column_config.NumberColumn("re-open", format="%.2f"),
            "exp_reopen_rate": st.column_config.NumberColumn("expected re-open", format="%.2f"),
            "sla_rate": st.column_config.NumberColumn("SLA met", format="%.2f"),
            "overall_score": st.column_config.ProgressColumn("score", min_value=0, max_value=100, format="%d"),
        })
        fig = px.scatter(csc, x="speed_score", y="durability_score", size="spend_inr", color="grade", text="contractor_name",
                         height=420, labels={"speed_score": "Speed (context-adjusted)", "durability_score": "Durability (context-adjusted)"},
                         category_orders={"grade": list("ABCDE")})
        fig.update_traces(textposition="top center")
        st.plotly_chart(fig, width="stretch")
        who = st.selectbox("Contractor scorecard", csc.contractor_name)
        r = csc[csc.contractor_name == who].iloc[0]
        a, b, c, e = st.columns(4)
        a.metric("Grade", r.grade, f"{r.overall_score:.0f}/100", delta_color="off")
        b.metric("Re-open rate", f"{r.reopen_rate:.0%}", f"expected {r.exp_reopen_rate:.0%}", delta_color="off")
        c.metric("SLA met", f"{r.sla_rate:.0%}")
        e.metric("Billing flags", int(r.overbilled + r.double_billed), f"{int(r.dlp_paid)} DLP payments", delta_color="off")
        ex = flags[(flags.contractor_name == who) & (flags.category == "Suspicious billing")]
        claude_box("Write citizen scorecard", f"card_{who}_{lang}", llm.contractor_card,
                   plain(r),
                   recs(ex[["work_order_id", "rule", "reason"]], 8), lang)
    with tab2:
        wv = wsc[["ward_code", "ward_name", "low_lying_index", "monsoon_repair_budget_inr_2025", "spend_inr", "budget_used_pct",
                  "failed_fix_spend_inr", "money_at_risk_inr", "sla_rate", "reopen_rate", "open_complaints", "top_contractor"]]
        st.dataframe(wv, hide_index=True, width="stretch", column_config={
            "monsoon_repair_budget_inr_2025": st.column_config.NumberColumn("budget", format="₹%d"),
            "spend_inr": st.column_config.NumberColumn("spent", format="₹%d"),
            "budget_used_pct": st.column_config.ProgressColumn("budget used", min_value=0, max_value=130, format="%.0f%%"),
            "failed_fix_spend_inr": st.column_config.NumberColumn("failed-fix spend", format="₹%d"),
            "money_at_risk_inr": st.column_config.NumberColumn("needs review", format="₹%d"),
            "sla_rate": st.column_config.NumberColumn(format="%.2f"), "reopen_rate": st.column_config.NumberColumn(format="%.2f"),
        })


elif page == "🧭 Next-rupee planner":
    st.header("Where should the next rupee go?")
    ward = st.selectbox("Ward", WARDS, format_func=lambda w: f"{w} – {d.wards.set_index('ward_code').ward_name[w]}")
    row = wsc.set_index("ward_code").loc[ward]
    default_budget = max(float(row.remaining_budget_inr), 0.0)
    c1, c2 = st.columns([1, 2])
    budget = c1.number_input("Budget available (₹)", min_value=0, value=int(default_budget) if default_budget else 500_000,
                             step=50_000, help="Defaults to unspent monsoon budget. Over-spent wards default to ₹5 L top-up.")
    if row.remaining_budget_inr < 0:
        c2.warning(f"Ward {ward} has already over-spent its monsoon budget by {inr(-row.remaining_budget_inr)}. "
                   "Showing a hypothetical top-up.")
    else:
        c2.info(f"Unspent monsoon budget: {inr(row.remaining_budget_inr)}")
    with st.expander("Risk score weights (0–100)"):
        st.write(planner.WEIGHTS)
        st.caption("Severity from category · flood hotspot threshold within 1 km + ward low-lying index · congestion, volume, "
                   "bus route · accidents caused by road condition (fatal ×10) · hospitals/schools whose access road this is · "
                   "number of reports and upvotes · days open · tide-sensitive hotspot.")
    plan = planner.allocate(E["ranked"], ward, budget)
    t_rank = st.container()
    with t_rank:
        if plan.empty:
            st.success("No open road issues in this ward. 🎉")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Open issues", len(plan))
            c2.metric("Fundable now", int(plan.fits_budget.sum()), inr((plan.cost_to_bmc_inr * plan.fits_budget).sum()))
            c3.metric("Free under DLP", int((plan.under_dlp == "Y").sum()), "send to original contractor", delta_color="off")
            st.dataframe(plan[["fits_budget", "risk_score", "locality", "category", "road_name", "repair_method", "cost_to_bmc_inr",
                               "why", "reasons", "reports", "first_reported", "issue_id"]],
                         hide_index=True, width="stretch",
                         column_config={"risk_score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                                        "cost_to_bmc_inr": st.column_config.NumberColumn("cost to BMC", format="₹%d"),
                                        "fits_budget": st.column_config.CheckboxColumn("fund")})
            fcols = [f"f_{k}" for k in planner.WEIGHTS]
            top = plan.head(10).assign(label=lambda x: x.locality + " · " + x.category)
            fig = px.bar(top, y="label", x=fcols, orientation="h", height=380, labels={"value": "risk points", "label": ""},
                         title="What drives the top 10")
            fig.update_layout(yaxis=dict(autorange="reversed"), legend_title="")
            st.plotly_chart(fig, width="stretch")
        a, b = st.columns(2)
        with a:
            st.subheader("Which method lasts?")
            st.dataframe(E["methods"][["work_type", "repair_method", "jobs", "reopen_rate", "standard_cost_inr", "cost_per_lasting_fix"]],
                         hide_index=True, column_config={"reopen_rate": st.column_config.NumberColumn(format="%.2f"),
                                                         "standard_cost_inr": st.column_config.NumberColumn(format="₹%d"),
                                                         "cost_per_lasting_fix": st.column_config.NumberColumn(format="₹%d")})
        with b:
            st.subheader("Stop patching: chronic roads")
            ch = E["chronic"][E["chronic"].ward_code == ward]
            st.dataframe(ch[["road_name", "jobs", "failures", "spend_inr", "under_dlp", "resurface_estimate_inr"]], hide_index=True,
                         column_config={"spend_inr": st.column_config.NumberColumn("patching spend", format="₹%d"),
                                        "resurface_estimate_inr": st.column_config.NumberColumn("resurface est.*", format="₹%d")})
            st.caption("*Resurfacing estimate assumes ₹1,100/sqm × 3.5 m lanes – not in the rate card; indicative only.")
        claude_box("Explain the plan for the corporator", f"plan_{ward}_{budget}_{lang}", llm.plan_explainer, ward, budget,
                   recs(plan[["fits_budget", "risk_score", "locality", "category", "road_name", "repair_method", "cost_to_bmc_inr",
                              "why", "reasons"]], 12) if not plan.empty else [],
                   recs(ch, 5), lang)


elif page == "🔗 Complaint linker":
    st.header("From messy complaints to issues to work orders")
    q = E["quality"]
    c = st.columns(6)
    c[0].metric("Complaints", f"{q['complaints']:,}")
    c[1].metric("Distinct issues", f"{q['issues']:,}", f"-{1 - q['issues'] / q['complaints']:.0%} duplicates", delta_color="off")
    c[2].metric("Geocoded", f"{q['geocoded_pct']:.0f}%")
    c[3].metric("Category accuracy", f"{q['category_accuracy_clean_pct']:.1f}%", f"+{q['category_accuracy_clean_pct'] - q['category_accuracy_raw_pct']:.1f} pts vs raw")
    c[4].metric("BMC duplicates merged", f"{q['bmc_duplicates_merged_pct']:.0f}%")
    c[5].metric("Work orders kept whole", f"{q['wo_kept_together_pct']:.0f}%")
    st.caption("Category evidence order was measured, not assumed: photo description agrees with the work order's work type "
               "100% of the time, the citizen's pick 83%, free-text keywords 78%. Accuracy is checked on the 4,948 linked complaints.")
    iss = E["issues"]
    a, b = st.columns([1, 2])
    with a:
        fig = px.pie(iss, names="outcome", hole=0.5, height=320, title="What happened to each issue")
        st.plotly_chart(fig, width="stretch")
        cl = E["clean"]
        st.dataframe(cl.groupby(["language"]).agg(complaints=("complaint_id", "size"),
                                                  recategorised=("category_changed", "sum")).reset_index(), hide_index=True)
    with b:
        o = st.multiselect("Outcome", sorted(iss.outcome.unique()), default=["Never fixed (open)"])
        w = st.multiselect("Ward ", WARDS)
        v = iss[iss.outcome.isin(o)] if o else iss
        if w:
            v = v[v.ward_code.isin(w)]
        st.dataframe(v[["issue_id", "ward_code", "locality", "category", "reports", "channels", "languages", "first_reported",
                        "work_order_id", "outcome", "statuses"]].sort_values("reports", ascending=False),
                     hide_index=True, height=420, width="stretch")
    iid = st.text_input("Drill into an issue (e.g. ISS-00012)")
    if iid:
        st.dataframe(E["clean"][E["clean"].issue_id == iid.strip()][[
            "complaint_id", "received_at", "channel", "language", "category_reported", "category_clean", "category_source",
            "description", "locality_text", "locality_clean", "ward_clean", "status", "work_order_id"]], hide_index=True)


elif page == "💬 Mera Complaint (citizen bot)":
    st.header("💬 Mera Complaint – what happened to my complaint?")
    st.caption("Ask in English, Hinglish, मराठी or हिंदी. Try: “BMC25-000005 ka kya hua?” · “Hindmata madhe paani "
               "complaint keli hoti, kay jhala?” · “What happened to the pothole complaints in Andheri East?”")
    clean, wo = E["clean"], d.work_orders.set_index("work_order_id")
    gaz = linker.build_gazetteer(d.localities)

    def lookup(q: str) -> dict:
        ids = re.findall(r"BMC25-\d{6}", q.upper())
        def wo_info(wid):
            if pd.isna(wid):
                return None
            w = wo.loc[wid]
            return dict(work_order_id=wid, contractor=w.contractor_name, method=w.repair_method, cost_inr=w.cost_inr,
                        rate_card_expected_inr=round(w.expected_cost_inr), completed_at=w.completed_at,
                        sla_hours=w.sla_hours, sla_met=w.sla_met, fix_failed_within_30d=w.reopened_within_30d,
                        engineer_remark=w.engineer_remark, road=w.road_name,
                        audit_flags=flags[flags.work_order_id == wid].reason.tolist())
        if ids:
            out = []
            for cid in ids:
                r = clean[clean.complaint_id == cid]
                if r.empty:
                    out.append(dict(complaint_id=cid, found=False)); continue
                r = r.iloc[0]
                same = clean[clean.issue_id == r.issue_id]
                wid = r.work_order_id if pd.notna(r.work_order_id) else same.work_order_id.dropna().head(1).squeeze() if same.work_order_id.notna().any() else None
                out.append(dict(complaint_id=cid, found=True, received_at=r.received_at, locality=r.locality_clean,
                                ward=r.ward_clean, category=r.category_clean, status=r.status, resolved_at=r.resolved_at,
                                other_reports_of_same_issue=len(same) - 1, work_order=wo_info(wid)))
            return {"complaints": out}
        loc, _ = social.find_locality(q, gaz)
        if not loc:
            return {"found": False, "hint": "No complaint ID or known locality in the question."}
        cat, _ = linker.classify(q, None)
        iss = E["issues"][E["issues"].locality == loc]
        if cat and cat in set(iss.category):
            iss = iss[iss.category == cat]
        iss = iss.sort_values("last_reported", ascending=False).head(4)
        return {"locality": loc, "category_guess": cat, "recent_issues": [
            dict(issue_id=r.issue_id, category=r.category, first_reported=r.first_reported, reports=r.reports,
                 outcome=r.outcome, road=r.road_id, work_order=wo_info(r.work_order_id)) for r in iss.itertuples()]}

    def template(ctx: dict) -> str:
        if "complaints" in ctx:
            lines = []
            for c in ctx["complaints"]:
                if not c["found"]:
                    lines.append(f"❌ {c['complaint_id']} not found."); continue
                w = c["work_order"]
                s = f"**{c['complaint_id']}** ({c['category']}, {c['locality']}) – status **{c['status']}**."
                if w:
                    s += (f" Fixed under {w['work_order_id']} by {w['contractor']} on {w['completed_at']:%d %b %Y} using "
                          f"{w['method']} for {inr(w['cost_inr'])} (rate card ≈ {inr(w['rate_card_expected_inr'])}). "
                          f"SLA {'met ✅' if w['sla_met'] == 'Y' else 'missed ⏱️'}. "
                          f"{'⚠️ The fix failed within 30 days.' if w['fix_failed_within_30d'] == 'Y' else 'The fix held ✅.'}")
                lines.append(s)
            return "\n\n".join(lines)
        if not ctx.get("found", True):
            return "I couldn't find that. Please share your complaint ID (e.g. BMC25-000123) or the locality name."
        return f"Recent issues in **{ctx['locality']}**:\n\n" + "\n".join(
            f"- {i['issue_id']}: {i['category']}, first reported {i['first_reported']:%d %b}, {i['reports']} reports → **{i['outcome']}**"
            for i in ctx["recent_issues"])

    st.session_state.setdefault("chat", [])
    for m in st.session_state.chat:
        st.chat_message(m["role"]).markdown(m["content"])
    if q := st.chat_input("Type your question…"):
        st.session_state.chat.append({"role": "user", "content": q})
        st.chat_message("user").markdown(q)
        ctx = lookup(q)
        with st.chat_message("assistant"):
            with st.spinner("Looking up…"):
                ans = llm.citizen_answer(q, ctx) if claude_on() else template(ctx)
            st.markdown(ans)
            with st.expander("Evidence used"):
                st.json(ctx, expanded=False)
        st.session_state.chat.append({"role": "assistant", "content": ans})


elif page == "📣 Social pulse":
    st.header("📣 Social pulse – what people say online")
    p = E["posts"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Posts", len(p))
    c2.metric("Located", f"{p.locality.notna().mean():.0%}")
    c3.metric("Blind spots", int(p.blind_spot.sum()), "reported online, no official complaint ±2 days", delta_color="off")
    a, b = st.columns(2)
    a.plotly_chart(px.histogram(p, x="post_type", color="source", height=320), width="stretch")
    bs = p[p.blind_spot].groupby(["ward_code", "locality", "issue_category"]).agg(
        posts=("post_id", "size"), engagement=("likes_or_forwards", "sum")).reset_index().sort_values("engagement", ascending=False)
    b.plotly_chart(px.bar(bs.head(12), x="engagement", y="locality", color="issue_category", orientation="h", height=320,
                          title="Top blind spots by engagement"), width="stretch")
    t = st.multiselect("Post type", sorted(p.post_type.unique()), default=["Fresh report", "Repeat / sarcasm"])
    v = p[p.post_type.isin(t)] if t else p
    st.dataframe(v[["post_id", "posted_at", "source", "text", "post_type", "issue_category", "locality", "ward_code",
                    "official_complaint_nearby", "blind_spot", "likes_or_forwards"]], hide_index=True, width="stretch", height=380)
    claude_box("Ask Claude to classify 25 of these posts (sarcasm, forwards, Marathi…)", "social_cls",
               llm.classify_posts, recs(v[["post_id", "text"]], 25))
