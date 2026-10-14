import os
import json
import pytest
import pandas as pd
from analytics.profiler import profile_dataset
from analytics.data_quality import calculate_health_scores
from analytics.cleaning import clean_dirty_numeric_series, impute_missing_values
from agents.data_engineering_agent import DataEngineeringAgent

TEST_CSV = "data/raw/telco_churn.csv"

def test_profiler_and_quality():
    assert os.path.exists(TEST_CSV)
    profile = profile_dataset(TEST_CSV)
    assert profile["rows"] > 0
    assert profile["columns"] > 0
    assert "TotalCharges" in profile["column_names"]

    df = pd.read_csv(TEST_CSV)
    health = calculate_health_scores(df)
    assert health["overall_health_score"] > 50
    assert "TotalCharges" in health["type_issues"]

def test_waterfall_numeric_cleaning():
    dirty_series = pd.Series(["$1,000", " 1500.5 ", "one thousand", "2.5k", "invalid_str"])
    cleaned = clean_dirty_numeric_series(dirty_series)
    assert cleaned.iloc[0] == 1000.0
    assert cleaned.iloc[1] == 1500.5
    assert cleaned.iloc[2] == 1000.0
    assert cleaned.iloc[3] == 2500.0
    assert pd.isna(cleaned.iloc[4])


def test_dirty_numeric_recommendation_is_applied_without_llm(tmp_path):
    source = tmp_path / "dirty_revenue.csv"
    pd.DataFrame({
        "Revenue": [
            "$1,200.50", "850", "1.5k", "one thousand", "$2,300.00",
            "banana", "$3,750.50", "2.1k", "$980.00", "ERROR_404",
            "$1,850.00", "five hundred",
        ]
    }).to_csv(source, index=False)

    class NoopLLM:
        def generate_json(self, *args, **kwargs):
            return {}

    agent = DataEngineeringAgent(llm_client=NoopLLM())
    audit = agent.run_audit(str(source))
    assert "Revenue" in audit["health"]["type_issues"]
    assert "Revenue" in audit["cleaning_strategy"]["numeric_waterfall_columns"]

    result = agent.execute_cleaning(
        str(source), strategy=audit["cleaning_strategy"], preview_mode=False
    )
    cleaned = pd.read_csv(result["cleaned_file_path"])
    assert cleaned["Revenue"].notna().sum() == 10
    assert cleaned.loc[2, "Revenue"] == 1500
    assert cleaned.loc[3, "Revenue"] == 1000
    assert pd.isna(cleaned.loc[5, "Revenue"])


def test_date_imputation_keeps_parquet_column_consistent(tmp_path, monkeypatch):
    source = tmp_path / "signup_dates.csv"
    dates = pd.date_range("2025-01-01", periods=10).strftime("%Y-%m-%d").tolist()
    dates[2] = ""
    dates[7] = ""
    pd.DataFrame({"SignupDate": dates}).to_csv(source, index=False)
    monkeypatch.chdir(tmp_path)

    class NoopLLM:
        def generate_json(self, *args, **kwargs):
            return {}

    agent = DataEngineeringAgent(llm_client=NoopLLM())
    audit = agent.run_audit(str(source))
    assert audit["cleaning_strategy"]["imputation_plan"]["SignupDate"]["strategy"] == "mode"

    result = agent.execute_cleaning(
        str(source), strategy=audit["cleaning_strategy"], preview_mode=False
    )
    processed_path = os.path.join(
        "data", "processed", "signup_dates_processed.parquet"
    )
    processed = pd.read_parquet(processed_path)

    assert result["status"] == "success"
    assert pd.api.types.is_datetime64_any_dtype(processed["SignupDate"])
    assert processed["SignupDate"].notna().all()


