"""Quiz generation — OpenAI (primary) with a naive transcript-based fallback.

When OPENAI_API_KEY is set, questions are generated via GPT-4o-mini.
Without an API key the tool falls back to a simple word-blanking heuristic
derived from transcript lines, which is always available with no extra deps.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class QuizQuestion:
    type: str
    prompt: str
    answer: Any
    options: Optional[List[str]] = field(default=None)
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": self.type,
            "prompt": self.prompt,
            "answer": self.answer,
            "explanation": self.explanation,
        }
        if self.options is not None:
            d["options"] = self.options
        return d


def generate_quiz_from_transcript(
    md_path: str, num_questions: int = 5, use_openai: bool = True
) -> List[QuizQuestion]:
    """Generate quiz questions from a markdown transcript file.

    Priority: Claude (ANTHROPIC_API_KEY) → OpenAI (OPENAI_API_KEY) → naive fallback.
    """
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        return _generate_claude(md_path, num_questions, anthropic_key)

    openai_key = os.getenv("OPENAI_API_KEY")
    if use_openai and openai_key:
        return _generate_openai(md_path, num_questions, openai_key)

    return _generate_naive(md_path, num_questions)


def _generate_claude(md_path: str, num_questions: int, api_key: str) -> List[QuizQuestion]:
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "The 'anthropic' package is required for Claude quiz generation. "
            "Install with: pip install anthropic"
        ) from exc

    client = anthropic.Anthropic(api_key=api_key)
    transcript = Path(md_path).read_text(encoding="utf-8")

    system = (
        "You are an expert instructional designer who creates effective assessments. "
        "You write questions that test genuine understanding at multiple cognitive levels "
        "(recall, comprehension, and application). Your distractors are plausible but "
        "clearly wrong to someone who knows the material. "
        "You always return valid JSON with no extra text or markdown fences."
    )

    instructions = (
        f"Create {num_questions} multiple-choice quiz questions from the lesson transcript above.\n\n"
        "Return a JSON array. Each element must have exactly these keys:\n"
        '  {"type": "multiple_choice", "prompt": "...", '
        '"options": ["...", "...", "...", "..."], '
        '"answer": "exact string from options that is correct", '
        '"explanation": "1-2 sentences explaining why the answer is right"}\n\n'
        "Rules:\n"
        "• Vary difficulty: include recall, comprehension, and application questions\n"
        "• Write plausible distractors — not obviously wrong\n"
        "• Each option must be a complete phrase, not a single letter\n"
        "• answer must exactly match one entry in options\n"
        "Return only the JSON array."
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": [
                # Cache the transcript — the expensive, reusable part
                {"type": "text", "text": "Lesson transcript:\n\n" + transcript,
                 "cache_control": {"type": "ephemeral"}},
                # Instructions vary by num_questions so not cached
                {"type": "text", "text": instructions},
            ],
        }],
    )

    content = response.content[0].text.strip()
    content = re.sub(r"^```[a-z]*\n?", "", content)
    content = re.sub(r"\n?```$", "", content)

    data = json.loads(content)
    return [
        QuizQuestion(
            type=item.get("type", "multiple_choice"),
            prompt=item["prompt"],
            options=item.get("options"),
            answer=item["answer"],
            explanation=item.get("explanation", ""),
        )
        for item in data
    ]


def _generate_openai(md_path: str, num_questions: int, api_key: str) -> List[QuizQuestion]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError(
            "The 'openai' package is required for AI quiz generation. "
            "Install with: pip install openai"
        ) from exc

    client = OpenAI(api_key=api_key)
    transcript = Path(md_path).read_text(encoding="utf-8")

    prompt = (
        f"Create a {num_questions}-question multiple-choice quiz from this transcript.\n"
        "Write questions that test genuine understanding, not just memorisation.\n"
        "Vary difficulty: include recall, comprehension, and application questions.\n"
        "Make distractors plausible — not obviously wrong.\n\n"
        "Return a JSON array. Each item must have exactly these keys:\n"
        '  {"type": "multiple_choice", "prompt": "...", "options": ["A","B","C","D"], "answer": "A", "explanation": "..."}\n'
        "• options: exactly 4 choices, each a short phrase (not just a single letter)\n"
        "• answer: must be the exact string from options that is correct\n"
        "• explanation: 1-2 sentences explaining why the correct answer is right\n"
        "Return only valid JSON — no markdown fences, no extra text.\n\n"
        "Transcript:\n" + transcript
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    content = response.choices[0].message.content.strip()
    content = re.sub(r"^```[a-z]*\n?", "", content)
    content = re.sub(r"\n?```$", "", content)

    data = json.loads(content)
    return [
        QuizQuestion(
            type=item.get("type", "multiple_choice"),
            prompt=item["prompt"],
            options=item.get("options"),
            answer=item["answer"],
            explanation=item.get("explanation", ""),
        )
        for item in data
    ]


def _generate_naive(md_path: str, limit: int) -> List[QuizQuestion]:
    """Word-blanking heuristic — no external dependencies required."""
    lines = [
        line.strip()
        for line in Path(md_path).read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("-")
    ]

    questions: List[QuizQuestion] = []
    for line in lines[:limit]:
        text = line.split("]", 1)[1].strip() if "]" in line else line[1:].strip()
        words = text.split()

        if len(words) > 5:
            idx = min(2, len(words) - 1)
            answer = words[idx]
            prompt_words = words.copy()
            prompt_words[idx] = "____"
            options = [answer]
            for w in words:
                if w.lower() != answer.lower() and w not in options:
                    options.append(w)
                    if len(options) >= 4:
                        break
            questions.append(QuizQuestion(
                type="multiple_choice",
                prompt="Fill in the blank: " + " ".join(prompt_words),
                options=options,
                answer=answer,
                explanation=f'"{answer}" is the word used in the lesson at this point.',
            ))
        else:
            questions.append(QuizQuestion(
                type="true_false",
                prompt=f"True or False: {text}",
                answer=True,
                explanation="This statement is taken directly from the lesson content.",
            ))

    return questions


def save_quiz_to_json(questions: List[QuizQuestion], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"questions": [q.to_dict() for q in questions]}, f, indent=2)


def save_quiz_to_xlsx(questions: List[QuizQuestion], output_path: str) -> None:
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError(
            "The 'pandas' and 'openpyxl' packages are required for XLSX export. "
            "Install with: pip install pandas openpyxl"
        ) from exc
    pd.DataFrame([q.to_dict() for q in questions]).to_excel(output_path, index=False)
