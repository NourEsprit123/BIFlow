import streamlit as st
import pandas as pd
import altair as alt
import os
import sys
from html import escape

# --- AJOUTER LA RACINE DU PROJET AU SYS.PATH ---
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../"))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from components import setup, page_header, btn, html, kpi, badge, bar, donut
from chat_widget import render_chat
from agents.bi_analyst_agent import BIAnalystAgent

render_chat("Datasets")
setup("BI Analysis")

LANGUAGE = "English"   # langue des titres / insights générés par l'agent (ex. "French")
CURRENCY = None        # optionnel, ex. "£" ; si None l'agent déduit (ou laisse vide)


def read_csv_safe(path: str) -> pd.DataFrame:
    for enc in ("utf-8", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, encoding="cp1252", encoding_errors="replace")


def fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def format_number(value: float, kind: str, unit: str) -> str:
    unit = unit or ""
    if kind == "percent":
        return f"{value:,.1f}%"
    s = f"{value:,.0f}" if (kind == "integer" or abs(value) >= 100_000) else f"{value:,.2f}"
    return f"{unit}{s}" if kind == "currency" else f"{s} {unit}".strip()


def kpi_texts(k: dict):
    """(valeur affichée, ligne de détail). Un libellé trop long pour la carte passe en détail
    et la carte affiche le chiffre associé."""
    detail = k.get("detail") or k["subtitle"]
    label = k.get("value_text")
    if label and len(label) <= 16:
        return label, detail
    if label:
        return format_number(k["value"], k["format"], k["unit"]), f"{label} · {detail}".strip(" ·")
    return format_number(k["value"], k["format"], k["unit"]), detail


# 1. Sélection du dataset
CLEANED_DIR = "data/cleaned_dataset/"
os.makedirs(CLEANED_DIR, exist_ok=True)
files = [f for f in os.listdir(CLEANED_DIR) if f.endswith(".csv")]
if not files:
    st.warning(f"⚠️ Aucun dataset nettoyé trouvé dans le dossier `{CLEANED_DIR}`.")
    st.stop()

st.markdown("### 🗄 Sélectionnez le dataset à analyser :")
selected_filename = st.selectbox("Dataset actif", files, label_visibility="collapsed")
latest_file = os.path.join(CLEANED_DIR, selected_filename)
dataset_name = selected_filename.replace(".csv", "").replace("_", " ").title()


# 2. L'agent fait TOUT le raisonnement (mis en cache par fichier + date de modification)
@st.cache_data(show_spinner=False)
def load_dashboard(file_path: str, mtime: float, language: str, currency):
    return BIAnalystAgent().build_dashboard(read_csv_safe(file_path), language=language, currency=currency)


if st.button("🔄 Relancer l'agent (nouvelle analyse)"):
    load_dashboard.clear()
    st.rerun()

with st.spinner(f"🤖 L'agent BI analyse `{selected_filename}` et conçoit le dashboard..."):
    try:
        dash = load_dashboard(latest_file, os.path.getmtime(latest_file), LANGUAGE, CURRENCY)
    except Exception as e:
        st.error(f"Erreur lors de l'exécution de l'agent : {e}")
        st.stop()

cl = dash["cleaning"]

# 3. En-tête
page_header("Business Intelligence Analysis", "Turn your data into actionable insights.",
            btn("⭳ Export report") + btn("✨ Create workflow", True), f"{dataset_name} / <b>Analysis</b>")

html(f'''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center;margin-bottom:1rem">🗄
  <small style="color:#4338ca"><b>ACTIVE DATASET</b></small> <b>{escape(dataset_name)}</b> ·
  {cl["rows_after"]:,} / {cl["rows_before"]:,} rows analysed
  <span style="margin-left:auto">{badge("● Results ready", "blue")}</span></div>''')

if dash.get("summary"):
    st.info(dash["summary"])

# Transparence : ce que l'agent a compris et décidé
with st.expander("🧠 Comment l'agent a compris vos données"):
    st.markdown(f"**Contexte métier :** {dash['business_context']}")
    if dash["data_quality_findings"]:
        st.markdown("**Problèmes de qualité détectés :**")
        for f in dash["data_quality_findings"]:
            st.markdown(f"- {f}")
    if cl["filters"]:
        st.markdown(f"**Nettoyage appliqué** ({cl['rows_before'] - cl['rows_after']:,} lignes exclues) : {cl['reasoning']}")
        st.json(cl["filters"])
    if dash["derived_columns"]:
        st.markdown("**Colonnes calculées par l'agent :**")
        for d in dash["derived_columns"]:
            st.markdown(f"- `{d.get('name')}` = {d.get('operation')}({', '.join(d.get('columns', []))}) — {d.get('reasoning', '')}")
    if dash["repair_attempts"]:
        st.caption(f"Le plan a été auto-corrigé {dash['repair_attempts']} fois après des erreurs d'exécution.")

if dash["errors"]:
    with st.expander(f"⚠️ {len(dash['errors'])} élément(s) du plan n'ont pas pu être produits"):
        for e in dash["errors"]:
            st.markdown(f"- {e}")

