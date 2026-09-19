from collections.abc import Iterator
from pathlib import Path

import pytest

from video_to_runbook.config import get_settings
from video_to_runbook.tracing import trace_url


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)  # keep the repo's .env out of the test
    monkeypatch.delenv("LOGFIRE_PROJECT_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_trace_url_is_none_without_project_url() -> None:
    assert trace_url("3f9a1c2b7d4e") is None


def test_trace_url_filters_by_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGFIRE_PROJECT_URL", "https://logfire-eu.pydantic.dev/me/proj")
    get_settings.cache_clear()
    assert (
        trace_url("3f9a1c2b7d4e") == "https://logfire-eu.pydantic.dev/me/proj"
        "?q=attributes-%3E%3E%27run_id%27%20%3D%20%273f9a1c2b7d4e%27"
    )
