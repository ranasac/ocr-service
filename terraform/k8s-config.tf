# ConfigMap and Secret consumed by ocr-service, ocr-consumer, and ocr-ml-service pods.
# Values here match the K8s service names created by the Helm charts in helm.tf.

resource "kubernetes_config_map" "ocr_config" {
  metadata {
    name      = "ocr-config"
    namespace = "default"
  }

  data = {
    APP_ENV = var.environment

    # Bitnami Kafka service: release-name = "kafka", port = 9092 (intra-cluster plaintext)
    KAFKA_BOOTSTRAP_SERVERS = "kafka:9092"

    # Bitnami Redis: master service is always "<release-name>-master"
    REDIS_HOST = "redis-master"
    REDIS_PORT = "6379"
    REDIS_DB   = "0"

    # MongoDB: Bitnami service name = "<release-name>"
    MONGODB_DB = "ocr_service"

    # ml-service ClusterIP service defined in k8s/ml-service-deployment.yaml
    ML_SERVICE_URL = "http://ocr-ml-service:8001"

    # Confluent cp-helm-charts Schema Registry service name
    SCHEMA_REGISTRY_URL = "http://schema-registry-cp-schema-registry:8081"

    # OpenTelemetry Collector OTLP/gRPC endpoint (deployed in monitoring namespace)
    OTEL_EXPORTER_ENDPOINT = "http://opentelemetry-collector.monitoring.svc:4317"

    # Storage backend: set to "s3" to use S3, "local" for in-pod ephemeral storage.
    # For S3, also set STORAGE_S3_BUCKET and STORAGE_S3_REGION via environment variables.
    STORAGE_BACKEND = "local"
  }

  depends_on = [module.eks]
}

resource "kubernetes_secret" "ocr_secrets" {
  metadata {
    name      = "ocr-secrets"
    namespace = "default"
  }

  # The kubernetes provider base64-encodes values automatically.
  data = {
    MONGODB_URI    = "mongodb://ocr_user:${var.mongodb_root_password}@mongodb:27017/ocr_service"
    REDIS_PASSWORD = var.redis_password
  }

  depends_on = [module.eks]
}
