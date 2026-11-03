"""Tests for scorm_packager.py.

The manifest is the allowlist: these tests build real manifests with
generate_manifest and check the ZIP's file list against them.
"""

import zipfile
from pathlib import Path

import pytest

from scorm_scorcher.builder import PLAYER_FILES, QUIZ_FILES, generate_manifest
from scorm_scorcher.scorm_packager import create_scorm_package, manifest_files

WORKING_FILES = [
    "audio.mp3",
    "subtitles.vtt",
    "lesson.srt",
    "transcript.md",
    "build.sections",
    "segment_000.mp4",
    "segment_001.mp4",
    ".video_source_url",
    "old_SCORM.zip",
    "notes/draft.txt",
]


def _make_build_dir(tmp_path: Path, include_quiz: bool = True, extra_files=()) -> Path:
    build = tmp_path / "build"
    build.mkdir()
    names = set(PLAYER_FILES) | (set(QUIZ_FILES) if include_quiz else set()) | set(extra_files)
    for name in names:
        (build / name).write_text("x", encoding="utf-8")
    generate_manifest("Lesson", build, include_quiz=include_quiz, extra_files=list(extra_files))
    return build


def _zip_names(path: Path) -> list:
    with zipfile.ZipFile(path) as zf:
        return sorted(zf.namelist())


@pytest.mark.parametrize("include_quiz", [True, False])
def test_zip_contains_exactly_manifest_files(tmp_path, include_quiz):
    build = _make_build_dir(tmp_path, include_quiz=include_quiz)
    out = tmp_path / "out.zip"
    create_scorm_package(str(build), str(out))
    expected = sorted(["imsmanifest.xml"] + manifest_files(build / "imsmanifest.xml"))
    assert _zip_names(out) == expected


def test_working_files_are_not_packaged(tmp_path):
    build = _make_build_dir(tmp_path, extra_files=["lesson.mp4"])
    for name in WORKING_FILES:
        (build / name).parent.mkdir(parents=True, exist_ok=True)
        (build / name).write_text("work", encoding="utf-8")
    out = tmp_path / "out.zip"
    create_scorm_package(str(build), str(out))

    names = _zip_names(out)
    for name in WORKING_FILES:
        assert name not in names
    assert "lesson.mp4" in names  # the embedded video is declared, so it is packaged


def test_zip_written_inside_build_dir_is_not_repackaged(tmp_path):
    build = _make_build_dir(tmp_path)
    first = build / "Lesson_SCORM.zip"
    create_scorm_package(str(build), str(first))
    second = build / "Lesson_SCORM_2004.zip"
    create_scorm_package(str(build), str(second))
    assert "Lesson_SCORM.zip" not in _zip_names(second)


def test_missing_required_file_raises(tmp_path):
    build = _make_build_dir(tmp_path, extra_files=["lesson.mp4"])
    (build / "scorm-shim.js").unlink()
    (build / "lesson.mp4").unlink()
    out = tmp_path / "out.zip"
    with pytest.raises(FileNotFoundError) as exc:
        create_scorm_package(str(build), str(out))
    assert "scorm-shim.js" in str(exc.value)
    assert "lesson.mp4" in str(exc.value)
    assert not out.exists()


@pytest.mark.parametrize("href", ["/etc/passwd", "../secret.txt", "C:\\video.mp4", "sub\\x.js"])
def test_manifest_path_outside_package_raises(tmp_path, href):
    build = _make_build_dir(tmp_path)
    manifest = build / "imsmanifest.xml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace('<file href="index.html" />', f'<file href="{href}" />'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="outside the package"):
        create_scorm_package(str(build), str(tmp_path / "out.zip"))


def test_invalid_manifest_raises(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    (build / "imsmanifest.xml").write_text("<manifest>", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid XML"):
        create_scorm_package(str(build), str(tmp_path / "out.zip"))


def test_missing_manifest_raises(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    (build / "index.html").write_text("<html/>")
    with pytest.raises(FileNotFoundError, match="imsmanifest.xml"):
        create_scorm_package(str(build), str(tmp_path / "out.zip"))


def test_missing_directory_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        create_scorm_package(str(tmp_path / "nonexistent"), str(tmp_path / "out.zip"))
