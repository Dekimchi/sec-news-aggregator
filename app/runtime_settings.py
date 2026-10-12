"""Persistent runtime overrides (schedule) stored in SQLite.

Env (.env) remains the default; UI values win until cleared.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from app.config import get_settings

SCHEMA_KV = """
CREATE TABLE IF NOT EXISTS app_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

KEY_FETCH_INTERVAL = "fetch_interval_hours"
KEY_DIGEST_ENABLED = "telegram_digest_enabled"
KEY_DIGEST_HOUR = "telegram_digest_hour_utc"

FETCH_INTERVAL_MIN = 1
FETCH_INTERVAL_MAX = 48


async def ensure_runtime_tables(db: aiosqlite.Connection) -> None:
    await db.executescript(SCHEMA_KV)


async def _get(db: aiosqlite.Connection, key: str) -> str | None:
    cur = await db.execute("SELECT value FROM app_kv WHERE key = ?", (key,))
    row = await cur.fetchone()
    return None if row is None else str(row["value"])


async def _set(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        """
        INSERT INTO app_kv (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def validate_fetch_interval(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Интервал сбора должен быть числом часов") from exc
    if value < FETCH_INTERVAL_MIN or value > FETCH_INTERVAL_MAX:
        raise ValueError(
            f"Интервал сбора: от {FETCH_INTERVAL_MIN} до {FETCH_INTERVAL_MAX} часов"
        )
    return value


def validate_digest_hour(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Час дайджеста должен быть числом 0–23 (UTC)") from exc
    if value < 0 or value > 23:
        raise ValueError("Час дайджеста: от 0 до 23 (UTC)")
    return value


async def get_schedule_settings(db: aiosqlite.Connection) -> dict[str, Any]:
    """Effective schedule: DB override → .env defaults."""
    base = get_settings()
    fetch_raw = await _get(db, KEY_FETCH_INTERVAL)
    digest_en_raw = await _get(db, KEY_DIGEST_ENABLED)
    digest_hour_raw = await _get(db, KEY_DIGEST_HOUR)

    try:
        fetch = (
            validate_fetch_interval(fetch_raw)
            if fetch_raw is not None
            else int(base.fetch_interval_hours)
        )
    except ValueError:
        fetch = int(base.fetch_interval_hours)

    digest_enabled = (
        digest_en_raw.strip().lower() in {"1", "true", "yes", "on"}
        if digest_en_raw is not None
        else bool(base.telegram_digest_enabled)
    )
    try:
        digest_hour = (
            validate_digest_hour(digest_hour_raw)
            if digest_hour_raw is not None
            else int(base.telegram_digest_hour_utc)
        )
    except ValueError:
        digest_hour = int(base.telegram_digest_hour_utc)
    token_ok = bool(base.telegram_bot_token and base.telegram_chat_id)
    return {
        "fetch_interval_hours": fetch,
        "digest_enabled": digest_enabled,
        "digest_hour_utc": digest_hour,
        "digest_configured": token_ok,
        "digest_active": digest_enabled and token_ok,
        "from_db": {
            "fetch_interval_hours": fetch_raw is not None,
            "digest_enabled": digest_en_raw is not None,
            "digest_hour_utc": digest_hour_raw is not None,
        },
    }


async def save_schedule_settings(
    db: aiosqlite.Connection,
    *,
    fetch_interval_hours: int,
    digest_enabled: bool,
    digest_hour_utc: int,
) -> dict[str, Any]:
    fetch = validate_fetch_interval(fetch_interval_hours)
    hour = validate_digest_hour(digest_hour_utc)
    await _set(db, KEY_FETCH_INTERVAL, str(fetch))
    await _set(db, KEY_DIGEST_ENABLED, "1" if digest_enabled else "0")
    await _set(db, KEY_DIGEST_HOUR, str(hour))
    await db.commit()
    return await get_schedule_settings(db)
