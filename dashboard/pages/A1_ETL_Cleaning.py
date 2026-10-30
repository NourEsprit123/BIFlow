import sys
import json
from pathlib import Path
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from components import setup, page_header, html, badge, card, table
from agents.data_engineering_agent import DataEngineeringAgent

if "sidebar_mode" not in st.session_state or st.session_state.sidebar_mode == "nav":
    st.session_state.sidebar_mode = "agent1"

setup("ETL & Cleaning", hub="Agent 1 · Data Engineering")

# ── Récupération des résultats Agent 1 ─────────────────────────────────────────
results = st.session_state.get("pipeline_results", {}).get("agent1", {})
if not results:
    results = (st.session_state.get("wf_graph_state") or {}).get("reports", {}).get("data_engineer", {})

report   = results.get("profiling_report", {})
strategy = results.get("cleaning_strategy", {})

page_header(
    "ETL & Cleaning",
    "Passez en revue les recommandations de l'Agent 1 et exécutez le nettoyage automatisé.",
    badge("Agent 1", "blue"),
    "Agent 1 · Data Engineering > <b>ETL & Cleaning</b>",
)

# ── Si aucun rapport n'est présent, proposer de lancer l'audit directement ──────
raw_dir = PROJECT_ROOT / "data" / "raw"
csv_files = sorted(raw_dir.glob("*.csv")) if raw_dir.exists() else []

if not report:
    st.info("💡 Aucun rapport d'audit actif en mémoire. Vous pouvez lancer l'Agent 1 directement sur un jeu de données :")
    if csv_files:
        default_idx = 0
        cur_p = st.session_state.get("current_dataset_path") or st.session_state.get("wf_file")
        if cur_p:
            cur_name = Path(cur_p).name
            for i, f in enumerate(csv_files):
                if f.name == cur_name:
                    default_idx = i
                    break
        c_sel, c_btn = st.columns([3, 1])
        with c_sel:
            chosen_csv = st.selectbox("Sélectionner un jeu de données :", [f.name for f in csv_files], index=default_idx, key="clean_page_ds_sel")
        with c_btn:
            st.write("")
            run_audit_now = st.button("🚀 Auditer le dataset", type="primary", use_container_width=True, key="btn_clean_audit_now")
        if run_audit_now and chosen_csv:
            with st.spinner("🔍 Analyse et audit par l'Agent 1..."):
                agent = DataEngineeringAgent()
                audit_res = agent.run_audit(str(raw_dir / chosen_csv))
                if "pipeline_results" not in st.session_state:
                    st.session_state["pipeline_results"] = {}
                st.session_state["pipeline_results"]["agent1"] = audit_res
                st.session_state["current_dataset_path"] = str(raw_dir / chosen_csv)
            st.rerun()
    else:
        st.warning("Aucun fichier CSV trouvé dans `data/raw/`.")
    st.stop()

# ── Déterminer le fichier source ──────────────────────────────────────────────
file_path = (
    results.get("file_path")
    or st.session_state.get("current_dataset_path")
    or st.session_state.get("wf_file")
)
if not file_path and csv_files:
    file_path = str(csv_files[0])

# ── SECTION 1 : BOUTONS D'ACTION DE NETTOYAGE ─────────────────────────────────
st.markdown("### 🧹 Actions de Nettoyage Automatisé (Agent 1)")

