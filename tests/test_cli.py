"""Tests for the Click CLI."""

import json
import textwrap
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from scorm_scorcher.cli import main

SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:03,000
    Hello world

    2
    00:00:04,000 --> 00:00:06,000
    Goodbye world

""")


def _make_prepared_dir(tmp_path: Path) -> Path:
    out = tmp_path / "lesson"
    out.mkdir()
    (out / "audio.srt").write_text(SRT, encoding="utf-8")
    return out


def test_quiz_command(tmp_path):
    out = _make_prepared_dir(tmp_path)
    md = out / "audio.md"
    md.write_text("- [00:00:01,000] The quick brown fox jumps over the lazy dog\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["quiz", "--input", str(out), "--num-questions", "1"])
    assert result.exit_code == 0, result.output
    assert (out / "quiz.json").exists()
    data = json.loads((out / "quiz.json").read_text())
    assert "questions" in data


def test_build_command_local(tmp_path):
    out = _make_prepared_dir(tmp_path)
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"")

    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--video", str(video),
        "--input", str(out),
        "--title", "Test Lesson",
    ])
    assert result.exit_code == 0, result.output
    assert (out / "index.html").exists()
    assert (out / "imsmanifest.xml").exists()


def test_build_command_youtube_requires_allow_flag(tmp_path):
    out = _make_prepared_dir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--video", "https://www.youtube.com/watch?v=test123",
        "--input", str(out),
        "--title", "Test Lesson",
    ])
    assert result.exit_code != 0
    assert "allow-youtube" in result.output.lower()
    assert not (out / "index.html").exists()


def test_build_command_youtube_with_allow_flag(tmp_path):
    out = _make_prepared_dir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--video", "https://www.youtube.com/watch?v=test123",
        "--input", str(out),
        "--title", "Test Lesson",
        "--allow-youtube",
    ])
    assert result.exit_code == 0, result.output
    content = (out / "index.html").read_text(encoding="utf-8")
    assert "test123" in content


def test_build_command_video_mode_url(tmp_path):
    out = _make_prepared_dir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--video", "https://cdn.example.com/signed/lesson.mp4?sig=abc",
        "--input", str(out),
        "--title", "Test Lesson",
        "--video-mode", "url",
    ])
    assert result.exit_code == 0, result.output
    content = (out / "index.html").read_text(encoding="utf-8")
    assert "https://cdn.example.com/signed/lesson.mp4?sig=abc" in content


def test_build_command_video_mode_embed_remote(tmp_path):
    out = _make_prepared_dir(tmp_path)
    runner = CliRunner()
    with patch("scorm_scorcher.builder.download_for_embed") as mock_dl:
        fake_local = out / "_source.mp4"
        fake_local.write_bytes(b"")
        mock_dl.return_value = fake_local

        result = runner.invoke(main, [
            "build",
            "--video", "https://cdn.example.com/master.mp4",
            "--input", str(out),
            "--title", "Test Lesson",
            "--video-mode", "embed",
        ])
        assert result.exit_code == 0, result.output
        mock_dl.assert_called_once()
        content = (out / "index.html").read_text(encoding="utf-8")
        assert "_source.mp4" in content
        assert "https://cdn.example.com/master.mp4" not in content


def test_package_command(tmp_path):
    out = _make_prepared_dir(tmp_path)
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"")

    runner = CliRunner()
    runner.invoke(main, ["build", "--video", str(video), "--input", str(out), "--title", "My Lesson"])
    result = runner.invoke(main, ["package", "--input", str(out), "--title", "My Lesson"])
    assert result.exit_code == 0, result.output
    assert (out / "My_Lesson_SCORM.zip").exists()


def test_build_command_video_expiry_url_mode(tmp_path):
    out = _make_prepared_dir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--video", "https://cdn.example.com/signed/lesson.mp4?sig=abc",
        "--input", str(out),
        "--title", "Test Lesson",
        "--video-mode", "url",
        "--video-expiry", "2020-01-01",
    ])
    assert result.exit_code == 0, result.output
    content = (out / "index.html").read_text(encoding="utf-8")
    assert "2020-01-01" in content


def test_build_command_video_expiry_ignored_for_embed(tmp_path):
    out = _make_prepared_dir(tmp_path)
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"")

    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--video", str(video),
        "--input", str(out),
        "--title", "Test Lesson",
        "--video-mode", "embed",
        "--video-expiry", "2020-01-01",
    ])
    assert result.exit_code == 0, result.output
    assert "ignored" in result.output.lower()
    content = (out / "index.html").read_text(encoding="utf-8")
    assert "2020-01-01" not in content


def test_package_command_scorm_both(tmp_path):
    out = _make_prepared_dir(tmp_path)
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"")

    runner = CliRunner()
    runner.invoke(main, ["build", "--video", str(video), "--input", str(out), "--title", "My Lesson"])
    result = runner.invoke(main, ["package", "--input", str(out), "--title", "My Lesson", "--scorm", "both"])
    assert result.exit_code == 0, result.output

    zip_12 = out / "My_Lesson_SCORM_12.zip"
    zip_2004 = out / "My_Lesson_SCORM_2004.zip"
    assert zip_12.exists()
    assert zip_2004.exists()

    with zipfile.ZipFile(zip_12) as z:
        manifest_12 = z.read("imsmanifest.xml").decode("utf-8")
    with zipfile.ZipFile(zip_2004) as z:
        manifest_2004 = z.read("imsmanifest.xml").decode("utf-8")

    assert "adlcp_rootv1p2" in manifest_12
    assert "adlcp_v1p3" in manifest_2004


def test_build_command_scorm_2004(tmp_path):
    out = _make_prepared_dir(tmp_path)
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"")

    runner = CliRunner()
    result = runner.invoke(main, [
        "build",
        "--video", str(video),
        "--input", str(out),
        "--title", "Test Lesson",
        "--scorm", "2004",
    ])
    assert result.exit_code == 0, result.output
    content = (out / "imsmanifest.xml").read_text(encoding="utf-8")
    assert "2004 4th Edition" in content


def test_build_missing_srt_fails(tmp_path):
    out = tmp_path / "empty"
    out.mkdir()
    runner = CliRunner()
    result = runner.invoke(main, ["build", "--video", "x.mp4", "--input", str(out)])
    assert result.exit_code != 0
    assert "prepare" in result.output.lower() or "srt" in result.output.lower()


# --- Package allowlist, end to end through the CLI ---

WORKING_FILES = ["audio.mp3", "audio.md", "segment_000.mp4", ".video_source_url"]


def _zip_names(path: Path) -> list:
    with zipfile.ZipFile(path) as zf:
        return sorted(zf.namelist())


def test_build_then_package_both_ships_video_and_no_working_files(tmp_path):
    out = _make_prepared_dir(tmp_path)  # holds audio.srt, a working file
    for name in WORKING_FILES:
        (out / name).write_text("work", encoding="utf-8")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"video")

    runner = CliRunner()
    built = runner.invoke(main, ["build", "--video", str(video), "--input", str(out), "--title", "My Lesson"])
    assert built.exit_code == 0, built.output
    result = runner.invoke(main, ["package", "--input", str(out), "--title", "My Lesson", "--scorm", "both"])
    assert result.exit_code == 0, result.output

    for zip_name in ("My_Lesson_SCORM_12.zip", "My_Lesson_SCORM_2004.zip"):
        names = _zip_names(out / zip_name)
        assert names == sorted(["imsmanifest.xml", "index.html", "branding.css", "scorm-shim.js", "lesson.mp4"])


def test_url_mode_package_has_no_video_file(tmp_path):
    out = _make_prepared_dir(tmp_path)
    runner = CliRunner()
    built = runner.invoke(main, [
        "build", "--video", "https://cdn.example.com/lesson.mp4", "--video-mode", "url",
        "--input", str(out), "--title", "Url Lesson",
    ])
    assert built.exit_code == 0, built.output
    result = runner.invoke(main, ["package", "--input", str(out), "--title", "Url Lesson"])
    assert result.exit_code == 0, result.output
    assert not any(n.endswith(".mp4") for n in _zip_names(out / "Url_Lesson_SCORM.zip"))


def test_package_reports_missing_listed_file(tmp_path):
    out = _make_prepared_dir(tmp_path)
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"video")
    runner = CliRunner()
    runner.invoke(main, ["build", "--video", str(video), "--input", str(out), "--title", "My Lesson"])
    (out / "lesson.mp4").unlink()
    result = runner.invoke(main, ["package", "--input", str(out), "--title", "My Lesson"])
    assert result.exit_code != 0
    assert "lesson.mp4" in result.output


def test_run_auto_ships_video_and_no_working_files(tmp_path):
    out = tmp_path / "run_out"
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"video")
    srt = tmp_path / "lesson.srt"
    srt.write_text(SRT, encoding="utf-8")

    def fake_process_video(video_source, work_dir, **kwargs):
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        audio = Path(work_dir) / "audio.mp3"
        audio.write_text("audio", encoding="utf-8")
        return {"audio": str(audio), "subtitles": None, "segments": []}

    with patch("scorm_scorcher.cli.process_video", side_effect=fake_process_video):
        result = CliRunner().invoke(main, [
            "run", "--video", str(video), "--output", str(out), "--title", "Run Lesson",
            "--subtitles", str(srt), "--no-segment", "--auto",
        ])
    assert result.exit_code == 0, result.output
    names = _zip_names(out / "Run_Lesson_SCORM.zip")
    assert "lesson.mp4" in names
    assert "audio.mp3" not in names
    assert not any(n.endswith((".srt", ".md", ".sections")) for n in names)
