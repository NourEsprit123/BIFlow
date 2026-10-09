import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
import pandas as pd
from components import setup, page_header, html, card, table, badge, bar
from agents.data_engineering_agent import DataEngineeringAgent

setup("Datasets")

RAW_DIR = "data/raw"
os.makedirs(RAW_DIR, exist_ok=True)

agent = DataEngineeringAgent()


@st.cache_data(ttl=300, show_spinner=False)
def get_audit(file_path: str):
    return agent.run_audit(file_path)


# ── Discover all datasets already in data/raw/ ──────────────────────────────
def list_raw_datasets():
    supported = (".csv", ".xlsx", ".xls", ".parquet")
    return [
        f for f in os.listdir(RAW_DIR)
        if f.lower().endswith(supported)
    ]


# ── Upload section ────────────────────────────────────────────────────────────
page_header(
    "Datasets",
    "Manage, inspect, and streamline your business intelligence assets.",
    crumbs="Workspace › <b>Datasets</b>"
)

col_refresh, col_upload, col_space = st.columns([1, 1.5, 6])
with col_refresh:
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with col_upload:
    show_upload = st.button("Upload dataset", type="primary", use_container_width=True)

# Upload expander triggered by button
if show_upload or st.session_state.get("show_upload_panel"):
    st.session_state["show_upload_panel"] = True
    with st.expander("Upload a new dataset", expanded=True):
        uploaded_file = st.file_uploader(
            "Drop a CSV, Excel, or Parquet file here",
            type=["csv", "xlsx", "xls", "parquet"],
            key="dataset_uploader"
        )
        if uploaded_file:
            save_path = os.path.join(RAW_DIR, uploaded_file.name)
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success(f"Saved **{uploaded_file.name}** to `{save_path}`. Running AI profiling...")
            st.cache_data.clear()
            st.session_state["active_dataset"] = save_path
            st.session_state["show_upload_panel"] = False
            st.rerun()

html("<br>")

# ── Build dataset list ────────────────────────────────────────────────────────
raw_files = list_raw_datasets()

if not raw_files:
    st.info("No datasets found in `data/raw/`. Upload a CSV, Excel, or Parquet file above.")
    st.stop()

# ── Profile each file (cached) ───────────────────────────────────────────────
dataset_summaries = []
with st.spinner("Loading dataset profiles..."):
    for fname in raw_files:
        fpath = os.path.join(RAW_DIR, fname)
        try:
            audit = get_audit(fpath)
            p = audit["profile"]
            h = audit["health"]
            score = int(h["overall_health_score"])
            ext = fname.rsplit(".", 1)[-1].upper()
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%b %d, %Y")
            if score >= 95:
                status = badge("● Ready", "green")
            elif score >= 80:
                status = badge("● Needs attention", "amber")
            else:
                status = badge("● Action required", "red")
            dataset_summaries.append({
                "fname": fname, "fpath": fpath,
                "rows": p["rows"], "cols": p["columns"],
                "score": score, "ext": ext,
                "mtime": mtime, "status": status,
                "audit": audit
            })
        except Exception as e:
            dataset_summaries.append({
                "fname": fname, "fpath": os.path.join(RAW_DIR, fname),
                "rows": "—", "cols": "—", "score": 0,
                "ext": fname.rsplit(".", 1)[-1].upper(),
                "mtime": "—", "status": badge("● Error", "red"),
                "audit": None, "error": str(e)
            })

# ── Summary table ─────────────────────────────────────────────────────────────
def fmt_type(t):
    return f'<span class="mono" style="color:#166534;background:#dcfce7;padding:.1rem .4rem;border-radius:6px">{t}</span>'

trs = []
for ds in dataset_summaries:
    score = ds["score"]
    q_html = f'<b>{score}%</b> {bar(score, "#10b981" if score >= 95 else "#f59e0b")}' if score else "<i>Error</i>"
    trs.append([
        f"<b>{ds['fname']}</b><small class='mono'>{ds['fpath']}</small>",
        fmt_type(ds["ext"]),
        f"{ds['rows']:,}" if isinstance(ds["rows"], int) else ds["rows"],
        str(ds["cols"]),
        q_html,
        ds["mtime"],
        ds["status"]
    ])

filter_chips = "".join(
    f'<span class="bf-chip{" on" if i == 0 else ""}">{t}</span>'
    for i, t in enumerate([f"All {len(raw_files)}", f"● Ready {sum(1 for d in dataset_summaries if d['score'] >= 95)}"])
)

html(card(
    f'<div style="display:flex;gap:1rem;align-items:center">'
    f'<div class="bf-search" style="flex:.7">🔍 Search datasets by title or format<span>⌘ F</span></div>'
    f'<div>{filter_chips}</div></div>'
))
html("<br>")
html(card(
    table(["DATASET", "FORMAT", "ROWS", "COLUMNS", "QUALITY SCORE", "LAST MODIFIED", "STATUS"], trs)
    + f'<div style="margin-top:1rem;color:#475569">Showing <b>{len(trs)}</b> dataset(s) — profiled live by Data Engineering Agent</div>'
))
html("<br>")

