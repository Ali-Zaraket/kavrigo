terraform {
  # The operator supplies TF_ENCRYPTION at runtime. Without it, state and plans
  # must not be written because DigitalOcean Spaces has no bucket-default SSE.
  encryption {
    state {
      enforced = true
    }

    plan {
      enforced = true
    }
  }
}
