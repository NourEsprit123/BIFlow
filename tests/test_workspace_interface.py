"""Exercise the real authenticated pages and dataset selection across reruns."""
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
    page.switch_page("pages/1_Overview.py").run(timeout=20)
    assert not page.exception
    return page


def test_dataset_picker_changes_active_data_and_survives_navigation(app):
    picker = app.selectbox(key="workspace_dataset_picker")
    assert len(picker.options) >= 2
    selected = str((ROOT / "data/raw/dirty_sales_test.csv").resolve())
    picker.select(selected).run(timeout=20)
    assert not app.exception
    assert app.session_state["workspace_dataset_path"] == selected
    assert any("dirty_sales_test.csv" in item.value for item in app.info)
    app.switch_page("pages/4_Data_Quality.py").run(timeout=20)
    assert not app.exception
    assert app.selectbox(key="workspace_dataset_picker").value == selected


def test_agent_controls_are_visible_and_search_is_local_to_dataset_library(app):
    assert app.button(key="profiler_run").label == "Run profiling"
    assert app.button(key="cleaner_run").label == "Run cleaning"
    assert not any(item.label == "Search datasets" for item in app.text_input)
    app.switch_page("pages/2_Datasets.py").run(timeout=20)
    assert not app.exception
    app.text_input(key="dataset_library_query").set_value("dirty sales").run(timeout=20)
    assert not app.exception
    assert len([b for b in app.button if b.key and b.key.startswith("select_")]) == 1
    app.button(key="select_dirty_sales_test.csv").click().run(timeout=20)
    assert not app.exception
    assert app.session_state["workspace_dataset_path"].endswith("dirty_sales_test.csv")
    app.text_input(key="dataset_library_query").set_value("no-such-dataset").run(timeout=20)
    assert any("No matching datasets" in item.value for item in app.info)


def test_profile_button_runs_on_selected_dataset_and_updates_status(app, monkeypatch):
    calls = []
    def audit(self, path):
        calls.append(path)
        return {"profile": {"rows": 30, "columns": 9},
                "profiling_report": {"metadata": {"llm_status": "fallback"}}}
    monkeypatch.setattr("agents.data_engineering_agent.DataEngineeringAgent.run_audit", audit)
    selected = str((ROOT / "data/raw/dirty_sales_test.csv").resolve())
    app.selectbox(key="workspace_dataset_picker").select(selected).run(timeout=20)
    app.button(key="profiler_run").click().run(timeout=20)
    assert not app.exception
    assert calls == [selected]
    assert any("Fallback report" in item.value for item in app.markdown)


def test_saved_workflow_can_be_restored(app):
    app.switch_page("pages/3_Workflows.py").run(timeout=20)
    assert not app.exception
    app.checkbox(key="workflow_task_2").check().run(timeout=20)
    next(button for button in app.button if button.label == "Save as template").click().run(timeout=20)
    app.checkbox(key="workflow_task_2").uncheck().run(timeout=20)
    next(button for button in app.button if button.label == "Load saved template").click().run(timeout=20)
    assert not app.exception
    assert app.checkbox(key="workflow_task_2").value


def test_future_agents_are_visible_but_bi_and_xai_routes_and_tasks_are_locked(app):
    assert app.button(key="locked_bi_analysis").disabled
    assert app.button(key="locked_xai").disabled
    pipeline = next(item.value for item in app.markdown if 'aria-label="BIFlow agent pipeline"' in item.value)
    assert "Orchestrator" in pipeline and "ETL / Engineering" in pipeline and "Auditor / XAI" in pipeline
    app.switch_page("pages/5_BI_Analysis.py").run(timeout=20)
    assert not app.exception
    assert any("BI Analysis · Locked" in item.value for item in app.markdown)
    assert not any(item.label == "Export analysis report" for item in app.get("download_button"))
    app.switch_page("pages/6_Audit_XAI.py").run(timeout=20)
    assert not app.exception
    assert any("Explainability / XAI · Locked" in item.value for item in app.markdown)
    assert not any(item.label == "Generate audit" for item in app.button)
    app.switch_page("pages/3_Workflows.py").run(timeout=20)
    assert not app.exception
    assert app.checkbox(key="workflow_task_3").disabled and not app.checkbox(key="workflow_task_3").value
    assert app.checkbox(key="workflow_task_4").disabled and not app.checkbox(key="workflow_task_4").value
