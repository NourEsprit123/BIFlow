from types import SimpleNamespace
from html import escape

from dashboard.pipeline import AGENTS, pipeline_html, pipeline_state


def test_all_eight_agents_are_present_but_only_integrated_agents_are_available():
    stages, summary = pipeline_state()
    assert len(stages) == 8
    assert {s["key"] for s in stages if s["available"]} == {"profiler", "cleaner", "etl"}
    assert [s["key"] for s in stages if s["current"]] == ["profiler"]
    assert "Data Profiling" in summary
    assert all(s["state"] == "locked" for s in stages if not s["available"])


def test_cleaning_and_etl_share_validation_status():
    stages, _ = pipeline_state(profile={"profile": {"rows": 2}})
    assert next(s for s in stages if s["current"])["key"] == "cleaner"
    failed = SimpleNamespace(validation=SimpleNamespace(all_passed=False))
    stages, summary = pipeline_state(profile={}, cleaning=failed)
    assert next(s for s in stages if s["key"] == "cleaner")["state"] == "review"
    assert "review required" in summary
    assert next(s for s in stages if s["key"] == "profiler")["state"] == "complete"
    passed = SimpleNamespace(validation=SimpleNamespace(all_passed=True))
    stages, summary = pipeline_state(profile={}, cleaning=passed)
    assert "Cleaning & ETL validated" in summary
    assert next(s for s in stages if s["key"] == "etl")["state"] == "complete"
    assert next(s for s in stages if s["key"] == "cleaner")["state"] == "complete"


def test_etl_runs_with_cleaning_and_requires_review_when_validation_fails():
    stages, _ = pipeline_state(running="cleaner")
    etl = next(s for s in stages if s["key"] == "etl")
    assert etl["state"] == "current" and "Cleaning Agent" in etl["detail"]
    failed = SimpleNamespace(validation=SimpleNamespace(all_passed=False))
    stages, _ = pipeline_state(cleaning=failed)
    assert next(s for s in stages if s["key"] == "etl")["state"] == "review"


def test_pipeline_html_has_accessible_current_step_and_every_agent_name():
    html = pipeline_html()
    assert html.count('aria-current="step"') == 1
    assert 'aria-label="BIFlow agent pipeline"' in html
    assert all(escape(label) in html for _, label, _, _ in AGENTS)
