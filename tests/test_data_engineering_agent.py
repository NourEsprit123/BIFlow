import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
from analytics.profiler import profile_dataset
from analytics.data_quality import calculate_health_scores
from agents.data_engineering_agent import DataEngineeringAgent
from agents.llm_client import LLMClient
from dataCleaningTools.agent1_adapter import parse_profiling_report

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
    assert report["metadata"]["llm_status"] == "fallback"
    assert report["metadata"]["llm_driven"] is False
    assert Path(audit_res["report_path"]).is_file()


def test_agent_profiles_boolean_columns_as_categorical():
    df = pd.DataFrame(
        {"subscribed": pd.Series([True, False, True, pd.NA], dtype="boolean")}
    )
    agent = DataEngineeringAgent(llm_client=FallbackLLM())
    evidence = agent._build_column_evidence(
        df,
        {"column_roles": {"subscribed": "boolean"}},
        calculate_health_scores(df),
    )["subscribed"]

    assert evidence["numeric_stats"] == {}
    assert set(evidence["unique_values"]) == {"True", "False"}
    assert evidence["value_counts"] == {"True": 2, "False": 1}


def test_llm_can_request_and_generate_a_sandboxed_check(tmp_path, monkeypatch):
    source_file = tmp_path / "sample.csv"
    pd.DataFrame({"value": [1, 2, 3]}).to_csv(source_file, index=False)
    monkeypatch.chdir(tmp_path)
    sandbox_calls = []

    class CheckGeneratingLLM:
        provider = "test"
        model_name = "test-model"

        def generate_json(self, prompt, system_prompt=None):
            if system_prompt:
                return {
                    "column_reasoning": {
                        "value": {
                            "severity": "LOW",
                            "agent_reasoning": "A specialized validation is useful.",
                            "needs_custom_check": True,
                            "custom_check_description": "Check values are positive.",
                        }
                    },
                    "agent_summary": "Profile complete.",
                }
            return {
                "code": (
                    "def custom_check(series):\n"
                    "    return {'passed': bool((series > 0).all()), "
                    "'metric': int((series > 0).sum()), 'details': 'positive values'}"
                )
            }

    def run_check(code, series, timeout_sec):
        sandbox_calls.append((code, series.tolist(), timeout_sec))
        return {
            "passed": True,
            "metric": 3,
            "details": "All values are positive.",
            "error": None,
            "backend": "docker",
        }

    monkeypatch.setattr(
        "agents.data_engineering_agent.run_sandboxed_check", run_check
    )
    result = DataEngineeringAgent(llm_client=CheckGeneratingLLM()).run_audit(
        str(source_file)
    )

    profile = result["profiling_report"]["column_profiles"]["value"]
    assert result["profiling_report"]["metadata"]["llm_status"] == "llm"
    assert result["profiling_report"]["metadata"]["llm_driven"] is True
    assert profile["sandbox_triggered"] is True
    assert profile["sandbox_result"]["passed"] is True
    assert sandbox_calls[0][1] == [1, 2, 3]
    assert sandbox_calls[0][2] == 8
    handoff = parse_profiling_report(result["profiling_report"])
    assert handoff.metadata.llm_provider == "test"
    assert handoff.metadata.llm_status == "llm"
    assert handoff.metadata.llm_driven is True


def test_ollama_transport_errors_are_not_returned_as_successful_empty_json(
    monkeypatch,
):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = LLMClient()

    def fail_request(*args, **kwargs):
        raise requests.ConnectionError("Ollama unavailable")

    monkeypatch.setattr("agents.llm_client.requests.post", fail_request)

    with pytest.raises(RuntimeError, match="Ollama request failed"):
        client.generate_json("profile dataset")


def test_gemini_client_uses_configured_genai_sdk_and_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-gemini-model")
    calls = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(text='{"column_reasoning": {}}')

    def create_client(*, api_key):
        calls["api_key"] = api_key
        return SimpleNamespace(models=FakeModels())

    from google import genai

    monkeypatch.setattr(genai, "Client", create_client)
    client = LLMClient()

    result = client.generate_json("analyze", "system")

    assert result == {"column_reasoning": {}}
    assert calls == {
        "api_key": "test-key",
        "model": "test-gemini-model",
        "contents": "system\n\nanalyze",
    }
