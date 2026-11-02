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
setup("BI Analysis", hub="Agent 2 · BI Analyst")
page_header(
    "Business Intelligence Analysis",
    "Turn your data into actionable insights with AI.",
    badge("Agent 2", "blue"),
    "Agent 2 · BI Analyst > <b>Analysis & Dashboards</b>",
)

# ── 1. Sidebar Dataset Selector (synchronisé avec Workflows et session globale) ──
st.sidebar.markdown("### 💾 Jeu de données")
raw_dir   = PROJECT_ROOT / "data" / "raw"
clean_dir = PROJECT_ROOT / "data" / "cleaned"
all_csvs   = sorted(raw_dir.glob("*.csv"))   if raw_dir.exists()   else []
clean_csvs = sorted(clean_dir.glob("*.csv")) if clean_dir.exists() else []

dataset_map = {}
for f in all_csvs:
    dataset_map[f.name] = str(f)
for f in clean_csvs:
    dataset_map[f"✨ [Nettoyé] {f.name}"] = str(f)

file_names = list(dataset_map.keys())
NONE_OPT   = "— Sélectionner —"

default_idx = 0
current_preset = st.session_state.get("current_dataset_path") or st.session_state.get("wf_file")
if current_preset:
    preset_name = Path(current_preset).name
    for idx, name in enumerate([NONE_OPT] + file_names):
        if preset_name in name:
            default_idx = idx
            break

selected_name = st.sidebar.selectbox(
    "Dataset source",
    [NONE_OPT] + file_names,
    index=default_idx,
    key="bi_dataset_select",
)
selected_path = dataset_map.get(selected_name) if selected_name != NONE_OPT else None

if selected_path:
    st.session_state["current_dataset_path"] = selected_path
    st.session_state["wf_file"] = selected_path

df = None
dataset_name = ""

if not selected_path or not Path(selected_path).exists():
    st.info("⬆️ Veuillez sélectionner un dataset dans la barre latérale pour afficher l'analyse BI.")
    st.stop()

try:
    df = pd.read_csv(selected_path)
    dataset_name = Path(selected_path).name
except Exception as e:
    st.error(f"Erreur de lecture du fichier : {e}")
    st.stop()

# ── Sidebar AI Provider Configuration ─────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.markdown("### 🤖 BI Agent Engine")

adapter_exists = (PROJECT_ROOT / "adapter" / "adapter_model.safetensors").exists()
engine_options = []
if adapter_exists:
    engine_options.append("⚡ Local Fine-Tuned (Qwen 2.5 3B LoRA)")
engine_options.append("☁️ Cloud API (Groq / Gemini)")

wf_rm = st.session_state.get("wf_resource_mode", "auto")
if wf_rm == "cloud" or st.session_state.get("_synced_wf_res") != wf_rm:
    st.session_state["_synced_wf_res"] = wf_rm
    if wf_rm == "cloud":
        st.session_state["bi_engine_choice"] = "☁️ Cloud API (Groq / Gemini)"
    elif wf_rm == "local" and adapter_exists:
        st.session_state["bi_engine_choice"] = "⚡ Local Fine-Tuned (Qwen 2.5 3B LoRA)"

if "bi_engine_choice" not in st.session_state:
    st.session_state["bi_engine_choice"] = (
        "☁️ Cloud API (Groq / Gemini)" if wf_rm == "cloud" or not adapter_exists
        else "⚡ Local Fine-Tuned (Qwen 2.5 3B LoRA)"
    )

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
    _env_groq = os.environ.get("GROQ_API_KEY", "")
    if _env_groq:
        st.sidebar.caption("🔑 **Groq API** : Configurée via `.env` ✅")
        with st.sidebar.expander("⚙️ Remplacer la clé API", expanded=False):
            custom_groq_key = st.text_input(
                "Nouvelle clé Groq",
                value="",
                type="password",
                placeholder="gsk_…",
                key="bi_custom_groq_key",
            )
            if custom_groq_key:
                os.environ["GROQ_API_KEY"] = custom_groq_key
                st.session_state["groq_api_key"] = custom_groq_key
    else:
        custom_groq_key = st.sidebar.text_input(
            "Groq API Key (optionnel)",
            value="",
            type="password",
            placeholder="gsk_…",
            key="bi_custom_groq_key",
            help="Entrez votre clé Groq. Si vide, Gemini ou les heuristiques seront utilisées.",
        )
        if custom_groq_key:
            os.environ["GROQ_API_KEY"] = custom_groq_key
            st.session_state["groq_api_key"] = custom_groq_key

