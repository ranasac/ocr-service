output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint (sensitive — do not log)."
  value       = module.eks.cluster_endpoint
  sensitive   = true
}

output "kubeconfig_command" {
  description = "Run this command to update your local ~/.kube/config."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "ocr_service_ecr_url" {
  description = "ECR repository URL for ocr-service."
  value       = aws_ecr_repository.ocr_service.repository_url
}

output "ml_service_ecr_url" {
  description = "ECR repository URL for ml-service."
  value       = aws_ecr_repository.ml_service.repository_url
}

output "ecr_login_command" {
  description = "Authenticate Docker with ECR before pushing images."
  value       = "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.ocr_service.registry_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

output "build_and_push_commands" {
  description = "Commands to build and push both service images."
  value       = <<-EOT
    # ocr-service
    docker build -t ${aws_ecr_repository.ocr_service.repository_url}:latest .
    docker push ${aws_ecr_repository.ocr_service.repository_url}:latest

    # ml-service
    docker build -f Dockerfile.ml_service -t ${aws_ecr_repository.ml_service.repository_url}:latest .
    docker push ${aws_ecr_repository.ml_service.repository_url}:latest
  EOT
}
