# Paper deployment images

`web.Dockerfile` produces the Next.js standalone server. `python.Dockerfile` has `api` and
`worker` targets. Both base images are pinned to immutable manifest digests; refresh them
through a reviewed dependency update. These are **build candidates**, not signed or promoted
release images. The web runtime includes Next.js static assets and the public font-license
notice. Build from the repository root.

The Python build stage uses the locked workspace dependencies on Debian 13. Its final API and
worker stages use the official Debian 13 distroless Python 3.13 runtime, with no shell or build
tools. The venv is created through the runtime's `/usr/bin/python` path, and CI smoke-imports
both candidates as UID 10001 with a read-only filesystem before scanning their final layers.
The pinned runtime is refreshed only after ABI, smoke, and final-image vulnerability checks.
The [2026-10-09 CI run](https://github.com/Ali-Zaraket/kavrigo/actions/runs/37983068033)
passed the read-only runtime smoke but **failed** the API final-image scan on high-severity
Debian 13 Python/Expat/ncurses findings with no fixed version reported by Trivy. This image is
not eligible for signing or promotion. A different maintained runtime or documented,
independently reviewed vulnerability disposition is required; the CI gate remains blocking.

For a local smoke image that never contains a Clerk secret:

```text
docker build -f kavrigo-infra/images/web.Dockerfile --target runtime \
  --build-arg KAVRIGO_ENV=local --build-arg KAVRIGO_WEB_AUTH_PROVIDER=dev \
  --build-arg KAVRIGO_WEB_ORIGIN=http://localhost:3000 -t kavrigo-web:local .
docker build -f kavrigo-infra/images/python.Dockerfile --target api -t kavrigo-api:candidate .
docker build -f kavrigo-infra/images/python.Dockerfile --target worker -t kavrigo-worker:candidate .
```

For a **staging** web image, use an owned HTTPS origin and matching production Clerk instance:

```text
docker build -f kavrigo-infra/images/web.Dockerfile --target runtime \
  --build-arg KAVRIGO_ENV=staging --build-arg KAVRIGO_WEB_AUTH_PROVIDER=clerk \
  --build-arg KAVRIGO_WEB_ORIGIN=https://app.example.com \
  --build-arg NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY \
  --secret id=clerk_secret_key,env=CLERK_SECRET_KEY \
  -t <private-registry>/kavrigo-web:<source-sha> .
```

Replace `app.example.com` with the owned hostname. Set the
`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` environment variables through a
secure operator/CI secret store before running the command; do not put values in terminal
arguments or source files. `CLERK_SECRET_KEY` is required during Next.js build validation and
again at **runtime**. Never pass it as `--build-arg`; never write it to a file in the build
context. The publishable key is public but baked into the client bundle. Rebuild if the Clerk
instance or web origin changes. `KAVRIGO_ENV` must be explicit; the build rejects a staging
image with `pk_test_`/`sk_test_` keys or an HTTP origin. The runtime must receive the same
`KAVRIGO_ENV`, `KAVRIGO_WEB_AUTH_PROVIDER`, `KAVRIGO_WEB_ORIGIN`, and publishable key, plus a
restricted `CLERK_SECRET_KEY` and API connection settings.

Before a release, generate and retain an SBOM, scan the final images, sign their immutable
digests, push only to the reviewed private registry, and deploy by digest. Registry credentials
must be short-lived or separately rotated; do not embed them in image layers or GitHub Actions
source. The worker still refuses nonlocal operation pending hosted Temporal transport and
paper-run security checks, so these Dockerfiles alone do **not** make the app deployable.
