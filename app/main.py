"""FastAPI application entry point."""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from app.cache.redis_client import close_redis, init_redis
from app.config import get_settings
from app.database.mongodb import close_db, init_db
from app.kafka.consumer import run_consumer_async
from app.kafka.producer import close_producer, init_producer
from app.kafka.serializers import init_serializers
from app.observability.tracing import setup_tracing
from app.api.routes import router
from app.api.ui_routes import ui_router

settings = get_settings()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: start-up and shutdown."""
    logger.info("Starting OCR service (env=%s)", settings.app_env)

    # Tracing
    setup_tracing(
        service_name=settings.otel.service_name,
        endpoint=settings.otel.exporter_endpoint,
        enabled=settings.otel.enabled,
    )

    # Database
    await init_db(settings.mongodb.uri, settings.mongodb.database)

    # Redis
    await init_redis(settings.redis)

    # Schema Registry serializers (must be before init_producer)
    init_serializers(settings.schema_registry)

    # Kafka producer
    init_producer(settings.kafka)

    # Kafka consumer (runs as asyncio task on the main event loop)
    _consumer_stop = asyncio.Event()
    consumer_task = asyncio.create_task(run_consumer_async(settings, _consumer_stop))

    logger.info("OCR service started successfully")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down OCR service")
    _consumer_stop.set()
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    close_producer()
    await close_redis()
    await close_db()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="OCR Service",
    description=(
        "Upload document images for OCR processing via a Kafka-backed pipeline. "
        "Images are stored, transformed, and passed to an ML inference service."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Prometheus instrumentation
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# Register routes
app.include_router(router, prefix="/api/v1")
app.include_router(ui_router)

# OpenTelemetry FastAPI instrumentation
FastAPIInstrumentor.instrument_app(app)
