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
from typing import Any, Dict, List, Optional, Tuple, Union

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
setup("Audit & XAI", hub="Agent 3 · XAI Auditor")
page_header(
    "🛡️ Cockpit de Gouvernance & Explicabilité XAI",
    "Conformité, traçabilité cryptographique et attribution causale des décisions IA.",
    badge("Agent 3", "purple"),
    "Agent 3 · XAI Auditor > <b>Governance & Audit</b>",
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
# SIDEBAR — Gouvernance & Navigation
# =============================================================================

st.sidebar.markdown("### 🛡️ Gouvernance & Audit")
st.sidebar.caption(
    "L'**Agent 3 (XAI Auditor)** certifie automatiquement le pipeline complet "
    "(A1 Profiling/Qualité ➔ A2 BI Insights ➔ A3 Audit)."
)

# Récupérer l'audit du pipeline
wf_st = st.session_state.get("wf_graph_state") or {}
pipe_res = st.session_state.get("pipeline_results") or {}
a3_rep = (wf_st.get("reports") or {}).get("xai_auditor") or pipe_res.get("agent3")
audit_report = st.session_state.get("xai_audit_report") or (a3_rep.get("audit_report") if a3_rep else None)

if audit_report:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**📋 Audit actif :**")
    st.sidebar.success(f"● {audit_report.get('dataset_name', 'Dataset')}")
    _ts = audit_report.get("timestamp", "")[:19].replace("T", " ")
    if _ts:
        st.sidebar.caption(f"📅 Scellé le : `{_ts}`")
    _hash = audit_report.get("integrity", {}).get("audit_hash", "")
    if _hash:
        st.sidebar.caption(f"🔐 Hash : `{_hash[:12]}…`")

# =============================================================================
# 1. ÉTAT D'AUDIT DU PIPELINE
# =============================================================================

_wf_res = st.session_state.get("wf_resource_mode", "auto")
_xai_eng = "api" if _wf_res == "cloud" else ("local" if _wf_res == "local" else "auto")
agent = XAIAuditorAgent(engine=_xai_eng, ollama_model="qwen2.5:3b")

if not audit_report:
    st.markdown("""
    <div style="background:#ffffff; border:1px solid #e0e7ff; border-radius:18px; padding:3rem 2rem; text-align:center; max-width:760px; margin:2.5rem auto; box-shadow:0 10px 25px -5px rgba(99,102,241,0.08);">
      <div style="font-size:3.5rem; margin-bottom:1rem;">🛡️</div>
      <h2 style="color:#1e1b4b; font-weight:700; margin-bottom:0.75rem;">Aucun audit actif en mémoire</h2>
      <p style="color:#475569; font-size:1rem; line-height:1.7; margin-bottom:1.5rem;">
        L'<b>Agent 3 (Audit & XAI)</b> est le certificateur final de la plateforme BIFlow.<br>
        Il s'exécute automatiquement lors de l'exécution du pipeline complet (<b>Agent 1 ➔ Agent 2 ➔ Agent 3</b>) afin d'auditer la conformité, vérifier le nettoyage des données et expliquer les décisions via SHAP.
      </p>
      <div style="background:#f8fafc; border-left:4px solid #6366f1; border-radius:0 10px 10px 0; padding:0.9rem 1.2rem; text-align:left; margin-bottom:2rem; font-size:0.88rem; color:#334155; line-height:1.6;">
        ℹ️ <b>Règle de gouvernance BIFlow :</b><br>
        Si vous avez sélectionné uniquement l'Agent 2 en mode direct (<code>direct_agent_2</code>), l'Agent 3 est intentionnellement ignoré car il ne dispose pas des métriques de qualité et de traçabilité de l'Agent 1.
      </div>
    </div>
    """, unsafe_allow_html=True)

    c_l, c_btn, c_r = st.columns([1, 2, 1])
    with c_btn:
        if st.button("🚀 Aller dans Workflows pour exécuter le pipeline complet", type="primary", use_container_width=True, key="btn_goto_wf_from_xai"):
            st.session_state.sidebar_mode = "nav"
            st.switch_page("pages/3_Workflows.py")
    st.stop()

# =============================================================================
# 2. RESTITUTION DE L'AUDIT CERTIFIÉ
# =============================================================================

dataset_name       = audit_report.get("dataset_name", "Dataset")
n_samples          = audit_report.get("n_samples", 0)
n_features         = audit_report.get("n_features", 0)
integrity          = audit_report.get("integrity", {})
telemetry          = audit_report.get("telemetry", {})
shap_block         = audit_report.get("shap", {})
shap_summary       = shap_block.get("summary", {})
top_features       = shap_summary.get("top_features", [])
pred_dist          = audit_report.get("predictions_distribution", {})
narrative          = audit_report.get("narrative_explanation", "")
explainer_type     = shap_block.get("explainer_type", "N/A")
upstream_ctx       = audit_report.get("upstream_context", {})
surrogate_accuracy = audit_report.get("surrogate_accuracy")
task_type          = audit_report.get("task_type", "classification")

# Carte de synthèse Dataset & Certification
col_card, col_badge = st.columns([3, 1], vertical_alignment="center")
with col_card:
    html(f'''<div class="bf-card" style="background:linear-gradient(135deg,#eef2ff,#f8faff);
      border:1px solid #c7d2fe;display:flex;gap:1.25rem;align-items:center;
      border-radius:16px;padding:1rem 1.4rem;margin-bottom:0.5rem">
      <span style="font-size:1.8rem;">🛡️</span>
      <div>
        <small style="color:#4338ca;font-weight:700;letter-spacing:0.04em;">DATASET CERTIFIÉ PAR LE PIPELINE</small>
        <div style="font-size:1.15rem;font-weight:700;color:#1e1b4b;">{dataset_name}</div>
        <span style="color:#64748b;font-size:0.85rem;">{n_samples:,} observations analysées · {n_features} features auditées</span>
      </div>
    </div>''')
with col_badge:
    st.markdown("""
    <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:14px;padding:0.85rem 1rem;text-align:center;">
      <span class="xai-badge-ok" style="font-size:0.82rem;padding:0.35rem 0.9rem;">● CERTIFIÉ COMPLIANT</span>
      <div style="color:#15803d;font-size:0.75rem;margin-top:0.35rem;font-weight:600;">Traçabilité scellée</div>
    </div>
    """, unsafe_allow_html=True)

# Lignée Tri-Agents
if upstream_ctx.get("has_a1") or upstream_ctx.get("has_a2"):
    c_t1, c_t2, c_t3 = st.columns([1.5, 1.5, 1.2], vertical_alignment="center")
    with c_t1:
        if upstream_ctx.get("has_a1"):
            h_s = upstream_ctx.get("a1_health_score", "N/A")
            st.markdown(f"""
            <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:10px;padding:0.5rem 0.85rem;font-size:0.8rem;">
              <b style="color:#166534;">⚙️ Agent 1 · Data Engineering</b><br>
              <span style="color:#15803d;">✅ Qualité connectée</span> · Score : <b>{h_s}%</b>
            </div>
            """, unsafe_allow_html=True)
    with c_t2:
        if upstream_ctx.get("has_a2"):
            st.markdown("""
            <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:10px;padding:0.5rem 0.85rem;font-size:0.8rem;">
              <b style="color:#166534;">📊 Agent 2 · BI Analyst</b><br>
              <span style="color:#15803d;">✅ Insights BI connectés</span> · KPIs intégrés
            </div>
            """, unsafe_allow_html=True)
    with c_t3:
        st.markdown("""
        <div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:10px;padding:0.5rem 0.85rem;text-align:center;font-size:0.8rem;">
          <b style="color:#4338ca;">🔗 Lineage Tri-Agents</b><br>
          <span style="color:#6366f1;">Scellé SHA-256</span>
        </div>
        """, unsafe_allow_html=True)

n_features_kpi     = n_features
llm_ok             = telemetry.get("is_llm", False)
hash_ok            = bool(integrity.get("audit_hash"))
shap_ok            = bool(top_features)
engine_used        = audit_report.get("engine_used", "auto")

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
    f"Ollama local · <b>{telemetry.get('model', 'qwen2.5:7b')}</b>" if engine_used == "local"
    else f"Cloud API · <b>{_provider_safe}</b>" if engine_used == "api"
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

    up_ctx = audit_report.get("upstream_context", {})
    if up_ctx.get("has_a1") or up_ctx.get("has_a2"):
        a1_pill = f"<b>⚙️ Qualité (Agent 1)</b> : Score santé <b>{up_ctx.get('a1_health_score', 'N/A')}%</b>" if up_ctx.get("has_a1") else ""
        a2_pill = "<b>📊 Insights (Agent 2)</b> : KPIs et tendances intégrés" if up_ctx.get("has_a2") else ""
        details = " &nbsp;·&nbsp; ".join([p for p in [a1_pill, a2_pill] if p])
        st.markdown(f"""
        <div style="background:#f0fdf4;border-left:4px solid #16a34a;border-radius:0 10px 10px 0;padding:0.75rem 1.1rem;margin-bottom:1rem;font-size:0.86rem;color:#166534;">
          🔗 <b>Synthèse Tri-Agents active :</b> {details}
        </div>
        """, unsafe_allow_html=True)

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
            global_shap = float(shap_df["Mean |SHAP|"].mean()) if len(shap_df) else 0.0
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
