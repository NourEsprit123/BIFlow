"""Host approve/reject decisions are applied to a finished run without calling the model."""
import json

import pandas as pd
import pytest

from agents.dataCleaning_agent import DataCleaningAgent
from dataCleaningTools import approvals
from tests.test_cleaning_loop import action


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr("agents.dataCleaning_agent.sandbox_status", lambda: {})


def finished_run(tmp_path, monkeypatch, outlier_action="cap"):
    """One outlier task whose IQR change passes its trial and stops at approval."""
    source = tmp_path / "orders.csv"
    pd.DataFrame({"amount": [10.0, 11.0, 12.0, 13.0, 1000.0]}).to_csv(source, index=False)
    report = {"dataset_ref": {"file_path": str(source), "file_name": source.name, "rows": 5, "columns": 1},
              "column_profiles": {"amount": {"dtype": "float"}}, "outlier_columns": ["amount"]}
    def respond(messages, tools, **kwargs):
        task = json.loads(messages[-1]["content"])["cleaning_focus"]["task"]
        if not task:
            return action("finish", summary="Outlier cap awaits approval")
        return action("test_builtin", hypothesis="Cap the extreme amount", columns=["amount"],
                      operation="handle_outliers", parameters={"action": outlier_action, "method": "iqr"})
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", respond)
    agent = DataCleaningAgent(data_root=tmp_path / "versions", use_llm=True)
    return agent, agent.run(report)


def no_model(*args, **kwargs):
    raise AssertionError("Resolving approvals must not call the model")


def test_pending_approval_lists_the_change_and_its_impact(tmp_path, monkeypatch):
    _, result = finished_run(tmp_path, monkeypatch)
    [item] = approvals.pending(result)
    assert item["operation"] == "handle_outliers" and item["impact"]["rows_changed"] == 1
    assert result.validation.status.value == "partial" and result.final_dataset.version == "V1"


def test_approving_applies_the_change_and_revalidates(tmp_path, monkeypatch):
    agent, result = finished_run(tmp_path, monkeypatch)
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    [item] = approvals.pending(result)
    resolved = agent.resolve_approvals(result, {item["step_id"]: "approve"})
    assert resolved.final_dataset.version == "V2" and resolved.validation.all_passed
    assert not approvals.pending(resolved) and not resolved.metadata["pending_approvals"]
    assert resolved.metadata["host_decisions"][0]["applied"]
    capped = pd.read_csv(resolved.final_dataset.path)["amount"]
    assert capped.max() < 1000 and capped.iloc[:4].tolist() == [10.0, 11.0, 12.0, 13.0]
    assert any(e["origin"] == "host_approval" and e["tool"] == "apply_candidate" for e in resolved.metadata["events"])


def test_rejecting_keeps_the_data_and_closes_the_task(tmp_path, monkeypatch):
    agent, result = finished_run(tmp_path, monkeypatch)
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    [item] = approvals.pending(result)
    resolved = agent.resolve_approvals(result, {item["step_id"]: "reject"})
    task = next(t for t in resolved.metadata["cleaning_tasks"] if t["category"] == "outliers")
    assert task["status"] == "reviewed" and task["reason"].startswith("Rejected by host")
    assert resolved.final_dataset.version == "V1" and resolved.validation.all_passed
    assert pd.read_csv(resolved.final_dataset.path)["amount"].max() == 1000.0


def test_undecided_items_stay_pending(tmp_path, monkeypatch):
    agent, result = finished_run(tmp_path, monkeypatch)
    resolved = agent.resolve_approvals(result, {})
    assert len(approvals.pending(resolved)) == 1 and resolved.validation.status.value == "partial"


def test_dashboard_panel_sends_the_chosen_decision(tmp_path, monkeypatch):
    import socket
    from streamlit.testing.v1 import AppTest
    previous_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(2)
        for connection in socket.socketpair():
            connection.close()
    except (OSError, TimeoutError):
        pytest.skip("Streamlit AppTest requires local socketpair support")
    finally:
        socket.setdefaulttimeout(previous_timeout)
    _, result = finished_run(tmp_path, monkeypatch)
    [item] = approvals.pending(result)
    sent = tmp_path / "sent.json"
    script = (
        "import json\n"
        "from pathlib import Path\n"
        "from unittest.mock import patch\n"
        "from dataCleaningTools.models import CleaningResult\n"
        "from dashboard.cleaning_review import render_cleaning_result\n"
        f"result = CleaningResult.model_validate_json({result.model_dump_json()!r})\n"
        "def resolve(path, cleaning, decisions):\n"
        f"    Path({str(sent)!r}).write_text(json.dumps(decisions))\n"
        "    return cleaning\n"
        "with patch('dashboard.workspace.resolve_cleaning_approvals', side_effect=resolve):\n"
        "    with patch('dashboard.workspace.selected_dataset_path', return_value=Path('orders.csv')):\n"
        "        render_cleaning_result(result)\n"
    )
    app = AppTest.from_string(script).run(timeout=15)
    assert not app.exception
    assert any("awaiting your approval (1)" in h.value for h in app.subheader)
    assert any("Would change 1 of 5 rows" in c.value for c in app.caption)
    app.radio(key=f"cleaning_review_approval_{item['step_id']}").set_value("Approve").run(timeout=15)
    app.button(key="cleaning_review_apply_approvals").click().run(timeout=15)
    assert json.loads(sent.read_text()) == {item["step_id"]: "approve"}


def test_blanks_left_by_an_approved_change_become_a_decision_not_a_failure(tmp_path, monkeypatch):
    from dataCleaningTools.decisions import open_decisions
    agent, result = finished_run(tmp_path, monkeypatch, outlier_action="set_missing")
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    [item] = approvals.pending(result)
    resolved = agent.resolve_approvals(result, {item["step_id"]: "approve"})
    # The blank opens missing-value work that no model will run after the run; the host settles it.
    assert resolved.validation.status.value == "partial"
    [decision] = open_decisions(resolved)
    assert decision["key"] == "amount" and decision["missing"] == 1 and decision["can_fill"]
    accepted = agent.resolve_decisions(resolved, {"amount": {"action": "accept", "note": "Blank the extreme amount"}})
    assert accepted.validation.all_passed and not open_decisions(accepted)


def test_the_final_version_is_published_for_the_bi_analyst_and_again_after_approval(tmp_path, monkeypatch):
    agent, result = finished_run(tmp_path, monkeypatch)
    agent.publish_root = tmp_path / "cleaned"
    published = tmp_path / "cleaned" / "orders_cleaned.csv"
    monkeypatch.setattr("agents.dataCleaning_agent.chat_with_tools", no_model)
    [item] = approvals.pending(result)
    resolved = agent.resolve_approvals(result, {item["step_id"]: "approve"})
    assert resolved.metadata["published_path"] == str(published)
    assert pd.read_csv(published).equals(pd.read_csv(resolved.final_dataset.path))
    assert pd.read_csv(published)["amount"].max() < 1000  # the approved cap is in the published file
