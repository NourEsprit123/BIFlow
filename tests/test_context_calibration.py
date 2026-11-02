"""The context budget learns characters per token from the prompt sizes Ollama reports."""
import json
from types import SimpleNamespace

import pytest

from agents.dataCleaning_agent import CALIBRATION_MARGIN, _calibrate, _request_context
from dataCleaningTools import workflow
from tests.test_cleaning_loop import action, run


def test_measured_ratio_sets_the_budget_with_a_safety_margin():
    state = SimpleNamespace(chars_per_token=4.0)
    request = [{"role": "user", "content": "x" * 30000}]
    tools = workflow.SCHEMAS_LIST
    chars = len(json.dumps(request)) + len(json.dumps(tools))
    _calibrate(state, request, tools, {"usage": {"prompt_tokens": chars // 6}})
    assert state.chars_per_token == pytest.approx(chars / (chars // 6) * CALIBRATION_MARGIN)


@pytest.mark.parametrize("tokens, expected", [(None, 4.0), (100, 4.0), (10, 4.0)])
def test_missing_or_tiny_measurements_keep_the_current_ratio(tokens, expected):
    state = SimpleNamespace(chars_per_token=4.0)
    _calibrate(state, [{"role": "user", "content": "x"}], [], {"usage": {"prompt_tokens": tokens}})
    assert state.chars_per_token == expected


def test_ratio_is_bounded():
    state = SimpleNamespace(chars_per_token=4.0)
    _calibrate(state, [{"role": "user", "content": "x" * 100000}], [], {"usage": {"prompt_tokens": 1000}})
    assert state.chars_per_token == 8.0


def test_request_too_large_at_the_default_fits_after_calibration():
    # About 16K characters fit at 4 chars/token and about 28K at 6, after the tool schemas.
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u" * 25000}]
    with pytest.raises(ValueError, match="Cleaning prompt exceeds"):
        _request_context(messages, tools=workflow.SCHEMAS_LIST)
    assert _request_context(messages, tools=workflow.SCHEMAS_LIST, chars_per_token=6.0) == messages


def test_loop_calibrates_from_reported_prompt_tokens(tmp_path, monkeypatch):
    def respond(messages, tools, **kwargs):
        reply = action("finish", summary="Done")
        reply["usage"] = {"prompt_tokens": 1000}  # far fewer tokens than characters / 4
        return reply
    result = run(tmp_path, monkeypatch, respond)
    ratios = [s["chars_per_token"] for s in result.metadata["step_log"] if "chars_per_token" in s]
    assert ratios and ratios[0] > 4.0
