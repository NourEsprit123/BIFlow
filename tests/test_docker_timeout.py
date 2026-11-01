"""A slow Docker reply is retried, and at worst drops one task; it never disables Docker for the run."""
from types import SimpleNamespace

from dataCleaningTools import experiments
from tests.test_cleaning_loop import action
from tests.test_explicit_execution import request, sandbox
from tests.test_task_dropping import focus, run

# conftest replaces runtime_status for every test; keep the real check for the unit tests here.
real_runtime_status = experiments.runtime_status


class ReadTimeout(Exception):
    pass


def fake_docker(monkeypatch, outcomes):
    """Each from_env() call pops the next outcome: an exception to raise from ping(), or None for success."""
    timeouts = []
    def from_env(timeout):
        timeouts.append(timeout)
        outcome = outcomes.pop(0)
        def ping():
            if outcome:
                raise outcome
        return SimpleNamespace(ping=ping, close=lambda: None,
                               images=SimpleNamespace(get=lambda name: SimpleNamespace(id="sha256:test")))
    monkeypatch.setitem(__import__("sys").modules, "docker", SimpleNamespace(from_env=from_env))
    return timeouts


def test_timed_out_check_is_retried_with_the_configured_timeout(monkeypatch):
    monkeypatch.setenv("BIFLOW_DOCKER_TIMEOUT", "45")
    timeouts = fake_docker(monkeypatch, [ReadTimeout("Read timed out. (read timeout=45)"), None])
    status = real_runtime_status()
    assert status["available"] and timeouts == [45.0, 45.0]


def test_repeated_timeouts_are_reported_as_transient(monkeypatch):
    fake_docker(monkeypatch, [ReadTimeout("Read timed out."), ReadTimeout("Read timed out.")])
    status = real_runtime_status()
    assert not status["available"] and status["transient"] and status["attempts"] == 2


def test_docker_not_running_is_not_transient_and_not_retried(monkeypatch):
    timeouts = fake_docker(monkeypatch, [FileNotFoundError("The system cannot find the file specified")])
    status = real_runtime_status()
    assert not status["available"] and not status["transient"] and len(timeouts) == 1


def test_timeout_drops_one_task_and_later_tasks_still_use_docker(tmp_path, monkeypatch):
    checks = iter([{"available": False, "transient": True, "error": "Read timed out. (read timeout=30)"},
                   {"available": True, "image_id": "sha256:test", "versions": {}}])
    monkeypatch.setattr(experiments, "runtime_status", lambda: next(checks))
    monkeypatch.setattr(experiments, "run_isolated_transform", sandbox)
    offered = []
    def respond(messages, tools, **kwargs):
        task = focus(messages)
        if not task:
            return action("finish", summary="Done")
        offered.append((task["category"], "test_generated" in {t["function"]["name"] for t in tools}))
        if task["category"] == "formatting":
            return action("test_generated", hypothesis="Trim city labels", columns=["city"],
                          code="def transform(df):\n    return df")
        if task["category"] == "types":
            return action("test_generated", **request())
        return action("flag_for_review", columns=task["columns"], reason="Not part of this test")
    result = run(tmp_path, monkeypatch, respond)
    assert [d["reason"] for d in result.metadata["task_drops"]] == ["sandbox_timeout"]
    assert ("types", True) in offered  # generated code is still offered after the timeout
    assert result.final_dataset.version == "V2"  # the flag conversion ran in the sandbox and was applied
