"""Heuristic interest score for practical security articles (0–100)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

CONTENT_TYPE_WEIGHTS = {
    "incident_report": 28,
    "research": 24,
    "writeup": 22,
    "advisory": 18,
    "release": 12,
    "news": 8,
}

# (pattern, points) — summed, capped separately
SIGNAL_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\bcve-\d{4}-\d+\b", re.I), 10),
    (re.compile(r"\b0-?day\b|\bzero-?day\b|\bzeroday\b", re.I), 12),
    (re.compile(r"\brce\b|remote code execution", re.I), 10),
    (re.compile(r"\bransomware\b|шифровальщик", re.I), 8),
    (re.compile(r"\bapt\b|\bnation[- ]state\b", re.I), 8),
    (re.compile(r"\bcritical\b|критическ", re.I), 6),
    (re.compile(r"actively exploited|активн\w* эксплуатац", re.I), 10),
    (re.compile(r"privilege escalation|повышен\w* привилег", re.I), 7),
    (re.compile(r"\bexploit\b|\bэксплойт\b", re.I), 6),
    (re.compile(r"\bauth(entication)? bypass\b|обход аутентификац", re.I), 7),
    (re.compile(r"\bwormable\b|\bsupply[- ]chain\b", re.I), 8),
]

HOT_THRESHOLD = 55
HOT_STRONG_THRESHOLD = 75


def _parse_ts(iso_ts: str | None) -> datetime | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def freshness_points(published_or_fetched: str | None, *, retention_days: int = 7) -> float:
    dt = _parse_ts(published_or_fetched)
    if dt is None:
        return 8.0
    age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    span = max(1.0, retention_days * 24.0)
    return max(0.0, 20.0 * (1.0 - min(age_hours, span) / span))


def signal_points(text: str) -> int:
    total = 0
    for pattern, pts in SIGNAL_PATTERNS:
        if pattern.search(text):
            total += pts
    return min(35, total)


def compute_interest_score(
    *,
    title: str = "",
    summary: str | None = None,
    content_type: str = "news",
    technologies: Iterable[str] | None = None,
    published_at: str | None = None,
    fetched_at: str | None = None,
    translated: bool = False,
    retention_days: int = 7,
) -> float:
    tech = list(technologies or [])
    blob = f"{title}\n{summary or ''}"

    score = float(CONTENT_TYPE_WEIGHTS.get(content_type, 8))
    score += signal_points(blob)
    score += min(12.0, 3.0 * len(tech))
    score += freshness_points(published_at or fetched_at, retention_days=retention_days)
    if translated:
        score += 3.0

    return round(min(100.0, max(0.0, score)), 2)


def score_article(article: dict[str, Any], *, retention_days: int = 7) -> float:
    return compute_interest_score(
        title=article.get("title") or "",
        summary=article.get("summary"),
        content_type=article.get("content_type") or "news",
        technologies=article.get("technologies") or [],
        published_at=article.get("published_at"),
        fetched_at=article.get("fetched_at"),
        translated=bool(article.get("translated")),
        retention_days=retention_days,
    )


def interest_tier(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= HOT_STRONG_THRESHOLD:
        return "strong"
    if score >= HOT_THRESHOLD:
        return "hot"
    return None
