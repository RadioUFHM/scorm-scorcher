"""Tests for transcript.py — SRT parsing, sections, markdown."""

import textwrap
from pathlib import Path

import pytest

from scorm_scorcher.transcript import (
    auto_generate_sections,
    generate_markdown,
    load_sections,
    parse_srt,
    save_sections,
    seconds_to_timestamp,
    time_to_seconds,
)

SRT_CONTENT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:03,000
    Hello world

    2
    00:00:04,000 --> 00:00:06,500
    Second line here

""")


def test_time_to_seconds():
    assert time_to_seconds("00:01:30,000") == 90
    assert time_to_seconds("01:00:00,000") == 3600


def test_seconds_to_timestamp():
    assert seconds_to_timestamp(90) == "00:01:30,000"
    assert seconds_to_timestamp(3661.5) == "01:01:01,500"


def test_parse_srt(tmp_path):
    srt = tmp_path / "test.srt"
    srt.write_text(SRT_CONTENT, encoding="utf-8")
    entries = parse_srt(srt)
    assert len(entries) == 2
    assert entries[0]["text"] == "Hello world"
    assert entries[0]["start_seconds"] == 1
    assert entries[1]["text"] == "Second line here"


def test_generate_markdown(tmp_path):
    srt = tmp_path / "test.srt"
    srt.write_text(SRT_CONTENT, encoding="utf-8")
    transcript = parse_srt(srt)
    md = tmp_path / "out.md"
    generate_markdown(transcript, md)
    lines = md.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("- [")
    assert "Hello world" in lines[0]


def test_auto_generate_sections():
    transcript = [
        {"start": "00:00:00,000", "start_seconds": 0},
        {"start": "00:05:00,000", "start_seconds": 300},
        {"start": "00:10:00,000", "start_seconds": 600},
    ]
    sections = auto_generate_sections(transcript, 300)
    assert len(sections) == 3
    assert sections[0]["title"] == "Section 1"
    assert sections[2]["start_seconds"] == 600


def test_save_and_load_sections(tmp_path):
    transcript = [
        {"start": "00:00:00,000", "start_seconds": 0},
        {"start": "00:05:00,000", "start_seconds": 300},
    ]
    sections = [
        {"start": "00:00:00,000", "start_seconds": 0, "title": "Intro"},
        {"start": "00:05:00,000", "start_seconds": 300, "title": "Main"},
    ]
    path = tmp_path / "lesson.sections"
    save_sections(sections, path)
    loaded = load_sections(path, transcript)
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0]["title"] == "Intro"
    assert loaded[1]["title"] == "Main"


def test_load_sections_missing_file(tmp_path):
    transcript = [{"start": "00:00:00,000", "start_seconds": 0}]
    assert load_sections(tmp_path / "nonexistent.sections", transcript) is None
