"""Kafka consumer that processes image ingestion events.

Responsibilities:
  1. Consume messages from the image topic
  2. Load raw image bytes from storage
  3. Run OCR preprocessing transformations
  4. Store transformed array in Redis with image_id as key
  5. Update image status in MongoDB
"""

import asyncio
import json
import logging
import signal
import threading
from typing import Optional

from confluent_kafka import Consumer, KafkaError, KafkaException, Message

from app.cache.redis_client import store_image_array
from app.config import Settings
from app.database.mongodb import init_db, update_status
from app.image.transforms import preprocess_for_ocr
from app.models.schemas import ImageStatus, KafkaImageMessage
from app.observability.metrics import (
    image_transform_latency_seconds,
    kafka_messages_consumed_total,
)
from app.storage import get_storage

logger = logging.getLogger(__name__)


async def process_message(msg_value: bytes, settings: Settings) -> None:
    """Process a single Kafka message end-to-end."""
    data = json.loads(msg_value)
    event = KafkaImageMessage(**data)
    image_id = event.image_id

    logger.info("Processing image %s (%s)", image_id, event.filename)

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

        await update_status(image_id, ImageStatus.COMPLETED)
        logger.info("Successfully processed image %s → shape %s", image_id, array.shape)

    except Exception as exc:
        logger.exception("Failed to process image %s: %s", image_id, exc)
        await update_status(image_id, ImageStatus.FAILED, error_message=str(exc))
        raise


def _build_consumer(settings: Settings) -> Consumer:
    conf = {
        "bootstrap.servers": settings.kafka.bootstrap_servers,
        "group.id": settings.kafka.consumer_group,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "session.timeout.ms": 30000,
        "max.poll.interval.ms": 300000,
    }
    return Consumer(conf)


async def run_consumer_async(settings: Settings, stop_event: Optional[asyncio.Event] = None) -> None:
    """Run the Kafka consumer loop (async wrapper)."""
    await init_db(settings.mongodb.uri, settings.mongodb.database)

    consumer = _build_consumer(settings)
    consumer.subscribe([settings.kafka.image_topic])
    logger.info("Kafka consumer subscribed to %s", settings.kafka.image_topic)

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
                await process_message(msg.value(), settings)
                consumer.commit(message=msg)
                kafka_messages_consumed_total.labels(topic=topic, status="success").inc()
            except Exception:
                kafka_messages_consumed_total.labels(topic=topic, status="error").inc()
                # Don't commit – will retry on restart

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
