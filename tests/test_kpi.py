import os

import pandas as pd
import pytest

from agents.bi_analyst_agent import BIAnalystAgent
from agents.llm_client import LLMRateLimitError
from analytics.kpi import calculate_kpis


class StubLLMClient:
    provider = "test"

    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_json(self, prompt, system_prompt=None, max_output_tokens=None):
        self.calls.append((prompt, system_prompt, max_output_tokens))
        return self.response


def insight(source_columns=("revenue", "region")):
    return {
        "title": "Revenue differs by region",
        "finding": "Average revenue differs between the represented regions.",
        "evidence": "The aggregate averages are 20 and 40.",
        "recommendation": "Review regional performance and underlying business context.",
        "confidence": 82,
        "source_columns": list(source_columns),
    }


def test_calculate_kpis_returns_aggregate_dataset_metrics():
    frame = pd.DataFrame({
        "revenue": [10.0, 30.0, 50.0, None],
        "region": ["North", "South", "North", "South"],
    })

    result = calculate_kpis(frame)

    assert result["record_count"] == 4
    assert result["field_count"] == 2
    assert result["missing_cells"] == 1
    assert result["missing_percentage"] == 12.5
    assert result["duplicate_rows"] == 0
    assert result["numeric_metrics"]["revenue"]["mean"] == 30
    assert result["categorical_distributions"]["region"][0]["count"] == 2
    comparison = result["group_comparisons"]["revenue by region"]
    assert {row["category"]: row["mean"] for row in comparison} == {
        "North": 30.0,
        "South": 30.0,
    }


def test_bi_analyst_uses_aggregates_and_validates_llm_insights(tmp_path):
    source = tmp_path / "sales.csv"
    pd.DataFrame({
        "revenue": [10.0, 30.0, 50.0, 70.0],
        "region": ["North", "South", "North", "South"],
        "comment": ["PRIVATE ROW VALUE"] * 4,
    }).to_csv(source, index=False)
    llm = StubLLMClient({"insights": [insight() for _ in range(3)]})

    result = BIAnalystAgent(llm_client=llm).analyze(str(source))

    assert result["status"] == "success"
    assert result["dataset"] == "sales.csv"
    assert len(result["insights"]) == 3
    assert result["kpis"]["numeric_metrics"]["revenue"]["mean"] == 40
    prompt, system_prompt, max_output_tokens = llm.calls[0]
    assert "PRIVATE ROW VALUE" not in prompt
    assert "aggregate statistics only" in system_prompt
    assert max_output_tokens == 700


def test_bi_analyst_uses_deterministic_insights_when_llm_quota_is_reached(tmp_path):
    source = tmp_path / "sales.csv"
    pd.DataFrame({
        "revenue": [10.0, 30.0, 50.0],
        "region": ["North", "South", "North"],
    }).to_csv(source, index=False)

    class RateLimitedLLMClient(StubLLMClient):
        def generate_json(self, prompt, system_prompt=None, max_output_tokens=None):
            raise LLMRateLimitError("daily token quota reached")

    result = BIAnalystAgent(llm_client=RateLimitedLLMClient({})).analyze(str(source))

    assert result["fallback_used"] is True
    assert len(result["insights"]) == 3
    assert result["kpis"]["numeric_metrics"]["revenue"]["mean"] == 30
    assert result["insights"][1]["source_columns"] == ["revenue"]
    assert "rate limit" in result["fallback_reason"]


def test_bi_analyst_rejects_unavailable_source_columns(tmp_path):
    source = tmp_path / "sales.csv"
    pd.DataFrame({"revenue": [10, 20]}).to_csv(source, index=False)
    llm = StubLLMClient({"insights": [insight(("not_a_column",)) for _ in range(3)]})

    with pytest.raises(ValueError, match="invalid BI insight source columns"):
        BIAnalystAgent(llm_client=llm).analyze(str(source))


