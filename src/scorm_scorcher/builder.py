"""HTML player and SCORM manifest generation."""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import List, Sequence
from xml.sax.saxutils import escape as _xml_escape

from .scorm_packager import MANIFEST_NAME, manifest_files
from .video_processing import download_for_embed, embedded_video_name

TEMPLATE_DIR = Path(__file__).parent / "templates"
QUIZ_HTML_NAME = "quiz.html"  # the old separate quiz page; no longer built
QUIZ_JSON_NAME = "quiz.json"
BRANDING_NAME = "branding.css"
SCORM_SHIM_NAME = "scorm-shim.js"

VIDEO_MODES = ("embed", "url", "youtube")

# Files the lesson SCO needs, as listed in imsmanifest.xml. The packager zips
# exactly what the manifest lists, so this list is the package allowlist.
# The quiz lives inside index.html (one SCO), so the quiz can stay locked until
# the video has been watched. quiz.json is not shipped: its questions are copied
# into index.html at build time. It stays in the build folder for editing.
PLAYER_FILES = ("index.html", BRANDING_NAME, SCORM_SHIM_NAME)

_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def _fill(template: str, values: dict) -> str:
    """Replace every {{NAME}} in one pass.

    Inserted text is never scanned again, so a title or transcript line that
    happens to contain "{{VIDEO}}" is shown as typed instead of substituted.
    """
    def sub(match):
        name = match.group(1)
        if name not in values:
            raise KeyError(f"Template placeholder {{{{{name}}}}} has no value")
        return values[name]
    return _PLACEHOLDER.sub(sub, template)

def _html_text(value: str) -> str:
    """Escape a user-supplied value for HTML text or a quoted attribute."""
    return html.escape(value, quote=True)


