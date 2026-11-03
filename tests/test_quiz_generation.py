"""Tests for quiz_generation.py."""

import json
from pathlib import Path

import pytest

from scorm_scorcher.quiz_generation import (
    QuizQuestion,
    _generate_naive,
    generate_quiz_from_transcript,
    save_quiz_to_json,
)

TRANSCRIPT_MD = """\
- [00:00:01,000] The quick brown fox jumps over the lazy dog
- [00:00:05,000] Hi
"""


def _write_md(tmp_path: Path) -> Path:
    md = tmp_path / "transcript.md"
    md.write_text(TRANSCRIPT_MD, encoding="utf-8")
    return md


def test_naive_multiple_choice(tmp_path):
    md = _write_md(tmp_path)
    questions = _generate_naive(str(md), 1)
    assert len(questions) == 1
    q = questions[0]
    assert q.type == "multiple_choice"
    assert "____" in q.prompt
    assert q.answer in q.options


def test_naive_true_false_for_short_line(tmp_path):
    md = _write_md(tmp_path)
    questions = _generate_naive(str(md), 2)
    tf = [q for q in questions if q.type == "true_false"]
    assert len(tf) == 1
    assert tf[0].answer is True


def test_generate_quiz_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    md = _write_md(tmp_path)
    questions = generate_quiz_from_transcript(str(md), num_questions=2)
    assert len(questions) == 2


def test_save_quiz_to_json(tmp_path):
    questions = [
        QuizQuestion(type="multiple_choice", prompt="Q?", options=["A", "B"], answer="A"),
    ]
    out = tmp_path / "quiz.json"
    save_quiz_to_json(questions, str(out))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "questions" in data
    assert data["questions"][0]["prompt"] == "Q?"
    assert data["questions"][0]["answer"] == "A"
