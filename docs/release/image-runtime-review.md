# Deployment image runtime review — 2026-10-10

**Decision: do not promote a candidate image.** The final-image HIGH/CRITICAL Trivy gate stays
blocking. A green source/lockfile scan and successful import smoke do not clear findings in the
runtime filesystem. Counts below are for the exact pinned images and vulnerability database used
by [CI run 64](https://github.com/Ali-Zaraket/kavrigo/actions/runs/37985383354); they can change
as the advisory database or image digests change. The run retained full JSON reports and
CycloneDX SBOMs in the `image-review-e318c619af9ee3e92877be1f10b13578dd7731e1` artifact.

| Candidate | Pinned runtime | CI HIGH/CRITICAL | Status |
|---|---|---:|---|
| API | `gcr.io/distroless/python3-debian13:nonroot@sha256:83aa8d4f74a4d7f7cf2d472054139bef71a927b76c680c0f2e1021d6b1d6d732` | 42 | Import smoke passed; release gate failed. |
| Worker | Same Python 3.13 runtime | 42 | Import smoke passed; release gate failed. |
| Web | `node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20` | 66 | Release gate failed. |

The official [distroless image catalog](https://github.com/GoogleContainerTools/distroless)
publishes Debian 13 Python 3 and Node 24 runtimes. Its current Python `:nonroot` manifest digest
was checked again on 2026-10-10 and matched the pinned digest. The web runtime is being trialed on
the official [distroless Node 24](https://github.com/GoogleContainerTools/distroless/blob/main/nodejs/README.md)
image, pinned by manifest digest in `web.Dockerfile`. [CI run 65](https://github.com/Ali-Zaraket/kavrigo/actions/runs/38043942589)
built it, but the read-only, non-root startup smoke failed. The public job summary contains only
an exit code, and that run stopped before scanning. The next run moves the smoke after report
collection and emits a bounded startup diagnostic; do not assume this runtime is viable yet.

Other runtime paths have material constraints:

- Docker's [Community hardened Python image](https://docs.docker.com/dhi/get-started/) is a
  candidate for a future authenticated trial, but `dhi.io` requires a Docker account login and
  a reviewed CI/cluster pull-credential flow. The image must still pass the same ABI, imports,
  read-only execution and final scan checks; a catalog description is not a scan result.
- The [official Node Alpine image](https://hub.docker.com/_/node) uses musl rather than glibc.
  Kavrigo's locked Next.js build includes native `sharp` assets, so switching only its final
  stage is not safe without a matching musl build and runtime test. The Python dependency set
  includes NautilusTrader's glibc wheels; a Python Alpine switch needs a separate ABI/dependency
  review.
- A vulnerability exception needs the exact image digest, package, CVE, exploitability evidence,
  compensating controls, owner, expiry and independent security approval. No blanket
  `--ignore-unfixed`, severity downgrade or scan disable is approved.

The next image trial should compare full reports, classify OS versus application packages,
identify fixed versions from maintained upstream images, and prove the final artifact starts
under the intended read-only security context. Only then can a clean or independently approved
image be signed and promoted by digest. This review does not authorize public deployment.