# ── 2. Dataset status banner + Action button ──────────────────────────────────
_current_telem = st.session_state.get("current_bi_telemetry", {}) or {}
if _current_telem.get("provider") and _current_telem.get("provider") != "Unknown":
    active_engine_name = f"{_current_telem.get('provider')} ({_current_telem.get('model', '-')})"
    badge_color = "purple" if "Local" in str(_current_telem.get("provider")) else "blue"
else:
    active_engine_name = "⚡ Local Qwen 2.5-3B (LoRA RTX 4050)" if is_local else ("☁️ Groq Llama-3" if (custom_groq_key or os.environ.get("GROQ_API_KEY")) else "☁️ Gemini / Smart Fallback")
    badge_color = "purple" if is_local else "blue"

dataset_sig = f"{dataset_name}_{df.shape[0]}_{df.shape[1]}"
cache_key   = f"{dataset_sig}_{chosen_engine}_{bool(custom_groq_key)}"

# Synchroniser automatiquement avec le rapport issu du pipeline si disponible
wf_st = st.session_state.get("wf_graph_state") or {}
a2_rep = (wf_st.get("reports") or {}).get("bi_analyst", {})
if not a2_rep:
    a2_rep = (st.session_state.get("pipeline_results") or {}).get("agent2", {})

has_report = (
    (st.session_state.get("bi_dataset_sig") == dataset_sig and bool(st.session_state.get("current_bi_report")))
    or bool(a2_rep and a2_rep.get("markdown"))
)

is_cleaned = "_cleaned" in dataset_name or "cleaned" in str(selected_path)
clean_tag = " · ✨ [Nettoyé]" if is_cleaned else ""

col_card, col_btn = st.columns([3, 1], vertical_alignment="center")
with col_card:
    html(f'''<div class="bf-card" style="background:linear-gradient(135deg,#eef2ff,#f8faff);
      border:1px solid #c7d2fe;display:flex;gap:1rem;align-items:center;
      border-radius:16px;padding:0.9rem 1.25rem;margin-bottom:0.5rem">🗄
      <small style="color:#4338ca;font-weight:700;">DATASET SOURCE</small>
      <b style="color:#1e1b4b;">{dataset_name}</b>{clean_tag}
      <span style="color:#64748b;">·</span> {df.shape[0]:,} lignes
      <span style="color:#64748b;">·</span> {df.shape[1]} colonnes
      <span style="margin-left:auto">{badge(f"● {active_engine_name}", badge_color)}</span>
    </div>''')
with col_btn:
    run_clicked = st.button(
        "🔄 Relancer l'analyse" if has_report else "🚀 Lancer l'analyse",
        type="primary",
        width="stretch",
        key="bi_run_btn"
    )

with st.expander("👀 Aperçu des données", expanded=False):
    st.dataframe(df.head(10), width="stretch")

should_run = run_clicked or st.session_state.pop("bi_force_rerun", False)

if a2_rep and a2_rep.get("markdown") and not should_run:
    if st.session_state.get("bi_dataset_sig") != dataset_sig or not st.session_state.get("current_bi_report"):
        st.session_state["current_bi_report"]    = a2_rep.get("markdown", "")
        st.session_state["current_chart_config"] = a2_rep.get("chart_config", {"kpis": [], "recommended_charts": []})
        st.session_state["current_bi_telemetry"] = a2_rep.get("telemetry", {})
        st.session_state["bi_dataset_sig"]       = dataset_sig
        st.session_state["bi_cache_key"]         = cache_key

if should_run:
    spinner_msg = (
        f"⚡ Running Local Fine-Tuned Qwen 2.5 3B (LoRA) on RTX 4050 for '{dataset_name}'…"
        if is_local
        else f"☁️ Querying Cloud API (Groq/Gemini) with Prompt Engineering for '{dataset_name}'…"
    )
    with st.spinner(spinner_msg):
        try:
            agent = BIAnalystAgent(api_key=custom_groq_key or None, engine=chosen_engine)
            full_response = agent.analyze(df, dataset_name=dataset_name)
            report, cfg = agent.parse_response(full_response)

            st.session_state["current_bi_report"]    = report
            st.session_state["current_chart_config"] = cfg
            st.session_state["current_bi_telemetry"] = agent.get_telemetry()
        except Exception as e:
            st.error(f"Error calling the AI agent: {e}")
            st.session_state["current_bi_report"]    = "Unable to generate analysis at this time."
            st.session_state["current_chart_config"] = {"kpis": [], "recommended_charts": []}
            st.session_state["current_bi_telemetry"] = {}

        st.session_state["bi_dataset_sig"] = dataset_sig
        st.session_state["bi_cache_key"]   = cache_key

