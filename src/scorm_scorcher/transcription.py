"""Whisper-based audio/video transcription."""

from __future__ import annotations

from pathlib import Path
from typing import List

from .transcript import seconds_to_timestamp

try:
    import whisper
except ImportError:
    whisper = None  # type: ignore[assignment]


def transcribe_to_srt(audio_path: Path, srt_path: Path) -> List[dict]:
    """Transcribe ``audio_path`` using Whisper and write an SRT to ``srt_path``.

    Returns the transcript list in the same format as ``parse_srt``.
    """
    if whisper is None:
        raise RuntimeError(
            "openai-whisper is required for auto-transcription. "
            "Install it with: pip install openai-whisper"
        )

    print(f"Transcribing {audio_path.name} with Whisper (this may take a while)...")
    model = whisper.load_model("base")
    result = model.transcribe(str(audio_path))

    transcript: List[dict] = []
    srt_lines: List[str] = []

    for i, seg in enumerate(result.get("segments", []), start=1):
        start = seconds_to_timestamp(seg["start"])
        end = seconds_to_timestamp(seg["end"])
        text = seg.get("text", "").strip()
        srt_lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        transcript.append({
            "index": i,
            "start": start,
            "end": end,
            "start_seconds": int(seg["start"]),
            "text": text,
        })

    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    print(f"Saved transcript: {srt_path}")
    return transcript
