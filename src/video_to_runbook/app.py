"""The Modal app: the only module that imports modal. Files and fan-out live here."""

import secrets
import shutil
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import logfire
import modal
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic_ai import UsageLimitExceeded

from video_to_runbook import observer, runs
from video_to_runbook.config import get_settings
from video_to_runbook.frames import probe_duration
from video_to_runbook.models import RunMeta, RunStatus
from video_to_runbook.observer import ObserverDeps
from video_to_runbook.render import render_fragment
from video_to_runbook.tracing import setup_logfire, trace_url

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("ffmpeg")
    .uv_pip_install(
        "fastapi[standard]>=0.115.0",
        "jinja2>=3.1.0",
        "logfire>=5.1.0",
        "pydantic-ai>=2.46.0",
        "pydantic-settings>=2.15.0",
    )
    .add_local_dir("src/video_to_runbook", "/root/video_to_runbook")
)
volume = modal.Volume.from_name("video-to-runbook-data", create_if_missing=True)
SECRETS = [
    modal.Secret.from_name("gemini", required_keys=["GEMINI_API_KEY"]),
    modal.Secret.from_name("logfire"),
]
DATA = "/data"

app = modal.App("video-to-runbook", image=image, volumes={DATA: volume}, secrets=SECRETS)

if not modal.is_local():
    setup_logfire()


# Gemini refuses requests from some regions ("User location is not supported"), so the
# functions that call it stay in the US.
GEMINI_REGION = "us"


@app.function(timeout=900, region=GEMINI_REGION)
async def observe(run_id: str) -> None:
    await volume.reload.aio()
    run_dir = runs.run_dir(get_settings().data_dir, run_id)
    meta = runs.read_meta(run_dir)
    meta.state = "watching"
    meta.trace_url = trace_url(run_id)
    runs.write_meta(run_dir, meta)
    await volume.commit.aio()
    with logfire.span("runbook", run_id=run_id, video=meta.filename):
        deps = ObserverDeps(
            run_id=run_id, video_path=run_dir / "video.mp4", duration_s=meta.duration_s
        )
        try:
            result = await observer.observe(deps)
        except UsageLimitExceeded:
            logfire.error("call cap reached", run_id=run_id, phase="observer")
            meta.state = "failed"
            meta.error = "call cap reached in observer"
        except Exception as exc:  # noqa: BLE001  the run must end failed, never stay watching
            meta.state = "failed"
            meta.error = f"{type(exc).__name__}: {exc}"
        else:
            runs.write_runbook(run_dir, result.runbook)
            meta.observer_requests = result.requests
            meta.observer_input_tokens = result.input_tokens
            meta.observer_output_tokens = result.output_tokens
            meta.state = "done"  # validation fan-out arrives with validate_step
        meta.finished_at = datetime.now(UTC)
        runs.write_meta(run_dir, meta)
        await volume.commit.aio()


@app.function()
@modal.asgi_app()
def web() -> FastAPI:
    settings = get_settings()
    api = FastAPI()
    index = (files("video_to_runbook") / "static" / "index.html").read_text()

    def run_dir_or_404(run_id: str) -> Path:
        volume.reload()
        run_dir = runs.run_dir(settings.data_dir, run_id)
        if not (run_dir / "meta.json").exists():
            raise HTTPException(status_code=404, detail="unknown run")
        return run_dir

    @api.get("/", response_class=HTMLResponse)
    def page() -> str:
        return index

    @api.post("/runs", status_code=202)
    async def ingest(file: UploadFile, tamper_step: int | None = Form(None)) -> dict[str, str]:
        if not (file.content_type or "").startswith("video/"):
            raise HTTPException(status_code=415, detail="only video/* uploads are accepted")
        if tamper_step is not None and tamper_step < 1:
            raise HTTPException(status_code=422, detail="tamper_step must be a positive int")
        data = await file.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(
                status_code=413, detail=f"uploads are limited to {settings.max_upload_mb} MB"
            )
        run_id = secrets.token_hex(6)
        run_dir = runs.run_dir(settings.data_dir, run_id)
        run_dir.mkdir(parents=True)
        video = run_dir / "video.mp4"
        video.write_bytes(data)
        meta = RunMeta(
            run_id=run_id,
            filename=file.filename or "recording.mp4",
            duration_s=probe_duration(video),
            created_at=datetime.now(UTC),
            tamper_step=tamper_step,
            state="uploaded",
        )
        runs.write_meta(run_dir, meta)
        await volume.commit.aio()
        await observe.spawn.aio(run_id)
        return {"run_id": run_id}

    @api.get("/status/{run_id}")
    def status(run_id: str) -> RunStatus:
        return runs.read_status(run_dir_or_404(run_id))

    @api.get("/runs/{run_id}/video")
    def video(run_id: str) -> FileResponse:
        local = Path(f"/tmp/{run_id}.mp4")
        if not local.exists():
            shutil.copyfile(run_dir_or_404(run_id) / "video.mp4", local)
        return FileResponse(local, media_type="video/mp4")

    @api.get("/runs/{run_id}/runbook.html", response_class=HTMLResponse)
    def fragment(run_id: str) -> str:
        return render_fragment(runs.read_status(run_dir_or_404(run_id)))

    return api
