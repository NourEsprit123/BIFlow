from components import setup, page_header, btn, html, kpi, grid, card, table, badge, svg_line

setup("Agent Operations")
page_header("Agent Health & Performance", "Real-time telemetry, resource metrics, and operational health of BIFlow's multi-agent system.",
            badge("● ACTIVE CLUSTER") + btn("🕒 Last 24 Hours") + btn("● Auto-refresh: 15s") + btn("⟳ Restart Agent Pool") + btn("⭳ Export Telemetry Log", True))

html(grid([kpi("OVERALL SYSTEM HEALTH", "99.94%", "✔ All 4 agents operational · Target 99.90%", "♥"),
           kpi("AVERAGE RESPONSE TIME", "342 ms", "vs. 370ms p95 baseline · p50 198ms · p99 610ms", "⏱"),
           kpi("TASKS COMPLETED (24H)", "1,428 runs", "0 fatal exceptions · 3 auto-recovered", "✔"),
           kpi("COMPUTE & TOKEN USAGE", "4.2k tokens/task", "Memory: 1.8 GB / 8 GB (22.5%)", "▤")], "g4"))

def agent(name, ver, role, rows):
    r = "".join(f'<div style="display:flex;justify-content:space-between;background:#f8fafc;padding:.4rem .6rem;margin-bottom:.2rem;border-radius:6px;font-size:.82rem"><span>{k}</span><b>{v}</b></div>' for k, v in rows)
    return card(f'<span class="bf-badge blue" style="float:right">● Online</span><b style="font-size:1.1rem">{name}</b><br><small>{ver}</small>'
                f'<div class="bf-box" style="margin:.6rem 0"><b style="font-size:.78rem;color:#3730a3">{role}</b></div>{r}'
                f'{svg_line("M0,60 C30,40 50,70 80,50 C110,30 130,60 160,20 L200,50", h=70, w=200)}')

html('<h2>⚛ Autonomous Core Agents <small class="mono" style="float:right;font-size:.8rem;font-weight:400">Cluster ID: cluster-biflow-prod-us-east-1</small></h2>')
html(grid([
    agent("Orchestrator", "v2.4.1", "Coordination & Task Management", [("Latency", "118 ms"), ("Tasks Routed", "1,428 (100%)"), ("Errors Handled", "0 crit · 2 retries"), ("Memory / CPU", "280 MB / 4.2%")]),
    agent("Data Engineering", "v2.3.0", "Data Quality & ETL", [("Latency", "412 ms"), ("Datasets Active", "12 (7,043 rows)"), ("Schema Self-Heal", "1 non-fatal"), ("Memory / CPU", "640 MB / 18.4%")]),
    agent("BI Analyst", "v2.4.0", "KPIs & Statistical Insights", [("Latency", "520 ms"), ("Insights Generated", "127 verified"), ("Errors Handled", "0 exceptions"), ("Memory / CPU", "512 MB / 12.1%")]),
    agent("XAI / Auditor", "v2.4.2", "Explanation & Lineage Traceability", [("Latency", "318 ms"), ("Audited Decisions", "84 verified"), ("Hallucinations", "0 flagged"), ("Memory / CPU", "390 MB / 8.6%")]),
], "g4"))

ms = lambda v: f"<b style='color:#0369a1'>{v} ms</b>"
lat = table(["SOURCE NODE", "TARGET NODE", "TRANSPORT", "LATENCY", "THROUGHPUT"], [
    ["● Orchestrator", "Data Engineering", "<code>gRPC / Unix</code>", ms(42), "1,428 msg/day"],
    ["● Data Engineering", "BI Analyst", "<code>Arrow Memory</code>", ms(65), "12.4 MB/s bulk"],
    ["● BI Analyst", "XAI Auditor", "<code>Protobuf IPC</code>", ms(58), "420 msg/day"],
    ["● XAI Auditor", "Results Bus", "<code>ZeroMQ Stream</code>", ms(24), "1,428 msg/day"]])
lat += '<p class="mono" style="font-size:.8rem">Active Pipeline: Telco Customer Churn Pipeline (Run ID: #BF-2026-0284) <b style="float:right">Total Cycle: 942 ms</b></p>'

logs = [("12:44:48", "XAI Auditor", "Explanation trace complete for run #BF-2026-0284<br>Execution: 318ms · SHAP Convergence 99.4%", "Success"),
        ("12:44:12", "BI Analyst", "Generated 3 high-confidence insights on Telco Customer Churn<br>Execution: 490ms · Auto-validated", "Success"),
        ("12:43:39", "BI Analyst", "KPI calculation completed (Churn rate 26.5%)<br>Execution: 210ms · Cache hit", "Success"),
        ("12:42:18", "Data Engineering", "Profiling completed (94% quality, 11 missing values flagged)", "Handled")]
tele = "".join(f'<div class="bf-box"><span class="mono" style="font-size:.78rem">{t} [{a}]</span> <span class="bf-badge gray" style="float:right">{s}</span><br>{m}</div>' for t, a, m, s in logs)
html(f'''<div class="bf-grid g12">{card(lat, "Agent Inter-Communication & Latency Matrix", "Bus transport telemetry across directed execution graph links", badge("● Zero Packet Loss"))}
{card(tele, "Live Operational Telemetry", "Event stream, audits & self-healing triggers", badge("STREAMING", "gray"))}</div>''')