import streamlit as st
import pandas as pd
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="BIFlow",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# DESIGN SYSTEM
# Palette : encre marine #0F1B3D · turquoise #0E9F8E · ambre #F5A524
#           papier #F4F6FB · surface #FFFFFF · trait #E2E7F1
# Typo    : Bricolage Grotesque (titres) + Manrope (texte)
# ============================================================

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700;12..96,800&family=Manrope:wght@400;500;600;700&display=swap');

:root {
    --ink: #0F1B3D;
    --ink-soft: #1C2C5C;
    --teal: #0E9F8E;
    --teal-soft: #DDF5F1;
    --amber: #F5A524;
    --amber-soft: #FDF0D5;
    --violet: #6B5BD6;
    --violet-soft: #ECE9FB;
    --rose: #E5566D;
    --rose-soft: #FCE6EA;
    --paper: #F4F6FB;
    --surface: #FFFFFF;
    --line: #E2E7F1;
    --muted: #66708A;
}

html, body, [class*="css"], .stMarkdown, p, label, li {
    font-family: 'Manrope', sans-serif;
}
h1, h2, h3, h4, .bf-display {
    font-family: 'Bricolage Grotesque', sans-serif !important;
    color: var(--ink);
    letter-spacing: -0.02em;
}

/* --- Chrome Streamlit --- */
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.stApp { background: var(--paper); }
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1180px; }

