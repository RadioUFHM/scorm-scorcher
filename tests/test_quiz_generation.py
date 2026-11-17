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


# ── Claude generation (anthropic client mocked) ──────────────────────────────

def _fake_anthropic(monkeypatch, text, stop_reason="end_turn"):
    import sys
    import types

    calls = {}

    class _Messages:
        def create(self, **kwargs):
            calls.update(kwargs)
            block = types.SimpleNamespace(text=text)
            return types.SimpleNamespace(content=[block], stop_reason=stop_reason)

    class _Client:
        def __init__(self, api_key):
            self.messages = _Messages()

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_Client))
    return calls


def test_claude_max_tokens_scales_with_question_count(tmp_path, monkeypatch):
    from scorm_scorcher.quiz_generation import _generate_claude

    md = tmp_path / "t.md"
    md.write_text(TRANSCRIPT_MD, encoding="utf-8")
    item = {"type": "multiple_choice", "prompt": "Q?", "options": ["a", "b"], "answer": "a"}
    calls = _fake_anthropic(monkeypatch, json.dumps([item] * 10))

    questions = _generate_claude(str(md), 10, "key")

    assert len(questions) == 10
    assert calls["max_tokens"] >= 4000


def test_claude_truncated_reply_raises_clear_error(tmp_path, monkeypatch):
    from scorm_scorcher.quiz_generation import _generate_claude

    md = tmp_path / "t.md"
    md.write_text(TRANSCRIPT_MD, encoding="utf-8")
    _fake_anthropic(monkeypatch, '[{"prompt": "Q?",', stop_reason="max_tokens")

    with pytest.raises(RuntimeError, match="cut off"):
        _generate_claude(str(md), 10, "key")


# ── Answer shuffling ─────────────────────────────────────────────────────────

def _mc(options, answer):
    return QuizQuestion(type="multiple_choice", prompt="Q?", options=list(options), answer=answer)


def test_shuffle_moves_the_correct_answer_around():
    import random
    from scorm_scorcher.quiz_generation import shuffle_options

    questions = [_mc(["right", "w1", "w2", "w3"], "right") for _ in range(40)]
    shuffle_options(questions, random.Random(1))
    positions = {q.options.index("right") for q in questions}
    assert len(positions) == 4  # not always first
    for q in questions:
        assert sorted(q.options) == sorted(["right", "w1", "w2", "w3"])
        assert q.answer in q.options


def test_shuffle_keeps_position_dependent_options_and_true_false():
    import random
    from scorm_scorcher.quiz_generation import shuffle_options

    above = _mc(["a", "b", "c", "All of the above"], "All of the above")
    tf = QuizQuestion(type="true_false", prompt="T?", answer=True)
    shuffle_options([above, tf], random.Random(0))
    assert above.options == ["a", "b", "c", "All of the above"]
    assert tf.options is None


def test_generated_heuristic_quiz_is_shuffled(tmp_path, monkeypatch):
    import random
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    md = tmp_path / "t.md"
    md.write_text(
        "".join(f"- [00:00:0{i},000] one two three{i} four five six seven\n" for i in range(9)),
        encoding="utf-8",
    )
    random.seed(3)
    questions = generate_quiz_from_transcript(str(md), 9)
    assert {q.options.index(q.answer) for q in questions} != {0}
