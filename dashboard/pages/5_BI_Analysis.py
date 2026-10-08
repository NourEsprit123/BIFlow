from components import setup, page_header, btn, html, kpi, grid, card, badge, bar, donut, columns_chart, svg_line

setup("BI Analysis")
page_header("Business Intelligence Analysis", "Turn your data into actionable insights.",
            btn("⭳ Export report") + btn("✨ Create workflow", True), "Telco Customer Churn / <b>Analysis</b>")

html(f'''<div class="bf-card" style="background:#eef2ff;display:flex;gap:1rem;align-items:center;margin-bottom:1rem">🗄
  <small style="color:#4338ca"><b>ACTIVE DATASET</b></small> <b>Telco Customer Churn</b> · 7,043 customers · Analysis completed today at 12:46
  <span style="margin-left:auto">{badge("● Results ready", "blue")}</span></div>''')

html(grid([kpi("Customers", "7,043", "Complete population", "👥"), kpi("Churn Rate", "26.5%", "1,869 customers", "👤", "red", "red"),
           kpi("Average Monthly Charges", "$64.76", "Median $70.35", "💵"), kpi("Average Tenure", "32.4 months", "Range 0–72 months", "📅", "blue", "gray")], "g4"))

churn = card(f'''<div style="display:flex;gap:2rem;align-items:center">{donut(26.5, "#4f46e5", size=130)}
  <div style="flex:1"><p>○ Retained <b style="float:right">5,174</b><br><small>73.5%</small></p>
  <p style="color:#4f46e5">● Churned <b style="float:right;color:#0f172a">1,869</b><br><small style="color:#b91c1c">26.5%</small></p></div></div>
  <div class="bf-box" style="margin-top:1rem">Target benchmark: &lt; 20.0% <b style="float:right;color:#b91c1c">+6.5% variance</b></div>''',
             "Churn distribution", "Customer share by churn status")
contract = card(columns_chart([100, 48, 22], ["Month-to-month<br>3,875 users", "One year<br>1,473 users", "Two year<br>1,695 users"],
                              ["#ddd6fe", "#e9d5ff", "#3730a3"], 150)
                + '<div class="bf-box" style="margin-top:2rem">ⓘ Switching customers to 1-year commitments reduces predicted attrition by 73.5%.</div>',
                "Churn by contract type", "Month-to-month is the strongest risk driver", badge("Critical Impact", "red"))
html(f'<div class="bf-grid g12">{churn}{contract}</div>')

html(grid([
    card(columns_chart([30, 50, 85, 95, 80, 45, 25], ["$20", "$35", "$50", "$65", "$80", "$95", "$110"],
                       ["#38bdf8"] * 6 + ["#075985"], 130), "Monthly charges distribution", "Customer frequency across price bands"),
    card(svg_line("M0,70 C40,60 70,35 110,40 C150,45 170,38 200,22 L260,8"), "Customer tenure distribution", "Concentration across lifecycle stages"),
    card(svg_line("M0,75 C50,70 80,45 130,40 C180,35 210,20 260,10"), "Churn trend", "Rolling churn rate across 12 months"),
], "g3"))

def insight(tag, title, text, conf):
    return f'''<div class="bf-card"><span class="bf-badge blue" style="float:right">● {conf}% confidence</span>
      <small style="color:#4338ca"><b>{tag}</b></small><h3 style="font-size:1.1rem;margin:.5rem 0">{title}</h3>
      <p style="color:#64748b;font-size:.85rem">{text}</p>Confidence <b style="float:right">{conf}%</b>{bar(conf, "#075985")}
      <div class="bf-box" style="text-align:center;margin-top:1rem;color:#4338ca">✨ Explain</div></div>'''

html(f'<div style="display:flex;justify-content:space-between"><h2>AI Insights</h2>{badge("3 high-confidence insights")}</div>')
html(grid([
    insight("CONTRACT RISK", "Customers on month-to-month contracts show a higher churn rate.", "Their churn rate is 42.7%, compared with 11.3% for one-year contracts and 2.8% for two-year terms.", 94),
    insight("PRICING PRESSURE", "Customers with higher monthly charges show increased churn risk.", "Churn probability rises markedly above $75 in monthly charges, especially when bundled with fiber optic add-ons.", 89),
    insight("TENURE LOYALTY", "Longer-tenure customers are significantly less likely to churn.", "Customers with tenure over 48 months demonstrate the highest retention stability at &lt;4.2% historical attrition.", 91),
], "g3"))