# Pas d'analyse pour ce dataset → on attend le clic
if st.session_state.get("bi_dataset_sig") != dataset_sig:
    st.info("👆 Cliquez sur **🚀 Lancer l'analyse** pour générer le rapport et les dashboards.")
    st.stop()

# Moteur changé depuis la dernière analyse
if st.session_state.get("bi_cache_key") != cache_key:
    st.warning("⚠️ Le moteur a changé depuis la dernière analyse. Relancez pour mettre à jour les résultats.")

ai_analysis_report = st.session_state.get("current_bi_report", "")
chart_config       = st.session_state.get("current_chart_config", {"kpis": [], "recommended_charts": []})

# Fournisseur réel ayant généré ce résultat
_t = st.session_state.get("current_bi_telemetry", {}) or {}
if _t.get("is_llm"):
    st.success(
        f"✅ Généré par **{_t.get('provider', '?')}** · modèle `{_t.get('model', '-')}` "
        f"· {_t.get('duration_s', 0)} s"
    )
elif _t:
    st.warning(
        "⚠️ **Aucun LLM n'a répondu** : ce rapport vient du moteur statistique Python (heuristique). "
        "Voir l'onglet Telemetry pour le détail des erreurs."
    )

# ── 4. Dynamic KPI cards (AI-driven with Python fallback) ─────────────────────
ai_kpis  = list(chart_config.get("kpis", []))
num_cols = list(df.select_dtypes(include=["number"]).columns)
cat_cols = list(df.select_dtypes(include=["object", "category", "string"]).columns)

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


def style_fig(fig, axes=True):
    """Apply the common BIFlow look to a plotly figure."""
    axis_style = dict(
        tickfont=dict(color="#334155", size=11),
        title_font=dict(color="#0f172a", size=12),
        gridcolor="#f1f5f9",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#0f172a", family="Inter, sans-serif"),
        margin=dict(t=15, b=25, l=25, r=15),
    )
    if axes:
        fig.update_layout(xaxis=axis_style, yaxis=axis_style)
    return fig


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
                    y_is_numeric = bool(c_y) and c_y in df.columns and pd.api.types.is_numeric_dtype(df[c_y])

                    if c_type == "pie":
                        data_pie = df[c_x].value_counts().reset_index()
                        data_pie.columns = [c_x, "Count"]
                        fig = px.pie(
                            data_pie.head(10),
                            names=c_x,
                            values="Count",
                            hole=0.45,
                            color_discrete_sequence=px.colors.sequential.Purp_r,
                        )
                        style_fig(fig, axes=False)
                        fig.update_layout(
                            legend=dict(font=dict(color="#334155", size=11)),
                            margin=dict(t=10, b=10, l=10, r=10),
                        )

                    elif c_type == "bar":
                        if y_is_numeric:
                            agg_df = df.groupby(c_x, observed=False)[c_y].mean().reset_index()
                            fig = px.bar(agg_df.head(15), x=c_x, y=c_y, color_discrete_sequence=["#6366f1"])
                        else:
                            data_bar = df[c_x].value_counts().reset_index()
                            data_bar.columns = [c_x, "Count"]
                            fig = px.bar(data_bar.head(15), x=c_x, y="Count", color_discrete_sequence=["#6366f1"])
                        style_fig(fig)

                    elif c_type == "histogram":
                        fig = px.histogram(df, x=c_x, color_discrete_sequence=["#8b5cf6"])
                        style_fig(fig)

                    elif c_type == "box":
                        if y_is_numeric:
                            fig = px.box(df, x=c_x, y=c_y, color_discrete_sequence=["#c026d3"])
                        else:
                            fig = px.box(df, y=c_x, color_discrete_sequence=["#c026d3"])
                        style_fig(fig)

                    else:
                        fig = px.histogram(df, x=c_x, color_discrete_sequence=["#6366f1"])
                        style_fig(fig, axes=False)

                    st.plotly_chart(fig, width="stretch", key=f"bi_chart_{i}")

                except Exception as chart_err:
                    st.warning(f"Could not render chart ({c_title}): {chart_err}")
