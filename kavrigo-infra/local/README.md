# Local development stack

```bash
make setup   # Python virtualenv + workspace packages
make up      # start the stack
make test    # unit + property tests (no stack required)
make down    # stop
```

Host ports sit in a 5xxxx range specific to this stack, because a developer machine commonly
already runs a PostgreSQL on 5432 or a Redis on 6379 for another project.

| Service | Local endpoint | Production equivalent |
|---|---|---|
| PostgreSQL | `localhost:55432` | Aurora PostgreSQL (ADR 0007) |
| Redpanda (Kafka API) | `localhost:59092` | Redpanda Cloud Dedicated/BYOC (ADR 0006) |
| Redpanda Schema Registry | `localhost:58081` | Redpanda Cloud schema registry |
| ClickHouse | `localhost:58123` | ClickHouse Cloud (ADR 0008) |
| Valkey | `localhost:56379` | ElastiCache for Valkey |
| Temporal | `localhost:57233`, UI `localhost:58233` | Temporal Cloud (ADR 0009) |
| Control-plane API | `localhost:58000`, docs `/docs` | EKS Auto Mode (ADR 0015) |

If the API port is occupied or falls inside a Windows excluded TCP range, set
`KAVRIGO_API_HOST_PORT` to an available port before running Compose. The default remains
58000; container-to-container traffic stays on 8000. For the 2026-09-09 Windows destination,
58000 was excluded and 58300 was verified:

```powershell
$env:KAVRIGO_API_HOST_PORT='58300'
docker compose -f kavrigo-infra/local/docker-compose.yml up -d --wait
```

Use `http://localhost:58300/healthz` for that override and set it again for subsequent Compose
commands in a new shell. This uses official [Compose interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
(verified 2026-09-09); no Windows reserved ranges or unrelated services need changing.

## Database roles

Two roles, and the split is what makes row-level security meaningful:

| Role | Used for | Privileges |
|---|---|---|
| `kavrigo` | migrations, test cleanup | owns the tables |
| `kavrigo_app` | **the application** | DML only; not a superuser, not the owner, no BYPASSRLS |

A superuser or a `BYPASSRLS` role ignores every policy silently. An application connecting as
one would pass an isolation test while providing no isolation at all.

## What is deliberately absent

- **No exchange credentials, and no path to a venue.** The execution boundary does not exist in
  this repository yet (`kavrigo-execution-security/README.md`).
- **No external provider keys.** `make test` passes with every provider variable unset; provider
  adapters are added behind interfaces with mocks (`AGENTS.md` § First build sequence step 5).
- **No model API key.** The model gateway defaults to a mock provider.

`LIVE_TRADING_ENABLED=false` is set on every service, and both the API and the worker refuse to
start if it is true (ADR 0001).

## Notes

- Local image tags are pinned but are development approximations of the managed services. Verify
  behaviour against the managed service before staging — notably Aurora, ClickHouse Cloud and
  Temporal Cloud differ from their local counterparts in ways that matter (connection limits,
  replication, namespace configuration).
- Valkey runs with persistence disabled on purpose: it is ephemeral cache and coordination only,
  never the authoritative order or position store.
- The PostgreSQL bootstrap enables row-level security on the example tenant-scoped table and
  forces it, so the pattern is established before there is a schema worth protecting. RLS is
  defence in depth; the backend must still scope every query.
- The ClickHouse TTLs are placeholders. Real retention follows each data provider's licence
  terms (`MASTER_BUILD_SPEC.md` §8.3), which are a launch blocker rather than a config detail.

## Durable worker and isolated integration tests

Step 13 registers four Temporal business workflows. See
[durable workflow operations](../../docs/product/durable-workflows.md) for run creation,
workspace dispatch configuration, lease recovery and limits. Migration `0002` owns the five
`engine_*` tables; API ORM autogeneration intentionally excludes these explicitly managed tables.
The Temporal server persists its local SQLite store under `/home/temporal` in a named volume.
Keep that volume and PostgreSQL data when restarting containers.

Integration tests must use a disposable database. API fixtures truncate the configured database
with dependent tables, so do not point either test DSN at the application database. Defaults
are `kavrigo_test`; create it and migrate it independently:

```bash
docker compose -f kavrigo-infra/local/docker-compose.yml exec postgres createdb -U kavrigo kavrigo_test
export TEST_POSTGRES_DSN=postgresql+asyncpg://kavrigo_app:kavrigo_local_dev@localhost:55432/kavrigo_test
export TEST_POSTGRES_OWNER_DSN=postgresql+asyncpg://kavrigo:kavrigo_local_dev@localhost:55432/kavrigo_test
export POSTGRES_MIGRATION_DSN="$TEST_POSTGRES_OWNER_DSN"
make migrate
export TEST_TEMPORAL_ADDRESS=localhost:57233
make test-integration
```

This example creates a new test database once; do not drop existing databases to repeat it.
The 2026-09-10 Windows verification uses `kavrigo_step13_test` through explicit test DSNs.
