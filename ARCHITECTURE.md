# OCR Service – Architecture Document

## Overview

The OCR service is a cloud-native, asynchronous document OCR pipeline built with
FastAPI, Apache Kafka, Redis and MongoDB.  It is designed to run locally with
Docker Compose and on any major cloud provider by swapping a YAML config file.

---

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                           Client                                        │
│                     POST /api/v1/upload                                 │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │ multipart/form-data
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         FastAPI (OCR Service)                             │
│                                                                          │
│  ┌──────────────┐   ┌──────────────────────┐   ┌─────────────────────┐ │
│  │   Validate   │──▶│  Save to Storage     │──▶│  Insert MongoDB     │ │
│  │  (type/size) │   │  local / S3 / GCS /  │   │  metadata doc       │ │
│  └──────────────┘   │  ADLS                │   └─────────────────────┘ │
│                     └──────────┬───────────┘                            │
│                                │                                         │
│                     ┌──────────▼───────────┐                            │
│                     │  Kafka Producer       │                            │
│                     │  Publish image event  │                            │
│                     └──────────┬───────────┘                            │
│                                │                                         │
│              ┌─────────────────▼──────────────┐                         │
│              │  Poll Redis for transformed     │                         │
│              │  array (up to 25 s)             │                         │
│              │  [fallback: inline preprocess]  │                         │
│              └─────────────────┬──────────────┘                         │
│                                │                                         │
│              ┌─────────────────▼──────────────┐                         │
│              │  HTTP POST → ML Inference Svc   │                         │
│              │  (Tesseract / SageMaker /        │                         │
│              │   Azure ML / Vertex AI)          │                         │
│              └─────────────────┬──────────────┘                         │
│                                │                                         │
│              ┌─────────────────▼──────────────┐                         │
│              │  Return OCR result to client    │                         │
│              └────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────────┘
          │                                │
          │ Kafka topic: ocr.images        │ HTTP
          ▼                                ▼
┌──────────────────────┐    ┌───────────────────────────────────┐
│   Kafka Consumer     │    │       ML Inference Service         │
│  (background thread  │    │           (FastAPI)                │
│   / separate pod)    │    │                                    │
│                      │    │  POST /infer                       │
│  1. Load raw bytes   │    │    1. Load array from Redis        │
│     from Storage     │    │    2. Run pytesseract OCR          │
│  2. Preprocess:      │    │    3. Return text + confidence     │
│     - grayscale      │    └───────────────────────────────────┘
│     - autocontrast   │                    │
│     - resize         │                    │ reads array
│     - denoise        │                    ▼
│  3. Store numpy arr  │         ┌─────────────────────┐
│     in Redis         │────────▶│       Redis          │
│  4. Update MongoDB   │         │  key: img:array:<id> │
│     status           │         │  key: img:meta:<id>  │
└──────────────────────┘         └─────────────────────┘
          │
          │ update status
          ▼
┌─────────────────────┐
│      MongoDB        │
│  collection:        │
│  image_metadata     │
└─────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                         Observability Stack                               │
│                                                                           │
│  FastAPI ──(traces)──▶ OTEL Collector ──▶ Jaeger / Cloud APM             │
│  FastAPI ──(metrics)──▶ Prometheus ──▶ Grafana                           │
│  All services ──(logs)──▶ stdout (collected by cloud logging agent)      │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Component Descriptions

| Component | Role | Technology |
|-----------|------|------------|
| **FastAPI (OCR Service)** | Client-facing REST API; orchestrates the upload, Kafka publish, and inference call | Python 3.11, FastAPI |
| **Kafka** | Durable message queue decoupling upload from transformation | Apache Kafka (local) / AWS MSK / Azure Event Hubs / GCP Pub/Sub bridge |
| **Kafka Consumer** | Reads image events; runs preprocessing; writes transformed array to Redis | confluent-kafka, PIL, numpy |
| **Storage** | Persists raw image bytes | Local FS / AWS S3 / GCS / Azure ADLS Gen2 |
| **MongoDB** | Persists image metadata (status, path, timestamps) | MongoDB / AWS DocumentDB / Azure Cosmos DB |
| **Redis** | Short-lived cache for preprocessed image arrays (1 h TTL) | Redis / AWS ElastiCache / Azure Cache for Redis / GCP Memorystore |
| **ML Inference Service** | Lightweight OCR microservice; reads array from Redis; runs Tesseract | FastAPI + pytesseract (swappable for SageMaker / Azure ML / Vertex AI) |
| **OpenTelemetry Collector** | Receives traces & metrics; exports to backends | OTEL Collector |
| **Prometheus + Grafana** | Metrics scraping and dashboarding | Prometheus + Grafana |

