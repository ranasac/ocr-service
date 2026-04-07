# All in-cluster dependencies are installed via Helm.
# Apply order is enforced by depends_on — EKS must be ready first,
# then infrastructure charts (Kafka, mongo, redis), then the KEDA operators.

# ── metrics-server ────────────────────────────────────────────────────────────
# Required by KEDA's CPU utilisation trigger and by kubectl top.
resource "helm_release" "metrics_server" {
  name       = "metrics-server"
  repository = "https://kubernetes-sigs.github.io/metrics-server/"
  chart      = "metrics-server"
  namespace  = "kube-system"
  version    = "3.12.1"

  set {
    name  = "args[0]"
    value = "--kubelet-insecure-tls"
  }

  depends_on = [module.eks]
}

# ── KEDA ──────────────────────────────────────────────────────────────────────
# Event-driven autoscaler. Reads Kafka lag and Prometheus metrics to drive HPA.
# ScaledObject manifests are in k8s/keda-scaledobject.yaml and
# k8s/ml-service-scaledobject.yaml — apply those after the app is deployed.
resource "helm_release" "keda" {
  name       = "keda"
  repository = "https://kedacore.github.io/charts"
  chart      = "keda"
  namespace  = "keda"
  version    = "2.14.0"

  create_namespace = true

  depends_on = [module.eks]
}

# ── Kafka (Bitnami — KRaft, single broker) ────────────────────────────────────
# KRaft removes the ZooKeeper dependency.
# Internal service: kafka:9092  (update KAFKA_BOOTSTRAP_SERVERS in ConfigMap)
# Partitions on ocr.images: 8  (matches maxReplicaCount in keda-scaledobject.yaml)
resource "helm_release" "kafka" {
  name       = "kafka"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "kafka"
  namespace  = "default"
  version    = "29.3.5"

  values = [
    yamlencode({
      kraft = { enabled = true }
      replicaCount       = 1
      controller         = { replicaCount = 1 }
      listeners = {
        client     = { protocol = "PLAINTEXT" }
        controller = { protocol = "PLAINTEXT" }
      }
      persistence = { size = "10Gi" }
      # Pre-create topics on first boot
      provisioning = {
        enabled = true
        topics = [
          {
            name              = "ocr.images"
            partitions        = 8
            replicationFactor = 1
            config            = { "retention.ms" = "604800000" }  # 7 days
          },
          {
            name              = "ocr.images.dlq"
            partitions        = 1
            replicationFactor = 1
          },
          {
            name              = "_schemas"  # required by Schema Registry
            partitions        = 1
            replicationFactor = 1
            config            = { "cleanup.policy" = "compact" }
          }
        ]
      }
    })
  ]

  depends_on = [module.eks]
}

# ── Confluent Schema Registry ─────────────────────────────────────────────────
# Stores and enforces Protobuf schemas. BACKWARD compatibility means new
# consumers can always read messages written by the previous schema version.
# Internal service: schema-registry-cp-schema-registry:8081
resource "helm_release" "schema_registry" {
  name       = "schema-registry"
  repository = "https://confluentinc.github.io/cp-helm-charts/"
  chart      = "cp-schema-registry"
  namespace  = "default"
  version    = "0.6.0"

  values = [
    yamlencode({
      replicaCount = 1
      kafka = {
        bootstrapServers = "PLAINTEXT://kafka:9092"
      }
      configurationOverrides = {
        "schema.compatibility.level" = "BACKWARD"
      }
    })
  ]

  depends_on = [helm_release.kafka]
}

# ── MongoDB (Bitnami — standalone) ────────────────────────────────────────────
# Stores image metadata (image_id, status, OCR results).
# Internal service: mongodb:27017
resource "helm_release" "mongodb" {
  name       = "mongodb"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "mongodb"
  namespace  = "default"
  version    = "15.6.22"

  values = [
    yamlencode({
      architecture = "standalone"
      auth = {
        enabled      = true
        rootPassword = var.mongodb_root_password
        databases    = ["ocr_service"]
        usernames    = ["ocr_user"]
        passwords    = [var.mongodb_root_password]
      }
      persistence = { size = "20Gi" }
    })
  ]

  depends_on = [module.eks]
}

# ── Redis (Bitnami — standalone) ──────────────────────────────────────────────
# Stores preprocessed image arrays (1h TTL) and idempotency locks (10min TTL).
# Internal service: redis-master:6379
resource "helm_release" "redis" {
  name       = "redis"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "redis"
  namespace  = "default"
  version    = "19.6.4"

  values = [
    yamlencode({
      architecture = "standalone"
      auth = {
        enabled  = var.redis_password != ""
        password = var.redis_password
      }
      master = {
        persistence = { size = "5Gi" }
      }
    })
  ]

  depends_on = [module.eks]
}

# ── kube-prometheus-stack (Prometheus + Grafana + Alertmanager) ───────────────
# Prometheus in-cluster URL for KEDA ScaledObjects:
#   http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090
#
# Grafana is exposed via a LoadBalancer service (see grafana.service below).
# Import the existing dashboard from monitoring/grafana/dashboards/ocr_service.json.
resource "helm_release" "prometheus_stack" {
  name       = "prometheus"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  namespace  = "monitoring"
  version    = "58.7.2"

  create_namespace = true

  values = [
    yamlencode({
      grafana = {
        adminPassword = "admin"  # override in production via secrets manager
        service       = { type = "LoadBalancer" }
        sidecar = {
          dashboards = { enabled = true, label = "grafana_dashboard" }
        }
      }
      prometheus = {
        prometheusSpec = {
          additionalScrapeConfigs = [
            {
              job_name       = "ocr-service"
              static_configs = [{ targets = ["ocr-service:8000"] }]
              metrics_path   = "/metrics"
            },
            {
              job_name       = "ml-service"
              static_configs = [{ targets = ["ocr-ml-service:8001"] }]
              metrics_path   = "/metrics"
            },
            {
              job_name       = "kafka-exporter"
              static_configs = [{ targets = ["kafka-exporter:9308"] }]
            }
          ]
        }
      }
    })
  ]

  depends_on = [module.eks]
}

# ── OpenTelemetry Collector ───────────────────────────────────────────────────
# Receives OTLP traces from ocr-service and ml-service; forwards to Tempo.
# Internal OTLP/gRPC endpoint: http://opentelemetry-collector:4317
resource "helm_release" "otel_collector" {
  name       = "opentelemetry-collector"
  repository = "https://open-telemetry.github.io/opentelemetry-helm-charts"
  chart      = "opentelemetry-collector"
  namespace  = "monitoring"
  version    = "0.97.0"

  create_namespace = true

  values = [
    yamlencode({
      mode = "deployment"
      config = {
        receivers = {
          otlp = {
            protocols = {
              grpc = { endpoint = "0.0.0.0:4317" }
              http = { endpoint = "0.0.0.0:4318" }
            }
          }
        }
        exporters = {
          otlp = {
            endpoint = "tempo:4317"
            tls      = { insecure = true }
          }
        }
        service = {
          pipelines = {
            traces = {
              receivers  = ["otlp"]
              exporters  = ["otlp"]
            }
          }
        }
      }
    })
  ]

  depends_on = [helm_release.prometheus_stack]
}
