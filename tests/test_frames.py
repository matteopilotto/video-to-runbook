import subprocess
from pathlib import Path

import pytest

from video_to_runbook.frames import extract_frames, probe_duration

PNG_MAGIC = b"\x89PNG"


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("frames") / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=64x64:rate=5",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def test_probe_duration(clip: Path) -> None:
    assert probe_duration(clip) == pytest.approx(3.0, abs=0.1)


def test_extract_three_png_frames(clip: Path) -> None:
    frames = extract_frames(clip, 1.5, 3.0)
    assert len(frames) == 3
    assert all(frame.startswith(PNG_MAGIC) for frame in frames)


def test_clamps_to_start(clip: Path) -> None:
    frames = extract_frames(clip, 0.0, 3.0)
    assert len(frames) == 3
    assert all(frame.startswith(PNG_MAGIC) for frame in frames)


def test_clamps_to_end(clip: Path) -> None:
    frames = extract_frames(clip, 3.0, 3.0)
    assert len(frames) == 3
    assert all(frame.startswith(PNG_MAGIC) for frame in frames)
