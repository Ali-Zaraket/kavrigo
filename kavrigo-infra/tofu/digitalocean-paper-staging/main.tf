terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "= 2.104.0"
    }
  }

  # Configure a separately reviewed encrypted, versioned, locked remote state at init.
  backend "s3" {}
}

provider "digitalocean" {}

locals {
  name = "kavrigo-paper-staging"
}

resource "digitalocean_vpc" "paper" {
  name        = local.name
  region      = var.region
  description = "Kavrigo paper-only staging"
}

# This provider resource is marked Private Preview. Verify account eligibility before apply.
resource "digitalocean_vpc_nat_gateway" "paper" {
  name   = "${local.name}-nat"
  type   = "PUBLIC"
  region = var.region
  size   = var.nat_size

  vpcs {
    vpc_uuid        = digitalocean_vpc.paper.id
    default_gateway = true
  }
}

resource "digitalocean_container_registry" "paper" {
  name                   = var.registry_name
  subscription_tier_slug = var.registry_tier
  region                 = var.registry_region
}

resource "digitalocean_kubernetes_cluster" "paper" {
  name                 = local.name
  region               = var.region
  version              = var.kubernetes_version
  vpc_uuid             = digitalocean_vpc.paper.id
  isolated_workers     = true
  ha                   = true
  auto_upgrade         = true
  registry_integration = true

  control_plane_firewall {
    enabled           = true
    allowed_addresses = var.operator_cidrs
  }

  node_pool {
    name       = "paper-apps"
    size       = var.node_size
    node_count = var.node_count
  }

  depends_on = [digitalocean_vpc_nat_gateway.paper, digitalocean_container_registry.paper]
}

resource "digitalocean_database_cluster" "postgres" {
  name                 = "${local.name}-pg"
  engine               = "pg"
  version              = "18"
  size                 = var.database_size
  region               = var.region
  node_count           = var.postgres_node_count
  private_network_uuid = digitalocean_vpc.paper.id
}

resource "digitalocean_database_firewall" "postgres" {
  cluster_id = digitalocean_database_cluster.postgres.id

  rule {
    type  = "k8s"
    value = digitalocean_kubernetes_cluster.paper.id
  }
}

resource "digitalocean_database_cluster" "valkey" {
  name                 = "${local.name}-valkey"
  engine               = "valkey"
  version              = "8"
  size                 = var.database_size
  region               = var.region
  node_count           = var.valkey_node_count
  private_network_uuid = digitalocean_vpc.paper.id
}

resource "digitalocean_database_firewall" "valkey" {
  cluster_id = digitalocean_database_cluster.valkey.id

  rule {
    type  = "k8s"
    value = digitalocean_kubernetes_cluster.paper.id
  }
}
