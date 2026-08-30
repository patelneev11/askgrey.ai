terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = var.tags
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name = var.name
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
  # The tasks' subnets: private only when a NAT gateway pays for their egress.
  task_subnet_ids      = var.private_tasks_with_nat ? aws_subnet.private[*].id : aws_subnet.public[*].id
  documents_prefix_arn = "arn:aws:s3:::${var.documents_bucket}/documents/*"
}
