import json
from types import SimpleNamespace

from dataCleaningTools import experiments, workflow
from tests.test_cleaning_loop import action, run

CODE = "def transform(df):\n    df['flag'] = df['flag'].map({'Yes': True, 'No': False})\n    return df"
BAD = r"def transform(df):\n    return df"


def request(code=CODE):
    return {"hypothesis": "Yes/No values encode boolean flags", "columns": ["flag"], "code": code,
            "checks": [{"column": "flag", "kind": "boolean"}]}


def sandbox(frame, code, **kwargs):
    output = frame.copy(); output["flag"] = output["flag"].map({"Yes": True, "No": False})
    return {"success": True, "df": output, "image_id": "sha256:test", "repeatable": True}


def test_testing_interfaces_are_separate():
    assert "test_method" not in workflow.SCHEMA
    assert "code" not in workflow.SCHEMA["test_builtin"]["properties"]
    assert not {"operation", "parameters"} & set(workflow.SCHEMA["test_generated"]["properties"])
    assert workflow.SCHEMA["test_builtin"]["properties"]["parameters"]["additionalProperties"] is False
    assert "code" in workflow.SCHEMA["test_generated"]["required"]
    assert "checks" in workflow.SCHEMA["test_generated"]["properties"]  # optional: the host supplies defaults


def test_misplaced_custom_code_is_reconstructed_and_tested(tmp_path, monkeypatch):
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    calls = []
    def respond(messages, tools, **kwargs):
        calls.append(kwargs.get("structured", False))
        if len(calls) == 1:
            return action("test_builtin", columns=["flag"], hypothesis="Custom parser",
                operation="convert_data_types", parameters={"target_type": "boolean", "code": "incomplete helper"})
        if kwargs.get("structured"):
            assert [t["function"]["name"] for t in tools] == ["test_generated"]
            return action("test_generated", **request())
        return action("finish", summary="Generated method tested and applied")
    result = run(tmp_path, monkeypatch, respond)
    assert result.validation.all_passed and result.final_dataset.version == "V2"
    assert calls == [False, True, False]
    events = result.metadata["events"]
    assert [(e["tool"], e["origin"]) for e in events[:3]] == [
        ("test_builtin", "model"), ("test_generated", "request_correction"), ("apply_candidate", "automatic_after_trial")]


def test_docker_unavailable_drops_the_generated_task_without_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(experiments, "runtime_status", lambda: {"available": False, "error": "Docker Desktop is stopped"})
    calls = []
    def respond(messages, tools, **k):
        calls.append(1)
        if len(calls) == 1:
            return action("test_generated", **request(BAD))
        assert "test_generated" not in {t["function"]["name"] for t in tools}
        return action("finish", summary="Flag conversion needs Docker")
    result = run(tmp_path, monkeypatch, respond)
    assert len(calls) == 2 and [d["reason"] for d in result.metadata["task_drops"]] == ["sandbox_unavailable"]
    assert result.final_dataset.version == "V1" and not result.validation.all_passed
    assert any("Docker Desktop is stopped" in text for text in result.unresolved_issues)
    assert not result.metadata["expert_generations"]


def test_failed_builtin_leaves_builtin_and_generated_routes_open(tmp_path, monkeypatch):
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    calls = []
    def respond(messages, tools, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return action("test_builtin", columns=["flag"], hypothesis="Wrong numeric conversion",
                          operation="convert_data_types", parameters={"target_type": "float"})
        if len(calls) == 2:
            assert {"test_builtin", "test_generated"} <= {t["function"]["name"] for t in tools}
            assert not json.loads(messages[-1]["content"])["cleaning_focus"]["task"].get("generated_required")
            return action("test_generated", **request())
        return action("finish", summary="A generated method resolved the failed builtin")
    result = run(tmp_path, monkeypatch, respond)
    assert result.validation.all_passed
    assert len([e for e in result.metadata["events"] if e["tool"] == "test_builtin"]) == 1


def test_invalid_request_correction_is_bounded(tmp_path, monkeypatch):
    calls = []
    def respond(*a, **k):
        calls.append(1)
        if len(calls) > 3:
            return action("finish", summary="Could not form a valid request")
        return action("test_generated", columns=["flag"], code=CODE)  # missing required fields
    result = run(tmp_path, monkeypatch, respond)
    assert len(calls) == 4  # original request + two request-envelope corrections, then finish
    assert [d["reason"] for d in result.metadata["task_drops"]] == ["request_correction_failed"]
    assert result.final_dataset.version == "V1" and not result.metadata["expert_generations"]


def test_groq_generated_code_is_auto_applied_only_after_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_ENABLED", "true")
    monkeypatch.setenv("GROQ_API_KEY", "test_groq_key")
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    providers = []
    def post(url, **kwargs):
        providers.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"decision": "generated", "code": CODE, "hypothesis": "Map verified Yes/No values", "assumptions": []})}}]})
    monkeypatch.setattr("dataCleaningTools.llm_client.httpx.post", post)
    calls = []
    def respond(messages, tools, **kwargs):
        calls.append(1)
        if kwargs.get("structured"):
            return action("repair_method", code=BAD, hypothesis="Unchanged local attempt")
        if len(calls) == 1:
            return action("test_generated", **request(BAD))
        return action("finish", summary="Groq-authored repair passed the same full-data checks")
    result = run(tmp_path, monkeypatch, respond)
    assert result.validation.all_passed and result.final_dataset.version == "V2"
    assert len(calls) == 4 and len(providers) == 1  # main, two unchanged local corrections, finish
    assert any(e["origin"] == "groq_generation" for e in result.metadata["events"])
    assert result.metadata["expert_generations"]


def test_uncorrectable_builtin_request_falls_back_to_generated_code(tmp_path, monkeypatch):
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    turns, corrections = [], []
    def respond(messages, tools, **kwargs):
        if kwargs.get("structured"):
            corrections.append(1)
            return {"tool_calls": []}  # request correction cannot repair it
        turns.append([t["function"]["name"] for t in tools])
        if len(turns) == 1:
            return action("test_builtin", columns=["flag"], hypothesis="Yes/No flags", operation="convert_data_types",
                          parameters={"target_type": "boolean", "method": "iqr"})
        if len(turns) == 2:
            feedback = json.loads(next(m["content"] for m in reversed(messages) if m["role"] == "tool"))
            assert "test_generated" in feedback["error"]
            return action("test_generated", **request())
        return action("finish", summary="Generated method applied after the builtin request failed")
    result = run(tmp_path, monkeypatch, respond)
    assert not result.metadata["task_drops"] and len(corrections) == 2
    assert "test_generated" in turns[1]
    assert result.validation.all_passed and result.final_dataset.version == "V2"
