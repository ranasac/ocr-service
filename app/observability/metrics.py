"""Prometheus metrics definitions for the OCR service."""

from prometheus_client import Counter, Histogram, Gauge

# ── Upload / OCR ────────────────────────────────────────────────────────────
ocr_requests_total = Counter(
    "ocr_requests_total",
    "Total number of OCR requests received",
    ["status"],  # success | error
)

ocr_latency_seconds = Histogram(
    "ocr_latency_seconds",
    "End-to-end OCR request latency in seconds",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# ── Kafka ────────────────────────────────────────────────────────────────────
kafka_messages_produced_total = Counter(
    "kafka_messages_produced_total",
    "Total Kafka messages produced",
    ["topic", "status"],
)

kafka_messages_consumed_total = Counter(
    "kafka_messages_consumed_total",
    "Total Kafka messages consumed",
    ["topic", "status"],
)

kafka_consumer_lag = Gauge(
    "kafka_consumer_lag",
    "Kafka consumer lag (messages behind)",
    ["topic", "partition"],
)

# ── Storage ──────────────────────────────────────────────────────────────────
storage_operations_total = Counter(
    "storage_operations_total",
    "Total storage operations",
    ["backend", "operation", "status"],
)

# ── ML Inference ─────────────────────────────────────────────────────────────
ml_inference_latency_seconds = Histogram(
    "ml_inference_latency_seconds",
    "ML inference call latency in seconds",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

ml_inference_errors_total = Counter(
    "ml_inference_errors_total",
    "Total ML inference errors",
    ["error_type"],
)

# ── Image transformation ──────────────────────────────────────────────────────
image_transform_latency_seconds = Histogram(
    "image_transform_latency_seconds",
    "Image transformation latency in seconds",
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0],
)
