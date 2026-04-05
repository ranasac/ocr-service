"""Standalone entry point for running the Kafka consumer as a separate process.

Used by the Kubernetes consumer Deployment (see k8s/consumer-deployment.yaml).
Run with:
    python -m app.kafka.consumer_entrypoint
"""

import asyncio
import logging
import sys

from app.cache.redis_client import close_redis, init_redis
from app.config import get_settings
from app.database.mongodb import close_db, init_db
from app.kafka.consumer import run_consumer_async
from app.kafka.producer import close_producer, init_producer
from app.observability.tracing import setup_tracing

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()

    setup_tracing(
        service_name=f"{settings.otel.service_name}-consumer",
        endpoint=settings.otel.exporter_endpoint,
        enabled=settings.otel.enabled,
    )

    await init_db(settings.mongodb.uri, settings.mongodb.database)
    await init_redis(settings.redis)
    init_producer(settings.kafka)

    logger.info("OCR consumer process starting (env=%s)", settings.app_env)

    try:
        await run_consumer_async(settings)
    finally:
        close_producer()
        await close_redis()
        await close_db()
        logger.info("OCR consumer process stopped")


if __name__ == "__main__":
    asyncio.run(main())
