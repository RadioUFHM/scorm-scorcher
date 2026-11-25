"""Command-line interface: prepare → quiz → build → package."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import click

from .builder import (
    LOGO_SUFFIXES,
    QUIZ_JSON_NAME,
    certificate_files,
    find_brand_logo,
    generate_manifest,
    generate_player_html,
    manifest_extra_files,
    package_basename,
    update_certificate_settings,
)
from .quiz_generation import generate_quiz_from_transcript, save_quiz_to_json, save_quiz_to_xlsx
from .scorm_packager import create_scorm_package
from .transcript import (
    auto_generate_sections,
    generate_markdown,
    load_sections,
    parse_srt,
    save_sections,
)
from .transcription import transcribe_to_srt
from .video_processing import embedded_video_name, process_video


def _resolve_video_mode(video: str, video_mode: str | None, allow_youtube: bool) -> str:
    """Resolve the explicit or inferred video-source mode, enforcing the
    YouTube gate (marketing-funnel source only, not for FI delivery)."""
    is_url = video.startswith("http://") or video.startswith("https://")
    is_youtube = is_url and ("youtube.com" in video or "youtu.be" in video)

    if is_youtube:
        if not allow_youtube:
            raise click.ClickException(
                "YouTube is a marketing-funnel source only — not for FI delivery. "
                "Pass --allow-youtube to build a low-security package anyway."
            )
        if video_mode and video_mode != "youtube":
            raise click.ClickException(
                "A youtube.com/youtu.be --video source must use --video-mode youtube."
            )
        return "youtube"

    if video_mode:
        if video_mode == "youtube":
            raise click.ClickException(
                "--video-mode youtube requires a youtube.com/youtu.be --video URL."
            )
        return video_mode

    return "url" if is_url else "embed"


def _embedded_files(video: str, resolved_mode: str, out_dir: Path) -> list[str]:
    """Package files beyond the standard ones: the video itself in embed mode,
    and the certificate logo if one is set."""
    video_files = [embedded_video_name(video)] if resolved_mode == "embed" else []
    return video_files + certificate_files(out_dir)


def _certificate_options(func):
    """--logo / --signer-name / --signer-title, saved to certificate.json."""
    func = click.option(
        "--signer-title", default=None,
        help="Signer's title, shown under the signature line. Saved for later builds.",
    )(func)
    func = click.option(
        "--signer-name", default=None,
        help="Name typed on the certificate's signature line (\"\" removes it). "
             "Saved for later builds.",
    )(func)
    func = click.option(
        "--logo", default=None,
        help="Logo image (.png, .jpg, .svg…) for the top of the certificate "
             "(\"\" removes it). Copied into the package and saved for later builds.",
    )(func)
    return func


BRAND_DIR = Path("brand")  # in the folder the command is run from


def _apply_certificate_settings(out_dir: Path, logo, signer_name, signer_title) -> None:
    """Save the certificate options, using the brand-folder logo as the default."""
    brand_logo = find_brand_logo(BRAND_DIR)
    settings = update_certificate_settings(out_dir, logo, signer_name, signer_title, brand_logo=brand_logo)
    if logo is None and settings["use_brand_logo"]:
        if brand_logo is not None:
            click.echo(f"Certificate logo: {brand_logo} (brand folder default)")
        elif BRAND_DIR.is_dir() and any(f.suffix.lower() in LOGO_SUFFIXES for f in BRAND_DIR.iterdir()):
            click.echo(
                f"Note: no default logo used: put exactly one image in {BRAND_DIR}/ "
                "(it has more than one), or pass --logo.",
                err=True,
            )


def _resolve_video_expiry(resolved_mode: str, video_expiry: str | None) -> str | None:
    """A technical kill switch only makes sense for a referenced signed URL
    (video_mode='url') — an embedded MP4 has no way to expire itself. Warn
    and drop the value rather than rendering a misleading countdown."""
    if video_expiry and resolved_mode != "url":
        click.echo(
            f"Warning: --video-expiry is ignored for --video-mode {resolved_mode} "
            "(only 'url' mode has a technical kill switch).",
            err=True,
        )
        return None
    return video_expiry


def _package_scorm_versions(
    title: str, out_dir: Path, scorm: str, extra_files: list[str] | None = None,
) -> list[Path]:
    """Regenerate imsmanifest.xml for each requested SCORM version and zip
    immediately after each regeneration. Cheap because index.html and its
    assets are built once and reused unchanged across every version — only
    the manifest differs."""
    versions = ["1.2", "2004"] if scorm == "both" else [scorm]
    quiz_exists = (out_dir / QUIZ_JSON_NAME).exists()
    if extra_files is None:  # 'package' alone: keep what 'build' listed, e.g. the video
        extra_files = manifest_extra_files(out_dir)
    multi = len(versions) > 1

    zip_paths = []
    for version in versions:
        generate_manifest(
            title, out_dir, include_quiz=quiz_exists, scorm_version=version, extra_files=extra_files,
        )
        suffix = "" if not multi else ("_12" if version == "1.2" else "_2004")
        zip_name = package_basename(title) + f"_SCORM{suffix}.zip"
        zip_path = out_dir / zip_name
        create_scorm_package(str(out_dir), str(zip_path))
        zip_paths.append(zip_path)
    return zip_paths


def _echo_quiz_source() -> None:
    """Say which quiz generator will run, so a missing key isn't silent."""
    if os.getenv("ANTHROPIC_API_KEY"):
        click.echo("      Using Claude (ANTHROPIC_API_KEY found).")
    elif os.getenv("OPENAI_API_KEY"):
        click.echo("      Using OpenAI (OPENAI_API_KEY found).")
    else:
        click.echo(
            "      No API key found: using the built-in fill-in-the-blank quiz. "
            "Set ANTHROPIC_API_KEY for AI-written questions."
        )