# ── Per-dataset detail: selectbox ─────────────────────────────────────────────
selected_name = st.selectbox(
    "Inspect dataset details:",
    options=[ds["fname"] for ds in dataset_summaries],
    index=0
)
selected = next(ds for ds in dataset_summaries if ds["fname"] == selected_name)

if selected["audit"] is None:
    st.error(f"Could not profile this dataset: {selected.get('error', 'Unknown error')}")
    st.stop()

audit    = selected["audit"]
profile  = audit["profile"]
health   = audit["health"]
strategy = audit["cleaning_strategy"]
score    = selected["score"]
col_roles = profile.get("column_roles", {})
missing  = health["missing_info"]["total_missing_cells"]
missing_pct = health["missing_info"]["missing_percentage"]
dup_cnt  = health["duplicate_info"]["count"]
type_issues = len(health["type_issues"])
rec      = strategy.get("recommendation_summary", "No issues detected.")

numeric_cols     = [c for c, r in col_roles.items() if r == "continuous_numeric"]
categorical_cols = [c for c, r in col_roles.items() if r in ("categorical", "boolean")]
id_cols          = [c for c, r in col_roles.items() if r == "primary_key"]
ts_cols          = [c for c, r in col_roles.items() if r == "timestamp"]

col_breakdown = f'''
<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">
  <div class="bf-box"><b>Numeric ({len(numeric_cols)})</b><br>
    <small class="mono">{", ".join(numeric_cols[:6]) + ("..." if len(numeric_cols) > 6 else "") or "—"}</small></div>
  <div class="bf-box"><b>Categorical ({len(categorical_cols)})</b><br>
    <small class="mono">{", ".join(categorical_cols[:6]) + ("..." if len(categorical_cols) > 6 else "") or "—"}</small></div>
  <div class="bf-box"><b>ID/Key ({len(id_cols)})</b><br>
    <small class="mono">{", ".join(id_cols) or "—"}</small></div>
  <div class="bf-box"><b>Timestamp ({len(ts_cols)})</b><br>
    <small class="mono">{", ".join(ts_cols) or "—"}</small></div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
  <div class="bf-box"><b>Missing cells: {missing}</b> ({missing_pct}%)<br>{bar(float(missing_pct), "#f59e0b")}</div>
  <div class="bf-box"><b>Duplicate rows: {dup_cnt}</b><br>{bar(health["duplicate_info"]["percentage"], "#6d28d9")}</div>
</div>'''

if health["type_issues"]:
    issues_rows = [
        [f"<span class='mono'>{col}</span>", info["issue"], info.get("recommendation", "—")]
        for col, info in health["type_issues"].items()
    ]
    issues_table = table(["COLUMN", "ISSUE", "RECOMMENDATION"], issues_rows)
else:
    issues_table = "<p style='color:#16a34a;padding:.5rem 0'>No type issues detected.</p>"

ai_rec = f'''<div style="background:#eef2ff;border-radius:12px;padding:1.2rem;display:flex;gap:1rem;align-items:center">
  <div style="flex:1"><b style="font-size:1.05rem">BIFlow AI Recommendation</b>
  <span class="bf-badge blue" style="margin-left:.5rem">Qwen 2.5 Agent</span>
  <br><span style="color:#334155">{rec}</span></div></div>'''

storage_html = f'''<div class="ch"><div><h3>{selected_name}</h3>
  <div class="subt">Live profile summary</div></div>{selected["status"]}</div>
  <div style="font-size:2.2rem;font-weight:700">{profile["rows"]:,} rows
  <small style="font-size:1rem;color:#64748b">× {profile["columns"]} columns</small></div>
  {bar(score, "#4f46e5")}
  <p style="color:#64748b;font-size:.85rem">Quality: <b style="color:#0f172a">{score}%</b>
  &nbsp;|&nbsp; Missing: <b>{missing}</b>
  &nbsp;|&nbsp; Duplicates: <b>{dup_cnt}</b>
  &nbsp;|&nbsp; Type issues: <b>{type_issues}</b></p>'''

html(f'<div class="bf-grid g21"><div>'
     f'{card(col_breakdown, "Column profile", "Auto-detected column types by Data Engineering Agent.")}'
     f'<br>{card(issues_table, "Type issues", f"{type_issues} column(s) require attention.")}'
     f'<br>{ai_rec}'
     f'</div><div>{card(storage_html)}</div></div>')

html("<br>")

c1, c2 = st.columns(2)
with c1:
    if st.button("Preview cleaning changes", use_container_width=True, key="prev_ds"):
        with st.spinner("Running preview..."):
            preview = agent.execute_cleaning(selected["fpath"], preview_mode=True)
        st.success(f"Health score after cleaning: **{preview['health_after']['overall_health_score']}%**")
with c2:
    if st.button("Apply recommended cleaning", type="primary", use_container_width=True, key="apply_ds"):
        with st.spinner("Cleaning dataset..."):
            res = agent.execute_cleaning(selected["fpath"], preview_mode=False)
        st.success(f"Done! Saved to `{res['cleaned_file_path']}`. New score: **{res['health_after']['overall_health_score']}%**")
        st.cache_data.clear()