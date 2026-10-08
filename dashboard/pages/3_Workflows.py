from components import setup, page_header, btn, html, badge

setup("Workflows")
page_header("Create Analysis Workflow", "Configure autonomous multi-agent pipeline tasks and intelligence parameters for your dataset.",
            badge("● Draft workflow", "gray"))

html('''<div class="bf-card" style="display:flex;gap:2rem;align-items:center;margin-bottom:1rem">
  <b style="color:#4338ca">✔ Dataset</b> › <b>② Tasks</b> › <span style="color:#64748b">③ Preferences</span>
  <span class="mono" style="margin-left:auto;font-size:.8rem">⏱ Estimated runtime: <b>2-4 min</b></span></div>''')

tasks = [("Data Profiling", "Understand structure, data distributions, and column cardinality", "Core Agent", "~30 sec", 1),
         ("Data Quality", "Detect missing, invalid, or duplicate records & anomalies", "Auditor", "~45 sec", 1),
         ("Data Cleaning", "Standardize categorical values and impute sparse metrics", "ETL Agent", "Optional", 0),
         ("KPI Analysis", "Calculate enterprise churn velocity, revenue risk, and LTV", "BI Engine", "~40 sec", 1),
         ("Trend Analysis", "Reveal movement and temporal churn shifts across rolling cohorts", "Temporal", "Optional", 0),
         ("Anomaly Detection", "Surface statistical outliers and abrupt churn pattern spikes", "ML Detector", "Optional", 0),
         ("Segmentation", "Discover meaningful customer clusters based on service behavior", "Clustering", "Optional", 0),
         ("AI Insights", "Generate actionable natural language business findings and trends", "LLM Analyst", "~50 sec", 1),
         ("XAI / Audit", "Explain and trace every mathematical calculation and heuristic", "Transparency", "~30 sec", 1)]
cards = "".join(f'''<div class="bf-task{" on" if on else ""}"><span class="chk"></span><span>⚙</span><h4>{t}</h4><p>{d}</p>
  <span class="bf-badge gray mono">{a}</span> <small>{r}</small></div>''' for t, d, a, r, on in tasks)

def section(n, title, sub, body):
    return f'''<div style="display:grid;grid-template-columns:1fr 3fr;gap:1.5rem;margin-bottom:1.5rem">
      <div><b style="background:#4338ca;color:#fff;border-radius:50%;padding:.1rem .5rem">{n}</b> <b>{title}</b><br><small style="color:#64748b">{sub}</small></div>
      <div>{body}</div></div>'''

dataset = '''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center">🗄
  <div><b>Telco Customer Churn</b> <span class="bf-badge blue">CSV Data Source</span><br><small>7,043 rows · 21 columns · <b style="color:#4338ca">Quality 94%</b></small></div>
  <span style="margin-left:auto"><span class="bf-badge">Selected</span> <b style="color:#4338ca">Change ⇄</b></span></div>'''
pref = lambda t, d, r: f'<div class="bf-card" style="margin-bottom:.7rem;display:flex;justify-content:space-between"><div><b>{t}</b><br><small>{d}</small></div>{r}</div>'
prefs = (pref("Execution priority", "Standard balances speed and autonomous compute cluster usage.", btn("Standard") + btn("Fast"))
         + pref("AI explanation", "Explain step-by-step how each business insight and metric was generated.", badge("ENABLED ●"))
         + pref("Generate recommendations", "Add prescriptive strategic playbooks and actions to key findings.", badge("ENABLED ●")))

html(section(1, "Select dataset", "Choose your data source", dataset))
html(section(2, "Analysis tasks", "5 of 9 selected", f'<div class="bf-grid g2">{cards}</div>'))
html(section(3, "Preferences", "Configure this run", prefs))
html(f'''<div class="bf-card" style="display:flex;gap:1rem;align-items:center">{badge("5 tasks")} Telco Customer Churn · Explainability ON
  <span style="margin-left:auto">Save as Template &nbsp; {btn("▷ Run BIFlow Pipeline", True)}</span></div>''')