---

## Configuration & Multi-Cloud Support

All environment-specific parameters live in `config/<env>.yaml` and are
overrideable via environment variables (highest priority) or `.env` file.

| Environment | `APP_ENV` | Kafka | Storage | Metadata DB | Cache |
|-------------|-----------|-------|---------|-------------|-------|
| Local | `local` | Docker Kafka | Local FS | Docker MongoDB | Docker Redis |
| AWS | `aws` | AWS MSK | S3 | DocumentDB / Atlas | ElastiCache |
| GCP | `gcp` | Confluent Cloud | GCS | MongoDB Atlas | Memorystore |
| Azure | `azure` | Event Hubs (Kafka API) | ADLS Gen2 | Cosmos DB | Azure Cache for Redis |

Switch environment by setting `APP_ENV=aws` (+ relevant credentials as env vars).

---

## Data Flow

```
1. Client sends PNG/JPEG/TIFF via POST /api/v1/upload
2. FastAPI validates type (PNG/JPEG/TIFF/BMP/WebP) and size (≤ 20 MB)
3. Raw bytes are saved to configured Storage backend
4. ImageMetadata doc is inserted into MongoDB (status=pending)
5. KafkaImageMessage is produced to topic ocr.images
6. FastAPI polls Redis (0.5 s intervals, max 25 s) for the preprocessed array
7. Kafka Consumer (background thread / separate pod):
     a. Consumes message from ocr.images
     b. Loads raw bytes from Storage
     c. Runs full preprocessing pipeline (grayscale → autocontrast → resize → denoise)
     d. Serialises numpy array + metadata into Redis (TTL 1 h)
     e. Updates MongoDB status → completed
8. FastAPI calls ML Inference Service POST /infer with image_id
9. ML Service loads array from Redis, runs Tesseract OCR
10. Result (text, confidence, word boxes) is returned to FastAPI → client
```

---

## Trade-offs

### Kafka (async queue) vs. synchronous processing

| Aspect | Kafka (chosen) | Sync inline |
|--------|---------------|-------------|
| Throughput | High – decouples producer/consumer | Low – blocked on transform |
| Complexity | Higher (broker, consumer, polling loop) | Lower |
| Fault tolerance | Good – consumer retries on failure | Poor – failure = 500 |
| Latency | Higher (round-trip through queue) | Lower |

**Choice rationale:** Kafka gives us replay, backpressure control and fan-out
(future consumers for thumbnails, audit logs, etc.).  The polling fallback in
the route ensures correctness if Kafka is temporarily unavailable.

### Redis for array cache vs. passing array in Kafka message

| Aspect | Redis (chosen) | Kafka payload |
|--------|---------------|---------------|
| Max size | No practical limit | ~1 MB Kafka default |
| Latency for inference | Redis read ~1 ms | N/A (already in memory) |
| Lifecycle management | TTL-based eviction | Kafka retention policy |

**Choice:** Kafka messages are small (event metadata only); arrays go to Redis.

### Local Tesseract vs. managed inference endpoint

| Aspect | Tesseract (default) | SageMaker / Azure ML |
|--------|--------------------|-----------------------|
| Cost | Free | Per-invocation billing |
| Accuracy | Good for clean documents | Higher (custom models) |
| Latency | 50–500 ms local | Network + cold start |
| Ops overhead | None | Endpoint management |

The code is designed so the ML Service can be a thin proxy to a managed
endpoint by replacing the `model.predict()` call with an SDK call.

---

## Scaling Considerations

### Low load (< 50 RPS)
- Single FastAPI pod, single Kafka consumer, single ML service replica
- Local Redis and MongoDB sufficient

### Medium load (50–500 RPS)
- Horizontal Pod Autoscaling on FastAPI (stateless)
- Multiple Kafka consumer replicas (each in same consumer group)
- Redis Cluster or managed service
- MongoDB Atlas M30+ or AWS DocumentDB

### High load (500+ RPS)

**Bottlenecks (in order):**

1. **Kafka Consumer / image transform** – CPU-bound; scale with more consumer
   replicas up to the number of Kafka partitions.  Increase partition count
   first (default 1 → 16+).

2. **ML Inference Service** – Tesseract is single-threaded.  Use GPU-backed
   models (EasyOCR, PaddleOCR) or offload to SageMaker with auto-scaling
   inference endpoints.

3. **Redis** – At very high load the array store becomes a bottleneck.  Options:
   - Redis Cluster (horizontal sharding)
   - Reduce TTL aggressively
   - Skip Redis entirely and pass the array directly through an internal gRPC
     call from consumer to inference service

