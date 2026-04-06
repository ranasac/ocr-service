"""Application configuration using Pydantic Settings with YAML config file support.

Priority order (highest to lowest):
  1. Environment variables
  2. .env file
  3. YAML config file (selected via APP_ENV)
  4. Defaults
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_yaml_config(env: str) -> dict:
    """Load YAML config file for the given environment."""
    config_path = Path(__file__).parent.parent / "config" / f"{env}.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


class KafkaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KAFKA_", extra="ignore")

    bootstrap_servers: str = "localhost:9092"
    image_topic: str = "ocr.images"
    consumer_group: str = "ocr-consumer-group"
    dlq_topic: str = "ocr.images.dlq"


class SchemaRegistrySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCHEMA_REGISTRY_", extra="ignore")

    url: str = "http://localhost:8081"
    # Optional basic-auth for hosted registries (Confluent Cloud, etc.)
    basic_auth_user_info: Optional[str] = None  # "key:secret"


class MongoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MONGODB_", extra="ignore")

    uri: str = "mongodb://localhost:27017"
    database: str = "ocr_service"


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    ssl: bool = False
    password: Optional[str] = None


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_", extra="ignore")

    backend: str = "local"  # local | s3 | gcs | adls
    local_path: str = "./images"

    # AWS S3
    s3_bucket: Optional[str] = None
    s3_region: str = "us-east-1"

    # GCS
    gcs_bucket: Optional[str] = None

    # Azure ADLS
    adls_account: Optional[str] = None
    adls_container: Optional[str] = None


class MLServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_SERVICE_", extra="ignore")

    url: str = "http://localhost:8001"
    timeout: int = 30


class OtelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OTEL_", extra="ignore")

    exporter_endpoint: str = "http://localhost:4317"
    service_name: str = "ocr-service"
    enabled: bool = True


class ImageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IMAGE_", extra="ignore")

    resize_width: int = 800
    resize_height: int = 800


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_env: str = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Sub-settings (can be overridden via env vars with prefix)
    kafka: KafkaSettings = KafkaSettings()
    schema_registry: SchemaRegistrySettings = SchemaRegistrySettings()
    mongodb: MongoSettings = MongoSettings()
    redis: RedisSettings = RedisSettings()
    storage: StorageSettings = StorageSettings()
    ml_service: MLServiceSettings = MLServiceSettings()
    otel: OtelSettings = OtelSettings()
    image: ImageSettings = ImageSettings()

    @field_validator("app_env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        valid = {"local", "aws", "gcp", "azure", "test"}
        if v not in valid:
            raise ValueError(f"app_env must be one of {valid}, got {v!r}")
        return v

    def model_post_init(self, __context) -> None:  # noqa: ANN001
        """Merge YAML config values (lowest priority) into sub-settings."""
        yaml_cfg = _load_yaml_config(self.app_env)
        if not yaml_cfg:
            return

        def _merge(sub_settings: BaseSettings, section: str) -> None:
            section_cfg = yaml_cfg.get(section, {})
            for key, value in section_cfg.items():
                # Only set if the env var is not already set
                attr = key.lower()
                if hasattr(sub_settings, attr):
                    env_key = (
                        sub_settings.model_config.get("env_prefix", "").lower() + attr
                    )
                    if not os.environ.get(env_key.upper()):
                        try:
                            object.__setattr__(sub_settings, attr, value)
                        except Exception:
                            pass

        _merge(self.kafka, "kafka")
        _merge(self.schema_registry, "schema_registry")
        _merge(self.mongodb, "mongodb")
        _merge(self.redis, "redis")
        _merge(self.storage, "storage")
        _merge(self.ml_service, "ml_service")
        _merge(self.otel, "otel")
        _merge(self.image, "image")


@lru_cache
def get_settings() -> Settings:
    return Settings()
