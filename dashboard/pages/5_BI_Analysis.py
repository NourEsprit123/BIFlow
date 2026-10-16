import html as html_lib
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
import plotly.express as px
import pandas as pd

from agents.bi_analyst_agent import BIAnalystAgent
from analytics.profiler import load_dataset
from components import (
    badge,
    bar,
    grid,
    html,
    kpi,
    page_header,
    setup,
)

setup("BI Analysis")
page_header(
    "Business Intelligence Analysis",
    "Turn your data into actionable insights.",
    crumbs="Workspace / <b>BI Analysis</b>",
)

RAW_DIR = "data/raw"
SUPPORTED_FORMATS = (".csv", ".xlsx", ".xls", ".parquet")
datasets = sorted(
    name for name in os.listdir(RAW_DIR)
    if name.lower().endswith(SUPPORTED_FORMATS)
) if os.path.isdir(RAW_DIR) else []

dataset_scope = st.session_state.get("workflow_dataset_scope")
if dataset_scope in datasets:
    datasets = [dataset_scope]
    st.info(f"Showing workflow results for **{dataset_scope}** only.")
    if st.button("Show all datasets", key="show_all_bi_datasets"):
        st.session_state.pop("workflow_dataset_scope", None)
        st.rerun()

if not datasets:
    st.info("No datasets found. Go to **Datasets** to upload your first file.")
    st.stop()

active_dataset = st.session_state.get("active_dataset")
active_name = os.path.basename(active_dataset) if active_dataset else None
default_dataset = active_name if active_name in datasets else datasets[0]
dataset_column, workflow_column, action_column = st.columns([4.5, 1.5, 1.5])
with dataset_column:
    dataset_name = st.selectbox(
        "Active dataset",
        datasets,
        index=datasets.index(default_dataset),
        key="bi_analysis_dataset",
    )
with workflow_column:
    st.write("")
    if st.button("✨ Create workflow", key="bi_create_workflow", use_container_width=True):
        st.switch_page("pages/3_Workflows.py")
with action_column:
    st.write("")
    run_analysis = st.button(
        "Refresh analysis",
        type="primary",
        use_container_width=True,
        key="run_bi_analysis",
    )

raw_dataset_path = os.path.join(RAW_DIR, dataset_name)
dataset_stem = os.path.splitext(dataset_name)[0]
workflow_cleaned_path = st.session_state.get("workflow_cleaned_dataset_path")
workflow_cleaned_source = st.session_state.get("workflow_cleaned_dataset_source")
cleaned_candidates = [
    path for path in (
        os.path.join("data", "cleaned", f"{dataset_stem}_cleaned.csv"),
        os.path.join("data", "processed", f"{dataset_stem}_processed.parquet"),
    )
    if os.path.isfile(path)
]
if (
    workflow_cleaned_source == dataset_name
    and workflow_cleaned_path
    and os.path.isfile(workflow_cleaned_path)
):
    cleaned_candidates.insert(0, workflow_cleaned_path)
cleaned_dataset_path = (
    max(dict.fromkeys(cleaned_candidates), key=os.path.getmtime)
    if cleaned_candidates
    else None
)
if (
    cleaned_dataset_path
    and os.path.getmtime(cleaned_dataset_path) < os.path.getmtime(raw_dataset_path)
):
    cleaned_dataset_path = None

