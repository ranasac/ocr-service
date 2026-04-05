"""Pytest configuration and shared fixtures."""

import asyncio
import io
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import numpy as np
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Force test environment so YAML config doesn't try to load non-existent files
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("ML_SERVICE_URL", "http://localhost:8001")
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("STORAGE_LOCAL_PATH", "/tmp/ocr-test-images")


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Generate a tiny in-memory PNG image for testing."""
    from PIL import Image
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_array() -> np.ndarray:
    """Return a simple grayscale test array."""
    return np.zeros((100, 100), dtype=np.uint8)


@pytest.fixture
def fake_redis():
    """Return a fakeredis instance for testing."""
    return fakeredis.aioredis.FakeRedis(decode_responses=False)
