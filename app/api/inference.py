"""ML inference client – calls the ML service for OCR inference."""

import logging
import time
from typing import Optional

import httpx

from app.config import MLServiceSettings
from app.models.schemas import OCRResult
from app.observability.metrics import ml_inference_errors_total, ml_inference_latency_seconds

logger = logging.getLogger(__name__)


async def run_ocr_inference(
    image_id: str,
    settings: MLServiceSettings,
    client: Optional[httpx.AsyncClient] = None,
) -> OCRResult:
    """Call the ML inference service and return OCR results.

    Args:
        image_id: The image identifier; the ML service retrieves the
                  transformed array from Redis using this key.
        settings: ML service configuration.
        client:   Optional httpx.AsyncClient (for testing / connection reuse).
    """
    url = f"{settings.url.rstrip('/')}/infer"
    payload = {"image_id": image_id}

    start = time.perf_counter()
    owns_client = client is None

    try:
        if owns_client:
            client = httpx.AsyncClient(timeout=settings.timeout)

        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        elapsed_ms = (time.perf_counter() - start) * 1000
        ml_inference_latency_seconds.observe((time.perf_counter() - start))

        return OCRResult(
            image_id=image_id,
            text=data.get("text", ""),
            confidence=data.get("confidence"),
            processing_time_ms=elapsed_ms,
            words=data.get("words"),
        )

    except httpx.TimeoutException as exc:
        ml_inference_errors_total.labels(error_type="timeout").inc()
        logger.error("ML inference timeout for image %s: %s", image_id, exc)
        raise

    except httpx.HTTPStatusError as exc:
        ml_inference_errors_total.labels(error_type="http_error").inc()
        logger.error("ML inference HTTP error for image %s: %s", image_id, exc)
        raise

    except Exception as exc:
        ml_inference_errors_total.labels(error_type="unknown").inc()
        logger.exception("ML inference unexpected error for image %s: %s", image_id, exc)
        raise

    finally:
        if owns_client and client:
            await client.aclose()