@click.group()
@click.version_option()
def main() -> None:
    """Convert video files into SCORM 1.2 packages.

    Quickstart (one command):

    \b
        scorm-scorcher run --video lesson.mp4 --output ./build --title "My Lesson"

    Step-by-step workflow:

    \b
        scorm-scorcher prepare --video lesson.mp4 --output ./build
        scorm-scorcher quiz    --input ./build
        scorm-scorcher build   --video lesson.mp4 --input ./build --title "My Lesson"
        scorm-scorcher package --input ./build --title "My Lesson"
    """


@main.command()
@click.option("--video", required=True, help="Local path or HTTP(S) URL to the video file.")
@click.option("--output", required=True, help="Output directory for processed assets.")
@click.option("--subtitles", default=None, help="Path to an existing .srt subtitle file (skips Whisper).")
@click.option("--interval", default=300, show_default=True, help="Section auto-generation interval in seconds.")
@click.option("--no-segment", is_flag=True, default=False, help="Skip ffmpeg video segmentation.")
def prepare(video: str, output: str, subtitles: str | None, interval: int, no_segment: bool) -> None:
    """Extract audio, transcribe, segment video, and generate section markers."""
    try:
        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)

        result = process_video(video, output, no_segment=no_segment)
        audio_path = Path(result["audio"])  # type: ignore[arg-type]

        if subtitles:
            srt_src = Path(subtitles)
            srt_path = out_dir / srt_src.name
            if srt_src.resolve() != srt_path.resolve():
                shutil.copy(srt_src, srt_path)
            transcript = parse_srt(srt_path)
            click.echo(f"Using provided subtitles: {srt_path}")
        else:
            srt_path = audio_path.with_suffix(".srt")
            transcript = transcribe_to_srt(audio_path, srt_path)

        md_path = srt_path.with_suffix(".md")
        generate_markdown(transcript, md_path)
        click.echo(f"Transcript: {md_path}")

        sections = auto_generate_sections(transcript, interval)
        sections_path = out_dir / f"{out_dir.name}.sections"
        save_sections(sections, sections_path)
        click.echo(f"Sections:   {sections_path}")
        click.echo("Prepare complete. Edit the .sections file before building if desired.")

    except (FileNotFoundError, EnvironmentError, RuntimeError) as exc:
        raise click.ClickException(str(exc))


