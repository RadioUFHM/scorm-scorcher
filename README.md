# scorm-scorcher

Convert a video into a SCORM package — a video player with synced transcript, an
auto-generated quiz, and a certificate on passing — ready to upload to an LMS.

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) on your `PATH`
- Optional: `openai-whisper`, for automatic transcription (or supply your own `.srt` file)
- Optional: an `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` environment variable, for
  AI-generated quiz questions (falls back to a built-in heuristic if neither is set)

## Install

```
pip install -e .
```

Optional extras:

```
pip install -e ".[transcribe]"  # Whisper, for auto-transcription
pip install -e ".[claude]"      # Claude quiz generation
pip install -e ".[quiz]"        # Claude + OpenAI quiz generation
pip install -e ".[xlsx]"        # quiz .xlsx export
pip install -e ".[full]"        # everything above
```

## Quickstart — one command

```
scorm-scorcher run --video lesson.mp4 --output ./build --title "My Lesson"
```

This extracts audio, transcribes it, generates chapter markers and quiz questions,
pauses so you can review/edit them, then builds and zips a SCORM package at
`./build/My_Lesson_SCORM.zip`. Pass `--auto` to skip the review pause and run
start to finish unattended.

## Step-by-step workflow

```
scorm-scorcher prepare --video lesson.mp4 --output ./build
scorm-scorcher quiz    --input ./build
scorm-scorcher build   --video lesson.mp4 --input ./build --title "My Lesson"
scorm-scorcher package --input ./build --title "My Lesson"
```

- **prepare** — extracts audio, transcribes it with Whisper (or pass
  `--subtitles existing.srt` to skip that), and writes an editable `.sections`
  file with chapter timestamps and titles, one per line.
- **quiz** — generates `quiz.json` from the transcript. Uses Claude if
  `ANTHROPIC_API_KEY` is set, otherwise OpenAI if `OPENAI_API_KEY` is set,
  otherwise a built-in word-blanking fallback that needs no API key at all.
  Add `--xlsx` to also export the quiz as a spreadsheet.
- **build** — renders the lesson page (`index.html`: video player plus quiz)
  and writes `imsmanifest.xml`. The quiz questions are copied from `quiz.json`
  into `index.html` at this step.
- **package** — zips `imsmanifest.xml` and exactly the files it lists into a
  SCORM `.zip`. Working files in the folder (`audio.mp3`, `.srt`,
  `transcript.md`, `.sections`, `quiz.json`, video segments) are never packaged. If a
  listed file is missing, packaging stops and names it.

### Editing the quiz

Edit `quiz.json` in the build folder after `quiz`, then run `build` again
before `package`. `package` alone does not re-read `quiz.json`, so edits made
after the last `build` won't reach the learner. `run` (without `--auto`)
pauses so you can edit the quiz, and rebuilds from your edited file.

## Video source options

`build` and `run` take `--video-mode` to control how the video is delivered:

- `embed` (default for a local file path) — the video is copied, or
  downloaded if given an http(s) URL, into the package. The built package
  plays with no external network call.
- `url` (default for an http(s) link) — the video is referenced by URL and
  never copied into the package. Combine with `--video-expiry 2026-12-31` and
  `--license-message "..."` to show a branded "license expired" panel instead
  of the video after that date — the quiz also refuses to show a certificate
  or report a pass once expired.
- `youtube` — embeds via the YouTube iframe API. Requires `--allow-youtube`;
  YouTube is treated as a marketing/demo source only, not for real course
  delivery.

## SCORM version

`build`, `package`, and `run` take `--scorm {1.2,2004,both}` (default `1.2`).
`both` produces two zip files, one per version, from the same build.

## Watching the video unlocks the quiz

The video and the quiz are one page and one SCO, so the quiz can't be opened
from the LMS menu early. On a learner's first viewing:

- They can rewind at any time but can't skip past the furthest point they've
  watched, including through chapter links (later chapters show a lock).
- Playback speed is capped at 2x.
- When the video ends, the quiz appears below it and the page scrolls to it.

Progress is saved to the LMS (`cmi.suspend_data`, with `cmi.exit` set to
`suspend`), so a learner who leaves and comes back resumes where they were,
and anyone who has finished the video once can seek freely and go straight
to the quiz. Failing the quiz allows an immediate retake; a retake never
lowers a pass already recorded. Without a quiz, finishing the video marks the
lesson complete.

## Certificate

When a learner scores 80% or higher on the quiz, a "View / Print Certificate"
button appears on the results screen. It renders and prints (or saves as PDF)
on one landscape page entirely in the browser, with no server involved.

The learner's name comes from the LMS. If the LMS supplies none (or in a local
preview), the learner is asked to type the name for the certificate.

Add a logo and a signature line when building:

```
scorm-scorcher build ... --logo my-logo.png --signer-name "Rio Miner" --signer-title "Principal"
```

These are saved in `certificate.json` in the build folder, so later builds
reuse them without retyping (edit that file, or pass `--logo ""` /
`--signer-name ""` to remove one). The logo is copied into the package as
`cert-logo.<ext>`; `certificate.json` itself is never packaged.

## Quiz answer key

The quiz is graded in the learner's browser, so the correct answers ship
inside the package, in `index.html`. A learner who opens the page source can
find them. SCORM has no server-side grading, so this is true of browser-graded
SCORM quizzes in general. (`quiz.json`, your editable copy, stays in the build
folder and is not packaged.)

Treat the quiz as a completion and comprehension check, not a secure exam.
Each answer, and the correct response, is also sent to the LMS through
`cmi.interactions`, so an administrator can review attempts there.

## Testing

### Automated tests

```
pytest
```

### Preview a build in your browser (no LMS needed)

SCORM tracking calls are all silent no-ops when no LMS API is present, so you
can preview a build directly in a plain browser:

```
scorm-scorcher build --video lesson.mp4 --input ./build --title "My Lesson"
cd build
npx --yes http-server -p 8000
```

Then open `http://localhost:8000/` in your browser. Use a server that supports
HTTP range requests, like `http-server`: Python's `python3 -m http.server`
does not, so the browser can't jump around in the video and chapter links
restart it from 0:00. Serving over `http://` rather than double-clicking the
file also avoids browser quirks with local video/iframe playback.

The quiz stays locked until the whole video has played. To check the quiz
without watching, open `http://localhost:8000/?unlock`. This only works with
no LMS present; inside an LMS the gate always applies.

This lets you check video playback, transcript sync, the quiz flow and
feedback, the certificate (pass the quiz to see it), and the license-expired
panel — rebuild with `--video-mode url --video-expiry 2020-01-01` to see that
panel. It won't exercise real SCORM score/resume tracking, since that
requires an actual LMS API.

### Testing real SCORM tracking

To verify score reporting, resume-after-reload, and `cmi.interactions`
without standing up your own LMS:

- Upload the built `.zip` to [SCORM Cloud](https://cloud.scorm.com) (free,
  browser-based, supports both SCORM 1.2 and 2004).
- Or install [Moodle](https://moodle.org) (self-hosted, or via the
  `bitnami/moodle` Docker image) and add the package as a course's "SCORM
  package" activity.
