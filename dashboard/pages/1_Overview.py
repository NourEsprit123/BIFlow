from components import setup, page_header, btn, html, kpi, grid, card, table, badge, bar

setup("Overview")
page_header("Good morning, Sarah.", "Here's what's happening with your data today.",
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
agents = "".join(f'<div class="bf-insight"><b>{n}</b><br><small>{d}</small> <span style="float:right">{s}</span></div>' for n, d, s in [
    ("Data Engineering...", "Normalized 7,043 clea...", "✔"), ("BI Analyst Agent", "Calculated KPIs & chu...", "✔"),
    ("Orchestrator Agent", "Planned 3-stage exec...", "✔"), ("XAI Auditor ...", "Verified lineag...", badge("Standby", "purple"))])
insights = f'''<div class="bf-insight"><b>Customer churn is increasing among month-to-month contracts.</b>
  <span style="float:right">{badge("● 94% confidence", "blue")}</span><br><small>Correlation factor r=0.78 identified across seni...</small></div>
  <div class="bf-box">Payment gateway latency spiked in EU-West-1 during peak mor... <b style="color:#4338ca;float:right">Inspect lineage</b></div>'''
capacity = f'''<div style="display:flex;justify-content:space-between"><b>Workspace capacity</b><span class="mono">4.8 / 20 GB</span></div>
  {bar(24, "#4f46e5")}<p>Storage quota used <b style="float:right;font-size:1.3rem">24%</b></p>
  <div class="bf-box"><small>CONNECTED SOURCES (3)</small><br>🗄 PostgreSQL &nbsp; 📄 CSV Uploads &nbsp; ❄ Snowflake</div>'''

html(f'''<div class="bf-grid g21"><div>
  {card(datasets, "Recent datasets", "", badge("3 active"))}<br>
  {card(insights, "✨ AI-generated insights", "Key findings surfaced across active analyses.", badge("Explainable XAI", "purple"))}
</div><div>{card(agents, "AI activity", "Latest autonomous agent runs")}<br>{card(capacity)}</div></div>''')