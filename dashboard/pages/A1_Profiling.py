import sys
from pathlib import Path
import streamlit as st

# CRITICAL: Set sidebar mode BEFORE any imports that call setup()
if "sidebar_mode" not in st.session_state or st.session_state.sidebar_mode == "nav":
    st.session_state.sidebar_mode = "agent1"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from components import setup, page_header, html, badge, card, grid, kpi, table

# Explicitly set sidebar mode for agent pages
if "sidebar_mode" not in st.session_state or st.session_state.sidebar_mode == "nav":
    st.session_state.sidebar_mode = "agent1"

setup("Profiling", hub="Agent 1 · Data Engineering")

results = st.session_state.get("pipeline_results", {}).get("agent1", {})
profile = results.get("profile", {})          # flat profiler output
report  = results.get("profiling_report", {}) # structured agent report

page_header(
    "Data Profiling",
    "Column-level structure, roles, distributions and cardinality.",
    badge("Agent 1", "blue"),
    "Agent 1 · Data Engineering > <b>Profiling</b>"
)

if not profile:
    html(
        '<div class="bf-card" style="text-align:center;padding:3rem;color:#94a3b8">'
        '<div style="font-size:2.5rem;margin-bottom:1rem">⚙</div>'
        '<b>No profiling data yet</b><br>'
        '<small>Run a pipeline from the '
        '<a href="/Workflows" style="color:#4338ca">Workflows</a> page first.</small>'
        '</div>'
    )
    st.stop()

# ── Summary KPIs from flat profile dict ───────────────────────────────────────
col_roles  = profile.get("column_roles", {})
col_types  = profile.get("column_types", {})
col_missing = profile.get("missing_values", {})
col_unique  = profile.get("unique_values", {})
total_cols  = profile.get("columns", len(col_roles))

num_cols  = sum(1 for r in col_roles.values() if "numeric" in r or r == "continuous_numeric")
cat_cols  = sum(1 for r in col_roles.values() if r == "categorical")
date_cols = sum(1 for r in col_roles.values() if r in ("timestamp", "datetime"))
id_cols   = sum(1 for r in col_roles.values() if r == "primary_key")

html(grid([
    kpi("Total Columns", str(total_cols),  "Across dataset",          "📋", "indigo"),
    kpi("Numeric",        str(num_cols),    "Numeric / continuous",    "🔢", "blue"),
    kpi("Categorical",    str(cat_cols),    "Text / category columns", "🏷", "blue"),
    kpi("Date / ID",      str(date_cols + id_cols), "Temporal + key columns", "📅", "blue"),
], "g4"))

# ── Per-column table ──────────────────────────────────────────────────────────
# Get LLM reasoning from profiling_report if available
col_profiles_report = report.get("column_profiles", {})

rows = []
for col in profile.get("column_names", list(col_roles.keys())):
    role    = col_roles.get(col, "unknown")
    dtype   = col_types.get(col, "")
    missing = col_missing.get(col, 0)
    unique  = col_unique.get(col, 0)
    total   = profile.get("rows", 1) or 1
    missing_pct = round(missing / total * 100, 1)

    # Pull LLM reasoning from report if available
    cp = col_profiles_report.get(col, {})
    reasoning = cp.get("agent_reasoning", cp.get("business_interpretation", ""))

    role_tone = {
        "continuous_numeric": "blue",
        "categorical":        "purple",
        "timestamp":          "green",
        "boolean":            "amber",
        "primary_key":        "gray",
    }.get(role, "gray")

    role_label = {
        "continuous_numeric": "numeric",
        "primary_key":        "id / key",
        "timestamp":          "datetime",
    }.get(role, role)

    missing_html = (
        f'<span style="color:#b91c1c;font-weight:600">{missing} ({missing_pct}%)</span>'
        if missing > 0 else
        '<span style="color:#166534">0</span>'
    )
    reasoning_html = (
        f'<small style="color:#64748b;display:block;max-width:300px">'
        f'{str(reasoning)[:130]}{"…" if len(str(reasoning)) > 130 else ""}</small>'
        if reasoning else '<small style="color:#cbd5e1">—</small>'
    )

    rows.append([
        f"<span class='mono'><b>{col}</b></span>",
        badge(role_label, role_tone),
        f"<span class='mono' style='font-size:.8rem'>{dtype}</span>",
        missing_html,
        str(unique),
        reasoning_html,
    ])

html(card(
    table(["COLUMN", "ROLE", "TYPE", "MISSING", "UNIQUE", "LLM REASONING"], rows),
    "Column Profiles",
    f"{total_cols} columns analysed by Agent 1",
    badge("LLM-reasoned", "purple") if col_profiles_report else badge("Rule-based", "gray"),
))

# ── Numerical statistics ───────────────────────────────────────────────────────
num_stats = profile.get("numerical_statistics", {})
if num_stats:
    stat_rows = []
    # num_stats is {stat_name: {col: value}} from describe()
    cols_list = list(next(iter(num_stats.values())).keys()) if num_stats else []
    stat_names = list(num_stats.keys())
    for col in cols_list[:15]:  # cap at 15 columns
        row = [f"<span class='mono'><b>{col}</b></span>"]
        for stat in stat_names:
            val = num_stats.get(stat, {}).get(col, "")
            row.append(f"<span class='mono' style='font-size:.82rem'>{round(val,2) if isinstance(val,(int,float)) else val}</span>")
        stat_rows.append(row)
    html(card(
        table(["COLUMN"] + [s.upper() for s in stat_names], stat_rows),
        "Numerical Statistics",
        "Descriptive stats for all numeric columns",
        badge(str(len(cols_list)) + " numeric cols", "blue"),
    ))

# ── Uncertainty flags ─────────────────────────────────────────────────────────
flags = report.get("uncertainty_flags", [])
if flags:
    flag_rows = [[
        f"<span class='mono'>{f.get('column', f.get('col', ''))}</span>",
        f.get("reason", f.get("flag", "")),
        badge("Needs review", "amber"),
    ] for f in flags]
    html(card(
        table(["COLUMN", "REASON", "STATUS"], flag_rows),
        "⚠ Uncertainty Flags",
        "Columns Agent 1 was not confident about — review recommended.",
        badge(str(len(flags)) + " flags", "amber"),
    ))
