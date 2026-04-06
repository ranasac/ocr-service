"""ML inference service (FastAPI microservice).

This service:
  1. Receives an image_id via POST /infer
  2. Retrieves the preprocessed image array from Redis
  3. Runs OCR via the local pytesseract model (or a managed endpoint)
  4. Returns the extracted text + metadata

The service can be deployed:
  - Locally (via docker-compose)
  - On Kubernetes (custom deployment)
  - As a managed endpoint: AWS SageMaker / Azure ML / GCP Vertex AI
    (by replacing the OCR model call with an SDK call)
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel

# Allow running as a standalone module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cache.redis_client import init_redis, load_image_array
from app.config import RedisSettings
from ml_service.model import get_model

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── Tracing setup ─────────────────────────────────────────────────────────────
_otel_endpoint = os.getenv("OTEL_EXPORTER_ENDPOINT", "http://localhost:4317")
_resource = Resource.create({SERVICE_NAME: "ml-service"})
_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=_otel_endpoint, insecure=True))
)
trace.set_tracer_provider(_provider)
_tracer = trace.get_tracer("ml-service.inference")


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_settings = RedisSettings(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
    )
    await init_redis(redis_settings)
    # Warm up model
    get_model()
    logger.info("ML service ready")
    yield


from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(
    title="OCR ML Inference Service",
    description="Lightweight Tesseract-based OCR inference microservice",
    version="1.0.0",
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")
FastAPIInstrumentor.instrument_app(app)


class InferRequest(BaseModel):
    image_id: str
    config: dict | None = None


class InferResponse(BaseModel):
    image_id: str
    text: str
    confidence: float | None = None
    words: list | None = None
    processing_time_ms: float


@app.post("/infer", response_model=InferResponse)
async def infer(request: InferRequest) -> InferResponse:
    """Run OCR on the preprocessed image stored in Redis."""
    image_id = request.image_id
    logger.info("Inference request for image_id=%s", image_id)

    with _tracer.start_as_current_span("ocr_model_predict") as span:
        span.set_attribute("image_id", image_id)

        array = await load_image_array(image_id)
        if array is None:
            span.set_status(trace.StatusCode.ERROR, "array not found in Redis")
            raise HTTPException(
                status_code=404,
                detail=f"No preprocessed array found for image_id={image_id!r}",
            )

        span.set_attribute("image.shape", str(array.shape))

        model = get_model()
        result = model.predict(array)

        span.set_attribute("ocr.text_length", len(result.get("text", "")))
        span.set_attribute("ocr.confidence", result.get("confidence") or 0.0)

        return InferResponse(
            image_id=image_id,
            text=result["text"],
            confidence=result.get("confidence"),
            words=result.get("words"),
            processing_time_ms=result["processing_time_ms"],
        )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("ML_SERVICE_PORT", "8001")))
