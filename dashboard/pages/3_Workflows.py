"""
3_Workflows.py — BIFlow Dashboard
====================================
Cockpit interactif de l'orchestrateur LangGraph BIFlow.
Gère les 3 agents (Data Engineer · BI Analyst · XAI Auditor)
avec 4 modes d'exécution, suivi en temps réel et HITL.

Règles de sécurité : zéro clé API, zéro hash brut, zéro route interne
en affichage principal — tout détail technique dans des st.expander.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

# ── BIFlow imports ────────────────────────────────────────────────────────────
from components import (
    setup, page_header, btn, html, badge, card, grid, kpi, bar,
)
from chat_widget import render_chat

render_chat("Workflows")
setup("Workflows")

# ── Inline CSS — identité visuelle Workflows ──────────────────────────────────
st.markdown("""
<style>
/* Pipeline stepper */
.wf-stepper { display:flex; gap:0; margin-bottom:1.5rem; }
.wf-step {
    flex:1; padding:.65rem .5rem; text-align:center;
    background:#f1f5f9; border:1px solid #e2e8f0;
    font-size:.78rem; font-weight:600; color:#94a3b8;
    position:relative;
}
.wf-step:first-child { border-radius:10px 0 0 10px; }
.wf-step:last-child  { border-radius:0 10px 10px 0; }
.wf-step.done  { background:#dcfce7; color:#166534; border-color:#bbf7d0; }
.wf-step.active{ background:#eef2ff; color:#4338ca; border-color:#a5b4fc; font-weight:700; }
.wf-step.error { background:#fff1f2; color:#be123c; border-color:#fecdd3; }

/* Mode selector pill */
.wf-mode-bar {
    background:#1e1b4b; border:1px solid #4338ca; border-radius:10px;
    padding:.6rem 1.1rem; display:flex; align-items:center; gap:.75rem;
    font-size:.85rem; color:#a5b4fc; margin-bottom:1rem;
}
.wf-mode-bar b { color:#e0e7ff; }

/* Agent card */
.wf-agent-card {
    border-left:4px solid #6366f1; background:#f8faff;
    border-radius:0 12px 12px 0; padding:1.1rem 1.4rem; margin-bottom:.75rem;
}
.wf-agent-card.a2 { border-left-color:#0ea5e9; }
.wf-agent-card.a3 { border-left-color:#a855f7; }
.wf-agent-card.done  { border-left-color:#10b981; background:#f0fdf4; }
.wf-agent-card.error { border-left-color:#f43f5e; background:#fff1f2; }

/* Sandbox badge */
.wf-sandbox {
    display:inline-flex; align-items:center; gap:.35rem;
    background:#0f172a; color:#38bdf8; font-size:.72rem; font-weight:600;
    padding:.2rem .7rem; border-radius:20px; border:1px solid #334155;
}
.wf-sandbox.ok    { color:#34d399; border-color:#065f46; background:#022c22; }
.wf-sandbox.warn  { color:#fbbf24; border-color:#78350f; background:#1c0f00; }

/* Narrative viewer */
.wf-narrative {
    background:#fff; border:1px solid #e2e8f0; border-radius:10px;
    padding:1rem 1.25rem; line-height:1.75; color:#1e293b;
    max-height:320px; overflow-y:auto;
}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# HELPERS
# =============================================================================

def _docker_status() -> Dict[str, bool]:
    """Vérifie si Docker est disponible — résultat mis en cache 30 s."""
    import subprocess
    cache_key  = "_wf_docker_checked"
    cache_ts   = "_wf_docker_ts"
    now        = time.time()
    if st.session_state.get(cache_ts, 0) + 30 > now:
        return st.session_state.get(cache_key, {"docker": False})
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=8)
        ok = r.returncode == 0
    except Exception:
        ok = False
    result = {"docker": ok}
    st.session_state[cache_key] = result
    st.session_state[cache_ts]  = now
    return result


def _sandbox_badge(sandbox_mode: str) -> str:
    docker_ok = _docker_status()["docker"]
    if sandbox_mode == "docker":
        if docker_ok:
            return '<span class="wf-sandbox ok">🐳 Docker · En ligne</span>'
        return '<span class="wf-sandbox warn">🐳 Docker · Hors ligne — fallback in-process</span>'
    return '<span class="wf-sandbox">⚙️ In-process</span>'


def _resource_badge(resource_mode: str) -> str:
    """Badge HTML discret indiquant le moteur LLM actif — sans exposer de clé."""
    icons = {"local": "🦙", "cloud": "☁️", "auto": "🔄"}
    labels = {"local": "Ollama Local", "cloud": "Cloud API", "auto": "Hybride / Auto"}
    return (
        f'<span class="wf-sandbox ok">'
        f'{icons.get(resource_mode,"🤖")} {labels.get(resource_mode, resource_mode)}'
        f'</span>'
    )


def _step_class(agent_key: str, current: str, done_keys: list) -> str:
    if agent_key in done_keys:
        return "done"
    if agent_key == current:
        return "active"
    return ""


def _fmt_duration(s: float) -> str:
    return f"{s:.1f}s" if s < 60 else f"{s/60:.1f}min"


def _safe_truncate_hash(h: str, prefix: int = 8, suffix: int = 4) -> str:
    """Tronque un hash SHA-256 pour l'affichage — règle sécurité F-05."""
    if not h or h == "N/A":
        return "—"
    return f"{h[:prefix]}…{h[-suffix:]}"


def _reset_pipeline() -> None:
    keys = [
        "wf_state", "wf_mode", "wf_step", "wf_file", "wf_sandbox",
        "wf_resource_mode", "wf_thread_id", "wf_app", "wf_graph_state",
        "wf_done_steps", "wf_hitl_pending", "wf_direct_start",
    ]
    for k in keys:
        st.session_state.pop(k, None)


def _init_session() -> None:
    defaults = {
        "wf_state":         "idle",      # idle | running | hitl_pause | done | error
        "wf_mode":          "auto",
        "wf_step":          "none",      # none | data_engineer | bi_analysis | xai_audit | done
        "wf_file":          None,
        "wf_sandbox":       "inprocess",
        "wf_resource_mode": "auto",      # local | cloud | auto  ← NOUVEAU
        "wf_thread_id":     None,
        "wf_app":           None,
        "wf_graph_state":   None,
        "wf_done_steps":    [],
        "wf_hitl_pending":  False,
        "wf_direct_start":  None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_session()

# ── Raccourcis session state ──────────────────────────────────────────────────
wf_state   = st.session_state.wf_state
wf_mode    = st.session_state.wf_mode
wf_step    = st.session_state.wf_step
done_steps = st.session_state.wf_done_steps

# =============================================================================
# PAGE HEADER (dynamique selon l'état)
# =============================================================================

if wf_state == "idle":
    page_header(
        "Orchestrateur Multi-Agents BIFlow",
        "Configurez et lancez le pipeline autonome A1 → A2 → A3 sur votre dataset.",
        "",
        "Workspace › <b>Nouveau Pipeline</b>",
    )
elif wf_state in ("running", "hitl_pause"):
    page_header(
        "Pipeline en cours…",
        "Les agents s'exécutent séquentiellement sur votre dataset.",
        btn("⏹ Arrêter"),
        "Workspace › <b>Pipeline Actif</b>",
    )
else:
    col_hdr1, col_hdr2 = st.columns([3, 1])
    with col_hdr1:
        page_header(
            "Pipeline Termine ✅",
            "Tous les agents ont complete leur travail. Modifiez les parametres dans la sidebar ou relancez.",
            "",
            "Workspace › <b>Resultats</b>",
        )
    with col_hdr2:
        st.write("")
        st.write("")
        if st.button("➕ Nouveau pipeline", type="primary", use_container_width=True, key="hdr_btn_new_pl_top"):
            _reset_pipeline()
            st.rerun()


# =============================================================================
# SIDEBAR — Mode + Sandbox + Dataset
# =============================================================================

# Ne verrouiller la sidebar QUE si le pipeline est en cours d'execution
is_locked = wf_state in ("running", "hitl_pause")

if wf_state == "done":
    col_sb1, col_sb2 = st.sidebar.columns([1, 1])
    with col_sb1:
        if st.sidebar.button("➕ Nouveau pipeline", type="primary", use_container_width=True, key="sb_btn_new_pl"):
            _reset_pipeline()
            st.rerun()
    st.sidebar.markdown("---")

st.sidebar.markdown("### ⚙️ Paramètres du pipeline")

# Mode d'exécution
mode_options = {
    "⚡ Full-Auto (A1 → A2 → A3)":       "auto",
    "🧑‍💼 Human-in-the-Loop (étape/étape)": "hitl",
    "🎯 Exécution directe — Agent 2 (BI)": "direct_agent_2",
    "🎯 Exécution directe — Agent 3 (XAI)":"direct_agent_3",
}
selected_mode_label = st.sidebar.radio(
    "Mode d'exécution",
    list(mode_options.keys()),
    index=0,
    key="wf_mode_radio",
    disabled=is_locked,
)
chosen_mode = mode_options[selected_mode_label]

st.sidebar.markdown("---")
st.sidebar.markdown("### 🐳 Sandbox")
sandbox_options = {"⚙️ In-process (développement)": "inprocess",
                   "🐳 Docker (production isolée)":   "docker"}
selected_sandbox_label = st.sidebar.radio(
    "Mode sandbox",
    list(sandbox_options.keys()),
    index=0,
    key="wf_sandbox_radio",
    disabled=is_locked,
)
chosen_sandbox = sandbox_options[selected_sandbox_label]

# Statut Docker (badge, sans exposer les routes internes)
docker_ok = _docker_status()["docker"]
if chosen_sandbox == "docker":
    if docker_ok:
        st.sidebar.success("🐳 Docker Engine · En ligne")
    else:
        st.sidebar.warning("🐳 Docker hors ligne — fallback in-process automatique")
else:
    st.sidebar.info("⚙️ Mode in-process actif")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🤖 Ressources LLM")

_resource_options = {
    "🦙 Local — Ollama (offline, privé)":    "local",
    "☁️ Cloud — Groq / Gemini (API)":        "cloud",
    "🔄 Hybride / Auto (Local → Cloud → Fallback)": "auto",
}
selected_resource_label = st.sidebar.radio(
    "Moteur LLM des agents",
    list(_resource_options.keys()),
    index=2,   # Auto par défaut
    key="wf_resource_radio",
    help=(
        "Local = Ollama tourne sur cette machine. "
        "Cloud = Groq ou Gemini via API. "
        "Auto = Local d'abord, Cloud si indisponible."
    ),
    disabled=is_locked,
)
chosen_resource = _resource_options[selected_resource_label]

# ── Statut des ressources (sans exposer les clés) ─────────────────────────────
if chosen_resource in ("cloud", "auto"):
    _groq_configured   = bool(os.environ.get("GROQ_API_KEY"))
    _gemini_configured = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

    if _groq_configured:
        st.sidebar.success("🔑 Groq API : Configurée [Masquée] ✅")
    else:
        st.sidebar.warning("🔑 Groq API : Non configurée ❌")

    if _gemini_configured:
        st.sidebar.success("🔑 Gemini API : Configurée [Masquée] ✅")
    else:
        st.sidebar.caption("🔑 Gemini API : Non configurée")

    if not _groq_configured and not _gemini_configured and chosen_resource == "cloud":
        st.sidebar.error(
            "⚠️ Aucune clé Cloud configurée. "
            "Ajoutez `GROQ_API_KEY` ou `GEMINI_API_KEY` dans votre `.env`."
        )

if chosen_resource in ("local", "auto"):
    # Vérifier Ollama (même cache que Docker — TTL 30 s)
    _ollama_cache_key = "_wf_ollama_ok"
    _ollama_cache_ts  = "_wf_ollama_ts"
    _now = time.time()
    if st.session_state.get(_ollama_cache_ts, 0) + 30 < _now:
        try:
            import requests as _req
            _r = _req.get("http://localhost:11434/api/tags", timeout=3)
            _ollama_ok = _r.status_code == 200
        except Exception:
            _ollama_ok = False
        st.session_state[_ollama_cache_key] = _ollama_ok
        st.session_state[_ollama_cache_ts]  = _now
    else:
        _ollama_ok = st.session_state.get(_ollama_cache_key, False)

    if _ollama_ok:
        st.sidebar.success("🦙 Ollama : En ligne ✅")
    else:
        if chosen_resource == "local":
            st.sidebar.warning(
                "⚠️ **Ollama hors ligne.** "
                "Démarrez-le avec `ollama serve` ou basculez sur le mode **Cloud** ou **Hybride**."
            )
        else:
            st.sidebar.caption("🦙 Ollama : Hors ligne — Cloud en fallback")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🗄 Jeu de données")
raw_dir     = PROJECT_ROOT / "data" / "raw"
clean_dir   = PROJECT_ROOT / "data" / "cleaned"
all_csvs    = sorted(raw_dir.glob("*.csv")) if raw_dir.exists() else []
clean_csvs  = sorted(clean_dir.glob("*.csv")) if clean_dir.exists() else []

dataset_map = {}
for f in all_csvs:
    dataset_map[f.name] = str(f)
for f in clean_csvs:
    dataset_map[f"✨ [Nettoyé] {f.name}"] = str(f)

file_names  = list(dataset_map.keys())
NONE_OPT    = "— Sélectionner —"

if not file_names:
    st.sidebar.warning("Aucun fichier trouvé dans `data/`.")
    file_names = []

default_idx = 0
current_preset = st.session_state.get("current_dataset_path")
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
    key="wf_dataset_select",
    disabled=is_locked,
)
selected_path = dataset_map.get(selected_name) if selected_name != NONE_OPT else None

# Pour les modes directs — chemin nettoyé optionnel
direct_cleaned_path = None
if chosen_mode in ("direct_agent_2", "direct_agent_3") and selected_path:
    direct_cleaned_path = selected_path  # utiliser le dataset sélectionné directement

# =============================================================================
# ÉTAT IDLE — Formulaire de configuration
# =============================================================================

if wf_state == "idle":

    # Barre de mode
    mode_icon = {"auto": "⚡", "hitl": "🧑‍💼",
                 "direct_agent_2": "🎯", "direct_agent_3": "🎯"}
    mode_desc = {
        "auto":           "Enchaînement automatique A1 → A2 → A3 sans interruption.",
        "hitl":           "Pause après chaque agent — vous validez avant de continuer.",
        "direct_agent_2": "Lance directement l'Agent 2 (BI) sur le dataset sélectionné.",
        "direct_agent_3": "Lance directement l'Agent 3 (XAI) sur le dataset sélectionné.",
    }
    html(
        f'<div class="wf-mode-bar">'
        f'{mode_icon.get(chosen_mode,"⚙️")} Mode actif : <b>{selected_mode_label.split("(")[0].strip()}</b>'
        f' &nbsp;·&nbsp; {mode_desc[chosen_mode]}'
        f' &nbsp;|&nbsp; {_sandbox_badge(chosen_sandbox)}'
        f' &nbsp;|&nbsp; {_resource_badge(chosen_resource)}'
        f'</div>'
    )

    # Récapitulatif dataset
    if selected_path:
        try:
            _df_preview = pd.read_csv(selected_path, nrows=5)
            _rows = sum(1 for _ in open(selected_path, encoding="utf-8")) - 1
            _cols = len(_df_preview.columns)
        except Exception:
            _rows, _cols = 0, 0

        html(
            '<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;'
            'align-items:center;margin-bottom:1.25rem">🗄 '
            f'<div><b>{selected_name}</b> <span class="bf-badge blue">Source</span><br>'
            f'<small>{_rows:,} lignes · {_cols} colonnes</small></div>'
            '</div>'
        )

        with st.expander("👀 Aperçu des données", expanded=False):
            st.dataframe(_df_preview, use_container_width=True)

    # Tâches sélectionnées (informatif — l'orchestrateur exécute tout)
    TASKS = [
        ("Profiling & Qualité",  "Profiling statistique, scores de santé, cross-column checks", "A1", "~45s", True),
        ("Nettoyage & ETL",      "Standardisation, imputation, détection des outliers",         "A1", "~60s", True),
        ("KPI & Insights",       "Métriques business, tendances, recommandations IA",            "A2", "~50s", True),
        ("Détection d'anomalies","Outliers statistiques et ruptures de patterns",                "A2", "~30s", False),
        ("Audit XAI",            "Attributions SHAP, SHA-256, explication narrative",            "A3", "~40s", True),
    ]

    if chosen_mode not in ("direct_agent_3",):
        st.markdown('<span style="font-size:.85rem;font-weight:600;color:#0f172a;">📋 Tâches incluses</span>',
                    unsafe_allow_html=True)
        cols = st.columns(2)
        for i, (t, d, agent, dur, default) in enumerate(TASKS):
            with cols[i % 2]:
                c1, c2 = st.columns([0.07, 0.93])
                with c1:
                    st.checkbox("", value=default, key=f"wf_task_{i}", label_visibility="collapsed")
                with c2:
                    tone = "indigo" if agent == "A1" else "blue" if agent == "A2" else "purple"
                    html(
                        f'<div style="padding:.1rem 0 .5rem">'
                        f'<b style="font-size:.88rem;color:#0f172a">{t}</b> '
                        f'<span class="bf-badge {tone}" style="font-size:.62rem">{agent}</span> '
                        f'<span style="color:#94a3b8;font-size:.72rem">{dur}</span>'
                        f'<br><small style="color:#64748b;font-size:.78rem">{d}</small></div>'
                    )

    st.markdown("---")

    # Bouton de lancement + bouton mock côte à côte
    col_spacer, col_mock, col_launch = st.columns([2, 1, 1])
    with col_mock:
        mock_clicked = st.button(
            "🧪 Données Mock",
            use_container_width=True,
            help=(
                "Lance directement l'Agent 2 ou 3 avec un dataset synthétique fictif — "
                "aucun fichier réel requis, zéro clé API exposée."
            ),
            disabled=chosen_mode not in ("direct_agent_2", "direct_agent_3"),
        )
    with col_launch:
        can_launch = bool(selected_path)
        launch_clicked = st.button(
            "▷  Lancer le pipeline",
            type="primary",
            use_container_width=True,
            disabled=not can_launch,
        )

    if not can_launch and not mock_clicked:
        st.info("⬆️ Sélectionnez un dataset dans la sidebar pour activer le lancement.")
    if chosen_mode not in ("direct_agent_2", "direct_agent_3") and not can_launch:
        st.caption(
            "💡 Le bouton **Données Mock** est disponible uniquement en mode "
            "**Exécution directe** (Agent 2 ou Agent 3)."
        )

    if launch_clicked and selected_path:
        # Importer et compiler le graphe
        from orchestration.graph import build_graph, make_initial_state

        app = build_graph(
            sandbox_mode=chosen_sandbox,
            enable_hitl=(chosen_mode == "hitl"),
        )
        initial = make_initial_state(
            data_path=selected_path,
            execution_mode=chosen_mode,
            sandbox_mode=chosen_sandbox,
            resource_mode=chosen_resource,
        )

        thread_id  = f"biflow_{int(time.time())}"
        thread_cfg = {"configurable": {"thread_id": thread_id}}

        st.session_state.wf_mode          = chosen_mode
        st.session_state.wf_sandbox       = chosen_sandbox
        st.session_state.wf_resource_mode = chosen_resource
        st.session_state.wf_file          = selected_path
        st.session_state.wf_thread_id  = thread_id
        st.session_state.wf_app        = app
        st.session_state.wf_done_steps = []

        with st.spinner("⚡ Exécution du pipeline multi-agents (A1 Profiling/ETL ➔ A2 BI Insights ➔ A3 Audit XAI)…"):
            try:
                result = app.invoke(initial, thread_cfg)
                st.session_state.wf_graph_state = result
                st.session_state.wf_state = "running"

                # Synchroniser pipeline_results pour les pages A1, A2, A3
                res_reps = result.get("reports") or {}
                if "pipeline_results" not in st.session_state:
                    st.session_state["pipeline_results"] = {}
                if "data_engineer" in res_reps:
                    st.session_state["pipeline_results"]["agent1"] = res_reps["data_engineer"]
                if "bi_analyst" in res_reps:
                    st.session_state["pipeline_results"]["agent2"] = res_reps["bi_analyst"]
                if "xai_auditor" in res_reps:
                    st.session_state["pipeline_results"]["agent3"] = res_reps["xai_auditor"]

                _cleaned_p = (
                    result.get("cleaned_data_path")
                    or res_reps.get("data_engineer", {}).get("cleaned_path")
                    or selected_path
                )
                if _cleaned_p and Path(_cleaned_p).exists():
                    st.session_state["current_dataset_path"] = str(_cleaned_p)

                # Vérifier si le graphe est déjà suspendu (HITL)
                snapshot   = app.get_state(thread_cfg)
                next_nodes = snapshot.next
                if next_nodes and chosen_mode == "hitl":
                    st.session_state.wf_state       = "hitl_pause"
                    st.session_state.wf_hitl_pending = True
                elif result.get("current_step") == "done":
                    st.session_state.wf_state = "done"
                    st.session_state.sidebar_mode = "agent1"
                    st.switch_page("pages/A1_Profiling.py")
            except Exception as e:
                st.session_state.wf_state       = "error"
                st.session_state.wf_graph_state = {"error_message": str(e)}

        st.rerun()

    # ── Lancement avec données mock ───────────────────────────────────────────
    if mock_clicked and chosen_mode in ("direct_agent_2", "direct_agent_3"):
        from orchestration.graph import build_graph
        from orchestration.mock_generator import MockGenerator

        # Sélecteur de domaine mock inline
        with st.container(border=True):
            st.markdown("**🧪 Configuration du Mock**")
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                mock_domain = st.selectbox(
                    "Domaine",
                    ["telecom", "retail", "finance"],
                    key="wf_mock_domain",
                    format_func=lambda d: {
                        "telecom": "📱 Télécom (Churn)",
                        "retail":  "🛍️ Retail (Ventes)",
                        "finance": "💳 Finance (Risque)",
                    }[d],
                )
            with mc2:
                mock_rows = st.number_input(
                    "Lignes générées",
                    min_value=50, max_value=1000, value=300, step=50,
                    key="wf_mock_rows",
                )
            with mc3:
                mock_seed = st.number_input(
                    "Graine (reproductibilité)",
                    min_value=0, max_value=9999, value=42,
                    key="wf_mock_seed",
                )
            launch_mock = st.button(
                "▶ Confirmer & Lancer le Mock",
                type="primary", use_container_width=True,
                key="wf_mock_confirm",
            )

        if launch_mock:
            with st.spinner(
                f"🧪 Génération des données mock ({mock_domain}, {mock_rows} lignes)…"
            ):
                try:
                    gen = MockGenerator(
                        seed=int(mock_seed),
                        domain=mock_domain,
                        n_rows=int(mock_rows),
                    )
                    target_agent = (
                        "bi_analyst" if chosen_mode == "direct_agent_2"
                        else "xai_auditor"
                    )
                    initial = gen.make_state_for_agent(
                        target_agent=target_agent,
                        resource_mode=chosen_resource,
                        sandbox_mode=chosen_sandbox,
                    )

                    app = build_graph(
                        sandbox_mode=chosen_sandbox,
                        enable_hitl=False,   # mock → mode auto uniquement
                    )
                    thread_id  = f"mock_{int(time.time())}"
                    thread_cfg = {"configurable": {"thread_id": thread_id}}

                    st.session_state.wf_mode          = chosen_mode
                    st.session_state.wf_sandbox       = chosen_sandbox
                    st.session_state.wf_resource_mode = chosen_resource
                    st.session_state.wf_file          = initial.get("data_path", "mock")
                    st.session_state.wf_thread_id     = thread_id
                    st.session_state.wf_app           = app
                    st.session_state.wf_done_steps    = []

                    result = app.invoke(initial, thread_cfg)
                    st.session_state.wf_graph_state = result
                    st.session_state.wf_state = "done"

                    if chosen_mode == "direct_agent_2":
                        st.session_state.sidebar_mode = "agent2"
                        st.switch_page("pages/5_BI_Analysis.py")
                    elif chosen_mode == "direct_agent_3":
                        st.session_state.sidebar_mode = "agent3"
                        st.switch_page("pages/6_Audit_XAI.py")
                    else:
                        st.session_state.sidebar_mode = "agent1"
                        st.switch_page("pages/A1_Profiling.py")

                except Exception as e:
                    import re as _re
                    safe_err = _re.sub(r'[A-Za-z]:\\[^\s,;]+', '[chemin masqué]', str(e))
                    st.session_state.wf_state       = "error"
                    st.session_state.wf_graph_state = {"error_message": safe_err}

            st.rerun()

# =============================================================================
# STEPPER VISUEL (affiché pendant running/hitl_pause/done/error)
# =============================================================================

if wf_state not in ("idle",):
    graph_st  = st.session_state.get("wf_graph_state") or {}
    done_list = st.session_state.get("wf_done_steps", [])
    cur_step  = graph_st.get("current_step", "start")

    STEPS = [
        ("data_engineer", "🛠️ Data Engineer"),
        ("bi_analyst",    "📊 BI Analyst"),
        ("xai_auditor",   "🛡️ XAI Auditor"),
    ]

    # Déduire les étapes terminées depuis history_logs
    logs = graph_st.get("history_logs") or []
    done_agents = {e.get("agent") for e in logs if e.get("status") == "success"}

    step_html = '<div class="wf-stepper">'
    for key, label in STEPS:
        cls = ""
        if key in done_agents:
            cls = "done"
            icon = "✅"
        elif key == cur_step:
            cls = "active"
            icon = "⏳"
        elif cur_step == "error" and key not in done_agents:
            cls = "error"
            icon = "❌"
        else:
            icon = "○"
        step_html += f'<div class="wf-step {cls}">{icon}<br>{label}</div>'
    step_html += "</div>"
    html(step_html)

# =============================================================================
# ÉTAT RUNNING (mode auto — exécution terminée ou en cours)
# =============================================================================

if wf_state == "running":
    graph_st = st.session_state.get("wf_graph_state") or {}
    cur      = graph_st.get("current_step", "start")

    if cur == "done":
        st.session_state.wf_state = "done"
        st.session_state.sidebar_mode = "agent1"
        st.switch_page("pages/A1_Profiling.py")
    elif cur == "error":
        st.session_state.wf_state = "error"
        st.rerun()
    else:
        # Le graphe tourne encore — on rerun en boucle légère
        st.info(f"⏳ Pipeline en cours — étape active : **{cur.replace('_', ' ').title()}**")
        time.sleep(1)
        st.rerun()

# =============================================================================
# ÉTAT HITL_PAUSE — pause après un agent, attente de validation
# =============================================================================

if wf_state == "hitl_pause":
    from orchestration.graph import resume_hitl, get_pipeline_summary

    app        = st.session_state.get("wf_app")
    thread_id  = st.session_state.get("wf_thread_id")
    thread_cfg = {"configurable": {"thread_id": thread_id}}
    graph_st   = st.session_state.get("wf_graph_state") or {}

    logs    = graph_st.get("history_logs") or []
    reports = graph_st.get("reports") or {}

    if not logs:
        st.warning("Aucun résultat disponible pour la validation.")
    else:
        last_log = logs[-1]
        agent    = last_log.get("agent", "inconnu")
        status   = last_log.get("status", "unknown")
        duration = last_log.get("duration_s", 0)

        # ── Livrable de l'agent terminé ──────────────────────────────────────
        agent_labels = {
            "data_engineer": ("🛠️ Agent 1 — Data Engineer",  "a1"),
            "bi_analyst":    ("📊 Agent 2 — BI Analyst",     "a2"),
            "xai_auditor":   ("🛡️ Agent 3 — XAI Auditor",   "a3"),
        }
        label, card_cls = agent_labels.get(agent, (f"Agent : {agent}", ""))

        st.markdown(f"### ⏸ Pause HITL — Validation requise après **{label}**")
        st.markdown(
            f"Durée d'exécution : **{_fmt_duration(duration)}** · "
            f"Statut : **{'✅ Succès' if status == 'success' else '❌ Erreur'}**"
        )

        # Résumé du livrable selon l'agent
        if agent == "data_engineer":
            a1_data = reports.get("data_engineer", {})
            health  = a1_data.get("health", {})
            score   = health.get("overall_health_score", "—")
            missing = health.get("missing_info", {}).get("total_missing_cells", "—")
            dupes   = health.get("duplicate_info", {}).get("count", "—")
            issues  = len(health.get("type_issues", {}))

            mc1, mc2, mc3, mc4 = st.columns(4)
            with mc1: st.metric("🎯 Score qualité", f"{score}%")
            with mc2: st.metric("⚠️ Valeurs manquantes", str(missing))
            with mc3: st.metric("📋 Doublons", str(dupes))
            with mc4: st.metric("🔧 Problèmes de types", str(issues))

            cleaned = a1_data.get("cleaned_path", "")
            if cleaned:
                st.caption(f"✅ Dataset nettoyé disponible : `{Path(cleaned).name}`")

            with st.expander("🔍 Détails techniques — Rapport de profiling", expanded=False):
                profiling = a1_data.get("profiling_report", {})
                if profiling:
                    st.json({
                        k: v for k, v in profiling.items()
                        if k in ("agent_summary", "etl_hints", "cross_column_issues")
                    })

        elif agent == "bi_analyst":
            a2_data  = reports.get("bi_analyst", {})
            markdown = a2_data.get("markdown", "")
            cfg      = a2_data.get("chart_config", {})
            kpis     = cfg.get("kpis", [])

            if kpis:
                metric_cols = st.columns(min(4, len(kpis)))
                for i, k in enumerate(kpis[:4]):
                    with metric_cols[i]:
                        st.metric(
                            label=k.get("title", "KPI"),
                            value=str(k.get("value", "—")),
                            delta=k.get("subtitle", ""),
                        )

            # Recuperer les donnees pour afficher les dashboards interactifs en HITL
            _wf_data_path_hitl = (
                graph_st.get("cleaned_data_path")
                or graph_st.get("data_path")
                or st.session_state.get("wf_file")
            )
            _df_wf_hitl = None
            if _wf_data_path_hitl and Path(_wf_data_path_hitl).exists():
                try:
                    _df_wf_hitl = pd.read_csv(_wf_data_path_hitl)
                except Exception:
                    _df_wf_hitl = None

            tab_hitl_rep, tab_hitl_viz = st.tabs(["📄 Rapport Executif BI", "📈 Dashboards IA"])
            with tab_hitl_rep:
                if markdown:
                    st.markdown(markdown)
                else:
                    st.info("Aucun rapport texte disponible.")

            with tab_hitl_viz:
                charts = cfg.get("recommended_charts", [])
                if _df_wf_hitl is not None and charts:
                    try:
                        import plotly.express as px
                        cols = st.columns(2)
                        for i, chart in enumerate(charts[:6]):
                            c_title = chart.get("title", f"Graphique {i+1}")
                            c_type  = str(chart.get("type", "bar")).lower()
                            c_x     = chart.get("column_x")
                            c_y     = chart.get("column_y")
                            if not c_x or c_x not in _df_wf_hitl.columns:
                                continue
                            with cols[i % 2]:
                                with st.container(border=True):
                                    st.caption(f"**{c_title}** · `{c_type.upper()}`")
                                    if c_type == "pie":
                                        data_pie = _df_wf_hitl[c_x].value_counts().reset_index()
                                        data_pie.columns = [c_x, "Count"]
                                        fig = px.pie(data_pie.head(10), names=c_x, values="Count", hole=0.4)
                                        st.plotly_chart(fig, use_container_width=True, key=f"hitl_wf_chart_{i}")
                                    elif c_type == "bar":
                                        if c_y and c_y in _df_wf_hitl.columns and pd.api.types.is_numeric_dtype(_df_wf_hitl[c_y]):
                                            agg = _df_wf_hitl.groupby(c_x, observed=False)[c_y].mean().reset_index()
                                            fig = px.bar(agg.head(15), x=c_x, y=c_y, color_discrete_sequence=["#6366f1"])
                                        else:
                                            data_bar = _df_wf_hitl[c_x].value_counts().reset_index()
                                            data_bar.columns = [c_x, "Count"]
                                            fig = px.bar(data_bar.head(15), x=c_x, y="Count", color_discrete_sequence=["#6366f1"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"hitl_wf_chart_{i}")
                                    elif c_type == "histogram":
                                        fig = px.histogram(_df_wf_hitl, x=c_x, color_discrete_sequence=["#8b5cf6"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"hitl_wf_chart_{i}")
                                    elif c_type == "box":
                                        y_col = c_y if c_y in _df_wf_hitl.columns else None
                                        fig = px.box(_df_wf_hitl, x=c_x, y=y_col, color_discrete_sequence=["#c026d3"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"hitl_wf_chart_{i}")
                                    elif c_type == "scatter":
                                        fig = px.scatter(_df_wf_hitl, x=c_x, y=c_y if c_y in _df_wf_hitl.columns else None, color_discrete_sequence=["#06b6d4"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"hitl_wf_chart_{i}")
                                    else:
                                        fig = px.histogram(_df_wf_hitl, x=c_x, color_discrete_sequence=["#6366f1"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"hitl_wf_chart_{i}")
                    except Exception as chart_err:
                        st.caption(f"Visualisation : {chart_err}")
                else:
                    st.info("Aucun graphique configure ou dataset non disponible.")

        elif agent == "xai_auditor":
            a3_data   = reports.get("xai_auditor", {})
            narrative = a3_data.get("narrative", "")
            telemetry = a3_data.get("telemetry", {})
            audit_rep = a3_data.get("audit_report", {})
            shap_sum  = audit_rep.get("shap", {}).get("summary", {})
            top_feat  = shap_sum.get("top_features", [])

            xc1, xc2, xc3 = st.columns(3)
            with xc1:
                st.metric("🔑 Provider LLM",
                          telemetry.get("provider", "—").split("(")[0].strip())
            with xc2:
                st.metric("📐 Features SHAP", str(len(top_feat)))
            with xc3:
                st.metric("⏱ Durée", f"{telemetry.get('duration_s', 0)}s")

            if narrative:
                st.markdown('<div class="wf-narrative">', unsafe_allow_html=True)
                st.markdown(narrative[:1200] + ("…" if len(narrative) > 1200 else ""))
                st.markdown("</div>", unsafe_allow_html=True)

            # Hashes SHA-256 dans tiroir (règle sécurité F-05)
            with st.expander("🔐 Traçabilité cryptographique (SHA-256)", expanded=False):
                integrity = audit_rep.get("integrity", {})
                for lbl, key in [("Data", "data_hash"), ("Prédictions", "predictions_hash"),
                                  ("Audit", "audit_hash")]:
                    h = _safe_truncate_hash(integrity.get(key, ""))
                    st.caption(f"**{lbl} hash :** `{h}`")

        # ── Boutons HITL ──────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### Que souhaitez-vous faire ?")
        btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 1])

        with btn_col1:
            approve = st.button(
                "✅ Valider & Continuer",
                type="primary", use_container_width=True, key="hitl_approve",
            )
        with btn_col2:
            retry = st.button(
                "🔄 Recommencer cet agent (Retry)",
                use_container_width=True, key="hitl_retry",
            )
        with btn_col3:
            stop = st.button(
                "⏹ Arrêter",
                use_container_width=True, key="hitl_stop",
            )

        if approve:
            with st.spinner("▶️ Reprise du pipeline…"):
                try:
                    new_state = resume_hitl(app, thread_cfg, decision="approved")
                    st.session_state.wf_graph_state = new_state
                    snapshot   = app.get_state(thread_cfg)
                    next_nodes = snapshot.next
                    if next_nodes:
                        st.session_state.wf_state = "hitl_pause"
                    else:
                        st.session_state.wf_state = "done"
                        st.session_state.sidebar_mode = "agent1"
                        st.switch_page("pages/A1_Profiling.py")
                except Exception as e:
                    st.session_state.wf_state       = "error"
                    st.session_state.wf_graph_state = {"error_message": str(e)}
            st.rerun()

        if retry:
            with st.spinner("🔄 Réexécution de l'agent…"):
                try:
                    new_state = resume_hitl(app, thread_cfg, decision="rejected")
                    st.session_state.wf_graph_state = new_state
                    snapshot   = app.get_state(thread_cfg)
                    next_nodes = snapshot.next
                    if next_nodes:
                        st.session_state.wf_state = "hitl_pause"
                    else:
                        st.session_state.wf_state = "done"
                except Exception as e:
                    st.session_state.wf_state       = "error"
                    st.session_state.wf_graph_state = {"error_message": str(e)}
            st.rerun()

        if stop:
            _reset_pipeline()
            st.rerun()

# =============================================================================
# ÉTAT DONE — Résultats consolidés
# =============================================================================

if wf_state == "done":
    from orchestration.graph import get_pipeline_summary

    graph_st = st.session_state.get("wf_graph_state") or {}
    reports  = graph_st.get("reports") or {}
    summary  = get_pipeline_summary(graph_st)

    # ── Métriques globales du pipeline ───────────────────────────────────────
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("✅ Statut", "SUCCÈS")
    with s2:
        st.metric("⏱ Durée totale", _fmt_duration(summary["total_duration"]))
    with s3:
        st.metric("📦 Agents exécutés", str(len(summary["steps_done"])))
    with s4:
        st.metric("🗄 Rapports produits", str(len(summary["reports_available"])))

    st.markdown("---")

    # ── Timeline des agents ───────────────────────────────────────────────────
    for step_info in summary["steps_done"]:
        ag   = step_info.get("agent", "")
        dur  = step_info.get("duration_s", 0)
        stat = step_info.get("status", "")

        icons = {"data_engineer": "🛠️", "bi_analyst": "📊", "xai_auditor": "🛡️"}
        names = {"data_engineer": "Agent 1 — Data Engineer",
                 "bi_analyst":    "Agent 2 — BI Analyst",
                 "xai_auditor":   "Agent 3 — XAI Auditor"}
        cls_map = {"data_engineer": "a1", "bi_analyst": "a2", "xai_auditor": "a3"}

        card_cls = "done" if stat == "success" else "error"
        html(
            f'<div class="wf-agent-card {card_cls}">'
            f'<b>{icons.get(ag,"⚙️")} {names.get(ag, ag)}</b>'
            f' &nbsp;<span style="color:#94a3b8;font-size:.8rem">{_fmt_duration(dur)}</span>'
            f'<br><small style="color:{"#166534" if stat=="success" else "#be123c"};">'
            f'{"✅ Succès" if stat == "success" else "❌ Erreur"}</small>'
            f'</div>'
        )

    # ── Sauvegarde automatique dans session_state pour les pages dédiées ────────
    _wf_cleaned_path = (
        graph_st.get("cleaned_data_path")
        or reports.get("data_engineer", {}).get("cleaned_path")
        or graph_st.get("data_path")
        or st.session_state.get("wf_file")
    )
    if _wf_cleaned_path and Path(_wf_cleaned_path).exists():
        st.session_state["current_dataset_path"] = str(_wf_cleaned_path)

    # Synchroniser les résultats pour A1_Profiling, A1_Quality, A1_ETL_Cleaning
    if "pipeline_results" not in st.session_state:
        st.session_state["pipeline_results"] = {}
    if "data_engineer" in reports:
        st.session_state["pipeline_results"]["agent1"] = reports["data_engineer"]
    if "bi_analyst" in reports:
        st.session_state["pipeline_results"]["agent2"] = reports["bi_analyst"]
    if "xai_auditor" in reports:
        st.session_state["pipeline_results"]["agent3"] = reports["xai_auditor"]

    # ── Onglets interactifs des livrables par Agent ────────────────────────────
    st.markdown("### 📋 Livrables et Détails par Agent")
    tab_a1, tab_a2, tab_a3 = st.tabs([
        "🛠️ Agent 1 — Data Quality & Nettoyage",
        "📊 Agent 2 — Analyse BI & Dashboards",
        "🛡️ Agent 3 — Audit XAI & Conformité",
    ])

    # ── Onglet Agent 1 : Data Engineer ────────────────────────────────────────
    with tab_a1:
        if "data_engineer" in reports:
            a1   = reports["data_engineer"]
            hlth = a1.get("health", {})
            score   = hlth.get("overall_health_score", hlth.get("overall_score", "—"))
            missing = hlth.get("missing_info", {}).get("total_missing_cells", "—")
            dupes   = hlth.get("duplicate_info", {}).get("count", "—")
            issues  = len(hlth.get("type_issues", {}))

            d1c1, d1c2, d1c3, d1c4 = st.columns(4)
            with d1c1: st.metric("🎯 Score santé qualité", f"{score}%")
            with d1c2: st.metric("⚠️ Valeurs manquantes",  str(missing))
            with d1c3: st.metric("📋 Doublons détectés",    str(dupes))
            with d1c4: st.metric("🔧 Problèmes de types",  str(issues))

            cleaned = a1.get("cleaned_path", "")
            if cleaned and Path(cleaned).exists():
                st.success(f"✨ **Dataset nettoyé prêt :** `{Path(cleaned).name}`")
                try:
                    df_clean_prev = pd.read_csv(cleaned)
                    st.caption(f"Aperçu des 5 premières lignes nettoyées ({len(df_clean_prev)} lignes × {len(df_clean_prev.columns)} colonnes) :")
                    st.dataframe(df_clean_prev.head(5), use_container_width=True)
                except Exception:
                    pass

            # Transformations appliquées
            trans = a1.get("transformations_log", [])
            if trans:
                with st.expander(f"⚙️ Transformations de nettoyage exécutées ({len(trans)})", expanded=True):
                    for t in trans:
                        col = t.get("column", "")
                        action = t.get("action", "")
                        nb = t.get("nulls_before", 0)
                        na = t.get("nulls_after", 0)
                        st.markdown(f"- Colonne **`{col}`** : `{action}` (valeurs nulles : {nb} ➔ {na})")

            with st.expander("🔍 Rapport de profiling complet (A1 Profiling)", expanded=False):
                prof = a1.get("profiling_report", {})
                summary_txt = prof.get("agent_summary", "")
                if summary_txt:
                    st.markdown(f"> {summary_txt}")
                etl = prof.get("etl_hints", {}).get("type_casting_targets", {})
                if etl:
                    casts = " · ".join(f"`{c}` → `{t}`" for c, t in etl.items())
                    st.markdown(f"**ETL hints :** {casts}")

            st.markdown("---")
            st.markdown("**Inspecter les sous-pages de l'Agent 1 :**")
            a1_btn_col1, a1_btn_col2, a1_btn_col3 = st.columns(3)
            with a1_btn_col1:
                if st.button("📊 Voir Profiling complet", use_container_width=True, key="tab_btn_goto_prof"):
                    st.session_state.sidebar_mode = "agent1"
                    st.switch_page("pages/A1_Profiling.py")
            with a1_btn_col2:
                if st.button("✅ Voir Quality Check", use_container_width=True, key="tab_btn_goto_qual"):
                    st.session_state.sidebar_mode = "agent1"
                    st.switch_page("pages/A1_Quality.py")
            with a1_btn_col3:
                if st.button("🔧 Voir ETL & Nettoyage", use_container_width=True, key="tab_btn_goto_etl"):
                    st.session_state.sidebar_mode = "agent1"
                    st.switch_page("pages/A1_ETL_Cleaning.py")
        else:
            st.info("Aucun rapport Data Engineer disponible.")

    # ── Onglet Agent 2 : BI Analyst ───────────────────────────────────────────
    with tab_a2:
        if "bi_analyst" in reports:
            a2   = reports["bi_analyst"]
            cfg  = a2.get("chart_config", {})
            kpis = cfg.get("kpis", [])
            md   = a2.get("markdown", "")

            if kpis:
                kpi_cols = st.columns(min(4, len(kpis)))
                for i, k in enumerate(kpis[:4]):
                    with kpi_cols[i]:
                        st.metric(k.get("title", "KPI"), str(k.get("value", "—")),
                                  delta=k.get("subtitle", ""))

            # Récupérer les données pour tracer les graphiques
            _df_wf = None
            if _wf_cleaned_path and Path(_wf_cleaned_path).exists():
                try:
                    _df_wf = pd.read_csv(_wf_cleaned_path)
                except Exception:
                    _df_wf = None

            tab_wf_rep, tab_wf_viz = st.tabs(["📄 Rapport Exécutif BI", "📈 Dashboards Interactifs"])

            with tab_wf_rep:
                if md:
                    st.markdown(md)
                else:
                    st.info("Aucun rapport texte disponible.")

            with tab_wf_viz:
                charts = cfg.get("recommended_charts", [])
                if _df_wf is not None and charts:
                    try:
                        import plotly.express as px
                        cols = st.columns(2)
                        for i, chart in enumerate(charts[:6]):
                            c_title = chart.get("title", f"Graphique {i+1}")
                            c_type  = str(chart.get("type", "bar")).lower()
                            c_x     = chart.get("column_x")
                            c_y     = chart.get("column_y")
                            if not c_x or c_x not in _df_wf.columns:
                                continue
                            with cols[i % 2]:
                                with st.container(border=True):
                                    st.caption(f"**{c_title}** · `{c_type.upper()}`")
                                    if c_type == "pie":
                                        data_pie = _df_wf[c_x].value_counts().reset_index()
                                        data_pie.columns = [c_x, "Count"]
                                        fig = px.pie(data_pie.head(10), names=c_x, values="Count", hole=0.4)
                                        st.plotly_chart(fig, use_container_width=True, key=f"wf_chart_{i}")
                                    elif c_type == "bar":
                                        if c_y and c_y in _df_wf.columns and pd.api.types.is_numeric_dtype(_df_wf[c_y]):
                                            agg = _df_wf.groupby(c_x, observed=False)[c_y].mean().reset_index()
                                            fig = px.bar(agg.head(15), x=c_x, y=c_y, color_discrete_sequence=["#6366f1"])
                                        else:
                                            data_bar = _df_wf[c_x].value_counts().reset_index()
                                            data_bar.columns = [c_x, "Count"]
                                            fig = px.bar(data_bar.head(15), x=c_x, y="Count", color_discrete_sequence=["#6366f1"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"wf_chart_{i}")
                                    elif c_type == "histogram":
                                        fig = px.histogram(_df_wf, x=c_x, color_discrete_sequence=["#8b5cf6"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"wf_chart_{i}")
                                    elif c_type == "box":
                                        y_col = c_y if c_y in _df_wf.columns else None
                                        fig = px.box(_df_wf, x=c_x, y=y_col, color_discrete_sequence=["#c026d3"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"wf_chart_{i}")
                                    else:
                                        fig = px.histogram(_df_wf, x=c_x, color_discrete_sequence=["#6366f1"])
                                        st.plotly_chart(fig, use_container_width=True, key=f"wf_chart_{i}")
                    except Exception as chart_err:
                        st.caption(f"Visualisation : {chart_err}")
                else:
                    st.info("Aucun graphique configuré ou dataset non disponible.")

            if st.button("👉 Ouvrir la page BI Analysis complète (avec Sandbox Monitor)", key="tab_btn_goto_bi"):
                st.session_state["current_bi_report"]    = md
                st.session_state["current_chart_config"] = cfg
                st.session_state["current_bi_telemetry"] = a2.get("telemetry", {})
                if _wf_cleaned_path:
                    st.session_state["current_dataset_path"] = str(_wf_cleaned_path)
                st.switch_page("pages/5_BI_Analysis.py")
        else:
            st.info("Aucun rapport BI Analyst disponible.")

    # ── Onglet Agent 3 : XAI Auditor ──────────────────────────────────────────
    with tab_a3:
        if "xai_auditor" in reports:
            a3        = reports["xai_auditor"]
            narrative = a3.get("narrative", "")
            telemetry = a3.get("telemetry", {})
            audit_rep = a3.get("audit_report", {})
            shap_sum  = audit_rep.get("shap", {}).get("summary", {})
            top_feat  = shap_sum.get("top_features", [])

            xm1, xm2, xm3, xm4 = st.columns(4)
            with xm1: st.metric("🔑 Provider LLM",
                                 telemetry.get("provider", "—").split("(")[0].strip())
            with xm2: st.metric("📐 Features SHAP", str(len(top_feat)))
            with xm3: st.metric("🌍 Mean |SHAP|",
                                 f'{shap_sum.get("global_mean_abs_shap", 0):.4f}')
            with xm4: st.metric("⏱ Durée LLM", f'{telemetry.get("duration_s", 0)}s')

            if top_feat:
                shap_df = pd.DataFrame(top_feat).rename(columns={
                    "feature": "Feature", "mean_abs_shap": "Mean |SHAP|"
                })
                st.bar_chart(
                    shap_df.set_index("Feature")["Mean |SHAP|"].sort_values(ascending=True),
                    color="#a855f7", horizontal=True,
                    height=max(200, len(top_feat) * 28),
                )

            if narrative:
                with st.expander("💬 Explication narrative XAI", expanded=True):
                    st.markdown(narrative)

            with st.expander("🔐 Traçabilité & lignée cryptographique (SHA-256)", expanded=False):
                integrity = audit_rep.get("integrity", {})
                for lbl, key in [("Data", "data_hash"), ("Prédictions", "predictions_hash"),
                                  ("Audit", "audit_hash")]:
                    h = _safe_truncate_hash(integrity.get(key, ""))
                    st.caption(f"**{lbl} hash :** `{h}`")

            if st.button("👉 Ouvrir le Cockpit XAI complet", key="tab_btn_goto_xai"):
                st.switch_page("pages/6_Audit_XAI.py")
        else:
            st.info("Aucun rapport XAI Auditor disponible.")

    # ── Actions finales ───────────────────────────────────────────────────────
    st.markdown("---")
    act1, act2, act3 = st.columns(3)
    with act1:
        if st.button("📊 Profiling & Qualité (Agent 1)", use_container_width=True):
            st.session_state.sidebar_mode = "agent1"
            st.switch_page("pages/A1_Profiling.py")
    with act2:
        if st.button("📈 Analyse BI complète (Agent 2)", use_container_width=True):
            st.session_state.sidebar_mode = "agent2"
            st.switch_page("pages/5_BI_Analysis.py")
    with act3:
        if st.button("🛡️ Audit XAI complet (Agent 3)", use_container_width=True):
            st.session_state.sidebar_mode = "agent3"
            st.switch_page("pages/6_Audit_XAI.py")

# =============================================================================
# ÉTAT ERROR
# =============================================================================

if wf_state == "error":
    graph_st = st.session_state.get("wf_graph_state") or {}
    # Masquer les chemins internes dans le message d'erreur (règle sécurité F-04)
    import re as _re
    raw_err = graph_st.get("error_message", "Erreur inconnue.")
    safe_err = _re.sub(r'[A-Za-z]:\\[^\s,;]+', '[chemin masqué]', raw_err)
    safe_err = _re.sub(r'/[^\s,;]{15,}',        '[chemin masqué]', safe_err)

    st.error(f"❌ **Le pipeline a rencontré une erreur.**\n\n{safe_err[:400]}")

    col_retry, col_reset = st.columns(2)
    with col_retry:
        if st.button("🔄 Réessayer depuis le début", type="primary", use_container_width=True):
            wf_file    = st.session_state.get("wf_file")
            wf_mode_sv = st.session_state.get("wf_mode", "auto")
            wf_sb_sv   = st.session_state.get("wf_sandbox", "inprocess")
            wf_rm_sv   = st.session_state.get("wf_resource_mode", "auto")
            _reset_pipeline()
            if wf_file:
                st.session_state.wf_file          = wf_file
                st.session_state.wf_mode          = wf_mode_sv
                st.session_state.wf_sandbox       = wf_sb_sv
                st.session_state.wf_resource_mode = wf_rm_sv
            st.rerun()
    with col_reset:
        if st.button("🏠 Retour à l'accueil", use_container_width=True):
            _reset_pipeline()
            st.rerun()
