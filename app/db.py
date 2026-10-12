from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.cluster import cluster_key
from app.config import get_settings
from app.scoring import score_article
from app.runtime_settings import ensure_runtime_tables
from app.user_data import ensure_user_tables

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
    interest_score REAL NOT NULL DEFAULT 0,
    cluster_id TEXT,
    brief_ru TEXT
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
    await ensure_user_tables(db)
    await ensure_runtime_tables(db)
    # Index after migration so existing DBs without the column do not break startup.
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_interest ON articles(interest_score DESC)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id)"
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
    if "cluster_id" not in cols:
        await db.execute("ALTER TABLE articles ADD COLUMN cluster_id TEXT")
        await _backfill_cluster_ids(db)
    if "brief_ru" not in cols:
        await db.execute("ALTER TABLE articles ADD COLUMN brief_ru TEXT")


async def _backfill_cluster_ids(db: aiosqlite.Connection) -> None:
    cur = await db.execute("SELECT id, title, summary FROM articles WHERE cluster_id IS NULL OR cluster_id = ''")
    rows = await cur.fetchall()
    for row in rows:
        key = cluster_key(row["title"] or "", row["summary"])
        await db.execute("UPDATE articles SET cluster_id = ? WHERE id = ?", (key, row["id"]))


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
    data["cluster_id"] = data.get("cluster_id") or None
    data["brief_ru"] = data.get("brief_ru") or None
    data["cluster_size"] = int(data.get("cluster_size") or 1)
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
    cid = article.get("cluster_id") or cluster_key(article.get("title") or "", article.get("summary"))

    try:
        cur = await db.execute(
            """
            INSERT INTO articles (
                source_id, source_name, guid, url, title, title_ru,
                summary, summary_ru, content, published_at, fetched_at,
                direction, content_type, technologies, is_legislation,
                lang_original, translated, interest_score, cluster_id, brief_ru
            ) VALUES (
                :source_id, :source_name, :guid, :url, :title, :title_ru,
                :summary, :summary_ru, :content, :published_at, :fetched_at,
                :direction, :content_type, :technologies, :is_legislation,
                :lang_original, :translated, :interest_score, :cluster_id, :brief_ru
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
                "cluster_id": cid,
                "brief_ru": article.get("brief_ru"),
            },
        )
        await db.commit()
        article["id"] = int(cur.lastrowid)
        article["cluster_id"] = cid
        article["interest_score"] = float(interest)
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
    "newest": "COALESCE(a.published_at, a.fetched_at) DESC, a.id DESC",
    "oldest": "COALESCE(a.published_at, a.fetched_at) ASC, a.id ASC",
    "interest": (
        "(a.interest_score + COALESCE(s.feedback, 0) * 15) DESC, "
        "COALESCE(a.published_at, a.fetched_at) DESC, a.id DESC"
    ),
    "source": "a.source_name ASC, COALESCE(a.published_at, a.fetched_at) DESC, a.id DESC",
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
    cve: str | None = None,
    translated_only: bool | None = None,
    bookmarked_only: bool = False,
    hide_read: bool = False,
    dedupe_clusters: bool = True,
    sort: str = "newest",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = ["1=1"]
    params: list[Any] = []

    if hide_legislation:
        clauses.append("a.is_legislation = 0")

    if directions:
        placeholders = ",".join("?" for _ in directions)
        clauses.append(f"a.direction IN ({placeholders})")
        params.extend(directions)

    if content_types:
        placeholders = ",".join("?" for _ in content_types)
        clauses.append(f"a.content_type IN ({placeholders})")
        params.extend(content_types)

    if source_ids:
        placeholders = ",".join("?" for _ in source_ids)
        clauses.append(f"a.source_id IN ({placeholders})")
        params.extend(source_ids)

    if technologies:
        tech_parts = []
        for tech in technologies:
            tech_parts.append("a.technologies LIKE ?")
            params.append(f'%"{tech}"%')
        clauses.append("(" + " OR ".join(tech_parts) + ")")

    if q:
        clauses.append(
            "(a.title LIKE ? OR a.summary LIKE ? OR a.title_ru LIKE ? OR a.summary_ru LIKE ? OR a.brief_ru LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like, like])

    if cve:
        cve_q = cve.strip().upper()
        clauses.append("(UPPER(a.title) LIKE ? OR UPPER(COALESCE(a.summary,'')) LIKE ?)")
        like = f"%{cve_q}%"
        params.extend([like, like])

    if translated_only is True:
        clauses.append("a.translated = 1")
    elif translated_only is False:
        clauses.append("a.translated = 0")

    if bookmarked_only:
        clauses.append("COALESCE(s.bookmarked, 0) = 1")
    if hide_read:
        clauses.append("COALESCE(s.is_read, 0) = 0")

    where = "WHERE " + " AND ".join(clauses)
    order_by = _SORT_SQL.get(sort, _SORT_SQL["newest"])
    if order_by not in _SORT_SQL.values():
        order_by = _SORT_SQL["newest"]

    fetch_limit = (offset + limit) * 4 if dedupe_clusters else limit
    fetch_offset = 0 if dedupe_clusters else offset
    sql = (
        "SELECT a.*, "
        "COALESCE(s.bookmarked, 0) AS bookmarked, "
        "COALESCE(s.is_read, 0) AS is_read, "
        "COALESCE(s.feedback, 0) AS feedback, "
        "(SELECT COUNT(*) FROM articles c WHERE c.cluster_id = a.cluster_id AND c.is_legislation = 0) AS cluster_size "
        "FROM articles a "
        "LEFT JOIN article_state s ON s.article_id = a.id "
        f"{where} "
        f"ORDER BY {order_by} "  # nosec B608
        "LIMIT ? OFFSET ?"
    )
    params.extend([fetch_limit, fetch_offset])
    cur = await db.execute(sql, params)
    rows = await cur.fetchall()
    articles = []
    for r in rows:
        item = row_to_article(r)
        item["bookmarked"] = bool(r["bookmarked"])
        item["is_read"] = bool(r["is_read"])
        item["feedback"] = int(r["feedback"] or 0)
        item["effective_score"] = float(item["interest_score"]) + item["feedback"] * 15
        item["cluster_size"] = int(r["cluster_size"] or 1)
        articles.append(item)

    if dedupe_clusters:
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for a in articles:
            key = a.get("cluster_id") or f"id:{a['id']}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(a)
        articles = deduped[offset : offset + limit]
    return articles


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
        "source_health": await source_health(db),
    }


async def source_health(db: aiosqlite.Connection, *, recent_runs: int = 12) -> list[dict[str, Any]]:
    cur = await db.execute(
        """
        SELECT source_id, source_name,
               COUNT(*) AS articles,
               MAX(COALESCE(published_at, fetched_at)) AS last_seen
        FROM articles
        WHERE is_legislation = 0
        GROUP BY source_id, source_name
        ORDER BY source_name
        """
    )
    by_source = {
        r["source_id"]: {
            "id": r["source_id"],
            "name": r["source_name"],
            "articles": int(r["articles"]),
            "last_seen": r["last_seen"],
            "fail_count": 0,
            "status": "ok",
        }
        for r in await cur.fetchall()
    }

    runs = await list_ingest_runs(db, limit=recent_runs)
    for run in runs:
        for sid in run.get("failed_sources") or []:
            if sid not in by_source:
                by_source[sid] = {
                    "id": sid,
                    "name": sid,
                    "articles": 0,
                    "last_seen": None,
                    "fail_count": 0,
                    "status": "failing",
                }
            by_source[sid]["fail_count"] += 1

    now = datetime.now(timezone.utc)
    out = []
    for item in by_source.values():
        if item["fail_count"] >= 3:
            item["status"] = "failing"
        elif item["last_seen"]:
            try:
                dt = datetime.fromisoformat(str(item["last_seen"]).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_h = (now - dt).total_seconds() / 3600
                if age_h > 48:
                    item["status"] = "silent"
            except ValueError:
                item["status"] = "unknown"
        else:
            item["status"] = "failing" if item["fail_count"] else "unknown"
        out.append(item)
    out.sort(key=lambda x: (0 if x["status"] == "failing" else 1 if x["status"] == "silent" else 2, x["name"]))
    return out


async def list_hot_for_digest(
    db: aiosqlite.Connection,
    *,
    hours: int = 24,
    limit: int = 10,
    min_score: float = 55.0,
) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cur = await db.execute(
        """
        SELECT a.*, COALESCE(s.feedback, 0) AS feedback
        FROM articles a
        LEFT JOIN article_state s ON s.article_id = a.id
        WHERE a.is_legislation = 0
          AND COALESCE(a.published_at, a.fetched_at) >= ?
          AND (a.interest_score + COALESCE(s.feedback, 0) * 15) >= ?
        ORDER BY (a.interest_score + COALESCE(s.feedback, 0) * 15) DESC,
                 COALESCE(a.published_at, a.fetched_at) DESC
        LIMIT ?
        """,
        (cutoff, min_score, limit),
    )
    rows = await cur.fetchall()
    articles = []
    for r in rows:
        item = row_to_article(r)
        item["feedback"] = int(r["feedback"] or 0)
        item["effective_score"] = float(item["interest_score"]) + item["feedback"] * 15
        articles.append(item)
    return articles


async def update_brief(db: aiosqlite.Connection, article_id: int, brief_ru: str) -> None:
    await db.execute("UPDATE articles SET brief_ru = ? WHERE id = ?", (brief_ru, article_id))
    await db.commit()


async def get_articles_by_ids(db: aiosqlite.Connection, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    cur = await db.execute(
        f"SELECT * FROM articles WHERE id IN ({placeholders})",  # nosec B608
        ids,
    )
    by_id = {int(r["id"]): row_to_article(r) for r in await cur.fetchall()}
    return [by_id[i] for i in ids if i in by_id]


async def list_cluster_members(db: aiosqlite.Connection, cluster_id: str) -> list[dict[str, Any]]:
    if not cluster_id:
        return []
    cur = await db.execute(
        """
        SELECT * FROM articles
        WHERE cluster_id = ? AND is_legislation = 0
        ORDER BY interest_score DESC, COALESCE(published_at, fetched_at) DESC
        """,
        (cluster_id,),
    )
    return [row_to_article(r) for r in await cur.fetchall()]


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
