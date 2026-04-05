"""AWS S3 storage backend."""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from app.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class S3Storage(BaseStorage):
    def __init__(self, bucket: str, region: str = "us-east-1") -> None:
        self._bucket = bucket
        self._client = boto3.client("s3", region_name=region)

    def _key(self, image_id: str, filename: str) -> str:
        return self.storage_key(image_id, filename)

    async def save(self, image_id: str, filename: str, data: bytes) -> str:
        import asyncio
        key = self._key(image_id, filename)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
            ),
        )
        path = f"s3://{self._bucket}/{key}"
        logger.info("Saved image %s to %s", image_id, path)
        return path

    async def load(self, storage_path: str) -> bytes:
        import asyncio
        # storage_path is "s3://bucket/key"
        key = storage_path.replace(f"s3://{self._bucket}/", "")
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.get_object(Bucket=self._bucket, Key=key),
        )
        return response["Body"].read()

    async def delete(self, storage_path: str) -> None:
        import asyncio
        key = storage_path.replace(f"s3://{self._bucket}/", "")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.delete_object(Bucket=self._bucket, Key=key),
        )

    def generate_presigned_url(
        self,
        image_id: str,
        filename: str,
        expires_in: int = 300,
    ) -> Optional[str]:
        """Generate a pre-signed S3 PUT URL for direct client upload."""
        key = self._key(image_id, filename)
        url = self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )
        logger.info("Generated S3 pre-signed URL for %s (expires %ds)", image_id, expires_in)
        return url
