from datetime import datetime
from html import escape

import streamlit as st



from components import setup, page_header, btn, html, kpi, grid, card, table, badge, bar

user = st.session_state.get("authenticated_user")
if user is None:
    st.switch_page("app.py")  # personne de connecté : retour à l'accueil
    st.stop()

first_name = escape(user["full_name"].split()[0]) if user["full_name"].strip() else "there"
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

page_header(f"{greeting}, {first_name}.", "Here's what's happening with your data today.",
            btn("☰ Filter View") + btn("+ Create analysis ✨", True))

html(grid([
    kpi("Active datasets", "12", "↑ +2 this month", "🗄"),
    kpi("Analyses completed", "48", "↑ +12 this week", "✔"),
    kpi("Data quality score", "94%", "↗ +3.2% improvement", "🛡", "blue"),
    kpi("Insights generated", "127", "✨ 18 new insights", "💡", "blue"),
], "g4"))

datasets = table(["DATASET", "ROWS", "COLUMNS", "QUALITY", "LAST UPDATE"], [
    ["<b>Telco Customer Churn</b><small class='mono'>churn_analysis_v2.parquet</small>", "7,043", "21", f"{bar(94)} 94%", "Today"],
    ["<b>Sales Performance</b><small class='mono'>q3_sales_agg.csv</small>", "25,430", "18", f"{bar(91)} 91%", "Yesterday"],
    ["<b>Customer Transactions</b><small class='mono'>ledger_sync_stream</small>", "54,820", "27", f"{bar(87, '#5b21b6')} 87%", "2 days ago"],
])

# ---------- AI activity : agents ----------
AGENTS = [
    # (icône, couleur, nom, description, statut, heure)
    ("⚙", "indigo", "Data Engineering Agent", "Normalized 7,043 clean records", "done", "2 min ago"),
    ("📊", "blue", "BI Analyst Agent", "Calculated KPIs & churn drivers", "done", "5 min ago"),
    ("🧭", "violet", "Orchestrator Agent", "Planned 3-stage execution", "done", "8 min ago"),
    ("🛡", "teal", "XAI Auditor Agent", "Ready to verify data lineage", "standby", "Waiting"),
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

insights = f'''<div class="bf-insight"><b>Customer churn is increasing among month-to-month contracts.</b>
  <span style="float:right">{badge("● 94% confidence", "blue")}</span><br><small>Correlation factor r=0.78 identified across seni...</small></div>
  <div class="bf-box">Payment gateway latency spiked in EU-West-1 during peak mor... <b style="color:#4338ca;float:right">Inspect lineage</b></div>'''
capacity = f'''<div style="display:flex;justify-content:space-between"><b>Workspace capacity</b><span class="mono">4.8 / 20 GB</span></div>
  {bar(24, "#4f46e5")}<p>Storage quota used <b style="float:right;font-size:1.3rem">24%</b></p>
  <div class="bf-box"><small>CONNECTED SOURCES (3)</small><br>🗄 PostgreSQL &nbsp; 📄 CSV Uploads &nbsp; ❄ Snowflake</div>'''

html(f'''<div class="bf-grid g21"><div>
  {card(datasets, "Recent datasets", "", badge("3 active"))}<br>
  {card(insights, "✨ AI-generated insights", "Key findings surfaced across active analyses.", badge("Explainable XAI", "purple"))}
</div><div>{card(agents, "AI activity", "Latest autonomous agent runs", badge("Live", "green"))}<br>{card(capacity)}</div></div>''')