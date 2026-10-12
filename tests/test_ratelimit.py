from app.ratelimit import SlidingWindowLimiter


def test_sliding_window_blocks_after_limit():
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert not limiter.allow("a")
