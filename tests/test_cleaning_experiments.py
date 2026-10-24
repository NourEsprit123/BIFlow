import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from dataCleaningTools import experiments
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager


CODE = """def transform(df):
    values = pd.to_numeric(df['amount'].str.replace('$', '', regex=False))
    df['amount'] = values.fillna(values.median())
    return df
"""


@pytest.fixture
def session(tmp_path):
    source = tmp_path / "dirty.csv"
    pd.DataFrame({"customer": ["a", "b", "c", "d"], "amount": ["$10", "$20", None, "$40"]}).to_csv(source, index=False)
    manager = DatasetVersionManager(tmp_path / "versions")
    original = manager.register_original(source, dataset_id="dirty")
    state = AgentSessionState(manager=manager, dataset_id="dirty", source_ref=original,
                              current_ref=manager.create_working_copy(original), expected_columns=["customer", "amount"])
    executor = ToolExecutor(state)
    observed = json.loads(executor.execute("inspect_column", {"column": "amount"}))
    return state, executor, observed["event_id"]


def request(evidence):
    return {"code": CODE, "columns": ["amount"], "rationale": "Observed currency strings and a missing value",
            "expected_effect": "Parse dollar amounts and fill the missing amount using the median",
            "evidence_ids": [evidence], "checks": [{"column": "amount", "kind": "numeric"},
                {"column": "amount", "kind": "no_missing"}, {"column": "amount", "kind": "non_negative"}]}


def trusted_test_runner(calls, fail_full=False):
    # Implement a known test transformation directly. Never exec generated code
    # on the host, including in mocked unit tests.
    def run(frame, code, *, image_id=None):
        calls.append({"index": frame.index.tolist(), "code": code, "image_id": image_id, "rows": len(frame)})
        result = frame.copy()
        numbers = pd.to_numeric(result.amount.str.replace("$", "", regex=False))
        result["amount"] = numbers.fillna(numbers.median())
        if fail_full and len(frame) == 4:
            result.loc[0, "amount"] = None
        return {"success": True, "df": result, "image_id": "sha256:tested", "repeatable": True}
    return run


def test_trials_are_disjoint_and_exact_method_is_promoted_after_full_checks(session, monkeypatch):
    state, executor, evidence = session
    original = Path(state.source_ref.path).read_bytes()
    calls = []
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner(calls))
    trial = json.loads(executor.execute("experiment_cleaning_method", request(evidence)))
    assert trial["tested"] and trial["success"]
    assert state.current_ref.version == "V1"
    assert set(calls[0]["index"]).isdisjoint(calls[1]["index"])
    assert calls[1]["image_id"] == "sha256:tested"
    result = json.loads(executor.execute("apply_experimental_method", {"candidate_id": trial["candidate_id"]}))
    assert result["accepted"] and state.current_ref.version == "V2"
    assert calls[2]["rows"] == 4 and calls[2]["code"] == CODE
    assert calls[2]["image_id"] == "sha256:tested"
    assert state.manager.load(state.current_ref).amount.tolist() == [10, 20, 20, 40]
    record = state.manager.get_changelog("dirty").entries[-1]
    assert record.metadata["experiment"]["code_hash"] == trial["code_hash"]
    assert trial["candidate_id"] in record.metadata["evidence_ids"]
    assert Path(state.source_ref.path).read_bytes() == original


def test_full_data_failure_rejects_sample_success_without_mutating_working_copy(session, monkeypatch):
    state, executor, evidence = session
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner([], fail_full=True))
    trial = json.loads(executor.execute("experiment_cleaning_method", request(evidence)))
    assert trial["tested"]
    result = json.loads(executor.execute("apply_experimental_method", {"candidate_id": trial["candidate_id"]}))
    assert not result["accepted"] and state.current_ref.version == "V1"
    assert not result["details"]["full_data_effect"]["accepted"]
    assert not state.manager.get_changelog("dirty").entries[-1].success


