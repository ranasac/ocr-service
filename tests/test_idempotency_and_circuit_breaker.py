"""Tests for the idempotency guard and circuit breaker."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.cache.redis_client as cache_module


# ── Idempotency tests ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def inject_fake_redis(fake_redis):
    original = cache_module._redis
    cache_module._redis = fake_redis
    yield
    cache_module._redis = original


@pytest.mark.asyncio
async def test_first_lock_acquisition_succeeds():
    acquired = await cache_module.acquire_processing_lock("img-lock-1")
    assert acquired is True


@pytest.mark.asyncio
async def test_second_lock_acquisition_fails_for_same_id():
    """Second SET NX on the same key must return False (duplicate guard)."""
    await cache_module.acquire_processing_lock("img-lock-2")
    second = await cache_module.acquire_processing_lock("img-lock-2")
    assert second is False


@pytest.mark.asyncio
async def test_release_allows_reacquisition():
    await cache_module.acquire_processing_lock("img-lock-3")
    await cache_module.release_processing_lock("img-lock-3")
    reacquired = await cache_module.acquire_processing_lock("img-lock-3")
    assert reacquired is True


@pytest.mark.asyncio
async def test_different_image_ids_have_independent_locks():
    a = await cache_module.acquire_processing_lock("img-a")
    b = await cache_module.acquire_processing_lock("img-b")
    assert a is True
    assert b is True


# ── Circuit breaker tests ─────────────────────────────────────────────────────

def test_circuit_breaker_opens_after_threshold():
    """Breaker must open after _FAILURE_THRESHOLD consecutive failures."""
    from app.api.inference import _breaker, _FAILURE_THRESHOLD, CircuitOpenError

    # Reset state
    _breaker._failures = 0
    _breaker._opened_at = None

    for _ in range(_FAILURE_THRESHOLD):
        assert not _breaker.is_open
        _breaker.record_failure()

    assert _breaker.is_open


def test_circuit_breaker_resets_on_success():
    from app.api.inference import _breaker

    _breaker._failures = 3
    _breaker._opened_at = None
    _breaker.record_success()

    assert _breaker._failures == 0
    assert not _breaker.is_open


def test_circuit_breaker_half_open_after_timeout():
    """After reset_timeout the breaker should allow a probe (is_open == False)."""
    import time
    from app.api.inference import _breaker, _RESET_TIMEOUT_SECONDS

    _breaker._failures = 99
    _breaker._opened_at = time.monotonic() - _RESET_TIMEOUT_SECONDS - 1

    # After timeout, is_open returns False (HALF-OPEN)
    assert not _breaker.is_open


@pytest.mark.asyncio
async def test_run_ocr_inference_raises_circuit_open_when_open():
    """run_ocr_inference should raise CircuitOpenError when breaker is open."""
    import time
    from app.api.inference import CircuitOpenError, _breaker, _FAILURE_THRESHOLD, run_ocr_inference
    from app.config import MLServiceSettings

    # Force breaker open
    _breaker._failures = _FAILURE_THRESHOLD
    _breaker._opened_at = time.monotonic()

    settings = MLServiceSettings(url="http://fake-ml:8001", timeout=5)

    with pytest.raises(CircuitOpenError):
        await run_ocr_inference("some-image-id", settings)

    # Clean up
    _breaker._failures = 0
    _breaker._opened_at = None
