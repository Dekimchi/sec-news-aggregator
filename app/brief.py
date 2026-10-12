"""Short RU briefs for hot articles (MyMemory-backed, quota-friendly)."""

from __future__ import annotations

import logging
import re

from app.config import get_settings
from app.translate import TranslateRateLimited, looks_russian, translate_text

log = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def extractive_brief(text: str, *, max_chars: int = 280) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    parts = _SENTENCE_SPLIT.split(cleaned)
    out: list[str] = []
    total = 0
    for part in parts:
        if not part:
            continue
        if total + len(part) > max_chars and out:
            break
        out.append(part)
        total += len(part) + 1
        if total >= max_chars:
            break
    brief = " ".join(out).strip()
    if len(brief) > max_chars:
        brief = brief[: max_chars - 1].rstrip() + "…"
    return brief


async def build_brief_ru(title: str, summary: str | None, *, already_ru: bool = False) -> str | None:
    settings = get_settings()
    if not settings.brief_enabled:
        return None
    source = (summary or title or "").strip()
    if not source:
        return None
    snippet = extractive_brief(source, max_chars=settings.brief_max_chars)
    if not snippet:
        return None
    if already_ru or looks_russian(snippet):
        return snippet
    if not settings.translate_enabled:
        return snippet
    try:
        translated = await translate_text(snippet)
    except TranslateRateLimited:
        log.info("Brief translation rate-limited; keeping extractive EN snippet")
        return snippet
    return translated or snippet
