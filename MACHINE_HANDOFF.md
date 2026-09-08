# Resume Kavrigo on another machine

Prepared 2026-09-08 after the user stopped implementation for a machine transfer.
This file, `HANDOFF.md`, `HANDOFF_PROMPT.md` and Git history are the portable project memory.
No account memory or previous chat is required. No background build is intended to continue.

## Checkpoint

- Branch: `main`; no remote or push. Latest implementation: `c46b315` (step 10).
- Step 8: `a77d1db`, provider-neutral model gateway with local mock calls, exact budgets,
  structured validation and metadata traces. No paid provider adapter.
- Step 9: `3abe65d`, synthetic news feeds, dedupe, injection-aware extraction and frozen evidence.
- Step 10: `c46b315`, frozen agent evaluation, structured decisions and inert portfolio proposals.
- Next: verify the destination stack, then step 11 deterministic risk. No step 11 code was written.
- Existing carry-overs include real market transport, durable stores, meaningful Nautilus strategy
  and BTC/ETH backtest wiring, provider rights, hosted integrations, and steps 11–15. See
  `HANDOFF.md` §5 for scope and reasons; the product milestone is not yet complete.

## Transfer and restore

The transfer archive contains `kavrigo.bundle` (committed source and reachable Git history),
these handoff documents, an environment-version reference and checksums. It excludes `.venv`,
Docker images/cache/volumes, databases, ignored datasets, local secrets and chat history.
Keep a copy outside the old machine before wiping it.

Unzip the archive into a directory on the destination machine. With Git installed, run there:

```bash
git clone kavrigo.bundle kavrigo
cd kavrigo
git remote remove origin
git log -4 --oneline
git status --short
```

Cloning a bundle sets `origin` to the bundle file; removing that local-file remote prevents
mistaking it for a hosted repository. Configure a real remote only when one is provisioned.
The bundle should clone without any pre-existing repository. Its exact HEAD and SHA-256 are
recorded in the transfer archive's `TRANSFER_MANIFEST.json` and `SHA256SUMS`.

Install/enable Git, Make, Python **3.13** and Docker Engine with Compose v2 (Docker Desktop on
macOS/Windows). The source machine used Python 3.13.5 on macOS arm64; container builds used
Python 3.13.11. Recreate the virtualenv on the destination; do not copy architecture-specific
Python packages. `make setup` uses `uv` if already installed and otherwise uses venv/pip.
Tool installation remains a human action as recorded in `HANDOFF.md` §11.

There is no committed `uv.lock`. `ENVIRONMENT_VERSIONS.txt` is a diagnostic reference from the
source host, not a portable dependency lock or an instruction to install editable source paths.
Dependency resolution and architecture compatibility must be verified on the new machine.

From the cloned repository, with Docker running:

```bash
make setup
make compose-validate
make check
make up && make migrate
make test-integration
```

`make up` rebuilds the API and worker and pulls the infrastructure images. The first build can
take a while. Migrations run with the owner role; the API uses the separate RLS-constrained role.
No model, exchange or news provider key is needed. Keep `LIVE_TRADING_ENABLED=false`,
`DEFAULT_TRADING_MODE=paper`, `KAVRIGO_ENV=local` and `AUTH_PROVIDER=dev` for local development.
Compose provides local defaults; `.env.example` is a reference, not a secret backup.

Verify services with `docker compose -f kavrigo-infra/local/docker-compose.yml ps` and the API
at `http://localhost:58000/healthz`. Integration tests skip if databases are unreachable, so
check the actual test summary: the final stack verification requires **50 integration passes**,
not skips. Open this repository in the coding agent and use `HANDOFF_PROMPT.md` to resume.

## Docker persistence and endpoints

The Compose project is `kavrigo`, defined in `kavrigo-infra/local/docker-compose.yml`.

| Service | Host port(s) | Persistence in this Compose configuration |
|---|---|---|
| PostgreSQL 18 | 55432 | Named `postgres-data`, mounted at `/var/lib/postgresql` |
| ClickHouse | 58123 HTTP, 59000 native | Named `clickhouse-data` |
| Redpanda | 59092 Kafka, 58081 schema registry, 58082 proxy | No persistent volume configured |
| Temporal dev | 57233 gRPC, 58233 UI | No persistent volume configured |
| Valkey | 56379 | Persistence deliberately disabled |
| API | 58000 | Authoritative state resides in PostgreSQL |
| Engine worker | None | Skeleton; no durable workflow or collector is configured |

Compose normally prefixes the named volumes with `kavrigo_`; inspect actual names before any
backup or restore. These volumes remain on the source machine and are **not** in this transfer.
No database backup or restore was performed or verified because its Docker daemon was unreachable.
A fresh stack initializes databases and the fixture-based tests can then run. Existing local
agents, versions and stored market rows require a separate verified data export/restore if wanted.
Do not erase the source volumes until any required data has been recovered.

Use `make down` to stop/remove this stack while retaining named database volumes. Do not use
`make clean-volumes`, `down -v` or volume pruning as a transfer step. Do not treat Docker's VM
disk file as a verified portable database backup. Database volume preservation does not preserve
ephemeral Redpanda/Temporal state or make the in-memory gateway/news/runtime ledgers durable.

## Exact verification at pause

- Final step 10 `make check`: **680 passed, 50 skipped**; ruff/format clean on 206 files and
  `mypy --strict` clean on 99 source files. Database integrations skipped because Docker was down.
- Separate `.venv/bin/python -m pytest -m 'not integration'`: **680 passed, 50 deselected**.
- Final step 10 `make up && make migrate && make test-integration`: `make up` stalled and was
  cancelled; the chained migration and integration commands did not execute.
- Earlier step 9: `make check` **676 passed**, and `make up && make migrate && make test-integration`
  completed with both images built, migrations applied and **50 integration tests passed**.
- This machine-transfer change is documentation/artifact work only. Full application tests were
  not repeated for it. Bundle integrity and a clean clone are checked separately in the manifest.

## Source-machine Docker incident and cleanup

Docker host logs recorded disk-space errors at 11:10 UTC on 2026-09-08 and a graceful VM stop
at 11:15 UTC. Later disk inspection showed 15 GiB free. Normal Desktop restart timed out.
With explicit user approval, stuck Docker processes were force-quit and Desktop restarted;
the VM logged startup at 13:27:55 UTC, but Docker's daemon remained unreachable. This is a
source-machine infrastructure problem, not a verified diagnosis of an application failure.

The user subsequently requested image deletion and Docker pruning after the handoff. The
requested cleanup retains volumes. Its exact outcome is recorded in `DOCKER_CLEANUP.txt` in
the transfer archive. The cleanup commands, to run on the **source machine**, are:

```bash
docker compose -f kavrigo-infra/local/docker-compose.yml down --rmi all --timeout 15
docker system prune --all --force
```

The second command is daemon-wide: it removes stopped containers, unused networks/images and
build cache, including unused resources from other projects. It does not stop unrelated running
containers. No `--volumes` flag is used. Images can be rebuilt/pulled on the destination.
Do not rerun cleanup on the destination as part of setup.

Command behavior verified against installed CLI help and official documentation on 2026-09-08:
[Compose down](https://docs.docker.com/reference/cli/docker/compose/down/),
[system prune](https://docs.docker.com/reference/cli/docker/system/prune/), and
[Git bundle](https://git-scm.com/docs/git-bundle).
