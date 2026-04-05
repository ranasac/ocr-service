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


app = FastAPI(
    title="OCR ML Inference Service",
    description="Lightweight Tesseract-based OCR inference microservice",
    version="1.0.0",
    lifespan=lifespan,
)


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

    array = await load_image_array(image_id)
    if array is None:
        raise HTTPException(
            status_code=404,
            detail=f"No preprocessed array found for image_id={image_id!r}",
        )

    model = get_model()
    result = model.predict(array)

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
