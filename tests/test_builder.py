"""Tests for builder.py — HTML and manifest generation."""

import json
import re
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
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


# --- Manifest escaping: parse the generated XML, never compare strings ---

_NCNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

SPECIAL_TITLES = [
    "AML & Sanctions",
    "Less <than> greater",
    'Say "hello"',
    "Rio's course",
    "All & <of> \"them\" 'together'",
    "2026 KYC refresher",
]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@pytest.mark.parametrize("version", ["1.2", "2004"])
@pytest.mark.parametrize("title", SPECIAL_TITLES)
def test_manifest_title_round_trips_through_xml_parser(tmp_path, title, version):
    path = generate_manifest(title, tmp_path, include_quiz=True, scorm_version=version)
    root = ET.parse(path).getroot()  # raises ParseError if the manifest is malformed

    titles = [el.text for el in root.iter() if _local(el.tag) == "title"]
    # Organization title + lesson item title carry the user's title; the quiz item is "Quiz".
    assert titles.count(title) == 2
    assert "Quiz" in titles


@pytest.mark.parametrize("title", SPECIAL_TITLES)
def test_manifest_identifier_is_valid_xml_id(tmp_path, title):
    root = ET.parse(generate_manifest(title, tmp_path)).getroot()
    assert _NCNAME.match(root.get("identifier"))


# --- SCO-type attribute spelling per SCORM version (parsed, not string-matched) ---

ADLCP_NS = {
    "1.2": "http://www.adlnet.org/xsd/adlcp_rootv1p2",
    "2004": "http://www.adlnet.org/xsd/adlcp_v1p3",
}
EXPECTED_ATTR = {"1.2": "scormtype", "2004": "scormType"}


@pytest.mark.parametrize("version", ["1.2", "2004"])
@pytest.mark.parametrize("include_quiz", [True, False])
def test_resource_scormtype_attribute_matches_version(tmp_path, version, include_quiz):
    root = ET.parse(generate_manifest("Lesson", tmp_path, include_quiz=include_quiz, scorm_version=version)).getroot()
    resources = [el for el in root.iter() if _local(el.tag) == "resource"]
    assert len(resources) == (2 if include_quiz else 1)

    ns = ADLCP_NS[version]
    for res in resources:
        adlcp_attrs = [k.split("}", 1)[1] for k in res.attrib if k.startswith("{" + ns + "}")]
        assert adlcp_attrs == [EXPECTED_ATTR[version]], adlcp_attrs  # exactly one spelling, the right one
        assert res.get(f"{{{ns}}}{EXPECTED_ATTR[version]}") == "sco"


@pytest.mark.parametrize("version", ["1.2", "2004"])
def test_no_manifest_mixes_scormtype_spellings(tmp_path, version):
    root = ET.parse(generate_manifest("Lesson", tmp_path, include_quiz=True, scorm_version=version)).getroot()
    spellings = {
        k.split("}", 1)[1]
        for el in root.iter()
        for k in el.attrib
        if k.split("}", 1)[-1].lower() == "scormtype"
    }
    assert spellings == {EXPECTED_ATTR[version]}


# --- Title in the HTML pages and the quiz script (parsed, not string-matched) ---

PAGE_TITLES = SPECIAL_TITLES + ["Ends the script </script><b>x</b>", "Back\\slash \\n title"]


class _PageReader(HTMLParser):
    """Collects <title> text, <h1> text and <script> contents."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.h1, self.scripts, self._in = "", [], [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("title", "h1", "script"):
            self._in = tag
            if tag == "h1":
                self.h1.append("")
            if tag == "script":
                self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "h1":
            self.h1[-1] += data
        elif self._in == "script":
            self.scripts[-1] += data


def _read_page(path: Path) -> _PageReader:
    reader = _PageReader()
    reader.feed(path.read_text(encoding="utf-8"))
    return reader


@pytest.mark.parametrize("title", PAGE_TITLES)
def test_player_page_shows_title_exactly(tmp_path, title):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    page = _read_page(generate_player_html(TRANSCRIPT, SECTIONS, title, tmp_path, str(video), video_mode="embed"))
    assert page.title == title
    assert page.h1 == [title]


@pytest.mark.parametrize("title", PAGE_TITLES)
def test_quiz_page_and_certificate_title_round_trip(tmp_path, title):
    (tmp_path / QUIZ_JSON_NAME).write_text('{"questions": []}', encoding="utf-8")
    page = _read_page(generate_quiz_html(tmp_path, title))
    assert page.title == f"{title} — Quiz"
    assert title in page.h1

    # The certificate's courseTitle must be one valid JS string literal inside
    # the script block. A JSON string literal is a valid JS string literal.
    script = "".join(page.scripts)
    match = re.search(r'courseTitle:\s*("(?:[^"\\]|\\.)*")\s*,', script)
    assert match, "courseTitle not found inside a <script> block"
    assert json.loads(match.group(1)) == title
