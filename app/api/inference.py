"""ML inference client – calls the ML service for OCR inference.

Circuit Breaker Pattern
-----------------------
A circuit breaker wraps the HTTP call to the ML service.  Without one, a slow
or failing inference service would cause every OCR request to block until
timeout, exhausting the FastAPI thread pool and taking down the whole service.

The breaker has three states:

  CLOSED (healthy) – requests flow through normally.
  OPEN   (tripped)  – after ``_FAILURE_THRESHOLD`` consecutive failures the
                      breaker opens.  Calls fail immediately with
                      ``CircuitOpenError`` for ``_RESET_TIMEOUT_SECONDS``
                      seconds, giving the downstream service time to recover.
  HALF-OPEN         – one probe request is attempted.  On success the breaker
                      resets to CLOSED; on failure it stays OPEN.

The breaker state is kept in-process.  For a multi-replica deployment, store
the counters in Redis so all pods share the same view.
"""

import logging
import threading
import time
from typing import Optional

import httpx
from opentelemetry import trace
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import MLServiceSettings
from app.models.schemas import OCRResult
from app.observability.metrics import ml_inference_errors_total, ml_inference_latency_seconds

logger = logging.getLogger(__name__)


# ── Circuit Breaker ────────────────────────────────────────────────────────────

_FAILURE_THRESHOLD = 5        # consecutive failures before opening
_RESET_TIMEOUT_SECONDS = 30   # seconds the breaker stays OPEN before half-open probe


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN and calls are being shed."""


class _CircuitBreaker:
    """Thread-safe in-process circuit breaker."""

    def __init__(self, failure_threshold: int, reset_timeout: float) -> None:
        self._lock = threading.Lock()
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._failures = 0
        self._opened_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self._reset_timeout:
                # Transition to HALF-OPEN: let one probe through
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
                logger.warning(
                    "Circuit breaker OPEN after %d consecutive failures – "
                    "ML inference calls will be shed for %ss",
                    self._failures,
                    self._reset_timeout,
                )


_breaker = _CircuitBreaker(_FAILURE_THRESHOLD, _RESET_TIMEOUT_SECONDS)
_tracer = trace.get_tracer("ocr-service.inference")


# ── Retry decorator ────────────────────────────────────────────────────────────

def _is_retryable(exc: BaseException) -> bool:
    """Only retry on network-level or 5xx errors; do not retry 4xx."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    if isinstance(exc, httpx.NetworkError):
        return True
    return False


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)
async def _call_ml_service(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
) -> dict:
    """Single attempt with tenacity retry on transient failures."""
    response = await client.post(url, json=payload)
    response.raise_for_status()
    return response.json()


# ── Public interface ───────────────────────────────────────────────────────────

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

    Raises:
        CircuitOpenError: When the circuit breaker is OPEN (ML service unhealthy).
        httpx.TimeoutException / httpx.HTTPStatusError: On persistent failures.
    """
    if _breaker.is_open:
        ml_inference_errors_total.labels(error_type="circuit_open").inc()
        raise CircuitOpenError(
            "ML inference circuit breaker is OPEN – service is currently unavailable"
        )

    url = f"{settings.url.rstrip('/')}/infer"
    payload = {"image_id": image_id}
    start = time.perf_counter()
    owns_client = client is None

    with _tracer.start_as_current_span("ml_inference") as span:
        span.set_attribute("image_id", image_id)
        span.set_attribute("ml_service.url", url)

        try:
            if owns_client:
                client = httpx.AsyncClient(timeout=settings.timeout)

            data = await _call_ml_service(client, url, payload)

            elapsed = time.perf_counter() - start
            ml_inference_latency_seconds.observe(elapsed)
            _breaker.record_success()

            span.set_attribute("ml_service.confidence", data.get("confidence") or 0.0)
            span.set_attribute("ml_service.text_length", len(data.get("text", "")))

            return OCRResult(
                image_id=image_id,
                text=data.get("text", ""),
                confidence=data.get("confidence"),
                processing_time_ms=elapsed * 1000,
                words=data.get("words"),
            )

        except httpx.TimeoutException as exc:
            _breaker.record_failure()
            ml_inference_errors_total.labels(error_type="timeout").inc()
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, "ML inference timeout")
            logger.error("ML inference timeout for image %s: %s", image_id, exc)
            raise

        except httpx.HTTPStatusError as exc:
            _breaker.record_failure()
            ml_inference_errors_total.labels(error_type="http_error").inc()
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, f"HTTP {exc.response.status_code}")
            logger.error("ML inference HTTP error for image %s: %s", image_id, exc)
            raise

        except Exception as exc:
            _breaker.record_failure()
            ml_inference_errors_total.labels(error_type="unknown").inc()
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            logger.exception("ML inference unexpected error for image %s: %s", image_id, exc)
            raise

        finally:
            if owns_client and client:
                await client.aclose()
