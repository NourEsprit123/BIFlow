import json
import time
from types import SimpleNamespace

import httpx
import pytest

from dataCleaningTools import experiments, expert_generator
from dataCleaningTools.self_correction import execute_and_fix_loop
from tests.test_cleaning_experiments import CODE, session, request, trusted_test_runner
from tests.test_cleaning_loop import action


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_ENABLED", "true")
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_unit_test_not_real")
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_MAX_CALLS", "2")


def provider(monkeypatch, *, code=CODE, decision="generated", status=200, finish="stop"):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=status, json=lambda: {"choices": [{"finish_reason": finish,
            "message": {"content": json.dumps({"decision": decision, "code": code,
                "hypothesis": "Parse currency with an explicit preservation rule", "assumptions": []})}}],
            "usage": {"total_tokens": 123}})
    monkeypatch.setattr("dataCleaningTools.llm_client.httpx.post", post)
    return calls


def initial_failure(executor, evidence):
    args = {**request(evidence), "code": r"def transform(df):\n    return df"}
    return args, json.loads(executor.execute("test_generated", args))


def failing_local(calls):
    def generate(messages, tools, **kwargs):
        calls.append(json.loads(messages[-1]["content"]))
        return action("repair_method", code=f"def transform(df):\n    raise ValueError('local-{len(calls)}')",
                      hypothesis="Address the observed parser failure")
    return generate


def test_context_filters_conflicting_profile_and_migrates_old_dashboard_objective(session, monkeypatch):
    state, executor, evidence = session
    args = request(evidence)
    state.source_ref.metadata["user_request"] = (
        "Preserve the uploaded original. If the isolated runtime is unavailable or the method fails, "
        "explain that result and test builtin catalog methods where appropriate.")
    state.working_report["column_profiles"] = {"amount": {
        "inferred_role": "categorical", "imputation_strategy": "median", "etl_cast_to": "float64",
        "business_interpretation": "Revenue per order", "agent_reasoning": "Dirty numeric text"}}
    state.focused_cleaning = True
    monkeypatch.setattr("dataCleaningTools.cleaning_tasks.model_view", lambda *a: {
        "cleaning_focus": {"task": {"category": "types"}}, "outstanding": {"pending_types": {"amount": "float"}}})
    runtime = {"image_id": "sha256:actual", "versions": {"python": "3.12.1", "pandas": "2.3.3", "numpy": "2.3.0"}}
    context = expert_generator.generation_context(executor, args, {}, [], runtime)
    profile = context["observations"]["amount"]["profiling"]
    assert profile["etl_cast_to"] == "float64" and profile["business_interpretation"]
    assert "imputation_strategy" not in profile and "inferred_role" not in profile
    assert "test builtin catalog methods" not in context["user_objective"]
    assert context["execution_contract"]["runtime"]["versions"] == runtime["versions"]
    assert "pd.NA" in context["execution_contract"]["numeric_missing_values"]
    assert state.working_report["column_profiles"]["amount"]["imputation_strategy"] == "median"


def test_truncated_local_reply_evidence_reaches_groq(session, monkeypatch):
    _, executor, evidence = session
    args, initial = initial_failure(executor, evidence)
    requests = provider(monkeypatch, decision="needs_review", code="")
    def truncated(*a, **k):
        return {"tool_calls": [], "finish_reason": "length", "response_issue": "truncated",
                "raw_response": "def transform(df): ... incomplete"}
    execute_and_fix_loop(args, initial, executor=executor, generate=truncated)
    payload = json.loads(requests[0][1]["json"]["messages"][1]["content"])
    assert len(payload["local_corrections"]) == 2  # two unusable replies end local correction
    for attempt in payload["local_corrections"]:
        assert attempt["finish_reason"] == "length"
        assert attempt["response_issue"] == "truncated"
        assert "incomplete" in attempt["raw_response"]["output_preview"]


