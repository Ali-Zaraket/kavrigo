# kavrigo-engine

Quant, data and agent services, plus the domain contracts every other repository depends on.

## Layout

```text
libs/domain/          Pydantic domain contracts — the shared vocabulary
libs/data-contracts/  Protobuf wire contracts for the Redpanda event bus
services/engine-worker/  worker skeleton; real services land here
tests/property/       Hypothesis invariants for money, risk and identity
```

## Contracts

`libs/domain` encodes the non-negotiable domain rules structurally rather than by convention:

| Rule (`AGENTS.md`) | Where it lives |
|---|---|
| Money and quantity are exact decimals with units | `money.ExactDecimal`, `Money`, `Quantity`, `Price` |
| Instruments are explicit, never bare tickers | `identifiers.InstrumentId` |
| A model output is a proposal, never an order | `decision.AgentDecision`, `decision.ProposedAction` |
| Only deterministic risk produces an approval | `risk.RiskEvaluation`, `orders.ApprovedOrderIntent` |
| `UNKNOWN` and `NO_TRADE` are successful outcomes | `decision.DecisionState`, `ProposedAction` |
| Data freshness is a risk input | `snapshot.FreshnessReport`, `risk.FreshnessPolicy` |
| Every run references immutable versions | `agent.AgentVersion`, `audit.AuditRecord` |
| Untrusted content is data, not instruction | `evidence.EvidenceItem`, `events.SourceKind` |

Every model is frozen and rejects unknown fields, so an unvalidated provider payload or model
response cannot enter the domain unnoticed.

## Services not yet built

`market-ingestion`, `feature-engine`, `news-intelligence`, `agent-runtime`, `portfolio-engine`,
`risk-engine`, `backtest-service`, `paper-broker`, `reconciliation`
(`MASTER_BUILD_SPEC.md` §17). They are added in the order given by `AGENTS.md` § First build
sequence, each behind the contracts above.

Nothing in this repository holds an exchange credential or reaches a venue. Paper execution will
be simulated by the paper broker; live execution belongs to the separate
`kavrigo-execution-security` boundary.
