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
