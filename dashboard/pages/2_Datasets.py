"""
2_Datasets.py — BIFlow Dashboard
================================
Gestionnaire dynamique des assets de données, avec détection en temps réel,
importation directe de CSV, filtrage et lancement de workflows.
"""

from pathlib import Path
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from components import setup, page_header, btn, html, card, table, badge, bar
from chat_widget import render_chat
from dataset_utils import get_workspace_summary, get_workspace_datasets

render_chat("Datasets")
setup("Datasets")

# ── Actions d'en-tête ────────────────────────────────────────────────────────
c_title, c_act1, c_act2 = st.columns([6, 1.2, 1.8], vertical_alignment="center")
with c_title:
    page_header(
        "Datasets",
        "Inspectez, gérez et orchestrez vos données brutes et nettoyées en temps réel.",
        "",
        "Workspace › <b>Datasets</b>",
    )
with c_act1:
    if st.button("⟳ Refresh", width="stretch", key="ds_refresh_btn"):
        st.cache_data.clear()
        st.rerun()
with c_act2:
    toggle_upload = st.button("☁ + Upload dataset", type="primary", width="stretch", key="ds_upload_btn")

# ── Panneau d'upload interactif ──────────────────────────────────────────────
if toggle_upload or st.session_state.get("ds_show_uploader", False):
    st.session_state["ds_show_uploader"] = True
    with st.container(border=True):
        st.markdown("**☁️ Importer un nouveau jeu de données (CSV)**")
        uploaded = st.file_uploader(
            "Glissez votre fichier CSV ici pour l'ajouter automatiquement au dossier data/raw :",
            type=["csv"],
            key="real_file_uploader",
        )
        c_up1, c_up2 = st.columns([1, 4])
        with c_up1:
            if uploaded:
                save_dir = PROJECT_ROOT / "data" / "raw"
                save_dir.mkdir(parents=True, exist_ok=True)
                dest = save_dir / uploaded.name
                with open(dest, "wb") as f:
                    f.write(uploaded.getbuffer())
                st.success(f"✅ '{uploaded.name}' importé avec succès !")
                st.cache_data.clear()
                st.session_state["ds_show_uploader"] = False
                st.rerun()
        with c_up2:
            if st.button("Fermer l'import", key="close_uploader_btn"):
                st.session_state["ds_show_uploader"] = False
                st.rerun()

# ── Récupération des données réelles ─────────────────────────────────────────
summary = get_workspace_summary()
all_datasets = summary["datasets"]

# ── Barre de recherche et filtres ────────────────────────────────────────────
s_col1, s_col2 = st.columns([2, 3], vertical_alignment="center")
with s_col1:
    search_q = st.text_input(
        "Recherche",
        placeholder="🔍 Rechercher par nom (ex: telco, customers, sales...)",
        label_visibility="collapsed",
        key="ds_search_input",
    )
with s_col2:
    raw_n   = summary["raw_datasets"]
    clean_n = summary["clean_datasets"]
    total_n = summary["total_datasets"]
    prof_n  = sum(1 for d in all_datasets if d["quality_score"] is not None)

    filter_choice = st.radio(
        "Filtres",
        [f"Tous ({total_n})", f"✨ Nettoyés ({clean_n})", f"📂 Bruts ({raw_n})", f"✅ Profilés ({prof_n})"],
        horizontal=True,
        label_visibility="collapsed",
        key="ds_filter_radio",
    )

# ── Filtrage dynamique ───────────────────────────────────────────────────────
filtered_ds = all_datasets
if search_q.strip():
    q = search_q.lower()
    filtered_ds = [d for d in filtered_ds if q in d["name"].lower()]

if "Nettoyés" in filter_choice:
    filtered_ds = [d for d in filtered_ds if d["is_cleaned"]]
elif "Bruts" in filter_choice:
    filtered_ds = [d for d in filtered_ds if not d["is_cleaned"]]
elif "Profilés" in filter_choice:
    filtered_ds = [d for d in filtered_ds if d["quality_score"] is not None]

# ── Construction du tableau réel ─────────────────────────────────────────────
def fmt_tag(is_clean: bool):
    return (
        '<span class="mono" style="color:#0369a1;background:#e0f2fe;padding:.15rem .45rem;border-radius:6px;font-weight:700">CLEAN</span>'
        if is_clean
        else '<span class="mono" style="color:#166534;background:#dcfce7;padding:.15rem .45rem;border-radius:6px;font-weight:700">CSV</span>'
    )

trs = []
for d in filtered_ds:
    score = d["quality_score"]
    if score is not None:
        color = "#10b981" if score >= 90 else "#f59e0b" if score >= 75 else "#ef4444"
        score_html = f"<b>{score}%</b> {bar(score, color)}"
    else:
        score_html = "<span style='color:#94a3b8;'><i>— Non profilé</i></span>"

    status_badge = (
        badge("● Nettoyé", "green") if d["is_cleaned"]
        else badge("● À vérifier", "amber") if (score is not None and score < 88)
        else badge("● Prêt", "blue") if score is not None
        else badge("● Brut", "indigo")
    )

    clean_icon = "✨ " if d["is_cleaned"] else ""
    name_html = f"<b>{clean_icon}{d['name']}</b><br><small style='color:#64748b;'>{d['size_mb']} MB · {d['stem']}</small>"

    trs.append([
        name_html,
        fmt_tag(d["is_cleaned"]),
        f"{d['rows']:,}",
        str(d["cols"]),
        score_html,
        d["mtime_str"],
        status_badge,
    ])