def test_cleaning_loads_latest_dataset_to_postgres_when_configured(tmp_path, monkeypatch):
    source = tmp_path / "sales report.csv"
    pd.DataFrame({"Revenue": [10, 20, 30]}).to_csv(source, index=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost/biflow",
    )
    monkeypatch.setenv("POSTGRES_SCHEMA", "analytics")
    load_calls = {}

    def fake_load(dataframe, database_url, table_name, schema):
        load_calls.update({
            "rows": len(dataframe),
            "database_url": database_url,
            "table_name": table_name,
            "schema": schema,
        })
        return {
            "status": "loaded",
            "schema": schema,
            "table": table_name,
            "rows_loaded": len(dataframe),
        }

    monkeypatch.setattr(
        "agents.data_engineering_agent.load_dataframe_to_postgres", fake_load
    )
    agent = DataEngineeringAgent(llm_client=object())
    result = agent.execute_cleaning(
        str(source),
        strategy={
            "recommendation_summary": "No changes",
            "numeric_waterfall_columns": [],
            "datetime_columns": [],
            "boolean_columns": [],
            "imputation_plan": {},
            "outlier_columns": [],
        },
        preview_mode=False,
    )

    assert load_calls["rows"] == 3
    assert load_calls["table_name"] == "sales_report"
    assert load_calls["schema"] == "analytics"
    assert result["database_load"]["status"] == "loaded"


def test_agent_execution():
    agent = DataEngineeringAgent()
    audit_res = agent.run_audit(TEST_CSV)
    assert "profile" in audit_res
    assert "cleaning_strategy" in audit_res

    clean_res = agent.execute_cleaning(TEST_CSV, preview_mode=True)
    assert clean_res["status"] == "preview"
    assert clean_res["rows_processed"] > 0


def test_cleaning_only_applies_data_quality_recommendations(tmp_path, monkeypatch):
    df = pd.DataFrame({
        "Revenue": [f"${i * 100}" for i in range(1, 13)] + ["not available"],
        "CustomerName": [f"Customer {i}" for i in range(13)],
        "Notes": ["ok"] * 12 + ["?"],
        "Segment": ["retail"] * 13,
        "Score": list(range(1, 13)) + [10000],
        "DateText": pd.date_range("2026-01-01", periods=13).strftime("%Y-%m-%d"),
        "ActiveText": ["Yes", "No"] * 6 + ["Yes"],
    })
    source = tmp_path / "recommendations.csv"
    df.to_csv(source, index=False)
    monkeypatch.chdir(tmp_path)

    strategy = {
        "numeric_waterfall_columns": ["Revenue", "CustomerName"],
        "datetime_columns": ["DateText", "CustomerName"],
        "boolean_columns": ["ActiveText", "CustomerName"],
        "imputation_plan": {
            "Notes": {"strategy": "mode"},
            "CustomerName": {"strategy": "mode"},
        },
        "synonym_mappings": {"Segment": {"retail": "RETAIL"}},
        "outlier_columns": ["Score", "Revenue"],
    }
    class NoopLLM:
        def generate_json(self, *args, **kwargs):
            return {}

    result = DataEngineeringAgent(llm_client=NoopLLM()).execute_cleaning(
        str(source), strategy=strategy, preview_mode=False
    )
    cleaned = pd.read_csv(result["cleaned_file_path"])
    with open(result["audit_log_path"], encoding="utf-8") as audit_file:
        actions = {
            item["action"]
            for item in json.load(audit_file)["applied_transformations"]
        }

    assert pd.api.types.is_numeric_dtype(cleaned["Revenue"])
    assert pd.isna(cleaned.loc[12, "Revenue"])
    assert cleaned["CustomerName"].equals(df["CustomerName"])
    assert pd.to_datetime(cleaned["DateText"]).equals(pd.Series(pd.date_range("2026-01-01", periods=13)))
    assert set(cleaned["ActiveText"].astype(str)) == {"True", "False"}
    assert "datetime_conversion" in actions
    assert "boolean_conversion" in actions
    assert cleaned.loc[12, "Notes"] == "ok"
    assert cleaned["Segment"].equals(df["Segment"])
    score_info = calculate_health_scores(df)["outlier_info"]["Score"]
    assert cleaned["Score"].max() == score_info["upper_bound"]
