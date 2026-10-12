from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import get_settings
from app.scoring import score_article

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    guid TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    title_ru TEXT,
    summary TEXT,
    summary_ru TEXT,
    content TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'both',
    content_type TEXT NOT NULL DEFAULT 'news',
    technologies TEXT NOT NULL DEFAULT '[]',
    is_legislation INTEGER NOT NULL DEFAULT 0,
    lang_original TEXT NOT NULL DEFAULT 'en',
    translated INTEGER NOT NULL DEFAULT 0,
    interest_score REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_direction ON articles(direction);
CREATE INDEX IF NOT EXISTS idx_articles_content_type ON articles(content_type);
CREATE INDEX IF NOT EXISTS idx_articles_legislation ON articles(is_legislation);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    sources INTEGER NOT NULL DEFAULT 0,
    fetched INTEGER NOT NULL DEFAULT 0,
    inserted INTEGER NOT NULL DEFAULT 0,
    translated INTEGER NOT NULL DEFAULT 0,
    skipped_old INTEGER NOT NULL DEFAULT 0,
    skipped_legislation INTEGER NOT NULL DEFAULT 0,
    purged INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    failed_sources TEXT NOT NULL DEFAULT '[]',
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_finished ON ingest_runs(finished_at DESC);
"""


async def connect() -> aiosqlite.Connection:
    settings = get_settings()
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # timeout: wait for locks instead of failing immediately
    db = await aiosqlite.connect(path, timeout=30.0)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA busy_timeout=30000;")
    await db.execute("PRAGMA temp_store=MEMORY;")
    await db.executescript(SCHEMA)
    await _migrate_articles(db)
    # Index after migration so existing DBs without the column do not break startup.
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_interest ON articles(interest_score DESC)"
    )
    await db.commit()
    return db


async def _migrate_articles(db: aiosqlite.Connection) -> None:
    cur = await db.execute("PRAGMA table_info(articles)")
    cols = {row[1] for row in await cur.fetchall()}
    if "interest_score" not in cols:
        await db.execute(
            "ALTER TABLE articles ADD COLUMN interest_score REAL NOT NULL DEFAULT 0"
        )
        await _backfill_interest_scores(db)


async def _backfill_interest_scores(db: aiosqlite.Connection) -> None:
    settings = get_settings()
    cur = await db.execute("SELECT * FROM articles")
    rows = await cur.fetchall()
    for row in rows:
        article = row_to_article(row)
        score = score_article(article, retention_days=settings.retention_days)
        await db.execute(
            "UPDATE articles SET interest_score = ? WHERE id = ?",
            (score, article["id"]),
        )


def row_to_article(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    raw_tech = data.get("technologies") or "[]"
    try:
        data["technologies"] = json.loads(raw_tech)
    except json.JSONDecodeError:
        data["technologies"] = []
    data["is_legislation"] = bool(data.get("is_legislation"))
    data["translated"] = bool(data.get("translated"))
    data["interest_score"] = float(data.get("interest_score") or 0)
    return data


async def upsert_article(db: aiosqlite.Connection, article: dict[str, Any]) -> bool:
    """Insert article if guid is new. Returns True when inserted."""
    tech = article.get("technologies") or []
    if isinstance(tech, list):
        tech_json = json.dumps(tech, ensure_ascii=False)
    else:
        tech_json = str(tech)

    settings = get_settings()
    interest = article.get("interest_score")
    if interest is None:
        interest = score_article(article, retention_days=settings.retention_days)

    try:
        await db.execute(
            """
            INSERT INTO articles (
                source_id, source_name, guid, url, title, title_ru,
                summary, summary_ru, content, published_at, fetched_at,
                direction, content_type, technologies, is_legislation,
                lang_original, translated, interest_score
            ) VALUES (
                :source_id, :source_name, :guid, :url, :title, :title_ru,
                :summary, :summary_ru, :content, :published_at, :fetched_at,
                :direction, :content_type, :technologies, :is_legislation,
                :lang_original, :translated, :interest_score
            )
            """,
            {
                "source_id": article["source_id"],
                "source_name": article["source_name"],
                "guid": article["guid"],
                "url": article["url"],
                "title": article["title"],
                "title_ru": article.get("title_ru"),
                "summary": article.get("summary"),
                "summary_ru": article.get("summary_ru"),
                "content": article.get("content"),
                "published_at": article.get("published_at"),
                "fetched_at": article["fetched_at"],
                "direction": article.get("direction", "both"),
                "content_type": article.get("content_type", "news"),
                "technologies": tech_json,
                "is_legislation": 1 if article.get("is_legislation") else 0,
                "lang_original": article.get("lang_original", "en"),
                "translated": 1 if article.get("translated") else 0,
                "interest_score": float(interest),
            },
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def update_translation(
    db: aiosqlite.Connection,
    article_id: int,
    title_ru: str | None,
    summary_ru: str | None,
) -> None:
    await db.execute(
        """
        UPDATE articles
        SET title_ru = ?, summary_ru = ?, translated = 1
        WHERE id = ?
        """,
        (title_ru, summary_ru, article_id),
    )
    await db.commit()


async def get_article(db: aiosqlite.Connection, article_id: int) -> dict[str, Any] | None:
    cur = await db.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
    row = await cur.fetchone()
    return row_to_article(row) if row else None


_SORT_SQL = {
    "newest": "COALESCE(published_at, fetched_at) DESC, id DESC",
    "oldest": "COALESCE(published_at, fetched_at) ASC, id ASC",
    "interest": "interest_score DESC, COALESCE(published_at, fetched_at) DESC, id DESC",
    "source": "source_name ASC, COALESCE(published_at, fetched_at) DESC, id DESC",
}


async def list_articles(
    db: aiosqlite.Connection,
    *,
    directions: list[str] | None = None,
    content_types: list[str] | None = None,
    technologies: list[str] | None = None,
    source_ids: list[str] | None = None,
    hide_legislation: bool = True,
    q: str | None = None,
    translated_only: bool | None = None,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if hide_legislation:
        clauses.append("is_legislation = 0")

    if directions:
        placeholders = ",".join("?" for _ in directions)
        clauses.append(f"direction IN ({placeholders})")
        params.extend(directions)

    if content_types:
        placeholders = ",".join("?" for _ in content_types)
        clauses.append(f"content_type IN ({placeholders})")
        params.extend(content_types)

    if source_ids:
        placeholders = ",".join("?" for _ in source_ids)
        clauses.append(f"source_id IN ({placeholders})")
        params.extend(source_ids)

    if technologies:
        tech_parts = []
        for tech in technologies:
            tech_parts.append("technologies LIKE ?")
            params.append(f'%"{tech}"%')
        clauses.append("(" + " OR ".join(tech_parts) + ")")

    if q:
        clauses.append("(title LIKE ? OR summary LIKE ? OR title_ru LIKE ? OR summary_ru LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])

    if translated_only is True:
        clauses.append("translated = 1")
    elif translated_only is False:
        clauses.append("translated = 0")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # ORDER BY comes only from the allowlisted _SORT_SQL values (never from user input).
    order_by = _SORT_SQL.get(sort, _SORT_SQL["newest"])
    if order_by not in _SORT_SQL.values():
        order_by = _SORT_SQL["newest"]
    sql = (
        "SELECT * FROM articles "
        f"{where} "
        f"ORDER BY {order_by} "  # nosec B608
        "LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    cur = await db.execute(sql, params)
    rows = await cur.fetchall()
    return [row_to_article(r) for r in rows]


async def count_articles(
    db: aiosqlite.Connection,
    *,
    hide_legislation: bool = True,
) -> int:
    if hide_legislation:
        cur = await db.execute("SELECT COUNT(*) AS c FROM articles WHERE is_legislation = 0")
    else:
        cur = await db.execute("SELECT COUNT(*) AS c FROM articles")
    row = await cur.fetchone()
    return int(row["c"]) if row else 0


async def distinct_sources(db: aiosqlite.Connection) -> list[dict[str, str]]:
    cur = await db.execute(
        """
        SELECT DISTINCT source_id, source_name
        FROM articles
        ORDER BY source_name
        """
    )
    rows = await cur.fetchall()
    return [{"id": r["source_id"], "name": r["source_name"]} for r in rows]


async def list_untranslated_titles(
    db: aiosqlite.Connection,
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    cur = await db.execute(
        """
        SELECT id, guid, title, summary
        FROM articles
        WHERE translated = 0
          AND (title_ru IS NULL OR title_ru = '')
          AND lang_original != 'ru'
          AND is_legislation = 0
        ORDER BY COALESCE(published_at, fetched_at) DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_legislation(db: aiosqlite.Connection) -> int:
    cur = await db.execute("DELETE FROM articles WHERE is_legislation = 1")
    await db.commit()
    return cur.rowcount if cur.rowcount is not None else 0


