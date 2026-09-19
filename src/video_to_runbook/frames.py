import subprocess
from collections.abc import Sequence
from pathlib import Path

# Container duration can exceed the last video frame (audio overhang, frame period),
# so the end clamp stays this far inside it.
END_MARGIN_S = 0.25


def probe_duration(video: Path) -> float:
    """Return the container duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video}: {result.stderr.strip()}")
    return float(result.stdout.strip())


def extract_frames(
    video: Path,
    timestamp_s: float,
    duration_s: float,
    offsets: Sequence[float] = (-1.0, 0.0, 1.0),
) -> list[bytes]:
    """Return one PNG per offset around `timestamp_s`, clamped inside the video."""
    frames: list[bytes] = []
    for offset in offsets:
        t = min(max(timestamp_s + offset, 0.0), duration_s - END_MARGIN_S)
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-c:v",
                "png",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed at {t:.3f} s of {video}: {result.stderr.decode().strip()}"
            )
        if not result.stdout:
            raise RuntimeError(f"ffmpeg produced no frame at {t:.3f} s of {video}")
        frames.append(result.stdout)
    return frames
