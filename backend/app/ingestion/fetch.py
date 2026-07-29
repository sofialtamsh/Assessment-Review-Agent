"""Fetch session content directly from the links in the mastersheet.

The CV mastersheet references content per session (Google Slides "Embedded links",
or direct .pptx/.pdf on S3). We do NOT generate anything — we pull the real content:
  * Google Slides published URL -> fetch the /pub HTML, read slide text from the
    SVG aria-label attributes (the published viewer renders each text box there).
  * Direct .pptx / .pdf / .txt / .md URL -> download and run the normal parsers.
Then chunk exactly like an uploaded file.
"""
from __future__ import annotations

import html as htmlmod
import re

import httpx

from ..schemas import Chunk
from .content import chunk_segments, parse_content

_GSLIDES = re.compile(r"docs\.google\.com/presentation", re.I)
_GDOC = re.compile(r"docs\.google\.com/document/d/([A-Za-z0-9_-]+)", re.I)
_GSHEET = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)", re.I)
_GDRIVE_FILE = re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)", re.I)
_GDRIVE_UC = re.compile(r"drive\.google\.com/uc\?[^ ]*?id=([A-Za-z0-9_-]+)", re.I)
_SLIDES_ID = re.compile(r"/presentation/d/(?:e/)?([A-Za-z0-9_-]+)", re.I)
_PUB_ID = re.compile(r"(/presentation/d/(?:e/)?[^/]+)", re.I)
_HEX = re.compile(r"\\x([0-9A-Fa-f]{2})")
_ARIA = re.compile(r'aria-label="([^"]{2,400})"')
_ASSET = re.compile(r"\.(png|jpe?g|gif|svg|webp)$", re.I)
_NUMISH = re.compile(r"^[\d\s().,+\-]+$")
_SKIP = {"speaker notes", "click to add text", "click to add title"}


def fetch_doc_text(url: str, timeout: float = 45.0) -> str:
    """Fetch the plain text of a shared Google Doc (or a direct text/markdown URL).

    Google Docs shared 'anyone with link' export publicly via /export?format=txt.
    """
    url = (url or "").strip()
    m = _GDOC.search(url)
    if m:
        export = f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
        resp = httpx.get(export, timeout=timeout, follow_redirects=True)
        if resp.status_code in (401, 403):
            raise PermissionError(
                "This Google Doc isn't shared publicly. In Google Drive open it > Share > "
                "General access > 'Anyone with the link' (Viewer). Or use Advanced > manual "
                "upload to provide the file for this unit."
            )
        resp.raise_for_status()
        if "text/html" in resp.headers.get("content-type", ""):
            raise PermissionError(
                "This Google Doc isn't shared publicly (a sign-in page was returned). Set it to "
                "'Anyone with the link' (Viewer), or upload the file manually."
            )
        return resp.text
    # plain text / markdown / other direct URL
    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_content(session_id: str, url: str, timeout: float = 45.0) -> list[Chunk]:
    url = (url or "").strip()
    if not url.lower().startswith("http"):
        raise ValueError("content_path is not a URL — upload the file instead.")
    if _GSLIDES.search(url):
        segments = _google_slides_segments(url, timeout)
    else:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        fname = (url.split("?")[0].rstrip("/").split("/")[-1] or "content").lower()
        if "." not in fname:
            fname += ".txt"
        return parse_content(session_id, resp.content, fname)
    return chunk_segments(session_id, segments)


def _google_slides_segments(url: str, timeout: float) -> list[tuple[str, str]]:
    pub = _to_pub_url(url)
    raw = httpx.get(pub, timeout=timeout, follow_redirects=True).text
    # the viewer embeds slides as escaped SVG strings — unescape \xNN first
    txt = _HEX.sub(lambda m: chr(int(m.group(1), 16)), raw)

    lines: list[str] = []
    seen: set[str] = set()
    for label in _ARIA.findall(txt):
        s = htmlmod.unescape(label).replace("&#xa;", " ")
        s = re.sub(r"\s+", " ", s).strip()
        low = s.lower()
        if len(s) <= 3 or low in seen or low in _SKIP:
            continue
        if _ASSET.search(low) or _NUMISH.match(s):
            continue
        seen.add(low)
        lines.append(s)

    if not lines:
        return []
    return [("Slides", "\n".join(lines))]


def _to_pub_url(url: str) -> str:
    """Normalize any Google Slides link to its published .../pub HTML page."""
    m = _PUB_ID.search(url)
    if m:
        return "https://docs.google.com" + m.group(1).rstrip("/") + "/pub"
    return url


# --------------------------------------------------------------------------- #
# Tutorial cheat-sheet (extra reference content) — a Google Sheet / .xlsx
# --------------------------------------------------------------------------- #
def looks_like_doc_source(url: str) -> bool:
    """True if the link is a Google Doc or a direct .doc/.docx — the tutorial doc
    that also carries the in-class MCQs at the end (vs a .xlsx/Sheet cheat-sheet)."""
    u = (url or "").strip().lower()
    return bool(_GDOC.search(u)) or u.split("?")[0].endswith((".doc", ".docx"))