@main.command()
@click.option("--input", "input_dir", required=True, help="Directory containing prepared assets.")
@click.option("--num-questions", default=5, show_default=True, help="Number of quiz questions to generate.")
@click.option("--xlsx", is_flag=True, default=False, help="Also export quiz as an .xlsx file.")
def quiz(input_dir: str, num_questions: int, xlsx: bool) -> None:
    """Generate quiz.json from the markdown transcript.

    Uses Claude when ANTHROPIC_API_KEY is set, else OpenAI GPT-4o-mini when
    OPENAI_API_KEY is set; otherwise uses a built-in word-blanking fallback
    that requires no API key.
    """
    try:
        out_dir = Path(input_dir)
        md_files = list(out_dir.glob("*.md"))
        if not md_files:
            raise FileNotFoundError("No markdown transcript found. Run 'prepare' first.")

        _echo_quiz_source()
        questions = generate_quiz_from_transcript(str(md_files[0]), num_questions)
        quiz_path = out_dir / QUIZ_JSON_NAME
        save_quiz_to_json(questions, str(quiz_path))
        click.echo(f"Quiz:       {quiz_path}")

        if xlsx:
            xlsx_path = out_dir / "quiz.xlsx"
            save_quiz_to_xlsx(questions, str(xlsx_path))
            click.echo(f"XLSX:       {xlsx_path}")

        click.echo("Quiz complete. Run 'build' to include it in the SCORM package.")

    except (FileNotFoundError, ImportError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc))


@main.command()
@click.option("--video", required=True, help="Local path or HTTP(S) URL used as the video player source.")
@click.option("--input", "input_dir", required=True, help="Directory containing prepared assets.")
@click.option("--title", default="SCORM Lesson", show_default=True, help="Lesson title shown in the player.")
@click.option(
    "--video-mode",
    type=click.Choice(["embed", "url", "youtube"]),
    default=None,
    help="How to source the video: embed (copy/download into the package, zero "
         "external calls at playback), url (reference as-is, e.g. a signed URL), "
         "or youtube (iframe embed, requires --allow-youtube). Defaults from "
         "--video: local path → embed, http(s) → url, youtube URL → youtube.",
)
@click.option(
    "--allow-youtube", is_flag=True, default=False,
    help="Required to build from a youtube.com/youtu.be source — YouTube is a "
         "marketing-funnel source only, not for FI delivery.",
)
@click.option(
    "--video-expiry", default=None,
    help="ISO date/datetime (e.g. 2026-12-31) after which the player shows a "
         "license-expired panel instead of the video. Only meaningful with "
         "--video-mode url (the technical kill switch for a signed URL).",
)
@click.option(
    "--license-message", default=None,
    help="Override the message shown in the license-expired panel.",
)
@click.option(
    "--scorm", type=click.Choice(["1.2", "2004"]), default="1.2", show_default=True,
    help="SCORM manifest version to write. Use 'package --scorm both' to also "
         "produce a second version at packaging time.",
)
@_certificate_options
def build(
    video: str,
    input_dir: str,
    title: str,
    video_mode: str | None,
    allow_youtube: bool,
    video_expiry: str | None,
    license_message: str | None,
    scorm: str,
    logo: str | None,
    signer_name: str | None,
    signer_title: str | None,
) -> None:
    """Render the HTML player and SCORM manifest."""
    try:
        resolved_mode = _resolve_video_mode(video, video_mode, allow_youtube)
        effective_expiry = _resolve_video_expiry(resolved_mode, video_expiry)

        out_dir = Path(input_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        _apply_certificate_settings(out_dir, logo, signer_name, signer_title)

        srt_files = list(out_dir.glob("*.srt"))
        if not srt_files:
            raise FileNotFoundError("No .srt file found in input directory. Run 'prepare' first.")

        transcript = parse_srt(srt_files[0])

        sections_path = out_dir / f"{out_dir.name}.sections"
        sections = load_sections(sections_path, transcript)
        if not sections:
            sections = auto_generate_sections(transcript, 300)
            save_sections(sections, sections_path)

        quiz_exists = (out_dir / QUIZ_JSON_NAME).exists()

        html_path = generate_player_html(
            transcript, sections, title, out_dir, video, resolved_mode,
            effective_expiry, license_message,
        )
        manifest_path = generate_manifest(
            title, out_dir, include_quiz=quiz_exists, scorm_version=scorm,
            extra_files=_embedded_files(video, resolved_mode, out_dir),
        )

        click.echo(f"Player:     {html_path}" + ("  (with quiz)" if quiz_exists else ""))
        click.echo(f"Manifest:   {manifest_path}")
        click.echo("Build complete. Run 'package' to create the SCORM zip.")

    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc))


