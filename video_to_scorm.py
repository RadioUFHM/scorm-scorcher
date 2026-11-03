import os
import re
import json
import argparse
import zipfile
import shutil
from pathlib import Path
from datetime import timedelta

try:
    import whisper  # Optional; only needed if auto-transcribing
except ImportError:  # pragma: no cover - dependency may be missing
    whisper = None

TEMPLATE_PATH = Path(__file__).parent / "templates" / "player_template.html"
BRANDING_PATH = Path(__file__).parent / "templates" / "branding.css"

# ----------------------------
# PARSE SRT
# ----------------------------
def parse_srt(file_path):
    """Parse .srt into structured transcript"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        r"(\d+)\s+(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\s+([\s\S]*?)(?=\n\n|\Z)"
    )
    matches = pattern.findall(content)

    return [
        {
            "index": int(m[0]),
            "start": m[1],
            "end": m[2],
            "start_seconds": time_to_seconds(m[1]),
            "text": re.sub(r"\s+", " ", m[3]).strip(),
        }
        for m in matches
    ]

# ----------------------------
# CONVERT TIME
# ----------------------------
def time_to_seconds(time_str):
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s)

# ----------------------------
# LOAD CUSTOM SECTIONS
# ----------------------------
def load_sections(sections_path, transcript):
    """Load .sections file if it exists"""
    sections = []
    if not sections_path.exists():
        return None

    print(f"📄 Found custom .sections file: {sections_path.name}")

    with open(sections_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                ts, title = line.split("=", 1)
                ts = ts.strip()
                title = title.strip()
                start_seconds = time_to_seconds(ts)

                # Skip timestamps beyond transcript length
                if start_seconds > transcript[-1]["start_seconds"]:
                    print(f"⚠️ Skipping {ts} ({title}) → beyond transcript length")
                    continue

                sections.append({
                    "start": ts,
                    "start_seconds": start_seconds,
                    "title": title
                })

    # Ensure sorted order
    sections.sort(key=lambda x: x["start_seconds"])
    print(f"✅ Loaded {len(sections)} custom sections.")
    return sections

# ----------------------------
# GENERATE SECTIONS AUTOMATICALLY
# ----------------------------
def auto_generate_sections(transcript, interval):
    """Fallback: auto-generate sections based on interval"""
    sections = []
    last_time = 0
    for entry in transcript:
        if entry["start_seconds"] >= last_time:
            sections.append({
                "start": entry["start"],
                "start_seconds": entry["start_seconds"],
                "title": f"Section {len(sections) + 1}"
            })
            last_time += interval
    print(f"ℹ️ No .sections file found → auto-generated {len(sections)} sections.")
    return sections

# ----------------------------
# GENERATE HTML PLAYER
# ----------------------------
def generate_player_html(transcript, sections, title, output_dir, video_src, is_url):
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    video_value = str(video_src) if is_url else video_src.name

    output_text = template
    output_text = output_text.replace("{{TRANSCRIPT_JSON}}", json.dumps(transcript))
    output_text = output_text.replace("{{SECTIONS_JSON}}", json.dumps(sections))
    output_text = output_text.replace("{{TITLE}}", title)
    output_text = output_text.replace("{{VIDEO}}", video_value)

    if not is_url:
        shutil.copy(video_src, output_dir / video_src.name)

    output_html = output_dir / "index.html"
    with open(output_html, "w", encoding="utf-8") as out:
        out.write(output_text)
    return output_html

# ----------------------------
# GENERATE SCORM MANIFEST
# ----------------------------
def generate_manifest(title, output_dir):
    manifest = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{title.replace(' ', '_').upper()}_SCORM" version="1.0"
 xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
 xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2
 imscp_rootv1p1p2.xsd
 http://www.adlnet.org/xsd/adlcp_rootv1p2
 adlcp_rootv1p2.xsd">

  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  <organizations default="ORG1">
    <organization identifier="ORG1">
      <title>{title}</title>
      <item identifier="ITEM1" identifierref="RES1">
        <title>{title}</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES1" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html" />
      <file href="{BRANDING_PATH.name}" />
    </resource>
  </resources>
</manifest>"""
    manifest_path = output_dir / "imsmanifest.xml"
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest)
    return manifest_path

# ----------------------------
# CREATE SCORM PACKAGE
# ----------------------------
def create_scorm_package(output_dir, title):
    zip_path = output_dir / f"{title.replace(' ', '_')}_SCORM.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(output_dir):
            for file in files:
                if file.endswith(".zip"):
                    continue
                abs_path = Path(root) / file
                rel_path = abs_path.relative_to(output_dir)
                zipf.write(abs_path, rel_path)
    return zip_path

# ----------------------------
# MAIN ENTRYPOINT
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate SCORM lesson")
    parser.add_argument("--video", help="Path to local video file (optional)")
    parser.add_argument("--video-url", help="Optional: external video URL (YouTube, Vimeo, etc.)")
    parser.add_argument("--subtitles", help="Path to existing .srt file")
    parser.add_argument("--output", required=True, help="Output folder")
    parser.add_argument("--title", default="SCORM Lesson", help="Lesson title")
    parser.add_argument("--interval", type=int, default=300, help="Auto-section interval in seconds")
    args = parser.parse_args()

    # Validate input
    if not args.video and not args.video_url:
        parser.error("You must provide either --video or --video-url")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Decide video source
    is_url = bool(args.video_url)
    video_src = args.video_url if is_url else Path(args.video)

    # Subtitle handling
    if not args.subtitles:
        parser.error("When using --video-url, please provide --subtitles pointing to a matching .srt")
    srt_path = Path(args.subtitles)
    transcript = parse_srt(srt_path)

    # Load custom sections if available
    sections_path = srt_path.with_suffix(".sections")
    sections = load_sections(sections_path, transcript)
    if not sections:
        sections = auto_generate_sections(transcript, args.interval)

    # Generate SCORM player
    html_file = generate_player_html(transcript, sections, args.title, output_dir, video_src, is_url)
    manifest_file = generate_manifest(args.title, output_dir)
    zip_file = create_scorm_package(output_dir, args.title)

    print(f"\n✅ Generated SCORM player: {html_file}")
    print(f"✅ SCORM manifest: {manifest_file}")
    print(f"✅ SCORM package: {zip_file}")

if __name__ == "__main__":
    main()
