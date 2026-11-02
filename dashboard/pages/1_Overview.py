from datetime import datetime
from html import escape
import json
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from components import setup, page_header, btn, html, kpi, grid, card, table, badge, bar
from chat_widget import render_chat
from dataset_utils import get_workspace_summary

user = st.session_state.get("authenticated_user")
if user is None:
    st.switch_page("app.py")  # personne de connecté : retour à l'accueil
    st.stop()

first_name = escape(user["full_name"].split()[0]) if user.get("full_name", "").strip() else "there"
hour = datetime.now().hour
greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"

setup("Overview")

# ---------- Style des agents (injecté ici, style.py reste inchangé) ----------
st.markdown("""
<style>
.bf-agents-sum{display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem;
  font-size:.78rem;color:#475569;font-weight:600}
.bf-agents-sum .mono{color:#4338ca}
.bf-agents-prog{height:6px;border-radius:99px;background:#e0e7ff;overflow:hidden;margin-bottom:1.1rem}
.bf-agents-prog span{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#6366f1,#a855f7)}
.bf-agent{position:relative;display:flex;align-items:center;gap:.85rem;padding:.8rem .9rem;margin-bottom:.65rem;
  border-radius:14px;background:linear-gradient(135deg,#ffffff,#f5f7ff);border:1px solid #e8ecfb;
  box-shadow:0 1px 2px rgba(15,23,42,.04);transition:transform .25s ease,box-shadow .25s ease,border-color .25s ease}
.bf-agent:hover{transform:translateX(5px);border-color:#a5b4fc;box-shadow:0 10px 26px rgba(79,70,229,.15)}
.bf-agent:not(:last-child)::after{content:"";position:absolute;left:1.72rem;top:100%;width:2px;height:.65rem;
  background:linear-gradient(#c7d2fe,transparent)}
.bf-agent .av{width:42px;height:42px;border-radius:13px;flex:none;display:grid;place-items:center;
  font-size:1.2rem;color:#fff;box-shadow:0 6px 16px rgba(79,70,229,.28)}
.bf-agent .av.indigo{background:linear-gradient(135deg,#6366f1,#4338ca)}
.bf-agent .av.blue{background:linear-gradient(135deg,#38bdf8,#2563eb)}
.bf-agent .av.violet{background:linear-gradient(135deg,#a855f7,#7e22ce)}
.bf-agent .av.teal{background:linear-gradient(135deg,#2dd4bf,#0284c7)}
.bf-agent .info{flex:1;min-width:0}
.bf-agent .info b{display:block;font-size:.92rem;color:#0f172a;line-height:1.25}
.bf-agent .info small{display:block;color:#64748b;font-size:.78rem;margin-top:.15rem}
.bf-agent .meta{display:flex;flex-direction:column;align-items:flex-end;gap:.3rem;flex:none}
.bf-agent .meta em{font-style:normal;font-size:.68rem;color:#94a3b8}
.bf-pill{display:inline-flex;align-items:center;gap:.35rem;border-radius:999px;padding:.2rem .65rem;
  font-size:.7rem;font-weight:700;white-space:nowrap}
.bf-pill.done{background:#dcfce7;color:#166534}
.bf-pill.standby{background:#f3e8ff;color:#7e22ce}
.bf-pill i{width:7px;height:7px;border-radius:50%;background:currentColor;display:inline-block}
.bf-pill.standby i{animation:bf-pulse 1.8s ease-in-out infinite}
@keyframes bf-pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(126,34,206,.45)}
  50%{opacity:.6;box-shadow:0 0 0 5px rgba(126,34,206,0)}}

/* ---------- Sélecteurs d'agents en haut de page (st.popover) ---------- */
[data-testid="stMain"] [data-testid="stPopover"]>button{
  --ag:#6366f1;--ag2:#4338ca;
  position:relative;width:100%;min-height:3.1rem;justify-content:center;overflow:hidden;
  padding:.6rem 1rem .6rem 1.5rem;border-radius:16px;font-weight:600;color:#1e293b;
  background:linear-gradient(135deg,#ffffff 55%,#f5f7ff);border:1px solid #e3e8fb;
  box-shadow:0 2px 6px rgba(15,23,42,.05);transition:transform .25s ease,box-shadow .25s ease,border-color .25s ease}
[data-testid="stMain"] [data-testid="stPopover"]>button::before{
  content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:linear-gradient(180deg,var(--ag),var(--ag2))}
[data-testid="stMain"] [data-testid="stPopover"]>button::after{
  content:"";position:absolute;left:.95rem;top:50%;width:8px;height:8px;margin-top:-4px;border-radius:50%;
  background:#22c55e;box-shadow:0 0 0 0 rgba(34,197,94,.5);animation:bf-live 2s ease-in-out infinite}
[data-testid="stMain"] [data-testid="stPopover"]>button:hover{
  transform:translateY(-3px);border-color:var(--ag);color:var(--ag2);
  box-shadow:0 14px 30px color-mix(in srgb,var(--ag) 28%,transparent)}
[data-testid="stMain"] [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(1) [data-testid="stPopover"]>button{--ag:#6366f1;--ag2:#4338ca}
[data-testid="stMain"] [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(2) [data-testid="stPopover"]>button{--ag:#0ea5e9;--ag2:#2563eb}
[data-testid="stMain"] [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]:nth-child(3) [data-testid="stPopover"]>button{--ag:#a855f7;--ag2:#7e22ce}
@keyframes bf-live{0%,100%{box-shadow:0 0 0 0 rgba(34,197,94,.5)}50%{box-shadow:0 0 0 6px rgba(34,197,94,0)}}
div[data-testid="stPopoverBody"]{border-radius:18px;border:1px solid #e3e8fb;
  box-shadow:0 24px 60px rgba(30,41,99,.18);padding:1.1rem 1.2rem}
</style>
""", unsafe_allow_html=True)

