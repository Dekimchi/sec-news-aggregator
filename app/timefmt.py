"""Time formatting (Asia/Vladivostok) and Russian plural helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_VLADIVOSTOK = ZoneInfo("Asia/Vladivostok")
UTC = timezone.utc
VLAD_UTC_OFFSET_HOURS = 10  # Asia/Vladivostok has no DST


def hours_word(n: int | float | str) -> str:
    """Russian plural form for 'час' given a count."""
    try:
        value = abs(int(n))
    except (TypeError, ValueError):
        return "часов"
    n10 = value % 10
    n100 = value % 100
    if n10 == 1 and n100 != 11:
        return "час"
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return "часа"
    return "часов"


def hours_phrase(n: int | float | str) -> str:
    try:
        value = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{value} {hours_word(value)}"


def utc_hour_to_vlad(hour_utc: int) -> int:
    return (int(hour_utc) + VLAD_UTC_OFFSET_HOURS) % 24


def vlad_hour_to_utc(hour_local: int) -> int:
    return (int(hour_local) - VLAD_UTC_OFFSET_HOURS) % 24


def _parse_dt(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def format_vladivostok(
    value: datetime | str | None,
    *,
    with_tz: bool = True,
    date_only: bool = False,
) -> str:
    dt = _parse_dt(value)
    if dt is None:
        return "—"
    local = dt.astimezone(TZ_VLADIVOSTOK)
    if date_only:
        return local.strftime("%d.%m.%Y")
    stamp = local.strftime("%d.%m.%Y %H:%M")
    return f"{stamp} VLAT" if with_tz else stamp


def group_articles_by_fetch_day(articles: list[dict]) -> list[dict]:
    """Group feed items by Vladivostok calendar day of fetched_at (newest first)."""
    buckets: dict[str, list[dict]] = {}
    order_keys: list[tuple[datetime, str]] = []
    for article in articles:
        raw = article.get("fetched_at") or article.get("published_at")
        dt = _parse_dt(raw)
        if dt is None:
            day_key = "без даты"
            sort_dt = datetime.min.replace(tzinfo=UTC)
        else:
            local = dt.astimezone(TZ_VLADIVOSTOK)
            day_key = local.strftime("%d.%m.%Y")
            sort_dt = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if day_key not in buckets:
            buckets[day_key] = []
            order_keys.append((sort_dt, day_key))
        buckets[day_key].append(article)

    order_keys.sort(key=lambda pair: pair[0], reverse=True)
    groups: list[dict] = []
    for index, (_, day_key) in enumerate(order_keys):
        fresh = index == 0
        groups.append(
            {
                "date_key": day_key,
                "fresh": fresh,
                "label": (
                    f"Актуальное обновление · {day_key}"
                    if fresh
                    else f"Прошлое обновление · {day_key}"
                ),
                "hint": (
                    "Свежий сбор — карточки ярче"
                    if fresh
                    else "Более ранний сбор — приглушено"
                ),
                "articles": buckets[day_key],
            }
        )
    return groups