@main.command("package")
@click.option("--input", "input_dir", required=True, help="Directory containing built assets.")
@click.option("--title", default="SCORM Lesson", show_default=True, help="Lesson title (used for zip filename).")
@click.option(
    "--scorm", type=click.Choice(["1.2", "2004", "both"]), default="1.2", show_default=True,
    help="SCORM manifest version(s) to package. 'both' regenerates the manifest "
         "and produces a separate zip for each version.",
)
def package_cmd(input_dir: str, title: str, scorm: str) -> None:
    """Bundle built assets into a SCORM-compliant zip file."""
    try:
        out_dir = Path(input_dir)
        zip_paths = _package_scorm_versions(title, out_dir, scorm)
        for zip_path in zip_paths:
            click.echo(f"SCORM package: {zip_path}")

    except (FileNotFoundError, NotADirectoryError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc))


@main.command("run")
@click.option("--video", required=True, help="Local path or HTTP(S) URL to the video file.")
@click.option("--output", required=True, help="Output directory for processed assets.")
@click.option("--title", default="SCORM Lesson", show_default=True, help="Lesson title.")
@click.option("--subtitles", default=None, help="Existing .srt subtitle file (skips Whisper).")
@click.option("--interval", default=300, show_default=True, help="Section auto-generation interval in seconds.")
@click.option("--no-segment", is_flag=True, default=False, help="Skip video segmentation.")
@click.option("--num-questions", default=5, show_default=True, help="Number of quiz questions.")
@click.option("--xlsx", is_flag=True, default=False, help="Also export quiz as .xlsx.")
@click.option("--auto", is_flag=True, default=False, help="Skip review prompts (fully automated).")
@click.option(
    "--video-mode",
    type=click.Choice(["embed", "url", "youtube"]),
    default=None,
    help="How to source the video: embed (copy/download into the package, zero "
         "external calls at playback), url (reference as-is, e.g. a signed URL), "
         "or youtube (iframe embed, requires --allow-youtube). Defaults from "
         "--video: local path → embed, http(s) → url, youtube URL → youtube.",
)
@click.option(
    "--allow-youtube", is_flag=True, default=False,
    help="Required to build from a youtube.com/youtu.be source — YouTube is a "
         "marketing-funnel source only, not for FI delivery.",
)
@click.option(
    "--video-expiry", default=None,
    help="ISO date/datetime (e.g. 2026-12-31) after which the player shows a "
         "license-expired panel instead of the video. Only meaningful with "
         "--video-mode url (the technical kill switch for a signed URL).",
)
@click.option(
    "--license-message", default=None,
    help="Override the message shown in the license-expired panel.",
)
@click.option(
    "--scorm", type=click.Choice(["1.2", "2004", "both"]), default="1.2", show_default=True,
    help="SCORM manifest version(s) to package. 'both' produces a separate zip "
         "for each version.",
)
@_certificate_options
def run_pipeline(
    video: str,
    output: str,
    title: str,
    subtitles: str | None,
    interval: int,
    no_segment: bool,
    num_questions: int,
    xlsx: bool,
    auto: bool,
    video_mode: str | None,
    allow_youtube: bool,
    video_expiry: str | None,
    license_message: str | None,
    scorm: str,
    logo: str | None,
    signer_name: str | None,
    signer_title: str | None,
) -> None:
    """Full pipeline: prepare → quiz → [review] → build → package.

    Pauses after generating sections and quiz questions so you can edit
    them before the final build. Use --auto to skip review prompts.
    """
    try:
        resolved_mode = _resolve_video_mode(video, video_mode, allow_youtube)
        effective_expiry = _resolve_video_expiry(resolved_mode, video_expiry)

        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        _apply_certificate_settings(out_dir, logo, signer_name, signer_title)

        # ── 1 / 4  PREPARE ───────────────────────────────────────────────
        click.echo("\n[1/4] Preparing video assets…")
        result = process_video(video, output, no_segment=no_segment)
        audio_path = Path(result["audio"])  # type: ignore[arg-type]

        if subtitles:
            srt_src = Path(subtitles)
            srt_path = out_dir / srt_src.name
            if srt_src.resolve() != srt_path.resolve():
                shutil.copy(srt_src, srt_path)
            transcript = parse_srt(srt_path)
            click.echo(f"      Subtitles : {srt_path}")
        else:
            srt_path = audio_path.with_suffix(".srt")
            transcript = transcribe_to_srt(audio_path, srt_path)
            click.echo(f"      Transcript: {srt_path}")

        md_path = srt_path.with_suffix(".md")
        generate_markdown(transcript, md_path)

        sections = auto_generate_sections(transcript, interval)
        sections_path = out_dir / f"{out_dir.name}.sections"
        save_sections(sections, sections_path)
        click.echo(f"      Sections  : {len(sections)} section(s) → {sections_path}")

        # ── 2 / 4  QUIZ ──────────────────────────────────────────────────
        click.echo("\n[2/4] Generating quiz questions…")
        _echo_quiz_source()
        questions = generate_quiz_from_transcript(str(md_path), num_questions)
        quiz_path = out_dir / QUIZ_JSON_NAME
        save_quiz_to_json(questions, str(quiz_path))
        click.echo(f"      Questions : {len(questions)} question(s) → {quiz_path}")

        if xlsx:
            xlsx_path = out_dir / "quiz.xlsx"
            save_quiz_to_xlsx(questions, str(xlsx_path))
            click.echo(f"      XLSX      : {xlsx_path}")

        # ── REVIEW PAUSE ─────────────────────────────────────────────────
        if not auto:
            click.echo("\n" + "─" * 60)
            click.echo("REVIEW — edit before packaging:")
            click.echo(f"  1. Sections file : {sections_path}")
            click.echo(f"     (timestamps and chapter titles — one per line)")
            click.echo(f"  2. Quiz file     : {quiz_path}")
            click.echo(f"     (questions, options, and correct answers)")
            click.echo("─" * 60)

            if click.confirm("\n  Open sections file in your editor?", default=True):
                click.edit(filename=str(sections_path))

            if click.confirm("  Open quiz file in your editor?", default=True):
                click.edit(filename=str(quiz_path))

            click.confirm("\nContinue to build and package?", default=True, abort=True)

        # Reload from disk — the user may have edited sections and/or quiz.
        transcript = parse_srt(srt_path)
        sections = load_sections(sections_path, transcript)
        if not sections:
            sections = auto_generate_sections(transcript, interval)
            save_sections(sections, sections_path)

        # ── 3 / 4  BUILD ─────────────────────────────────────────────────
        click.echo("\n[3/4] Building SCORM assets…")
        html_path = generate_player_html(
            transcript, sections, title, out_dir, video, resolved_mode,
            effective_expiry, license_message,
        )
        click.echo(f"      Player   : {html_path}")

        # ── 4 / 4  PACKAGE ───────────────────────────────────────────────
        click.echo("\n[4/4] Packaging SCORM zip…")
        zip_paths = _package_scorm_versions(
            title, out_dir, scorm, extra_files=_embedded_files(video, resolved_mode, out_dir),
        )

        click.echo("\n" + "─" * 60)
        for zip_path in zip_paths:
            click.echo(f"SCORM package ready: {zip_path}")
        click.echo("─" * 60)

    except (FileNotFoundError, EnvironmentError, RuntimeError, ImportError, ValueError) as exc:
        raise click.ClickException(str(exc))


if __name__ == "__main__":
    main()
