import sys
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from components import setup, page_header, btn, html, kpi, grid, card, table, badge, bar, donut, columns_chart
from chat_widget import render_chat

render_chat("Data Quality")
setup("Data Quality")

# ── Dataset selector ──────────────────────────────────────────────────────────
raw_dir = PROJECT_ROOT / "data" / "raw"
all_files = (
    sorted(raw_dir.glob("*.csv")) +
    sorted(raw_dir.glob("*.xlsx")) +
    sorted(raw_dir.glob("*.parquet"))
)
file_names = [f.name for f in all_files]

if not file_names:
    st.warning("No datasets found in data/raw/.")
    st.stop()

col_sel, col_run = st.columns([4, 1])
with col_sel:
    selected_name = st.selectbox("Dataset", file_names, label_visibility="collapsed")
with col_run:
    run_btn = st.button("Run Audit", type="primary", use_container_width=True)

selected_path = str(raw_dir / selected_name)


@st.cache_data(show_spinner=False, ttl=300)
def run_agent(file_path: str):
    from agents.data_engineering_agent import DataEngineeringAgent
    agent = DataEngineeringAgent()
    return agent.run_audit(file_path)


# ── Severity badge helper ─────────────────────────────────────────────────────
def sev_badge(sev: str) -> str:
    tone = {"HIGH": "red", "MEDIUM": "blue", "LOW": "gray", "NONE": "gray"}.get(sev, "gray")
    return badge("" + sev, tone)