with st.container(border=True):
    col_info, col_act1, col_act2 = st.columns([2, 1, 1])
    with col_info:
        st.markdown(f"**Jeu de données cible :** `{Path(file_path).name if file_path else 'Inconnu'}`")
        existing_cleaned = results.get("cleaned_path")
        if existing_cleaned and Path(existing_cleaned).exists():
            st.caption(f"✅ **Dataset nettoyé actif :** `{Path(existing_cleaned).name}`")
        else:
            st.caption("Prêt pour l'application des règles d'imputation, typage et normalisation.")

    with col_act1:
        st.write("")
        btn_preview = st.button("👀 Prévisualiser", use_container_width=True, help="Simule les transformations sans écrire de fichier.")
    with col_act2:
        st.write("")
        btn_clean = st.button("✨ Nettoyer le dataset", type="primary", use_container_width=True, help="Exécute le pipeline ETL et sauvegarde les fichiers nettoyés.")

    # ── Simulation (Preview) ──────────────────────────────────────────────────
    if btn_preview and file_path and Path(file_path).exists():
        with st.spinner("🔬 Simulation des transformations en cours…"):
            agent = DataEngineeringAgent()
            prev_res = agent.execute_cleaning(file_path, strategy=strategy, preview_mode=True)
            st.info(
                f"**Simulation réussie :** {prev_res.get('rows_processed', 0)} lignes et "
                f"{prev_res.get('columns_processed', 0)} colonnes traitées. "
                f"Score santé projeté : **{prev_res.get('health_after', {}).get('overall_health_score', 0)}%**"
            )

    # ── Exécution du nettoyage réel ───────────────────────────────────────────
    if btn_clean and file_path and Path(file_path).exists():
        with st.spinner("🧹 Nettoyage ETL en cours (imputations, conversions, normalisation)…"):
            agent = DataEngineeringAgent()
            clean_res = agent.execute_cleaning(file_path, strategy=strategy, preview_mode=False)
            
            cleaned_csv = clean_res.get("cleaned_file_path", "")
            if cleaned_csv and Path(cleaned_csv).exists():
                st.session_state["current_dataset_path"] = str(cleaned_csv)
                st.session_state["cleaned_dataset_path"] = str(cleaned_csv)
                results["cleaned_path"] = str(cleaned_csv)
                if "clean_result" not in results:
                    results["clean_result"] = {}
                results["clean_result"]["cleaned_file_path"] = str(cleaned_csv)
                if "pipeline_results" not in st.session_state:
                    st.session_state["pipeline_results"] = {}
                st.session_state["pipeline_results"]["agent1"] = results

                st.success(f"🎉 **Dataset nettoyé avec succès !** Fichier généré : `{Path(cleaned_csv).name}`")
                
                # Métriques avant / après
                h_after = clean_res.get("health_after", {})
                h_before = results.get("health", {})
                score_before = h_before.get("overall_health_score", h_before.get("overall_score", "—"))
                score_after = h_after.get("overall_health_score", 100)
                
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("🎯 Score santé avant", f"{score_before}%")
                with m2:
                    st.metric("🚀 Score santé après", f"{score_after}%", delta=f"+{round(float(score_after) - float(score_before), 1)}%" if str(score_before).replace('.','').isdigit() else "")
                with m3:
                    st.metric("📁 Format Parquet", "✅ Sauvegardé")

                # Bouton de transmission vers l'Agent 2
                st.markdown("---")
                cta1, cta2 = st.columns([2, 1])
                with cta1:
                    st.markdown("Le dataset nettoyé est désormais injecté dans la session de l'**Agent 2 (BI Analyst)**.")
                with cta2:
                    st.page_link("pages/5_BI_Analysis.py", label="👉 Analyser avec l'Agent 2 (BI)", icon="📊")

    # ── Aperçu des données nettoyées si déjà disponibles (Style Carte BIFlow) ──
    active_clean_path = results.get("cleaned_path") or st.session_state.get("current_dataset_path")
    if active_clean_path and Path(active_clean_path).exists() and "_cleaned" in str(active_clean_path):
        try:
            df_prev = pd.read_csv(active_clean_path)
            prev_cols = [f"<span class='mono'><b>{c}</b></span>" for c in df_prev.columns]
            prev_rows = []
            for _, r in df_prev.head(5).iterrows():
                prev_rows.append([f"<span class='mono' style='font-size:.82rem'>{val}</span>" for val in r.values])
            
            clean_tbl_html = table(prev_cols, prev_rows)
            html(card(
                clean_tbl_html,
                "👀 Aperçu du dataset nettoyé",
                f"5 premières lignes · {len(df_prev):,} lignes totales · {len(df_prev.columns)} colonnes",
                badge("Nettoyé", "green")
            ))
            with open(active_clean_path, "rb") as f_dl:
                st.download_button(
                    "⬇️ Télécharger le CSV nettoyé",
                    f_dl,
                    file_name=Path(active_clean_path).name,
                    mime="text/csv",
                    key="btn_dl_cleaned_csv",
                )
        except Exception as e:
            st.caption(f"Aperçu indisponible : {e}")

st.markdown("---")

# ── SECTION 2 : RECOMMANDATIONS DÉTAILLÉES ────────────────────────────────────
etl_hints = report.get("etl_hints", {})
rows = []
for column, dtype in etl_hints.get("type_casting_targets", {}).items():
    rows.append(["Type conversion", column, f"Cast to {dtype}"])
for column, plan in strategy.get("imputation_plan", report.get("imputation_plan", {})).items():
    rows.append(["Missing values", column, f"Suggested strategy: {plan.get('strategy', 'review')}"])
for column, mapping in etl_hints.get("synonym_mappings", {}).items():
    rows.append(["Category normalization", column, f"{len(mapping)} suggested mappings"])
for column in strategy.get("numeric_waterfall_columns", []):
    rows.append(["Numeric parsing", column, "Review dirty numeric values"])
for column in report.get("outlier_columns", []):
    rows.append(["Outliers", column, "Review detected outliers"])
for column in etl_hints.get("drop_candidates", []):
    rows.append(["Schema", column, "Review before dropping"])

if rows:
    html(card(table(["AREA", "COLUMN", "RECOMMENDATION"], rows, max_height=380),
              "Cleaning & ETL recommendations",
              "Suggestions from Agent 1; review before applying transformations."))
else:
    html(card("No cleaning or ETL recommendations were returned.", "Recommendations"))

summary = report.get("agent_summary", strategy.get("recommendation_summary", ""))
if summary:
    html(card(summary, "Agent 1 summary"))

if etl_hints.get("join_key_candidates"):
    html(card(", ".join(etl_hints["join_key_candidates"]), "Join key candidates"))