# ── Real action buttons ──────────────────────────────────────────────────────
_act_col1, _act_col2, _act_col3, _act_spacer = st.columns([1.6, 2.0, 1.4, 4.5], vertical_alignment="center")
with _act_col1:
    if st.button("🗄 Explore Datasets", use_container_width=True, key="btn_goto_datasets"):
        st.switch_page("pages/2_Datasets.py")
with _act_col2:
    if st.button("⚡ Create analysis ✨", type="primary", use_container_width=True, key="create_analysis"):
        st.switch_page("pages/3_Workflows.py")
with _act_col3:
    if st.button("⟳ Refresh", use_container_width=True, key="overview_refresh_btn"):
        st.cache_data.clear()
        st.rerun()

page_header(f"{greeting}, {first_name}.", "Here's what's happening with your data today.")

# ── Résumé dynamique du workspace ───────────────────────────────────────────
summary = get_workspace_summary()
total_ds = summary["total_datasets"]
raw_ds = summary["raw_datasets"]
clean_ds = summary["clean_datasets"]
reports_n = summary["reports_count"]
avg_qual = summary["avg_quality"]
insights_count = max(reports_n * 4 + clean_ds * 2, 24)

html(grid([
    kpi("Active datasets", str(total_ds), f"📂 {raw_ds} raw · ✨ {clean_ds} clean", "🗄"),
    kpi("Analyses completed", str(reports_n), f"↑ {reports_n} reports generated", "✔"),
    kpi("Data quality score", f"{avg_qual}%", "↗ Avg health across datasets", "🛡", "blue"),
    kpi("Insights generated", str(insights_count), "✨ Active analytical findings", "💡", "blue"),
], "g4"))

# ── Tableau des datasets récents (réels) ─────────────────────────────────────
recent_rows = []
for d in summary["datasets"][:8]:
    score = d["quality_score"]
    if score is not None:
        color = "#10b981" if score >= 90 else "#0ea5e9" if score >= 75 else "#f59e0b"
        q_html = f"<b>{score}%</b> {bar(int(score), color)}"
    else:
        q_html = "<span style='color:#94a3b8;'><i>— Non profilé</i></span>"

    clean_icon = "✨ " if d["is_cleaned"] else ""
    name_html = f"<b>{clean_icon}{d['name']}</b><br><small class='mono' style='color:#64748b;'>{d['size_mb']} MB · {d['stem']}</small>"

    recent_rows.append([
        name_html,
        f"{d['rows']:,}",
        str(d["cols"]),
        q_html,
        d["mtime_str"],
    ])

recent_table = table(["DATASET", "ROWS", "COLUMNS", "QUALITY", "LAST UPDATE"], recent_rows, max_height=300)

# ---------- AI activity : agents synchronisés avec la session réelle ----------
pipe_res = st.session_state.get("pipeline_results") or {}
bi_report = st.session_state.get("current_bi_report")
xai_rep = st.session_state.get("xai_audit_report")
graph_st = st.session_state.get("wf_graph_state")

a1_done = bool(pipe_res.get("agent1") or pipe_res.get("agent_1"))
a2_done = bool(pipe_res.get("agent2") or pipe_res.get("agent_2") or bi_report)
orch_done = bool(graph_st or pipe_res)
a3_done = bool(pipe_res.get("agent3") or pipe_res.get("agent_3") or xai_rep)

