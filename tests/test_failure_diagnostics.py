import json

import pytest

from dataCleaningTools.diagnostics import failure_diagnostic
from tests.test_cleaning_experiments import session


def test_literal_newlines_are_identified_without_rewriting_code():
    code = r"def transform(df):\n    return df"
    result = failure_diagnostic("sandbox_execution", "Invalid candidate Python", code=code)
    assert result["stage"] == "python_syntax"
    assert result["location"]["line"] == 1
    assert result["evidence"]["execution_started"] is False
    assert result["evidence"]["literal_newline_escapes"] == 1
    assert "do not double-escape" in result["correction"]


@pytest.mark.parametrize("code", ["def transform(df)\n    return df", "def transform(df):\nreturn df"])
def test_other_syntax_errors_have_precise_location(code):
    result = failure_diagnostic("sandbox_execution", "Invalid candidate Python", code=code)
    assert result["stage"] == "python_syntax"
    assert result["location"]["line"]
    assert result["location"]["source"]
    assert "literal_newline_escapes" not in result["evidence"]


def test_runtime_location_comes_from_partition_traceback():
    error = 'Traceback:\n  File "<cleaning-candidate>", line 2, in transform\nKeyError: missing'
    result = failure_diagnostic("sandbox_execution", "Trial failed",
        code="def transform(df):\n    return df['missing']", trials=[{"partition": "sample", "error": error}])
    assert result["location"] == {"line": 2, "function": "transform", "source": "    return df['missing']"}
    assert "KeyError" in result["problem"]


def test_unknown_error_does_not_invent_a_cause():
    result = failure_diagnostic("general", "Unexpected failure")
    assert result["location"] is None
    assert result["problem"] == "Unexpected failure"


def test_executor_returns_diagnostic_in_trace_and_recovery(session):
    state, executor, _ = session
    code = r"def transform(df):\n    return df"
    result = json.loads(executor.execute(('test_generated'), {"hypothesis": "Preserve values", "columns": ["amount"],
        "code": code, "checks": [{"column": "amount", "kind": "numeric"}]}))
    assert not result["success"]
    assert result["diagnostic"]["stage"] == "python_syntax"
    assert result["diagnostic"] == result["recovery_prompt"]["context"]["diagnostic"]
    assert state.events[-1]["result"]["diagnostic"] == result["diagnostic"]
    assert state.events[-1]["arguments"]["code"] == code
    assert state.current_ref.version == "V1"
