# ocr-service

A cloud-native document OCR pipeline built with **FastAPI**, **Apache Kafka**,
**Redis**, **MongoDB** and a pluggable storage backend (local / S3 / GCS / ADLS).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design, trade-offs and scaling guide.

---

## Features

- **REST API** – Upload document images (PNG, JPEG, TIFF, BMP, WebP, ≤ 20 MB)
- **Kafka pipeline** – Durable, replayable image ingestion queue
- **Pluggable storage** – Local FS, AWS S3, GCS, Azure ADLS Gen2
- **MongoDB** – Image metadata persistence (status, path, timestamps)
- **Redis** – Preprocessed image array cache (1 h TTL)
- **Image preprocessing** – Grayscale conversion, auto-contrast, resize, denoise
- **ML Inference Service** – Standalone FastAPI microservice using Tesseract OCR
- **Observability** – OpenTelemetry tracing + Prometheus metrics + Grafana dashboard
- **Multi-cloud** – Swap `APP_ENV=local|aws|gcp|azure` to change all backends

---

## Quick Start (Docker Compose)

```bash
# Clone and copy env example
cp .env.example .env

# Start all services (Kafka, MongoDB, Redis, OTEL, Prometheus, Grafana, ML service, OCR service)
docker-compose up --build
```

Services:
| Service | URL |
|---------|-----|
| OCR API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| ML Inference | http://localhost:8001 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |

### Upload an image

```bash
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@/path/to/document.png"
```

Response:
```json
{
  "image_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "ocr_result": {
    "image_id": "550e8400-e29b-41d4-a716-446655440000",
    "text": "Hello World\nThis is extracted text",
    "confidence": 92.5,
    "processing_time_ms": 150.3,
    "words": [...]
  },
  "message": "Image processed successfully"
}
```

---

## Local Development (without Docker)

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Start infrastructure (Kafka, MongoDB, Redis)
docker-compose up zookeeper kafka mongodb redis -d

# Start ML service
uvicorn ml_service.main:app --port 8001 --reload

# Start OCR service
APP_ENV=local uvicorn app.main:app --port 8000 --reload
```

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `local` | Config profile: `local`, `aws`, `gcp`, `azure` |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `REDIS_HOST` | `localhost` | Redis host |
| `STORAGE_BACKEND` | `local` | Storage: `local`, `s3`, `gcs`, `adls` |
| `ML_SERVICE_URL` | `http://localhost:8001` | ML inference service URL |
| `OTEL_ENABLED` | `true` | Enable OpenTelemetry tracing |

Full list in [.env.example](.env.example).  Cloud-specific settings in
`config/aws.yaml`, `config/gcp.yaml`, `config/azure.yaml`.

---

## Project Structure

```
├── app/                    # FastAPI OCR service
│   ├── main.py             # App entry point + lifespan hooks
│   ├── config.py           # Pydantic settings (env + YAML)
│   ├── api/                # Route handlers + ML inference client
│   ├── kafka/              # Producer + consumer
│   ├── storage/            # Local / S3 / GCS / ADLS backends
│   ├── database/           # MongoDB helpers
│   ├── cache/              # Redis array store
│   ├── image/              # OCR preprocessing transforms
│   └── observability/      # OpenTelemetry + Prometheus metrics
├── ml_service/             # ML inference microservice
│   ├── main.py             # FastAPI app
│   └── model.py            # Tesseract OCR wrapper
├── config/                 # Per-environment YAML configs
├── monitoring/             # Prometheus + Grafana + OTEL configs
├── tests/                  # pytest test suite
├── docker-compose.yml      # Local stack
├── Dockerfile              # OCR service image
├── Dockerfile.ml_service   # ML service image
└── ARCHITECTURE.md         # System design + trade-offs
```
