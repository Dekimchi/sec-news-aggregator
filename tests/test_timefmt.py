from datetime import datetime, timezone

from app.timefmt import (
    format_vladivostok,
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
