import os
from pathlib import Path

import pandas as pd
from analytics.profiler import profile_dataset
from analytics.data_quality import calculate_health_scores
from agents.data_engineering_agent import DataEngineeringAgent

TEST_CSV = "data/raw/telco_churn.csv"


class FallbackLLM:
    def generate_json(self, prompt, system_prompt=None):
        return {}


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

def test_agent_audit_handoff(tmp_path, monkeypatch):
    source_file = Path(TEST_CSV).resolve()
    monkeypatch.chdir(tmp_path)

    agent = DataEngineeringAgent(llm_client=FallbackLLM())
    audit_res = agent.run_audit(str(source_file))
    assert "profile" in audit_res
    assert "cleaning_strategy" in audit_res
    report = audit_res["profiling_report"]
    assert report["dataset_ref"]["file_path"] == str(source_file)
    assert "column_profiles" in report
    assert "imputation_plan" in report
    assert "etl_hints" in report
    assert "recommended_cleaning_order" in report
    assert Path(audit_res["report_path"]).is_file()
