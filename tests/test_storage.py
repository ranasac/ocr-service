"""Tests for storage backends."""

import os
import tempfile

import pytest
import pytest_asyncio

from app.storage.local import LocalStorage


@pytest.fixture
def tmp_storage(tmp_path):
    return LocalStorage(base_path=str(tmp_path))


@pytest.mark.asyncio
async def test_save_and_load(tmp_storage, sample_image_bytes):
    path = await tmp_storage.save("img-001", "test.png", sample_image_bytes)
    assert path.endswith(".png")
    assert os.path.exists(path)

    loaded = await tmp_storage.load(path)
    assert loaded == sample_image_bytes


@pytest.mark.asyncio
async def test_delete(tmp_storage, sample_image_bytes):
    path = await tmp_storage.save("img-002", "test.png", sample_image_bytes)
    assert os.path.exists(path)
    await tmp_storage.delete(path)
    assert not os.path.exists(path)


@pytest.mark.asyncio
async def test_load_missing_raises(tmp_storage):
    with pytest.raises(FileNotFoundError):
        await tmp_storage.load("/nonexistent/path/image.png")


@pytest.mark.asyncio
async def test_save_uses_image_id_as_stem(tmp_storage, sample_image_bytes):
    path = await tmp_storage.save("my-unique-id", "photo.jpg", sample_image_bytes)
    assert "my-unique-id" in path
