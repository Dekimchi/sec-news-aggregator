"""Per-user portal state: bookmarks, read, feedback, filter presets (single-operator)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

SCHEMA_USER = """
CREATE TABLE IF NOT EXISTS article_state (
    article_id INTEGER PRIMARY KEY,
    bookmarked INTEGER NOT NULL DEFAULT 0,
    is_read INTEGER NOT NULL DEFAULT 0,
    feedback INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_article_state_bookmarked ON article_state(bookmarked);
CREATE INDEX IF NOT EXISTS idx_article_state_read ON article_state(is_read);

CREATE TABLE IF NOT EXISTS filter_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    params_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

FEEDBACK_SCORE_STEP = 15.0


async def ensure_user_tables(db: aiosqlite.Connection) -> None:
    await db.executescript(SCHEMA_USER)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_states(
    db: aiosqlite.Connection,
    article_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not article_ids:
        return {}
    placeholders = ",".join("?" for _ in article_ids)
    cur = await db.execute(
        f"SELECT * FROM article_state WHERE article_id IN ({placeholders})",  # nosec B608
        article_ids,
    )
    out: dict[int, dict[str, Any]] = {}
    for row in await cur.fetchall():
        out[int(row["article_id"])] = {
            "bookmarked": bool(row["bookmarked"]),
            "is_read": bool(row["is_read"]),
            "feedback": int(row["feedback"] or 0),
        }
    return out


async def attach_states(
    db: aiosqlite.Connection,
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    states = await get_states(db, [int(a["id"]) for a in articles])
    for a in articles:
        st = states.get(int(a["id"]), {})
        a["bookmarked"] = bool(st.get("bookmarked"))
        a["is_read"] = bool(st.get("is_read"))
        a["feedback"] = int(st.get("feedback") or 0)
        a["effective_score"] = float(a.get("interest_score") or 0) + a["feedback"] * FEEDBACK_SCORE_STEP
    return articles


async def _upsert_state(
    db: aiosqlite.Connection,
    article_id: int,
    *,
    bookmarked: int | None = None,
    is_read: int | None = None,
    feedback: int | None = None,
) -> None:
    cur = await db.execute("SELECT * FROM article_state WHERE article_id = ?", (article_id,))
    row = await cur.fetchone()
    if row is None:
        await db.execute(
            """
            INSERT INTO article_state (article_id, bookmarked, is_read, feedback, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                article_id,
                0 if bookmarked is None else bookmarked,
                0 if is_read is None else is_read,
                0 if feedback is None else feedback,
                _now(),
            ),
        )
    else:
        b = row["bookmarked"] if bookmarked is None else bookmarked
        r = row["is_read"] if is_read is None else is_read
        f = row["feedback"] if feedback is None else feedback
        await db.execute(
            """
            UPDATE article_state
            SET bookmarked = ?, is_read = ?, feedback = ?, updated_at = ?
            WHERE article_id = ?
            """,
            (b, r, f, _now(), article_id),
        )
    await db.commit()


async def toggle_bookmark(db: aiosqlite.Connection, article_id: int) -> bool:
    cur = await db.execute(
        "SELECT bookmarked FROM article_state WHERE article_id = ?", (article_id,)
    )
    row = await cur.fetchone()
    new_val = 0 if (row and row["bookmarked"]) else 1
    await _upsert_state(db, article_id, bookmarked=new_val)
    return bool(new_val)


async def toggle_read(db: aiosqlite.Connection, article_id: int) -> bool:
    cur = await db.execute(
        "SELECT is_read FROM article_state WHERE article_id = ?", (article_id,)
    )
    row = await cur.fetchone()
    new_val = 0 if (row and row["is_read"]) else 1
    await _upsert_state(db, article_id, is_read=new_val)
    return bool(new_val)


async def set_feedback(db: aiosqlite.Connection, article_id: int, value: int) -> int:
    value = max(-1, min(1, int(value)))
    cur = await db.execute(
        "SELECT feedback FROM article_state WHERE article_id = ?", (article_id,)
    )
    row = await cur.fetchone()
    current = int(row["feedback"]) if row else 0
    # Second click on same value clears feedback.
    new_val = 0 if current == value else value
    await _upsert_state(db, article_id, feedback=new_val)
    return new_val


async def list_bookmarked_articles(db: aiosqlite.Connection, *, limit: int = 200) -> list[int]:
    cur = await db.execute(
        """
        SELECT article_id FROM article_state
        WHERE bookmarked = 1
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [int(r["article_id"]) for r in await cur.fetchall()]


async def list_presets(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    cur = await db.execute(
        "SELECT id, name, params_json, created_at FROM filter_presets ORDER BY name"
    )
    rows = await cur.fetchall()
    out = []
    for r in rows:
        try:
            params = json.loads(r["params_json"] or "{}")
        except json.JSONDecodeError:
            params = {}
        out.append(
            {
                "id": int(r["id"]),
                "name": r["name"],
                "params": params,
                "created_at": r["created_at"],
            }
        )
    return out


async def save_preset(db: aiosqlite.Connection, name: str, params: dict[str, Any]) -> int:
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("empty preset name")
    payload = json.dumps(params, ensure_ascii=False)
    cur = await db.execute(
        """
        INSERT INTO filter_presets (name, params_json, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET params_json = excluded.params_json
        """,
        (name, payload, _now()),
    )
    await db.commit()
    return int(cur.lastrowid or 0)


async def delete_preset(db: aiosqlite.Connection, preset_id: int) -> None:
    await db.execute("DELETE FROM filter_presets WHERE id = ?", (preset_id,))
    await db.commit()


async def get_preset(db: aiosqlite.Connection, preset_id: int) -> dict[str, Any] | None:
    cur = await db.execute(
        "SELECT id, name, params_json, created_at FROM filter_presets WHERE id = ?",
        (preset_id,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    try:
        params = json.loads(row["params_json"] or "{}")
    except json.JSONDecodeError:
        params = {}
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "params": params,
        "created_at": row["created_at"],
    }
