"""FastAPI route handlers – HTTP concerns only.

All backend coordination (storage, MongoDB, Kafka) is delegated to
app.orchestration.service.  This module owns only:
  - Request parsing and validation
  - Calling the orchestration layer
  - Returning HTTP responses
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile, status
from opentelemetry import trace

from app.config import Settings, get_settings
from app.database.mongodb import get_metadata
from app.models.schemas import (
    ImageMetadata,
    ImageStatus,
    PresignedUploadRequest,
    PresignedUploadResponse,
    UploadResponse,
)
from app.observability.metrics import ocr_requests_total
from app.orchestration.service import (
    OrchestrationError,
    create_presigned_upload,
    ingest_image,
    resubmit_image,
)

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
    """Validate the uploaded file and hand off to the orchestration layer."""
    with tracer.start_as_current_span("upload_image") as span:
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

        image_id = str(uuid.uuid4())
        span.set_attribute("image_id", image_id)

        try:
            response = await ingest_image(
                image_id=image_id,
                filename=file.filename or "upload",
                content_type=file.content_type,
                image_bytes=image_bytes,
                settings=settings,
            )
        except OrchestrationError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        ocr_requests_total.labels(status="accepted").inc()
        return response


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
    """Re-enqueue a pending or failed image for OCR processing."""
    try:
        return await resubmit_image(image_id, settings)
    except OrchestrationError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=409, detail=msg) from exc


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
    """Return a pre-signed URL for direct client-to-storage upload."""
    if body.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type: {body.content_type}",
        )

    image_id = str(uuid.uuid4())
    try:
        return await create_presigned_upload(
            image_id=image_id,
            filename=body.filename,
            content_type=body.content_type,
            settings=settings,
        )
    except OrchestrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/images/{image_id}/text",
    summary="Get OCR text result",
)
async def get_image_text(image_id: str) -> dict:
    """Returns the OCR extracted text for a completed image, or current status if still processing."""
    metadata = await get_metadata(image_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Image {image_id!r} not found")

    if metadata.status == ImageStatus.COMPLETED and metadata.ocr_result:
        return {
            "image_id": image_id,
            "status": metadata.status,
            "text": metadata.ocr_result.text,
            "confidence": metadata.ocr_result.confidence,
            "processing_time_ms": metadata.ocr_result.processing_time_ms,
        }

    return {
        "image_id": image_id,
        "status": metadata.status,
        "text": None,
        "message": "OCR not complete yet — poll this endpoint until status is 'completed'",
    }


@router.get("/health", summary="Health check")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}
