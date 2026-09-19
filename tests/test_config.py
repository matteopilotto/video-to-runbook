from pathlib import Path

import pytest

from video_to_runbook.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_settings.cache_clear()


def test_defaults_load_without_environment() -> None:
    s = Settings()
    assert s.observer_model == "gemini-3.1-pro-preview"
    assert s.validator_model == "gemini-3.8-flash"
    assert s.call_cap == 60
    assert s.observer_request_limit == 4
    assert s.check_request_limit == 3
    assert s.max_upload_mb == 100
    assert s.data_dir == Path("/data")
    assert s.frame_offsets_s == (-1.0, 0.0, 1.0)
    assert s.gemini_api_key == ""


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVER_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    s = get_settings()
    assert s.observer_model == "gemini-2.5-pro"
    assert s.gemini_api_key == "abc"
