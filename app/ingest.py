from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import mktime
from typing import Any

import feedparser
import httpx
import yaml

from app.brief import build_brief_ru
from app.classifier import classify
from app.config import get_settings
from app.db import (
    connect,
    delete_legislation,
    delete_older_than,
    is_older_than,
    list_untranslated_titles,
    save_ingest_run,
    update_brief,
    upsert_article,
)
from app.notify import alert_critical_article
from app.security import is_http_url
from app.translate import (
    TranslateRateLimited,
    looks_russian,
    translate_summary,
    translate_title,
)

log = logging.getLogger(__name__)

USER_AGENT = "sec-news-aggregator/0.1 (+local; practical-security-news)"

MAX_SUMMARY_TRANSLATIONS_PER_RUN = 15
MAX_TITLE_BACKFILL_PER_RUN = 60

_ingest_lock = asyncio.Lock()


class IngestBusy(Exception):
    """Another ingest cycle is already running."""


def load_sources() -> list[dict[str, Any]]:
    settings = get_settings()
    path = Path(settings.sources_path)
    if not path.exists():
        log.error("Sources file missing: %s", path)
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or []
    return [s for s in sources if s.get("enabled", True)]


def _entry_published(entry: Any) -> str | None:
    if getattr(entry, "published_parsed", None):
        try:
            return datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc).isoformat()
        except (OverflowError, ValueError, TypeError):
            pass
    if getattr(entry, "updated_parsed", None):
        try:
            return datetime.fromtimestamp(mktime(entry.updated_parsed), tz=timezone.utc).isoformat()
        except (OverflowError, ValueError, TypeError):
            pass
    for key in ("published", "updated"):
        raw = entry.get(key) if hasattr(entry, "get") else getattr(entry, key, None)
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, IndexError):
                continue
    return None


def clean_text(raw: str | None) -> str:
    """Strip HTML tags and decode entities (&nbsp;, &amp;, …)."""
    if not raw:
        return ""
    text = html.unescape(str(raw))
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _entry_summary(entry: Any) -> str:
    summary = entry.get("summary") or entry.get("description") or ""
    return clean_text(summary)[:2000]


async def fetch_feed(url: str) -> feedparser.FeedParserDict:
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return feedparser.parse(resp.content)


