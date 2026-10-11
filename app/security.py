from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import Response

CSRF_COOKIE = "sec_news_csrf"
CSRF_FORM_FIELD = "csrf_token"


def safe_next_url(candidate: str | None, *, default: str = "/") -> str:
    """Allow only same-site relative paths (block open redirects)."""
    if not candidate:
        return default
    value = candidate.strip()
    if not value.startswith("/") or value.startswith("//") or value.startswith("/\\"):
        return default
    if "\\" in value or "://" in value:
        return default
    return value


def constant_time_equals(left: str, right: str) -> bool:
    """Length-safe compare for credentials."""
    left_digest = hashlib.sha256(left.encode("utf-8")).digest()
    right_digest = hashlib.sha256(right.encode("utf-8")).digest()
    return hmac.compare_digest(left_digest, right_digest)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str | None = None) -> str:
    value = token or new_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE,
        value=value,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
        path="/",
    )
    return value


def get_or_create_csrf(request: Request) -> str:
    existing = request.cookies.get(CSRF_COOKIE)
    if existing and len(existing) >= 16:
        return existing
    return new_csrf_token()


def validate_csrf(request: Request, form_token: str | None) -> bool:
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if not cookie_token or not form_token:
        return False
    return secrets.compare_digest(cookie_token, form_token)


def is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