else:
    st.info("No charts configured for this dataset.")


# ── 6. Full AI report & Prompt Telemetry Inspector ────────────────────────────
st.markdown("---")

# ── Sandbox status badge (always visible) ────────────────────────────────────
_sb_telemetry = st.session_state.get("current_bi_telemetry", {})
_sb_all        = _sb_telemetry.get("sandbox_results", [])
_sb_baseline   = next((e for e in _sb_all if e.get("type") == "baseline"), None)
_sb_llm_blocks = [e for e in _sb_all if e.get("type") == "llm"]

if not _sb_all:
    # Pas encore d'analyse
    st.caption("⬜ **Sandbox :** aucune analyse lancée — statut inconnu")
elif _sb_baseline and not _sb_baseline.get("error"):
    # Baseline OK
    _sb_llm_ok  = sum(1 for e in _sb_llm_blocks if not e.get("error"))
    _sb_llm_err = sum(1 for e in _sb_llm_blocks if e.get("error"))
    if _sb_llm_blocks:
        _badge_txt = (
            f"✅ **Sandbox exécuté** — moteur actif · "
            f"{_sb_llm_ok} bloc(s) LLM vérifié(s)"
            + (f" · {_sb_llm_err} erreur(s)" if _sb_llm_err else "")
        )
    else:
        _badge_txt = "✅ **Sandbox exécuté** — moteur actif! ·"
    st.success(_badge_txt)
else:
    st.error("❌ **Sandbox ERREUR** — le moteur n'a pas pu s'exécuter · voir ⚡ Sandbox Monitor")

tab_report, tab_prompt, tab_sandbox = st.tabs([
    "🧠 Full Executive AI Report",
    "🔍 Prompt Engineering & Engine Telemetry",
    "⚡ Sandbox Monitor",
])

with tab_report:
    st.markdown(ai_analysis_report)

with tab_prompt:
    telemetry = st.session_state.get("current_bi_telemetry", {})
    t_mode = telemetry.get("execution_mode", active_engine_name)
    t_prompt_type = telemetry.get("prompt_type", "Standard")
    t_prompt = telemetry.get("prompt_used", "")
    t_sys = telemetry.get("system_prompt", "")
    t_provider = telemetry.get("provider", "Unknown")
    t_model = telemetry.get("model", "-")
    t_attempts = telemetry.get("attempts", [])
    t_converted = telemetry.get("converted_columns", [])

    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        st.markdown(f"**🏢 Fournisseur réel :** `{t_provider}`")
    with col_t2:
        st.markdown(f"**🧩 Modèle :** `{t_model}`")
    with col_t3:
        st.markdown(f"**📝 Prompt Strategy:** `{t_prompt_type}`")

    if "Local" in str(t_provider):
        st.info(
            "💡 **Mode Local Qwen 2.5-3B LoRA :** Le modèle a été fine-tuné spécifiquement pour analyser "
            "directement le résumé statistique compact du dataset. Il n'a pas besoin du long prompt verbeux !"
        )
    elif telemetry.get("is_llm"):
        st.info(
            "💡 **Mode Cloud API :** Les LLMs généralistes requièrent un prompt engineering exhaustif "
            "avec persona d'expert BI, instructions multi-sections, consignes strictes et structure JSON."
        )
    else:
        st.info("💡 **Mode heuristique :** aucun LLM n'a été utilisé, le rapport est calculé en Python.")

    if t_converted:
        st.caption(f"🔧 Colonnes texte converties en numérique avant analyse : {', '.join(t_converted)}")

    if t_attempts:
        st.markdown("**🧾 Historique des tentatives (dans l'ordre) :**")
        icons = {"success": "✅", "failed": "❌", "skipped": "⏭️"}
        st.dataframe(
            pd.DataFrame([
                {"": icons.get(a["status"], "•"), "Fournisseur": a["provider"], "Modèle": a["model"],
                 "Statut": a["status"], "Détail": a["detail"]}
                for a in t_attempts
            ]),
            width="stretch",
            hide_index=True,
        )

    if t_sys and t_sys != "N/A":
        with st.expander("📌 System Prompt envoyé au modèle", expanded=False):
            st.code(t_sys, language="text")

    st.markdown("**📄 Prompt / Dataset Summary transmis au modèle :**")
    st.code(t_prompt if t_prompt else "Aucun prompt enregistré.", language="text")

    # (sandbox results moved to dedicated ⚡ Sandbox Monitor tab)

