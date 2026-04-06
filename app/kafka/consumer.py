"""Kafka consumer that processes image ingestion events.

Responsibilities:
  1. Consume messages from the image topic
  2. Acquire an idempotency lock (Redis SET NX) to skip duplicate deliveries
  3. Load raw image bytes from storage
  4. Run OCR preprocessing transformations
  5. Store transformed array in Redis with image_id as key
  6. Call ML inference service and persist the OCR result in MongoDB
  7. Update image status in MongoDB
  8. On unrecoverable failure, publish to the dead-letter queue (DLQ) topic
"""

import asyncio
import logging
import threading
from typing import Optional

from confluent_kafka import DeserializingConsumer, KafkaError, Message
from confluent_kafka.serialization import StringDeserializer

from app.api.inference import CircuitOpenError, run_ocr_inference
from app.cache.redis_client import (
    acquire_processing_lock,
    release_processing_lock,
    store_image_array,
)
from app.config import Settings
from app.database.mongodb import store_ocr_result, update_status
from app.image.transforms import preprocess_for_ocr
from app.kafka.producer import publish_to_dlq
from app.kafka.serializers import get_deserializer
from app.models.schemas import ImageStatus, KafkaImageMessage
from app.observability.metrics import (
    image_transform_latency_seconds,
    kafka_messages_consumed_total,
)
from app.storage import get_storage

logger = logging.getLogger(__name__)


def _proto_to_pydantic(proto_msg) -> KafkaImageMessage:
    """Convert a deserialized protobuf KafkaImageMessage to the Pydantic model."""
    return KafkaImageMessage(
        image_id=proto_msg.image_id,
        filename=proto_msg.filename,
        content_type=proto_msg.content_type,
        storage_path=proto_msg.storage_path,
        size_bytes=proto_msg.size_bytes,
        # timestamp is an ISO string in the proto; Pydantic parses it automatically
        timestamp=proto_msg.timestamp or None,
    )


async def process_message(proto_msg, settings: Settings) -> None:
    """Process a single deserialized Kafka message end-to-end."""
    event = _proto_to_pydantic(proto_msg)
    image_id = event.image_id

    logger.info("Processing image %s (%s)", image_id, event.filename)

    # ── Idempotency guard ─────────────────────────────────────────────────────
    lock_acquired = await acquire_processing_lock(image_id)
    if not lock_acquired:
        logger.warning(
            "Duplicate message detected for image %s – skipping (idempotency guard)",
            image_id,
        )
        return

    try:
        await update_status(image_id, ImageStatus.PROCESSING)

        # 1. Load image from storage
        storage = get_storage(settings.storage)
        image_bytes = await storage.load(event.storage_path)

        # 2. Transform image
        with image_transform_latency_seconds.time():
            array = preprocess_for_ocr(
                image_bytes,
                resize_width=settings.image.resize_width,
                resize_height=settings.image.resize_height,
            )

        # 3. Store transformed array in Redis
        await store_image_array(image_id, array)
        logger.info("Successfully preprocessed image %s → shape %s", image_id, array.shape)

        # 4. Call ML inference and persist result
        ocr_result = await run_ocr_inference(image_id, settings.ml_service)
        await store_ocr_result(image_id, ocr_result)
        logger.info("OCR completed for image %s: %d chars", image_id, len(ocr_result.text))

    except Exception as exc:
        logger.exception("Failed to process image %s: %s", image_id, exc)
        await update_status(image_id, ImageStatus.FAILED, error_message=str(exc))
        try:
            # Re-serialize to bytes for the DLQ envelope using proto
            from proto.ocr_image_pb2 import KafkaImageMessage as KafkaImageMessageProto  # type: ignore[import]  # noqa: PLC0415
            original_bytes = KafkaImageMessageProto(
                image_id=event.image_id,
                filename=event.filename,
                content_type=event.content_type,
                storage_path=event.storage_path,
                size_bytes=event.size_bytes,
            ).SerializeToString()
            publish_to_dlq(
                image_id=image_id,
                original_payload=original_bytes,
                error=str(exc),
                dlq_topic=settings.kafka.dlq_topic,
            )
        except Exception as dlq_exc:
            logger.error("Failed to publish to DLQ for image %s: %s", image_id, dlq_exc)
        raise

    finally:
        await release_processing_lock(image_id)


def _build_consumer(settings: Settings) -> DeserializingConsumer:
    conf = {
        "bootstrap.servers": settings.kafka.bootstrap_servers,
        "group.id": settings.kafka.consumer_group,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "session.timeout.ms": 30000,
        "max.poll.interval.ms": 300000,
        # Deserializers: key → UTF-8 string, value → Protobuf via Schema Registry
        "key.deserializer": StringDeserializer("utf_8"),
        "value.deserializer": get_deserializer(),
    }
    return DeserializingConsumer(conf)


async def run_consumer_async(settings: Settings, stop_event: Optional[asyncio.Event] = None) -> None:
    """Run the Kafka consumer loop (async wrapper)."""
    consumer = _build_consumer(settings)
    consumer.subscribe([settings.kafka.image_topic])
    logger.info("Kafka DeserializingConsumer subscribed to %s", settings.kafka.image_topic)

    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_event_loop()

    try:
        while not stop_event.is_set():
            msg: Optional[Message] = await loop.run_in_executor(
                None, lambda: consumer.poll(timeout=1.0)
            )

            if msg is None:
                continue

            topic = msg.topic()

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    logger.debug("Reached end of partition for %s", topic)
                else:
                    logger.error("Kafka error: %s", msg.error())
                    kafka_messages_consumed_total.labels(topic=topic, status="error").inc()
                continue

            try:
                # msg.value() is already the deserialized protobuf object
                await process_message(msg.value(), settings)
                consumer.commit(message=msg)
                kafka_messages_consumed_total.labels(topic=topic, status="success").inc()
            except Exception:
                kafka_messages_consumed_total.labels(topic=topic, status="error").inc()

    finally:
        consumer.close()
        logger.info("Kafka consumer closed")


def start_consumer_thread(settings: Settings) -> threading.Thread:
    """Start consumer in a background thread (used when running alongside FastAPI)."""

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_consumer_async(settings))
        finally:
            loop.close()

    thread = threading.Thread(target=_run, daemon=True, name="kafka-consumer")
    thread.start()
    logger.info("Kafka consumer thread started")
    return thread
