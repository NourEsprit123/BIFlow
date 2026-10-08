from components import setup, page_header, btn, html, kpi, grid, card, table, badge, bar, donut, columns_chart

setup("Data Quality")
page_header("Data Quality", "Monitor, understand, and improve the reliability of Telco Customer Churn.",
            btn("✨ Apply recommended cleaning", True), "Telco Customer Churn › <b>Data Quality</b>")

html(grid([kpi("Quality Score", "94%", "● Excellent data health", "🛡"),
           kpi("Missing Values", "11", "0.16% of total cells", "⚠", "blue", "gray"),
           kpi("Duplicates", "0", "● No duplicates found", "⧉", "blue"),
           kpi("Type Issues", "1", "1 column: TotalCharges", "{}")], "g4"))

dims = [("Completeness", 99.8, "#38bdf8"), ("Validity", 98.6, "#4f46e5"), ("Uniqueness", 100, "#075985"), ("Consistency", 89.4, "#6d28d9")]
dim_html = "".join(f'<div style="margin-bottom:1rem"><div style="display:flex;justify-content:space-between"><span>{n}</span><span class="mono">{v}%</span></div>{bar(v, c)}</div>' for n, v, c in dims)
overview = card(f'<div style="display:flex;gap:2rem;align-items:center">{donut(94, "#4f46e5", size=190)}<div style="flex:1">{dim_html}</div></div>',
                "Quality overview", "Weighted health score across four primary quality dimensions.")
severity = card(columns_chart([20, 100, 18], ["Low", "Medium", "High"], ["#dbeafe", "#38bdf8", "#dbeafe"], 150)
                + f'<div style="display:flex;gap:.4rem;margin-top:1rem">{badge("High · 0", "red")}{badge("Medium · 2", "blue")}{badge("Low · 0", "gray")}</div>',
                "Issues by severity", "2 actionable issues detected.")
html(f'<div class="bf-grid g21">{overview}{severity}</div>')

issues = table(["SEVERITY", "COLUMN", "ISSUE", "DETECTED VALUES", "RECOMMENDATION"], [
    [badge("● Medium", "blue"), "<span class='mono'>TotalCharges</span>", "Incorrect data type", "99.84% numeric-compatible values", "Convert to numeric (<code>Float64</code>) ›"],
    [badge("● Medium", "blue"), "<span class='mono'>TotalCharges</span>", "Empty values", "11 blank entries", "Impute with column median / treat as missing ›"]])
html(card(issues, "Detected issues", "Review each issue and apply the recommended remediation.",
          f'<div>{badge("All · 2")} {badge("High · 0", "gray")} {badge("Medium · 2", "gray")} {badge("Low · 0", "gray")}</div>'))
html("<br>")
html(f'''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center">🪄
  <div style="flex:1"><b style="font-size:1.1rem">BIFlow recommends one safe cleaning rule</b> {badge("AI Profiler")}<br>
  Convert <code>TotalCharges</code> to numeric and treat 11 empty values as missing. Your original dataset will be preserved.</div>
  {btn("Preview changes")} {btn("✨ Apply recommended cleaning", True)}</div>''')