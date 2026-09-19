from urllib.parse import quote

import logfire

from video_to_runbook.config import get_settings

_configured = False


def setup_logfire() -> None:
    """Configure Logfire once per process and instrument Pydantic AI."""
    global _configured
    if _configured:
        return
    logfire.configure(
        send_to_logfire="if-token-present",
        service_name="video-to-runbook",
        console=False,
    )
    logfire.instrument_pydantic_ai(include_binary_content=False)
    _configured = True


def trace_url(run_id: str) -> str | None:
    """Link to the run's spans in the Logfire project, if one is configured."""
    url = get_settings().logfire_project_url
    if not url:
        return None
    return f"{url}?q=" + quote(f"attributes->>'run_id' = '{run_id}'")
