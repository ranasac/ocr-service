"""Kafka producer for image ingestion events."""

import logging
from datetime import datetime, timezone

from confluent_kafka import SerializingProducer
from confluent_kafka.serialization import StringSerializer

from app.config import KafkaSettings
from app.kafka.serializers import get_serializer, make_serialization_context
from app.models.schemas import KafkaImageMessage
from app.observability.metrics import kafka_messages_produced_total

logger = logging.getLogger(__name__)

_producer: SerializingProducer | None = None


def get_producer() -> SerializingProducer:
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
        # Serializers: key → UTF-8 string, value → Protobuf via Schema Registry
        "key.serializer": StringSerializer("utf_8"),
        "value.serializer": get_serializer(),
    }
    _producer = SerializingProducer(conf)
    logger.info("Kafka SerializingProducer initialised: %s", settings.bootstrap_servers)


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
    """Serialise a KafkaImageMessage to Protobuf and publish to Kafka.

    The ProtobufSerializer embeds the schema ID in the message header so the
    consumer can look up the exact schema version used to serialize each message,
    enabling safe schema evolution.
    """
    producer = get_producer()

    # Convert Pydantic model → protobuf message
    from proto.ocr_image_pb2 import KafkaImageMessage as KafkaImageMessageProto  # noqa: PLC0415

    proto_msg = KafkaImageMessageProto(
        image_id=message.image_id,
        filename=message.filename,
        content_type=message.content_type,
        storage_path=message.storage_path,
        size_bytes=message.size_bytes,
        timestamp=message.timestamp.isoformat(),
    )

    producer.produce(
        topic=topic,
        key=message.image_id,
        value=proto_msg,
        on_delivery=_delivery_callback,
        headers={"content-type": "application/x-protobuf"},
    )
    producer.poll(0)  # Trigger delivery callbacks


def publish_to_dlq(image_id: str, original_payload: bytes, error: str, dlq_topic: str) -> None:
    """Publish a failed message to the dead-letter queue topic.

    DLQ messages are published as plain JSON strings (not Protobuf) so they
    remain inspectable without a schema lookup even if the original schema
    is later deleted from the registry.
    """
    import json  # noqa: PLC0415

    from confluent_kafka import Producer  # noqa: PLC0415

    # Use a plain producer for DLQ to keep error envelopes human-readable
    from app.config import get_settings  # noqa: PLC0415

    settings = get_settings()
    plain_producer = Producer({"bootstrap.servers": settings.kafka.bootstrap_servers})

    dlq_envelope = {
        "image_id": image_id,
        "error": error,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "original_payload": original_payload.decode("utf-8", errors="replace"),
    }
    payload = json.dumps(dlq_envelope).encode("utf-8")
    plain_producer.produce(
        topic=dlq_topic,
        key=image_id.encode("utf-8"),
        value=payload,
    )
    plain_producer.flush(timeout=5)
    logger.warning("Published image %s to DLQ topic %s: %s", image_id, dlq_topic, error)

