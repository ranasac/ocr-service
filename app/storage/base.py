"""Abstract base class for image storage backends."""

import abc
from pathlib import Path


class BaseStorage(abc.ABC):
    """Interface that every storage backend must implement."""

    @abc.abstractmethod
    async def save(self, image_id: str, filename: str, data: bytes) -> str:
        """Persist image bytes and return the storage path/key."""

    @abc.abstractmethod
    async def load(self, storage_path: str) -> bytes:
        """Load and return raw image bytes from storage."""

    @abc.abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Delete image from storage."""
