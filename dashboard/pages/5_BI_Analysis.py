import os
import sys
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

# ── BIFlow imports ────────────────────────────────────────────────────────────
from agents.bi_analyst_agent import BIAnalystAgent
from components import setup, page_header, btn, html, kpi, grid, card, badge, bar, donut, columns_chart, svg_line
from chat_widget import render_chat

# ── Chat widget ───────────────────────────────────────────────────────────────
render_chat("BI Analysis")

# ── Page setup ────────────────────────────────────────────────────────────────
setup("BI Analysis")
page_header(
    "Business Intelligence Analysis",
    "Turn your data into actionable insights with AI.",
    btn("⭳ Export report") + btn("✨ Create workflow", True),
    "Dynamic BI / <b>AI Analysis</b>",
)

# ── 1. Dataset selection / upload ─────────────────────────────────────────────
st.sidebar.markdown("### 🗄 Data Source")
data_dir = PROJECT_ROOT / "data"
available_csvs = []
if data_dir.exists():
    available_csvs = [p.relative_to(PROJECT_ROOT) for p in data_dir.glob("**/*.csv")]

source_mode = st.sidebar.radio(
    "Selection mode",
    ["📂 Choose an existing dataset", "📤 Upload a new CSV"],
)

df = None
dataset_name = ""

if source_mode == "📂 Choose an existing dataset":
    if available_csvs:
        csv_options = {str(p): p for p in available_csvs}
        selected_path_str = st.sidebar.selectbox("Select a file", list(csv_options.keys()))
        if selected_path_str:
            full_path = PROJECT_ROOT / csv_options[selected_path_str]
            try:
                df = pd.read_csv(full_path)
                dataset_name = full_path.name
            except Exception as e:
                st.sidebar.error(f"File read error: {e}")
    else:
        st.sidebar.warning("No CSV files found in `data/`.")
else:
    uploaded_file = st.sidebar.file_uploader("📂 Import a CSV file", type=["csv"])
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        dataset_name = uploaded_file.name

# ── Sidebar AI Provider Configuration ─────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("### 🤖 BI Agent Engine")

adapter_exists = (PROJECT_ROOT / "adapter" / "adapter_model.safetensors").exists()
engine_options = []
if adapter_exists:
    engine_options.append("⚡ Local Fine-Tuned (Qwen 2.5 3B LoRA)")
engine_options.append("☁️ Cloud API (Groq / Gemini)")

if "bi_engine_choice" not in st.session_state:
    st.session_state["bi_engine_choice"] = engine_options[0]

selected_engine_label = st.sidebar.radio(
    "Choose Agent Engine",
    engine_options,
    index=engine_options.index(st.session_state["bi_engine_choice"]) if st.session_state["bi_engine_choice"] in engine_options else 0,
    key="sidebar_bi_engine_radio",
    help="Toggle between Local LoRA (runs 100% offline on your RTX 4050 GPU using compact statistical summaries) and Cloud API (uses prompt engineering with external LLMs)."
)
st.session_state["bi_engine_choice"] = selected_engine_label

is_local = "Local" in selected_engine_label
chosen_engine = "local_lora" if is_local else "api"

custom_groq_key = ""
if is_local:
    st.sidebar.success("🔒 **100% Offline & Private**\n- **Model**: Qwen 2.5-3B (4-bit NF4)\n- **Adapter**: LoRA Fine-Tuned\n- **Prompt**: Compact Dataset Summary\n- **Hardware**: NVIDIA RTX 4050")
else:
    st.sidebar.info("☁️ **Cloud API Engine**\n- **Provider**: Groq Llama-3.3 70B / Gemini\n- **Prompt**: Long Prompt Engineering\n- **Internet**: Required")
    custom_groq_key = st.sidebar.text_input(
        "Groq API Key (Optional)",
        value=os.environ.get("GROQ_API_KEY", "") or st.session_state.get("groq_api_key", ""),
        type="password",
        help="Enter your Groq key. If blank, Gemini or smart heuristics are used.",
    )
    if custom_groq_key:
        os.environ["GROQ_API_KEY"] = custom_groq_key
        st.session_state["groq_api_key"] = custom_groq_key

