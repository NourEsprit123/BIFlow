"""Exercise the real authenticated pages and dataset selection across reruns."""
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIRTY_SALES = str((ROOT / "data/raw/dirty_sales_test.csv").resolve())


@pytest.fixture
def app():
    previous = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(2)
        pair = socket.socketpair()
        for item in pair:
            item.close()
    except OSError:
        pytest.skip("Streamlit AppTest requires local socketpair support")
    finally:
        socket.setdefaulttimeout(previous)
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "dashboard" / "app.py"))
    page.session_state["authenticated_user"] = {"full_name": "UI Tester", "email": "ui@example.test"}
    page.run(timeout=20)
    page.switch_page("pages/1_Overview.py").run(timeout=30)
    assert not page.exception
    return page


def test_dataset_picker_changes_active_data_for_every_page(app):
    app.switch_page("pages/A1_Profiling.py").run(timeout=30)
    assert not app.exception
    picker = app.selectbox(key="workspace_dataset_picker")
    assert len(picker.options) >= 2
    picker.select(DIRTY_SALES).run(timeout=30)
    assert not app.exception
    assert app.session_state["workspace_dataset_path"] == DIRTY_SALES
    # The team's pages read current_dataset_path; both keys follow the picker.
    assert app.session_state["current_dataset_path"] == DIRTY_SALES
    app.switch_page("pages/A1_Cleaning.py").run(timeout=30)
    assert not app.exception
    assert app.selectbox(key="workspace_dataset_picker").value == DIRTY_SALES


def test_stepper_lists_the_four_agents_in_pipeline_order(app):
    steps = [b.label for b in app.button if b.key and b.key.startswith("agent_pipeline_top_btn_")]
    assert [label.split("· ", 1)[1] for label in steps] == ["Data Profiling", "Data Cleaning", "BI Analyst", "XAI Auditor"]


def test_profile_button_runs_on_selected_dataset_and_reports_fallback(app, monkeypatch):
    monkeypatch.setattr("dashboard.workspace.load_saved_profile", lambda path: None)
    monkeypatch.setattr("workspace.load_saved_profile", lambda path: None)
    calls = []
    def audit(self, path):
        calls.append(path)
        return {"profile": {"rows": 30, "columns": 9}, "health": {},
                "profiling_report": {"metadata": {"llm_status": "fallback"}}}
    monkeypatch.setattr("agents.data_engineering_agent.DataEngineeringAgent.run_audit", audit)
    app.switch_page("pages/A1_Profiling.py").run(timeout=30)
    app.selectbox(key="workspace_dataset_picker").select(DIRTY_SALES).run(timeout=30)
    app.button(key="btn_run_direct_prof").click().run(timeout=30)
    assert not app.exception
    assert calls == [DIRTY_SALES]
    assert any("rule-based fallback" in item.value for item in app.warning)


def test_team_pages_open_with_the_merged_navigation(app):
    for page in ("pages/5_BI_Analysis.py", "pages/6_Audit_XAI.py", "pages/3_Workflows.py", "pages/2_Datasets.py"):
        app.switch_page(page).run(timeout=30)
        assert not app.exception, page


def test_cleaning_run_reports_its_result_on_the_cleaning_page(app, monkeypatch):
    finished = SimpleNamespace(
        final_dataset=SimpleNamespace(version="V3"),
        change_log=SimpleNamespace(successful_ops=lambda: [1, 2]),
        metadata={"mode": "llm"}, unresolved_issues=[],
        validation=SimpleNamespace(all_passed=True, status=SimpleNamespace(value="passed")),
    )
    monkeypatch.setattr("dashboard.cleaning_review.run_cleaning_with_progress", lambda path: finished)
    app.switch_page("pages/A1_Cleaning.py").run(timeout=30)
    app.button(key="cleaner_run").click().run(timeout=30)
    assert not app.exception
    assert any("Cleaning finished in V3; 2 changes applied" in item.value for item in app.success)
