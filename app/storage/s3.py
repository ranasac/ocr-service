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
        import os
        suffix = os.path.splitext(filename)[1] or ".bin"
        return f"images/{image_id}{suffix}"

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