async def delete_older_than(db: aiosqlite.Connection, days: int) -> int:
    """Delete articles older than N days by published_at (fallback: fetched_at)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = await db.execute(
        """
        DELETE FROM articles
        WHERE COALESCE(published_at, fetched_at) < ?
        """,
        (cutoff,),
    )
    await db.commit()
    return cur.rowcount if cur.rowcount is not None else 0


async def save_ingest_run(
    db: aiosqlite.Connection,
    *,
    started_at: str,
    finished_at: str,
    trigger: str,
    status: str,
    stats: dict[str, Any],
    error_message: str | None = None,
) -> int:
    failed = stats.get("failed_sources") or []
    cur = await db.execute(
        """
        INSERT INTO ingest_runs (
            started_at, finished_at, trigger, status,
            sources, fetched, inserted, translated,
            skipped_old, skipped_legislation, purged, errors,
            failed_sources, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            started_at,
            finished_at,
            trigger,
            status,
            int(stats.get("sources") or 0),
            int(stats.get("fetched") or 0),
            int(stats.get("inserted") or 0),
            int(stats.get("translated") or 0),
            int(stats.get("skipped_old") or 0),
            int(stats.get("skipped_legislation") or 0),
            int(stats.get("purged") or 0),
            int(stats.get("errors") or 0),
            json.dumps(failed, ensure_ascii=False),
            error_message,
        ),
    )
    await db.commit()
    return int(cur.lastrowid)


