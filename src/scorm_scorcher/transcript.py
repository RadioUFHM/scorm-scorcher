"""SRT parsing, markdown generation, and section handling."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import List, Optional


def time_to_seconds(time_str: str) -> int:
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s)


def seconds_to_timestamp(seconds: float) -> str:
    td = timedelta(seconds=seconds)
    total = int(td.total_seconds())
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    ms = int(round((seconds - total) * 1000))
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def parse_srt(file_path: Path) -> List[dict]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        r"(\d+)\s+(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\s+([\s\S]*?)(?=\n\n|\Z)"
    )

    return [
        {
            "index": int(m[0]),
            "start": m[1],
            "end": m[2],
            "start_seconds": time_to_seconds(m[1]),
            "text": re.sub(r"\s+", " ", m[3]).strip(),
        }
        for m in pattern.findall(content)
    ]


def generate_markdown(transcript: List[dict], md_path: Path) -> Path:
    with open(md_path, "w", encoding="utf-8") as f:
        for entry in transcript:
            f.write(f"- [{entry['start']}] {entry['text']}\n")
    return md_path


def load_sections(sections_path: Path, transcript: List[dict]) -> Optional[List[dict]]:
    if not sections_path.exists():
        return None

    sections = []
    with open(sections_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" not in line:
                continue
            ts, title = line.split("=", 1)
            ts = ts.strip()
            title = title.strip()
            start_seconds = time_to_seconds(ts)
            if start_seconds > transcript[-1]["start_seconds"]:
                continue
            sections.append({
                "start": ts,
                "start_seconds": start_seconds,
                "title": title,
            })

    sections.sort(key=lambda x: x["start_seconds"])
    return sections or None


def auto_generate_sections(transcript: List[dict], interval: int) -> List[dict]:
    sections: List[dict] = []
    last_time = 0
    for entry in transcript:
        if entry["start_seconds"] >= last_time:
            sections.append({
                "start": entry["start"],
                "start_seconds": entry["start_seconds"],
                "title": f"Section {len(sections) + 1}",
            })
            last_time += interval
    return sections


def save_sections(sections: List[dict], sections_path: Path) -> None:
    with open(sections_path, "w", encoding="utf-8") as f:
        for sec in sections:
            f.write(f"{sec['start']} = {sec['title']}\n")
