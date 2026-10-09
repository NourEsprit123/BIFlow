import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
from components import setup, page_header, html, kpi, grid, card, table, badge, bar
# Use ONLY fast Python functions — NO LLM call on Overview
from analytics.profiler import profile_dataset, load_dataset
from analytics.data_quality import calculate_health_scores

setup("Overview")

RAW_DIR = "data/raw"
supported = (".csv", ".xlsx", ".xls", ".parquet")


@st.cache_data(ttl=300, show_spinner=False)
def get_fast_profile(file_path: str):
    """Fast Python-only profiling — no LLM, runs in <1 second."""
    profile = profile_dataset(file_path)
    df = load_dataset(file_path)
    health = calculate_health_scores(df)
    return profile, health


# ── Discover all datasets ─────────────────────────────────────────────────────
available = []
if os.path.exists(RAW_DIR):
    for fname in os.listdir(RAW_DIR):
        if fname.lower().endswith(supported):
            fpath = os.path.join(RAW_DIR, fname)
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%b %d")
            available.append((fname, fpath, mtime))

hour = datetime.now().hour
greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")
today = datetime.now().strftime("%B %d, %Y")

page_header(
    f"{greeting}, Sarah.",
    "Here's what's happening with your data today."
)

# Real action buttons
_c1, _c2, _spacer = st.columns([1, 1.4, 5])
with _c1:
    st.button("Filter View", use_container_width=True)
with _c2:
    if st.button("+ Create analysis", type="primary", use_container_width=True):
        st.switch_page("pages/4_Data_Quality.py")

# ── Profile all datasets (fast — no LLM) ─────────────────────────────────────
profiles = []
total_missing = 0
total_type_issues = 0
avg_score = 0

if not available:
    st.info("No datasets found. Go to **Datasets** to upload your first file.")
    st.stop()

for fname, fpath, mtime in available:
    try:
        profile, health = get_fast_profile(fpath)
        score = int(health["overall_health_score"])
        missing = health["missing_info"]["total_missing_cells"]
        type_issues = len(health["type_issues"])
        total_missing += missing
        total_type_issues += type_issues
        avg_score += score
        profiles.append({
            "fname": fname, "fpath": fpath, "mtime": mtime,
            "rows": profile["rows"], "cols": profile["columns"],
            "score": score, "missing": missing, "type_issues": type_issues,
            "health": health
        })
    except Exception:
        pass

if profiles:
    avg_score = avg_score // len(profiles)

# ── KPI cards ─────────────────────────────────────────────────────────────────
html(grid([
    kpi("Active datasets", str(len(profiles)), f"{len(profiles)} dataset(s) profiled", "🗄"),
    kpi("Data quality score", f"{avg_score}%", f"Avg across all datasets · {today}", "🛡", "blue"),
    kpi("Missing values", str(total_missing), "Total across all datasets", "⚠", "blue", "gray"),
    kpi("Type issues", str(total_type_issues), f"{total_type_issues} column(s) need attention", "{}", "blue"),
], "g4"))

# ── Datasets table ────────────────────────────────────────────────────────────
trs = []
for p in profiles:
    s = p["score"]
    status = badge("● Ready", "green") if s >= 95 else badge("● Needs attention", "amber")
    trs.append([
        f"<b>{p['fname']}</b><small class='mono'>{p['fpath']}</small>",
        f"{p['rows']:,}",
        str(p["cols"]),
        f"{bar(s)} {s}%",
        p["mtime"],
    ])

datasets_tbl = table(["DATASET", "ROWS", "COLUMNS", "QUALITY", "LAST MODIFIED"], trs)

# ── AI Activity panel ─────────────────────────────────────────────────────────
agents_html = "".join(
    f'<div class="bf-insight"><b>{n}</b><br><small>{d}</small>'
    f'<span style="float:right">{s}</span></div>'
    for n, d, s in [
        ("Data Engineering Agent",
         f"Profiled {len(profiles)} dataset(s), avg quality {avg_score}%", "&#10003;"),
        ("BI Analyst Agent", "Pending — not yet implemented", badge("Standby", "purple")),
        ("Dashboard Agent",  "Pending — not yet implemented", badge("Standby", "purple")),
        ("XAI Auditor Agent","Pending — not yet implemented", badge("Standby", "purple")),
    ]
)

# ── Health breakdown for first dataset ───────────────────────────────────────
if profiles:
    first = profiles[0]
    h = first["health"]
    dims_html = "".join(
        f'<div style="margin-bottom:.6rem">'
        f'<div style="display:flex;justify-content:space-between">'
        f'<span>{n}</span><span class="mono">{v}%</span></div>{bar(v, c)}</div>'
        for n, v, c in [
            ("Completeness", h["completeness"], "#38bdf8"),
            ("Validity",     h["validity"],     "#4f46e5"),
            ("Uniqueness",   h["uniqueness"],   "#075985"),
            ("Consistency",  h["consistency"],  "#6d28d9"),
        ]
    )
    health_card_html = (
        f'<div style="display:flex;justify-content:space-between">'
        f'<b>Health breakdown · {first["fname"]}</b></div>{dims_html}'
    )
else:
    health_card_html = "<p>No data yet.</p>"

_ai_card_body = (
    '<div class="bf-box"><b>Go to Data Quality</b> to get AI-powered recommendations and apply cleaning.<br>'
    '<small>Data Engineering Agent with Qwen 2.5 · Ready</small></div>'
)

html(f'''<div class="bf-grid g21"><div>
  {card(datasets_tbl, "Active datasets", "", badge(f"{len(profiles)} active"))}
  <br>
  {card(_ai_card_body, "AI-powered analysis", "Click below to run the full LLM audit on any dataset.", badge("Qwen 2.5", "blue"))}
</div><div>
  {card(agents_html, "AI activity", "Latest autonomous agent runs")}
  <br>
  {card(health_card_html)}
</div></div>''')