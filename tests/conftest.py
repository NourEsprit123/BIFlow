"""Unit tests are offline; individual runtime/provider tests override these fakes."""
import pytest


@pytest.fixture(autouse=True)
def offline_execution_boundaries(monkeypatch):
    monkeypatch.setenv("BIFLOW_CLEANING_EXPERT_ENABLED", "false")
    monkeypatch.setattr("dataCleaningTools.experiments.runtime_status",
                        lambda: {"available": True, "backend": "docker", "image_id": "sha256:test"})
