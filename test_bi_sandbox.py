"""Quick verification test for the BI Analyst sandbox engine."""
from analytics.kpi import run_bi_sandboxed_calc
import pandas as pd

df = pd.read_csv("data/raw/telco_churn.csv")

code = """
def compute_insight(df):
    rate = df[df["Churn"] == "Yes"].shape[0] / df.shape[0] * 100
    avg_charges = round(df["MonthlyCharges"].mean(), 2)
    return {"churn_rate_pct": round(rate, 2), "avg_monthly_charges": avg_charges}
"""

result, error = run_bi_sandboxed_calc(code, df)
print("Result :", result)
print("Error  :", error)
assert error is None, f"Sandbox raised an error: {error}"
assert isinstance(result, dict), "Result must be a dict"
assert "churn_rate_pct" in result
print("\n✅ Sandbox OK — test passed!")