if df is None:
    st.warning("⚠️ Please select an existing dataset or upload one via the sidebar to start the analysis.")
    st.stop()

# ── Main Page Engine Quick-Switcher Tool ──────────────────────────────────────
st.markdown("### 🔀 BI Agent Engine Switcher")
col_sw1, col_sw2 = st.columns([1, 1])

with col_sw1:
    main_engine = st.radio(
        "Active Engine Mode:",
        engine_options,
        index=engine_options.index(st.session_state["bi_engine_choice"]) if st.session_state["bi_engine_choice"] in engine_options else 0,
        horizontal=True,
        key="main_page_engine_radio"
    )
    if main_engine != st.session_state["bi_engine_choice"]:
        st.session_state["bi_engine_choice"] = main_engine
        st.rerun()

with col_sw2:
    if is_local:
        st.caption("⚡ **Local LoRA Active**: Zero data leaves your PC. Powered by Qwen 2.5 3B with your fine-tuned LoRA weights on GPU. Uses the specialized **compact dataset summary** prompt.")
    else:
        st.caption("☁️ **Cloud API Active**: High-reasoning inference via Groq/Gemini. Uses **comprehensive prompt engineering** with multi-section instructions and JSON schema guidelines.")

# ── 2. Dataset status banner ──────────────────────────────────────────────────
active_engine_name = "⚡ Local Qwen 2.5-3B (LoRA RTX 4050)" if is_local else ("☁️ Groq Llama-3" if (custom_groq_key or os.environ.get("GROQ_API_KEY")) else "☁️ Gemini / Smart Fallback")
badge_color = "purple" if is_local else "blue"

html(f'''<div class="bf-card" style="background:linear-gradient(135deg,#eef2ff,#f8faff);
  border:1px solid #c7d2fe;display:flex;gap:1rem;align-items:center;
  margin-bottom:1.5rem;border-radius:16px;padding:1rem 1.25rem;">🗄
  <small style="color:#4338ca;font-weight:700;">ACTIVE DATASET</small>
  <b style="color:#1e1b4b;">{dataset_name}</b>
  <span style="color:#64748b;">·</span> {df.shape[0]:,} rows
  <span style="color:#64748b;">·</span> {df.shape[1]} columns
  <span style="margin-left:auto">{badge(f"● {active_engine_name}", badge_color)}</span>
</div>''')

# ── 3. AI Agent analysis ──────────────────────────────────────────────────────
cache_key = f"bi_cache_{dataset_name}_{df.shape[0]}_{df.shape[1]}_{chosen_engine}_{bool(custom_groq_key)}"

if st.session_state.get("bi_cache_key") != cache_key:
    spinner_msg = (
        f"⚡ Running Local Fine-Tuned Qwen 2.5 3B (LoRA) on RTX 4050 for '{dataset_name}'…"
        if is_local
        else f"☁️ Querying Cloud API (Groq/Gemini) with Prompt Engineering for '{dataset_name}'…"
    )
    with st.spinner(spinner_msg):
        try:
            agent = BIAnalystAgent(api_key=custom_groq_key or None, engine=chosen_engine)
            full_response = agent.analyze(df, dataset_name=dataset_name)
            ai_analysis_report, chart_config = agent.parse_response(full_response)
            telemetry = agent.get_telemetry()

            st.session_state["bi_cache_key"]         = cache_key
            st.session_state["current_bi_report"]    = ai_analysis_report
            st.session_state["current_chart_config"] = chart_config
            st.session_state["current_bi_telemetry"] = telemetry

        except Exception as e:
            st.error(f"Error calling the AI agent: {e}")
            st.session_state["current_bi_report"]    = "Unable to generate analysis at this time."
            st.session_state["current_chart_config"] = {"kpis": [], "recommended_charts": []}
            st.session_state["current_bi_telemetry"] = {}