4. **Storage I/O** – With S3/GCS, parallel uploads benefit from transfer
   acceleration; pre-signed URLs let clients upload directly without routing
   through the API.

5. **MongoDB** – Write throughput cap on a single-node replica set.  Use a
   sharded cluster keyed on `image_id` (UUID → natural distribution).

6. **The upload endpoint previously had a 25 s busy-poll loop** waiting for Redis.
   This has been removed — the upload now returns 202 immediately (see item 1
   in the implemented improvements below).

### Implemented design improvements

1. ✅ **Return 202 Accepted immediately** — `POST /api/v1/upload` now responds
   immediately with `image_id` and a `status_url`.  The Kafka consumer drives
   the full pipeline (preprocess → Redis → ML inference → MongoDB result).
   Clients poll `GET /api/v1/images/{image_id}` until `status == "completed"`.

2. ✅ **Separate consumer into its own Kubernetes Deployment** — see
   `k8s/consumer-deployment.yaml`.  The consumer is also runnable standalone
   via `python -m app.kafka.consumer_entrypoint`.

3. ✅ **KEDA autoscaling for the consumer** — `k8s/keda-scaledobject.yaml`
   defines a `ScaledObject` that watches consumer lag on `ocr.images` and
   scales consumer pods from `minReplicaCount: 1` to `maxReplicaCount: 8`
   (one replica per Kafka partition).  KEDA adds a replica for every 10
   unprocessed messages and scales back down after a 60 s cooldown.

   Prerequisites:
   ```bash
   kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.14.0/keda-2.14.0.yaml
   kubectl apply -f k8s/consumer-deployment.yaml
   kubectl apply -f k8s/keda-scaledobject.yaml
   ```

4. ✅ **Dead-letter queue (DLQ)** — when the consumer fails to process a
   message after exhausting retries, the original payload is forwarded to the
   `ocr.images.dlq` Kafka topic (configurable via `KAFKA_DLQ_TOPIC`).  The
   envelope includes `image_id`, `error`, `failed_at`, and `original_payload`
   for operator inspection and replay.  The message is **not committed**,
   preserving consumer-lag visibility in monitoring dashboards.

5. ✅ **Idempotency guard** — the consumer calls `acquire_processing_lock()`
   which issues a Redis `SET NX` with a 10-minute TTL before doing any work.
   If the lock is already held (duplicate delivery or concurrent consumer),
   the message is silently skipped.  The lock is released — and automatically
   expires — when processing finishes, allowing clean re-processing after a
   crash.

6. ✅ **Pre-signed URL upload** — `POST /api/v1/presigned-upload` returns a
   time-limited URL (5 min) pointing directly at S3/GCS/ADLS.  The client
   PUTs the image bytes straight to cloud storage (bypassing the API server),
   then calls `POST /api/v1/images/{image_id}/submit` to enqueue OCR.
   Supported backends: `s3` (presigned PUT), `gcs` (v4 signed URL),
   `adls` (user-delegation SAS token).  Local storage returns HTTP 400
   directing the caller to use the regular `/upload` endpoint.

7. ✅ **Circuit breaker on ML inference** — `app/api/inference.py` wraps the
   HTTP call to the ML service with:
   - **Tenacity retry**: up to 3 attempts with exponential back-off (0.5 s → 4 s)
     on transient errors (timeouts, 5xx responses, network errors).
   - **In-process circuit breaker**: after 5 consecutive failures the breaker
     opens for 30 seconds.  During this window all calls raise
     `CircuitOpenError` immediately (fail-fast), preventing thread exhaustion
     and giving the downstream service time to recover.  The breaker
     transitions to HALF-OPEN after the reset timeout and closes again on the
     first successful probe.

   For multi-replica deployments, store the failure counter in Redis so all
   API pods share the same breaker state.

8. **gRPC between consumer and ML service** — not yet implemented; the current
   HTTP/JSON interface is simple and sufficient for most workloads.

---

## Observability

| Signal | Tool | Endpoint |
|--------|------|----------|
| Traces | OpenTelemetry → OTLP Collector | `4317` (gRPC) |
| Metrics | Prometheus scrape | `/metrics` |
| Dashboards | Grafana | `3000` |
| Logs | stdout → cloud logging agent | – |

Key metrics exported:
- `ocr_requests_total{status}` – request count by status
- `ocr_latency_seconds` – end-to-end latency histogram
- `ml_inference_latency_seconds` – ML service call latency
- `image_transform_latency_seconds` – preprocessing latency
- `kafka_messages_produced_total` / `kafka_messages_consumed_total`
- `kafka_consumer_lag{topic,partition}`
