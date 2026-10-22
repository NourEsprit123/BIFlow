import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from components import setup, page_header, html, badge, card, table

if "sidebar_mode" not in st.session_state or st.session_state.sidebar_mode == "nav":
    st.session_state.sidebar_mode = "agent1"

setup("ETL & Cleaning", hub="Agent 1 · Data Engineering")

results = st.session_state.get("pipeline_results", {}).get("agent1", {})
report = results.get("profiling_report", {})
strategy = results.get("cleaning_strategy", {})

page_header(
    "ETL & Cleaning",
    "Review Agent 1's cleaning recommendations and ETL hints.",
    badge("Agent 1", "blue"),
    "Agent 1 · Data Engineering > <b>ETL & Cleaning</b>",
)

if not report:
    html(
        '<div class="bf-card" style="text-align:center;padding:3rem;color:#94a3b8">'
        '<b>No ETL recommendations yet</b><br>'
        '<small>Run a pipeline from the <a href="/Workflows">Workflows</a> page first.</small>'
        '</div>'
    )
    st.stop()

etl_hints = report.get("etl_hints", {})
rows = []
for column, dtype in etl_hints.get("type_casting_targets", {}).items():
    rows.append(["Type conversion", column, f"Cast to {dtype}"])
for column, plan in strategy.get("imputation_plan", report.get("imputation_plan", {})).items():
    rows.append(["Missing values", column, f"Suggested strategy: {plan.get('strategy', 'review')}"])
for column, mapping in etl_hints.get("synonym_mappings", {}).items():
    rows.append(["Category normalization", column, f"{len(mapping)} suggested mappings"])
for column in strategy.get("numeric_waterfall_columns", []):
    rows.append(["Numeric parsing", column, "Review dirty numeric values"])
for column in report.get("outlier_columns", []):
    rows.append(["Outliers", column, "Review detected outliers"])
for column in etl_hints.get("drop_candidates", []):
    rows.append(["Schema", column, "Review before dropping"])

if rows:
    html(card(table(["AREA", "COLUMN", "RECOMMENDATION"], rows),
              "Cleaning & ETL recommendations",
              "Suggestions from Agent 1; review before applying transformations."))
else:
    html(card("No cleaning or ETL recommendations were returned.", "Recommendations"))

summary = report.get("agent_summary", strategy.get("recommendation_summary", ""))
if summary:
    html(card(summary, "Agent 1 summary"))

if etl_hints.get("join_key_candidates"):
    html(card(", ".join(etl_hints["join_key_candidates"]), "Join key candidates"))

html(card(
    f"Recommended output format: {etl_hints.get('recommended_output_format', 'parquet')}",
    "ETL output hint",
))
