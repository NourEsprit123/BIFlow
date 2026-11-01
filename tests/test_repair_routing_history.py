import json

from dataCleaningTools import experiments
from dataCleaningTools.self_correction import execute_and_fix_loop
from dataCleaningTools.request_correction import correct_request
from tests.test_cleaning_experiments import CODE, session, trusted_test_runner
from tests.test_cleaning_loop import action, run


def test_invalid_check_routes_to_request_repair_without_changing_code(session, monkeypatch):
    state, executor, _ = session
    args = {"code": CODE, "columns": ["amount"], "hypothesis": "Parse currency", "checks": [{"column": "amount", "kind": "float"}]}
    initial = json.loads(executor.execute(('test_generated'), args))
    assert initial["recovery_prompt"]["case"] == "arguments"
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner([]))
    def generate(messages, tools, **options):
        assert tools[0]["function"]["name"] == "test_generated"
        return action("test_generated", code=CODE, hypothesis="Correct the numeric check vocabulary", columns=["amount"],
                      checks=[{"column": "amount", "kind": "numeric"}])
    _, corrected, result = correct_request("test_generated", args, initial, executor=executor, generate=generate)
    assert result["success"] and corrected["code"] == CODE
    assert corrected["checks"][0]["kind"] == "numeric"


def test_request_repair_cannot_weaken_intended_outcomes(session):
    state, executor, _ = session
    args = {"code": CODE, "columns": ["amount"], "hypothesis": "Parse currency", "checks": [{"column": "amount", "kind": "float"}]}
    initial = json.loads(executor.execute(('test_generated'), args))
    def generate(*a, **k):
        return action("test_generated", code=CODE, hypothesis="Weaken to string", columns=["amount"], checks=[{"column": "amount", "kind": "string"}])
    _, _, result = correct_request("test_generated", args, initial, executor=executor, generate=generate, max_retries=1)
    assert not result["success"] and "without weakening" in result["error"]
    assert len(state.events) == 2


def test_infrastructure_failure_does_not_request_code_repair(session, monkeypatch):
    state, executor, _ = session
    monkeypatch.setattr(experiments, "run_isolated_transform", lambda *a, **k: {
        "success": False, "error": "Docker input transport failed", "error_kind": "sandbox_infrastructure"})
    args = {"code": CODE, "columns": ["amount"], "hypothesis": "Parse currency", "checks": [{"column": "amount", "kind": "numeric"}]}
    initial = json.loads(executor.execute(('test_generated'), args))
    assert initial["recovery_prompt"]["case"] == "sandbox_unavailable"
    def forbidden(*a, **k):
        raise AssertionError("Infrastructure failure must not request a code fix")
    _, result = execute_and_fix_loop(args, initial, executor=executor, generate=forbidden)
    assert result == initial


def test_equivalent_failed_code_is_blocked_across_turns_and_checks(session, monkeypatch):
    state, executor, _ = session
    args = {"code": "def transform(df):\n    return df", "columns": ["amount"], "hypothesis": "Attempt", "checks": [{"column": "amount", "kind": "numeric"}]}
    calls = []
    def sandbox(frame, code, **options):
        calls.append(code)
        return {"success": True, "df": frame.copy(), "image_id": "test", "repeatable": True}
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    initial = json.loads(executor.execute(('test_generated'), args))
    assert not initial["success"]
    state.current_turn = 8
    duplicate = json.loads(executor.execute(('test_generated'), {**args, "code": "# cosmetically different\ndef transform(df):\n  return df\n",
        "hypothesis": "Different explanation", "checks": args["checks"] + [{"column": "amount", "kind": "no_missing"}]}))
    assert duplicate["candidate_status"] == "failed" and duplicate["previous_attempt"] == "repair-1"
    assert len(calls) == 1
    trace = json.loads((state.manager.root / state.dataset_id / "execution_trace.json").read_text())
    assert trace["repair_history"][0]["arguments"]["code"] == args["code"]


def test_data_loss_requires_proposal_and_still_checks_actual_data(session, monkeypatch):
    state, executor, _ = session
    bad = "def transform(df):\n    df['amount'] = None\n    return df"
    args = {"code": bad, "columns": ["amount"], "hypothesis": "Bad erasure", "checks": [{"column": "amount", "kind": "numeric"}]}
    good_runner = trusted_test_runner([])
    def sandbox(frame, code, **options):
        if code == bad:
            output = frame.copy(); output["amount"] = None
            return {"success": True, "df": output, "image_id": "test", "repeatable": True}
        return good_runner(frame, code, **options)
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    initial = json.loads(executor.execute(('test_generated'), args))
    requests = []
    def generate(messages, tools, **options):
        requests.append(json.loads(messages[-1]["content"]))
        assert "proposal" in tools[0]["function"]["parameters"]["required"]
        if len(requests) == 1:
            return action("repair_method", code=CODE, hypothesis="Missing proposal")
        return action("repair_method", code=CODE, hypothesis="Parse currency", proposal={
            "supported_interpretations": "Dollar amounts have explicit numeric meaning",
            "preservation": "Remove the currency formatting and preserve numeric amounts",
            "ambiguities": "No unknown tokens in the inspected fixture"})
    corrected, result = execute_and_fix_loop(args, initial, executor=executor, generate=generate)
    assert "proposal" in requests[1]["failure"]["repair_error"]
    assert requests[1]["repair_history"][0]["route"] == "validation"
    assert result["success"] and "Repair proposal" in corrected["hypothesis"]
    assert state.current_ref.version == "V1"  # passing trial alone does not commit


def test_failed_builtin_cannot_be_bypassed_with_another_builtin(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})
    calls = []
    def respond(messages, tools, **options):
        calls.append(messages)
        if len(calls) <= 3:
            return action("test_builtin", hypothesis="Invalid numeric flags", columns=["flag"], operation="convert_data_types",
                          parameters={"target_type": "float", "errors": "coerce"})
        if len(calls) == 4:
            assert json.loads(messages[-1]["content"])["repair_history"]
            return action("test_builtin", hypothesis="Yes/No flags have boolean meaning", columns=["flag"], operation="convert_data_types",
                          parameters={"target_type": "boolean"})
        return action("finish", summary="Flags converted")
    result = run(tmp_path, monkeypatch, respond, max_turns=5)
    assert not result.validation.all_passed and result.final_dataset.version == "V1"
    assert not any(e["tool"] == "apply_candidate" for e in result.metadata["events"])
