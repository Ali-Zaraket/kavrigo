output "region" {
  value = var.region
}

output "cluster_id" {
  value = digitalocean_kubernetes_cluster.paper.id
}

output "vpc_id" {
  value = digitalocean_vpc.paper.id
}

output "postgres_cluster_id" {
  value = digitalocean_database_cluster.postgres.id
}

output "valkey_cluster_id" {
  value = digitalocean_database_cluster.valkey.id
}

output "registry_endpoint" {
  value = digitalocean_container_registry.paper.endpoint
}
