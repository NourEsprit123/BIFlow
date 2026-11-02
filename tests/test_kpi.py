import pandas as pd
import numpy as np
from analytics.kpi import calculate_kpis, recommend_charts


def test_calculate_kpis_empty():
    kpis = calculate_kpis(pd.DataFrame())
    assert len(kpis) == 4
    assert kpis[0]["title"] == "Total Records"
    assert kpis[0]["value"] == "0"


def test_calculate_kpis_numeric():
    df = pd.DataFrame({
        "sales": [100.0, 200.0, 300.0, 400.0, 500.0],
        "profit": [10.0, 25.0, 40.0, 80.0, 120.0],
        "region": ["North", "South", "East", "West", "North"]
    })
    kpis = calculate_kpis(df)
    assert len(kpis) == 4
    assert kpis[0]["value"] == "5"
    assert "sales" in kpis[1]["title"].lower() or "avg" in kpis[1]["title"].lower()


def test_calculate_kpis_target_churn():
    df = pd.DataFrame({
        "CustomerID": [1, 2, 3, 4],
        "MonthlyCharges": [50.0, 70.0, 90.0, 40.0],
        "Churn": ["No", "Yes", "No", "No"]
    })
    kpis = calculate_kpis(df)
    assert len(kpis) == 4
    assert any("Churn" in k["title"] for k in kpis)


def test_recommend_charts():
    df = pd.DataFrame({
        "Department": ["HR", "IT", "Finance", "Sales", "IT", "HR"],
        "Salary": [50000, 80000, 75000, 60000, 85000, 52000],
        "Tenure": [2, 5, 4, 3, 6, 1]
    })
    charts = recommend_charts(df)
    assert len(charts) >= 3
    chart_types = {c["type"] for c in charts}
    assert "bar" in chart_types or "pie" in chart_types or "histogram" in chart_types
