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
