"""Tests for the FastAPI upload endpoint."""

import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

import app.cache.redis_client as cache_module
import app.database.mongodb as db_module
from app.models.schemas import ImageStatus, OCRResult, UploadResponse


def _make_mock_ocr_result(image_id: str) -> OCRResult:
    return OCRResult(
        image_id=image_id,
        text="Hello World",
        confidence=95.0,
        processing_time_ms=50.0,
        words=[],
    )


@pytest.fixture
def app_with_mocks(fake_redis, tmp_path):
    """Build a test app with all external dependencies mocked."""
    import os
    os.environ["APP_ENV"] = "test"
    os.environ["STORAGE_LOCAL_PATH"] = str(tmp_path)

    # Patch heavy dependencies before importing main
    with (
        patch("app.database.mongodb.init_db", new=AsyncMock()),
        patch("app.database.mongodb.close_db", new=AsyncMock()),
        patch("app.cache.redis_client.init_redis", new=AsyncMock()),
        patch("app.cache.redis_client.close_redis", new=AsyncMock()),
        patch("app.kafka.producer.init_producer"),
        patch("app.kafka.producer.close_producer"),
        patch("app.kafka.producer.publish_image_event"),
        patch("app.kafka.consumer.start_consumer_thread"),
        patch("app.observability.tracing.setup_tracing"),
    ):
        from app.config import get_settings
        get_settings.cache_clear()

        from app.main import app
        yield app

    get_settings.cache_clear()


@pytest.fixture
def mock_db():
    """Mock MongoDB operations."""
    with (
        patch("app.api.routes.insert_metadata", new=AsyncMock()),
        patch("app.api.routes.update_status", new=AsyncMock()),
        patch("app.api.routes.get_metadata", new=AsyncMock()),
    ):
        yield


@pytest.fixture
def mock_redis_with_array(fake_redis, sample_array):
    """Pre-populate fake redis with a transformed array and inject it."""
    original = cache_module._redis
    cache_module._redis = fake_redis

    import asyncio

    async def _store():
        await cache_module.store_image_array("__placeholder__", sample_array)

    asyncio.get_event_loop().run_until_complete(_store())
    yield fake_redis
    cache_module._redis = original


@pytest.mark.asyncio
async def test_health_endpoint(app_with_mocks):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_mocks), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_upload_success(app_with_mocks, mock_db, sample_image_bytes, fake_redis):
    """Full upload flow with mocked external services."""
    cache_module._redis = fake_redis

    # Mock the inference call
    captured_image_id = {}

    async def mock_insert(metadata):
        captured_image_id["id"] = metadata.image_id
        # Pre-store the array so the route doesn't timeout waiting
        import app.image.transforms as t
        arr = t.preprocess_for_ocr(sample_image_bytes)
        await cache_module.store_image_array(metadata.image_id, arr)

    with (
        patch("app.api.routes.insert_metadata", new=mock_insert),
        patch("app.api.routes.update_status", new=AsyncMock()),
        patch("app.api.routes.run_ocr_inference", new=AsyncMock(
            return_value=_make_mock_ocr_result("test")
        )),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_mocks), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/upload",
                files={"file": ("test.png", sample_image_bytes, "image/png")},
            )

    assert response.status_code == 200
    data = response.json()
    assert "image_id" in data
    assert data["status"] == "completed"
    assert data["ocr_result"]["text"] == "Hello World"


@pytest.mark.asyncio
async def test_upload_invalid_content_type(app_with_mocks):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_mocks), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/upload",
            files={"file": ("test.pdf", b"fake pdf content", "application/pdf")},
        )
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_upload_too_large(app_with_mocks):
    big_data = b"x" * (21 * 1024 * 1024)  # 21 MB
    async with AsyncClient(
        transport=ASGITransport(app=app_with_mocks), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/upload",
            files={"file": ("big.png", big_data, "image/png")},
        )
    assert response.status_code == 413
