from unittest.mock import patch

from app.models.schemas import AppointmentResult
from app.services.idempotency import IdempotencyStore


def _result(event_id="evt-1"):
    return AppointmentResult(
        id=1, status="confirmed", start="2026-09-21T09:00:00", end="2026-09-21T09:45:00",
        outlook_event_id=event_id,
    )


def test_get_returns_none_for_unknown_key():
    store = IdempotencyStore()
    assert store.get("missing") is None


def test_get_returns_none_for_empty_or_missing_key():
    store = IdempotencyStore()
    store.put("real-key", _result())
    assert store.get(None) is None
    assert store.get("") is None


def test_put_then_get_replays_the_same_result():
    store = IdempotencyStore()
    result = _result()
    store.put("key-1", result)
    assert store.get("key-1") is result


def test_entry_expires_after_ttl():
    store = IdempotencyStore(ttl_seconds=0)
    store.put("key-1", _result())
    assert store.get("key-1") is None


def test_entry_with_zero_ttl_expires_even_on_the_same_clock_tick():
    """Regression test: time.monotonic() has coarser resolution on some
    platforms (observed on Windows) than others, so put() and an
    immediately-following get() can read the exact same value. A strict
    '<' comparison treated that as "not yet expired" and returned a stale
    entry; '<=' (the fix) correctly expires it right at the TTL boundary.
    """
    store = IdempotencyStore(ttl_seconds=0)
    with patch("time.monotonic", return_value=1000.0):
        store.put("key-1", _result())
        assert store.get("key-1") is None


def test_different_keys_do_not_collide():
    store = IdempotencyStore()
    store.put("key-1", _result("evt-1"))
    store.put("key-2", _result("evt-2"))
    assert store.get("key-1").outlook_event_id == "evt-1"
    assert store.get("key-2").outlook_event_id == "evt-2"
