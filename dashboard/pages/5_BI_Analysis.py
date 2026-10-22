"""
BI Analysis — dashboard entièrement généré par le LLM.

Le dataset reçu est déjà nettoyé par l'Agent 1 (Data Engineering).
Cet agent se concentre uniquement sur :
  1. Profiler le dataset
  2. Demander au LLM de planifier KPIs + graphiques
  3. Exécuter le plan et afficher les résultats
"""
import os
import sys
from html import escape

import pandas as pd
import streamlit as st

# ── path ─────────────────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir    = os.path.abspath(os.path.join(current_dir, "../../"))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from components              import setup, page_header, btn, html, badge
from chat_widget             import render_chat
from agents.bi_analyst_agent import BIAnalystAgent
from dashboard_view          import render_kpis, render_chart_grid, insight_component

# ── setup ────────────────────────────────────────────────────────────────────
render_chat("Datasets")
setup("BI Analysis")

CLEANED_DIR = "data/cleaned_dataset/"
os.makedirs(CLEANED_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def read_csv_safe(path: str) -> pd.DataFrame:
    for enc in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, encoding="cp1252", encoding_errors="replace")


@st.cache_data(show_spinner=False)
def run_agent(file_path: str, mtime: float, language: str, currency) -> dict:
    """Lance l'agent BI et met le résultat en cache (clé = fichier + mtime + langue + devise)."""
    df = read_csv_safe(file_path)
    return BIAnalystAgent().build_dashboard(df, language=language, currency=currency)


def dataset_cache_key(filename: str, mtime: float, language: str, currency) -> str:
    return f"{filename}|{mtime}|{language}|{currency}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. Sélection du dataset + paramètres
# ─────────────────────────────────────────────────────────────────────────────
files = sorted(f for f in os.listdir(CLEANED_DIR) if f.endswith(".csv"))
if not files:
    st.warning(
        f"⚠️ Aucun dataset trouvé dans `{CLEANED_DIR}`. "
        "Importez et nettoyez un fichier via la page **Datasets**."
    )
    st.stop()

if st.session_state.get("active_dataset_filename") not in files:
    st.session_state.pop("active_dataset_filename", None)

col_sel, col_lang, col_cur, col_run = st.columns([4, 2, 2, 1])

with col_sel:
    st.markdown("**Dataset à analyser**")
    selected_filename = st.selectbox(
        "Dataset", files,
        key="active_dataset_filename",
        label_visibility="collapsed",
    )

with col_lang:
    st.markdown("**Langue**")
    language = st.selectbox(
        "Langue",
        ["English", "French", "Arabic", "Spanish", "German"],
        key="bi_language",
        label_visibility="collapsed",
    )

with col_cur:
    st.markdown("**Devise (optionnel)**")
    currency = st.text_input(
        "Devise", value="", placeholder="ex. $, €, £ …",
        key="bi_currency", label_visibility="collapsed",
    ).strip() or None

with col_run:
    st.markdown("&nbsp;", unsafe_allow_html=True)
    if st.button("🔄", help="Effacer le cache et relancer l'analyse"):
        run_agent.clear()
        st.session_state.pop("bi_dashboard",   None)
        st.session_state.pop("bi_dataset_key", None)
        st.rerun()

file_path    = os.path.join(CLEANED_DIR, selected_filename)
mtime        = os.path.getmtime(file_path)
current_key  = dataset_cache_key(selected_filename, mtime, language, currency)
dataset_name = selected_filename.replace(".csv", "").replace("_", " ").title()

# ─────────────────────────────────────────────────────────────────────────────
# 2. Lancement automatique dès que le dataset / la langue change
# ─────────────────────────────────────────────────────────────────────────────
is_cached = (
    st.session_state.get("bi_dataset_key") == current_key
    and "bi_dashboard" in st.session_state
)

if not is_cached:
    with st.spinner(f"🤖 L'agent BI analyse **{selected_filename}** et conçoit le dashboard…"):
        try:
            dash = run_agent(file_path, mtime, language, currency)
        except Exception as e:
            st.error(f"❌ L'agent BI a échoué : {e}")
            st.info("💡 Vérifiez votre clé API dans `.env` et le nom du modèle LLM.")
            st.stop()

    st.session_state["bi_dashboard"]   = dash
    st.session_state["bi_dataset_key"] = current_key
    st.rerun()   # re-render propre sans le spinner
else:
    dash = st.session_state["bi_dashboard"]

