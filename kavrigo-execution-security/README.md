# kavrigo-execution-security — boundary placeholder

**This directory intentionally contains no code.**

`MASTER_BUILD_SPEC.md` §17 and ADR [0017](../docs/adr/0017-kms-isolated-credential-service.md)
define this as a separate, access-restricted repository and deployment boundary holding:

```text
execution-gateway/     credential-service/    venue-adapters/
reconciliation/        signing/               security-tests/
threat-model/          CODEOWNERS
```

Work here does not start until:

1. the restricted GitHub repository exists, with access limited to `@kavrigo/execution-security`;
2. its threat model is written and reviewed;
3. the KMS/Secrets Manager design and IAM isolation are implemented in `kavrigo-infra`;
4. the live-execution readiness checklist (`MASTER_BUILD_SPEC.md` §47) is owned and tracked.

Until then, nothing in this repository may:

- hold or read exchange credentials,
- construct a venue order,
- or provide any path from an agent decision to a real venue.

`LIVE_TRADING_ENABLED=false`. Paper execution is simulated by the paper broker in
`kavrigo-engine`, which has no credential access and no venue connectivity.
