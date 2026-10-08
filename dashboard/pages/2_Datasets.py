from components import setup, page_header, btn, html, card, table, badge, bar

setup("Datasets")
page_header("Datasets", "Manage, inspect, and streamline your business intelligence assets and data ingest pipelines.",
            btn("⟳ Refresh") + btn("☁ + Upload dataset", True), "Workspace › <b>Datasets</b>")

def fmt(t): return f'<span class="mono" style="color:#166534;background:#dcfce7;padding:.1rem .4rem;border-radius:6px">{t}</span>'
rows = [
    ("Telco Customer Churn", "Added by Sarah Chen · Production", "CSV", "7,043", "21", 94, "#10b981", "Today, 12:43", badge("● Ready", "green")),
    ("Sales Performance", "Added by Alex Mercer · Q3 Regional Sync", "XLSX", "25,430", "18", 91, "#10b981", "Yesterday", badge("● Ready", "green")),
    ("Customer Transactions", "3 null schema collisions detected", "CSV", "54,820", "27", 87, "#f59e0b", "2 days ago", badge("● Needs attention", "amber")),
    ("Marketing Campaigns", "Automated ingest from Ads Manager", "CSV", "12,904", "16", None, "", "Not analyzed", badge("● Processing", "blue")),
    ("Product Catalog & Inventory", "PostgreSQL · Multi-region read replica", "SQL", "108,200", "34", 96, "#10b981", "3 days ago", badge("● Ready", "green")),
]
trs = [[f"<b>{n}</b><small>{d}</small>", fmt(f), r, c, (f"<b>{q}%</b> {bar(q, col)}" if q else "<i>— Auditing</i>"), la, s]
       for n, d, f, r, c, q, col, la, s in rows]

filters = "".join(f'<span class="bf-chip{" on" if i == 0 else ""}">{t}</span>' for i, t in
                  enumerate(["All 12", "● Ready 9", "● Needs attention 2", "● Processing 1"]))
html(card(f'<div style="display:flex;gap:1rem;align-items:center"><div class="bf-search" style="flex:.7">🔍 Search datasets by title, tag, or owner<span>⌘ F</span></div><div>{filters}</div></div>'))
html("<br>")
html(card(table(["DATASET", "FORMAT", "ROWS", "COLUMNS", "QUALITY SCORE", "LAST ANALYSIS", "STATUS"], trs)
          + '<div style="display:flex;justify-content:space-between;margin-top:1rem;color:#475569">Showing <b>5</b> of <b>12</b> datasets'
            '<span><span class="bf-chip">Previous</span><span class="bf-chip on">1</span><span class="bf-chip">2</span><span class="bf-chip">Next</span></span></div>'))
html("<br>")
storage = f'''<div class="ch"><div><h3>Workspace storage</h3><div class="subt">Real-time analytical cache & blob storage limit</div></div>{badge("Healthy", "green")}</div>
  <div style="font-size:2.2rem;font-weight:700">4.8 GB <small style="font-size:1rem;color:#64748b">/ 20 GB</small>
  <span style="float:right;font-size:.9rem;color:#4338ca">24% capacity used</span></div>{bar(24, "#4f46e5")}
  <p style="color:#64748b;font-size:.85rem">15.2 GB remaining <b style="float:right;color:#0f172a">Manage quota →</b></p>'''
sources = f'''<div class="ch"><div><h3>Connected sources</h3><div class="subt">Active connections & streaming endpoints</div></div>{btn("+ Add source")}</div>
  <div style="font-size:2.2rem;font-weight:700">3 active {badge("● All connectors synced", "blue")}</div>
  <div class="bf-box" style="margin-top:.8rem">📄 CSV uploads · PostgreSQL · Google Sheets · Snow...</div>'''
html(f'<div class="bf-grid g2">{card(storage)}{card(sources)}</div>')