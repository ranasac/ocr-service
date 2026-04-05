"""Storage factory – returns the configured backend."""

from app.config import StorageSettings
from app.storage.base import BaseStorage


def get_storage(settings: StorageSettings) -> BaseStorage:
    backend = settings.backend.lower()

    if backend == "local":
        from app.storage.local import LocalStorage
        return LocalStorage(base_path=settings.local_path)

    if backend == "s3":
        from app.storage.s3 import S3Storage
        return S3Storage(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        )

    if backend == "gcs":
        from app.storage.gcs import GCSStorage
        return GCSStorage(bucket=settings.gcs_bucket)

    if backend == "adls":
        from app.storage.adls import ADLSStorage
        return ADLSStorage(
            account=settings.adls_account,
            container=settings.adls_container,
        )

    raise ValueError(f"Unknown storage backend: {backend!r}")
