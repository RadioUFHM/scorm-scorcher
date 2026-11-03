"""Tests for builder.py — HTML and manifest generation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scorm_scorcher.builder import (
    BRANDING_NAME,
    QUIZ_HTML_NAME,
    QUIZ_JSON_NAME,
    SCORM_SHIM_NAME,
    generate_manifest,
    generate_player_html,
    generate_quiz_html,
)

TRANSCRIPT = [{"index": 1, "start": "00:00:01,000", "end": "00:00:03,000", "start_seconds": 1, "text": "Hello"}]
SECTIONS = [{"start": "00:00:00,000", "start_seconds": 0, "title": "Intro"}]


def test_generate_player_html_local(tmp_path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"")
    html = generate_player_html(TRANSCRIPT, SECTIONS, "Test", tmp_path, str(video), video_mode="embed")
    assert html.exists()
    content = html.read_text(encoding="utf-8")
    assert "lesson.mp4" in content
    assert "Hello" in content
    assert "Intro" in content
    assert (tmp_path / BRANDING_NAME).exists()
    assert (tmp_path / SCORM_SHIM_NAME).exists()


def test_generate_player_html_youtube(tmp_path):
    html = generate_player_html(
        TRANSCRIPT, SECTIONS, "Test", tmp_path,
        "https://www.youtube.com/watch?v=abc123", video_mode="youtube",
    )
    content = html.read_text(encoding="utf-8")
    assert "youtube" in content
    assert "abc123" in content


def test_generate_player_html_url_mode(tmp_path):
    html = generate_player_html(
        TRANSCRIPT, SECTIONS, "Test", tmp_path,
        "https://cdn.example.com/signed/lesson.mp4?sig=abc", video_mode="url",
    )
    content = html.read_text(encoding="utf-8")
    assert "https://cdn.example.com/signed/lesson.mp4?sig=abc" in content
    assert '"url"' in content
    # url mode never copies the video into the package
    assert not (tmp_path / "lesson.mp4").exists()


def test_generate_player_html_embed_downloads_remote(tmp_path):
    with patch("scorm_scorcher.builder.download_for_embed") as mock_dl:
        fake_local = tmp_path / "_source.mp4"
        fake_local.write_bytes(b"")
        mock_dl.return_value = fake_local

        html = generate_player_html(
            TRANSCRIPT, SECTIONS, "Test", tmp_path,
            "https://cdn.example.com/master.mp4", video_mode="embed",
        )
        mock_dl.assert_called_once_with("https://cdn.example.com/master.mp4", tmp_path)
        content = html.read_text(encoding="utf-8")
        assert "_source.mp4" in content
        assert "https://cdn.example.com/master.mp4" not in content


def test_generate_player_html_url_mode_with_expiry(tmp_path):
    html = generate_player_html(
        TRANSCRIPT, SECTIONS, "Test", tmp_path,
        "https://cdn.example.com/signed/lesson.mp4?sig=abc", video_mode="url",
        video_expiry="2020-01-01", license_message="Contact sales to renew.",
    )
    content = html.read_text(encoding="utf-8")
    assert "2020-01-01" in content
    assert "Contact sales to renew." in content


def test_generate_player_html_embed_ignores_expiry(tmp_path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"")
    html = generate_player_html(
        TRANSCRIPT, SECTIONS, "Test", tmp_path, str(video), video_mode="embed",
        video_expiry="2020-01-01",
    )
    content = html.read_text(encoding="utf-8")
    # embed mode has no technical kill switch — expiry must not be rendered
    assert "2020-01-01" not in content
    assert 'const videoExpiry = "";' in content


def test_generate_player_html_default_license_message(tmp_path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"")
    html = generate_player_html(TRANSCRIPT, SECTIONS, "Test", tmp_path, str(video), video_mode="embed")
    content = html.read_text(encoding="utf-8")
    assert "This training license has expired" in content


def test_generate_quiz_html(tmp_path):
    quiz_data = {"questions": [{"type": "true_false", "prompt": "True?", "answer": True}]}
    (tmp_path / QUIZ_JSON_NAME).write_text(json.dumps(quiz_data), encoding="utf-8")
    out = generate_quiz_html(tmp_path, "My Quiz")
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "My Quiz" in content
    assert "True?" in content
    assert (tmp_path / SCORM_SHIM_NAME).exists()
    assert "This training license has expired" in content


def test_generate_quiz_html_includes_certificate(tmp_path):
    quiz_data = {"questions": [{"type": "true_false", "prompt": "True?", "answer": True}]}
    (tmp_path / QUIZ_JSON_NAME).write_text(json.dumps(quiz_data), encoding="utf-8")
    out = generate_quiz_html(tmp_path, "My Quiz")
    content = out.read_text(encoding="utf-8")
    assert 'id="certificate-view"' in content
    assert "renderCertificate" in content
    assert "window.print()" in content


def test_generate_quiz_html_with_expiry(tmp_path):
    quiz_data = {"questions": [{"type": "true_false", "prompt": "True?", "answer": True}]}
    (tmp_path / QUIZ_JSON_NAME).write_text(json.dumps(quiz_data), encoding="utf-8")
    out = generate_quiz_html(tmp_path, "My Quiz", video_expiry="2020-01-01", license_message="Renew now.")
    content = out.read_text(encoding="utf-8")
    assert "2020-01-01" in content
    assert "Renew now." in content


def test_generate_manifest_no_quiz(tmp_path):
    manifest = generate_manifest("My Lesson", tmp_path, include_quiz=False)
    content = manifest.read_text(encoding="utf-8")
    assert "MY_LESSON_SCORM" in content
    assert "SCORM" in content
    assert QUIZ_HTML_NAME not in content


def test_generate_manifest_with_quiz(tmp_path):
    manifest = generate_manifest("My Lesson", tmp_path, include_quiz=True)
    content = manifest.read_text(encoding="utf-8")
    assert QUIZ_HTML_NAME in content
    assert "masteryscore" in content


def test_generate_manifest_2004_no_masteryscore(tmp_path):
    manifest = generate_manifest("My Lesson", tmp_path, include_quiz=True, scorm_version="2004")
    content = manifest.read_text(encoding="utf-8")
    assert "adlcp_v1p3" in content
    assert "adlseq_v1p3" in content
    assert "2004 4th Edition" in content
    assert "masteryscore" not in content
    assert QUIZ_HTML_NAME in content


def test_generate_manifest_2004_without_quiz(tmp_path):
    manifest = generate_manifest("My Lesson", tmp_path, include_quiz=False, scorm_version="2004")
    content = manifest.read_text(encoding="utf-8")
    assert "2004 4th Edition" in content
    assert QUIZ_HTML_NAME not in content


def test_generate_manifest_unknown_version_raises(tmp_path):
    with pytest.raises(ValueError):
        generate_manifest("My Lesson", tmp_path, scorm_version="3.0")
