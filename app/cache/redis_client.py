"""Redis client for storing transformed image arrays."""

import json
import logging
from typing import Optional

import numpy as np
import redis.asyncio as aioredis

from app.config import RedisSettings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None

# TTL for cached image arrays (1 hour)
ARRAY_TTL_SECONDS = 3600
# TTL for idempotency keys – long enough to cover any redelivery window (10 min)
IDEMPOTENCY_TTL_SECONDS = 600


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised – call init_redis() first")
    return _redis


async def init_redis(settings: RedisSettings) -> None:
    global _redis
    _redis = await aioredis.from_url(
        f"redis{'s' if settings.ssl else ''}://{settings.host}:{settings.port}/{settings.db}",
        password=settings.password,
        decode_responses=False,
    )
    await _redis.ping()
    logger.info("Redis connected: %s:%s/%s", settings.host, settings.port, settings.db)


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
    logger.info("Redis connection closed")


async def store_image_array(image_id: str, array: np.ndarray) -> None:
    """Serialise a numpy array and store it in Redis with TTL."""
    r = get_redis()
    meta = {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
    }
    array_key = f"img:array:{image_id}"
    meta_key = f"img:meta:{image_id}"
    pipe = r.pipeline()
    pipe.set(array_key, array.tobytes(), ex=ARRAY_TTL_SECONDS)
    pipe.set(meta_key, json.dumps(meta), ex=ARRAY_TTL_SECONDS)
    await pipe.execute()
    logger.debug("Stored image array for %s (shape=%s)", image_id, array.shape)


async def load_image_array(image_id: str) -> Optional[np.ndarray]:
    """Load a numpy array from Redis."""
    r = get_redis()
    array_key = f"img:array:{image_id}"
    meta_key = f"img:meta:{image_id}"

    raw_bytes, raw_meta = await r.mget(array_key, meta_key)
    if raw_bytes is None or raw_meta is None:
        logger.warning("Image array not found in Redis for %s", image_id)
        return None

    meta = json.loads(raw_meta)
    array = np.frombuffer(raw_bytes, dtype=np.dtype(meta["dtype"])).reshape(meta["shape"])
    return array


async def delete_image_array(image_id: str) -> None:
    r = get_redis()
    await r.delete(f"img:array:{image_id}", f"img:meta:{image_id}")


# ── Idempotency guard ─────────────────────────────────────────────────────────

async def acquire_processing_lock(image_id: str) -> bool:
    """Attempt to acquire an exclusive processing lock for *image_id*.

    Uses Redis SET NX (set-if-not-exists) so that only the first consumer
    thread/pod to call this function will return True.  Subsequent callers
    – caused by Kafka re-delivery or duplicate messages – will receive False
    and must skip processing to avoid double-running the pipeline.

    The lock expires automatically after IDEMPOTENCY_TTL_SECONDS, allowing
    re-processing if the first attempt crashed before completing.

    Returns:
        True  – lock acquired; this worker should proceed with processing.
        False – lock already held; this is a duplicate, skip processing.
    """
    r = get_redis()
    acquired = await r.set(
        f"processing_lock:{image_id}",
        "1",
        nx=True,
        ex=IDEMPOTENCY_TTL_SECONDS,
    )
    return bool(acquired)


async def release_processing_lock(image_id: str) -> None:
    """Release the processing lock once the pipeline has finished (success or failure)."""
    r = get_redis()
    await r.delete(f"processing_lock:{image_id}")

