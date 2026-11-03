"""The cleaning run view: plain summary, then the rendered layout."""
import socket

import pytest

from dataCleaningTools.run_summary import summarize
from tests.test_host_approvals import finished_run, offline  # noqa: F401  (fixture)


def test_summary_of_a_run_waiting_for_approval(tmp_path, monkeypatch):
    _, result = finished_run(tmp_path, monkeypatch)
    summary = summarize(result)
    assert summary["status"] == "partial" and summary["needs_you"] == 1
    assert summary["kpis"] == {"applied": 0, "awaiting": 1, "dropped_or_blocked": 0, "set_to_missing": 0}
    outliers = next(c for c in summary["categories"] if c["key"] == "outliers")
    assert outliers["state"] == "waiting" and outliers["waiting"] == 1
    assert [row["status"] for row in summary["board"]] == ["awaiting_approval"]
    assert summary["trail"] == [{"version": "V0", "label": "original"}]


def test_summary_after_approval_shows_the_new_version_and_changed_values(tmp_path, monkeypatch):
    agent, result = finished_run(tmp_path, monkeypatch)
    from dataCleaningTools import approvals
    [item] = approvals.pending(result)
    summary = summarize(agent.resolve_approvals(result, {item["step_id"]: "approve"}))
    assert summary["status"] == "passed" and summary["needs_you"] == 0
    assert summary["stop"] == "Finished; your decisions were applied"
    assert [step["version"] for step in summary["trail"]] == ["V0", "V1", "V2"] and summary["trail"][-1]["approved"]
    assert summary["health"] == [{"column": "amount", "rows_before": 5, "rows_after": 5, "missing_before": 0,
                                  "missing_after": 0, "dtype_before": "float64", "dtype_after": "float64",
                                  "values_changed": 1}]


def test_view_renders_overview_board_and_grouped_trace(tmp_path, monkeypatch):
    previous = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(2)
        for connection in socket.socketpair():
            connection.close()
    except (OSError, TimeoutError):
        pytest.skip("Streamlit AppTest requires local socketpair support")
    finally:
        socket.setdefaulttimeout(previous)
    from streamlit.testing.v1 import AppTest
    _, result = finished_run(tmp_path, monkeypatch)
    script = ("from dataCleaningTools.models import CleaningResult\n"
              "from dashboard.cleaning_review import render_cleaning_result\n"
              f"render_cleaning_result(CleaningResult.model_validate_json({result.model_dump_json()!r}))\n")
    app = AppTest.from_string(script).run(timeout=15)
    assert not app.exception
    assert [h.value for h in app.subheader] == ["Cleaning run", "Changes awaiting your approval (1)"]
    assert any("Final validation: partial · 1 decision needs you: approve amount" in w.value for w in app.warning)
    html = " ".join(m.value for m in app.markdown)
    for section in ("Progress by category", "Task board", "Version trail", "Column health"):
        assert section in html
    assert any(e.label.startswith("Outliers · amount · 2 action(s) · awaiting approval") for e in app.expander)
