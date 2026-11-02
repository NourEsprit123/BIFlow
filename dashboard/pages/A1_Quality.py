import sys
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from components import setup, page_header, html, badge, card, grid, kpi, table, bar, donut, dataset_picker
from workspace import PROFILE_STATE_KEY, get_workspace_result, profile_dataset_for_workspace, profiling_execution_status

# Explicitly set sidebar mode for agent pages
if "sidebar_mode" not in st.session_state or st.session_state.sidebar_mode == "nav":
    st.session_state.sidebar_mode = "agent1"

setup("Quality Check", hub="Agent 1 · Data Profiling")

page_header(
    "Quality Check",
    "Missing values, type mismatches, duplicates, outliers and cross-column integrity.",
    badge("Agent 1", "blue"),
    "Agent 1 · Data Profiling > <b>Quality Check</b>"
)

# The quality evidence comes from the profiling run of the active dataset.
path = dataset_picker()
if path is None:
    st.stop()
if st.button("🚀 Run Data Profiling Agent", type="primary", key="btn_run_direct_qual"):
    with st.spinner("🔍 Profiling and auditing the active dataset..."):
        profile_dataset_for_workspace(path)
    st.rerun()

results  = get_workspace_result(PROFILE_STATE_KEY, path) or {}
if results:
    st.session_state.setdefault("pipeline_results", {})["agent1"] = results
    used_llm, message = profiling_execution_status(results)
    (st.info if used_llm else st.warning)(message)
health   = results.get("health", {})
report   = results.get("profiling_report", {})
strategy = results.get("cleaning_strategy", {})

if not health and report and "health_scores" in report:
    health = report.get("health_scores", {})

if not health:
    st.info(f"No quality report for {path.name} yet. Run the profiling agent to audit this dataset.")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
overall_raw  = health.get("overall_health_score") if health.get("overall_health_score") is not None else health.get("overall", 0)
try:
    overall = round(max(0.0, min(100.0, float(overall_raw))), 1)
except (ValueError, TypeError):
    overall = 0.0

missing_info = health.get("missing_info", {})
dup_info     = health.get("duplicate_info", {})
type_issues  = health.get("type_issues", {})
outlier_info = health.get("outlier_info", {})

missing_total = missing_info.get("total_missing_cells")
if missing_total is None:
    missing_total = sum(missing_info.get("columns", {}).values())
dup_count     = dup_info.get("count", 0)
type_count    = len(type_issues)
outlier_count = len(outlier_info) if isinstance(outlier_info, dict) else 0

tone = "blue" if overall >= 90 else ("amber" if overall >= 70 else "red")
html(grid([
    kpi("Quality Score",  f"{overall}%",       "Overall health",        "🛡", tone),
    kpi("Missing Cells",  str(missing_total),  "Across all columns",    "⚠", "blue", "gray"),
    kpi("Duplicates",     str(dup_count),       "Duplicate rows",        "🔁", "blue"),
    kpi("Type Issues",    str(type_count),      "Columns with problems", "🏷", "blue"),
], "g4"))

# ── Health score donut + dimension bars ───────────────────────────────────────
dim_scores = health.get("dimension_scores", {})
completeness = health.get("completeness")
if completeness is None:
    completeness = dim_scores.get("completeness")
if completeness is None:
    miss_pct = missing_info.get("missing_percentage")
    if miss_pct is not None:
        completeness = max(0.0, 100.0 - float(miss_pct))
    else:
        tot_cells = missing_info.get("total_cells", 0)
        completeness = max(0.0, 100.0 - (missing_total / tot_cells * 100)) if tot_cells > 0 else 100.0

validity = health.get("validity")
if validity is None:
    validity = dim_scores.get("validity", max(0.0, 100.0 - (type_count * 5.0)))

uniqueness = health.get("uniqueness")
if uniqueness is None:
    uniqueness = dim_scores.get("uniqueness")
if uniqueness is None:
    dup_pct = dup_info.get("percentage")
    if dup_pct is not None:
        uniqueness = max(0.0, 100.0 - float(dup_pct))
    else:
        tot_rows = dup_info.get("total_rows", 0)
        uniqueness = max(0.0, 100.0 - (dup_count / tot_rows * 100)) if tot_rows > 0 else 100.0

consistency = health.get("consistency")
if consistency is None:
    consistency = dim_scores.get("consistency", overall)

# Garantir des valeurs arrondies et strictement bornées entre 0.0 et 100.0%
completeness = round(max(0.0, min(100.0, float(completeness))), 1)
validity     = round(max(0.0, min(100.0, float(validity))), 1)
uniqueness   = round(max(0.0, min(100.0, float(uniqueness))), 1)
consistency  = round(max(0.0, min(100.0, float(consistency))), 1)

