terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.66.0"
    }
  }

  # Supply a distinct, versioned, encrypted S3 bucket/key per environment at init time.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = "kavrigo"
      Environment = var.environment
      ManagedBy   = "opentofu"
      TradingMode = "paper"
    }
  }
}

data "aws_partition" "current" {}

locals {
  name = "kavrigo-${var.environment}"
  cluster_policies = toset([
    "AmazonEKSClusterPolicy",
    "AmazonEKSComputePolicy",
    "AmazonEKSBlockStoragePolicyV2",
    "AmazonEKSLoadBalancingPolicy",
    "AmazonEKSNetworkingPolicy",
  ])
  node_policies = toset([
    "AmazonEKSWorkerNodeMinimalPolicy",
    "AmazonEC2ContainerRegistryPullOnly",
  ])
}

data "aws_iam_policy_document" "cluster_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${local.name}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.cluster_trust.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  for_each   = local.cluster_policies
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.value}"
}

data "aws_iam_policy_document" "node_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${local.name}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.node_trust.json
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each   = local.node_policies
  role       = aws_iam_role.node.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/${each.value}"
}

resource "aws_eks_cluster" "paper" {
  name     = local.name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }

  bootstrap_self_managed_addons = false
  enabled_cluster_log_types     = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  compute_config {
    enabled       = true
    node_pools    = ["general-purpose", "system"]
    node_role_arn = aws_iam_role.node.arn
  }

  kubernetes_network_config {
    elastic_load_balancing {
      enabled = true
    }
  }

  storage_config {
    block_storage {
      enabled = true
    }
  }

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = false
  }

  depends_on = [
    aws_iam_role_policy_attachment.cluster,
    aws_iam_role_policy_attachment.node,
  ]
}

resource "aws_eks_access_entry" "operator" {
  cluster_name  = aws_eks_cluster.paper.name
  principal_arn = var.operator_role_arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "operator" {
  cluster_name  = aws_eks_cluster.paper.name
  principal_arn = aws_eks_access_entry.operator.principal_arn
  policy_arn    = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

resource "aws_ecr_repository" "service" {
  for_each             = toset(["api", "worker", "web"])
  name                 = "${local.name}/${each.value}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
  }
}
