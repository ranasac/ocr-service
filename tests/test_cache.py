"""Tests for Redis cache (image array store)."""

import json

import fakeredis.aioredis
import numpy as np
import pytest

import app.cache.redis_client as cache_module


@pytest.fixture(autouse=True)
def inject_fake_redis(fake_redis):
    """Replace the module-level Redis client with a fake one."""
    original = cache_module._redis
    cache_module._redis = fake_redis
    yield
    cache_module._redis = original


@pytest.mark.asyncio
async def test_store_and_load_array(sample_array):
    await cache_module.store_image_array("test-id", sample_array)
    loaded = await cache_module.load_image_array("test-id")
    assert loaded is not None
    assert np.array_equal(loaded, sample_array)


@pytest.mark.asyncio
async def test_load_missing_returns_none():
    result = await cache_module.load_image_array("non-existent-id")
    assert result is None


@pytest.mark.asyncio
async def test_delete_array(sample_array):
    await cache_module.store_image_array("del-id", sample_array)
    loaded_before = await cache_module.load_image_array("del-id")
    assert loaded_before is not None

    await cache_module.delete_image_array("del-id")
    loaded_after = await cache_module.load_image_array("del-id")
    assert loaded_after is None


@pytest.mark.asyncio
async def test_store_preserves_dtype_and_shape():
    arr = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    await cache_module.store_image_array("dtype-test", arr)
    loaded = await cache_module.load_image_array("dtype-test")
    assert loaded.dtype == arr.dtype
    assert loaded.shape == arr.shape
    assert np.array_equal(loaded, arr)
