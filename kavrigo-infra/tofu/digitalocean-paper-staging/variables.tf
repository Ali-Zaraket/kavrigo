variable "region" {
  description = "First paper-only staging region."
  type        = string
  default     = "ams3"
}

variable "registry_region" {
  description = "Supported container-registry region; confirm current availability before plan."
  type        = string
  default     = "ams3"
}

variable "registry_name" {
  description = "Globally unique DigitalOcean container registry name on a dedicated/reviewed team."
  type        = string
}

variable "registry_tier" {
  description = "Review quota and recurring price before apply."
  type        = string
  default     = "basic"

  validation {
    condition     = contains(["basic", "professional"], var.registry_tier)
    error_message = "Use a paid private-registry tier reviewed for image retention."
  }
}

variable "kubernetes_version" {
  description = "Current DOKS version 1.36+ from account options; isolated workers require 1.36+."
  type        = string

  validation {
    condition     = can(regex("^1\\.(3[6-9]|[4-9][0-9])(\\.|$)", var.kubernetes_version))
    error_message = "Isolated workers require Kubernetes 1.36 or newer."
  }
}

variable "operator_cidrs" {
  description = "Named operator egress CIDRs for the public DOKS API; never 0.0.0.0/0."
  type        = list(string)

  validation {
    condition     = length(var.operator_cidrs) > 0 && alltrue([
      for cidr in var.operator_cidrs : can(cidrhost(cidr, 0)) && cidr != "0.0.0.0/0" && cidr != "::/0"
    ])
    error_message = "Supply at least one valid restricted operator CIDR."
  }
}

variable "nat_size" {
  description = "VPC NAT gateway size increment; review peak egress and cost."
  type        = string
  default     = "1"
}

variable "node_size" {
  description = "DOKS worker Droplet size; verify account/region options."
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "node_count" {
  description = "Worker count. Three nodes support basic staging failure-domain rehearsal."
  type        = number
  default     = 3

  validation {
    condition     = var.node_count >= 3
    error_message = "Paper staging requires at least three workers."
  }
}

variable "database_size" {
  description = "Managed PostgreSQL/Valkey size; verify both engine options in ams3."
  type        = string
  default     = "db-s-1vcpu-1gb"
}

variable "postgres_node_count" {
  description = "Use 2+ nodes for HA before any public paper release."
  type        = number
  default     = 1

  validation {
    condition     = var.postgres_node_count >= 1
    error_message = "PostgreSQL needs at least one node."
  }
}

variable "valkey_node_count" {
  description = "Ephemeral cache node count."
  type        = number
  default     = 1
}
