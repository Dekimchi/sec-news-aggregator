import pytest

from app.runtime_settings import (
    validate_digest_hour,
    validate_fetch_interval,
)


def test_validate_fetch_interval_ok():
    assert validate_fetch_interval("4") == 4
    assert validate_fetch_interval(1) == 1
    assert validate_fetch_interval(48) == 48


def test_validate_fetch_interval_rejects():
    with pytest.raises(ValueError):
        validate_fetch_interval(0)
    with pytest.raises(ValueError):
        validate_fetch_interval(49)
    with pytest.raises(ValueError):
        validate_fetch_interval("x")


def test_validate_digest_hour_ok():
    assert validate_digest_hour("0") == 0
    assert validate_digest_hour(23) == 23


def test_validate_digest_hour_rejects():
    with pytest.raises(ValueError):
        validate_digest_hour(-1)
    with pytest.raises(ValueError):
        validate_digest_hour(24)
