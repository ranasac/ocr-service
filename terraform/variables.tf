variable "aws_region" {
  description = "AWS region to deploy all resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment label (dev | staging | prod)."
  type        = string
  default     = "dev"
}

variable "cluster_name" {
  description = "Name of the EKS cluster."
  type        = string
  default     = "ocr-service-cluster"
}

variable "cluster_version" {
  description = "Kubernetes version to run on EKS."
  type        = string
  default     = "1.30"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

# ── Node groups ───────────────────────────────────────────────────────────────

variable "general_node_instance_types" {
  description = "EC2 instance types for general workloads (ocr-service, consumer, Kafka, MongoDB, Redis)."
  type        = list(string)
  default     = ["t3.medium"]
}

variable "general_node_min" {
  description = "Minimum number of general-purpose nodes."
  type        = number
  default     = 2
}

variable "general_node_max" {
  description = "Maximum number of general-purpose nodes (Cluster Autoscaler upper bound)."
  type        = number
  default     = 10
}

variable "general_node_desired" {
  description = "Initial desired number of general-purpose nodes."
  type        = number
  default     = 2
}

variable "ml_node_instance_types" {
  description = "EC2 instance types for ML inference pods (Tesseract is CPU-bound; c5.xlarge = 4 vCPU)."
  type        = list(string)
  default     = ["c5.xlarge"]
}

variable "ml_node_min" {
  description = "Minimum number of ML inference nodes (keep ≥1 to avoid cold starts)."
  type        = number
  default     = 1
}

variable "ml_node_max" {
  description = "Maximum number of ML inference nodes."
  type        = number
  default     = 10
}

variable "ml_node_desired" {
  description = "Initial desired number of ML inference nodes."
  type        = number
  default     = 1
}

# ── Application secrets ───────────────────────────────────────────────────────

variable "mongodb_root_password" {
  description = "MongoDB root password (injected into K8s Secret and Helm values)."
  type        = string
  sensitive   = true
}

variable "redis_password" {
  description = "Redis auth password. Leave empty string to disable Redis AUTH."
  type        = string
  sensitive   = true
  default     = ""
}