@pytest.mark.parametrize("change", ["code", "version", "dataset_bytes"])
def test_changed_code_or_input_requires_a_new_experiment(session, monkeypatch, change):
    state, executor, evidence = session
    calls = []
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner(calls))
    trial = json.loads(executor.execute("experiment_cleaning_method", request(evidence)))
    if change == "code":
        Path(state.experiments[trial["candidate_id"]]["code_path"]).write_text(CODE + "\n# changed", encoding="utf-8")
    elif change == "version":
        executor.execute("trim_whitespace", {"columns": ["customer"]})
    else:
        with Path(state.current_ref.path).open("a", encoding="utf-8") as stream:
            stream.write("e,$50\n")
    result = json.loads(executor.execute("apply_experimental_method", {"candidate_id": trial["candidate_id"]}))
    assert not result["accepted"]
    assert len(calls) == 2
    assert "changed" in result["error"]


def test_unavailable_runtime_is_a_failed_trial_with_no_host_fallback(session, monkeypatch):
    state, executor, evidence = session
    monkeypatch.setattr(experiments, "run_isolated_transform", lambda *a, **k: {
        "success": False, "error": "Docker unavailable", "setup": experiments.BUILD_COMMAND})
    trial = json.loads(executor.execute("experiment_cleaning_method", request(evidence)))
    assert not trial["tested"] and state.current_ref.version == "V1"
    assert trial["trials"][0]["setup"] == experiments.BUILD_COMMAND
    result = json.loads(executor.execute("apply_experimental_method", {"candidate_id": trial["candidate_id"]}))
    assert not result["accepted"] and state.current_ref.version == "V1"


def test_syntax_error_is_feedback_for_revision_not_an_agent_crash(session, monkeypatch):
    state, executor, evidence = session
    def unexpected(*a, **k):
        raise AssertionError("Invalid code must not reach the sandbox")
    monkeypatch.setattr(experiments, "run_isolated_transform", unexpected)
    arguments = request(evidence)
    arguments["code"] = "def transform(df):\n    return ("
    result = json.loads(executor.execute("experiment_cleaning_method", arguments))
    assert not result["success"] and "Invalid candidate Python" in result["error"]
    assert state.current_ref.version == "V1" and not state.experiments


def test_methods_cannot_change_unselected_columns_or_remove_rows(session, monkeypatch):
    state, executor, evidence = session
    def run(frame, *args, **kwargs):
        after = frame.copy()
        after["customer"] = "changed"
        return {"success": True, "df": after, "image_id": "sha256:test"}
    monkeypatch.setattr(experiments, "run_isolated_transform", run)
    trial = json.loads(executor.execute("experiment_cleaning_method", request(evidence)))
    assert not trial["tested"]
    assert any(r["rule_name"] == "untouched:customer" and not r["passed"] for r in trial["trials"][0]["effect"]["rules"])
    before = state.manager.load(state.current_ref)
    assert not experiments.assess_method(before, before.iloc[:1], ["amount"], [])["accepted"]


def test_runner_refuses_missing_docker_instead_of_executing_on_host(tmp_path, monkeypatch):
    import docker
    monkeypatch.setattr(docker, "from_env", lambda **kw: (_ for _ in ()).throw(RuntimeError("No daemon")))
    sentinel = tmp_path / "must_not_exist.txt"
    code = f"def transform(df):\n    open({str(sentinel)!r}, 'w').write('bad')\n    return df\n"
    result = experiments.run_isolated_transform(pd.DataFrame({"a": [1]}), code)
    assert not result["success"] and not sentinel.exists()


