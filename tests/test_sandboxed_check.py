import json

import pandas as pd
import pytest

import analytics.data_quality as data_quality
from dataCleaningTools.sandbox import SandboxResult


def test_generated_check_is_not_run_without_isolated_backend(monkeypatch):
    monkeypatch.setattr(data_quality, "detect_backend", lambda: "fallback")

    def unexpected_execution(*args, **kwargs):
        raise AssertionError("Generated code must not run on the host fallback.")

    monkeypatch.setattr(data_quality, "run_code", unexpected_execution)

    result = data_quality.run_sandboxed_check(
        "def custom_check(series): return {'passed': True}",
        pd.Series([1, 2, 3]),
    )

    assert not result["passed"]
    assert "not safe" in result["error"]


def test_generated_check_uses_isolated_runner_and_returns_validated_result(
    monkeypatch,
):
    captured = {}
    monkeypatch.setattr(data_quality, "detect_backend", lambda: "docker")

    def run_code(code, **kwargs):
        captured["code"] = code
        captured.update(kwargs)
        return SandboxResult(
            success=True,
            stdout=json.dumps(
                {"passed": True, "metric": 0.75, "details": "3 of 4 valid"}
            ),
            backend="docker",
        )

    monkeypatch.setattr(data_quality, "run_code", run_code)

    result = data_quality.run_sandboxed_check(
        "def custom_check(series):\n"
        "    return {'passed': True, 'metric': 0.75, 'details': '3 of 4 valid'}",
        pd.Series([1, None, 3, 4]),
        timeout_sec=3,
    )

    assert result == {
        "passed": True,
        "metric": 0.75,
        "details": "3 of 4 valid",
        "error": None,
        "backend": "docker",
    }
    assert captured["backend"] == "docker"
    assert captured["timeout"] == 3
    assert captured["check_safety"] is True
    assert "series = pd.Series(json.loads(" in captured["code"]
    assert "custom_check(series)" in captured["code"]


def test_generated_check_rejects_non_object_json_result(monkeypatch):
    monkeypatch.setattr(data_quality, "detect_backend", lambda: "docker")
    monkeypatch.setattr(
        data_quality,
        "run_code",
        lambda *args, **kwargs: SandboxResult(success=True, stdout="[]"),
    )

    result = data_quality.run_sandboxed_check(
        "def custom_check(series): return {}",
        pd.Series([1]),
    )

    assert not result["passed"]
    assert result["error"] == "Expected a JSON object."


def test_generated_check_rejects_non_positive_timeout(monkeypatch):
    monkeypatch.setattr(data_quality, "detect_backend", lambda: "docker")

    with pytest.raises(ValueError, match="positive finite"):
        data_quality.run_sandboxed_check(
            "def custom_check(series): return {}",
            pd.Series([1]),
            timeout_sec=0,
        )
