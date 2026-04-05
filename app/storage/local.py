"""Local filesystem storage backend."""

import asyncio
import logging
from pathlib import Path

from app.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class LocalStorage(BaseStorage):
    def __init__(self, base_path: str = "./images") -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    async def save(self, image_id: str, filename: str, data: bytes) -> str:
        suffix = Path(filename).suffix or ".bin"
        dest = self._base / f"{image_id}{suffix}"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, dest.write_bytes, data)
        logger.info("Saved image %s to %s", image_id, dest)
        return str(dest)

    async def load(self, storage_path: str) -> bytes:
        path = Path(storage_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found at {storage_path}")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, path.read_bytes)

    async def delete(self, storage_path: str) -> None:
        path = Path(storage_path)
        if path.exists():
            path.unlink()
            logger.info("Deleted image at %s", storage_path)
