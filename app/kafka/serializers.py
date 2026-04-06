"""Protobuf serializer / deserializer factories for Kafka.

The confluent_kafka ProtobufSerializer automatically:
  1. Registers the schema with the Schema Registry on first publish.
  2. Embeds a 5-byte magic prefix (0x00 + 4-byte schema ID) in every message.
  3. Enforces the configured compatibility level (BACKWARD by default) —
     a breaking change is rejected at PRODUCE time, before any message hits
     the topic.

The ProtobufDeserializer strips the magic prefix, looks up the schema by ID,
and deserialises the payload into the correct protobuf Message class.
"""

import logging
from typing import Optional

from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.protobuf import (
    ProtobufDeserializer,
    ProtobufSerializer,
)
from confluent_kafka.serialization import MessageField, SerializationContext

from app.config import SchemaRegistrySettings

# Import the generated protobuf class.
# proto/ocr_image_pb2.py is generated at build time via:
#   python -m grpc_tools.protoc -I./proto --python_out=./proto proto/ocr_image.proto
try:
    from proto.ocr_image_pb2 import KafkaImageMessage as KafkaImageMessageProto  # type: ignore[import]
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Generated protobuf file not found. Run 'make proto' to generate it.\n"
        "  python -m grpc_tools.protoc -I./proto --python_out=./proto proto/ocr_image.proto"
    ) from exc

logger = logging.getLogger(__name__)

# Module-level singletons — created once via init_serializers()
_registry_client: Optional[SchemaRegistryClient] = None
_serializer: Optional[ProtobufSerializer] = None
_deserializer: Optional[ProtobufDeserializer] = None


def init_serializers(settings: SchemaRegistrySettings) -> None:
    """Initialise the Schema Registry client and both serializers.

    Must be called once during application startup (lifespan) before any
    Kafka produce or consume operations.
    """
    global _registry_client, _serializer, _deserializer

    client_conf: dict = {"url": settings.url}
    if settings.basic_auth_user_info:
        client_conf["basic.auth.user.info"] = settings.basic_auth_user_info

    _registry_client = SchemaRegistryClient(client_conf)

    # Serializer: registers the schema and enforces compatibility on produce.
    # use.deprecated.format=False → modern Confluent wire format (magic byte + schema ID).
    _serializer = ProtobufSerializer(
        KafkaImageMessageProto,
        _registry_client,
        {"use.deprecated.format": False},
    )

    # Deserializer: looks up schema by the embedded ID.
    _deserializer = ProtobufDeserializer(
        KafkaImageMessageProto,
        {"use.deprecated.format": False},
    )

    logger.info("Schema Registry serializers initialised: %s", settings.url)


def get_serializer() -> ProtobufSerializer:
    if _serializer is None:
        raise RuntimeError("Serializers not initialised – call init_serializers() first")
    return _serializer


def get_deserializer() -> ProtobufDeserializer:
    if _deserializer is None:
        raise RuntimeError("Serializers not initialised – call init_serializers() first")
    return _deserializer


def get_registry_client() -> SchemaRegistryClient:
    if _registry_client is None:
        raise RuntimeError("Schema Registry client not initialised – call init_serializers() first")
    return _registry_client


def make_serialization_context(topic: str) -> SerializationContext:
    """Return a SerializationContext for the value field of a topic message."""
    return SerializationContext(topic, MessageField.VALUE)
