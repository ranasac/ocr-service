"""Pydantic schemas for the OCR service."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ImageStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageMetadata(BaseModel):
    """Stored in MongoDB for each uploaded image."""

    image_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    content_type: str
    size_bytes: int
    storage_path: str
    status: ImageStatus = ImageStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = None
    ocr_result: Optional["OCRResult"] = None

    model_config = {"use_enum_values": True}


class KafkaImageMessage(BaseModel):
    """Message published to Kafka for image processing."""

    image_id: str
    filename: str
    content_type: str
    storage_path: str
    size_bytes: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"use_enum_values": True}


class TransformedImageData(BaseModel):
    """Stored in Redis after image transformation."""

    image_id: str
    width: int
    height: int
    channels: int
    # Array stored separately as raw bytes; this is metadata only
    shape: list[int]


class OCRRequest(BaseModel):
    """Request to the ML inference service."""

    image_id: str
    config: Optional[dict[str, Any]] = None


class OCRResult(BaseModel):
    """OCR inference result."""

    image_id: str
    text: str
    confidence: Optional[float] = None
    processing_time_ms: float
    words: Optional[list[dict[str, Any]]] = None


class UploadResponse(BaseModel):
    """Response returned to client after image upload (202 Accepted)."""

    image_id: str
    status: str
    status_url: str
    message: str = "Image accepted for processing. Poll status_url for the result."


class PresignedUploadRequest(BaseModel):
    """Request body for the pre-signed URL endpoint."""

    filename: str
    content_type: str


class PresignedUploadResponse(BaseModel):
    """Pre-signed URL response – client uploads directly to cloud storage."""

    image_id: str
    upload_url: str
    expires_in: int = 300
    status_url: str
    submit_url: str
    message: str = (
        "Upload your file to upload_url using HTTP PUT, "
        "then POST to submit_url to trigger OCR processing."
    )


# Resolve forward reference
ImageMetadata.model_rebuild()
