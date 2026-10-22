import sys
import time
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from components import setup, page_header, btn, html, badge, card, grid, kpi, bar
from chat_widget import render_chat

render_chat("Workflows")
setup("Workflows")

# ── Session state defaults ────────────────────────────────────────────────────
if "pipeline_state" not in st.session_state:
    st.session_state.pipeline_state = "idle"
if "pipeline_step"  not in st.session_state:
    st.session_state.pipeline_step = 0
if "pipeline_file"  not in st.session_state:
    st.session_state.pipeline_file = None
if "pipeline_results" not in st.session_state:
    st.session_state.pipeline_results = {}

step  = st.session_state.pipeline_step
state = st.session_state.pipeline_state

# ── Page header ───────────────────────────────────────────────────────────────
if state == "idle":
    page_header(
        "Create Analysis Workflow",
        "Configure and launch an autonomous multi-agent pipeline on your dataset.",
        "",
        "Workspace > <b>New Analysis</b>"
    )
elif state == "running":
    page_header(
        "Pipeline Running...",
        f"Agent {step} of 3 is processing your dataset.",
        "",
        "Workspace > <b>Running Pipeline</b>"
    )
else:
    page_header(
        "Analysis Complete",
        "All agents have finished. Review results below.",
        btn("+ New Analysis", True),
        "Workspace > <b>Results</b>"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# SETUP FORM (only shown when idle)
# ═══════════════════════════════════════════════════════════════════════════════
if state == "idle":

    def section(n, title, sub, body):
        return (
            f'<div style="display:grid;grid-template-columns:1fr 3fr;gap:1.5rem;margin-bottom:1.5rem">'
            f'<div><b style="background:#4338ca;color:#fff;border-radius:50%;padding:.1rem .55rem">{n}</b> '
            f'<b>{title}</b><br><small style="color:#64748b">{sub}</small></div>'
            f'<div>{body}</div></div>'
        )

    # Step 1: Dataset picker
    raw_dir = PROJECT_ROOT / "data" / "raw"
    all_files = (
        sorted(raw_dir.glob("*.csv")) +
        sorted(raw_dir.glob("*.xlsx")) +
        sorted(raw_dir.glob("*.parquet"))
    )
    file_names = [f.name for f in all_files]

    if not file_names:
        st.warning("No datasets found in data/raw/. Please upload a file.")
        st.stop()

    selected_name = st.selectbox("Select dataset", file_names, label_visibility="collapsed")
    selected_path = str(raw_dir / selected_name)

    dataset_card = (
        '<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center">🗄 '
        '<div><b>' + selected_name + '</b> <span class="bf-badge blue">Data Source</span><br>'
        '<small>Selected from data/raw/ &nbsp;·&nbsp; <b style="color:#4338ca">Change above ↑</b></small></div>'
        '</div>'
    )
    html(section("1", "Select dataset", "Choose your data source", dataset_card))

    # Step 2: Task selection
    TASKS = [
        ("Data Profiling",     "Understand structure, distributions, column roles & cardinality", "Agent 1", "~30s",  True),
        ("Data Quality Check", "Detect missing, invalid, duplicates, outliers & cross-column issues", "Agent 1", "~45s", True),
        ("Data Cleaning",      "Standardize, impute, convert types and treat outliers", "Agent 1", "~60s", True),
        ("KPI Analysis",       "Calculate churn velocity, revenue risk, LTV & business KPIs",      "Agent 2", "~40s",  True),
        ("Trend Analysis",     "Reveal temporal churn shifts across rolling cohorts",               "Agent 2", "~30s",  False),
        ("Anomaly Detection",  "Surface statistical outliers and abrupt pattern spikes",            "Agent 2", "~30s",  False),
        ("AI Insights",        "Generate actionable natural language business findings",            "Agent 2", "~50s",  True),
        ("XAI / Audit",        "Explain and trace every metric calculation end-to-end",             "Agent 3", "~30s",  True),
    ]

    task_cols = st.columns(2)
    selected_tasks = {}
    for i, (t, d, agent, dur, default) in enumerate(TASKS):
        with task_cols[i % 2]:
            col_chk, col_info = st.columns([0.07, 0.93])
            with col_chk:
                checked = st.checkbox("", value=default, key=f"task_{i}", label_visibility="collapsed")
            with col_info:
                tone = "blue" if "Agent 1" in agent else ("purple" if "Agent 2" in agent else "indigo")
                html(
                    f'<div style="padding:.1rem 0 .55rem">'
                    f'<b style="font-size:.93rem;color:#0f172a">{t}</b> '
                    f'<span class="bf-badge {tone}" style="font-size:.65rem">{agent}</span> '
                    f'<span style="color:#94a3b8;font-size:.75rem">{dur}</span>'
                    f'<br><small style="color:#64748b;font-size:.8rem">{d}</small></div>'
                )
            selected_tasks[t] = checked

    selected_count = sum(1 for v in selected_tasks.values() if v)

    # Step 3: Preferences
    prefs_html = (
        '<div class="bf-card" style="margin-bottom:.7rem;display:flex;justify-content:space-between">'
        '<div><b>AI explanation depth</b><br><small>Include step-by-step reasoning trails per column</small></div>'
        + badge("ENABLED", "blue") + '</div>'
        '<div class="bf-card" style="display:flex;justify-content:space-between">'
        '<div><b>Sandbox validation</b><br><small>Generate and test custom check functions per column</small></div>'
        + badge("ENABLED", "blue") + '</div>'
    )
    html(section("3", "Preferences", "Pipeline settings", prefs_html))

    # Launch button
    html(
        '<div class="bf-card" style="display:flex;gap:1rem;align-items:center">'
        + badge(str(selected_count) + " tasks selected")
        + " " + selected_name
        + ' <span style="margin-left:auto"></span></div>'
    )

    col_save, col_run = st.columns([3, 1])
    with col_run:
        launch = st.button("▷  Run BIFlow Pipeline", type="primary", use_container_width=True)

    if launch:
        st.session_state.pipeline_state = "running"
        st.session_state.pipeline_step  = 1
        st.session_state.pipeline_file  = selected_path
        st.session_state.pipeline_results = {}
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNING — Agent 1: Data Engineering
# ═══════════════════════════════════════════════════════════════════════════════
elif state == "running" and step == 1:

    file_path = st.session_state.pipeline_file

    st.info("⚙ **Agent 1 — Data Engineering** is running: profiling dataset and auditing quality...")
    prog = st.progress(0, text="Loading dataset...")

    try:
        from agents.data_engineering_agent import DataEngineeringAgent
        agent = DataEngineeringAgent()

        prog.progress(20, text="Running statistical profiling...")
        result = agent.run_audit(file_path)
        prog.progress(100, text="Agent 1 complete ✓")

        st.session_state.pipeline_results["agent1"] = result
        st.session_state.pipeline_step = 2
        time.sleep(0.5)
        st.rerun()

    except Exception as e:
        st.error(f"Agent 1 failed: {e}")
        st.session_state.pipeline_state = "idle"
        st.session_state.pipeline_step  = 0
        if st.button("Retry"):
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNING — Agent 2: BI Analyst (stub — to be implemented)
# ═══════════════════════════════════════════════════════════════════════════════
elif state == "running" and step == 2:

    st.info("📊 **Agent 2 — BI Analyst** would run here (not yet implemented)...")
    prog = st.progress(0, text="Agent 2 processing...")

    # Simulate for now
    for i in range(0, 101, 20):
        prog.progress(i, text=f"BI analysis... {i}%")
        time.sleep(0.3)

    st.session_state.pipeline_step = 3
    st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNING — Agent 3: XAI Auditor (stub)
# ═══════════════════════════════════════════════════════════════════════════════
elif state == "running" and step == 3:

    st.info("🧠 **Agent 3 — XAI Auditor** would run here (not yet implemented)...")
    prog = st.progress(0, text="Auditing...")

    for i in range(0, 101, 25):
        prog.progress(i, text=f"XAI audit... {i}%")
        time.sleep(0.2)

    st.session_state.pipeline_state = "done"
    st.session_state.pipeline_step  = 4   # all done
    # Auto-navigate to Agent 1 Profiling page with sidebar open
    st.session_state.sidebar_mode = "agent1"
    st.switch_page("pages/A1_Profiling.py")


# ═══════════════════════════════════════════════════════════════════════════════
# DONE — Show Results
# ═══════════════════════════════════════════════════════════════════════════════
elif state == "done":

    results = st.session_state.pipeline_results
    agent1  = results.get("agent1", {})
    health  = agent1.get("health", {})
    profile = agent1.get("profile", {})
    report  = agent1.get("profiling_report", {})
    strategy = agent1.get("cleaning_strategy", {})

    overall = health.get("overall_health_score", 0)
    missing_count = health.get("missing_info", {}).get("total_missing_cells", 0)
    issue_count   = len(health.get("type_issues", {}))
    dup_count     = health.get("duplicate_info", {}).get("count", 0)

    # KPI summary
    html(grid([
        kpi("Quality Score",  str(overall) + "%",     "From Agent 1 audit", "shield",
            "blue" if overall >= 90 else "amber"),
        kpi("Missing Values", str(missing_count),      "Detected by Agent 1", "warning", "blue", "gray"),
        kpi("Duplicates",     str(dup_count),           "Row-level", "copy", "blue"),
        kpi("Type Issues",    str(issue_count),         "Columns flagged", "type", "blue"),
    ], "g4"))

    # Agent 1 summary
    agent_summary = report.get("agent_summary", strategy.get("recommendation_summary", ""))
    if agent_summary:
        html(
            '<div class="bf-card" style="background:#eef2ff;margin-top:1rem">'
            '<b>Agent 1 says:</b> ' + agent_summary + '</div>'
        )

    # Issues detected
    type_issues = health.get("type_issues", {})
    cross_issues = report.get("cross_column_issues", [])
    missing_cols = health.get("missing_info", {}).get("columns", {})

    rows = []
    for col, info in type_issues.items():
        rows.append([
            badge("MEDIUM", "blue"),
            "<span class='mono'>" + col + "</span>",
            info.get("issue", ""), info.get("detected", ""),
            info.get("recommendation", "")
        ])
    for col, count in missing_cols.items():
        if col not in type_issues:
            rows.append([badge("MEDIUM", "blue"), "<span class='mono'>" + col + "</span>",
                         "Missing values", str(count) + " entries", "Impute with median/mode"])
    for ci in cross_issues:
        sev = ci.get("severity", "MEDIUM")
        rows.append([
            badge(sev, "red" if sev == "HIGH" else "blue"),
            " + ".join("<code>" + c + "</code>" for c in ci.get("columns", [])),
            ci.get("issue", ""), str(ci.get("affected_rows", "")) + " rows",
            ci.get("recommendation", "")
        ])

    if rows:
        from components import table
        html(card(
            table(["SEVERITY", "COLUMN", "ISSUE", "DETECTED", "RECOMMENDATION"], rows),
            "Issues detected by Agent 1",
            str(len(rows)) + " issue(s) found across single-column and cross-column checks."
        ))

    # ETL hints
    etl = report.get("etl_hints", {})
    casts = etl.get("type_casting_targets", {})
    if casts:
        casts_html = " &nbsp;·&nbsp; ".join(
            "<code>" + c + "</code> → <code>" + t + "</code>"
            for c, t in casts.items()
        )
        html('<div class="bf-card"><b>ETL hints from Agent 1:</b><br>' + casts_html + '</div>')

    # Action buttons
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("View full Quality Report", use_container_width=True):
            st.session_state["last_audited"] = st.session_state.pipeline_file
            st.switch_page("pages/4_Data_Quality.py")
    with col2:
        if st.button("Start New Analysis", type="primary", use_container_width=True):
            st.session_state.pipeline_state = "idle"
            st.session_state.pipeline_step  = 0
            st.session_state.pipeline_results = {}
            st.rerun()