terraform {
  # The operator supplies TF_ENCRYPTION at runtime. Without it, state and
  # plans must not be written, regardless of backend-side encryption.
  encryption {
    state {
      enforced = true
    }

    plan {
      enforced = true
    }
  }
}