async def ingest_once(
    *,
    allow_wait: bool = True,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Fetch sources, store new items, translate titles.

    allow_wait=False: skip immediately if another ingest is running (scheduler).
    Returns stats dict including run_id when persisted.
    """
    if _ingest_lock.locked() and not allow_wait:
        raise IngestBusy("Сбор новостей уже выполняется")
    if _ingest_lock.locked() and allow_wait:
        log.info("Ingest waiting for running job to finish")
    async with _ingest_lock:
        return await _ingest_body(trigger=trigger)


async def _ingest_body(*, trigger: str) -> dict[str, Any]:
    settings = get_settings()
    sources = load_sources()
    started_at = datetime.now(timezone.utc).isoformat()
    stats: dict[str, Any] = {
        "sources": 0,
        "fetched": 0,
        "inserted": 0,
        "translated": 0,
        "skipped_old": 0,
        "skipped_legislation": 0,
        "purged": 0,
        "errors": 0,
        "failed_sources": [],
        "run_id": None,
    }
    error_message: str | None = None
    status = "ok"

    try:
        return await _ingest_body_work(
            settings=settings,
            sources=sources,
            started_at=started_at,
            stats=stats,
            trigger=trigger,
        )
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error_message = f"{type(exc).__name__}: {exc}"
        finished_at = datetime.now(timezone.utc).isoformat()
        db = await connect()
        try:
            stats["run_id"] = await save_ingest_run(
                db,
                started_at=started_at,
                finished_at=finished_at,
                trigger=trigger,
                status=status,
                stats=stats,
                error_message=error_message,
            )
        finally:
            await db.close()
        raise


async def _ingest_body_work(
    *,
    settings: Any,
    sources: list[dict[str, Any]],
    started_at: str,
    stats: dict[str, Any],
    trigger: str,
) -> dict[str, Any]:
    status = "ok"
    error_message: str | None = None

    # 1) Network I/O without holding SQLite.
    fetched: list[tuple[dict[str, Any], Any]] = []
    for source in sources:
        stats["sources"] += 1
        sid = source.get("id") or "?"
        url = source.get("url") or ""
        if not is_http_url(url):
            log.warning("Feed skipped %s: invalid URL scheme", sid)
            stats["errors"] += 1
            stats["failed_sources"].append(str(sid))
            continue
        try:
            feed = await fetch_feed(url)
            fetched.append((source, feed))
        except Exception as exc:  # noqa: BLE001
            log.warning("Feed failed %s: %s: %r", sid, type(exc).__name__, exc)
            stats["errors"] += 1
            stats["failed_sources"].append(str(sid))

    pending_translate: list[dict[str, Any]] = []

    # 2) Short DB session: purge + insert.
    db = await connect()
    try:
        purged = await delete_older_than(db, settings.retention_days)
        stats["purged"] = purged
        if purged:
            log.info("Purged %s articles older than %s days", purged, settings.retention_days)
        removed_law = await delete_legislation(db)
        if removed_law:
            log.info("Removed %s legislation articles", removed_law)
        await _repair_stored_entities(db)

        for source, feed in fetched:
            sid = source["id"]
            name = source.get("name") or sid
            lang = (source.get("lang") or "en").lower()
            prefer_type = source.get("prefer_type")

            for entry in feed.entries[:40]:
                stats["fetched"] += 1
                link = entry.get("link") or ""
                title = clean_text(entry.get("title")) or "(no title)"
                guid = (entry.get("id") or link or title).strip()
                summary = _entry_summary(entry)
                published_at = _entry_published(entry)
                if is_older_than(published_at, settings.retention_days):
                    stats["skipped_old"] += 1
                    continue

                labels = classify(title, summary, prefer_type=prefer_type)
                if labels["is_legislation"]:
                    stats["skipped_legislation"] += 1
                    continue

                is_ru = lang == "ru" or looks_russian(title)
                article_guid = f"{sid}:{guid}"

                article = {
                    "source_id": sid,
                    "source_name": name,
                    "guid": article_guid,
                    "url": link,
                    "title": title,
                    "title_ru": title if is_ru else None,
                    "summary": summary,
                    "summary_ru": summary if is_ru else None,
                    "content": None,
                    "published_at": published_at,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "direction": labels["direction"],
                    "content_type": labels["content_type"],
                    "technologies": labels["technologies"],
                    "is_legislation": False,
                    "lang_original": "ru" if is_ru else "en",
                    "translated": is_ru,
                }
                inserted = await upsert_article(db, article)
                if not inserted:
                    continue
                stats["inserted"] += 1
                stats.setdefault("new_articles", []).append(dict(article))
                if settings.translate_enabled and not is_ru:
                    pending_translate.append(
                        {
                            "guid": article_guid,
                            "title": title,
                            "summary": summary,
                            "do_summary": True,
                        }
                    )

        if settings.translate_enabled:
            for row in await list_untranslated_titles(db, limit=MAX_TITLE_BACKFILL_PER_RUN):
                pending_translate.append(
                    {
                        "id": row["id"],
                        "guid": row["guid"],
                        "title": row["title"],
                        "summary": None,
                        "do_summary": False,
                    }
                )
    finally:
        await db.close()

    # 3) Translate without DB lock.
    summaries_left = MAX_SUMMARY_TRANSLATIONS_PER_RUN
    translations: list[dict[str, Any]] = []
    for item in pending_translate:
        title_ru = None
        summary_ru = None
        try:
            title_ru = await translate_title(item["title"])
        except TranslateRateLimited:
            log.warning("Stopping auto-translate for this ingest cycle")
            break
        if item.get("do_summary") and summaries_left > 0 and item.get("summary"):
            try:
                summary_ru = await translate_summary(item["summary"])
                if summary_ru:
                    summaries_left -= 1
            except TranslateRateLimited:
                log.warning("Stopping auto-translate after title; summary rate-limited")
                if title_ru:
                    translations.append(
                        {
                            "id": item.get("id"),
                            "guid": item["guid"],
                            "title_ru": title_ru,
                            "summary_ru": None,
                        }
                    )
                break
        if title_ru or summary_ru:
            translations.append(
                {
                    "id": item.get("id"),
                    "guid": item["guid"],
                    "title_ru": title_ru,
                    "summary_ru": summary_ru,
                }
            )

    # 4) Apply translations in a short DB session.
    if translations:
        db = await connect()
        try:
            for tr in translations:
                if tr.get("id") is not None:
                    await db.execute(
                        """
                        UPDATE articles
                        SET title_ru = ?, translated = 1
                        WHERE id = ?
                        """,
                        (tr["title_ru"], tr["id"]),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE articles
                        SET title_ru = COALESCE(?, title_ru),
                            summary_ru = COALESCE(?, summary_ru),
                            translated = CASE
                                WHEN ? IS NOT NULL THEN 1
                                ELSE translated
                            END
                        WHERE guid = ?
                        """,
                        (tr["title_ru"], tr["summary_ru"], tr["title_ru"], tr["guid"]),
                    )
                stats["translated"] += 1
            await db.commit()
        finally:
            await db.close()

    # Briefs + Telegram alerts for newly inserted hot items.
    new_articles = list(stats.pop("new_articles", []) or [])
    briefs_left = settings.brief_max_per_ingest
    for article in new_articles:
        try:
            await alert_critical_article(article)
        except Exception:  # noqa: BLE001
            log.exception("Critical alert failed")
        score = float(article.get("interest_score") or 0)
        if (
            settings.brief_enabled
            and briefs_left > 0
            and score >= settings.brief_min_score
            and article.get("id")
            and not article.get("brief_ru")
        ):
            try:
                brief = await build_brief_ru(
                    article.get("title") or "",
                    article.get("summary_ru") or article.get("summary"),
                    already_ru=bool(article.get("translated")),
                )
                if brief:
                    db = await connect()
                    try:
                        await update_brief(db, int(article["id"]), brief)
                    finally:
                        await db.close()
                    briefs_left -= 1
            except Exception:  # noqa: BLE001
                log.exception("Brief generation failed for article %s", article.get("id"))

    if stats["errors"]:
        status = "partial"
    finished_at = datetime.now(timezone.utc).isoformat()
    db = await connect()
    try:
        stats["run_id"] = await save_ingest_run(
            db,
            started_at=started_at,
            finished_at=finished_at,
            trigger=trigger,
            status=status,
            stats=stats,
            error_message=error_message,
        )
    finally:
        await db.close()

    log.info("Ingest done: %s", stats)
    return stats


