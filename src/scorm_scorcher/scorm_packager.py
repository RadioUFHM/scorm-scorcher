"""SCORM packaging utilities."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def create_scorm_package(source_dir: str, output_zip: str) -> None:
    """Zip source_dir into a SCORM-compliant package at output_zip.

    Raises:
        NotADirectoryError: source_dir does not exist.
        FileNotFoundError: imsmanifest.xml is missing from source_dir.
    """
    src = Path(source_dir)
    if not src.is_dir():
        raise NotADirectoryError(f"Source directory not found: {source_dir}")

    manifest = src / "imsmanifest.xml"
    if not manifest.is_file():
        raise FileNotFoundError("imsmanifest.xml not found — run 'build' first.")

    with ZipFile(output_zip, "w", compression=ZIP_DEFLATED) as zf:
        for file in src.rglob("*"):
            if file.is_dir() or file.suffix == ".zip":
                continue
            zf.write(file, file.relative_to(src))
