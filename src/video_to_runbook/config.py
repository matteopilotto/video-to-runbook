from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    logfire_token: str | None = None
    logfire_project_url: str | None = None
    observer_model: str = "gemini-3.1-pro-preview"
    validator_model: str = "gemini-3.8-flash"
    planner_model: str = "google:gemini-3.5-flash"
    catalog_path: Path = Path("/root/catalog.json")
    call_cap: int = 100
    observer_request_limit: int = 4
    check_request_limit: int = 3
    observer_timeout_s: int = 180
    validator_timeout_s: int = 60
    max_upload_mb: int = 100
    data_dir: Path = Path("/data")
    frame_offsets_s: tuple[float, float, float] = (-1.0, 0.0, 1.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