async def _repair_stored_entities(db: Any) -> None:
    cur = await db.execute(
        """
        SELECT id, title, title_ru, summary, summary_ru
        FROM articles
        WHERE title LIKE '%&%'
           OR IFNULL(title_ru, '') LIKE '%&%'
           OR IFNULL(summary, '') LIKE '%&%'
           OR IFNULL(summary_ru, '') LIKE '%&%'
        """
    )
    rows = await cur.fetchall()
    fixed = 0
    for row in rows:
        title = clean_text(row["title"])
        title_ru = clean_text(row["title_ru"]) if row["title_ru"] else row["title_ru"]
        summary = clean_text(row["summary"]) if row["summary"] else row["summary"]
        summary_ru = clean_text(row["summary_ru"]) if row["summary_ru"] else row["summary_ru"]
        if (
            title != row["title"]
            or title_ru != row["title_ru"]
            or summary != row["summary"]
            or summary_ru != row["summary_ru"]
        ):
            await db.execute(
                """
                UPDATE articles
                SET title = ?, title_ru = ?, summary = ?, summary_ru = ?
                WHERE id = ?
                """,
                (title or row["title"], title_ru, summary, summary_ru, row["id"]),
            )
            fixed += 1
    if fixed:
        await db.commit()
        log.info("Repaired HTML entities in %s articles", fixed)