if run_btn or st.session_state.get("last_audited") == selected_path:
    st.session_state["last_audited"] = selected_path

    with st.spinner(f"Agent 1 is reasoning over {selected_name}..."):
        try:
            result = run_agent(selected_path)
        except Exception as e:
            st.error(f"Agent error: {e}")
            st.stop()

    profile  = result["profile"]
    health   = result["health"]
    strategy = result["cleaning_strategy"]
    report   = result.get("profiling_report", {})
    missing  = health["missing_info"]
    dupes    = health["duplicate_info"]
    issues   = health["type_issues"]
    overall  = health["overall_health_score"]
    tone     = "blue" if overall >= 90 else "amber" if overall >= 75 else "red"

    page_header(
        "Data Quality — " + selected_name,
        str(profile["rows"]) + " rows, " + str(profile["columns"]) + " columns",
        btn("Apply recommended cleaning", True),
        "Datasets > Data Quality"
    )

    # ── KPIs ─────────────────────────────────────────────────────────────────
    missing_count = missing["total_missing_cells"]
    missing_pct   = missing["missing_percentage"]
    dup_count     = dupes["count"]
    issue_count   = len(issues)

    html(grid([
        kpi("Quality Score",  str(overall) + "%",
            "Excellent" if overall >= 90 else "Needs attention", "shield", tone),
        kpi("Missing Values", str(missing_count),
            str(missing_pct) + "% of total cells", "warning", "blue", "gray"),
        kpi("Duplicates",     str(dup_count),
            "No duplicates" if dup_count == 0 else str(dup_count) + " rows", "copy", "blue"),
        kpi("Type Issues",    str(issue_count),
            str(issue_count) + " column(s) affected", "type", "blue"),
    ], "g4"))

    # ── Quality dimensions donut ──────────────────────────────────────────────
    dims = [
        ("Completeness", health["completeness"], "#38bdf8"),
        ("Validity",     health["validity"],     "#4f46e5"),
        ("Uniqueness",   health["uniqueness"],   "#075985"),
        ("Consistency",  health["consistency"],  "#6d28d9"),
    ]
    dim_html = ""
    for n, v, c in dims:
        dim_html += (
            '<div style="margin-bottom:1rem">'
            '<div style="display:flex;justify-content:space-between">'
            '<span>' + n + '</span><span class="mono">' + str(v) + '%</span></div>'
            + bar(v, c) + '</div>'
        )
    high_count   = sum(1 for i in issues.values() if "dirty" in i.get("issue", "").lower()
                       or "negative" in i.get("issue", "").lower())
    medium_count = len(issues) - high_count

    overview_card = card(
        '<div style="display:flex;gap:2rem;align-items:center">'
        + donut(int(overall), "#4f46e5", size=190)
        + '<div style="flex:1">' + dim_html + '</div></div>',
        "Quality overview", "Weighted health score across four primary quality dimensions."
    )
    sev_card = card(
        columns_chart(
            [max(high_count * 30, 5), max(medium_count * 30 + 30, 20), 18],
            ["Low", "Medium", "High"], ["#dbeafe", "#38bdf8", "#dbeafe"], 150
        )
        + '<div style="display:flex;gap:.4rem;margin-top:1rem">'
        + badge("High " + str(high_count), "red")
        + badge("Medium " + str(medium_count), "blue")
        + badge("Low 0", "gray") + '</div>',
        "Issues by severity", str(issue_count) + " issue(s) detected."
    )
    html('<div class="bf-grid g21">' + overview_card + sev_card + '</div>')

    # ── Issues table ─────────────────────────────────────────────────────────
    rows_html = []
    for col_name, info in issues.items():
        sev = "High" if "dirty" in info["issue"].lower() else "Medium"
        rows_html.append([
            badge(sev, "red" if sev == "High" else "blue"),
            "<span class='mono'>" + col_name + "</span>",
            info["issue"], info["detected"], info["recommendation"]
        ])
    for col_name, count in missing["columns"].items():
        if col_name not in issues:
            rows_html.append([
                badge("Medium", "blue"),
                "<span class='mono'>" + col_name + "</span>",
                "Missing values", str(count) + " null entries",
                "Impute with median/mode based on column type"
            ])

    # Cross-column issues from ProfilingReport
    cross_issues = report.get("cross_column_issues", [])
    for ci in cross_issues:
        sev = ci.get("severity", "MEDIUM")
        tone_ci = "red" if sev == "HIGH" else "blue"
        cols_str = " + ".join("<code>" + c + "</code>" for c in ci.get("columns", []))
        rows_html.append([
            badge(sev, tone_ci), cols_str,
            ci.get("issue", ""), str(ci.get("affected_rows", "")) + " rows",
            ci.get("recommendation", "")
        ])

    if rows_html:
        html(card(
            table(["SEVERITY", "COLUMN", "ISSUE", "DETECTED", "RECOMMENDATION"], rows_html),
            "Detected issues",
            "Single-column and cross-column issues detected by Agent 1."
        ))
    else:
        html(card("<p style='color:#16a34a;font-weight:600'>No issues detected.</p>",
                  "Detected issues"))

    # ── NEW: Per-column Reasoning Trail ──────────────────────────────────────
    col_profiles = report.get("column_profiles", {})
    cols_with_reasoning = {
        col: prof for col, prof in col_profiles.items()
        if prof.get("agent_reasoning") and prof.get("severity", "NONE") != "NONE"
    }

    if cols_with_reasoning:
        html("<br>")
        st.markdown("### Agent Reasoning Trail")
        st.caption("Per-column LLM reasoning — what Agent 1 thinks each issue means in context")

        for col_name, col_prof in cols_with_reasoning.items():
            sev = col_prof.get("severity", "NONE")
            sev_color = {"HIGH": "#fee2e2", "MEDIUM": "#eff6ff", "LOW": "#f0fdf4"}.get(sev, "#f8fafc")
            sev_border = {"HIGH": "#fca5a5", "MEDIUM": "#bfdbfe", "LOW": "#86efac"}.get(sev, "#e2e8f0")

            reasoning_html = (
                '<div style="background:' + sev_color + ';border:1px solid ' + sev_border +
                ';border-radius:12px;padding:1rem;margin-bottom:.75rem">'
                '<div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem">'
                '<span class="mono" style="font-weight:700">' + col_name + '</span>'
                + sev_badge(sev) + badge(col_prof.get("inferred_role", ""), "gray") +
                '</div>'
            )
            if col_prof.get("business_interpretation"):
                reasoning_html += (
                    '<div style="color:#475569;font-size:.85rem;margin-bottom:.4rem">'
                    '<b>Business context:</b> ' + col_prof["business_interpretation"] + '</div>'
                )
            if col_prof.get("agent_reasoning"):
                reasoning_html += (
                    '<div style="color:#1e293b;font-size:.88rem;margin-bottom:.4rem">'
                    '<b>Reasoning:</b> ' + col_prof["agent_reasoning"] + '</div>'
                )
            # ETL hint
            if col_prof.get("etl_cast_to") and col_prof["etl_cast_to"] != "none":
                reasoning_html += (
                    '<div style="color:#6d28d9;font-size:.8rem">'
                    'Cast to: <code>' + col_prof["etl_cast_to"] + '</code>'
                    ' | Impute: <code>' + col_prof.get("imputation_strategy", "none") + '</code></div>'
                )
            # Sandbox result
            custom = col_prof.get("custom_check")
            if custom and not custom.get("skipped"):
                r = custom.get("result", {})
                sandbox_color = "#dcfce7" if r.get("passed") else "#fef3c7" if r.get("passed") is None else "#fee2e2"
                passed_icon = "Passed" if r.get("passed") else ("Unknown" if r.get("passed") is None else "Failed")
                reasoning_html += (
                    '<div style="background:' + sandbox_color +
                    ';border-radius:8px;padding:.5rem .75rem;margin-top:.5rem;font-size:.8rem">'
                    '<b>Sandbox check:</b> ' + custom.get("check_description", "") +
                    '<br>Result: <b>' + passed_icon + '</b>'
                    + (' | ' + str(r.get("metric", "")) if r.get("metric") is not None else "")
                    + (' | ' + str(r.get("details", "")) if r.get("details") else "")
                    + ((' | Error: ' + str(r.get("error", ""))) if r.get("error") else "")
                    + '</div>'
                )

            reasoning_html += '</div>'
            html(reasoning_html)

    # ── Uncertainty flags ─────────────────────────────────────────────────────
    uncertainty_flags = report.get("uncertainty_flags", [])
    if uncertainty_flags:
        html("<br>")
        flags_rows = []
        for uf in uncertainty_flags:
            flags_rows.append([
                "<span class='mono'>" + uf.get("column", "") + "</span>",
                uf.get("flag", ""),
                badge("Confirm", "amber") if uf.get("requires_human_confirmation") else badge("Auto-OK", "gray")
            ])
        html(card(
            table(["COLUMN", "UNCERTAINTY FLAG", "ACTION"], flags_rows),
            "Uncertainty flags",
            "Columns where Agent 1 is not confident — Agent 2 will verify before cleaning."
        ))

    # ── AI Cleaning Strategy banner ───────────────────────────────────────────
    html("<br>")
    rec = strategy.get("recommendation_summary", "")
    agent_summary = report.get("agent_summary", "")
    wf  = strategy.get("numeric_waterfall_columns", [])
    imp = strategy.get("imputation_plan", {})
    syn = strategy.get("synonym_mappings", {})
    out = strategy.get("outlier_columns", [])
    etl = report.get("etl_hints", {})

    details = ""
    if agent_summary:
        details += "<br><i style='color:#475569'>" + agent_summary + "</i>"
    if wf:
        details += "<br><b>Waterfall cleaning:</b> " + ", ".join(
            "<code>" + c + "</code>" for c in wf)
    if imp:
        details += "<br><b>Imputation:</b> " + ", ".join(
            "<code>" + c + "</code> (" + str(v.get("strategy", "median")) + ")"
            for c, v in imp.items())
    if syn:
        details += "<br><b>Synonym normalization:</b> " + ", ".join(
            "<code>" + c + "</code>" for c in syn)
    if out:
        details += "<br><b>Outlier capping:</b> " + ", ".join(
            "<code>" + c + "</code>" for c in out)
    if etl.get("type_casting_targets"):
        casts = ", ".join(
            "<code>" + c + "</code> to <code>" + t + "</code>"
            for c, t in etl["type_casting_targets"].items()
        )
        details += "<br><b>ETL type casting:</b> " + casts
    if etl.get("join_key_candidates"):
        details += "<br><b>Join keys:</b> " + ", ".join(
            "<code>" + c + "</code>" for c in etl["join_key_candidates"])

    sandbox_count = report.get("metadata", {}).get("sandbox_executions", 0)
    sandbox_badge = badge("Sandbox: " + str(sandbox_count) + " checks run", "purple") if sandbox_count > 0 else ""

    html(
        '<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:flex-start">'
        + "<div style='font-size:1.5rem'>AI</div>"
        +         '<div style="flex:1"><b style="font-size:1.05rem">Agent 1 Cleaning Strategy</b> '
        + badge("Gemini", "purple") + " " + sandbox_badge
        + "<br>" + rec + details + "</div>"
        + btn("Preview changes") + " " + btn("Apply recommended cleaning", True)
        + "</div>"
    )

else:
    # ── Placeholder ───────────────────────────────────────────────────────────
    page_header("Data Quality",
                "Select a dataset and click Run Audit to analyse it with Agent 1.", "", "")
    html(
        '<div class="bf-card" style="text-align:center;padding:3rem;color:#64748b">'
        '<div style="font-size:3rem;margin-bottom:1rem">Search</div>'
        '<b style="font-size:1.2rem">No dataset audited yet</b>'
        '<p>Pick a dataset from the dropdown and click <b>Run Audit</b>.</p>'
        '<p>Available: ' + ", ".join("<code>" + n + "</code>" for n in file_names[:5]) + "</p>"
        '</div>'
    )