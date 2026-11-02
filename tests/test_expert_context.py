from copy import deepcopy
import json

import pytest

from dataCleaningTools.expert_context import compact, fit_request, MAX_REQUEST_BYTES


def payload():
    return {"messages": [{"role": "system", "content": "Write code"}, {"role": "user", "content": ""}],
            "response_format": {"schema": "test"}, "max_completion_tokens": 4096}


def test_repeated_row_failures_fit_without_losing_counts_or_mutating_audit():
    rows = [{"row_position": i, "row_index": str(i), "column": "Dependents",
             "before": "Yes" if i % 2 else "No", "expected": bool(i % 2), "actual": None} for i in range(200)]
    failed = {"mismatches": rows}
    context = {"method": {"code": "def transform(df):\n    return df"},
               "local_corrections": [{"attempt": n, "diagnostic": {"failed_checks": [failed, failed]},
                                      "failure_summary": failed} for n in range(1, 5)]}
    original = deepcopy(context)
    request = payload()
    assert len(json.dumps(context)) > MAX_REQUEST_BYTES
    sent, size = fit_request(context, request)
    assert size <= MAX_REQUEST_BYTES
    assert len(json.dumps(request).encode()) <= MAX_REQUEST_BYTES
    summary = sent["local_corrections"][0]["failure_summary"]["mismatches"]
    assert summary["total_cells"] == 200 and summary["distinct_groups"] == 2
    assert sum(g["count"] for g in summary["groups"]) == 200
    assert sent["method"]["code"] == context["method"]["code"]
    assert context == original


def test_adaptive_grouping_discloses_omitted_groups():
    context = {"failure": {"lost_values": [{"before": str(i) + "x"*1000, "after": None} for i in range(500)]}}
    sent, size = fit_request(context, payload())
    summary = sent["failure"]["lost_values"]
    assert size <= MAX_REQUEST_BYTES and summary["omitted_groups"] > 0
    assert summary["total_cells"] == 500 and summary["distinct_groups"] == 500


def test_entire_request_budget_counts_system_schema_and_unicode():
    request = payload()
    request["messages"][0]["content"] = "large system prompt" * 4000
    with pytest.raises(ValueError, match="no request sent"):
        fit_request({"method": {"code": "small"}}, request)
    request = payload()
    with pytest.raises(ValueError):
        fit_request({"method": {"code": "\u20ac" * 12000}}, request)


def test_malformed_output_keeps_preview_without_local_reasoning_transcript():
    result = compact({"raw_response": {"message": {"content": "unfinished method", "thinking": "x"*100000}},
                      "finish_reason": "length"})
    assert result["raw_response"]["output_preview"] == "unfinished method"
    assert result["finish_reason"] == "length" and "thinking" not in json.dumps(result)


def test_duplicated_evidence_is_removed_before_coarser_grouping():
    from dataCleaningTools.expert_context import deduplicate
    checks = [{"rule_name": "expected:numeric_values:amount", "passed": False}]
    mappings = [{"raw": f"${i}", "meaning": i} for i in range(30)]
    context = {"method": {"code": "def transform(df):\n    return df"},
               "failure": {"failure_summary": {"failed_checks": checks}, "diagnostic": {"case": "conversion", "evidence": {"failed_checks": checks}}},
               "value_interpretation": {"columns": {"amount": {"mappings": mappings, "format_groups": ["$<digits>"]}}},
               "observations": {"amount": {"inventory": {"values": list(range(30)), "format_groups": ["$<digits>"]}}},
               "related_row_examples": [{"amount": i} for i in range(20)],
               "local_corrections": [{"attempt": 1, "code": "def transform(df):\n    return df"},
                                     {"attempt": 2, "code": "def transform(df):\n    return df.copy()"},
                                     {"attempt": 3, "code": "def transform(df):\n    return df.copy()"}]}
    original = deepcopy(context)
    sent = deduplicate(context)
    assert context == original
    assert sent["failure"]["diagnostic"]["evidence"].startswith("same failed checks") and sent["failure"]["diagnostic"]["case"] == "conversion"
    assert sent["observations"]["amount"]["inventory"]["format_groups"] == "see value_interpretation"
    assert len(sent["observations"]["amount"]["inventory"]["values"]) == 10
    assert sent["observations"]["amount"]["inventory"]["omitted_values"] == 20
    assert len(sent["related_row_examples"]) == 5
    assert [a["code"] for a in sent["local_corrections"]] == [
        "same as method.code", "def transform(df):\n    return df.copy()", "same as local correction 2"]
    assert sent["value_interpretation"] == original["value_interpretation"] and sent["method"] == original["method"]


def test_budget_follows_the_provider_token_limit(monkeypatch):
    from dataCleaningTools.expert_context import CHARS_PER_TOKEN, prompt_chars, request_budget
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_TOKEN_LIMIT", "8000")
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_MAX_COMPLETION_TOKENS", "2000")
    assert request_budget() == int(6000 * CHARS_PER_TOKEN)
    request = payload()
    big = {"method": {"code": "x" * 30000}}
    with pytest.raises(ValueError, match="no request sent"):
        fit_request(big, request)
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_TOKEN_LIMIT", "30000")
    sent, _ = fit_request(big, request)
    assert prompt_chars(request) <= request_budget() and sent["method"]["code"] == "x" * 30000
