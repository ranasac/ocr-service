"""Abstract base class for image storage backends."""

import abc
from pathlib import Path
from typing import Optional


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

    def generate_presigned_url(
        self,
        image_id: str,
        filename: str,
        expires_in: int = 300,
    ) -> Optional[str]:
        """Return a pre-signed URL that allows a client to PUT the image
        directly to this storage backend, bypassing the API server.

        Only cloud storage backends (S3, GCS, ADLS) implement this method.
        Local storage raises NotImplementedError.

        Args:
            image_id:   Unique identifier for the image (used as the key stem).
            filename:   Original filename (used to derive the file extension).
            expires_in: URL validity in seconds (default 300 s = 5 min).

        Returns:
            A time-limited pre-signed URL string, or None if not supported.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support pre-signed URLs. "
            "Use the regular /upload endpoint instead, or switch to S3/GCS/ADLS."
        )

    def storage_key(self, image_id: str, filename: str) -> str:
        """Return the canonical storage key/path for an image.

        Used by callers that need to know the key before the file is uploaded
        (e.g. when generating a pre-signed URL).
        """
        import os
        suffix = os.path.splitext(filename)[1] or ".bin"
        return f"images/{image_id}{suffix}"