def row_to_ingest_run(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    raw = data.get("failed_sources") or "[]"
    try:
        data["failed_sources"] = json.loads(raw)
    except json.JSONDecodeError:
        data["failed_sources"] = []
    return data


async def list_ingest_runs(
    db: aiosqlite.Connection,
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    cur = await db.execute(
        """
        SELECT * FROM ingest_runs
        ORDER BY finished_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cur.fetchall()
    return [row_to_ingest_run(r) for r in rows]


async def get_ingest_run(
    db: aiosqlite.Connection,
    run_id: int,
) -> dict[str, Any] | None:
    cur = await db.execute("SELECT * FROM ingest_runs WHERE id = ?", (run_id,))
    row = await cur.fetchone()
    return row_to_ingest_run(row) if row else None


async def dashboard_stats(db: aiosqlite.Connection) -> dict[str, Any]:
    total = await count_articles(db, hide_legislation=True)
    runs = await list_ingest_runs(db, limit=1)
    last = runs[0] if runs else None

    cur = await db.execute(
        """
        SELECT content_type, COUNT(*) AS c
        FROM articles
        WHERE is_legislation = 0
        GROUP BY content_type
        ORDER BY c DESC
        """
    )
    by_type = [{"content_type": r["content_type"], "count": int(r["c"])} for r in await cur.fetchall()]

    cur = await db.execute(
        """
        SELECT COUNT(*) AS c FROM articles
        WHERE is_legislation = 0 AND interest_score >= 55
        """
    )
    row = await cur.fetchone()
    hot_count = int(row["c"]) if row else 0

    return {
        "total_articles": total,
        "hot_count": hot_count,
        "last_run": last,
        "by_type": by_type,
    }


def is_older_than(iso_ts: str | None, days: int) -> bool:
    if not iso_ts:
        return False
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < datetime.now(timezone.utc) - timedelta(days=days)