html(card(
    table(["DATASET", "FORMAT", "ROWS", "COLUMNS", "QUALITY SCORE", "DERNIÈRE MODIF", "STATUS"], trs, max_height=480)
    + f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:1rem;color:#475569;font-size:0.85rem;">'
    f'<span>Affichage de <b>{len(filtered_ds)}</b> sur <b>{total_n}</b> datasets détectés</span>'
    f'<span style="color:#4f46e5;font-weight:600;font-size:0.8rem">↕ Défilement vertical actif ({len(filtered_ds)} éléments)</span></div>'
))

html("<br>")

# ── Panneau d'action rapide sur le dataset sélectionné ───────────────────────
if filtered_ds:
    st.markdown('<div class="bf-card" style="padding:1rem 1.4rem;border-radius:14px;background:#f8faff;border:1px solid #c7d2fe;">'
                '<b style="color:#1e1b4b;font-size:0.95rem;">⚡ Actions Rapides sur un Dataset</b><br>'
                '<span style="color:#64748b;font-size:0.82rem;">Sélectionnez un dataset pour prévisualiser ses données ou lancer un workflow d\'analyse multi-agents.</span></div>',
                unsafe_allow_html=True)
    st.markdown("")

    col_sel, col_w_btn, col_p_btn = st.columns([3, 1.5, 1.5], vertical_alignment="bottom")
    with col_sel:
        chosen_ds_name = st.selectbox(
            "Dataset cible",
            options=[d["name"] for d in filtered_ds],
            label_visibility="collapsed",
            key="quick_ds_select",
        )
    
    chosen_ds = next((d for d in filtered_ds if d["name"] == chosen_ds_name), filtered_ds[0])

    with col_w_btn:
        if st.button("🚀 Lancer Workflow", type="primary", width="stretch", key="quick_wf_btn"):
            st.session_state["current_dataset_path"] = chosen_ds["path"]
            st.session_state["wf_file"] = chosen_ds["path"]
            st.session_state["sidebar_mode"] = "nav"
            st.switch_page("pages/3_Workflows.py")

    with col_p_btn:
        if st.button("🔍 Profiler (Agent 1)", width="stretch", key="quick_prof_btn"):
            st.session_state["current_dataset_path"] = chosen_ds["path"]
            st.session_state["wf_file"] = chosen_ds["path"]
            st.session_state["sidebar_mode"] = "agent1"
            st.switch_page("pages/A1_Profiling.py")

    with st.expander(f"👁️ Aperçu direct des données ({chosen_ds_name})", expanded=False):
        try:
            df_preview = pd.read_csv(chosen_ds["path"], nrows=10)
            st.dataframe(df_preview, width="stretch")
        except Exception as e:
            st.warning(f"Impossible de prévisualiser ce fichier : {e}")

html("<br>")

# ── Stockage & Sources Connectées Réels ───────────────────────────────────────
total_mb = summary["total_mb"]
used_pct = summary["used_pct"]
remaining_gb = round((20 * 1024 - total_mb) / 1024, 2)

storage_card = f'''<div class="ch"><div><h3>Stockage Espace BIFlow</h3><div class="subt">Données réelles indexées dans data/raw et data/cleaned</div></div>{badge("Actif", "green")}</div>
  <div style="font-size:2.2rem;font-weight:700">{total_mb} MB <small style="font-size:1rem;color:#64748b">/ 20 GB Quota</small>
  <span style="float:right;font-size:.9rem;color:#4338ca">{used_pct}% utilisé</span></div>{bar(int(max(used_pct, 2)), "#4f46e5")}
  <p style="color:#64748b;font-size:.85rem;margin-top:.4rem">{remaining_gb} GB restants disponibles <b style="float:right;color:#0f172a">{total_n} fichiers CSV</b></p>'''

sources_card = f'''<div class="ch"><div><h3>Dépôts et Sources Connectés</h3><div class="subt">Dossiers et répertoires de persistance actifs</div></div>{badge("● Synchronisé", "blue")}</div>
  <div style="font-size:2.2rem;font-weight:700">2 <small style="font-size:1rem;color:#64748b">sources locales</small>
  <span style="float:right;font-size:.9rem;color:#10b981">100% opérationnel</span></div>{bar(100, "#10b981")}
  <div class="bf-box" style="margin-top:.8rem">📂 <code>data/raw/</code> ({raw_n} bruts) &nbsp;·&nbsp; ✨ <code>data/cleaned/</code> ({clean_n} nettoyés) &nbsp;·&nbsp; 📊 <code>data/reports/</code> ({summary['reports_count']} rapports)</div>'''

html(f'<div class="bf-grid g2">{card(storage_card)}{card(sources_card)}</div>')