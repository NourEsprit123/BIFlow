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
if not results:
    results = (st.session_state.get("wf_graph_state") or {}).get("reports", {}).get("data_engineer", {})
profile = results.get("profile", {})          # flat profiler output
report  = results.get("profiling_report", {}) # structured agent report

page_header(
    "Data Profiling",
    "Column-level structure, roles, distributions and cardinality.",
    badge("Agent 1", "blue"),
    "Agent 1 · Data Engineering > <b>Profiling</b>"
)

# Si profile est manquant mais que profiling_report est présent, reconstruire le profil
if not profile and report:
    col_profiles = report.get("column_profiles", {})
    if col_profiles:
        col_roles = {col: cp.get("inferred_role", "unknown") for col, cp in col_profiles.items()}
        col_types = {col: cp.get("detected_dtype", "") for col, cp in col_profiles.items()}
        col_missing = {col: cp.get("missing_count", 0) for col, cp in col_profiles.items()}
        col_unique = {col: cp.get("unique_count", 0) for col, cp in col_profiles.items()}
        profile = {
            "column_roles": col_roles,
            "column_types": col_types,
            "missing_values": col_missing,
            "unique_values": col_unique,
            "columns": len(col_roles),
            "column_names": list(col_roles.keys()),
        }

if not profile:
    st.info("💡 Aucun profil de données actif en mémoire pour le moment.")
    raw_dir = PROJECT_ROOT / "data" / "raw"
    csv_files = sorted(raw_dir.glob("*.csv")) if raw_dir.exists() else []
    if csv_files:
        default_idx = 0
        cur_p = st.session_state.get("current_dataset_path") or st.session_state.get("wf_file")
        if cur_p:
            cur_name = Path(cur_p).name
            for i, f in enumerate(csv_files):
                if f.name == cur_name:
                    default_idx = i
                    break
        c_sel, c_btn = st.columns([3, 1])
        with c_sel:
            chosen_csv = st.selectbox("Sélectionner un jeu de données à profiler :", [f.name for f in csv_files], index=default_idx, key="prof_ds_sel")
        with c_btn:
            st.write("")
            run_direct_prof = st.button("🚀 Profiler avec l'Agent 1", type="primary", use_container_width=True, key="btn_run_direct_prof")
        if run_direct_prof and chosen_csv:
            with st.spinner("🔍 Analyse et profiling en cours par l'Agent 1..."):
                from agents.data_engineering_agent import DataEngineeringAgent
                agent = DataEngineeringAgent()
                audit_res = agent.run_audit(str(raw_dir / chosen_csv))
                if "pipeline_results" not in st.session_state:
                    st.session_state["pipeline_results"] = {}
                st.session_state["pipeline_results"]["agent1"] = audit_res
                st.session_state["current_dataset_path"] = str(raw_dir / chosen_csv)
            st.rerun()
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
    table(["COLUMN", "ROLE", "TYPE", "MISSING", "UNIQUE", "LLM REASONING"], rows, max_height=420),
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
        table(["COLUMN"] + [s.upper() for s in stat_names], stat_rows, max_height=380),
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
        table(["COLUMN", "REASON", "STATUS"], flag_rows, max_height=300),
        "⚠ Uncertainty Flags",
        "Columns Agent 1 was not confident about — review recommended.",
        badge(str(len(flags)) + " flags", "amber"),
    ))