run_analysis = run_analysis or (
    st.session_state.get("bi_analysis_dataset") != dataset_name
    or cleaned_dataset_path is None
    or st.session_state.get("bi_analysis_source_path") != cleaned_dataset_path
    or (
        cleaned_dataset_path is not None
        and st.session_state.get("bi_analysis_fingerprint")
        != (
            os.path.getsize(cleaned_dataset_path),
            os.stat(cleaned_dataset_path).st_mtime_ns,
        )
    )
)
if run_analysis:
    st.session_state.pop("bi_analysis_result", None)
    try:
        if cleaned_dataset_path is None:
            with st.spinner(
                f"Running profiling, cleaning, and ETL for {dataset_name}..."
            ):
                pipeline_result = BIAnalystAgent().run_pipeline(raw_dataset_path)
            cleaned_dataset_path = pipeline_result["cleaned_dataset_path"]
            st.session_state["workflow_profile_result"] = {
                "status": pipeline_result["status"],
                "workflow": "profiling",
                "profile": pipeline_result["profile"],
            }
            st.session_state["workflow_profile_dataset"] = dataset_name
            st.session_state["workflow_cleaned_dataset_path"] = cleaned_dataset_path
            st.session_state["workflow_cleaned_dataset_source"] = dataset_name

            result = pipeline_result["analysis"]
        else:
            dataset_stat = os.stat(cleaned_dataset_path)
            dataset_fingerprint = (dataset_stat.st_size, dataset_stat.st_mtime_ns)
            with st.spinner(f"BI Analyst is analyzing cleaned data for {dataset_name}..."):
                result = BIAnalystAgent().analyze(cleaned_dataset_path)
        dataset_stat = os.stat(cleaned_dataset_path)
        dataset_fingerprint = (dataset_stat.st_size, dataset_stat.st_mtime_ns)
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        st.error(f"Profile, cleaning, or BI analysis failed. No fallback was used. Details: {error}")
        st.stop()
    else:
        st.session_state["bi_analysis_result"] = result
        st.session_state["bi_analysis_dataset"] = dataset_name
        st.session_state["bi_analysis_source_path"] = cleaned_dataset_path
        st.session_state["bi_analysis_fingerprint"] = dataset_fingerprint

analysis_source_path = st.session_state.get("bi_analysis_source_path")
if analysis_source_path and os.path.isfile(analysis_source_path):
    current_stat = os.stat(analysis_source_path)
    current_fingerprint = (current_stat.st_size, current_stat.st_mtime_ns)
else:
    current_fingerprint = None

analysis = st.session_state.get("bi_analysis_result")
result_is_current = (
    st.session_state.get("bi_analysis_dataset") == dataset_name
    and st.session_state.get("bi_analysis_fingerprint") == current_fingerprint
)
if not analysis or not result_is_current:
    active_card = f'''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center;margin-bottom:1rem">
      🗄 <small style="color:#4338ca"><b>ACTIVE DATASET</b></small>
      <b>{html_lib.escape(dataset_name)}</b>
      <span style="margin-left:auto">{badge("Analysis required", "amber")}</span></div>'''
    html(active_card)
    st.info("Run the pipeline to profile, clean, and validate this dataset before BI analysis.")
    st.stop()

analysis = st.session_state["bi_analysis_result"]

if analysis.get("fallback_used"):
    fallback_steps = []
    if analysis.get("cleaning_fallback_used"):
        fallback_steps.append("cleaning")
    if analysis.get("insights_fallback_used"):
        fallback_steps.append("insight generation")
    if not fallback_steps:
        fallback_steps.append("insight generation")
    st.warning(
        f"The Groq quota was reached; Python fallback was used for "
        f"{' and '.join(fallback_steps) or 'the unavailable LLM step(s)'}. "
        "KPIs and charts use the validated cleaned dataset."
    )

kpis = analysis["kpis"]
numeric_metrics = kpis["numeric_metrics"]
chart_df = load_dataset(analysis_source_path)
numeric_columns = chart_df.select_dtypes(include="number").columns.tolist()
def find_column(keywords):
    return next(
        (
            column for column in chart_df.columns
            if any(keyword in str(column).lower().replace("_", " ") for keyword in keywords)
        ),
        None,
    )


churn_column = find_column(("churn", "attrition"))
contract_column = find_column(("contract", "subscription plan"))
if contract_column is None and churn_column is not None:
    contract_column = next(
        (
            column for column in chart_df.columns
            if column != churn_column
            and (
                pd.api.types.is_object_dtype(chart_df[column])
                or isinstance(chart_df[column].dtype, pd.CategoricalDtype)
            )
            and 1 < chart_df[column].nunique(dropna=True) <= 12
        ),
        None,
    )
