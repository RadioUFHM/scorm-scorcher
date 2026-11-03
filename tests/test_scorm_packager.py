"""Tests for scorm_packager.py."""

import zipfile
from pathlib import Path

import pytest

from scorm_scorcher.scorm_packager import create_scorm_package


def _make_build_dir(tmp_path: Path) -> Path:
    build = tmp_path / "build"
    build.mkdir()
    (build / "imsmanifest.xml").write_text("<manifest/>", encoding="utf-8")
    (build / "index.html").write_text("<html/>", encoding="utf-8")
    (build / "branding.css").write_text("body{}", encoding="utf-8")
    return build


def test_creates_zip(tmp_path):
    build = _make_build_dir(tmp_path)
    out = tmp_path / "out.zip"
    create_scorm_package(str(build), str(out))
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "imsmanifest.xml" in names
    assert "index.html" in names


def test_zip_excluded_from_zip(tmp_path):
    build = _make_build_dir(tmp_path)
    (build / "old.zip").write_text("old", encoding="utf-8")
    out = tmp_path / "out.zip"
    create_scorm_package(str(build), str(out))
    with zipfile.ZipFile(out) as zf:
        assert "old.zip" not in zf.namelist()


def test_missing_manifest_raises(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    (build / "index.html").write_text("<html/>")
    with pytest.raises(FileNotFoundError, match="imsmanifest.xml"):
        create_scorm_package(str(build), str(tmp_path / "out.zip"))


def test_missing_directory_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        create_scorm_package(str(tmp_path / "nonexistent"), str(tmp_path / "out.zip"))
