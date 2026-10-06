from unittest.mock import patch

from app.services.rate_limit import RateLimiter


def test_allows_requests_up_to_the_limit():
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is True


def test_rejects_once_the_limit_is_exceeded():
    limiter = RateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-a") is False


def test_keys_are_independent():
    limiter = RateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("client-a") is True
    assert limiter.allow("client-b") is True  # a different client, unaffected
    assert limiter.allow("client-a") is False


def test_old_hits_fall_out_of_the_window():
    limiter = RateLimiter(limit=1, window_seconds=60)
    with patch("time.monotonic", return_value=1000.0):
        assert limiter.allow("client-a") is True
        assert limiter.allow("client-a") is False
    with patch("time.monotonic", return_value=1061.0):  # 61s later, window has passed
        assert limiter.allow("client-a") is True