# 4. KPIs (nombre décidé par l'agent)
kpis = dash["kpis"]
per_row = -(-len(kpis) // -(-len(kpis) // 4)) if kpis else 1      # répartition équilibrée (5 -> 3+2, 6 -> 3+3)
for i in range(0, len(kpis), per_row):
    row = kpis[i:i + per_row]
    for col, k in zip(st.columns(len(row)), row):
        with col:
            value_txt, detail_txt = kpi_texts(k)
            html(kpi(k["title"], value_txt, detail_txt, k["icon"], "blue", "blue"))


# 5. Rendu générique d'un graphique, selon le type choisi par l'agent
def render_chart(c):
    data, t = c["data"], c["type"]

    if t == "table":
        st.dataframe(data.rename(columns={"x": c["x_label"], "value": c["y_label"]}),
                     use_container_width=True, hide_index=True)
        return

    if t == "donut":
        total = data["value"].sum()
        pct = round(data["value"].iloc[0] / total * 100) if total else 0
        rows = "".join(
            f'<p style="margin:.2rem 0">● {escape(str(r.x))} <b style="float:right">{fmt(r.value)} '
            f'({r.value / total * 100:.1f}%)</b></p>' for r in data.itertuples())
        html(f'<div style="display:flex;gap:2rem;align-items:center">{donut(pct, "#4f46e5", size=130)}'
             f'<div style="flex:1">{rows}</div></div>')
        return

    if t == "scatter":
        tip = [alt.Tooltip("x:Q", format=",.2f"), alt.Tooltip("y:Q", format=",.2f")]
        if "label" in data.columns:
            tip.insert(0, alt.Tooltip("label:N"))
        ch = (alt.Chart(data).mark_circle(size=60, opacity=0.6)
              .encode(x=alt.X("x:Q", title=c["x_label"]), y=alt.Y("y:Q", title=c["y_label"]), tooltip=tip)
              .interactive().properties(height=300))
        st.altair_chart(ch, use_container_width=True)
        return

    # bar / histogram / line / area
    tooltip = [alt.Tooltip("x", title=c["x_label"]), alt.Tooltip("value:Q", format=",.2f", title=c["y_label"])]
    color = {}
    if c["has_series"]:
        color = {"color": alt.Color("series:N", title=c.get("series_label"))}
        tooltip.insert(1, alt.Tooltip("series:N"))

    horizontal = (t == "bar" and not c["is_time"]
                  and (data["x"].nunique() > 6 or data["x"].astype(str).str.len().max() > 14))
    if horizontal:
        enc = {"y": alt.Y("x:N", sort=None, title=None), "x": alt.X("value:Q", title=c["y_label"])}
    elif c["is_time"]:
        enc = {"x": alt.X("x:T", title=c["x_label"]), "y": alt.Y("value:Q", title=c["y_label"])}
    else:
        enc = {"x": alt.X("x:N", sort=None, title=c["x_label"], axis=alt.Axis(labelAngle=-30)),
               "y": alt.Y("value:Q", title=c["y_label"])}

    base = alt.Chart(data)
    mark = {"line": base.mark_line(point=True), "area": base.mark_area(opacity=0.6)}.get(t, base.mark_bar())
    st.altair_chart(mark.encode(**enc, **color, tooltip=tooltip).properties(height=300),
                    use_container_width=True)


charts = dash["charts"]
for i in range(0, len(charts), 2):
    row = charts[i:i + 2]
    for col, c in zip(st.columns(len(row)), row):
        with col:
            with st.container(border=True):
                st.markdown(f"#### {c['title']}")
                if c["subtitle"]:
                    st.caption(c["subtitle"])
                render_chart(c)
                if c["note"]:
                    st.caption(c["note"])
                if c["reasoning"]:
                    with st.expander("🧠 Pourquoi ce graphique ?"):
                        st.write(c["reasoning"])


# 6. Insights (rédigés à partir des résultats réellement calculés)
def insight_component(tag, title, text, conf):
    conf = int(conf) if str(conf).isdigit() else 90
    return f'''<div class="bf-card"><span class="bf-badge blue" style="float:right">● {conf}% confidence</span>
      <small style="color:#4338ca"><b>{escape(str(tag))}</b></small><h3 style="font-size:1.1rem;margin:.5rem 0">{escape(str(title))}</h3>
      <p style="color:#64748b;font-size:.85rem">{escape(str(text))}</p>Confidence <b style="float:right">{conf}%</b>{bar(conf, "#075985")}
      </div>'''


insights = dash["insights"]
if insights:
    html(f'<div style="display:flex;justify-content:space-between"><h2>AI Insights</h2>'
         f'{badge(f"{len(insights)} insights grounded in computed results")}</div>')
    for i in range(0, len(insights), 3):
        row = insights[i:i + 3]
        for col, ins in zip(st.columns(len(row)), row):
            with col:
                html(insight_component(ins.get("tag", "INSIGHT"), ins.get("title", ""),
                                       ins.get("text", ""), ins.get("confidence", 90)))