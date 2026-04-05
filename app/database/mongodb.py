"""MongoDB async client for image metadata storage."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import motor.motor_asyncio
from pymongo import DESCENDING

from app.models.schemas import ImageMetadata, ImageStatus, OCRResult

logger = logging.getLogger(__name__)

_client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
_db: Optional[motor.motor_asyncio.AsyncIOMotorDatabase] = None


def get_db() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised – call init_db() first")
    return _db


async def init_db(uri: str, database: str) -> None:
    global _client, _db
    _client = motor.motor_asyncio.AsyncIOMotorClient(uri)
    _db = _client[database]
    await _db["image_metadata"].create_index("image_id", unique=True)
    await _db["image_metadata"].create_index([("created_at", DESCENDING)])
    logger.info("MongoDB connected: %s / %s", uri, database)


async def close_db() -> None:
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
    logger.info("MongoDB connection closed")


# ── CRUD helpers ─────────────────────────────────────────────────────────────

async def insert_metadata(metadata: ImageMetadata) -> None:
    db = get_db()
    doc = metadata.model_dump()
    doc["created_at"] = metadata.created_at
    doc["updated_at"] = metadata.updated_at
    await db["image_metadata"].insert_one(doc)


async def get_metadata(image_id: str) -> Optional[ImageMetadata]:
    db = get_db()
    doc = await db["image_metadata"].find_one({"image_id": image_id})
    if doc is None:
        return None
    doc.pop("_id", None)
    return ImageMetadata(**doc)


async def update_status(
    image_id: str,
    status: ImageStatus,
    error_message: Optional[str] = None,
) -> None:
    db = get_db()
    update: dict = {
        "$set": {
            "status": status.value if hasattr(status, "value") else status,
            "updated_at": datetime.now(timezone.utc),
        }
    }
    if error_message is not None:
        update["$set"]["error_message"] = error_message
    await db["image_metadata"].update_one({"image_id": image_id}, update)


async def store_ocr_result(image_id: str, result: OCRResult) -> None:
    """Persist the OCR result alongside the image metadata document."""
    db = get_db()
    await db["image_metadata"].update_one(
        {"image_id": image_id},
        {
            "$set": {
                "ocr_result": result.model_dump(),
                "status": ImageStatus.COMPLETED.value,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