dims_html = "".join(
    f'<div style="margin-bottom:.9rem"><div style="display:flex;justify-content:space-between;'
    f'font-size:.83rem;margin-bottom:.3rem"><span>{lbl}</span><b>{val}%</b></div>'
    f'{bar(val, clr)}</div>'
    for lbl, val, clr in [
        ("Completeness",  completeness, "#4f46e5"),
        ("Validity",      validity,     "#0ea5e9"),
        ("Uniqueness",    uniqueness,   "#10b981"),
        ("Consistency",   consistency,  "#f59e0b"),
    ]
)

donut_html = donut(int(overall), "#4f46e5", "HEALTH SCORE", 140)
html(card(
    f'<div style="display:flex;gap:2rem;align-items:center">'
    f'{donut_html}<div style="flex:1">{dims_html}</div></div>',
    "Quality Dimensions"
))

# ── Issues table ──────────────────────────────────────────────────────────────
rows = []

# type issues
for col, info in type_issues.items():
    sev = info.get("severity", "MEDIUM")
    tone_b = "red" if sev == "HIGH" else "blue"
    rows.append([
        badge(sev, tone_b),
        f"<span class='mono'>{col}</span>",
        info.get("issue", "Type mismatch"),
        info.get("detected", ""),
        info.get("recommendation", ""),
    ])

# missing columns
missing_cols = missing_info.get("columns", {})
for col, count in missing_cols.items():
    if col not in type_issues:
        rows.append([
            badge("MEDIUM", "blue"),
            f"<span class='mono'>{col}</span>",
            "Missing values",
            f"{count} missing cells",
            "Impute with median / mode",
        ])

# cross-column issues
for ci in report.get("cross_column_issues", []):
    sev = ci.get("severity", "MEDIUM")
    cols_str = " + ".join(f"<code>{c}</code>" for c in ci.get("columns", []))
    rows.append([
        badge(sev, "red" if sev == "HIGH" else "blue"),
        cols_str,
        ci.get("issue", ""),
        f"{ci.get('affected_rows', '')} rows",
        ci.get("recommendation", ""),
    ])

# sandbox results
col_profiles = report.get("column_profiles", {})
for col, cp in col_profiles.items():
    for sc in cp.get("custom_checks", []):
        if sc.get("result") and sc["result"] != 0:
            rows.append([
                badge("LOW", "gray"),
                f"<span class='mono'>{col}</span>",
                f"Custom check: {sc.get('check_name','')}",
                f"Result: {sc['result']}",
                "Review sandbox finding",
            ])

if rows:
    html(card(
        table(["SEVERITY", "COLUMN(S)", "ISSUE", "DETECTED", "RECOMMENDATION"], rows, max_height=380),
        "Issues Detected",
        f"{len(rows)} issue(s) found",
        badge(str(len(rows)), "red" if any("HIGH" in str(r) for r in rows) else "blue"),
    ))
else:
    html('<div class="bf-card" style="color:#166534;background:#dcfce7;text-align:center;padding:1.5rem">'
         '✅ <b>No issues detected</b> — dataset looks clean!</div>')

# ── LLM reasoning trail ───────────────────────────────────────────────────────
reasoning_cols = {
    col: cp for col, cp in col_profiles.items()
    if cp.get("agent_reasoning") or cp.get("issues")
}
if reasoning_cols:
    trail_html = ""
    for col, cp in list(reasoning_cols.items())[:15]:
        issues = cp.get("issues", [])
        reasoning = cp.get("agent_reasoning", "")
        sev_top = max((i.get("severity", "LOW") for i in issues),
                      key=lambda s: {"HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(s, 0),
                      default="NONE")
        tone_t = "red" if sev_top == "HIGH" else ("blue" if sev_top == "MEDIUM" else "gray")
        trail_html += (
            f'<div style="border-left:3px solid var(--bf-{tone_t},#e2e8f0);'
            f'padding:.6rem 1rem;margin-bottom:.8rem;background:#f8fafc;border-radius:0 10px 10px 0">'
            f'<b style="font-size:.9rem">{col}</b> {badge(sev_top, tone_t)}<br>'
            f'<small style="color:#475569">{reasoning}</small>'
            f'</div>'
        )
    scrollable_trail = f'<div style="max-height:380px;overflow-y:auto;padding-right:8px">{trail_html}</div>'
    html(card(scrollable_trail, "LLM Reasoning Trail", "Agent 1's column-level reasoning", badge("AI", "purple")))

# ── AI strategy summary ───────────────────────────────────────────────────────
summary = report.get("agent_summary", strategy.get("recommendation_summary", ""))
if summary:
    html(f'<div class="bf-card" style="background:#eef2ff;margin-top:.5rem">'
         f'<b>Agent 1 recommendation:</b><br><span style="color:#334155">{summary}</span></div>')
