"""SCORM packaging utilities.

The manifest is the allowlist: a package contains imsmanifest.xml plus exactly
the files its <file href> entries name, and nothing else. Working files left in
the build folder (audio.mp3, .srt, transcript.md, segment_*.mp4, old zips) are
never packaged.
"""

from pathlib import Path, PurePosixPath
from typing import List
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

MANIFEST_NAME = "imsmanifest.xml"


def manifest_files(manifest_path: Path) -> List[str]:
    """Return the package-relative paths named by <file href> in the manifest,
    in manifest order, without duplicates.

    Raises:
        ValueError: the manifest does not parse, or a path is absolute or
            escapes the package folder.
    """
    try:
        root = ET.parse(manifest_path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{MANIFEST_NAME} is not valid XML: {exc}") from exc

    files: List[str] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "file":
            continue
        href = el.get("href", "")
        path = PurePosixPath(href)
        if not href or path.is_absolute() or ".." in path.parts or "\\" in href or ":" in href:
            raise ValueError(f"{MANIFEST_NAME} lists a path outside the package: {href!r}")
        if href != MANIFEST_NAME and href not in files:
            files.append(href)
    return files


def create_scorm_package(source_dir: str, output_zip: str) -> None:
    """Zip imsmanifest.xml and the files it lists into output_zip.

    Raises:
        NotADirectoryError: source_dir does not exist.
        FileNotFoundError: imsmanifest.xml, or a file it lists, is missing.
        ValueError: the manifest is invalid or lists a path outside the package.
    """
    src = Path(source_dir)
    if not src.is_dir():
        raise NotADirectoryError(f"Source directory not found: {source_dir}")

    manifest = src / MANIFEST_NAME
    if not manifest.is_file():
        raise FileNotFoundError(f"{MANIFEST_NAME} not found — run 'build' first.")

    allowed = [MANIFEST_NAME] + manifest_files(manifest)
    missing = [name for name in allowed if not (src / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Files listed in {MANIFEST_NAME} are missing from {src}: {', '.join(missing)}"
        )

    with ZipFile(output_zip, "w", compression=ZIP_DEFLATED) as zf:
        for name in allowed:
            zf.write(src / name, name)
        packaged = zf.namelist()

    if sorted(packaged) != sorted(allowed):  # guard: nothing outside the allowlist
        Path(output_zip).unlink(missing_ok=True)
        raise RuntimeError(f"Package contents do not match {MANIFEST_NAME}: {packaged}")
