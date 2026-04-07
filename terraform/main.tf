terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.27"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
  }

  # Uncomment to store state in S3 (recommended for teams):
   backend "s3" {
     bucket         = "sr-ocr-service"
     key            = "ocr-service/terraform.tfstate"
     region         = "us-east-1"
     dynamodb_table = "terraform-state-locks"
     encrypt        = true
   }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "ocr-service"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

# EKS providers authenticate via the AWS CLI (aws eks get-token).
# Requires: aws eks update-kubeconfig --region <region> --name <cluster>
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--region", var.aws_region]
    }
  }
}