# ─────────────────────────────────────────────────────────────────────────────
# 3. Partager le contexte avec le chat widget
# ─────────────────────────────────────────────────────────────────────────────
st.session_state["dashboard_context"] = {
    "file":            selected_filename,
    "filters":         [],                   # dataset déjà nettoyé, pas de filtres
    "derived_columns": dash["derived_columns"],
    "kpis": [
        {"title": k["title"], "value": k.get("value_text") or round(k["value"], 2)}
        for k in dash["kpis"]
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. En-tête
# ─────────────────────────────────────────────────────────────────────────────
page_header(
    "Business Intelligence Analysis",
    "KPIs et dashboards générés automatiquement par le LLM.",
    btn("⭳ Export report") + btn("✨ Create workflow", True),
    f"{dataset_name} / <b>Analysis</b>",
)

cache_badge = badge("● Résultat en cache", "indigo") if is_cached else badge("● Nouvelle analyse", "blue")
html(f'''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center;margin-bottom:1rem">
  🗄 <small style="color:#4338ca"><b>DATASET ACTIF</b></small>
  <b>{escape(dataset_name)}</b> ·
  {dash["total_rows"]:,} lignes · langue : <b>{escape(language)}</b>
  {f"· devise : <b>{escape(currency)}</b>" if currency else ""}
  <span style="margin-left:auto">{cache_badge}</span>
</div>''')

# ─────────────────────────────────────────────────────────────────────────────
# 5. Vue injectée depuis le chat
# ─────────────────────────────────────────────────────────────────────────────
view = st.session_state.get("injected_view")
if view and view.get("file") != selected_filename:
    view = None

show_default = not (view and view.get("placement") == "replace")

if view:
    with st.container(border=True):
        left, right = st.columns([6, 1], vertical_alignment="center")
        with left:
            st.markdown(f"### ✨ {view['title']}")
            st.caption(f"Demandé dans le chat : « {view['question']} »")
        with right:
            label = "↩ Dashboard principal" if not show_default else "✕ Fermer"
            if st.button(label, key=f"close_view_{view['id']}"):
                st.session_state.pop("injected_view", None)
                st.rerun()
        render_kpis(view["kpis"])
        render_chart_grid(view["charts"])

# ─────────────────────────────────────────────────────────────────────────────
# 6. Dashboard principal
# ─────────────────────────────────────────────────────────────────────────────
if show_default:

    # Résumé exécutif
    if dash.get("summary"):
        st.info(f"📋 **Résumé :** {dash['summary']}")

    # Raisonnement de l'agent (collapsé par défaut)
    with st.expander("🧠 Raisonnement de l'agent BI", expanded=False):
        st.markdown(f"**Contexte métier :** {dash['business_context']}")

        if dash["derived_columns"]:
            st.markdown("**Colonnes calculées par l'agent :**")
            for d in dash["derived_columns"]:
                st.markdown(
                    f"- `{d.get('name')}` = "
                    f"{d.get('operation')}({', '.join(d.get('columns', []))}) "
                    f"— {d.get('reasoning', '')}"
                )
        else:
            st.caption("Aucune colonne dérivée (toutes les métriques sont calculées directement).")

        if dash["repair_attempts"]:
            st.caption(
                f"ℹ️ Le plan a été auto-corrigé **{dash['repair_attempts']} fois** "
                "après des erreurs d'exécution."
            )

    # Erreurs non-fatales
    if dash["errors"]:
        with st.expander(
            f"⚠️ {len(dash['errors'])} élément(s) non produits",
            expanded=False,
        ):
            for e in dash["errors"]:
                st.markdown(f"- {e}")

    # ── KPIs ─────────────────────────────────────────────────────────────────
    if dash["kpis"]:
        st.markdown("### 📊 Indicateurs clés de performance")
        render_kpis(dash["kpis"])
    else:
        st.warning("⚠️ L'agent n'a produit aucun KPI pour ce dataset.")

    st.divider()

    # ── Graphiques ────────────────────────────────────────────────────────────
    if dash["charts"]:
        st.markdown("### 📈 Visualisations")
        render_chart_grid(dash["charts"])
    else:
        st.warning("⚠️ L'agent n'a produit aucun graphique pour ce dataset.")

    st.divider()

    # ── Insights IA ───────────────────────────────────────────────────────────
    insights = dash["insights"]
    if insights:
        html(
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<h3 style="margin:0">🔎 AI Insights</h3>'
            f'{badge(f"{len(insights)} insights fondés sur les données calculées")}'
            f'</div>'
        )
        st.markdown("")
        for i in range(0, len(insights), 3):
            row = insights[i:i + 3]
            for col, ins in zip(st.columns(len(row)), row):
                with col:
                    html(insight_component(
                        ins.get("tag", "INSIGHT"),
                        ins.get("title", ""),
                        ins.get("text", ""),
                        ins.get("confidence", 90),
                    ))

    # Footer
    st.divider()
    st.caption(
        f"Dashboard généré par **BIFlow Agent BI** · "
        f"`{selected_filename}` · {dash['total_rows']:,} lignes · {language}"
        + (f" · devise : {currency}" if currency else "")
        + (f" · {dash['repair_attempts']} réparation(s) auto" if dash["repair_attempts"] else "")
    )
