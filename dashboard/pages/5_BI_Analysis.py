import html as html_lib
import json
import os
import sys

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
dataset_column, action_column = st.columns([5, 1.5])
with dataset_column:
    dataset_name = st.selectbox(
        "Active dataset",
        datasets,
        index=datasets.index(default_dataset),
        key="bi_analysis_dataset",
    )
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

active_card = f'''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center;margin-bottom:1rem">
  🗄 <small style="color:#4338ca"><b>ACTIVE DATASET</b></small>
  <b>{html_lib.escape(dataset_name)}</b> · {kpis["record_count"]:,} records · {kpis["field_count"]} fields
  <span style="margin-left:auto">{badge("● Cleaned dataset", "green")}</span></div>'''
html(active_card)
st.caption(f"BI results are calculated from the validated cleaned file: `{os.path.basename(analysis_source_path)}`.")

primary_metric_name = next(iter(numeric_metrics), None)
primary_metric = numeric_metrics.get(primary_metric_name, {}) if primary_metric_name else {}
average_label = (
    f"Average {html_lib.escape(primary_metric_name)}"
    if primary_metric_name
    else "Numeric metrics"
)
average_value = f'{primary_metric["mean"]:,.2f}' if primary_metric else "—"
average_subtitle = (
    f'Median {primary_metric["median"]:,.2f}' if primary_metric else "No numeric metrics detected"
)
html(grid([
    kpi("Records", f'{kpis["record_count"]:,}', "Rows analyzed", "👥"),
    kpi(
        "Missing cells",
        f'{kpis["missing_percentage"]:.1f}%',
        f'{kpis["missing_cells"]:,} total',
        "⚠",
        "red",
        "red" if kpis["missing_cells"] else "gray",
    ),
    kpi(average_label, average_value, average_subtitle, "💵"),
    kpi("Duplicate rows", f'{kpis["duplicate_rows"]:,}', "Exact duplicate records", "▦", "blue", "gray"),
], "g4"))

st.subheader("Interactive dashboard")
st.caption(
    "Build and explore charts from the validated cleaned dataset. Use the chart toolbar "
    "to zoom, pan, and inspect values; filters affect the chart below."
)
chart_df = load_dataset(analysis_source_path)
category_columns = [
    column for column in chart_df.columns
    if (
        pd.api.types.is_object_dtype(chart_df[column])
        or isinstance(chart_df[column].dtype, pd.CategoricalDtype)
        or pd.api.types.is_bool_dtype(chart_df[column])
    )
    and 1 < chart_df[column].nunique(dropna=True) <= 50
]
filter_columns = [
    column for column in chart_df.columns
    if (
        pd.api.types.is_object_dtype(chart_df[column])
        or isinstance(chart_df[column].dtype, pd.CategoricalDtype)
        or pd.api.types.is_bool_dtype(chart_df[column])
    )
    and 1 < chart_df[column].nunique(dropna=True) <= 100
]
numeric_columns = chart_df.select_dtypes(include="number").columns.tolist()
chart_options = ["Bar", "Pie", "Line", "Scatter", "Histogram", "Box"]

filter_column = st.selectbox(
    "Filter by category",
    ["No filter"] + filter_columns,
    key=f"bi_chart_filter_column_{dataset_name}",
)
if filter_column != "No filter":
    filter_values = sorted(
        chart_df[filter_column].dropna().astype(str).unique().tolist()
    )
    selected_values = st.multiselect(
        "Keep selected values (leave empty to show all)",
        filter_values,
        key=f"bi_chart_filter_values_{dataset_name}_{filter_column}",
    )
    if selected_values:
        chart_df = chart_df[
            chart_df[filter_column].astype("string").isin(selected_values)
        ]

chart_type = st.selectbox(
    "Chart type",
    chart_options,
    key=f"bi_chart_type_{dataset_name}",
)
figure = None

