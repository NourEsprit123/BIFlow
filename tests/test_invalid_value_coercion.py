import json
from copy import deepcopy

import pandas as pd

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools import cleaning_tasks, experiments
from dataCleaningTools.effects import assess_candidate
from dataCleaningTools.models import ProfilingReport
from dataCleaningTools.tool_registry import AgentSessionState, ToolExecutor
from dataCleaningTools.versioning import DatasetVersionManager
from dataCleaningTools.working_context import initialize
from tests.test_cleaning_loop import action


def test_invalid_to_nan_is_accepted_and_all_affected_values_are_audited():
    before = pd.DataFrame({"amount": ["10", "banana", "ERROR_404"], "other": [1, 2, 3]})
    after = before.copy(); after["amount"] = pd.to_numeric(after["amount"], errors="coerce")
    effect = assess_candidate(before, after, "convert_data_types", ["amount"], {"target_type": "float"})
    assert effect["accepted"]
    assert not any(r["rule_name"].startswith("no_new_missing:") for r in effect["rules"])
    assert [cell["before"] for cell in effect["lost_values"]] == ["banana", "ERROR_404"]
    assert effect["lost_value_count"] == 2
    after.loc[0, "other"] = None
    assert not assess_candidate(before, after, "convert_data_types", ["amount"], {"target_type": "float"})["accepted"]
    assert not assess_candidate(before, after.iloc[:2], "convert_data_types", ["amount"], {"target_type": "float"})["accepted"]


def test_only_committed_nan_creates_a_missing_task(tmp_path):
    path = tmp_path / "input.csv"; pd.DataFrame({"amount": ["10", "banana"]}).to_csv(path, index=False)
    report = ProfilingReport.model_validate({"dataset_ref": {"file_path": str(path), "file_name": path.name, "rows": 2, "columns": 1},
        "column_profiles": {"amount": {"dtype": "str", "etl_cast_to": "float", "missing_count": 0}}})
    manager = DatasetVersionManager(tmp_path / "versions"); source = manager.register_original(path, dataset_id="input")
    state = AgentSessionState(manager=manager, dataset_id="input", source_ref=source, current_ref=manager.create_working_copy(source),
        required_targets={"amount": "float"}, focused_cleaning=True)
    initialize(state, report); cleaning_tasks.initialize(state); original = deepcopy(state.working_report)
    executor = ToolExecutor(state)
    trial = json.loads(executor.execute("test_builtin", {"hypothesis": "Invalid banana becomes NaN; numeric 10 remains valid",
        "columns": ["amount"], "operation": "convert_data_types", "parameters": {"target_type": "float", "errors": "coerce"}}))
    assert trial["tested"] and state.required_missing == []
    assert not any(t["category"] == "missing" for t in state.cleaning_tasks)
    result = json.loads(executor.execute("apply_candidate", {"candidate_id": trial["candidate_id"], "assessment": "Numeric value retained; invalid token audited as NaN"}))
    assert result["success"] and state.required_missing == ["amount"]
    assert cleaning_tasks.active(state)["category"] == "missing"
    assert state.working_context["columns"]["amount"]["steps"]["type_conversion"]["status"] == "done"
    assert state.working_context["columns"]["amount"]["steps"]["missing_values"]["remaining"] == 1
    assert state.working_report == original
    finish = json.loads(executor.execute("finish", {"summary": "Converted", "unresolved": []}))
    assert not finish["success"]  # new NaNs cannot disappear from final validation


def test_generated_nan_is_applied_reported_and_handled_separately(tmp_path, monkeypatch):
    source = tmp_path / "input.csv"; pd.DataFrame({"amount": ["10", "banana", "20", "ERROR_404"]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 4, "columns": 1},
              "column_profiles": {"amount": {"dtype": "str", "etl_cast_to": "float", "missing_count": 0}}}
    def sandbox(frame, code, **kwargs):
        output = frame.copy(); output["amount"] = pd.to_numeric(output["amount"], errors="coerce")
        return {"success": True, "df": output, "image_id": "sha256:test", "repeatable": True}
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    requests = []
    def respond(messages, tools, **kwargs):
        focus = json.loads(messages[-1]["content"])["cleaning_focus"]; requests.append(focus)
        if len(requests) == 1:
            return action("test_generated", hypothesis="Parse numeric strings and coerce nonsensical tokens to NaN",
                columns=["amount"], code="def transform(df):\n    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')\n    return df",
                checks=[{"column": "amount", "kind": "numeric"}])
        if len(requests) == 2:
            assert focus["category"] == "missing"
            return action("test_builtin", hypothesis="Use the user-approved synthetic zero fill", columns=["amount"],
                          operation="handle_missing_values", parameters={"strategy": "fill_constant", "fill_value": 0})
        return action("finish", summary="Invalid tokens audited and missing-value handling completed")
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    result = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True).run(report)
    assert result.validation.all_passed and result.final_dataset.version == "V3"
    assert result.metadata["report_summary"]["values_coerced_to_missing"] == 2
    assert pd.read_csv(result.final_dataset.path)["amount"].tolist() == [10, 0, 20, 0]
    assert pd.read_csv(result.source_dataset.path)["amount"].tolist() == ["10", "banana", "20", "ERROR_404"]
    assert len(result.metadata["cleaning_tasks"]) == 2
    assert all(t["status"] == "done" for t in result.metadata["cleaning_tasks"])
