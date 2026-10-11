from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Annotated
from urllib.parse import quote

from fastapi import Form, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.flash import redirect_with_flash
from app.security import (
    CSRF_COOKIE,
    constant_time_equals,
    safe_next_url,
    set_csrf_cookie,
    validate_csrf,
)

COOKIE_NAME = "sec_news_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/") -> None:
        self.next_url = next_url


def _sign(payload: str) -> str:
    secret = get_settings().app_secret.encode("utf-8")
    digest = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{digest}"


def _verify(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, signature = token.rsplit(".", 1)
    secret = get_settings().app_secret.encode("utf-8")
    expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected):
        return None
    try:
        username, expires_s = payload.split(":", 1)
        if int(expires_s) < int(time.time()):
            return None
    except ValueError:
        return None
    return username


def create_session_token(username: str) -> str:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    return _sign(f"{username}:{expires}")


def check_credentials(username: str, password: str) -> bool:
    settings = get_settings()
    return constant_time_equals(username, settings.basic_auth_user) and constant_time_equals(
        password,
        settings.basic_auth_password,
    )


def require_user(request: Request) -> str:
    username = _verify(request.cookies.get(COOKIE_NAME))
    if username:
        return username
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    raise LoginRequired(next_url=safe_next_url(path))


async def login_form_handler(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
    csrf_token: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    if not validate_csrf(request, csrf_token):
        return redirect_with_flash("/login", "Сессия устарела, войдите снова", "error")
    if not check_credentials(username, password):
        return redirect_with_flash("/login", "Неверный логин или пароль", "error")
    target = safe_next_url(next)
    response = redirect_with_flash(target, "Вход выполнен", "ok")
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_token(username),
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )
    set_csrf_cookie(response)
    return response


def logout_response() -> RedirectResponse:
    response = redirect_with_flash("/login", "Вы вышли из системы", "info")
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


def login_redirect(exc: LoginRequired) -> RedirectResponse:
    next_url = quote(safe_next_url(exc.next_url), safe="/?=&")
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)
