"""Telegram notifications: critical alerts + daily digest."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


async def telegram_send(text: str) -> bool:
    settings = get_settings()
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_chat_id or "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text[:3900],
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code >= 400:
                log.warning("Telegram send failed: %s %s", resp.status_code, resp.text[:200])
                return False
            return True
    except Exception:  # noqa: BLE001
        log.exception("Telegram send error")
        return False


async def alert_critical_article(article: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.telegram_alerts_enabled:
        return
    score = float(article.get("interest_score") or 0)
    if score < settings.telegram_alert_min_score:
        return
    title = article.get("title_ru") or article.get("title") or "article"
    src = article.get("source_name") or article.get("source_id") or "?"
    url = article.get("url") or ""
    text = (
        f"🔥 Hot ({score:.0f}): {title}\n"
        f"Источник: {src}\n"
        f"{url}"
    )
    await telegram_send(text)


async def send_daily_digest(articles: list[dict[str, Any]]) -> bool:
    settings = get_settings()
    if not settings.telegram_digest_enabled:
        return False
    if not articles:
        return await telegram_send("sec-news digest: за сутки интересных статей нет.")
    lines = ["sec-news · дневной дайджест", ""]
    for i, a in enumerate(articles, 1):
        title = a.get("title_ru") or a.get("title") or "?"
        score = float(a.get("interest_score") or 0)
        lines.append(f"{i}. ({score:.0f}) {title}")
        if a.get("url"):
            lines.append(a["url"])
        lines.append("")
    return await telegram_send("\n".join(lines).strip())
