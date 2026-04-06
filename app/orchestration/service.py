"""Orchestration service – coordinates all backend tasks for the OCR pipeline.

The API layer (routes.py) is responsible only for HTTP concerns:
  - Request parsing and validation
  - Returning HTTP responses

Everything else lives here:
  - Persisting images to storage
  - Writing/updating metadata in MongoDB
  - Publishing events to Kafka
  - Submitting re-processing requests
  - Generating pre-signed upload URLs

The Kafka consumer side of the pipeline (consume → transform → infer → store)
is already isolated in app/kafka/consumer.py and is NOT duplicated here.
"""

import logging

from opentelemetry import trace

from app.config import Settings
from app.database.mongodb import get_metadata, insert_metadata, update_status
from app.kafka.producer import publish_image_event
from app.models.schemas import (
    ImageMetadata,
    ImageStatus,
    KafkaImageMessage,
    PresignedUploadResponse,
    UploadResponse,
)
from app.storage import get_storage

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("ocr-service.orchestration")


class OrchestrationError(Exception):
    """Raised when a non-recoverable orchestration step fails."""


async def ingest_image(
    image_id: str,
    filename: str,
    content_type: str,
    image_bytes: bytes,
    settings: Settings,
) -> UploadResponse:
    """Persist an uploaded image and enqueue it for OCR processing.

    Steps:
      1. Save raw bytes to the configured storage backend.
      2. Insert ImageMetadata document into MongoDB (status=pending).
      3. Publish a KafkaImageMessage for the async OCR consumer.
      4. Return an UploadResponse with the image_id and polling URL.

    Raises:
        OrchestrationError: If storage save fails (unrecoverable for this request).
    """
    with _tracer.start_as_current_span("orchestrate_ingest") as span:
        span.set_attribute("image_id", image_id)
        span.set_attribute("filename", filename)
        span.set_attribute("content_type", content_type)
        span.set_attribute("size_bytes", len(image_bytes))

        # ── 1. Persist to storage ─────────────────────────────────────────────
        storage = get_storage(settings.storage)
        try:
            storage_path = await storage.save(image_id, filename, image_bytes)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, "storage save failed")
            logger.exception("Storage save failed for %s", image_id)
            raise OrchestrationError("Failed to save image to storage") from exc

        span.set_attribute("storage_path", storage_path)

        # ── 2. Insert metadata ────────────────────────────────────────────────
        metadata = ImageMetadata(
            image_id=image_id,
            filename=filename,
            content_type=content_type,
            size_bytes=len(image_bytes),
            storage_path=storage_path,
        )
        await insert_metadata(metadata)

        # ── 3. Publish to Kafka ───────────────────────────────────────────────
        kafka_msg = KafkaImageMessage(
            image_id=image_id,
            filename=filename,
            content_type=content_type,
            storage_path=storage_path,
            size_bytes=len(image_bytes),
        )
        try:
            publish_image_event(kafka_msg, topic=settings.kafka.image_topic)
        except Exception as exc:
            # Non-fatal: the caller can re-submit via /images/{id}/submit.
            logger.error("Kafka publish failed for %s: %s", image_id, exc)

        return UploadResponse(
            image_id=image_id,
            status="pending",
            status_url=f"/api/v1/images/{image_id}/text",
        )


async def resubmit_image(image_id: str, settings: Settings) -> dict:
    """Re-publish a Kafka event for an image that is pending or failed.

    Used in the pre-signed URL flow and by the /images/{id}/submit endpoint.

    Returns:
        dict with image_id, status, and status_url.

    Raises:
        OrchestrationError: If the image is not found or is in a terminal
                            non-resubmittable state.
    """
    with _tracer.start_as_current_span("orchestrate_resubmit") as span:
        span.set_attribute("image_id", image_id)

        metadata = await get_metadata(image_id)
        if metadata is None:
            raise OrchestrationError(f"Image {image_id!r} not found")

        if metadata.status not in (ImageStatus.PENDING, ImageStatus.FAILED):
            raise OrchestrationError(
                f"Image {image_id!r} is already in status {metadata.status!r}"
            )

        kafka_msg = KafkaImageMessage(
            image_id=image_id,
            filename=metadata.filename,
            content_type=metadata.content_type,
            storage_path=metadata.storage_path,
            size_bytes=metadata.size_bytes,
        )
        publish_image_event(kafka_msg, topic=settings.kafka.image_topic)
        await update_status(image_id, ImageStatus.PENDING)

        span.set_attribute("resubmitted", True)
        return {
            "image_id": image_id,
            "status": "accepted",
            "status_url": f"/api/v1/images/{image_id}",
        }


async def create_presigned_upload(
    image_id: str,
    filename: str,
    content_type: str,
    settings: Settings,
) -> PresignedUploadResponse:
    """Generate a pre-signed URL for direct client-to-storage upload and
    pre-insert a metadata placeholder so the submit endpoint can find the record.

    Raises:
        OrchestrationError: If the storage backend does not support pre-signed URLs.
    """
    with _tracer.start_as_current_span("orchestrate_presigned_upload") as span:
        span.set_attribute("image_id", image_id)
        span.set_attribute("filename", filename)

        storage = get_storage(settings.storage)
        try:
            url = storage.generate_presigned_url(
                image_id=image_id,
                filename=filename,
                expires_in=300,
            )
        except NotImplementedError as exc:
            raise OrchestrationError(str(exc)) from exc

        storage_key = storage.storage_key(image_id, filename)
        metadata = ImageMetadata(
            image_id=image_id,
            filename=filename,
            content_type=content_type,
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