additional_group_column = next(
    (
        column for column in kpis["categorical_distributions"]
        if column not in {churn_column, contract_column}
    ),
    None,
)

churn_rate = None
churn_mask = None
churn_count = 0
if churn_column:
    positive_labels = {
        "yes", "y", "true", "1", "churn", "churned", "attrited",
        "left", "cancelled", "canceled",
    }
    known_churn = chart_df[churn_column].notna()
    churn_mask = (
        chart_df[churn_column].astype("string").str.strip().str.lower()
        .isin(positive_labels)
    )
    if bool((churn_mask & known_churn).any()):
        churn_count = int((churn_mask & known_churn).sum())
        churn_rate = churn_count / max(int(known_churn.sum()), 1) * 100

primary_metric_name = next(iter(numeric_metrics), None)
primary_metric = numeric_metrics.get(primary_metric_name, {}) if primary_metric_name else {}
charge_column = find_column(("monthly charges", "monthly charge", "charges", "revenue", "amount"))
tenure_column = find_column(("tenure", "months"))
date_column = find_column(("date", "time", "month"))
if charge_column not in numeric_metrics:
    charge_column = primary_metric_name
if tenure_column not in numeric_metrics or tenure_column == charge_column:
    tenure_column = next(
        (column for column in numeric_metrics if column != charge_column),
        None,
    )

stat = os.stat(analysis_source_path)
completed_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
html(
    f'''<div class="bf-card" style="background:linear-gradient(110deg,#eef2ff,#f5f3ff);display:flex;gap:1rem;align-items:center;margin-bottom:1rem">
      🗄 <small style="color:#4338ca"><b>ACTIVE DATASET</b></small>
      <b>{html_lib.escape(dataset_name)}</b> · {kpis["record_count"]:,} records · {kpis["field_count"]} fields · Validated {completed_at}
      <span style="margin-left:auto">{badge("● Results ready", "blue")}</span></div>'''
)
html(
    """<style>
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #e8eaf5;
        border-radius: 16px;
        box-shadow: 0 2px 8px rgba(30, 41, 59, .04);
        background: linear-gradient(180deg, #ffffff, #fcfcff);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] h4 {
        color: #1e1b4b;
        letter-spacing: -.01em;
    }
    </style>"""
)

average_label = (
    f"Average {html_lib.escape(primary_metric_name)}"
    if primary_metric_name else "Numeric metrics"
)
average_value = f'{primary_metric["mean"]:,.2f}' if primary_metric else "—"
average_subtitle = (
    f'Median {primary_metric["median"]:,.2f}'
    if primary_metric else "No numeric metrics detected"
)
secondary_label = (
    "Churn Rate" if churn_rate is not None
    else "Missing cells"
)
secondary_value = (
    f"{churn_rate:.1f}%" if churn_rate is not None
    else f'{kpis["missing_percentage"]:.1f}%'
)
secondary_subtitle = (
    f"{churn_count:,} churned records" if churn_rate is not None
    else f'{kpis["missing_cells"]:,} total missing'
)
fourth_label = (
    f"Average {html_lib.escape(tenure_column)}"
    if tenure_column else "Duplicate rows"
)
fourth_value = (
    f'{numeric_metrics[tenure_column]["mean"]:,.1f}'
    if tenure_column else f'{kpis["duplicate_rows"]:,}'
)
fourth_subtitle = (
    f'Median {numeric_metrics[tenure_column]["median"]:,.1f}'
    if tenure_column else "Exact duplicate records"
)
html(grid([
    kpi(
        "Customers" if "customer" in dataset_name.lower() else "Records",
        f'{kpis["record_count"]:,}',
        "Complete population",
        "👥",
    ),
    kpi(
        secondary_label,
        secondary_value,
        secondary_subtitle,
        "👤" if churn_rate is not None else "⚠",
        "red" if churn_rate is not None or kpis["missing_cells"] else "blue",
        "red" if churn_rate is not None or kpis["missing_cells"] else "gray",
    ),
    kpi(average_label, average_value, average_subtitle, "💵"),
    kpi(fourth_label, fourth_value, fourth_subtitle, "📅" if tenure_column else "▦", "blue", "gray"),
], "g4"))