def test_four_failed_corrections_trigger_groq_code_then_docker(session, monkeypatch):
    state, executor, evidence = session
    args, initial = initial_failure(executor, evidence)
    requests = provider(monkeypatch)
    executions = []
    trusted = trusted_test_runner(executions)
    def sandbox(frame, code, **kwargs):
        if "raise ValueError" in code:
            executions.append({"code": code})
            return {"success": False, "error": "ValueError: parser still fails on $10", "error_kind": "sandbox_execution"}
        return trusted(frame, code, **kwargs)
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    local = []
    revised, result = execute_and_fix_loop(args, initial, executor=executor, generate=failing_local(local))
    assert len(local) == 4 and len(requests) == 1
    assert result["success"] and revised["code"] == CODE and state.current_ref.version == "V1"
    assert [e["origin"] for e in state.events if e["tool"] == "test_generated"][-1] == "groq_generation"
    url, options = requests[0]
    assert url == expert_generator.ENDPOINT
    assert options["json"]["response_format"]["json_schema"]["strict"]
    payload = json.loads(options["json"]["messages"][1]["content"])
    assert len(payload["local_corrections"]) == 4
    assert "local-4" in payload["method"]["code"]
    assert payload["failure"]["error"] and payload["observations"]["amount"]["inventory"]["all_distinct_values_displayed"]
    assert payload["execution_contract"]["signature"]
    assert "customer" not in payload["observations"]
    assert "gsk_unit_test" not in json.dumps(state.expert_generations)


@pytest.mark.parametrize("success_at", [1, 2, 3, 4])
def test_success_before_escalation_never_calls_groq(session, monkeypatch, success_at):
    state, executor, evidence = session
    args, failure = initial_failure(executor, evidence)
    calls = provider(monkeypatch)
    trusted = trusted_test_runner([])
    def runner(frame, code, **kwargs):
        # The new-but-wrong methods leave amount unparsed, so their checks fail.
        if "attempt =" in code:
            return {"success": True, "df": frame.copy(), "image_id": "sha256:tested", "repeatable": True}
        return trusted(frame, code, **kwargs)
    monkeypatch.setattr(experiments, "run_isolated_transform", runner)
    attempts = []
    def generate(messages, tools, **k):
        attempts.append(1)
        # Earlier replies are new methods that still fail, so local correction keeps going.
        failing = f"def transform(df):\n    attempt = {len(attempts)}\n    return df"
        reply = {"code": CODE if len(attempts) == success_at else failing, "hypothesis": "Correction"}
        if "proposal" in tools[0]["function"]["parameters"]["required"]:
            reply["proposal"] = {k: "Parse currency text" for k in ("supported_interpretations", "preservation", "ambiguities")}
        return action("repair_method", **reply)
    _, result = execute_and_fix_loop(args, failure, executor=executor, generate=generate)
    assert result["success"] and len(attempts) == success_at and not calls
    assert not state.expert_generations


def test_unproductive_corrections_stop_early_and_escalate(session, monkeypatch):
    _, executor, evidence = session
    args, failure = initial_failure(executor, evidence)
    calls = provider(monkeypatch)
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner([]))
    attempts = []
    def generate(*a, **k):
        attempts.append(1)
        return action("repair_method", code=args["code"], **({"hypothesis": "Unchanged"} if len(attempts) % 2 else {}))
    _, result = execute_and_fix_loop(args, failure, executor=executor, generate=generate)
    # Two consecutive replies without a new method end local correction; Groq gets the task.
    assert result["success"] and len(attempts) == 2 and len(calls) == 1


@pytest.mark.parametrize("status,finish,code,decision", [
    (429, "stop", CODE, "generated"), (402, "stop", CODE, "generated"),
    (503, "stop", CODE, "generated"), (200, "length", CODE, "generated"),
    (200, "stop", "not valid python", "generated"), (200, "stop", "", "needs_review")])
def test_unusable_expert_output_stops_without_applying(session, monkeypatch, status, finish, code, decision):
    state, executor, evidence = session
    args, failure = initial_failure(executor, evidence)
    calls = provider(monkeypatch, status=status, finish=finish, code=code, decision=decision)
    attempts = []
    _, result = execute_and_fix_loop(args, failure, executor=executor,
        generate=lambda *a, **k: (attempts.append(1) or action("repair_method", code=args["code"], hypothesis="Unchanged")))
    assert not result["success"] and state.finished and state.current_ref.version == "V1"
    assert state.stop_reason == "expert_generation_failed" and len(calls) == 1 and len(attempts) == 2