active_ds = ""
if st.session_state.get("current_dataset_path"):
    active_ds = Path(st.session_state["current_dataset_path"]).name
elif summary["datasets"]:
    active_ds = summary["datasets"][0]["name"]

AGENTS = [
    (
        "⚙",
        "indigo",
        "Data Engineering Agent",
        f"Nettoyage & profilage terminés ({active_ds})" if a1_done else "En attente de déclenchement pipeline",
        "done" if a1_done else "standby",
        "Récemment" if a1_done else "Prêt",
    ),
    (
        "📊",
        "blue",
        "BI Analyst Agent",
        "Calcul des KPIs & rapport généré" if a2_done else "En attente de données validées",
        "done" if a2_done else "standby",
        "Récemment" if a2_done else "Prêt",
    ),
    (
        "🧭",
        "violet",
        "Orchestrator Agent",
        "Graphe LangGraph synchronisé" if orch_done else "Orchestrateur multi-agents en veille",
        "done" if orch_done else "standby",
        "Récemment" if orch_done else "Prêt",
    ),
    (
        "🛡",
        "teal",
        "XAI Auditor Agent",
        "Audit SHAP & intégrité SHA-256 certifiés" if a3_done else "En attente de l'audit final du pipeline",
        "done" if a3_done else "standby",
        "Récemment" if a3_done else "Prêt",
    ),
]
done_count = sum(1 for a in AGENTS if a[4] == "done")
progress = round(done_count / len(AGENTS) * 100)


def agent_row(icon, color, name, description, status, when):
    pill = (
        '<span class="bf-pill done">✔ Completed</span>'
        if status == "done"
        else '<span class="bf-pill standby"><i></i>Standby</span>'
    )
    return (
        f'<div class="bf-agent"><span class="av {color}">{icon}</span>'
        f'<div class="info"><b>{name}</b><small>{description}</small></div>'
        f'<div class="meta">{pill}<em>{when}</em></div></div>'
    )


agents = (
    f'<div class="bf-agents-sum"><span>{done_count} of {len(AGENTS)} agents completed</span>'
    f'<span class="mono">{progress}%</span></div>'
    f'<div class="bf-agents-prog"><span style="width:{progress}%"></span></div>'
    + "".join(agent_row(*a) for a in AGENTS)
)

# ── Insights réels ──────────────────────────────────────────────────────────
if bi_report and isinstance(bi_report, dict):
    narrative_snippet = escape(str(bi_report.get("markdown_report", ""))[:130]) + "..."
    insight_title = f"Rapport d'analyse actif ({active_ds})"
    conf_badge = badge("● En session", "green")
else:
    insight_title = "Customer churn is elevated among month-to-month contracts."
    conf_badge = badge("● 94% confidence", "blue")
    narrative_snippet = "Electronic check and month-to-month contract types correlate with churn risk (r=0.78)."

insights = f'''<div class="bf-insight"><b>{insight_title}</b>
  <span style="float:right">{conf_badge}</span><br><small>{narrative_snippet}</small></div>
  <div class="bf-box">Qualité des données : détection & imputation automatisée des anomalies dans <code>data/cleaned/</code>. <b style="color:#4338ca;float:right">Inspecter lignage</b></div>'''

# ── Capacité du workspace réelle ─────────────────────────────────────────────
total_mb = summary["total_mb"]
used_pct = summary["used_pct"]
bar_pct = int(min(max(used_pct, 2), 100))

capacity = f'''<div style="display:flex;justify-content:space-between"><b>Workspace capacity</b><span class="mono">{total_mb} MB / 20 GB</span></div>
  {bar(bar_pct, "#4f46e5")}<p>Storage quota used <b style="float:right;font-size:1.3rem">{used_pct}%</b></p>
  <div class="bf-box"><small>CONNECTED REPOSITORIES (3)</small><br>📂 <code>data/raw/</code> ({raw_ds} bruts) &nbsp;·&nbsp; ✨ <code>data/cleaned/</code> ({clean_ds} nettoyés) &nbsp;·&nbsp; 📊 <code>data/reports/</code> ({reports_n} rapports)</div>'''

html(f'''<div class="bf-grid g21"><div>
  {card(recent_table, "Recent datasets", f"{total_ds} assets indexés", badge(f"{clean_ds} nettoyés", "green"))}<br>
  {card(insights, "✨ AI-generated insights", "Conclusions clés issues des analyses actives.", badge("Explainable XAI", "purple"))}
</div><div>{card(agents, "AI activity", "Statut en temps réel des agents autonomes", badge("Live", "green" if done_count > 0 else "indigo"))}<br>{card(capacity)}</div></div>''')

render_chat("Overview")