def fetch_spreadsheet_bytes(url: str, timeout: float = 45.0, *, what: str = "spreadsheet") -> bytes:
    """Download a spreadsheet as .xlsx bytes.

    A Google Sheet is exported via /export?format=xlsx (this preserves cell hyperlinks,
    which the mastersheet/tutorial parsers rely on); any other URL is downloaded as-is.
    `what` only tweaks the not-shared-publicly error message.
    """
    url = (url or "").strip()
    m = _GSHEET.search(url)
    if m:
        export = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=xlsx"
        resp = httpx.get(export, timeout=timeout, follow_redirects=True)
        if resp.status_code in (401, 403):
            raise PermissionError(
                f"This {what} Google Sheet isn't shared publicly. Open it > Share > "
                "General access > 'Anyone with the link' (Viewer)."
            )
        resp.raise_for_status()
        if "text/html" in resp.headers.get("content-type", ""):
            raise PermissionError(
                f"This {what} Google Sheet isn't shared publicly (a sign-in page was "
                "returned). Set it to 'Anyone with the link' (Viewer)."
            )
        return resp.content
    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def fetch_tutorial_content(session_id: str, url: str, timeout: float = 45.0) -> list["Chunk"]:
    """Fetch a unit's Tutorial and chunk it as reference content.

    Two link shapes are supported:
      * a Google *Doc* (or .doc/.docx) — the tutorial prose (its tail also holds the
        in-class MCQs, parsed separately); read as plain text and chunked as "Tutorial".
      * a Google *Sheet* / .xlsx cheat-sheet — export as .xlsx and read the
        `TutorialStep` sheet's `content` column.
    Chunks are tagged so scope evidence reads "Tutorial …" (vs "Slide …").
    """
    from .tutorial import parse_tutorial

    url = (url or "").strip()
    if not url.lower().startswith("http"):
        raise ValueError("tutorial link is not a URL — upload the file instead.")

    # Tutorial *doc*: read the whole document as reference prose.
    if looks_like_doc_source(url):
        text = fetch_doc_text(url, timeout)
        return chunk_segments(session_id, [("Tutorial", text)])

    data = fetch_spreadsheet_bytes(url, timeout, what="tutorial")
    return parse_tutorial(session_id, data)


# --------------------------------------------------------------------------- #
# MCQ questions — a Drive-hosted .zip (LMS export) or a Google Doc fallback
# --------------------------------------------------------------------------- #
def looks_like_zip_source(url: str) -> bool:
    """True if the link is a Drive file or a direct .zip (i.e. the LMS MCQ export)."""
    url = (url or "").strip().lower()
    return bool(_GDRIVE_FILE.search(url) or _GDRIVE_UC.search(url) or url.endswith(".zip"))


def looks_like_spreadsheet_source(url: str) -> bool:
    """True if the link is a Google Sheet or a direct .xlsx/.csv (a question-pool sheet)."""
    u = (url or "").strip().lower()
    return bool(_GSHEET.search(u)) or u.split("?")[0].endswith((".xlsx", ".xlsm", ".csv"))


def fetch_questions(session_id: str, url: str, source_set: str,
                    default_topic: str = "", timeout: float = 45.0) -> list["Question"]:
    """Fetch a unit's MCQs, choosing the parser from the link type:
      * a Drive / .zip link            -> the LMS zip parser
      * a Google Sheet / .xlsx / .csv  -> the tabular question-set parser (each sheet
                                          tab is read; inline-option "pool" cells are
                                          split into stem + options + key)
      * anything else (a Google Doc)   -> the Google-Doc text parser
    """
    from .mcq_text import parse_mcq_text
    from .mcq_zip import parse_mcq_zip
    from .questions import parse_questions

    url = (url or "").strip()
    if looks_like_zip_source(url):
        data = _download_drive_file(url, timeout)
        return parse_mcq_zip(data, session_id, source_set, default_topic=default_topic)
    if looks_like_spreadsheet_source(url):
        data = fetch_spreadsheet_bytes(url, timeout, what="MCQ question")
        fname = "questions.xlsx" if _GSHEET.search(url) else (
            url.split("?")[0].rstrip("/").split("/")[-1] or "questions.xlsx")
        questions = parse_questions(data, fname, default_session=session_id)
        for q in questions:
            q.session_id = session_id
            q.source_set = source_set  # type: ignore[assignment]
            q.topic = q.topic or (default_topic or None)
        return questions
    text = fetch_doc_text(url, timeout)
    return parse_mcq_text(text, session_id, source_set, default_topic=default_topic)


def _download_drive_file(url: str, timeout: float = 45.0) -> bytes:
    """Download a Google-Drive-hosted file (or any direct URL) as bytes."""
    m = _GDRIVE_FILE.search(url) or _GDRIVE_UC.search(url)
    if m:
        dl = f"https://drive.google.com/uc?export=download&id={m.group(1)}"
        resp = httpx.get(dl, timeout=timeout, follow_redirects=True)
        if resp.status_code in (401, 403):
            raise PermissionError(
                "This MCQ file isn't shared publicly. Open it in Drive > Share > "
                "General access > 'Anyone with the link' (Viewer)."
            )
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        # small files download directly; if Drive returns its HTML warning page,
        # follow the confirm token so we still get the bytes.
        if "text/html" in ctype:
            token = re.search(r"confirm=([0-9A-Za-z_-]+)", resp.text)
            if token:
                resp = httpx.get(f"{dl}&confirm={token.group(1)}",
                                 timeout=timeout, follow_redirects=True)
                resp.raise_for_status()
            else:
                raise PermissionError(
                    "This MCQ file isn't shared publicly (a sign-in page was returned). "
                    "Set it to 'Anyone with the link' (Viewer)."
                )
        return resp.content
    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.content