chart_df = chart_df.copy()
chart_df["__bi_churn__"] = churn_mask if churn_mask is not None else False
chart_df["__bi_churn_known__"] = (
    chart_df[churn_column].notna() if churn_column else False
)

distribution_column = churn_column
if distribution_column is None:
    distribution_column = next(iter(kpis["categorical_distributions"]), None)
if distribution_column is None:
    distribution_column = next(
        (
            column for column in chart_df.columns
            if column not in {"__bi_churn__", "__bi_churn_known__"}
            and (
                pd.api.types.is_object_dtype(chart_df[column])
                or isinstance(chart_df[column].dtype, pd.CategoricalDtype)
                or pd.api.types.is_bool_dtype(chart_df[column])
            )
            and 1 < chart_df[column].nunique(dropna=True) <= 10
        ),
        None,
    )

plot_theme = {
    "template": "plotly_white",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"family": "Inter, sans-serif", "color": "#334155", "size": 12},
    "colorway": ["#4f46e5", "#38bdf8", "#a78bfa", "#fb7185", "#14b8a6"],
    "margin": {"l": 12, "r": 12, "t": 20, "b": 12},
    "legend": {"orientation": "h", "y": -0.18},
}

st.markdown("### Customer behaviour")
left_chart, right_chart = st.columns([0.9, 1.1], gap="large")
with left_chart:
    with st.container(border=True):
        st.markdown("#### Churn distribution" if churn_column else "#### Category distribution")
        st.caption(
            "Customer share by churn status"
            if churn_column else "Share of records across the largest available category"
        )
        if distribution_column:
            distribution = (
                chart_df[distribution_column].fillna("(missing)").astype(str)
                .value_counts().rename_axis("category").reset_index(name="records")
            )
            if churn_column and churn_count:
                palette = ["#4f46e5" if value.strip().lower() in positive_labels else "#c7d2fe"
                           for value in distribution["category"]]
            else:
                palette = ["#4f46e5", "#8b5cf6", "#38bdf8", "#14b8a6", "#f59e0b"]
            figure = px.pie(
                distribution,
                names="category",
                values="records",
                hole=0.68,
                color_discrete_sequence=palette,
            )
            figure.update_layout(**plot_theme, showlegend=True)
            if churn_rate is not None:
                figure.add_annotation(
                    text=f"<b>{churn_rate:.1f}%</b><br><span style='font-size:11px'>CHURN</span>",
                    showarrow=False,
                    font={"size": 20, "color": "#0f172a"},
                )
            st.plotly_chart(
                figure,
                use_container_width=True,
                key=f"bi_churn_distribution_{dataset_name}",
            )
            if churn_rate is not None:
                st.markdown(
                    f"Retained **{kpis['record_count'] - churn_count:,}** · "
                    f"Churned **{churn_count:,}**"
                )
        else:
            st.info("No categorical column is available for a distribution chart.")

