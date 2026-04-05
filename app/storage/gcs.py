"""Google Cloud Storage backend."""

import asyncio
import logging
import os
from typing import Optional

from app.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class GCSStorage(BaseStorage):
    def __init__(self, bucket: str) -> None:
        from google.cloud import storage as gcs
        self._bucket_name = bucket
        self._client = gcs.Client()
        self._bucket = self._client.bucket(bucket)

    def _blob_name(self, image_id: str, filename: str) -> str:
        suffix = os.path.splitext(filename)[1] or ".bin"
        return f"images/{image_id}{suffix}"

    async def save(self, image_id: str, filename: str, data: bytes) -> str:
        blob_name = self._blob_name(image_id, filename)
        loop = asyncio.get_event_loop()
        blob = self._bucket.blob(blob_name)
        await loop.run_in_executor(None, lambda: blob.upload_from_string(data))
        path = f"gs://{self._bucket_name}/{blob_name}"
        logger.info("Saved image %s to %s", image_id, path)
        return path

    async def load(self, storage_path: str) -> bytes:
        blob_name = storage_path.replace(f"gs://{self._bucket_name}/", "")
        loop = asyncio.get_event_loop()
        blob = self._bucket.blob(blob_name)
        return await loop.run_in_executor(None, blob.download_as_bytes)

    async def delete(self, storage_path: str) -> None:
        blob_name = storage_path.replace(f"gs://{self._bucket_name}/", "")
        loop = asyncio.get_event_loop()
        blob = self._bucket.blob(blob_name)
        await loop.run_in_executor(None, blob.delete)

    def generate_presigned_url(
        self,
        image_id: str,
        filename: str,
        expires_in: int = 300,
    ) -> Optional[str]:
        """Generate a GCS signed URL for direct client PUT upload."""
        import datetime
        blob_name = self._blob_name(image_id, filename)
        blob = self._bucket.blob(blob_name)
        url = blob.generate_signed_url(
            expiration=datetime.timedelta(seconds=expires_in),
            method="PUT",
            version="v4",
        )
        logger.info("Generated GCS signed URL for %s (expires %ds)", image_id, expires_in)
        return url