def test_container_is_resource_limited_and_has_no_network_or_host_mounts(monkeypatch):
    import docker
    output = pd.DataFrame({"a": [1]}).to_json(orient="table").encode()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        member = tarfile.TarInfo("output.json")
        member.size = len(output)
        bundle.addfile(member, io.BytesIO(output))
    calls = {}
    class Container:
        def start(self): pass
        def put_archive(self, path, data): calls["input_path"] = path
        def wait(self, **kwargs): return {"StatusCode": 0}
        def logs(self, **kwargs): return b"repeatable"
        def get_archive(self, path): return [archive.getvalue()], {}
        def remove(self, **kwargs): calls["removed"] = kwargs
    def create(*args, **kwargs):
        calls.update(kwargs)
        return Container()
    client = SimpleNamespace(images=SimpleNamespace(get=lambda image: SimpleNamespace(id="sha256:pinned")),
                             containers=SimpleNamespace(create=create), close=lambda: None)
    monkeypatch.setattr(docker, "from_env", lambda **kw: client)
    result = experiments.run_isolated_transform(pd.DataFrame({"a": [1]}), "def transform(df):\n    return df\n")
    assert result["success"]
    assert calls["network_disabled"] and calls["read_only"]
    assert calls["cap_drop"] == ["ALL"] and calls["user"] == "65534:65534"
    assert "volumes" not in calls and "mounts" not in calls
    assert calls["mem_limit"] and calls["pids_limit"] and calls["nano_cpus"]
    assert calls["removed"] == {"force": True}


def test_llm_can_invent_test_and_promote_a_method_through_registered_tools(tmp_path, monkeypatch):
    from agents.dataCleaning_agent import DataCleaningAgent
    source = tmp_path / "dirty.csv"
    pd.DataFrame({"customer": ["a", "b", "c", "d"], "amount": ["$10", "$20", None, "$40"]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 4, "columns": 2},
              "column_profiles": {"amount": {"dtype": "str", "missing_count": 1, "etl_cast_to": "numeric"}}}
    calls = []
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner(calls))
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {"selected": "docker"})
    turns = []
    def respond(messages, *args, **kwargs):
        turn = len(turns)
        turns.append(turn)
        if turn == 0:
            name, arguments = "inspect_column", {"column": "amount"}
        elif turn == 1:
            name, arguments = "experiment_cleaning_method", request("event-1")
        elif turn == 2:
            result = json.loads(next(m["content"] for m in reversed(messages) if m["role"] == "tool"))
            name, arguments = "apply_experimental_method", {"candidate_id": result["candidate_id"]}
        else:
            name, arguments = "finish", {"summary": "Tested a generated method and validated its full-data result"}
        return {"content": None, "tool_calls": [{"id": str(turn), "name": name, "arguments": arguments}]}
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path / "runs", use_llm=True).run(report)
    assert result.validation.all_passed and result.final_dataset.version == "V2"
    assert len(result.metadata["experiments"]) == 1
    assert len(calls) == 3  # development, holdout, then full data
    assert result.change_log.entries[0].operation == "apply_experimental_method"
    assert Path(result.metadata["result_path"]).is_file()


def test_trial_ui_shows_generated_code_results_and_promotion_requirements(session, monkeypatch):
    import socket
    from streamlit.testing.v1 import AppTest
    timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(2)
        pair = socket.socketpair()
        for connection in pair:
            connection.close()
    except OSError:
        pytest.skip("Streamlit AppTest requires local socketpair support")
    finally:
        socket.setdefaulttimeout(timeout)
    state, executor, evidence = session
    monkeypatch.setattr(experiments, "run_isolated_transform", trusted_test_runner([]))
    executor.execute("experiment_cleaning_method", request(evidence))
    event = state.events[-1]
    app = AppTest.from_string(
        "import json\nfrom dashboard.cleaning_review import render_event\n"
        f"render_event(json.loads({json.dumps(event)!r}))\n"
    ).run(timeout=15)
    assert not app.exception
    assert any("transform(df)" in code.value for code in app.code)
    assert any("Trials passed" in item.label for item in app.expander)
    assert any("full-data checks" in item.value for item in app.info)
    assert len(app.dataframe) >= 2
