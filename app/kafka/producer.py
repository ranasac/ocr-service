"""Kafka producer for image ingestion events."""

import json
import logging
from datetime import datetime, timezone

from confluent_kafka import Producer

from app.config import KafkaSettings
from app.models.schemas import KafkaImageMessage
from app.observability.metrics import kafka_messages_produced_total

logger = logging.getLogger(__name__)

_producer: Producer | None = None


def get_producer() -> Producer:
    if _producer is None:
        raise RuntimeError("Kafka producer not initialised – call init_producer() first")
    return _producer


def init_producer(settings: KafkaSettings) -> None:
    global _producer
    conf = {
        "bootstrap.servers": settings.bootstrap_servers,
        "client.id": "ocr-service-producer",
        "acks": "all",
        "retries": 3,
        "retry.backoff.ms": 500,
    }
    _producer = Producer(conf)
    logger.info("Kafka producer initialised: %s", settings.bootstrap_servers)


def close_producer() -> None:
    global _producer
    if _producer:
        _producer.flush(timeout=5)
        _producer = None
    logger.info("Kafka producer closed")


def _delivery_callback(err, msg) -> None:  # noqa: ANN001
    topic = msg.topic() if msg else "unknown"
    if err:
        logger.error("Kafka delivery failed [%s]: %s", topic, err)
        kafka_messages_produced_total.labels(topic=topic, status="error").inc()
    else:
        logger.debug("Kafka message delivered to %s [%s] @ %s", topic, msg.partition(), msg.offset())
        kafka_messages_produced_total.labels(topic=topic, status="success").inc()


def publish_image_event(message: KafkaImageMessage, topic: str) -> None:
    """Publish an image ingestion event to Kafka."""
    producer = get_producer()

    def _serialise(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serialisable")

    payload = json.dumps(message.model_dump(), default=_serialise).encode("utf-8")
    producer.produce(
        topic=topic,
        key=message.image_id.encode("utf-8"),
        value=payload,
        callback=_delivery_callback,
    )
    producer.poll(0)  # Trigger delivery callbacks
