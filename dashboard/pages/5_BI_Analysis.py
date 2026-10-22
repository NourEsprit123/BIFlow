import os
import sys
import json
import re
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv

# Gestion des chemins (monte de 2 niveaux pour atteindre la racine BIFlow)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from agents.bi_analyst_agent import BIAnalystAgent
from components import setup, page_header, btn, html, kpi, grid, card, badge, bar, donut, columns_chart, svg_line
from chat_widget import render_chat

# Connexion du widget de chat flottant
render_chat("BI Analysis")

setup("BI Analysis")
page_header(
    "Business Intelligence Analysis", 
    "Turn your data into actionable insights with AI.",
    btn("⭳ Export report") + btn("✨ Create workflow", True), 
    "Dynamic BI / <b>AI Analysis</b>"
)

# --- 1. Sélection ou Importation du Dataset ---
st.sidebar.markdown("### 🗄 Source de Données")
data_dir = PROJECT_ROOT / "data"
available_csvs = []
if data_dir.exists():
    available_csvs = [p.relative_to(PROJECT_ROOT) for p in data_dir.glob("**/*.csv")]

source_mode = st.sidebar.radio("Mode de sélection", ["📁 Choisir un dataset existant", "📤 Uploader un nouveau CSV"])

df = None
dataset_name = ""

if source_mode == "📁 Choisir un dataset existant":
    if available_csvs:
        csv_options = {str(p): p for p in available_csvs}
        selected_path_str = st.sidebar.selectbox("Sélectionner un fichier", list(csv_options.keys()))
        if selected_path_str:
            full_path = PROJECT_ROOT / csv_options[selected_path_str]
            try:
                df = pd.read_csv(full_path)
                dataset_name = full_path.name
            except Exception as e:
                st.sidebar.error(f"Erreur de lecture du fichier : {e}")
    else:
        st.sidebar.warning("Aucun fichier CSV trouvé dans le dossier `data/`.")
else:
    uploaded_file = st.sidebar.file_uploader("📂 Importer un fichier CSV", type=["csv"])
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        dataset_name = uploaded_file.name

if df is None:
    st.warning("⚠️ Veuillez sélectionner un dataset existant ou en importer un via la barre latérale pour lancer l'analyse.")
    st.stop()

# --- 2. En-tête de Statut du Dataset ---
html(f'''<div class="bf-card" style="background:linear-gradient(135deg, #eef2ff, #f8faff); border: 1px solid #c7d2fe; display:flex; gap:1rem; align-items:center; margin-bottom:1.5rem; border-radius: 16px; padding: 1rem 1.25rem;">🗄
  <small style="color:#4338ca; font-weight: 700;">ACTIVE DATASET</small> <b style="color: #1e1b4b;">{dataset_name}</b> <span style="color:#64748b">·</span> {df.shape[0]:,} lignes <span style="color:#64748b">·</span> {df.shape[1]} colonnes
  <span style="margin-left:auto">{badge("● Results ready", "blue")}</span></div>''')


# --- 3. Analyse Dynamique via l'Agent Groq ---
with st.spinner(f"🤖 L'Agent BI Analyst analyse '{dataset_name}' et extrait les KPI dynamiques..."):
    try:
        agent = BIAnalystAgent()
        full_response = agent.analyze(df)
        
        chart_config = {"kpis": [], "recommended_charts": []}
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', full_response, re.DOTALL)
        if json_match:
            try:
                chart_config = json.loads(json_match.group(1))
            except:
                pass
        
        ai_analysis_report = re.sub(r'```(?:json)?.*?\s*```', '', full_response, flags=re.DOTALL).strip()

        st.session_state["current_bi_report"] = ai_analysis_report
        st.session_state["current_chart_config"] = chart_config
        
    except Exception as e:
        st.error(f"Erreur lors de l'appel à l'API Groq : {e}")
        ai_analysis_report = "Impossible de générer l'analyse pour le moment."
        chart_config = {"kpis": [], "recommended_charts": []}


# --- 4. Affichage des KPIs Dynamiques décidés par l'IA (avec Fallback Python) ---
ai_kpis = chart_config.get("kpis", [])

# Fallback statistique calculé par Python si l'IA n'a pas renvoyé assez de KPIs
num_cols = list(df.select_dtypes(include=['number']).columns)
cat_cols = list(df.select_dtypes(include=['object', 'category']).columns)

default_kpis = [
    {"title": "Volume Lignes", "value": f"{df.shape[0]:,}", "subtitle": "Enregistrements totaux"},
    {"title": f"Moy. ({num_cols[0][:8]})" if num_cols else "Variables", "value": f"{df[num_cols[0]].mean():.2f}" if num_cols else str(df.shape[1]), "subtitle": "Indicateur moyen"},
    {"title": f"Max ({num_cols[0][:8]})" if num_cols else "Colonnes", "value": f"{df[num_cols[0]].max():.2f}" if num_cols else str(df.shape[1]), "subtitle": "Pic maximal"},
    {"title": f"Uniques ({cat_cols[0][:8]})" if cat_cols else "Dataset", "value": f"{df[cat_cols[0]].nunique():,}" if cat_cols else dataset_name[:12], "subtitle": "Catégories distinctes"}
]