def _script_safe(json_text: str) -> str:
    """Make JSON text safe to place inside a <script> block.

    In valid JSON, '<', '>' and '&' can only occur inside strings, where the
    \\u escapes mean the same characters. So the data is unchanged, but text
    such as '</script>' can no longer end the script block early.
    """
    return (
        json_text
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _script_json(value) -> str:
    """Encode a value (string, list, dict…) as JSON that is safe inside <script>.

    A JSON value is also a valid JavaScript literal.
    """
    return _script_safe(json.dumps(value))


DEFAULT_LICENSE_MESSAGE = (
    "This training license has expired. Please contact FCI Tradecraft to renew access."
)


def generate_player_html(
    transcript: List[dict],
    sections: List[dict],
    title: str,
    output_dir: Path,
    video_src: str,
    video_mode: str,
    video_expiry: str | None = None,
    license_message: str | None = None,
) -> Path:
    """Render the lesson page (video player + quiz) into output_dir/index.html.

    If output_dir/quiz.json exists, its questions are built into the page. The
    quiz stays hidden until the learner has watched the whole video once; on
    that first viewing they cannot skip ahead or play faster than 2x.

    video_mode:
      "embed"   — video is copied (local path) or downloaded (http(s) URL)
                  into the package and referenced by relative filename; the
                  built package makes no external call to play it.
      "url"     — video_src (e.g. a signed, expiring URL) is referenced
                  as-is and never copied into the package.
      "youtube" — video_src is embedded via the YouTube iframe API.

    video_expiry is only meaningful for video_mode="url" — an embedded MP4
    has no technical kill switch, and youtube content isn't license-gated,
    so expiry is silently dropped for those modes rather than rendering a
    misleading countdown on content that can't actually be revoked.
    """
    if video_mode not in VIDEO_MODES:
        raise ValueError(f"Unknown video_mode: {video_mode!r} (expected one of {VIDEO_MODES})")

    template = (TEMPLATE_DIR / "player_template.html").read_text(encoding="utf-8")
    shutil.copy(TEMPLATE_DIR / BRANDING_NAME, output_dir / BRANDING_NAME)
    shutil.copy(TEMPLATE_DIR / SCORM_SHIM_NAME, output_dir / SCORM_SHIM_NAME)

    if video_mode == "embed":
        if video_src.startswith("http://") or video_src.startswith("https://"):
            local_path = download_for_embed(video_src, output_dir)
        else:
            video_path = Path(video_src)
            dest = output_dir / embedded_video_name(video_src)
            if video_path.resolve() != dest.resolve():
                shutil.copy(video_path, dest)
            local_path = dest
        video_value = local_path.name
        video_type = "local"
    else:
        video_value = video_src
        video_type = video_mode  # "url" or "youtube"

    expiry_value = video_expiry if (video_mode == "url" and video_expiry) else ""

    quiz_json_path = output_dir / QUIZ_JSON_NAME
    quiz_data = load_quiz_data(quiz_json_path) if quiz_json_path.exists() else {"questions": []}

    html = _fill(template, {
        "TITLE": _html_text(title),
        "TITLE_JSON": _script_json(title),
        "TRANSCRIPT_JSON": _script_json(transcript),
        "SECTIONS_JSON": _script_json(sections),
        "QUIZ_JSON": _script_json(quiz_data),
        "VIDEO_ATTR": _html_text(video_value),
        "VIDEO_JSON": _script_json(video_value),
        "VIDEO_TYPE": video_type,
        "VIDEO_EXPIRY": expiry_value,
        "LICENSE_MESSAGE_JSON": _script_json(license_message or DEFAULT_LICENSE_MESSAGE),
        "CERTIFICATE_PARTIAL": (TEMPLATE_DIR / "certificate_partial.html").read_text(encoding="utf-8"),
    })

    out = output_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    # A quiz.html left by an older build would be a second, ungated copy of the
    # quiz when previewing locally. It is never packaged; remove it anyway.
    (output_dir / QUIZ_HTML_NAME).unlink(missing_ok=True)
    return out


def load_quiz_data(path: Path) -> dict:
    """Read quiz.json, with a plain-English error if it isn't valid JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path.name} has a typo on line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("questions", []), list):
        raise ValueError(f'{path.name} must look like {{"questions": [ ... ]}}')
    return data


# (prefix, namespace URI, schema file) — prefix None means the default xmlns.
_SCORM_1P2 = {
    "schema_version": "1.2",
    "namespaces": [
        (None, "http://www.imsproject.org/xsd/imscp_rootv1p1p2", "imscp_rootv1p1p2.xsd"),
        ("adlcp", "http://www.adlnet.org/xsd/adlcp_rootv1p2", "adlcp_rootv1p2.xsd"),
    ],
    "masteryscore": True,
    # SCORM 1.2 spells the SCO-type attribute all lowercase.
    "scormtype_attr": "adlcp:scormtype",
}

_SCORM_2004 = {
    "schema_version": "2004 4th Edition",
    "namespaces": [
        (None, "http://www.imsglobal.org/xsd/imscp_v1p1", "imscp_v1p1.xsd"),
        ("adlcp", "http://www.adlnet.org/xsd/adlcp_v1p3", "adlcp_v1p3.xsd"),
        ("adlseq", "http://www.adlnet.org/xsd/adlseq_v1p3", "adlseq_v1p3.xsd"),
        ("adlnav", "http://www.adlnet.org/xsd/adlnav_v1p3", "adlnav_v1p3.xsd"),
        ("imsss", "http://www.imsglobal.org/xsd/imsss", "imsss_v1p0.xsd"),
    ],
    # SCORM 2004 has no manifest-level mastery score — pass/fail is the SCO's
    # own cmi.success_status, already set by scorm-shim.js.
    "masteryscore": False,
    # SCORM 2004 (CAM, adlcp_v1p3) spells it camelCase.
    "scormtype_attr": "adlcp:scormType",
}

SCORM_VERSIONS = {"1.2": _SCORM_1P2, "2004": _SCORM_2004}

_XML_QUOTES = {'"': "&quot;", "'": "&apos;"}


def _xml_text(value: str) -> str:
    """Escape a user-supplied value for XML text or a quoted attribute."""
    return _xml_escape(value, _XML_QUOTES)


def _manifest_identifier(title: str) -> str:
    """Build a manifest identifier that is a valid xs:ID (an XML NCName).

    Escaping alone is not enough: "AML_&amp;_SANCTIONS" would parse but is not
    a valid ID. Anything outside letters, digits, '_', '-' and '.' becomes '_',
    and a leading character that cannot start an NCName gets an 'ID_' prefix.
    """
    ident = re.sub(r"[^A-Za-z0-9_.-]", "_", title).upper() + "_SCORM"
    if not re.match(r"[A-Za-z_]", ident):
        ident = "ID_" + ident
    return ident


def _file_lines(names: Sequence[str]) -> str:
    return "".join(f'      <file href="{_xml_text(name)}" />\n' for name in names)


def package_basename(title: str) -> str:
    """Zip filename stem for a title: letters, digits, '-' and '_' only.

    "AML & Sanctions" -> "AML_Sanctions". The title shown inside the course
    is unchanged; only the filename is simplified.
    """
    return re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") or "SCORM_Lesson"


def manifest_extra_files(output_dir: Path) -> List[str]:
    """Files an existing manifest lists beyond the standard player and quiz
    files (e.g. the embedded video), so a regenerated manifest keeps them."""
    path = output_dir / MANIFEST_NAME
    if not path.is_file():
        return []
    # quiz.html and quiz.json count as standard so a manifest from an older
    # build (separate quiz page) doesn't carry them forward as "extra" files.
    standard = set(PLAYER_FILES) | {QUIZ_HTML_NAME, QUIZ_JSON_NAME}
    return [name for name in manifest_files(path) if name not in standard]


def generate_manifest(
    title: str,
    output_dir: Path,
    include_quiz: bool = False,
    scorm_version: str = "1.2",
    extra_files: Sequence[str] = (),
) -> Path:
    """Write an imsmanifest.xml SCORM manifest (1.2 or 2004) into output_dir.

    The lesson is one SCO (index.html holds the video and the quiz).
    include_quiz adds the 80% mastery score for SCORM 1.2.

    extra_files are added to the lesson resource, e.g. the video in embed mode.
    Every file the package will contain is listed here; the packager zips
    nothing else.

    The <organizations>/<resources> skeleton is identical between versions;
    only the namespace/schema header, <schemaversion>, and presence of
    <adlcp:masteryscore> differ (SCORM 2004 has no manifest-level mastery
    score — see SCORM_VERSIONS).
    """
    if scorm_version not in SCORM_VERSIONS:
        raise ValueError(
            f"Unknown scorm_version: {scorm_version!r} (expected one of {tuple(SCORM_VERSIONS)})"
        )
    cfg = SCORM_VERSIONS[scorm_version]

    identifier = _manifest_identifier(title)
    sco_attr = cfg["scormtype_attr"]
    title_xml = _xml_text(title)

    xmlns_lines = []
    schema_pairs = []
    for prefix, uri, xsd in cfg["namespaces"]:
        attr = "xmlns" if prefix is None else f"xmlns:{prefix}"
        xmlns_lines.append(f'  {attr}="{uri}"')
        schema_pairs.append(f"{uri} {xsd}")
    xmlns_block = "\n".join(xmlns_lines)
    schema_location = "\n                      ".join(schema_pairs)

    masteryscore_line = (
        "        <adlcp:masteryscore>80</adlcp:masteryscore>\n"
        if include_quiz and cfg["masteryscore"] else ""
    )

    manifest = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{identifier}" version="1.0"
{xmlns_block}
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="{schema_location}">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>{cfg['schema_version']}</schemaversion>
  </metadata>
  <organizations default="ORG1">
    <organization identifier="ORG1">
      <title>{title_xml}</title>
      <item identifier="ITEM1" identifierref="RES1">
        <title>{title_xml}</title>
{masteryscore_line}      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES1" type="webcontent" {sco_attr}="sco" href="index.html">
{_file_lines(list(PLAYER_FILES) + list(extra_files))}    </resource>
  </resources>
</manifest>"""

    out = output_dir / "imsmanifest.xml"
    out.write_text(manifest, encoding="utf-8")
    return out
