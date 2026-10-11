from __future__ import annotations

from urllib.parse import quote, unquote

from fastapi.responses import RedirectResponse
from starlette.requests import Request

FLASH_COOKIE = "sec_news_flash"


def encode_flash(level: str, message: str) -> str:
    return f"{level}:{quote(message, safe='')}"


def decode_flash(raw: str | None) -> dict[str, str] | None:
    if not raw or ":" not in raw:
        return None
    level, msg = raw.split(":", 1)
    if level not in {"ok", "error", "info"}:
        return None
    try:
        message = unquote(msg)
    except Exception:  # noqa: BLE001
        return None
    if not message:
        return None
    # Hard cap to avoid oversized cookie abuse.
    if len(message) > 500:
        message = message[:500] + "…"
    return {"level": level, "message": message}


def redirect_with_flash(url: str, message: str, level: str = "ok") -> RedirectResponse:
    response = RedirectResponse(url=url, status_code=303)
    response.set_cookie(
        key=FLASH_COOKIE,
        value=encode_flash(level, message),
        max_age=60,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


def attach_flash(request: Request) -> None:
    request.state.flash = decode_flash(request.cookies.get(FLASH_COOKIE))
