.PHONY: up down restart logs test test-cov lint infra dev-api dev-ml proto

# ── Protobuf ──────────────────────────────────────────────────────────────────

proto:
	python -m grpc_tools.protoc \
	    -I./proto \
	    --python_out=./proto \
	    proto/ocr_image.proto
	@echo "Generated proto/ocr_image_pb2.py"

# ── Docker Compose ────────────────────────────────────────────────────────────

up:
	docker-compose up --build -d

down:
	docker-compose down --remove-orphans

restart:
	docker-compose down --remove-orphans && docker-compose up --build -d

logs:
	docker-compose logs -f

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	uv run pytest -q

test-cov:
	uv run pytest --cov=app --cov-report=term-missing -q

# ── Local Development (infra only) ────────────────────────────────────────────

infra:
	docker-compose up kafka mongodb redis -d

dev-api:
	APP_ENV=local uv run uvicorn app.main:app --port 8000 --reload

dev-ml:
	uv run uvicorn ml_service.main:app --port 8001 --reload
