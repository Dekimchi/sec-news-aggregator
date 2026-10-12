from datetime import datetime, timezone

from app.timefmt import (
    format_vladivostok,
    group_articles_by_fetch_day,
    hours_phrase,
    hours_word,
    utc_hour_to_vlad,
    vlad_hour_to_utc,
)


def test_hours_word():
    assert hours_word(1) == "час"
    assert hours_word(2) == "часа"
    assert hours_word(4) == "часа"
    assert hours_word(5) == "часов"
    assert hours_word(11) == "часов"
    assert hours_word(21) == "час"
    assert hours_word(22) == "часа"


def test_hours_phrase():
    assert hours_phrase(3) == "3 часа"


def test_vlad_utc_roundtrip():
    assert utc_hour_to_vlad(6) == 16
    assert vlad_hour_to_utc(16) == 6
    assert vlad_hour_to_utc(0) == 14


def test_format_vladivostok():
    dt = datetime(2026, 10, 12, 6, 5, tzinfo=timezone.utc)
    assert format_vladivostok(dt) == "12.10.2026 16:05 VLAT"
    assert "VLAT" not in format_vladivostok(dt, with_tz=False)


def test_group_articles_by_fetch_day_orders_newest_first():
    groups = group_articles_by_fetch_day(
        [
            {
                "id": 1,
                "fetched_at": "2026-10-10T10:00:00+00:00",
                "published_at": "2026-10-09T12:00:00+00:00",
                "title": "old",
            },
            {
                "id": 2,
                "fetched_at": "2026-10-12T02:00:00+00:00",
                "published_at": "2026-10-11T08:00:00+00:00",
                "title": "new",
            },
            {
                "id": 3,
                "fetched_at": "2026-10-12T08:00:00+00:00",
                "published_at": "2026-10-12T01:00:00+00:00",
                "title": "new2",
            },
        ]
    )
    assert len(groups) == 2
    assert groups[0]["fresh"] is True
    assert "Актуальное" in groups[0]["label"]
    assert [a["id"] for a in groups[0]["articles"]] == [2, 3]
    assert groups[1]["fresh"] is False
    assert "Прошлое" in groups[1]["label"]
    # Nested by publish day (VLAT): id3 publish 12.10, id2 publish 11.10
    assert [s["date_key"] for s in groups[0]["subgroups"]] == ["12.10.2026", "11.10.2026"]
    assert [a["id"] for a in groups[0]["subgroups"][0]["articles"]] == [3]
    assert [a["id"] for a in groups[0]["subgroups"][1]["articles"]] == [2]
    assert "Выход" in groups[0]["subgroups"][0]["label"]
    assert "hint" not in groups[0]