ai_analysis_report = st.session_state.get("current_bi_report", "")
chart_config       = st.session_state.get("current_chart_config", {"kpis": [], "recommended_charts": []})

# ── 4. Dynamic KPI cards (AI-driven with Python fallback) ─────────────────────
ai_kpis  = chart_config.get("kpis", [])
num_cols = list(df.select_dtypes(include=["number"]).columns)
cat_cols = list(df.select_dtypes(include=["object", "category"]).columns)

default_kpis = [
    {"title": "Row Count",      "value": f"{df.shape[0]:,}",
     "subtitle": "Total records"},
    {"title": f"Avg {num_cols[0][:10]}" if num_cols else "Variables",
     "value": f"{df[num_cols[0]].mean():.2f}" if num_cols else str(df.shape[1]),
     "subtitle": "Mean value"},
    {"title": f"Max {num_cols[0][:10]}" if num_cols else "Columns",
     "value": f"{df[num_cols[0]].max():.2f}" if num_cols else str(df.shape[1]),
     "subtitle": "Peak value"},
    {"title": f"Unique {cat_cols[0][:10]}" if cat_cols else "Dataset",
     "value": f"{df[cat_cols[0]].nunique():,}" if cat_cols else dataset_name[:12],
     "subtitle": "Distinct categories"},
]

while len(ai_kpis) < 4:
    ai_kpis.append(default_kpis[len(ai_kpis)])

html(grid([
    kpi(ai_kpis[0].get("title", "KPI 1"), str(ai_kpis[0].get("value", "-")), ai_kpis[0].get("subtitle", ""), "📊"),
    kpi(ai_kpis[1].get("title", "KPI 2"), str(ai_kpis[1].get("value", "-")), ai_kpis[1].get("subtitle", ""), "📈", "blue", "gray"),
    kpi(ai_kpis[2].get("title", "KPI 3"), str(ai_kpis[2].get("value", "-")), ai_kpis[2].get("subtitle", ""), "🔢"),
    kpi(ai_kpis[3].get("title", "KPI 4"), str(ai_kpis[3].get("value", "-")), ai_kpis[3].get("subtitle", ""), "🎯", "blue", "gray"),
], "g4"))


# ── 5. Chart rendering ────────────────────────────────────────────────────────
def find_best_column(col_name, available_cols):
    """Fuzzy-match a column name suggested by the AI against actual columns."""
    if not col_name:
        return None
    if col_name in available_cols:
        return col_name
    for c in available_cols:
        if c.lower() == col_name.lower():
            return c
    for c in available_cols:
        if col_name.lower() in c.lower() or c.lower() in col_name.lower():
            return c
    return None


st.markdown("---")
st.markdown("### 📊 AI-Generated Dashboards")
st.markdown(
    "<small style='color:#64748b;'>The BI Agent analysed the data structure and "
    "selected the most relevant visualisations below:</small>",
    unsafe_allow_html=True,
)

charts = chart_config.get("recommended_charts", [])

# Fallback charts if AI returned none
if not charts and cat_cols and num_cols:
    charts = [
        {"title": f"Distribution of {cat_cols[0]}", "type": "pie",       "column_x": cat_cols[0], "column_y": None},
        {"title": f"Distribution of {num_cols[0]}", "type": "histogram", "column_x": num_cols[0], "column_y": None},
    ]

