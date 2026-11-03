"""Video processing utilities using ffmpeg.

Handles local files and remote URLs. For URLs, the video is downloaded to the
output directory before processing so ffmpeg and Whisper can operate on it.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional


def _run_ffmpeg(cmd: List[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() or "Unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg command failed: {stderr}")


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _download_video(url: str, dest: Path) -> None:
    print(f"Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"Saved to {dest}")


SOURCE_URL_MARKER = ".video_source_url"


def download_for_embed(url: str, dest_dir: Path) -> Path:
    """Download url into dest_dir, or reuse an existing cached copy if the
    same url was already downloaded there.

    Shared by prepare()'s transcription source and by --video-mode embed
    builds that reference a remote master, so a multi-hundred-MB video isn't
    downloaded twice across a prepare + build pair pointed at the same
    output directory.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    marker = dest_dir / SOURCE_URL_MARKER
    suffix = Path(url.split("?")[0]).suffix or ".mp4"
    local_copy = dest_dir / f"_source{suffix}"

    if (
        local_copy.exists()
        and marker.exists()
        and marker.read_text(encoding="utf-8").strip() == url
    ):
        return local_copy

    _download_video(url, local_copy)
    marker.write_text(url, encoding="utf-8")
    return local_copy


def process_video(
    video_source: str,
    work_dir: str,
    segment_duration: int = 360,
    no_segment: bool = False,
) -> Dict[str, object]:
    """Process a video from a local path or URL, writing artefacts to work_dir.

    Args:
        video_source: Local file path or HTTP(S) URL.
        work_dir: Directory for intermediate artefacts.
        segment_duration: Seconds per ffmpeg segment.
        no_segment: Skip segmentation (useful for URL-sourced or short videos).

    Returns:
        Dict with keys ``audio`` (str), ``subtitles`` (str|None),
        ``segments`` (list[str]).

    Raises:
        FileNotFoundError: Local file not found.
        EnvironmentError: ffmpeg not on PATH.
        RuntimeError: ffmpeg processing error.
    """
    out_dir = Path(work_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if shutil.which("ffmpeg") is None:
        raise EnvironmentError("ffmpeg is required but was not found on PATH")

    if _is_url(video_source):
        src = download_for_embed(video_source, out_dir)
    else:
        src = Path(video_source)
        if not src.exists():
            raise FileNotFoundError(f"Video file not found: {video_source}")

    # Extract audio for Whisper transcription
    audio_path = out_dir / "audio.mp3"
    _run_ffmpeg([
        "ffmpeg", "-v", "error", "-i", str(src),
        "-vn", "-acodec", "mp3", str(audio_path),
    ])

    # Extract embedded subtitles (optional; many videos have none)
    subtitles_path: Optional[Path] = out_dir / "subtitles.vtt"
    try:
        _run_ffmpeg([
            "ffmpeg", "-v", "error", "-i", str(src),
            "-map", "0:s:0?", "-f", "webvtt", str(subtitles_path),
        ])
    except RuntimeError as exc:
        if "Output file does not contain any stream" in str(exc):
            subtitles_path = None
        else:
            raise

    # Segment video into fixed-length chunks
    segments: List[str] = []
    if not no_segment:
        segment_template = out_dir / "segment_%03d.mp4"
        _run_ffmpeg([
            "ffmpeg", "-v", "error", "-i", str(src),
            "-map", "0", "-c", "copy",
            "-f", "segment", "-segment_time", str(segment_duration),
            "-reset_timestamps", "1",
            str(segment_template),
        ])
        segments = [str(p) for p in sorted(out_dir.glob("segment_*.mp4"))]
        if not segments:
            raise RuntimeError("ffmpeg did not produce any segments")

    return {
        "audio": str(audio_path),
        "subtitles": str(subtitles_path) if subtitles_path else None,
        "segments": segments,
    }
