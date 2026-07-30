"""Pluggable archive for reviewed content.

Whenever a review finishes, we push the reviewed content to an external store so it
lives outside the (ephemeral) app database. The backend is chosen by env so the org
can swap GitHub -> S3 later without touching call sites:

    ARCHIVE_BACKEND = github | s3 | none      (default: none)

GitHub (now):  commits files via the Contents API — no git binary needed.
    GITHUB_TOKEN   = a fine-grained PAT with Contents:read/write on the repo
    GITHUB_REPO    = owner/name
    GITHUB_BRANCH  = main (default)
    ARCHIVE_DIR    = reviews (default, the folder inside the repo)

S3 (later):    a stub is wired but not implemented (add boto3 when the org moves).

All credentials come from ENV — never commit them to git.
"""
from __future__ import annotations

import base64
import json
from typing import Protocol

import httpx

from .config import get_settings


class StorageBackend(Protocol):
    def enabled(self) -> bool: ...
    def save(self, path: str, data: bytes, message: str) -> str | None: ...


class NoopBackend:
    """Default when nothing is configured — archiving is simply skipped."""

    def enabled(self) -> bool:
        return False

    def save(self, path: str, data: bytes, message: str) -> str | None:
        return None


class GitHubBackend:
    """Commit a file to a GitHub repo via the Contents API (create or update)."""

    def __init__(self, token: str, repo: str, branch: str = "main", timeout: float = 30.0):
        self.token = token
        self.repo = repo
        self.branch = branch or "main"
        self.timeout = timeout

    def enabled(self) -> bool:
        return bool(self.token and self.repo)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _url(self, path: str) -> str:
        return f"https://api.github.com/repos/{self.repo}/contents/{path.lstrip('/')}"

    def save(self, path: str, data: bytes, message: str) -> str | None:
        url = self._url(path)
        headers = self._headers()
        # updating an existing path needs its current blob sha
        sha = None
        r = httpx.get(url, headers=headers, params={"ref": self.branch}, timeout=self.timeout)
        if r.status_code == 200:
            sha = r.json().get("sha")
        body = {
            "message": message,
            "content": base64.b64encode(data).decode("ascii"),
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha
        resp = httpx.put(url, headers=headers, json=body, timeout=self.timeout)
        resp.raise_for_status()
        return (resp.json().get("content") or {}).get("html_url")


class S3Backend:
    """Placeholder for the org's future move to AWS S3 (add boto3 to implement)."""

    def __init__(self, bucket: str, prefix: str = ""):
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def enabled(self) -> bool:
        return False  # not implemented yet

    def save(self, path: str, data: bytes, message: str) -> str | None:
        raise NotImplementedError(
            "S3 archive backend is not implemented yet — set ARCHIVE_BACKEND=github for now.")


def get_backend() -> StorageBackend:
    s = get_settings()
    kind = (s.archive_backend or "none").lower()
    if kind == "github":
        return GitHubBackend(s.github_token or "", s.github_repo or "", s.github_branch or "main")
    if kind == "s3":
        return S3Backend(s.s3_bucket or "", s.archive_dir or "reviews")
    return NoopBackend()


# --------------------------------------------------------------------------- #
# High-level: archive one review
# --------------------------------------------------------------------------- #
def _safe(part: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(part))[:80] or "x"


def archive_review(*, session_id: str, run_id: str, source_set: str, title: str,
                   reviewer: str, record: dict, xlsx: bytes | None) -> list[str]:
    """Write the reviewed content to the configured store. Best-effort — returns the
    list of URLs written (empty if archiving is disabled). Never raises to the caller
    who wraps it; but does raise inside if a configured backend fails (so callers can log).
    """
    backend = get_backend()
    if not backend.enabled():
        return []
    base = f"{(get_settings().archive_dir or 'reviews').strip('/')}/{_safe(session_id)}/{_safe(run_id)}"
    urls: list[str] = []
    msg = f"Review {run_id} — {title or session_id} ({source_set}) by {reviewer}"

    j = backend.save(f"{base}/review.json",
                     json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8"), msg)
    if j:
        urls.append(j)
    if xlsx:
        x = backend.save(f"{base}/reviewed.xlsx", xlsx, msg)
        if x:
            urls.append(x)
    return urls
