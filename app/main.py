"""FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from app.cache.redis_client import close_redis, init_redis
from app.config import get_settings
from app.database.mongodb import close_db, init_db
from app.kafka.consumer import start_consumer_thread
from app.kafka.producer import close_producer, init_producer
from app.observability.tracing import setup_tracing
from app.api.routes import router

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

    # Kafka producer
    init_producer(settings.kafka)

    # Kafka consumer (runs in background thread)
    start_consumer_thread(settings)

    logger.info("OCR service started successfully")
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down OCR service")
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

# OpenTelemetry FastAPI instrumentation
FastAPIInstrumentor.instrument_app(app)
