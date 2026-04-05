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


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def publish_image_event(message: KafkaImageMessage, topic: str) -> None:
    """Publish an image ingestion event to Kafka."""
    producer = get_producer()
    payload = json.dumps(message.model_dump(), default=_serialize).encode("utf-8")
    producer.produce(
        topic=topic,
        key=message.image_id.encode("utf-8"),
        value=payload,
        callback=_delivery_callback,
    )
    producer.poll(0)  # Trigger delivery callbacks


def publish_to_dlq(image_id: str, original_payload: bytes, error: str, dlq_topic: str) -> None:
    """Publish a failed message to the dead-letter queue topic.

    The DLQ message wraps the original payload together with error context so
    that operators can inspect failures, replay events after fixing root causes,
    or route them to an alerting pipeline.
    """
    producer = get_producer()
    dlq_envelope = {
        "image_id": image_id,
        "error": error,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "original_payload": original_payload.decode("utf-8", errors="replace"),
    }
    payload = json.dumps(dlq_envelope, default=_serialize).encode("utf-8")
    producer.produce(
        topic=dlq_topic,
        key=image_id.encode("utf-8"),
        value=payload,
        callback=_delivery_callback,
    )
    producer.poll(0)
    logger.warning("Published image %s to DLQ topic %s: %s", image_id, dlq_topic, error)
