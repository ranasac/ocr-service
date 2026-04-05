"""FastAPI route handlers."""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from opentelemetry import trace

from app.api.inference import run_ocr_inference
from app.cache.redis_client import get_redis, load_image_array
from app.config import Settings, get_settings
from app.database.mongodb import get_metadata, insert_metadata, update_status
from app.kafka.producer import get_producer, publish_image_event
from app.models.schemas import (
    ImageMetadata,
    ImageStatus,
    KafkaImageMessage,
    OCRResult,
    UploadResponse,
)
from app.observability.metrics import ocr_latency_seconds, ocr_requests_total
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
    status_code=status.HTTP_200_OK,
    summary="Upload a document image for OCR",
)
async def upload_image(
    file: Annotated[UploadFile, File(description="Document image (JPEG, PNG, TIFF, BMP, WebP)")],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UploadResponse:
    """Upload a document image, run it through the OCR pipeline and return extracted text.

    Flow:
      1. Validate & store image.
      2. Publish to Kafka for async preprocessing (resize, normalise → Redis).
      3. Wait for processed array to become available in Redis.
      4. Call ML inference service to perform OCR.
      5. Return OCR result to caller.
    """
    start = time.perf_counter()

    with tracer.start_as_current_span("upload_image") as span:
        # ── Validate ──────────────────────────────────────────────────────────
        if file.content_type not in _ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported media type: {file.content_type}. Allowed: {_ALLOWED_CONTENT_TYPES}",
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
            # Non-fatal: fall through to inline processing below

        # ── Wait for transformed array in Redis ───────────────────────────────
        # The Kafka consumer preprocesses the image asynchronously.
        # Poll Redis for up to 25 s (consumer is co-located or fast).
        import asyncio
        array = None
        for _ in range(50):  # 50 × 0.5 s = 25 s max
            array = await load_image_array(image_id)
            if array is not None:
                break
            await asyncio.sleep(0.5)

        if array is None:
            # Fallback: preprocess inline if consumer hasn't run yet
            logger.warning("Transformed array not in Redis for %s – preprocessing inline", image_id)
            from app.image.transforms import preprocess_for_ocr
            from app.cache.redis_client import store_image_array
            array = preprocess_for_ocr(
                image_bytes,
                resize_width=settings.image.resize_width,
                resize_height=settings.image.resize_height,
            )
            await store_image_array(image_id, array)

        # ── ML Inference ──────────────────────────────────────────────────────
        try:
            ocr_result = await run_ocr_inference(image_id, settings.ml_service)
        except Exception as exc:
            logger.exception("OCR inference failed for %s: %s", image_id, exc)
            await update_status(image_id, ImageStatus.FAILED, error_message=str(exc))
            ocr_requests_total.labels(status="error").inc()
            raise HTTPException(status_code=502, detail="OCR inference failed") from exc

        elapsed = time.perf_counter() - start
        ocr_latency_seconds.observe(elapsed)
        ocr_requests_total.labels(status="success").inc()
        await update_status(image_id, ImageStatus.COMPLETED)

        return UploadResponse(
            image_id=image_id,
            status="completed",
            ocr_result=ocr_result,
        )


@router.get(
    "/images/{image_id}",
    response_model=ImageMetadata,
    summary="Get image metadata",
)
async def get_image(image_id: str) -> ImageMetadata:
    """Retrieve metadata for a previously uploaded image."""
    metadata = await get_metadata(image_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Image {image_id!r} not found")
    return metadata


@router.get("/health", summary="Health check")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}
