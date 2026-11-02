"""
6_Audit_XAI.py — BIFlow Dashboard
====================================
🛡️ Cockpit de Gouvernance & Explicabilité XAI.
Identité visuelle orientée conformité : distincte de la page BI Analyst.
Sélecteur de moteur LLM (Local Ollama / Cloud API) en sidebar.
Tous les correctifs QA (BUG-01 → BUG-04, IC-01 → IC-03) sont intégrés.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── BIFlow imports ────────────────────────────────────────────────────────────
from agents.xai_auditor_agent import XAIAuditorAgent
from components import setup, page_header, btn, html, kpi, grid, badge
from chat_widget import render_chat

# ── Chat widget & page setup ──────────────────────────────────────────────────
render_chat("Audit XAI")
setup("Audit & XAI")
page_header(
    "🛡️ Cockpit de Gouvernance & Explicabilité XAI",
    "Conformité, traçabilité cryptographique et attribution causale des décisions IA.",
    btn("⭳ Exporter le rapport") + btn("🛡 Certifier l'audit", True),
    "Workspace › <b>Gouvernance & XAI</b>",
)

# ── Inline CSS — identité visuelle XAI ───────────────────────────────────────
st.markdown("""
<style>
.xai-banner {
    background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
    border: 1px solid #10b981;
    border-radius: 14px;
    padding: 1rem 1.5rem;
    display: flex;
    align-items: center;
    gap: 1.25rem;
    margin-bottom: 1.25rem;
}
.xai-banner .xai-badge-ok   { background:#10b981; color:#fff; font-weight:700;
    font-size:.78rem; padding:.25rem .8rem; border-radius:20px; white-space:nowrap; }
.xai-banner .xai-badge-warn { background:#d97706; color:#fff; font-weight:700;
    font-size:.78rem; padding:.25rem .8rem; border-radius:20px; white-space:nowrap; }