if chart_type in {"Bar", "Pie", "Line"}:
    if not category_columns:
        st.info("This chart type needs a categorical column with 2–50 distinct values.")
    else:
        dimension = st.selectbox(
            "Category / X axis",
            category_columns,
            key=f"bi_chart_dimension_{dataset_name}_{chart_type}",
        )
        metric_options = ["Record count"] + numeric_columns
        metric = st.selectbox(
            "Value",
            metric_options,
            key=f"bi_chart_metric_{dataset_name}_{chart_type}",
        )
        aggregation = st.selectbox(
            "Aggregation",
            ["Sum", "Mean", "Median"],
            disabled=metric == "Record count",
            key=f"bi_chart_aggregation_{dataset_name}_{chart_type}",
        )
        category_values = chart_df[dimension].fillna("(missing)").astype(str)
        if metric == "Record count":
            chart_data = category_values.value_counts().rename_axis(dimension).reset_index(name="value")
            value_label = "Records"
        else:
            values = pd.to_numeric(chart_df[metric], errors="coerce")
            grouped = pd.DataFrame({dimension: category_values, metric: values}).groupby(
                dimension, dropna=False
            )[metric]
            if aggregation == "Sum":
                chart_data = grouped.sum().reset_index(name="value")
            elif aggregation == "Mean":
                chart_data = grouped.mean().reset_index(name="value")
            else:
                chart_data = grouped.median().reset_index(name="value")
            value_label = f"{aggregation} of {metric}"
        chart_data = chart_data.dropna(subset=["value"]).sort_values(
            "value", ascending=False
        ).head(50)
        if chart_data.empty:
            st.info("No values are available for this chart with the current filter.")
        elif chart_type == "Bar":
            figure = px.bar(
                chart_data, x=dimension, y="value", hover_data={dimension: True, "value": ":,.2f"},
                labels={"value": value_label}, title=f"{value_label} by {dimension}",
            )
        elif chart_type == "Pie":
            if (chart_data["value"] < 0).any() or chart_data["value"].sum() <= 0:
                st.warning("Pie charts require non-negative values with a positive total.")
            else:
                figure = px.pie(
                    chart_data, names=dimension, values="value",
                    title=f"{value_label} by {dimension}", hole=0.35,
                )
        else:
            figure = px.line(
                chart_data.sort_values(dimension), x=dimension, y="value", markers=True,
                labels={"value": value_label}, title=f"{value_label} by {dimension}",
            )
elif chart_type == "Scatter":
    if len(numeric_columns) < 2:
        st.info("A scatter plot needs at least two numeric columns.")
    else:
        scatter_columns = st.columns(2)
        with scatter_columns[0]:
            x_axis = st.selectbox(
                "X axis", numeric_columns, key=f"bi_scatter_x_{dataset_name}"
            )
        y_options = [column for column in numeric_columns if column != x_axis]
        with scatter_columns[1]:
            y_axis = st.selectbox(
                "Y axis", y_options, key=f"bi_scatter_y_{dataset_name}_{x_axis}"
            )
        color_options = ["No grouping"] + category_columns
        color_by = st.selectbox(
            "Color by",
            color_options,
            key=f"bi_scatter_color_{dataset_name}",
        )
        figure = px.scatter(
            chart_df, x=x_axis, y=y_axis,
            color=None if color_by == "No grouping" else color_by,
            title=f"{y_axis} vs {x_axis}",
            hover_data=chart_df.columns[:5].tolist(),
        )
elif chart_type == "Histogram":
    if not numeric_columns:
        st.info("A histogram needs a numeric column.")
    else:
        value_column = st.selectbox(
            "Numeric column",
            numeric_columns,
            key=f"bi_histogram_column_{dataset_name}",
        )
        figure = px.histogram(
            chart_df, x=value_column, nbins=30,
            title=f"Distribution of {value_column}",
        )
else:
    if not numeric_columns:
        st.info("A box plot needs a numeric column.")
    else:
        value_column = st.selectbox(
            "Numeric column",
            numeric_columns,
            key=f"bi_box_value_{dataset_name}",
        )
        box_categories = ["No grouping"] + category_columns
        group_column = st.selectbox(
            "Group by",
            box_categories,
            key=f"bi_box_group_{dataset_name}",
        )
        figure = px.box(
            chart_df,
            x=None if group_column == "No grouping" else group_column,
            y=value_column,
            color=None if group_column == "No grouping" else group_column,
            title=f"Distribution of {value_column}",
        )

if figure is not None:
    figure.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=60, b=20))
    st.plotly_chart(figure, use_container_width=True, key=f"bi_chart_{dataset_name}")

insights = analysis["insights"]
html(
    f'<div style="display:flex;justify-content:space-between">'
    f'<h2>AI Insights</h2>{badge(f"{len(insights)} evidence-based insights")}</div>'
)
insight_cards = []
for item in insights:
    title = html_lib.escape(item["title"])
    finding = html_lib.escape(item["finding"])
    evidence = html_lib.escape(item["evidence"])
    recommendation = html_lib.escape(item["recommendation"])
    confidence = item["confidence"]
    sources = ", ".join(html_lib.escape(column) for column in item["source_columns"])
    insight_cards.append(
        f'''<div class="bf-card">
          <span class="bf-badge blue" style="float:right">● {confidence}% confidence</span>
          <small style="color:#4338ca"><b>DATASET INSIGHT</b></small>
          <h3 style="font-size:1.1rem;margin:.5rem 0">{title}</h3>
          <p style="color:#64748b;font-size:.85rem">{finding}</p>
          <div class="bf-box"><b>Evidence</b><br>{evidence}</div>
          <div class="bf-box"><b>Recommendation</b><br>{recommendation}</div>
          <small>Confidence</small><b style="float:right">{confidence}%</b>{bar(confidence, "#075985")}
          <small>Source columns: {sources or "Dataset-level aggregates"}</small>
        </div>'''
    )
html(grid(insight_cards, "g3"))

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
