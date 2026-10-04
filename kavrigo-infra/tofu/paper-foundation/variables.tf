variable "environment" {
  description = "Paper-only environment; live production is intentionally unsupported."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "paper-prod"], var.environment)
    error_message = "Environment must be dev, staging, or paper-prod."
  }
}

variable "aws_region" {
  description = "Region chosen after data-residency and operating-entity review."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "Supply an AWS region such as us-east-1."
  }
}

variable "kubernetes_version" {
  description = "An EKS-supported standard-support Kubernetes version, confirmed before apply."
  type        = string
}

variable "private_subnet_ids" {
  description = "At least two private EKS subnets in distinct availability zones, with egress or required VPC endpoints."
  type        = list(string)

  validation {
    condition = length(var.private_subnet_ids) >= 2 && alltrue([
      for id in var.private_subnet_ids : can(regex("^subnet-[0-9a-f]+$", id))
    ])
    error_message = "Provide at least two private subnet IDs."
  }
}

variable "operator_role_arn" {
  description = "Existing tightly controlled IAM role granted initial cluster administration. Never a CI role."
  type        = string

  validation {
    condition     = can(regex("^arn:aws(-[a-z]+)?:iam::[0-9]{12}:role/.+$", var.operator_role_arn))
    error_message = "Provide an existing IAM role ARN."
  }
}