if charts:
    cols = st.columns(2)
    for i, chart in enumerate(charts):
        c_title = chart.get("title", "Analysis")
        c_type  = str(chart.get("type", "bar")).lower()
        c_x     = find_best_column(chart.get("column_x"), df.columns)
        c_y     = find_best_column(chart.get("column_y"), df.columns)

        if not c_x:
            c_x = cat_cols[0] if cat_cols else (num_cols[0] if num_cols else df.columns[0])

        with cols[i % 2]:
            with st.container(border=True):
                # Badge color & icon mapping
                if c_type == "pie":
                    b_tone = "purple"
                    c_icon = "🥧"
                    sub_desc = f"Proportions across <b>{c_x}</b>"
                elif c_type == "bar":
                    b_tone = "indigo"
                    c_icon = "📊"
                    sub_desc = f"Breakdown of <b>{c_x}</b>" + (f" vs <b>{c_y}</b>" if c_y else " (frequency)")
                elif c_type == "histogram":
                    b_tone = "blue"
                    c_icon = "📈"
                    sub_desc = f"Distribution curve of <b>{c_x}</b>"
                elif c_type == "box":
                    b_tone = "red"
                    c_icon = "📦"
                    sub_desc = f"Spread & outliers of <b>{c_x}</b>" + (f" by <b>{c_y}</b>" if c_y else "")
                else:
                    b_tone = "indigo"
                    c_icon = "📊"
                    sub_desc = f"Analysis of <b>{c_x}</b>"

                # Render Card Header with Title, Subtitle, and Badge
                html(f'''
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.75rem; padding-bottom:0.4rem; border-bottom:1px solid #f1f5f9;">
                    <div>
                        <div style="display:flex; align-items:center; gap:0.4rem;">
                            <span style="font-size:1.1rem;">{c_icon}</span>
                            <h4 style="margin:0; font-size:1.05rem; font-weight:700; color:#0f172a; letter-spacing:-0.01em;">{c_title}</h4>
                        </div>
                        <div style="font-size:0.8rem; color:#64748b; margin-top:0.25rem;">{sub_desc}</div>
                    </div>
                    <div>{badge(c_type.upper(), b_tone)}</div>
                </div>
                ''')

                try:
                    if c_type == "pie":
                        data_pie = df[c_x].value_counts().reset_index()
                        data_pie.columns = [c_x, "Count"]
                        fig = px.pie(
                            data_pie.head(10),
                            names=c_x,
                            values="Count",
                            hole=0.45,
                            color_discrete_sequence=px.colors.sequential.Purp_r
                        )
                        fig.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#0f172a", family="Inter, sans-serif"),
                            legend=dict(font=dict(color="#334155", size=11)),
                            margin=dict(t=10, b=10, l=10, r=10)
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    elif c_type == "bar":
                        if c_y and c_y in df.columns and df[c_y].dtype in ["int64", "float64"]:
                            agg_df = df.groupby(c_x, observed=False)[c_y].mean().reset_index()
                            fig = px.bar(agg_df.head(15), x=c_x, y=c_y, color_discrete_sequence=["#6366f1"])
                        else:
                            data_bar = df[c_x].value_counts().reset_index()
                            data_bar.columns = [c_x, "Count"]
                            fig = px.bar(data_bar.head(15), x=c_x, y="Count", color_discrete_sequence=["#6366f1"])

                        fig.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#0f172a", family="Inter, sans-serif"),
                            xaxis=dict(
                                tickfont=dict(color="#334155", size=11),
                                title_font=dict(color="#0f172a", size=12),
                                gridcolor="#f1f5f9"
                            ),
                            yaxis=dict(
                                tickfont=dict(color="#334155", size=11),
                                title_font=dict(color="#0f172a", size=12),
                                gridcolor="#f1f5f9"
                            ),
                            margin=dict(t=15, b=25, l=25, r=15)
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    elif c_type == "histogram":
                        fig = px.histogram(df, x=c_x, color_discrete_sequence=["#8b5cf6"])
                        fig.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#0f172a", family="Inter, sans-serif"),
                            xaxis=dict(
                                tickfont=dict(color="#334155", size=11),
                                title_font=dict(color="#0f172a", size=12),
                                gridcolor="#f1f5f9"
                            ),
                            yaxis=dict(
                                tickfont=dict(color="#334155", size=11),
                                title_font=dict(color="#0f172a", size=12),
                                gridcolor="#f1f5f9"
                            ),
                            margin=dict(t=15, b=25, l=25, r=15)
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    elif c_type == "box":
                        if c_y and c_y in df.columns and df[c_y].dtype in ["int64", "float64"]:
                            fig = px.box(df, x=c_x, y=c_y, color_discrete_sequence=["#c026d3"])
                        else:
                            fig = px.box(df, y=c_x, color_discrete_sequence=["#c026d3"])

                        fig.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#0f172a", family="Inter, sans-serif"),
                            xaxis=dict(
                                tickfont=dict(color="#334155", size=11),
                                title_font=dict(color="#0f172a", size=12),
                                gridcolor="#f1f5f9"
                            ),
                            yaxis=dict(
                                tickfont=dict(color="#334155", size=11),
                                title_font=dict(color="#0f172a", size=12),
                                gridcolor="#f1f5f9"
                            ),
                            margin=dict(t=15, b=25, l=25, r=15)
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    else:
                        fig = px.histogram(df, x=c_x, color_discrete_sequence=["#6366f1"])
                        fig.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#0f172a", family="Inter, sans-serif"),
                            margin=dict(t=15, b=25, l=25, r=15)
                        )
                        st.plotly_chart(fig, use_container_width=True)

                except Exception as chart_err:
                    st.warning(f"Could not render chart ({c_title}): {chart_err}")
