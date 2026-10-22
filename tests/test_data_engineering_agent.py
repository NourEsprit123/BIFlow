import os
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
    assert pd.isna(cleaned.iloc[4])

def test_agent_execution():
    agent = DataEngineeringAgent()
    audit_res = agent.run_audit(TEST_CSV)
    assert "profile" in audit_res
    assert "cleaning_strategy" in audit_res

    clean_res = agent.execute_cleaning(TEST_CSV, preview_mode=True)
    assert clean_res["status"] == "preview"
    assert clean_res["rows_processed"] > 0
