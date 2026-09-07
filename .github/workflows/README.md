# CI workflows

`ci.yml` runs on every pull request and on `main`:

| Job | What it proves |
|---|---|
| `quality` | lint, strict typecheck, unit and property tests, and that the suite passes with every external provider key unset |
| `contracts` | Protobuf lints and does not break consumers |
| `security` | no secrets in history; no known critical/high vulnerabilities or misconfigurations |
| `codeql` | static security analysis |
| `build` | the compose stack is valid and both service images build |

## Not yet wired

Per `MASTER_BUILD_SPEC.md` §24.4 and §36, the main-branch pipeline also needs SBOM generation
(Syft), image signing (Cosign), provenance attestation, ECR push and the Argo CD manifest bump.
Those land with the deployment pipeline in `kavrigo-infra`. They are omitted rather than stubbed:
a signing step that signs nothing gives false assurance.

## Rules

- **No long-lived cloud credentials in CI.** Deployment uses GitHub OIDC to AWS (ADR 0016).
- **No provider or exchange credentials in CI.** The `quality` job asserts the suite passes
  without them.
- **`LIVE_TRADING_ENABLED` stays false.** A test requiring it to be true must not exist.
- Execution-sensitive components get a manual review gate before any live environment, with
  restricted `CODEOWNERS`.
