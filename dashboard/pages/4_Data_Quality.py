import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
from components import setup, page_header, btn, html, kpi, grid, card, table, badge, bar, donut, columns_chart
from agents.data_engineering_agent import DataEngineeringAgent

setup("Data Quality")

RAW_DIR = "data/raw"
agent = DataEngineeringAgent()


@st.cache_data(ttl=60, show_spinner=False)
def get_audit(file_path: str):
    return agent.run_audit(file_path)


# Dataset selector
supported = (".csv", ".xlsx", ".xls", ".parquet")
available = [f for f in os.listdir(RAW_DIR) if f.lower().endswith(supported)] if os.path.exists(RAW_DIR) else []

if not available:
    st.warning("No datasets found in `data/raw/`. Please upload a dataset from the Datasets page first.")
    st.stop()

default_idx = 0
if "active_dataset" in st.session_state:
    active_name = os.path.basename(st.session_state["active_dataset"])
    if active_name in available:
        default_idx = available.index(active_name)

_sel_col, _btn_col = st.columns([5, 1])
with _sel_col:
    selected_file = st.selectbox(
        "Select dataset to audit:",
        options=available,
        index=default_idx,
        key="dq_dataset_select"
    )
with _btn_col:
    st.write("")
    if st.button("Force re-audit", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

file_path = os.path.join(RAW_DIR, selected_file)

# Load audit
with st.spinner(f"Data Engineering Agent is auditing '{selected_file}'..."):
    audit_data = get_audit(file_path)

health   = audit_data["health"]
strategy = audit_data["cleaning_strategy"]

score           = int(health["overall_health_score"])
missing_cnt     = health["missing_info"]["total_missing_cells"]
dup_cnt         = health["duplicate_info"]["count"]
type_issues_cnt = len(health["type_issues"])
outlier_info    = health.get("outlier_info", {})
outlier_cnt     = len(outlier_info)

# Page header
page_header(
    "Data Quality",
    f"Monitor, understand, and improve the reliability of <b>{selected_file}</b>.",
    btn("Apply recommended cleaning", True),
    f"{selected_file} &rsaquo; <b>Data Quality</b>"
)

# KPI cards — add outlier KPI
html(grid([
    kpi("Quality Score",  f"{score}%",       "Evaluated by AI Agent",                  "shield"),
    kpi("Missing Values", f"{missing_cnt}",   f"{health['missing_info']['missing_percentage']}% of cells", "warn", "blue", "gray"),
    kpi("Duplicates",     f"{dup_cnt}",        f"{health['duplicate_info']['percentage']}% duplicates",    "copy", "blue"),
    kpi("Type Issues",    f"{type_issues_cnt}", f"{type_issues_cnt} column(s) dirty",                      "braces"),
], "g4"))

# Quality overview
dims = [
    ("Completeness", health["completeness"], "#38bdf8"),
    ("Validity",     health["validity"],     "#4f46e5"),
    ("Uniqueness",   health["uniqueness"],   "#075985"),
    ("Consistency",  health["consistency"],  "#6d28d9")
]
dim_html = "".join(
    f'<div style="margin-bottom:1rem"><div style="display:flex;justify-content:space-between">'
    f'<span>{n}</span><span class="mono">{v}%</span></div>{bar(v, c)}</div>'
    for n, v, c in dims
)
overview = card(
    f'<div style="display:flex;gap:2rem;align-items:center">{donut(score, "#4f46e5", size=190)}'
    f'<div style="flex:1">{dim_html}</div></div>',
    "Quality overview", "Weighted health score across four primary quality dimensions."
)

# Severity breakdown — now includes outliers
high_cnt   = type_issues_cnt
medium_cnt = len(health["missing_info"]["columns"]) + outlier_cnt
total_issues = high_cnt + medium_cnt
severity = card(
    columns_chart(
        [0,
         medium_cnt * 100 // max(total_issues, 1),
         high_cnt  * 100 // max(total_issues, 1)],
        ["Low", "Medium", "High"],
        ["#dbeafe", "#38bdf8", "#fee2e2"], 150
    ) + f'<div style="display:flex;gap:.4rem;margin-top:1rem">'
        f'{badge(f"High {high_cnt}", "red")}'
        f'{badge(f"Medium {medium_cnt}", "blue")}'
        f'{badge("Low 0", "gray")}</div>',
    "Issues by severity",
    f"{total_issues} actionable issues detected."
)
html(f'<div class="bf-grid g21">{overview}{severity}</div>')

# Issues table — 3 categories: type mismatches, missing, outliers
table_rows = []

for col, issue_info in health["type_issues"].items():
    # Use the richer 'detected' field if available, fallback to ratio
    detected_val = issue_info.get("detected") or f"{issue_info.get('valid_numeric_ratio', '-')}% numeric compatible"
    table_rows.append([
        badge("High", "red"),
        f"<span class='mono'>{col}</span>",
        issue_info["issue"],
        detected_val,
        issue_info.get("recommendation", "-")
    ])

if missing_cnt > 0:
    imputation_plan = strategy.get("imputation_plan", {})
    for col, cnt in health["missing_info"]["columns"].items():
        # Read the LLM-chosen strategy per column, fallback to generic text
        col_plan = imputation_plan.get(col, {})
        strat = col_plan.get("strategy", "")
        if strat == "median":
            rec = f"Impute with <b>median</b> (skewed numeric)"
        elif strat == "mean":
            rec = f"Impute with <b>mean</b> (gaussian numeric)"
        elif strat == "mode":
            rec = f"Impute with <b>mode</b> (categorical)"
        elif strat == "constant":
            fill_val = col_plan.get("value", 0)
            rec = f"Fill with constant <b>{fill_val}</b>"
        else:
            rec = "Impute with median / mode"
        table_rows.append([
            badge("Medium", "blue"),
            f"<span class='mono'>{col}</span>",
            "Missing / Empty entries",
            f"{cnt} blank entries",
            rec
        ])

for col, info in outlier_info.items():
    table_rows.append([
        badge("Medium", "blue"),
        f"<span class='mono'>{col}</span>",
        "Statistical outliers (IQR)",
        f"{info['outlier_count']} outliers ({info['outlier_pct']}%)",
        f"Winsorize: cap at [{round(info['lower_bound'], 2)}, {round(info['upper_bound'], 2)}]"
    ])

if not table_rows:
    table_rows = [[badge("None", "green"), "-", "No issues detected", "-", "-"]]

total_cnt = len(table_rows)
issues_table = table(
    ["SEVERITY", "COLUMN", "ISSUE", "DETECTED VALUES", "RECOMMENDATION"],
    table_rows
)
html(card(
    issues_table,
    "Detected issues",
    "Review each issue and apply the recommended remediation.",
    f'<div>{badge(f"All {total_cnt}")} '
    f'{badge(f"High {high_cnt}", "red")} '
    f'{badge(f"Medium {medium_cnt}", "blue")}</div>'
))

html("<br>")

# AI Recommendation banner
summary_text = strategy.get(
    "recommendation_summary",
    f"BIFlow recommends addressing {type_issues_cnt} type mismatches, "
    f"{missing_cnt} missing values, and {outlier_cnt} outlier column(s)."
)
html(f'<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center">'
     f'<div style="flex:1"><b style="font-size:1.1rem">BIFlow AI Recommendation</b> '
     f'{badge("Qwen 2.5 Agent")}<br>{summary_text}</div></div>')

html("<br>")

# Action buttons
col1, col2 = st.columns(2)
with col1:
    if st.button("Preview changes", use_container_width=True):
        with st.spinner("Running preview..."):
            preview = agent.execute_cleaning(file_path, preview_mode=True)
        st.success(
            f"Preview ready! Score: **{score}%** to "
            f"**{preview['health_after']['overall_health_score']}%**"
        )
with col2:
    if st.button("Apply recommended cleaning", type="primary", use_container_width=True):
        with st.spinner("Applying cleaning pipeline..."):
            res = agent.execute_cleaning(file_path, preview_mode=False)
        st.success(
            f"Done! Saved to `{res['cleaned_file_path']}`. "
            f"New score: **{res['health_after']['overall_health_score']}%**"
        )
        st.cache_data.clear()
        st.rerun()