with right_chart:
    with st.container(border=True):
        st.markdown(
            f"#### Churn by {html_lib.escape(str(contract_column))}"
            if churn_column and contract_column
            else "#### Group comparison"
        )
        st.caption(
            "Observed churn rate across contract groups"
            if churn_column and contract_column
            else "Record counts across the largest available categories"
        )
        if churn_column and contract_column:
            comparison = chart_df.loc[chart_df["__bi_churn_known__"]].groupby(
                contract_column, dropna=False
            )["__bi_churn__"].agg(["mean", "count"]).reset_index()
            comparison["group"] = comparison[contract_column].fillna("(missing)").astype(str)
            comparison["rate"] = comparison["mean"] * 100
            comparison = comparison.sort_values("rate", ascending=True)
            figure = px.bar(
                comparison,
                x="rate",
                y="group",
                orientation="h",
                text=comparison["rate"].map(lambda value: f"{value:.1f}%"),
                color="rate",
                color_continuous_scale=["#c4b5fd", "#4f46e5", "#312e81"],
                labels={"rate": "Churn rate", "group": str(contract_column)},
            )
            figure.update_traces(textposition="outside", cliponaxis=False)
            figure.update_layout(**plot_theme, coloraxis_showscale=False, xaxis_ticksuffix="%")
        elif distribution_column:
            distribution = (
                chart_df[distribution_column].fillna("(missing)").astype(str)
                .value_counts().head(8).rename_axis("group").reset_index(name="records")
                .sort_values("records", ascending=True)
            )
            figure = px.bar(
                distribution,
                x="records",
                y="group",
                orientation="h",
                text="records",
                color="records",
                color_continuous_scale=["#c4b5fd", "#4f46e5"],
                labels={"records": "Records", "group": str(distribution_column)},
            )
            figure.update_traces(textposition="outside", cliponaxis=False)
            figure.update_layout(**plot_theme, coloraxis_showscale=False)
        else:
            figure = None
        if figure is not None:
            st.plotly_chart(
                figure,
                use_container_width=True,
                key=f"bi_contract_comparison_{dataset_name}",
            )
        else:
            st.info("No categorical groups are available to compare.")

st.markdown("### Dataset trends & distributions")
trend_columns = st.columns(3, gap="large")
for index, (title, metric_column, description) in enumerate((
    ("Monthly charges distribution", charge_column, "Record frequency across value bands"),
    ("Customer tenure distribution", tenure_column, "Records across lifecycle stages"),
    (
     "Churn trend" if churn_column and date_column else
     f"Churn by {additional_group_column}" if churn_column and additional_group_column else
     "Numeric metric distribution",
     date_column if churn_column and date_column else primary_metric_name,
     "Observed churn rate over time" if churn_column and date_column else
     f"Observed churn rate by {additional_group_column}"
     if churn_column and additional_group_column else
     "Frequency across the selected measure"),
)):
    with trend_columns[index]:
        with st.container(border=True):
            st.markdown(f"#### {html_lib.escape(title)}")
            st.caption(html_lib.escape(description))
            if index == 2 and churn_column and date_column and metric_column in chart_df.columns:
                trend = pd.DataFrame({
                    "date": pd.to_datetime(chart_df[date_column], errors="coerce"),
                    "churned": chart_df["__bi_churn__"],
                    "known": chart_df["__bi_churn_known__"],
                }).dropna(subset=["date"])
                trend = trend.loc[trend["known"]].assign(
                    period=lambda frame: frame["date"].dt.to_period("M").dt.to_timestamp()
                )
                trend = (
                    trend.groupby("period")["churned"].mean().mul(100)
                    .rename("churn_rate").reset_index()
                )
                if not trend.empty:
                    figure = px.line(
                        trend,
                        x="period",
                        y="churn_rate",
                        markers=True,
                        color_discrete_sequence=["#4f46e5"],
                        labels={"period": "", "churn_rate": "Churn rate"},
                    )
                    figure.update_traces(line={"width": 3}, marker={"size": 7})
                    figure.update_layout(**plot_theme, yaxis_ticksuffix="%", showlegend=False)
                    st.plotly_chart(
                        figure,
                        use_container_width=True,
                        key=f"bi_churn_trend_{dataset_name}",
                    )
                else:
                    st.info("No valid dates are available for a churn trend.")
            elif index == 2 and churn_column and additional_group_column:
                comparison = chart_df.loc[chart_df["__bi_churn_known__"]].groupby(
                    additional_group_column, dropna=False
                )["__bi_churn__"].agg(["mean", "count"]).reset_index()
                comparison["group"] = (
                    comparison[additional_group_column].fillna("(missing)").astype(str)
                )
                comparison["rate"] = comparison["mean"] * 100
                comparison = comparison.sort_values("rate", ascending=True)
                figure = px.bar(
                    comparison,
                    x="rate",
                    y="group",
                    orientation="h",
                    text=comparison["rate"].map(lambda value: f"{value:.1f}%"),
                    color="rate",
                    color_continuous_scale=["#bae6fd", "#0284c7", "#075985"],
                    labels={"rate": "Churn rate", "group": str(additional_group_column)},
                )
                figure.update_traces(textposition="outside", cliponaxis=False)
                figure.update_layout(
                    **plot_theme,
                    coloraxis_showscale=False,
                    xaxis_ticksuffix="%",
                )
                st.plotly_chart(
                    figure,
                    use_container_width=True,
                    key=f"bi_churn_by_group_{dataset_name}",
                )
            elif metric_column and metric_column in chart_df.columns:
                figure = px.histogram(
                    chart_df,
                    x=metric_column,
                    nbins=24,
                    color_discrete_sequence=[
                        ["#38bdf8", "#075985"][index % 2]
                    ],
                    labels={metric_column: str(metric_column)},
                )
                figure.update_traces(marker_line_width=0, opacity=0.9)
                figure.update_layout(**plot_theme, bargap=0.08, showlegend=False)
                st.plotly_chart(
                    figure,
                    use_container_width=True,
                    key=f"bi_distribution_{index}_{dataset_name}",
                )
            elif kpis["missing_cells"]:
                missing_by_column = (
                    chart_df.isna().sum().sort_values(ascending=False).head(10)
                    .rename_axis("column").reset_index(name="missing")
                )
                figure = px.bar(
                    missing_by_column,
                    x="missing",
                    y="column",
                    orientation="h",
                    color_discrete_sequence=["#8b5cf6"],
                )
                figure.update_layout(**plot_theme, showlegend=False)
                st.plotly_chart(
                    figure,
                    use_container_width=True,
                    key=f"bi_missing_{index}_{dataset_name}",
                )
            else:
                st.info("No eligible numeric measure is available for this chart.")

