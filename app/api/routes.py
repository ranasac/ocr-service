"""FastAPI route handlers."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile, status
from opentelemetry import trace

from app.api.inference import CircuitOpenError
from app.config import Settings, get_settings
from app.database.mongodb import get_metadata, insert_metadata, update_status
from app.kafka.producer import publish_image_event
from app.models.schemas import (
    ImageMetadata,
    ImageStatus,
    KafkaImageMessage,
    PresignedUploadRequest,
    PresignedUploadResponse,
    UploadResponse,
)
from app.observability.metrics import ocr_requests_total
from app.storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter()
tracer = trace.get_tracer("ocr-service.routes")

_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/tiff",
    "image/bmp",
    "image/webp",
}
_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document image for OCR (async)",
)
async def upload_image(
    file: Annotated[UploadFile, File(description="Document image (JPEG, PNG, TIFF, BMP, WebP)")],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UploadResponse:
    """Upload a document image and immediately receive a task ID.

    Flow:
      1. Validate file type and size.
      2. Persist raw image to the configured storage backend.
      3. Insert image metadata into MongoDB (status=pending).
      4. Publish an event to Kafka for async preprocessing + OCR by the consumer.
      5. Return 202 Accepted with ``image_id`` and a ``status_url`` to poll.

    The Kafka consumer handles the full pipeline asynchronously:
      preprocessing → Redis array cache → ML inference → MongoDB result storage.

    Poll ``GET /api/v1/images/{image_id}`` to check status and retrieve the
    OCR result once ``status == "completed"``.
    """
    with tracer.start_as_current_span("upload_image") as span:
        # ── Validate ──────────────────────────────────────────────────────────
        if file.content_type not in _ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Unsupported media type: {file.content_type}. "
                    f"Allowed: {sorted(_ALLOWED_CONTENT_TYPES)}"
                ),
            )

        image_bytes = await file.read()
        if len(image_bytes) > _MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {_MAX_FILE_SIZE // (1024 * 1024)} MB",
            )

        # ── Persist image ─────────────────────────────────────────────────────
        storage = get_storage(settings.storage)
        metadata = ImageMetadata(
            filename=file.filename or "upload",
            content_type=file.content_type,
            size_bytes=len(image_bytes),
            storage_path="",  # set after save
        )
        image_id = metadata.image_id
        span.set_attribute("image_id", image_id)

        try:
            storage_path = await storage.save(image_id, file.filename or "upload", image_bytes)
        except Exception as exc:
            logger.exception("Storage save failed for %s: %s", image_id, exc)
            raise HTTPException(status_code=500, detail="Failed to save image") from exc

        metadata.storage_path = storage_path
        await insert_metadata(metadata)

        # ── Publish to Kafka ──────────────────────────────────────────────────
        kafka_msg = KafkaImageMessage(
            image_id=image_id,
            filename=file.filename or "upload",
            content_type=file.content_type,
            storage_path=storage_path,
            size_bytes=len(image_bytes),
        )
        try:
            publish_image_event(kafka_msg, topic=settings.kafka.image_topic)
        except Exception as exc:
            logger.error("Kafka publish failed for %s: %s", image_id, exc)
            # Non-fatal: the consumer will pick it up on retry, or the caller
            # can re-submit via the /images/{id}/submit endpoint.

        ocr_requests_total.labels(status="accepted").inc()
        status_url = f"/api/v1/images/{image_id}"

        return UploadResponse(
            image_id=image_id,
            status="accepted",
            status_url=status_url,
        )


@router.get(
    "/images/{image_id}",
    response_model=ImageMetadata,
    summary="Get image status and OCR result",
)
async def get_image(image_id: str) -> ImageMetadata:
    """Poll the processing status and retrieve the OCR result.

    Returns the full ``ImageMetadata`` document including the ``ocr_result``
    field once processing has completed (``status == "completed"``).
    Clients should poll until ``status`` is either ``"completed"`` or ``"failed"``.
    """
    metadata = await get_metadata(image_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Image {image_id!r} not found")
    return metadata


@router.post(
    "/images/{image_id}/submit",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger OCR processing for a pre-uploaded image",
)
async def submit_image(
    image_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Publish a Kafka event for an image that was uploaded via a pre-signed URL.

    Used in the pre-signed URL flow:
      1. ``POST /api/v1/presigned-upload`` → get pre-signed URL + image_id
      2. Client PUTs image bytes directly to cloud storage using the URL
      3. Client calls this endpoint to trigger OCR processing
    """
    metadata = await get_metadata(image_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Image {image_id!r} not found")

    if metadata.status not in (ImageStatus.PENDING, ImageStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Image {image_id!r} is already in status {metadata.status!r}",
        )

    kafka_msg = KafkaImageMessage(
        image_id=image_id,
        filename=metadata.filename,
        content_type=metadata.content_type,
        storage_path=metadata.storage_path,
        size_bytes=metadata.size_bytes,
    )
    publish_image_event(kafka_msg, topic=settings.kafka.image_topic)

    return {
        "image_id": image_id,
        "status": "accepted",
        "status_url": f"/api/v1/images/{image_id}",
    }


@router.post(
    "/presigned-upload",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a pre-signed URL to upload an image directly to cloud storage",
)
async def presigned_upload(
    body: PresignedUploadRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PresignedUploadResponse:
    """Return a time-limited pre-signed URL for direct client-to-storage upload.

    This endpoint offloads large image transfers from the API server to the
    storage backend, which is particularly valuable at high request rates.

    Pre-signed URL upload flow:
      1. POST here with ``filename`` + ``content_type`` → receive ``upload_url``
      2. HTTP PUT the raw image bytes directly to ``upload_url``
         (no auth header required; the signature is embedded in the URL)
      3. POST to ``submit_url`` to enqueue the OCR pipeline

    Note: Only supported when ``STORAGE_BACKEND`` is ``s3``, ``gcs``, or ``adls``.
    Use the regular ``/upload`` endpoint for local storage.
    """
    if body.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type: {body.content_type}",
        )

    storage = get_storage(settings.storage)
    image_id = str(uuid.uuid4())

    try:
        url = storage.generate_presigned_url(
            image_id=image_id,
            filename=body.filename,
            expires_in=300,
        )
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Pre-insert metadata so the submit endpoint can find the record
    storage_key = storage.storage_key(image_id, body.filename)
    metadata = ImageMetadata(
        image_id=image_id,
        filename=body.filename,
        content_type=body.content_type,
        size_bytes=0,  # unknown until upload completes
        storage_path=storage_key,
    )
    await insert_metadata(metadata)

    return PresignedUploadResponse(
        image_id=image_id,
        upload_url=url,
        expires_in=300,
        status_url=f"/api/v1/images/{image_id}",
        submit_url=f"/api/v1/images/{image_id}/submit",
    )


@router.get("/health", summary="Health check")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}
