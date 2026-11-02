from agents.bi_analyst_agent import BIAnalystAgent

user_raw = '''json { "kpis": [ { "title": "Churn Rate", "value": "26.55%", "subtitle": "Percentage of customers who left the service during the observation period." }, { "title": "Average Monthly Charges", "value": "$64.76", "subtitle": "Mean monthly spend across all customers, indicating overall revenue per user." }, { "title": "Fiber-Optic Internet Adoption", "value": "43.96%", "subtitle": "Share of customers subscribed to Fiber-optic Internet, the highest-speed option." }, { "title": "Month-to-Month Contract Share", "value": "55.04%", "subtitle": "Proportion of customers on the most flexible (and most churn-prone) contract type." } ], "recommended_charts": [ { "title": "Churn Distribution", "type": "pie", "column_x": "Churn", "column_y": null }, { "title": "Internet Service Mix", "type": "bar", "column_x": "InternetService", "column_y": "count" }, { "title": "Monthly Charges Distribution", "type": "histogram", "column_x": "MonthlyCharges", "column_y": null }, { "title": "Tenure by Churn", "type": "box", "column_x": "Churn", "column_y": "tenure" }, { "title": "Monthly vs Total Charges", "type": "scatter", "column_x": "MonthlyCharges", "column_y": "TotalCharges" } ] }'''

agent = BIAnalystAgent()
report, cfg = agent.parse_response(user_raw)

print("Parsed KPIs count:", len(cfg.get("kpis", [])))
print("Parsed Charts count:", len(cfg.get("recommended_charts", [])))
print("Report starts with '# 📊 Executive Business Intelligence Report'?", report.startswith("# 📊 Executive Business Intelligence Report"))
assert len(cfg["kpis"]) == 4
assert len(cfg["recommended_charts"]) == 5
assert report.startswith("# 📊 Executive Business Intelligence Report")
print("VERIFICATION 100% OK!")

