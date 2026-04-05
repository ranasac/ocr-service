"""Azure Data Lake Storage (ADLS Gen2 / Blob Storage) backend."""

import asyncio
import logging
import os

from app.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class ADLSStorage(BaseStorage):
    def __init__(self, account: str, container: str) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob.aio import BlobServiceClient

        self._account = account
        self._container = container
        credential = DefaultAzureCredential()
        self._service_client = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=credential,
        )

    def _blob_name(self, image_id: str, filename: str) -> str:
        suffix = os.path.splitext(filename)[1] or ".bin"
        return f"images/{image_id}{suffix}"

    async def save(self, image_id: str, filename: str, data: bytes) -> str:
        blob_name = self._blob_name(image_id, filename)
        container_client = self._service_client.get_container_client(self._container)
        blob_client = container_client.get_blob_client(blob_name)
        await blob_client.upload_blob(data, overwrite=True)
        path = f"adls://{self._account}/{self._container}/{blob_name}"
        logger.info("Saved image %s to %s", image_id, path)
        return path

    async def load(self, storage_path: str) -> bytes:
        # storage_path: adls://<account>/<container>/<blob>
        parts = storage_path.replace(f"adls://{self._account}/{self._container}/", "")
        container_client = self._service_client.get_container_client(self._container)
        blob_client = container_client.get_blob_client(parts)
        download = await blob_client.download_blob()
        return await download.readall()

    async def delete(self, storage_path: str) -> None:
        parts = storage_path.replace(f"adls://{self._account}/{self._container}/", "")
        container_client = self._service_client.get_container_client(self._container)
        blob_client = container_client.get_blob_client(parts)
        await blob_client.delete_blob()
