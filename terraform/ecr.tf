resource "aws_ecr_repository" "ocr_service" {
  name                 = "ocr-service"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "ml_service" {
  name                 = "ml-service"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep last 10 images; older images are expired automatically to control storage costs.
resource "aws_ecr_lifecycle_policy" "ocr_service" {
  repository = aws_ecr_repository.ocr_service.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images older than 14 days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 14
      }
      action = { type = "expire" }
    },
    {
      rulePriority = 2
      description  = "Keep last 10 tagged images"
      selection = {
        tagStatus   = "tagged"
        tagPrefixList = ["v", "latest"]
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "ml_service" {
  repository = aws_ecr_repository.ml_service.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images older than 14 days"
      selection = {
        tagStatus   = "untagged"
        countType   = "sinceImagePushed"
        countUnit   = "days"
        countNumber = 14
      }
      action = { type = "expire" }
    },
    {
      rulePriority = 2
      description  = "Keep last 10 tagged images"
      selection = {
        tagStatus   = "tagged"
        tagPrefixList = ["v", "latest"]
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