/* --- Sidebar --- */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0F1B3D 0%, #13235A 100%);
    border-right: none;
}
section[data-testid="stSidebar"] * { color: #C9D2EC; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.10); }

.bf-brand { display:flex; align-items:center; gap:.7rem; padding:.3rem 0 .2rem; }
.bf-logo {
    width:38px; height:38px; border-radius:11px;
    background: linear-gradient(135deg, #0E9F8E, #2DD4BF);
    display:flex; align-items:center; justify-content:center;
    font-size:1.2rem; box-shadow: 0 6px 18px rgba(14,159,142,.45);
}
.bf-brand-name {
    font-family:'Bricolage Grotesque',sans-serif; font-weight:800;
    font-size:1.45rem; color:#FFFFFF !important; line-height:1;
}
.bf-brand-tag { font-size:.74rem; color:#8E9BC4 !important; margin-top:.2rem; }

.bf-side-label { font-size:.78rem; color:#7F8CB8 !important; margin:.2rem 0 .4rem; font-weight:600; }

/* Navigation (radio transformé en menu) */
section[data-testid="stSidebar"] div[role="radiogroup"] { gap:.25rem; }
section[data-testid="stSidebar"] div[role="radiogroup"] label {
    padding:.62rem .85rem; border-radius:11px; width:100%;
    transition: background .15s ease; cursor:pointer;
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background: rgba(255,255,255,.07); }
section[data-testid="stSidebar"] div[role="radiogroup"] label > div:first-child { display:none; }
section[data-testid="stSidebar"] div[role="radiogroup"] label p { font-weight:600; font-size:.95rem; }
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
    background: rgba(45,212,191,.16);
    box-shadow: inset 3px 0 0 #2DD4BF;
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p { color:#FFFFFF !important; }

.bf-status {
    display:flex; align-items:center; gap:.55rem;
    background: rgba(255,255,255,.06); border-radius:12px;
    padding:.7rem .9rem; font-size:.85rem; font-weight:600;
}
.bf-dot { width:9px; height:9px; border-radius:50%; background:#2DD4BF; box-shadow:0 0 0 4px rgba(45,212,191,.22); }

/* --- Hero --- */
.bf-hero {
    background: linear-gradient(120deg, #0F1B3D 0%, #1C2C5C 60%, #0E7F74 135%);
    border-radius: 22px; padding: 2.6rem 2.8rem; margin-bottom: 1.8rem;
    position: relative; overflow: hidden;
}
.bf-hero::after {
    content:""; position:absolute; right:-70px; top:-70px; width:280px; height:280px;
    border-radius:50%; background: radial-gradient(circle, rgba(45,212,191,.35), transparent 70%);
}
.bf-hero h1 { color:#FFFFFF !important; font-size:2.7rem; font-weight:800; margin:0 0 .7rem; line-height:1.08; max-width:640px; }
.bf-hero p { color:#B9C4E6; font-size:1.05rem; max-width:560px; margin:0; line-height:1.6; }

/* --- Titres de page --- */
.bf-page-title { font-size:2.1rem; font-weight:800; margin:0 0 .3rem; }
.bf-page-sub { color:var(--muted); font-size:1rem; margin-bottom:1.6rem; max-width:680px; }
.bf-section { font-size:1.2rem; font-weight:700; margin:2rem 0 1rem; }

/* --- Cartes --- */
.bf-card {
    background: var(--surface); border:1px solid var(--line); border-radius:16px;
    padding:1.3rem 1.3rem 1.2rem; height:100%;
}
.bf-icon {
    width:44px; height:44px; border-radius:12px; display:flex; align-items:center;
    justify-content:center; font-size:1.3rem; margin-bottom:.9rem;
}
.bf-card h4 { margin:0 0 .35rem; font-size:1.05rem; font-weight:700; }
.bf-card p { margin:0; color:var(--muted); font-size:.9rem; line-height:1.5; }

.bf-pill {
    display:inline-block; padding:.22rem .65rem; border-radius:999px;
    font-size:.74rem; font-weight:700; margin-top:.9rem;
}
.pill-wait { background:#EEF1F7; color:#66708A; }
.pill-ready { background: var(--teal-soft); color:#0A7468; }
.pill-done { background: var(--teal-soft); color:#0A7468; }

/* --- Pipeline (vraie séquence) --- */
.bf-pipe { display:flex; align-items:flex-start; background:var(--surface);
    border:1px solid var(--line); border-radius:16px; padding:1.5rem 1rem; }
.bf-step { flex:1; text-align:center; position:relative; }
.bf-step:not(:last-child)::after {
    content:""; position:absolute; top:19px; left:calc(50% + 26px); right:calc(-50% + 26px);
    height:2px; background: var(--line);
}
.bf-step.done:not(:last-child)::after { background: var(--teal); }
.bf-num {
    width:38px; height:38px; border-radius:50%; margin:0 auto .6rem;
    display:flex; align-items:center; justify-content:center; font-weight:800;
    background:#EEF1F7; color:var(--muted); font-family:'Bricolage Grotesque',sans-serif;
}
.bf-step.done .bf-num { background: var(--teal); color:#fff; }
.bf-step b { display:block; font-size:.95rem; color:var(--ink); }
.bf-step span { font-size:.8rem; color:var(--muted); }

/* --- KPI --- */
.bf-kpi { background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:1.2rem 1.3rem; }
.bf-kpi .v { font-family:'Bricolage Grotesque',sans-serif; font-size:2.1rem; font-weight:800; color:var(--ink); line-height:1.1; }
.bf-kpi .l { color:var(--muted); font-size:.85rem; margin-top:.3rem; font-weight:500; }

/* --- Composants Streamlit --- */
[data-testid="stFileUploader"] section {
    background: var(--surface); border:2px dashed #C3CDE3; border-radius:16px; padding:1.6rem;
}
[data-testid="stFileUploader"] section:hover { border-color: var(--teal); }
[data-testid="stFileUploader"] button {
    background: var(--ink); color:#fff; border:none; border-radius:10px; font-weight:600;
}
.stButton > button {
    background: var(--teal); color:#fff; border:none; border-radius:11px;
    padding:.6rem 1.3rem; font-weight:700;
}
.stButton > button:hover { background:#0B8576; color:#fff; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:14px; overflow:hidden; }
div[data-testid="stAlert"] { border-radius:14px; }
.stSelectbox > div > div { border-radius:11px; }

.bf-empty {
    background:var(--surface); border:1px dashed #C3CDE3; border-radius:16px;
    padding:2.2rem; text-align:center; color:var(--muted);
}
.bf-empty b { display:block; color:var(--ink); font-size:1.05rem; margin-bottom:.3rem; }

.bf-log { display:flex; gap:1rem; padding:.85rem 0; border-bottom:1px solid var(--line); font-size:.92rem; }
.bf-log:last-child { border-bottom:none; }
.bf-log time { color:var(--muted); font-variant-numeric: tabular-nums; min-width:64px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ============================================================
# HELPERS
# ============================================================

def init_state():
    st.session_state.setdefault("df", None)
    st.session_state.setdefault("filename", None)
    st.session_state.setdefault("log", [])


def log(event: str):
    st.session_state["log"].insert(0, (datetime.now().strftime("%H:%M:%S"), event))


def load_dataset(uploaded_file):
    """Charge le fichier en DataFrame (une seule fois par fichier)."""
    if st.session_state["filename"] == uploaded_file.name:
        return
    try:
        name = uploaded_file.name.lower()
        if name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        elif name.endswith(".xlsx"):
            df = pd.read_excel(uploaded_file)
        else:
            df = pd.read_json(uploaded_file)
        st.session_state["df"] = df
        st.session_state["filename"] = uploaded_file.name
        log(f"Dataset loaded: {uploaded_file.name} ({len(df):,} rows, {df.shape[1]} columns)")
    except Exception as e:
        st.error(f"Could not read this file. Check its format and try again. ({e})")


def page_header(title: str, subtitle: str):
    st.markdown(
        f'<div class="bf-page-title">{title}</div><div class="bf-page-sub">{subtitle}</div>',
        unsafe_allow_html=True,
    )


def kpi(value, label):
    return f'<div class="bf-kpi"><div class="v">{value}</div><div class="l">{label}</div></div>'


def empty_state(title, text):
    st.markdown(f'<div class="bf-empty"><b>{title}</b>{text}</div>', unsafe_allow_html=True)


def uploader(key):
    f = st.file_uploader(
        "Drop your business dataset here",
        type=["csv", "xlsx", "json"],
        key=key,
        help="CSV, XLSX or JSON",
    )
    if f:
        load_dataset(f)
    return f


init_state()
df = st.session_state["df"]

# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown(
        """
        <div class="bf-brand">
            <div class="bf-logo">📊</div>
            <div>
                <div class="bf-brand-name">BIFlow</div>
                <div class="bf-brand-tag">Intelligent Business Intelligence</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown('<div class="bf-side-label">Workspace</div>', unsafe_allow_html=True)

    page = st.radio(
        "Workspace",
        ["Overview", "Data", "Data Quality", "Analytics", "AI Agents", "Audit"],
        label_visibility="collapsed",
        format_func=lambda p: {
            "Overview": "🏠  Overview",
            "Data": "📁  Data",
            "Data Quality": "🧹  Data Quality",
            "Analytics": "📈  Analytics",
            "AI Agents": "🤖  AI Agents",
            "Audit": "🔍  Audit",
        }[p],
    )

    st.divider()
    dataset_txt = st.session_state["filename"] or "No dataset yet"
    st.markdown(
        f"""
        <div class="bf-status"><div class="bf-dot"></div>
        <div>System ready<br><span style="font-weight:500;font-size:.75rem;color:#8E9BC4">{dataset_txt}</span></div></div>
        """,
        unsafe_allow_html=True,
    )

# ============================================================
# OVERVIEW
# ============================================================

if page == "Overview":

    st.markdown(
        """
        <div class="bf-hero">
            <h1>Transform data into decisions</h1>
            <p>BIFlow turns raw business data into reliable insights
            through a workflow of four cooperating AI agents.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="bf-section" style="margin-top:0">Start an analysis</div>', unsafe_allow_html=True)
    f = uploader("upload_overview")
    if f:
        st.success(f"Dataset loaded: {f.name}")
        df = st.session_state["df"]
    else:
        st.info("Upload a CSV, XLSX or JSON file to start.")

    # Pipeline : une vraie séquence, l'étape 1 s'active après import
    loaded = st.session_state["df"] is not None
    steps = [
        ("1", "Data", "Import", loaded),
        ("2", "Clean", "Quality", False),
        ("3", "Analyze", "Business KPIs", False),
        ("4", "Explain", "Traceability", False),
        ("5", "Insight", "Decision", False),
    ]
    html = '<div class="bf-pipe">'
    for n, t, s, done in steps:
        html += (
            f'<div class="bf-step {"done" if done else ""}">'
            f'<div class="bf-num">{"✓" if done else n}</div><b>{t}</b><span>{s}</span></div>'
        )
    html += "</div>"
    st.markdown('<div class="bf-section">Pipeline</div>', unsafe_allow_html=True)
    st.markdown(html, unsafe_allow_html=True)

    st.markdown('<div class="bf-section">Your agents</div>', unsafe_allow_html=True)
    agents = [
        ("⚙️", "var(--teal-soft)", "Data Engineering", "Profiles, cleans and transforms your dataset."),
        ("📊", "var(--amber-soft)", "BI Analyst", "Calculates KPIs, trends and anomalies."),
        ("🔍", "var(--violet-soft)", "XAI / Auditor", "Explains each result and keeps it traceable."),
        ("🧠", "var(--rose-soft)", "Orchestrator", "Coordinates the full workflow."),
    ]
    cols = st.columns(4)
    for col, (icon, bg, name, desc) in zip(cols, agents):
        with col:
            st.markdown(
                f'<div class="bf-card"><div class="bf-icon" style="background:{bg}">{icon}</div>'
                f"<h4>{name}</h4><p>{desc}</p></div>",
                unsafe_allow_html=True,
            )

    st.markdown('<div class="bf-section">Workspace</div>', unsafe_allow_html=True)
    n_ds = 1 if loaded else 0
    rows = f"{len(st.session_state['df']):,}" if loaded else "0"
    c1, c2, c3 = st.columns(3)
    c1.markdown(kpi(n_ds, "Datasets analyzed"), unsafe_allow_html=True)
    c2.markdown(kpi(rows, "Rows available"), unsafe_allow_html=True)
    c3.markdown(kpi(0, "Insights generated"), unsafe_allow_html=True)

# ============================================================
# DATA
# ============================================================

elif page == "Data":

    page_header("Data", "Import and explore the datasets used by BIFlow.")
    uploader("upload_data")
    df = st.session_state["df"]

    if df is not None:
        st.markdown('<div class="bf-section">Summary</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.markdown(kpi(f"{len(df):,}", "Rows"), unsafe_allow_html=True)
        c2.markdown(kpi(df.shape[1], "Columns"), unsafe_allow_html=True)
        c3.markdown(
            kpi(f"{df.memory_usage(deep=True).sum() / 1024:,.0f} KB", "Memory size"),
            unsafe_allow_html=True,
        )
        st.markdown('<div class="bf-section">Preview</div>', unsafe_allow_html=True)
        st.dataframe(df.head(100), use_container_width=True, height=360)
    else:
        empty_state("No dataset yet", "Upload a file above to preview it here.")

# ============================================================
# DATA QUALITY
# ============================================================

elif page == "Data Quality":

    page_header(
        "Data Quality",
        "Missing values, duplicates and overall health of your dataset.",
    )

    if df is None:
        empty_state("Nothing to check yet", "Import a dataset in the Data page to see its quality report.")
    else:
        total_cells = df.shape[0] * df.shape[1]
        missing = int(df.isna().sum().sum())
        dups = int(df.duplicated().sum())
        completeness = 100 * (1 - missing / total_cells) if total_cells else 100

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(kpi(f"{completeness:.1f}%", "Completeness"), unsafe_allow_html=True)
        c2.markdown(kpi(f"{missing:,}", "Missing values"), unsafe_allow_html=True)
        c3.markdown(kpi(f"{dups:,}", "Duplicate rows"), unsafe_allow_html=True)
        c4.markdown(kpi(df.shape[1], "Columns"), unsafe_allow_html=True)

        st.markdown('<div class="bf-section">Missing values by column</div>', unsafe_allow_html=True)
        miss = df.isna().sum().rename("Missing").to_frame()
        miss["Missing %"] = (100 * miss["Missing"] / max(len(df), 1)).round(1)
        miss["Type"] = df.dtypes.astype(str)
        left, right = st.columns([3, 2])
        with left:
            st.bar_chart(miss["Missing"], color="#0E9F8E", height=300)
        with right:
            st.dataframe(miss, use_container_width=True, height=300)

# ============================================================
# ANALYTICS
# ============================================================

elif page == "Analytics":

    page_header("Analytics", "Explore KPIs, trends and distributions.")

    if df is None:
        empty_state("No data to analyze", "Import a dataset in the Data page to explore it here.")
    else:
        num_cols = df.select_dtypes("number").columns.tolist()
        if not num_cols:
            empty_state("No numeric column found", "Analytics needs at least one numeric column.")
        else:
            col = st.selectbox("Measure", num_cols)
            s = df[col].dropna()
            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(kpi(f"{s.sum():,.0f}", "Total"), unsafe_allow_html=True)
            c2.markdown(kpi(f"{s.mean():,.2f}", "Average"), unsafe_allow_html=True)
            c3.markdown(kpi(f"{s.min():,.2f}", "Minimum"), unsafe_allow_html=True)
            c4.markdown(kpi(f"{s.max():,.2f}", "Maximum"), unsafe_allow_html=True)

            st.markdown('<div class="bf-section">Trend</div>', unsafe_allow_html=True)
            st.line_chart(s.reset_index(drop=True), color="#0E9F8E", height=300)

            cat_cols = df.select_dtypes(exclude="number").columns.tolist()
            if cat_cols:
                st.markdown('<div class="bf-section">By segment</div>', unsafe_allow_html=True)
                seg = st.selectbox("Group by", cat_cols)
                grouped = df.groupby(seg)[col].sum().sort_values(ascending=False).head(15)
                st.bar_chart(grouped, color="#6B5BD6", height=320)

# ============================================================
# AI AGENTS
# ============================================================

elif page == "AI Agents":

    page_header("AI Agents", "Follow what each agent is doing in the BIFlow workflow.")

    has_data = df is not None
    agents = [
        ("⚙️", "var(--teal-soft)", "Data Engineering Agent",
         "Profiles, cleans and transforms the dataset.",
         ("Ready", "pill-ready") if has_data else ("Waiting for dataset", "pill-wait")),
        ("📊", "var(--amber-soft)", "BI Analyst Agent",
         "Calculates KPIs, trends and anomalies.",
         ("Waiting for processed data", "pill-wait")),
        ("🔍", "var(--violet-soft)", "XAI / Auditor Agent",
         "Explains results and ensures traceability.",
         ("Waiting for analysis", "pill-wait")),
        ("🧠", "var(--rose-soft)", "Orchestrator Agent",
         "Coordinates the complete workflow.",
         ("Ready", "pill-ready")),
    ]
    for row in (agents[:2], agents[2:]):
        cols = st.columns(2)
        for col, (icon, bg, name, desc, (status, cls)) in zip(cols, row):
            with col:
                st.markdown(
                    f'<div class="bf-card"><div class="bf-icon" style="background:{bg}">{icon}</div>'
                    f"<h4>{name}</h4><p>{desc}</p>"
                    f'<span class="bf-pill {cls}">{status}</span></div>',
                    unsafe_allow_html=True,
                )
        st.write("")

# ============================================================
# AUDIT
# ============================================================

elif page == "Audit":

    page_header(
        "Explainability & Audit",
        "Trace how BIFlow turned your data into business insights.",
    )

    events = st.session_state["log"]
    if not events:
        empty_state("No activity yet", "Every step of the workflow will be recorded here.")
    else:
        html = '<div class="bf-card">'
        for t, e in events:
            html += f'<div class="bf-log"><time>{t}</time><div>{e}</div></div>'
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)