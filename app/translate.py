from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

# Rough heuristic: Cyrillic share suggests already Russian.
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")

# Pause auto-translation after MyMemory rate limit / quota hits.
_rate_limited_until: float = 0.0
_last_request_at: float = 0.0
_MIN_INTERVAL_SEC = 0.35


class TranslateRateLimited(Exception):
    """Raised when the free translation API asks us to back off."""


def looks_russian(text: str) -> bool:
    if not text:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    cyr = sum(1 for c in letters if _CYRILLIC.match(c))
    return (cyr / len(letters)) > 0.4


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _mark_rate_limited(seconds: int = 900) -> None:
    global _rate_limited_until
    _rate_limited_until = time.time() + seconds
    log.warning("Translation paused for %s seconds due to rate limit/quota", seconds)


async def _throttle() -> None:
    global _last_request_at
    elapsed = time.time() - _last_request_at
    if elapsed < _MIN_INTERVAL_SEC:
        await asyncio.sleep(_MIN_INTERVAL_SEC - elapsed)
    _last_request_at = time.time()


async def translate_text(text: str, *, source: str = "en", target: str = "ru") -> str | None:
    settings = get_settings()
    if not settings.translate_enabled or not text.strip():
        return None
    if time.time() < _rate_limited_until:
        raise TranslateRateLimited("translation temporarily paused")
    if looks_russian(text):
        return text

    provider = settings.translate_provider.lower()
    if provider == "mymemory":
        return await _mymemory(text, source=source, target=target)
    log.warning("Unknown translate provider: %s", provider)
    return None


async def _mymemory(text: str, *, source: str, target: str) -> str | None:
    settings = get_settings()
    # MyMemory recommends short segments; keep under ~450 chars for reliability.
    chunk = _truncate(text, min(settings.translate_max_chars, 450))
    params: dict[str, str] = {
        "q": chunk,
        "langpair": f"{source}|{target}",
    }
    if settings.mymemory_email:
        params["de"] = settings.mymemory_email

    try:
        await _throttle()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://api.mymemory.translated.net/get",
                params=params,
            )
            if resp.status_code == 429:
                _mark_rate_limited()
                raise TranslateRateLimited("MyMemory 429")
            resp.raise_for_status()
            data = resp.json()
    except TranslateRateLimited:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("MyMemory request failed: %s", exc)
        return None

    translated = (
        (data.get("responseData") or {}).get("translatedText")
        if isinstance(data, dict)
        else None
    )
    if not translated:
        return None
    # MyMemory sometimes echoes ERROR messages as translation.
    if translated.upper().startswith("MYMEMORY WARNING"):
        log.warning("MyMemory quota/warning: %s", translated)
        _mark_rate_limited()
        raise TranslateRateLimited(translated)
    return translated.strip()


async def translate_title(title: str) -> str | None:
    """Translate title immediately (priority over summary)."""
    return await translate_text(title)


async def translate_summary(summary: str | None) -> str | None:
    if not summary:
        return None
    settings = get_settings()
    return await translate_text(_truncate(summary, settings.translate_max_chars))


async def translate_article_fields(
    title: str,
    summary: str | None,
) -> tuple[str | None, str | None]:
    title_ru = await translate_title(title)
    summary_ru = await translate_summary(summary)
    return title_ru, summary_ru
