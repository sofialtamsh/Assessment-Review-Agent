"""Lightweight shared-password login for reviewer identity + attribution.

This is NOT hard security — it's a name badge. Everyone signs in with their own
name and a single shared password (`ARP_SHARED_PASSWORD`, default 'admin@123'). On
success we hand back a token = HMAC(name) so the frontend can prove the password was
entered without us storing sessions. Requests carry `X-Reviewer-Name` (+ optional
`X-Reviewer-Token`); we use the name to attribute reviews and drive the activity feed.
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Request

from .config import get_settings


def make_token(name: str) -> str:
    secret = get_settings().auth_secret.encode()
    return hmac.new(secret, (name or "").strip().lower().encode(), hashlib.sha256).hexdigest()


def verify_token(name: str, token: str) -> bool:
    if not name or not token:
        return False
    return hmac.compare_digest(make_token(name), token)


def login(name: str, password: str) -> dict:
    """Validate the shared password and mint a token for this reviewer name."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Enter your name.")
    if (password or "") != get_settings().shared_password:
        raise ValueError("Incorrect password.")
    return {"name": name, "token": make_token(name)}


def reviewer_from_request(request: Request) -> str:
    """Best-effort reviewer name from headers (soft auth — never raises).

    Returns the verified name, or the raw name if the token is missing (the UI gates
    login), or 'unknown' when no name header is present at all.
    """
    name = (request.headers.get("x-reviewer-name") or "").strip()
    if not name:
        return "unknown"
    token = (request.headers.get("x-reviewer-token") or "").strip()
    if token and not verify_token(name, token):
        return "unknown"
    return name
