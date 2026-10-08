from components import setup, page_header, btn, html, card, badge

setup("Audit & XAI")
page_header("Audit & Explainability", "Understand how BIFlow generated its results and verify algorithmic decisions.",
            btn("⭳ Export audit log") + btn("🛡 Verify result", True), "Workspace › <b>Audit & XAI</b>")

html(f'''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center;margin-bottom:1rem">🔏
  <div><b style="font-size:1.1rem">Audit run #BF-2026-0284</b> <span class="mono bf-badge gray">SHA-256: 8a4c…e92f</span><br>
  <small>Telco Customer Churn · Completed today at 12:44 · 6 traceable events</small></div>
  <span style="margin-left:auto">{badge("● Verified", "blue")}</span></div>''')

events = [("☁", "Dataset uploaded", "12:40:51", "Telco Customer Churn received and validated", 0),
          ("⛓", "Orchestrator selected workflow", "12:41:04", "Profiling, quality, KPI, insight, and XAI tasks", 0),
          ("🗄", "Data Engineering Agent analyzed quality", "12:42:18", "94% quality score; 2 issues identified", 0),
          ("📊", "BI Analyst calculated KPIs", "12:43:39", "Churn rate = 26.5%; 7,043 customers analyzed", 1),
          ("✨", "AI generated insight", "12:44:12", "Month-to-month contracts linked to higher churn", 0),
          ("✔", "XAI Auditor generated explanation", "12:44:48", "Evidence, confidence, and sources verified", 0)]
tl = "".join(f'<div class="bf-tl{" act" if a else ""}"><i>{i}</i><div style="flex:1"><span class="t">{t}</span><b>{n}</b><br><small>{d}</small></div></div>'
             for i, n, t, d, a in events)
timeline = card(tl, "Audit timeline", "A chronological record of every decision and transformation.", badge("Live Audit Log", "gray"))

box = lambda k, v, r="": f'<div class="bf-box"><small>{k}</small><b style="font-size:1.05rem">{v}</b><span class="mono" style="float:right;font-size:.8rem">{r}</span></div>'
details = card(
    box("AGENT", "🤖 BI Analyst Agent", "model: gpt-4o-analytic-v2") + box("TASK", "Churn analysis")
    + box("INPUT", "Telco Customer Churn", "7,043 rows × 21 cols") + box("OUTPUT", "Churn rate = 26.5%", "<span style='color:#0369a1'>Deterministic match</span>")
    + '''<div class="bf-box" style="background:#dbe7ff"><b style="color:#3730a3">🧠 Explanation</b><p>The BI Analyst Agent counted customers marked “Yes”
      in the Churn field and divided that total by all valid customer records. 1,869 of 7,043 customers churned, producing a rate of 26.53%, rounded to 26.5%.
      No rows were excluded and the calculation was independently verified by the XAI Auditor.</p></div>''',
    "AI Decision Details", "The exact inputs, logic, and output for the selected decision.", badge("● 92% confidence", "blue"))

steps = [("🗄", "Dataset", "v1.4"), ("⇅", "Transformation", "Cleanse"), ("▦", "Analysis", "KPIs"),
         ("⬚", "LLM", "Agentic"), ("💡", "Insight", "Synthesized"), ("🔍", "Explanation", "Verified")]
trace = card('<div style="display:flex;gap:.5rem">' + "".join(
    f'<div class="bf-box" style="flex:1;text-align:center;{"background:#bae6fd" if i == 5 else ""}">{ic}<br><b style="font-size:.75rem">{n}</b><br><small class="mono">{s}</small></div>'
    for i, (ic, n, s) in enumerate(steps)) + '</div>', "Traceability", "Follow the lineage from source data to explanation.")
gov = card('<div class="bf-grid g4">' + "".join(f'<div class="bf-box" style="min-height:110px">✔<br><b>{t}</b></div>' for t in
           ["Source lineage complete", "Calculation reproducible", "Explanation grounded", "No sensitive fields exposed"]) + '</div>',
           "Governance checks", "Controls applied automatically to this result.")
html(f'<div class="bf-grid g12">{timeline}<div>{details}<br>{trace}<br>{gov}</div></div>')