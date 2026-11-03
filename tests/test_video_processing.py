"""Tests for video_processing.py."""

import subprocess
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from scorm_scorcher.video_processing import SOURCE_URL_MARKER, _is_url, download_for_embed, process_video


def test_is_url():
    assert _is_url("https://example.com/video.mp4")
    assert _is_url("http://example.com/video.mp4")
    assert not _is_url("/local/path/video.mp4")
    assert not _is_url("relative/path.mp4")


def test_missing_local_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_video("/nonexistent/video.mp4", str(tmp_path))


def test_missing_local_file_reported_before_missing_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(FileNotFoundError):
        process_video("/nonexistent/video.mp4", str(tmp_path))


def test_missing_ffmpeg_raises(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(EnvironmentError, match="ffmpeg"):
        process_video(str(video), str(tmp_path))


def test_ffmpeg_audio_failure_raises(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    with patch("scorm_scorcher.video_processing.shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("scorm_scorcher.video_processing._run_ffmpeg", side_effect=RuntimeError("ffmpeg failed")):
            with pytest.raises(RuntimeError, match="ffmpeg failed"):
                process_video(str(video), str(tmp_path))


def test_url_triggers_download(tmp_path):
    with patch("scorm_scorcher.video_processing.shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("scorm_scorcher.video_processing._download_video") as mock_dl:
            with patch("scorm_scorcher.video_processing._run_ffmpeg") as mock_ffmpeg:
                # Make the downloaded file appear to exist
                fake_src = tmp_path / "_source.mp4"
                fake_src.write_bytes(b"")

                def fake_download(url, dest):
                    dest.write_bytes(b"")

                mock_dl.side_effect = fake_download
                # Suppress subtitle extraction "no stream" error gracefully
                mock_ffmpeg.side_effect = [
                    None,  # audio extraction
                    RuntimeError("Output file does not contain any stream"),  # subtitles
                    None,  # segmentation
                ]
                # Create fake segment
                (tmp_path / "segment_000.mp4").write_bytes(b"")

                result = process_video("https://example.com/v.mp4", str(tmp_path))
                mock_dl.assert_called_once()
                assert "audio" in result


def test_download_for_embed_downloads_when_uncached(tmp_path):
    with patch("scorm_scorcher.video_processing._download_video") as mock_dl:
        def fake_download(url, dest):
            dest.write_bytes(b"content")

        mock_dl.side_effect = fake_download

        result = download_for_embed("https://example.com/v.mp4", tmp_path)

        mock_dl.assert_called_once()
        assert result == tmp_path / "_source.mp4"
        assert (tmp_path / SOURCE_URL_MARKER).read_text(encoding="utf-8").strip() == "https://example.com/v.mp4"


def test_download_for_embed_reuses_cached_copy(tmp_path):
    (tmp_path / "_source.mp4").write_bytes(b"cached")
    (tmp_path / SOURCE_URL_MARKER).write_text("https://example.com/v.mp4", encoding="utf-8")

    with patch("scorm_scorcher.video_processing._download_video") as mock_dl:
        result = download_for_embed("https://example.com/v.mp4", tmp_path)

        mock_dl.assert_not_called()
        assert result == tmp_path / "_source.mp4"


def test_download_for_embed_redownloads_on_url_change(tmp_path):
    (tmp_path / "_source.mp4").write_bytes(b"old")
    (tmp_path / SOURCE_URL_MARKER).write_text("https://example.com/old.mp4", encoding="utf-8")

    with patch("scorm_scorcher.video_processing._download_video") as mock_dl:
        def fake_download(url, dest):
            dest.write_bytes(b"new")

        mock_dl.side_effect = fake_download

        download_for_embed("https://example.com/new.mp4", tmp_path)

        mock_dl.assert_called_once()
        assert (tmp_path / SOURCE_URL_MARKER).read_text(encoding="utf-8").strip() == "https://example.com/new.mp4"


# Restored from archive/dev-2025-08-29: success path and no-subtitle path.

def _fake_run_factory(tmp_path: Path):
    """Create a ``subprocess.run`` replacement writing expected artefacts."""

    def _fake_run(cmd: List[str], capture_output: bool = True, text: bool = True):
        output = Path(cmd[-1])
        if "segment" in cmd:
            # create two dummy segments
            (tmp_path / "segment_000.mp4").write_text("seg0")
            (tmp_path / "segment_001.mp4").write_text("seg1")
        else:
            output.write_text("data")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    return _fake_run


def _fake_run_no_subs(tmp_path: Path):
    """A ``subprocess.run`` replacement that simulates missing subtitles."""

    def _fake_run(cmd: List[str], capture_output: bool = True, text: bool = True):
        output = Path(cmd[-1])
        if "segment" in cmd:
            (tmp_path / "segment_000.mp4").write_text("seg0")
            return subprocess.CompletedProcess(args=cmd, returncode=0)
        if output.name == "subtitles.vtt":
            # Simulate ffmpeg failing because no subtitle streams exist
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stderr="Output file does not contain any stream",
            )
        output.write_text("data")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    return _fake_run


def test_process_video_success(tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_text("data")

    with patch("scorm_scorcher.video_processing.shutil.which", return_value="ffmpeg"), \
        patch("scorm_scorcher.video_processing.subprocess.run") as mock_run:
        mock_run.side_effect = _fake_run_factory(tmp_path)
        artefacts = process_video(str(video_file), str(tmp_path))

    assert Path(artefacts["audio"]).is_file()
    assert Path(artefacts["subtitles"]).is_file()
    assert len(artefacts["segments"]) == 2
    assert mock_run.call_count == 3


def test_process_video_without_subtitles(tmp_path):
    video_file = tmp_path / "video.mp4"
    video_file.write_text("data")

    with patch("scorm_scorcher.video_processing.shutil.which", return_value="ffmpeg"), \
        patch("scorm_scorcher.video_processing.subprocess.run") as mock_run:
        mock_run.side_effect = _fake_run_no_subs(tmp_path)
        artefacts = process_video(str(video_file), str(tmp_path))

    assert artefacts["subtitles"] is None
    assert Path(artefacts["audio"]).is_file()
    assert len(artefacts["segments"]) == 1  # one segment was created