else:
    st.info("No charts configured for this dataset.")


# ── 6. Full AI report & Prompt Telemetry Inspector ────────────────────────────
st.markdown("---")
tab_report, tab_prompt = st.tabs(["🧠 Full Executive AI Report", "🔍 Prompt Engineering & Engine Telemetry"])

with tab_report:
    st.markdown(ai_analysis_report)

with tab_prompt:
    telemetry = st.session_state.get("current_bi_telemetry", {})
    t_mode = telemetry.get("execution_mode", active_engine_name)
    t_prompt_type = telemetry.get("prompt_type", "Standard")
    t_prompt = telemetry.get("prompt_used", "")
    t_sys = telemetry.get("system_prompt", "")

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown(f"**⚡ Active Engine:** `{t_mode}`")
    with col_t2:
        st.markdown(f"**📝 Prompt Strategy:** `{t_prompt_type}`")

    if is_local:
        st.info(
            "💡 **Mode Local Qwen 2.5-3B LoRA :** Le modèle a été fine-tuné spécifiquement pour analyser "
            "directement le résumé statistique compact du dataset. Il n'a pas besoin du long prompt verbeux !"
        )
    else:
        st.info(
            "💡 **Mode Cloud API (Groq/Gemini) :** Les LLMs généralistes requièrent un prompt engineering exhaustif "
            "avec persona d'expert BI, instructions multi-sections, consignes strictes et structure JSON."
        )

    if t_sys and t_sys != "N/A":
        with st.expander("📌 System Prompt envoyé au modèle", expanded=False):
            st.code(t_sys, language="text")

    st.markdown("**📄 Prompt / Dataset Summary transmis au modèle :**")
    st.code(t_prompt if t_prompt else "Aucun prompt enregistré.", language="text")

# ── 7. Actions ────────────────────────────────────────────────────────────────
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    if st.button("⭳ Download Markdown Report", use_container_width=True):
        st.download_button(
            label="Confirm download",
            data=ai_analysis_report,
            file_name="BIFlow_BI_Analysis_Report.md",
            mime="text/markdown",
        )
with col2:
    if st.button("🔄 Re-run AI Analysis", type="primary", use_container_width=True):
        # Clear the cache so the next rerun triggers a fresh analysis
        st.session_state.pop("bi_cache_key", None)
        st.rerun()