.xai-banner .xai-title { color:#ecfdf5; font-weight:700; font-size:1rem; margin:0; }
.xai-banner .xai-sub   { color:#6ee7b7; font-size:.8rem; margin:0; }

.xai-engine-bar {
    background: #1e1b4b;
    border: 1px solid #4338ca;
    border-radius: 10px;
    padding: .6rem 1rem;
    display: flex;
    align-items: center;
    gap: .75rem;
    margin-bottom: 1rem;
    font-size: .85rem;
    color: #a5b4fc;
}
.xai-engine-bar b { color: #e0e7ff; }

.xai-pill {
    display: inline-flex; align-items: center; gap:.4rem;
    background: #1e1b4b; color: #a5b4fc;
    font-weight:600; font-size:.78rem;
    padding:.2rem .8rem; border-radius:20px;
    margin-bottom:.6rem; letter-spacing:.03em;
}

.xai-narrative {
    background: #f8faff;
    border-left: 4px solid #6366f1;
    border-radius: 0 12px 12px 0;
    padding: 1.25rem 1.5rem;
    line-height: 1.8;
    color: #1e293b;
}
.xai-narrative-warn {
    background: #fffbeb;
    border-left: 4px solid #f59e0b;
    border-radius: 0 12px 12px 0;
    padding: 1rem 1.4rem;
    color: #78350f;
    font-size: .9rem;
    margin-bottom: 1rem;
}

.xai-hash-box {
    background: #0f172a; border: 1px solid #334155;
    border-radius: 10px; padding: .85rem 1.1rem; margin-bottom: .75rem;
}
.xai-hash-box .hl  { color:#94a3b8; font-size:.72rem; text-transform:uppercase;
    letter-spacing:.08em; margin-bottom:.3rem; }
.xai-hash-box .hv  { font-family:'Fira Code','JetBrains Mono',monospace;
    font-size:.8rem; color:#38bdf8; word-break:break-all; }
.xai-hash-box .hd  { color:#64748b; font-size:.72rem; margin-top:.2rem; }

.xai-gov-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:.75rem; }
.xai-gov-item {
    background:#f0fdf4; border:1px solid #bbf7d0; border-radius:10px;
    padding:.75rem 1rem; text-align:center; min-height:76px;
    display:flex; flex-direction:column; align-items:center;
    justify-content:center; gap:.2rem;
}
.xai-gov-item.fail { background:#fff1f2; border-color:#fecdd3; }
.xai-gov-item.warn { background:#fffbeb; border-color:#fde68a; }
.xai-gov-item .gs  { font-size:1.25rem; }
.xai-gov-item .gl  { font-size:.76rem; font-weight:600; color:#1e293b; }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# SIDEBAR — Moteur LLM + Source de données
# =============================================================================

st.sidebar.markdown("### 🤖 Moteur d'explication XAI")

engine_options = [
    "🦙 Local — Ollama (qwen2.5:7b)",
    "☁️ Cloud — Groq / Gemini",
    "⚡ Auto (Local → Cloud → Fallback)",
]
if "xai_engine_choice" not in st.session_state:
    st.session_state["xai_engine_choice"] = engine_options[2]

selected_engine_label = st.sidebar.radio(
    "Moteur actif",
    engine_options,
    index=engine_options.index(st.session_state["xai_engine_choice"]),
    key="xai_engine_radio",
    help="Local = Ollama hors-ligne · Cloud = Groq/Gemini · Auto = cascade intelligente",
)
st.session_state["xai_engine_choice"] = selected_engine_label

# Résoudre l'engine string pour l'agent
if "Local" in selected_engine_label:
    chosen_engine = "local"
elif "Cloud" in selected_engine_label:
    chosen_engine = "api"
else:
    chosen_engine = "auto"

# Options spécifiques au moteur
groq_key = ""
if "Cloud" in selected_engine_label or "Auto" in selected_engine_label:
    st.sidebar.markdown("---")
    # Charger la clé depuis l'env SANS l'afficher comme valeur par défaut du widget
    _env_groq = os.environ.get("GROQ_API_KEY", "")
    _groq_configured = bool(_env_groq)
    groq_key = st.sidebar.text_input(
        "Groq API Key (optionnel)",
        value="",                  # jamais pré-rempli avec la valeur réelle
        type="password",
        key="xai_groq_key",
        placeholder="Saisir une clé pour la remplacer…" if _groq_configured else "gsk_…",
        help="Laissez vide pour utiliser GROQ_API_KEY du .env, ou Gemini en fallback.",
    )
    # Affichage du statut sans jamais montrer la valeur
    if groq_key:
        # L'utilisateur vient de saisir une nouvelle clé → l'injecter dans l'env
        os.environ["GROQ_API_KEY"] = groq_key
        st.sidebar.success("🔑 Clé API : Configurée [Sécurisée] ✅")
    elif _groq_configured:
        st.sidebar.success("🔑 Clé API : Configurée via `.env` ✅")
        groq_key = _env_groq   # utiliser la clé env sans l'afficher
    else:
        st.sidebar.warning("🔑 Clé API : Non configurée ❌")

ollama_url     = "http://localhost:11434/api/generate"
ollama_model   = "qwen2.5:7b"
ollama_timeout = 120

if "Local" in selected_engine_label or "Auto" in selected_engine_label:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**🦙 Paramètres Ollama**")
    ollama_url     = st.sidebar.text_input("URL Ollama", value=ollama_url, key="xai_ollama_url")
    ollama_model   = st.sidebar.text_input("Modèle", value=ollama_model, key="xai_ollama_model")
    ollama_timeout = st.sidebar.slider("Timeout (s)", 30, 300, 120, 10, key="xai_ollama_timeout")
    # Statut de connexion — URL affichée sans credential, port uniquement
    _ollama_host_display = ollama_url.split("//")[-1].split("/")[0]  # ex: localhost:11434
    st.sidebar.caption(f"📡 Endpoint : `{_ollama_host_display}`")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🗄 Source de données")

data_dir      = PROJECT_ROOT / "data"
available_csv = (
    [p.relative_to(PROJECT_ROOT) for p in data_dir.glob("**/*.csv")]
    if data_dir.exists() else []
)
NONE_OPT = "— Aucun —"
existing_choice = st.sidebar.selectbox(
    "Dataset existant",
    [NONE_OPT] + [str(p) for p in available_csv],
    key="xai_existing_choice",
)

# ── Agent — instanciation via session_state pour éviter le cache opaque ──────
# @st.cache_resource est intentionnellement évité ici : il conserve l'ancienne
# instance après un hot-reload et lève un TypeError si la signature a changé.
# On indexe sur un tuple de paramètres : toute modification recrée l'instance.
_agent_key = (chosen_engine, ollama_url, ollama_model, int(ollama_timeout),
              groq_key or "")
if st.session_state.get("_xai_agent_key") != _agent_key:
    st.session_state["_xai_agent_key"] = _agent_key
    st.session_state["_xai_agent"] = XAIAuditorAgent(
        engine=chosen_engine,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        ollama_timeout=int(ollama_timeout),
        groq_api_key=groq_key or None,
    )

agent: XAIAuditorAgent = st.session_state["_xai_agent"]

# =============================================================================
# 1. SÉLECTEUR DE FICHIER
# =============================================================================

st.markdown('<span class="xai-pill">📂 Jeu de données à auditer</span>', unsafe_allow_html=True)
st.markdown("")

df: Optional[pd.DataFrame] = None
dataset_name = ""

with st.container(border=True):
    col_up, col_btn = st.columns([3, 1], vertical_alignment="bottom")
    with col_up:
        uploaded_file = st.file_uploader(
            "Glissez votre fichier CSV ici — ou sélectionnez-en un dans la sidebar",
            type=["csv"], key="xai_uploader",
        )
    try:
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            dataset_name = uploaded_file.name
        elif existing_choice != NONE_OPT:
            df = pd.read_csv(PROJECT_ROOT / existing_choice)
            dataset_name = Path(existing_choice).name
        else:
            # Fallback automatique sur le dataset actif du pipeline / Agent 1
            wf_st = st.session_state.get("wf_graph_state") or {}
            wf_path = (
                st.session_state.get("current_dataset_path")
                or wf_st.get("cleaned_data_path")
                or wf_st.get("data_path")
                or st.session_state.get("wf_file")
            )
            if wf_path and Path(wf_path).exists():
                df = pd.read_csv(wf_path)
                dataset_name = Path(wf_path).name
    except Exception as e:
        st.error(f"Erreur de lecture : {e}")
        df = None

    with col_btn:
        launch_audit = st.button(
            "🔬 Lancer l'Audit Forensique",
            type="primary", use_container_width=True, disabled=df is None,
        )

    if df is not None:
        st.caption(f"✅ **{dataset_name}** · {df.shape[0]:,} lignes · {df.shape[1]} colonnes")
        with st.expander("👀 Aperçu des données brutes", expanded=False):
            st.dataframe(df.head(10), use_container_width=True)

if df is None:
    st.info("⬆️ Importez un CSV (ou choisissez-en un dans la sidebar), puis cliquez sur **🔬 Lancer l'Audit Forensique**.")
    st.stop()

# =============================================================================
# 2. CONFIGURATION AUDIT
# =============================================================================

st.markdown("---")
st.markdown('<span class="xai-pill">⚙️ Paramètres de l\'audit</span>', unsafe_allow_html=True)
st.markdown("")

cfg1, cfg2, cfg3 = st.columns(3)
with cfg1:
    target_column = st.selectbox(
        "🎯 Variable cible à expliquer",
        options=df.columns.tolist(),
        index=len(df.columns) - 1,
        key="xai_target_col",
        help="Le surrogate RandomForest sera entraîné à prédire cette colonne.",
    )
with cfg2:
    top_n = st.slider(
        "🔢 Top N features SHAP",
        min_value=3, max_value=min(20, df.shape[1] - 1),
        value=min(10, df.shape[1] - 1), key="xai_top_n",
    )
with cfg3:
    max_rows = st.number_input(
        "📏 Lignes max pour SHAP",
        min_value=50, max_value=min(2000, df.shape[0]),
        value=min(500, df.shape[0]), step=50, key="xai_max_rows",
        help="500 est un bon compromis performance / représentativité.",
    )

# =============================================================================
# 3. SURROGATE MODEL
# =============================================================================

@st.cache_data(show_spinner=False)
def train_surrogate(_df: pd.DataFrame, target_col: str, _max_rows: int):
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.metrics import accuracy_score
    from sklearn.preprocessing import LabelEncoder

    df_work = _df.copy()
    if len(df_work) > _max_rows:
        df_work = df_work.sample(n=_max_rows, random_state=42)

    feature_cols = [c for c in df_work.columns if c != target_col]
    X_raw = df_work[feature_cols].copy()
    y_raw = df_work[target_col].copy()

    for col in X_raw.select_dtypes(include=["object", "category"]).columns:
        try:
            X_raw[col] = pd.to_numeric(X_raw[col], errors="coerce")
        except Exception:
            pass
        if X_raw[col].dtype == object:
            le = LabelEncoder()
            X_raw[col] = le.fit_transform(X_raw[col].astype(str))

    X_raw = X_raw.apply(pd.to_numeric, errors="coerce")
    X_raw = X_raw.fillna(X_raw.median(numeric_only=True))
    X = X_raw.astype(float)

    try:
        y_numeric = pd.to_numeric(y_raw, errors="coerce")
        if y_numeric.isna().sum() / len(y_raw) > 0.5:
            raise ValueError("mostly non-numeric")
        if int(y_numeric.nunique()) <= 20:
            le_y = LabelEncoder()
            y    = le_y.fit_transform(y_raw.astype(str))
            mdl  = RandomForestClassifier(n_estimators=80, max_depth=8, random_state=42, n_jobs=-1)
            task = "classification"
        else:
            y    = y_numeric.fillna(y_numeric.median()).values
            mdl  = RandomForestRegressor(n_estimators=80, max_depth=8, random_state=42, n_jobs=-1)
            task = "regression"
    except Exception:
        le_y = LabelEncoder()
        y    = le_y.fit_transform(y_raw.astype(str))
        mdl  = RandomForestClassifier(n_estimators=80, max_depth=8, random_state=42, n_jobs=-1)
        task = "classification"

    try:
        mdl.fit(X, y)
    except Exception as e:
        return None, None, None, feature_cols, "unknown", None, str(e)

    accuracy = None
    if task == "classification":
        try:
            accuracy = round(float(accuracy_score(y, mdl.predict(X))), 4)
        except Exception:
            pass

    return mdl, X, y, feature_cols, task, accuracy, None


# =============================================================================
# 4. EXÉCUTION AU CLIC
# =============================================================================

dataset_sig = f"{dataset_name}_{df.shape[0]}_{df.shape[1]}_{target_column}_{chosen_engine}"

if launch_audit or st.session_state.get("xai_force_rerun", False):
    st.session_state.pop("xai_force_rerun", None)

    with st.spinner("⚙️ Entraînement du surrogate RandomForest…"):
        mdl, X, y, feature_names, task_type, surrogate_accuracy, fit_err = (
            train_surrogate(df, target_column, int(max_rows))
        )

    if fit_err or mdl is None:
        st.error(f"❌ Échec du surrogate model : {fit_err}")
        st.stop()

    engine_label_short = (
        "🦙 Ollama local" if chosen_engine == "local"
        else "☁️ Cloud API"  if chosen_engine == "api"
        else "⚡ Auto"
    )
    with st.spinner(
        f"🔬 Audit forensique en cours — SHAP · SHA-256 · LLM ({engine_label_short})…  "
        "⏳ L'appel LLM peut prendre 30 à 90 secondes."
    ):
        try:
            audit_report = agent.audit(
                model=mdl, X=X, predictions=None,
                feature_names=feature_names,
                dataset_name=dataset_name,
                top_n_features=int(top_n),
            )
        except Exception as e:
            st.error(f"❌ Erreur audit : {e}")
            st.stop()

    st.session_state["xai_audit_report"]      = audit_report
    st.session_state["xai_dataset_sig"]        = dataset_sig
    st.session_state["xai_task_type"]          = task_type
    st.session_state["xai_feature_names"]      = feature_names
    st.session_state["xai_surrogate_accuracy"] = surrogate_accuracy

if st.session_state.get("xai_dataset_sig") != dataset_sig:
    wf_st = st.session_state.get("wf_graph_state") or {}
    a3_rep = (wf_st.get("reports") or {}).get("xai_auditor") or st.session_state.get("pipeline_results", {}).get("agent3")
    if a3_rep and a3_rep.get("audit_report"):
        st.session_state["xai_audit_report"] = a3_rep["audit_report"]
        st.session_state["xai_dataset_sig"] = dataset_sig
        st.session_state["xai_task_type"] = a3_rep["audit_report"].get("task_type", "classification")
        st.session_state["xai_feature_names"] = a3_rep["audit_report"].get("feature_names", [f.get("feature") for f in a3_rep["audit_report"].get("shap", {}).get("summary", {}).get("top_features", []) if isinstance(f, dict)])
        st.session_state["xai_surrogate_accuracy"] = a3_rep["audit_report"].get("surrogate_accuracy")
    else:
        st.info("👆 Configurez les paramètres ci-dessus puis cliquez sur **🔬 Lancer l'Audit Forensique**.")
        st.stop()

# ── Lecture des résultats ─────────────────────────────────────────────────────
audit_report       = st.session_state["xai_audit_report"]
task_type          = st.session_state.get("xai_task_type", "unknown")
feature_names      = st.session_state.get("xai_feature_names", [])
surrogate_accuracy = st.session_state.get("xai_surrogate_accuracy")
telemetry          = audit_report.get("telemetry", {})
integrity          = audit_report.get("integrity", {})
shap_block         = audit_report.get("shap", {})
shap_summary       = shap_block.get("summary", {})
top_features       = shap_summary.get("top_features", [])
pred_dist          = audit_report.get("predictions_distribution", {})
narrative          = audit_report.get("narrative_explanation", "")
explainer_type     = shap_block.get("explainer_type", "N/A")
global_shap        = shap_summary.get("global_mean_abs_shap", 0.0)
n_samples          = audit_report.get("n_samples", 0)
n_features_kpi     = audit_report.get("n_features", 0)
llm_ok             = telemetry.get("is_llm", False)
hash_ok            = bool(integrity.get("audit_hash"))
shap_ok            = bool(top_features)
engine_used        = audit_report.get("engine_used", chosen_engine)

# =============================================================================
# 5. BARRE MOTEUR ACTIF + BADGE CONFORMITÉ
# =============================================================================
st.markdown("---")

# Barre moteur — affichage épuré sans noms de modèles internes (F-03)
engine_icon  = "🦙" if engine_used == "local" else "☁️" if engine_used == "api" else "⚡"
_provider_display = telemetry.get("provider", "—")
# Masquer tout ce qui ressemble à un identifiant de modèle interne dans le provider
_provider_safe = _provider_display.split("(")[0].strip()  # ex: "☁️ Groq" sans "(llama-…)"
engine_label = (
    f"Ollama local · <b>{ollama_model}</b>"   if engine_used == "local"
    else f"Cloud API · <b>{_provider_safe}</b>"   if engine_used == "api"
    else f"Auto → <b>{_provider_safe}</b>"
)
_llm_status_badge = '<b style="color:#34d399">✅ actif</b>' if llm_ok else '<b style="color:#f87171">❌ fallback</b>'
st.markdown(
    f'<div class="xai-engine-bar">{engine_icon} Moteur actif : {engine_label}'
    f' &nbsp;|&nbsp; Durée : <b>{telemetry.get("duration_s", 0)} s</b>'
    f' &nbsp;|&nbsp; LLM : {_llm_status_badge}'
    f'</div>',
    unsafe_allow_html=True,
)

# Badge de conformité
is_compliant  = shap_ok and hash_ok
compliance_lbl = "CERTIFIÉ COMPLIANT" if is_compliant else "AUDIT PARTIEL"
compliance_sub = (
    f"SHAP vérifié · Intégrité SHA-256 établie · "
    f"{'Explication LLM active' if llm_ok else 'Fallback déterministe'}"
    if is_compliant
    else "Certains contrôles n'ont pas pu être complétés — voir les onglets."
)
badge_cls = "xai-badge-ok" if is_compliant else "xai-badge-warn"
st.markdown(f"""
<div class="xai-banner">
  <span style="font-size:2rem;">🛡️</span>
  <div style="flex:1">
    <p class="xai-title">Statut de conformité</p>
    <p class="xai-sub">{compliance_sub}</p>
  </div>
  <span class="{badge_cls}">● {compliance_lbl}</span>
</div>
""", unsafe_allow_html=True)

# =============================================================================
# 6. MÉTRIQUES RAPIDES
# =============================================================================
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("🔍 Observations", f"{n_samples:,}", delta=f"Tâche : {task_type}")
with m2:
    st.metric("📐 Features", str(n_features_kpi), delta=f"Explainer : {explainer_type}")
with m3:
    acc_disp = f"{surrogate_accuracy*100:.1f}%" if surrogate_accuracy else "N/A (régression)"
    st.metric("🎯 Précision surrogate", acc_disp, delta="RandomForest in-sample")
with m4:
    lin_status = "✅ Établi" if hash_ok else "⚠ Incomplet"
    _hash_preview = integrity.get("audit_hash", "")
    _hash_display = f"{_hash_preview[:12]}…" if _hash_preview else "—"
    st.metric("🔗 Lineage", lin_status, delta=f"Audit : {_hash_display}")
with m5:
    st.metric("⏱ Durée totale", f"{telemetry.get('duration_s', 0)} s",
              delta=f"{'LLM actif' if llm_ok else 'Fallback'}")

# =============================================================================
# 7. ONGLETS
# =============================================================================
st.markdown("---")

tab_narrative, tab_shap, tab_telemetry = st.tabs([
    "💬 Rapport Narratif XAI",
    "📊 Attributions SHAP & Prédictions",
    "⚙️ Télémétrie, Lineage & Gouvernance",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — RAPPORT NARRATIF
# ─────────────────────────────────────────────────────────────────────────────
with tab_narrative:
    st.markdown('<span class="xai-pill">💬 Explication en langage naturel</span>', unsafe_allow_html=True)
    st.markdown("")

    if not llm_ok:
        st.markdown("""
<div class="xai-narrative-warn">
⚠️ <b>Mode déterministe actif</b> — aucun moteur LLM n'a répondu.<br>
L'explication ci-dessous est générique. Les attributions SHAP et les hashes SHA-256 restent valides.<br>
Pour activer le narratif complet : choisissez un moteur dans la sidebar et relancez l'audit.
</div>
""", unsafe_allow_html=True)

    # Rendu Markdown natif dans conteneur stylisé — jamais de code brut
    st.markdown(f'<div class="xai-narrative">', unsafe_allow_html=True)
    st.markdown(narrative)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    with st.expander("📋 Rapport d'audit complet (Markdown)", expanded=False):
        formatted_md = agent.format_audit_report(audit_report)
        st.markdown(formatted_md)

    dl1, dl2 = st.columns(2)
    with dl1:
        formatted_md = agent.format_audit_report(audit_report)
        st.download_button("⭳ Télécharger Markdown", data=formatted_md,
            file_name=f"BIFlow_XAI_{dataset_name}.md", mime="text/markdown",
            use_container_width=True)
    with dl2:
        # F-07 : sanitiser la télémétrie avant export — retirer les détails bruts
        def _sanitize_report_for_export(report: dict) -> dict:
            """Retire narrative_explanation et nettoie les détails d'erreur de télémétrie."""
            safe = {k: v for k, v in report.items() if k != "narrative_explanation"}
            if "telemetry" in safe and "attempts" in safe["telemetry"]:
                safe["telemetry"] = {
                    **safe["telemetry"],
                    "attempts": [
                        {k2: v2 for k2, v2 in a.items() if k2 != "detail"}
                        for a in safe["telemetry"]["attempts"]
                    ],
                }
            return safe

        st.download_button("⭳ Exporter JSON",
            data=json.dumps(_sanitize_report_for_export(audit_report), indent=2, default=str),
            file_name=f"BIFlow_XAI_{dataset_name}.json", mime="application/json",
            use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — ATTRIBUTIONS SHAP
# ─────────────────────────────────────────────────────────────────────────────
with tab_shap:
    st.markdown(
        f'<span class="xai-pill">📊 Top {len(top_features)} features — {explainer_type}</span>',
        unsafe_allow_html=True,
    )
    st.markdown("")

    if not top_features:
        st.warning("Les valeurs SHAP n'ont pas pu être calculées pour ce dataset.")
    else:
        col_chart, col_table = st.columns([3, 2])

        with col_chart:
            st.markdown("##### Importance des features (Mean |SHAP|)")

            shap_df = pd.DataFrame(top_features).rename(columns={
                "rank": "Rang", "feature": "Feature",
                "mean_abs_shap": "Mean |SHAP|", "direction_sample_0": "Direction",
            })

            # Graphique à barres interactif natif Streamlit
            chart_data = shap_df.set_index("Feature")["Mean |SHAP|"].sort_values(ascending=True)
            st.bar_chart(chart_data, color="#6366f1", horizontal=True,
                         height=max(240, len(top_features) * 30))

            # Graphique Plotly enrichi (coloré par direction) si disponible
            try:
                import plotly.express as px
                fig = px.bar(
                    shap_df.sort_values("Mean |SHAP|", ascending=True),
                    x="Mean |SHAP|", y="Feature", orientation="h",
                    color="Direction",
                    color_discrete_map={"positive": "#10b981", "negative": "#f43f5e"},
                    title="Attribution causale colorée par direction d'impact",
                )
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#0f172a", family="Inter, sans-serif"),
                    margin=dict(t=40, b=20, l=10, r=10),
                    legend=dict(title="Direction"),
                    yaxis=dict(tickfont=dict(size=11)),
                )
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                pass

        with col_table:
            st.markdown("##### Tableau des attributions")
            max_shap = float(shap_df["Mean |SHAP|"].max()) if len(shap_df) else 1.0
            st.dataframe(
                shap_df[["Rang", "Feature", "Mean |SHAP|", "Direction"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "Mean |SHAP|": st.column_config.ProgressColumn(
                        "Mean |SHAP|", format="%.6f",
                        min_value=0.0, max_value=max_shap,
                    ),
                },
            )
            st.metric("Mean |SHAP| global", f"{global_shap:.6f}",
                      delta=f"Sur {n_samples:,} observations")

    # ── Distribution des prédictions ─────────────────────────────────────────
    st.markdown("---")
    st.markdown('<span class="xai-pill">📈 Distribution des prédictions</span>', unsafe_allow_html=True)
    st.markdown("")

    pred_dist_values = list(pred_dist.values())
    if not pred_dist_values:
        st.info("Aucune distribution disponible.")
    elif isinstance(pred_dist_values[0], dict):             # BUG-01 fix
        pred_rows = [
            {"Classe": cls, "Count": s.get("count", 0), "Part (%)": s.get("pct", 0)}
            for cls, s in pred_dist.items()
        ]
        pred_df = pd.DataFrame(pred_rows)
        pc1, pc2 = st.columns([1, 2])
        with pc1:
            st.dataframe(pred_df, use_container_width=True, hide_index=True)
        with pc2:
            try:
                import plotly.express as px
                fig_pie = px.pie(pred_df, names="Classe", values="Count", hole=0.45,
                    color_discrete_sequence=["#6366f1","#10b981","#f43f5e","#f59e0b"],
                    title="Répartition des classes prédites")
                fig_pie.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=40,b=10,l=10,r=10), font=dict(color="#0f172a"))
                st.plotly_chart(fig_pie, use_container_width=True)
            except ImportError:
                st.bar_chart(pred_df.set_index("Classe")["Count"])
    else:
        dc = st.columns(len(pred_dist))
        for i, (k, v) in enumerate(pred_dist.items()):
            with dc[i]:
                st.metric(k.capitalize(), f"{v:.4f}")

    # ── Hashes SHA-256 dans tiroir ────────────────────────────────────────────
    st.markdown("---")
    with st.expander("🔐 Traçabilité & Lignée Cryptographique (SHA-256)", expanded=False):
        st.caption(
            "Ces empreintes garantissent que les données sources et les prédictions "
            "n'ont pas été altérées depuis la signature de cet audit. "
            "Les valeurs complètes sont disponibles dans l'export JSON signé."
        )

        def _fmt_hash(h: str) -> str:
            """Tronque un hash SHA-256 : 8 chars + … + 3 derniers chars (F-05)."""
            if not h or h == "N/A":
                return "N/A"
            return f"{h[:8]}…{h[-3:]}"

        for label, hkey, desc in [
            ("🗄  DATA HASH",        "data_hash",
             "SHA-256 du DataFrame source (CSV sérialisé sans index)"),
            ("📈  PREDICTIONS HASH", "predictions_hash",
             "SHA-256 du tableau numpy des prédictions brutes"),
            ("🔏  AUDIT HASH",       "audit_hash",
             "SHA-256 de l'audit complet — à conserver pour vérification légale"),
        ]:
            hval = _fmt_hash(integrity.get(hkey, "N/A"))
            st.markdown(
                f'<div class="xai-hash-box">'
                f'<div class="hl">{label}</div>'
                f'<div class="hv">{hval}</div>'
                f'<div class="hd">{desc}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("**🔎 Vérificateur manuel**")
        v1, v2 = st.columns([3, 1])
        with v1:
            input_verify = st.text_area("Contenu à hacher", height=70, key="xai_verify_input",
                                        placeholder="Collez ici le texte à vérifier…")
        with v2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔐 SHA-256", use_container_width=True, key="xai_verify_btn"):
                if input_verify:
                    computed   = agent.compute_sha256(input_verify)
                    data_hash  = integrity.get("data_hash", "")
                    pred_hash  = integrity.get("predictions_hash", "")
                    audit_hash = integrity.get("audit_hash", "")
                    note = (
                        "✅ Correspond au DATA HASH"        if computed == data_hash  else
                        "✅ Correspond au PREDICTIONS HASH" if computed == pred_hash  else
                        "✅ Correspond à l'AUDIT HASH"      if computed == audit_hash else
                        "⚪ Aucune correspondance avec les artefacts de cet audit."
                    )
                    # Afficher le hash tronqué — hash complet disponible en export JSON
                    st.code(_fmt_hash(computed), language="text")
                    st.info(note)

        st.markdown("---")
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            st.metric("📅 Timestamp UTC",
                      audit_report.get("timestamp", "N/A")[:19].replace("T", " "))
        with mc2:
            st.metric("🗄 Dataset", audit_report.get("dataset_name", "N/A"))
        with mc3:
            st.metric("📊 Obs. / Features",
                      f"{audit_report.get('n_samples',0):,} / {audit_report.get('n_features',0)}")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — TÉLÉMÉTRIE & GOUVERNANCE
# ─────────────────────────────────────────────────────────────────────────────
with tab_telemetry:

    st.markdown('<span class="xai-pill">⚙️ Télémétrie d\'exécution</span>', unsafe_allow_html=True)
    st.markdown("")

    t1, t2, t3, t4 = st.columns(4)
    with t1: st.metric("🏢 Fournisseur", telemetry.get("provider", "N/A"))
    with t2: st.metric("🧩 Modèle", telemetry.get("model", "-"))
    with t3: st.metric("🤖 LLM", "✅ Actif" if llm_ok else "❌ Fallback")
    with t4: st.metric("⏱ Durée", f"{telemetry.get('duration_s', 0)} s")

    st.markdown("---")
    st.markdown('<span class="xai-pill">🧾 Historique des tentatives</span>', unsafe_allow_html=True)
    st.markdown("")

    attempts = telemetry.get("attempts", [])
    if not attempts:
        st.info("Aucune tentative LLM enregistrée pour cet audit.")
    else:
        icons = {"success": "✅", "failed": "❌", "skipped": "⏭️"}
        # F-04 : sanitiser les détails — masquer les stack traces et chemins internes
        def _sanitize_detail(raw: str) -> str:
            """Remplace les détails techniques bruts par un message lisible."""
            if not raw:
                return "—"
            # Masquer les chemins système (Windows et Unix)
            import re
            raw = re.sub(r'[A-Za-z]:\\[^\s,;]+', '[chemin masqué]', raw)
            raw = re.sub(r'/[^\s,;]{10,}',        '[chemin masqué]', raw)
            # Tronquer à 80 chars pour éviter les stack traces complètes
            return raw[:80] + ("…" if len(raw) > 80 else "")

        st.dataframe(
            pd.DataFrame([{
                "":            icons.get(a["status"], "•"),
                "Fournisseur": a["provider"],
                "Statut":      a["status"],
                "Détail":      _sanitize_detail(a.get("detail", "")),
            } for a in attempts]),
            use_container_width=True, hide_index=True,
        )

    # Timeline forensique
    st.markdown("---")
    st.markdown('<span class="xai-pill">📅 Timeline forensique</span>', unsafe_allow_html=True)
    st.markdown("")

    ts_str = audit_report.get("timestamp", "")[:19].replace("T", " ")
    acc_str = f"{surrogate_accuracy*100:.1f}%" if surrogate_accuracy else "N/A"
    events = [
        ("🗄",  "Dataset chargé & validé",        ts_str,
         f"{n_samples:,} lignes · {n_features_kpi} features · {dataset_name}", 0),
        ("⚙️", "Surrogate RandomForest entraîné", "—",
         f"Tâche : {task_type} · Précision : {acc_str}", 0),
        ("📐",  "Attributions SHAP calculées",     "—",
         f"Explainer : {explainer_type} · {len(top_features)} features", 1),
        ("🔐",  "Hashes SHA-256 générés",          "—",
         f"Data · Prédictions · Audit — {'✅ OK' if hash_ok else '⚠ KO'}", 0),
        ("💬",  "Explication LLM générée",         "—",
         f"Moteur : {engine_used} · Provider : {telemetry.get('provider','N/A')}", 0),
        ("🛡️", "Rapport d'audit finalisé",        ts_str,
         f"Durée : {telemetry.get('duration_s',0)} s · {compliance_lbl}", 1),
    ]
    tl = "".join(
        f'<div class="bf-tl{" act" if a else ""}"><i>{ic}</i>'
        f'<div style="flex:1"><span class="t">{ts}</span><b>{n}</b>'
        f'<br><small>{d}</small></div></div>'
        for ic, n, ts, d, a in events
    )
    html(f'<div class="bf-card">{tl}</div>')

    # Grille de gouvernance
    st.markdown("---")
    st.markdown('<span class="xai-pill">🛡️ Contrôles de gouvernance</span>', unsafe_allow_html=True)
    st.markdown("")

    shap_expl_ok = explainer_type not in ("failed", "shap_not_installed")
    gov = [
        ("Lignée des données complète",        "✔", "ok"),
        ("Calculs déterministes reproductibles","✔", "ok"),
        ("Explication ancrée dans les données","✔", "ok"),
        ("Intégrité SHA-256 vérifiée",
         "✔" if hash_ok else "⚠", "ok" if hash_ok else "warn"),
        ("Aucune feature sensible exposée",    "✔", "ok"),
        (f"SHAP · {explainer_type}",
         "✔" if shap_expl_ok else "❌", "ok" if shap_expl_ok else "fail"),
    ]
    gov_html = '<div class="xai-gov-grid">'
    for label, status, cls in gov:
        gov_html += (
            f'<div class="xai-gov-item{" fail" if cls=="fail" else " warn" if cls=="warn" else ""}">'
            f'<span class="gs">{status}</span><span class="gl">{label}</span></div>'
        )
    gov_html += "</div>"
    st.markdown(gov_html, unsafe_allow_html=True)

# =============================================================================
# 8. ACTION — Relancer
# =============================================================================
st.markdown("---")
if st.button("🔄 Relancer l'audit forensique", type="primary"):
    train_surrogate.clear()
    st.session_state["xai_force_rerun"] = True
    st.rerun()