while len(ai_kpis) < 4:
    ai_kpis.append(default_kpis[len(ai_kpis)])

html(grid([
    kpi(ai_kpis[0].get("title", "KPI 1"), str(ai_kpis[0].get("value", "-")), ai_kpis[0].get("subtitle", ""), "📊"), 
    kpi(ai_kpis[1].get("title", "KPI 2"), str(ai_kpis[1].get("value", "-")), ai_kpis[1].get("subtitle", ""), "📈", "blue", "gray"),
    kpi(ai_kpis[2].get("title", "KPI 3"), str(ai_kpis[2].get("value", "-")), ai_kpis[2].get("subtitle", ""), "⚡"), 
    kpi(ai_kpis[3].get("title", "KPI 4"), str(ai_kpis[3].get("value", "-")), ai_kpis[3].get("subtitle", ""), "🏷️", "blue", "gray")
], "g4"))


# --- Fonction utilitaire pour trouver une colonne de manière intelligente (Fuzzy Matching) ---
def find_best_column(col_name, available_cols):
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


# --- 5. Rendu Automatique et Robuste des Graphiques ---
st.markdown("---")
st.markdown("### 📈 Tableaux de Bord Générés par l'IA")
st.markdown("<small style='color: #64748b;'>L'Agent BI a analysé la structure des données et sélectionné les visualisations pertinentes ci-dessous :</small>", unsafe_allow_html=True)

charts = chart_config.get("recommended_charts", [])

if not charts and cat_cols and num_cols:
    charts = [
        {"title": f"Répartition de {cat_cols[0]}", "type": "pie", "column_x": cat_cols[0], "column_y": None},
        {"title": f"Distribution de {num_cols[0]}", "type": "histogram", "column_x": num_cols[0], "column_y": None}
    ]

if charts:
    cols = st.columns(2)
    for i, chart in enumerate(charts):
        c_title = chart.get("title", "Analyse")
        c_type = chart.get("type", "bar")
        
        c_x = find_best_column(chart.get("column_x"), df.columns)
        c_y = find_best_column(chart.get("column_y"), df.columns)

        if not c_x:
            c_x = cat_cols[0] if cat_cols else (num_cols[0] if num_cols else df.columns[0])

        with cols[i % 2]:
            st.markdown(f"<div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:1rem; margin-bottom:1.0rem; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);'>", unsafe_allow_html=True)
            try:
                if c_type == "pie":
                    data_pie = df[c_x].value_counts().reset_index()
                    data_pie.columns = [c_x, 'Count']
                    fig = px.pie(data_pie.head(10), names=c_x, values='Count', title=c_title, hole=0.4, color_discrete_sequence=px.colors.sequential.Purp_r)
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig, use_container_width=True)

                elif c_type == "bar":
                    if c_y and c_y in df.columns and df[c_y].dtype in ['int64', 'float64']:
                        agg_df = df.groupby(c_x, observed=False)[c_y].mean().reset_index()
                        fig = px.bar(agg_df.head(15), x=c_x, y=c_y, title=c_title, color_discrete_sequence=["#6366f1"])
                    else:
                        data_bar = df[c_x].value_counts().reset_index()
                        data_bar.columns = [c_x, 'Count']
                        fig = px.bar(data_bar.head(15), x=c_x, y='Count', title=c_title, color_discrete_sequence=["#6366f1"])
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig, use_container_width=True)

                elif c_type == "histogram":
                    fig = px.histogram(df, x=c_x, title=c_title, color_discrete_sequence=["#8b5cf6"])
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig, use_container_width=True)

                elif c_type == "box":
                    if c_y and c_y in df.columns and df[c_y].dtype in ['int64', 'float64']:
                        fig = px.box(df, x=c_x, y=c_y, title=c_title, color_discrete_sequence=["#c026d3"])
                    else:
                        fig = px.box(df, y=c_x, title=c_title, color_discrete_sequence=["#c026d3"])
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    fig = px.histogram(df, x=c_x, title=c_title, color_discrete_sequence=["#6366f1"])
                    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=40, b=20, l=20, r=20))
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as chart_err:
                st.warning(f"Impossible de rendre ce graphique ({c_title}) : {chart_err}")
            st.markdown("</div>", unsafe_allow_html=True)
else:
    st.info("Aucun graphique configuré pour ce dataset.")


# --- 6. Affichage du Rapport dans un Expander (Cliquable) ---
st.markdown("---")
with st.expander("🧠 Afficher le Rapport d'Intelligence Artificielle & Insights complet", expanded=False):
    st.markdown(ai_analysis_report)

# Section d'export ou d'action
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    if st.button("📥 Télécharger le rapport Markdown", use_container_width=True):
        st.download_button(
            label="Confirmer le téléchargement",
            data=ai_analysis_report,
            file_name="BIFlow_BI_Analysis_Report.md",
            mime="text/markdown"
        )
with col2:
    if st.button("✨ Relancer l'analyse Agent", type="primary", use_container_width=True):
        st.rerun()