with tab_sandbox:
    # ── Sandbox Monitor Tab ──────────────────────────────────────────────────
    from analytics.kpi import run_bi_sandboxed_calc

    telemetry_sb = st.session_state.get("current_bi_telemetry", {})
    sb_results   = telemetry_sb.get("sandbox_results", [])
    is_heuristic = not telemetry_sb.get("is_llm", False)
    sb_provider  = telemetry_sb.get("provider", "")

    # ── Status badge ─────────────────────────────────────────────────────────
    st.markdown("### 🛡️ Statut du Moteur Sandbox In-Memory")

    if not sb_results:
        st.warning(
            "**Aucune analyse enregistrée dans la session courante.**  \n"
            "Veuillez lancer une analyse ou utiliser l'outil d'exécution manuel ci-dessous."
        )
    else:
        errors  = [e for e in sb_results if e.get("error")]
        success = [e for e in sb_results if not e.get("error")]
        if errors:
            st.error(f"**Sandbox exécuté avec erreurs — {len(errors)} bloc(s) en échec / {len(sb_results)} total**")
        else:
            st.success(f"**Sandbox actif et vérifié — {len(success)} calcul(s) exécuté(s) en environnement sécurisé**")

    # ── Résultats de la dernière analyse ─────────────────────────────────────
    if sb_results:
        st.markdown("---")
        st.markdown("#### Résultats des blocs exécutés lors de la dernière analyse")
        for entry in sb_results:
            b = entry["block"]
            if entry.get("error"):
                st.error(f"**Bloc {b}** — Erreur sandbox")
                st.code(entry["error"], language="text")
            else:
                st.success(f"**Bloc {b}** — Calcul vérifié sur les données réelles")
                st.json(entry["result"])

    # ── Test manuel du sandbox ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Tester le sandbox manuellement")
    st.caption(
        "Exécute un calcul de test sur le dataset chargé pour confirmer que le moteur "
        "sandbox fonctionne, indépendamment du LLM."
    )

    test_code = st.text_area(
        "Code à tester (doit définir `def compute_insight(df) -> dict`) :",
        value=(
            "def compute_insight(df):\n"
            "    n_rows = len(df)\n"
            "    n_cols = len(df.columns)\n"
            "    missing_pct = round(df.isnull().sum().sum() / (n_rows * n_cols) * 100, 2)\n"
            "    return {'nb_lignes': n_rows, 'nb_colonnes': n_cols, 'pct_manquant': missing_pct}"
        ),
        height=180,
        key="sandbox_test_code",
    )

    col_run, col_timeout = st.columns([3, 1])
    with col_timeout:
        timeout_val = st.number_input("Timeout (s)", min_value=1, max_value=30, value=5, key="sb_timeout")
    with col_run:
        run_test = st.button("Lancer le test sandbox", type="primary", width="stretch")

    if run_test:
        if df is None or df.empty:
            st.error("Aucun dataset chargé — chargez un fichier CSV d'abord.")
        else:
            with st.spinner("Exécution dans le sandbox..."):
                result, error = run_bi_sandboxed_calc(test_code, df, timeout_sec=int(timeout_val))
            if error:
                st.error("**Sandbox ERREUR**")
                st.code(error, language="text")
            else:
                st.success("**Sandbox OK — calcul exécuté sur les données réelles**")
                st.json(result)
                st.caption(
                    f"Données : {df.shape[0]} lignes x {df.shape[1]} colonnes  "
                    f"| Timeout : {timeout_val}s"
                )

# ── 7. Actions ────────────────────────────────────────────────────────────────
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    st.download_button(
        "⭳ Download Markdown Report",
        data=ai_analysis_report,
        file_name="BIFlow_BI_Analysis_Report.md",
        mime="text/markdown",
        width="stretch",
    )
with col2:
    if st.button("🔄 Re-run AI Analysis", type="primary", width="stretch"):
        st.session_state["bi_force_rerun"] = True
        st.rerun()