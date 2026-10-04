output "cluster_name" {
  value = aws_eks_cluster.paper.name
}

output "cluster_arn" {
  value = aws_eks_cluster.paper.arn
}

output "ecr_repository_urls" {
  value = { for name, repo in aws_ecr_repository.service : name => repo.repository_url }
}