insights = analysis["insights"]
html(
    f'<div style="display:flex;justify-content:space-between;align-items:center;margin:1.5rem 0 .8rem">'
    f'<h2>AI Insights</h2>{badge(f"{len(insights)} evidence-based insights", "blue")}</div>'
)
insight_columns = st.columns(3, gap="large")
for index, item in enumerate(insights):
    title = html_lib.escape(item["title"])
    finding = html_lib.escape(item["finding"])
    evidence = html_lib.escape(item["evidence"])
    recommendation = html_lib.escape(item["recommendation"])
    confidence = item["confidence"]
    sources = ", ".join(html_lib.escape(column) for column in item["source_columns"])
    with insight_columns[index % 3]:
        html(
            f'''<div class="bf-card" style="height:100%;border-top:3px solid #6366f1">
              <span class="bf-badge blue" style="float:right">● {confidence}% confidence</span>
              <small style="color:#4338ca"><b>{sources.upper() or "DATASET INSIGHT"}</b></small>
              <h3 style="font-size:1.05rem;margin:.65rem 0">{title}</h3>
              <p style="color:#64748b;font-size:.88rem;min-height:3.6rem">{finding}</p>
              <small>Confidence</small><b style="float:right">{confidence}%</b>{bar(confidence, "#4f46e5")}
            </div>'''
        )
        with st.expander("✨ Explain this insight"):
            st.markdown(f"**Evidence**  \n{evidence}")
            st.markdown(f"**Recommended action**  \n{recommendation}")
            st.caption(f"Source columns: {sources or 'Dataset-level aggregates'}")

export_json = json.dumps(analysis, indent=2, ensure_ascii=False, allow_nan=False)
st.download_button(
    "⭳ Export report",
    data=export_json,
    file_name=f"{os.path.splitext(dataset_name)[0]}_bi_analysis.json",
    mime="application/json",
)

if st.session_state.get("workflow_dataset_scope") == dataset_name:
    if st.button("Continue to Data Quality", key="bi_open_data_quality"):
        st.session_state["dq_dataset_select"] = dataset_name
        st.switch_page("pages/4_Data_Quality.py")