def test_bi_analyst_retries_when_llm_returns_too_few_insights(tmp_path):
    source = tmp_path / "sales.csv"
    pd.DataFrame({"revenue": [10, 20, 30]}).to_csv(source, index=False)

    class RetryLLMClient(StubLLMClient):
        def generate_json(self, prompt, system_prompt=None, max_output_tokens=None):
            self.calls.append((prompt, system_prompt, max_output_tokens))
            if len(self.calls) == 1:
                return {"insights": [insight(("revenue",))]}
            return {"insights": [insight(("revenue",)) for _ in range(3)]}

    llm = RetryLLMClient({})
    result = BIAnalystAgent(llm_client=llm).analyze(str(source))

    assert len(result["insights"]) == 3
    assert len(llm.calls) == 2
    assert "exactly 3 concise insights" in llm.calls[1][0]
    assert all(call[2] == 700 for call in llm.calls)


def test_bi_analyst_reports_when_insight_retry_still_has_wrong_count(tmp_path):
    source = tmp_path / "sales.csv"
    pd.DataFrame({"revenue": [10, 20, 30]}).to_csv(source, index=False)
    llm = StubLLMClient({"insights": [insight(("revenue",))]})

    with pytest.raises(ValueError, match="1 BI insights after one retry"):
        BIAnalystAgent(llm_client=llm).analyze(str(source))

    assert len(llm.calls) == 2


def test_bi_pipeline_runs_kpis_on_validated_cleaned_dataset(tmp_path, monkeypatch):
    source = tmp_path / "raw" / "sales.csv"
    source.parent.mkdir()
    pd.DataFrame({"revenue": [10, 10, 20]}).to_csv(source, index=False)
    monkeypatch.chdir(tmp_path)

    class PipelineLLMClient(StubLLMClient):
        def generate_json(self, prompt, system_prompt=None, max_output_tokens=None):
            self.calls.append((prompt, system_prompt, max_output_tokens))
            if max_output_tokens == 150:
                return {
                    "profile_summary": "Revenue values are numeric.",
                    "columns": [{
                        "name": "revenue",
                        "type": "numeric",
                        "role": "measure",
                        "insight": "Revenue amount",
                    }],
                }
            if max_output_tokens == 200:
                return {
                    "quality_findings": ["One duplicate row was detected."],
                    "cleaning_strategy": {
                        "numeric_waterfall_columns": [],
                        "imputation_plan": {},
                        "synonym_mappings": {},
                        "outlier_columns": [],
                        "date_columns": [],
                        "boolean_columns": [],
                        "remove_duplicates": True,
                    },
                }
            return {"insights": [insight(("revenue",)) for _ in range(3)]}

    llm = PipelineLLMClient({})
    result = BIAnalystAgent(llm_client=llm).run_pipeline(str(source))

    assert result["cleaning"]["validation"]["valid"]
    assert os.path.isfile(result["cleaned_dataset_path"])
    assert pd.read_csv(result["cleaned_dataset_path"]).shape[0] == 2
    assert result["analysis"]["kpis"]["record_count"] == 2
    assert len(llm.calls) == 3
    assert [call[2] for call in llm.calls] == [150, 200, 700]
    assert "PRIVATE" not in llm.calls[-1][0]


def test_bi_pipeline_completes_with_python_fallback_when_llm_quota_is_reached(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "raw" / "sales.csv"
    source.parent.mkdir()
    pd.DataFrame({
        "revenue": [10.0, None, 30.0],
        "region": ["North", "South", "North"],
    }).to_csv(source, index=False)
    monkeypatch.chdir(tmp_path)

    class RateLimitedLLMClient(StubLLMClient):
        def generate_json(self, prompt, system_prompt=None, max_output_tokens=None):
            raise LLMRateLimitError("daily token quota reached")

    result = BIAnalystAgent(llm_client=RateLimitedLLMClient({})).run_pipeline(str(source))

    assert result["fallback_used"] is True
    assert result["cleaning"]["validation"]["valid"]
    assert os.path.isfile(result["cleaned_dataset_path"])
    assert result["analysis"]["fallback_used"] is True
    assert result["analysis"]["kpis"]["missing_cells"] == 0
    assert len(result["analysis"]["insights"]) == 3
