import json
import time

import pandas as pd

from dataCleaningTools import experiments
from dataCleaningTools.self_correction import execute_and_fix_loop
from tests.test_cleaning_experiments import CODE, session, trusted_test_runner
from tests.test_cleaning_loop import action, run


BAD = r"def transform(df):\n    return df"


def failed_trial(executor):
    args = {"hypothesis": "Parse observed currency", "columns": ["amount"], "code": BAD,
            "checks": [{"column": "amount", "kind": "numeric"}]}
    return args, json.loads(executor.execute(('test_generated'), args))


def test_failed_syntax_is_repaired_and_tested_without_host_execution(session, monkeypatch):
    state, executor, _ = session
    args, failure = failed_trial(executor)
    sandbox_calls = []
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner(sandbox_calls))
    requests = []
    def generate(messages, tools, **options):
        requests.append(json.loads(messages[-1]["content"]))
        return action("repair_method", code=CODE, hypothesis="Decode actual lines and parse currency before justified imputation")
    revised, result = execute_and_fix_loop(args, failure, executor=executor, generate=generate)
    assert result["success"] and result["tested"]
    assert revised["columns"] == args["columns"] and revised["checks"] == args["checks"]
    assert requests[0]["failure"]["diagnostic"]["stage"] == "python_syntax"
    assert len(sandbox_calls) == 2  # sample and holdout, no promotion in helper
    assert state.current_ref.version == "V1"
    assert state.events[-1]["origin"] == "self_correction"


def test_repeated_code_is_bounded_and_not_executed(session):
    state, executor, _ = session
    args, failure = failed_trial(executor)
    calls = []
    def generate(messages, tools, **options):
        calls.append(json.loads(messages[-1]["content"]))
        return action("repair_method", code=BAD, hypothesis="Changed explanation")
    _, result = execute_and_fix_loop(args, failure, executor=executor, generate=generate)
    assert len(calls) == 2  # a second unchanged reply ends local correction
    assert "exact code already failed" in calls[1]["failure"]["repair_error"]
    assert not result["success"] and len(state.events) == 2
    assert len([s for s in state.step_log if s.get("source") == "self_correction"]) == 2


def test_setup_failures_and_expired_deadlines_do_not_request_repairs(session):
    state, executor, _ = session
    args, failure = failed_trial(executor)
    def forbidden(*a, **k):
        raise AssertionError("No LLM call expected")
    unavailable = {"success": False, "recovery_prompt": {"case": "sandbox_unavailable"}}
    assert execute_and_fix_loop(args, unavailable, executor=executor, generate=forbidden)[1] == unavailable
    state.deadline = time.monotonic() - 1
    assert execute_and_fix_loop(args, failure, executor=executor, generate=forbidden)[1] == failure


def test_provider_error_preserves_failed_trial_and_dataset(session):
    state, executor, _ = session
    args, failure = failed_trial(executor)
    def generate(*a, **k):
        raise TimeoutError("request budget expired")
    _, result = execute_and_fix_loop(args, failure, executor=executor, generate=generate)
    assert not result["success"] and "TimeoutError" in result["repair_error"]
    assert state.current_ref.version == "V1"


def test_agent_promotes_corrected_method_in_same_turn(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})
    def sandbox(frame, code, **options):
        output = frame.copy()
        output["flag"] = output["flag"].map({"Yes": True, "No": False}).astype("boolean")
        return {"success": True, "df": output, "image_id": "test-image", "repeatable": True}
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    requests = []
    def respond(messages, tools, **options):
        requests.append(tools[0]["function"]["name"])
        if len(requests) == 1:
            return action("test_generated", code=BAD, hypothesis="Parse Yes/No flags", columns=["flag"],
                          checks=[{"column": "flag", "kind": "boolean"}])
        if requests[-1] == "repair_method":
            return action("repair_method", code="def transform(df):\n    df['flag'] = df['flag'].map({'Yes': True, 'No': False})\n    return df",
                          hypothesis="Correct newline serialization and preserve Yes/No meaning")
        return action("finish", summary="Flags converted and checked")
    result = run(tmp_path, monkeypatch, respond, max_turns=2)
    assert result.validation.all_passed
    events = result.metadata["events"]
    assert [e["tool"] for e in events] == ["test_generated", "test_generated", "apply_candidate", "finish"]
    assert events[1]["origin"] == "self_correction"
    assert result.final_dataset.version == "V2"
    assert result.metadata["turns_used"] == 2
    assert pd.read_csv(tmp_path / "input.csv")["flag"].tolist() == ["Yes", "No"]
