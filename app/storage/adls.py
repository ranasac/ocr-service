"""Azure Data Lake Storage (ADLS Gen2 / Blob Storage) backend."""

import asyncio
import logging
import os
from typing import Optional

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

    def generate_presigned_url(
        self,
        image_id: str,
        filename: str,
        expires_in: int = 300,
    ) -> Optional[str]:
        """Generate an Azure Blob Storage SAS URL for direct client PUT upload."""
        from datetime import datetime, timedelta, timezone

        from azure.storage.blob import (
            BlobSasPermissions,
            BlobServiceClient as SyncBlobServiceClient,
            generate_blob_sas,
        )

        blob_name = self._blob_name(image_id, filename)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # generate_blob_sas requires account key or user delegation key;
        # here we use DefaultAzureCredential-backed user delegation key.
        sync_client = SyncBlobServiceClient(
            account_url=f"https://{self._account}.blob.core.windows.net"
        )
        udk = sync_client.get_user_delegation_key(
            key_start_time=datetime.now(timezone.utc),
            key_expiry_time=expiry,
        )
        sas_token = generate_blob_sas(
            account_name=self._account,
            container_name=self._container,
            blob_name=blob_name,
            user_delegation_key=udk,
            permission=BlobSasPermissions(write=True, create=True),
            expiry=expiry,
        )
        url = (
            f"https://{self._account}.blob.core.windows.net"
            f"/{self._container}/{blob_name}?{sas_token}"
        )
        logger.info("Generated ADLS SAS URL for %s (expires %ds)", image_id, expires_in)
        return url