def test_groq_code_must_pass_dataset_checks(session, monkeypatch):
    state, executor, evidence = session
    args, failure = initial_failure(executor, evidence)
    provider(monkeypatch)
    def loses_data(frame, code, **kwargs):
        output = frame.copy(); output["amount"] = None
        return {"success": True, "df": output, "image_id": "sha256:test"}
    monkeypatch.setattr(experiments, "run_isolated_transform", loses_data)
    _, result = execute_and_fix_loop(args, failure, executor=executor,
        generate=lambda *a, **k: action("repair_method", code=args["code"], hypothesis="Unchanged"))
    assert not result["success"] and state.stop_reason == "correction_exhausted"
    assert state.current_ref.version == "V1"


def test_budget_cache_missing_key_and_safe_errors(session, monkeypatch):
    state, executor, evidence = session
    args = request(evidence); attempts = [{"attempt": n, "error": "Failed"} for n in range(1, 5)]
    calls = provider(monkeypatch)
    first = expert_generator.generate_candidate(executor, args, {}, attempts=attempts)
    assert expert_generator.generate_candidate(executor, args, {}, attempts=attempts) == first
    assert len(calls) == 1
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_MAX_CALLS", "1")
    blocked = expert_generator.generate_candidate(executor, {**args, "hypothesis": "A different context"}, {}, attempts=attempts)
    assert blocked["decision"] == "unavailable" and len(calls) == 1
    state.expert_generations.clear(); monkeypatch.delenv("GROQ_API_KEY")
    assert expert_generator.generate_candidate(executor, args, {}, attempts=attempts)["decision"] == "unavailable"
    state.expert_generations.clear(); monkeypatch.setenv("GROQ_API_KEY", "gsk_unit_test_not_real")
    def fail(*a, **k): raise httpx.ConnectError("gsk_unit_test_not_real must not leak")
    monkeypatch.setattr("dataCleaningTools.llm_client.httpx.post", fail)
    record = expert_generator.generate_candidate(executor, args, {}, attempts=attempts)
    assert record["decision"] == "unavailable" and "gsk_unit_test" not in json.dumps(record)


def test_deadline_no_groq_and_no_late_acceptance(session, monkeypatch):
    state, executor, evidence = session
    args = request(evidence)
    calls = provider(monkeypatch)
    state.deadline = time.monotonic()-1
    assert expert_generator.generate_candidate(executor, args, {}, attempts=[])["decision"] == "unavailable"
    assert not calls


def test_oversized_irreducible_request_never_reaches_provider(session, monkeypatch):
    _, executor, evidence = session
    calls = provider(monkeypatch)
    args = {**request(evidence), "hypothesis": "x" * 70000}
    record = expert_generator.generate_candidate(executor, args, {},
        attempts=[{"attempt": n, "error": "failed"} for n in range(1, 5)])
    assert not record["request_sent"] and not calls
    assert "no request sent" in record["error"] and record["audit_context"]["method"]["hypothesis"] == args["hypothesis"]


def test_large_repeated_evidence_is_sent_under_budget(session, monkeypatch):
    _, executor, evidence = session
    calls = provider(monkeypatch)
    mismatches = [{"row_position": i, "column": "amount", "before": "$10", "expected": 10, "actual": None}
                  for i in range(200)]
    attempts = [{"attempt": n, "failure_summary": {"mismatches": mismatches}} for n in range(1, 5)]
    record = expert_generator.generate_candidate(executor, request(evidence), {}, attempts=attempts)
    assert record["request_sent"] and len(calls) == 1
    assert len(json.dumps(calls[0][1]["json"]).encode()) <= 60000
    assert record["request_bytes"] <= record["request_limit_bytes"]
    assert record["context"]["local_corrections"][0]["failure_summary"]["mismatches"]["total_cells"] == 200
    assert len(record["audit_context"]["local_corrections"][0]["failure_summary"]["mismatches"]) == 200


def test_truncated_then_repeated_corrections_escalate_after_two(session, monkeypatch):
    state, executor, evidence = session
    args, failure = initial_failure(executor, evidence)
    calls = provider(monkeypatch)
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner([]))
    replies = [action("repair_method", hypothesis="Cut off before the code"),
               action("repair_method", code=args["code"], hypothesis="Same code again")]
    attempts = []
    def generate(*a, **k):
        attempts.append(1)
        return replies[len(attempts) - 1]
    _, result = execute_and_fix_loop(args, failure, executor=executor, generate=generate)
    assert result["success"] and len(attempts) == 2 and len(calls) == 1
    assert [g["trigger"] for g in state.expert_generations.values()] == ["unproductive_local_corrections"]
