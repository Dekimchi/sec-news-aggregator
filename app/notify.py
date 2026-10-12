"""Telegram notifications: critical alerts + daily digest."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.timefmt import format_vladivostok

log = logging.getLogger(__name__)


async def telegram_send(text: str, *, parse_mode: str | None = "HTML") -> bool:
    settings = get_settings()
    token = (settings.telegram_bot_token or "").strip()
    chat_id = (settings.telegram_chat_id or "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                log.warning("Telegram send failed: %s %s", resp.status_code, resp.text[:200])
                return False
            return True
    except Exception:  # noqa: BLE001
        log.exception("Telegram send error")
        return False


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


async def alert_critical_article(article: dict[str, Any]) -> None:
    settings = get_settings()
    if not settings.telegram_alerts_enabled:
        return
    score = float(article.get("interest_score") or 0)
    if score < settings.telegram_alert_min_score:
        return
    title = _esc(article.get("title_ru") or article.get("title") or "article")
    src = _esc(article.get("source_name") or article.get("source_id") or "?")
    url = str(article.get("url") or "").strip()
    lines = [
        f"🔥 <b>Hot</b> · <code>{score:.0f}</code>",
        f"<b>{title}</b>",
        f"Источник: {src}",
    ]
    if url:
        lines.append(f'<a href="{html.escape(url, quote=True)}">открыть статью →</a>')
    await telegram_send("\n".join(lines))


def format_daily_digest(articles: list[dict[str, Any]]) -> str:
    now = format_vladivostok(datetime.now(timezone.utc), with_tz=True)
    if not articles:
        return (
            "🗞 <b>sec-news</b> · дневной дайджест\n"
            f"<i>{_esc(now)}</i>\n\n"
            "За сутки интересных статей нет."
        )

    lines = [
        "🗞 <b>sec-news</b> · дневной дайджест",
        f"<i>{_esc(now)}</i>",
        f"Топ-{len(articles)} за сутки",
        "",
    ]
    for i, a in enumerate(articles, 1):
        title = _esc(a.get("title_ru") or a.get("title") or "?")
        score = float(a.get("interest_score") or 0)
        src = _esc(a.get("source_name") or a.get("source_id") or "")
        url = str(a.get("url") or "").strip()
        brief = (a.get("brief_ru") or "").strip()
        if brief and len(brief) > 160:
            brief = brief[:157].rstrip() + "…"
        lines.append(f"<b>{i}.</b> {title}")
        meta = f"⚡ <code>{score:.0f}</code>"
        if src:
            meta += f" · {src}"
        lines.append(meta)
        if brief:
            lines.append(f"<i>{_esc(brief)}</i>")
        if url:
            safe = html.escape(url, quote=True)
            lines.append(f'<a href="{safe}">читать →</a>')
        lines.append("")
    lines.append("—")
    lines.append("<i>sec-news aggregator</i>")
    return "\n".join(lines).strip()


async def send_daily_digest(articles: list[dict[str, Any]]) -> bool:
    # Enable/disable is enforced by the scheduler / UI; here we only send.
    return await telegram_send(format_daily_digest(articles))
