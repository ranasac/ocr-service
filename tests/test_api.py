"""Tests for the FastAPI upload endpoint."""

import io
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

import app.cache.redis_client as cache_module
import app.database.mongodb as db_module
from app.models.schemas import ImageMetadata, ImageStatus, OCRResult, UploadResponse


def _make_mock_metadata(image_id: str) -> ImageMetadata:
    return ImageMetadata(
        image_id=image_id,
        filename="test.png",
        content_type="image/png",
        size_bytes=100,
        storage_path=f"/tmp/{image_id}.png",
        status=ImageStatus.COMPLETED,
        ocr_result=OCRResult(
            image_id=image_id,
            text="Hello World",
            confidence=95.0,
            processing_time_ms=50.0,
            words=[],
        ),
    )


@pytest.fixture
def app_with_mocks(fake_redis, tmp_path):
    """Build a test app with all external dependencies mocked."""
    import os
    os.environ["APP_ENV"] = "test"
    os.environ["STORAGE_LOCAL_PATH"] = str(tmp_path)

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


@pytest.mark.asyncio
async def test_health_endpoint(app_with_mocks):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_mocks), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_upload_returns_202_accepted(app_with_mocks, sample_image_bytes, fake_redis):
    """Upload should immediately return 202 with image_id and status_url."""
    cache_module._redis = fake_redis

    with (
        patch("app.api.routes.insert_metadata", new=AsyncMock()),
        patch("app.api.routes.update_status", new=AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_mocks), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/upload",
                files={"file": ("test.png", sample_image_bytes, "image/png")},
            )

    assert response.status_code == 202
    data = response.json()
    assert "image_id" in data
    assert data["status"] == "accepted"
    assert "status_url" in data
    assert data["status_url"].startswith("/api/v1/images/")


@pytest.mark.asyncio
async def test_upload_status_url_contains_image_id(app_with_mocks, sample_image_bytes, fake_redis):
    """The status_url must embed the same image_id as the response."""
    cache_module._redis = fake_redis

    with (
        patch("app.api.routes.insert_metadata", new=AsyncMock()),
        patch("app.api.routes.update_status", new=AsyncMock()),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_mocks), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/upload",
                files={"file": ("test.png", sample_image_bytes, "image/png")},
            )

    data = response.json()
    assert data["image_id"] in data["status_url"]


@pytest.mark.asyncio
async def test_get_image_status_completed(app_with_mocks):
    """GET /images/{id} returns full metadata including OCR result when done."""
    image_id = "test-completed-id"
    mock_meta = _make_mock_metadata(image_id)

    with patch(
        "app.api.routes.get_metadata",
        new=AsyncMock(return_value=mock_meta),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_mocks), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/v1/images/{image_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["image_id"] == image_id
    assert data["status"] == "completed"
    assert data["ocr_result"]["text"] == "Hello World"


@pytest.mark.asyncio
async def test_get_image_not_found(app_with_mocks):
    with patch("app.api.routes.get_metadata", new=AsyncMock(return_value=None)):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_mocks), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/images/nonexistent")
    assert response.status_code == 404


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


@pytest.mark.asyncio
async def test_presigned_upload_local_storage_returns_400(app_with_mocks):
    """Local storage doesn't support pre-signed URLs – expect 400."""
    async with AsyncClient(
        transport=ASGITransport(app=app_with_mocks), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/presigned-upload",
            json={"filename": "doc.png", "content_type": "image/png"},
        )
    assert response.status_code == 400
    assert "does not support" in response.json()["detail"]

