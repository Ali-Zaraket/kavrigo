# Deployment image runtime review — 2026-10-10

**Decision: do not promote a candidate image.** The final-image HIGH/CRITICAL Trivy gate stays
blocking. A green source/lockfile scan and successful import smoke do not clear findings in the
runtime filesystem. Counts below are for the exact pinned images and vulnerability database used
by [CI run 67](https://github.com/Ali-Zaraket/kavrigo/actions/runs/38045234630); they can change
as the advisory database or image digests change. The run retained full JSON reports and
CycloneDX SBOMs in the `image-review-96bd7d36925db312e1a13daa961e59c8fe0df080` artifact.

| Candidate | Pinned runtime | CI HIGH/CRITICAL | Status |
|---|---|---:|---|
| API | `gcr.io/distroless/python3-debian13:nonroot@sha256:83aa8d4f74a4d7f7cf2d472054139bef71a927b76c680c0f2e1021d6b1d6d732` | 42 | Import smoke passed; release gate failed. |
| Worker | Same Python 3.13 runtime | 42 | Import smoke passed; release gate failed. |
| Web | `gcr.io/distroless/nodejs24-debian13:nonroot@sha256:9eeb7f5887d0e239e78264b06f7f11d2e14be534050481803a9e4728fcdd278e` | 0 | Read-only non-root homepage smoke passed; scan gate passed for this image. |

The official [distroless image catalog](https://github.com/GoogleContainerTools/distroless)
publishes Debian 13 Python 3 and Node 24 runtimes. Its current Python `:nonroot` manifest digest
was checked again on 2026-10-10 and matched the pinned digest. The web candidate now uses the
official [distroless Node 24](https://github.com/GoogleContainerTools/distroless/blob/main/nodejs/README.md)
image, pinned by manifest digest in `web.Dockerfile`. Its first startup smoke omitted required
runtime environment values; [CI run 67](https://github.com/Ali-Zaraket/kavrigo/actions/runs/38045234630)
passed with those values supplied and reported no blocking web-image findings. The previous
`node:24-bookworm-slim` web runtime had 66 HIGH/CRITICAL findings in
[CI run 64](https://github.com/Ali-Zaraket/kavrigo/actions/runs/37985383354).

The later [CI run 38063760190](https://github.com/Ali-Zaraket/kavrigo/actions/runs/38063760190)
retained another scan of the same Python runtime candidates. Each still had 42 HIGH/CRITICAL
findings: 31 Debian OS findings and 11 Python-package findings. The Python findings were six
for PyJWT 2.13.0, two for urllib3 2.7.0, and one each for fsspec 2026.2.0, msgpack 1.1.2,
and setuptools 70.3.0. The API's direct PyJWT requirement and workspace lock now require
2.15.1, but this is a source change awaiting a fresh final-image scan; it does not clear the
release gate. NautilusTrader 1.231.0 pins fsspec 2026.2.0, so fsspec cannot be updated inside
the current stable dependency set without a separate compatibility decision. The OS findings
remain in the pinned base. The other Python package findings need final-image path attribution
before changing build inputs or claiming a fix.

Other runtime paths have material constraints:

- Docker's [Community hardened Python image](https://docs.docker.com/dhi/get-started/) is a
  candidate for a future authenticated trial, but `dhi.io` requires a Docker account login and
  a reviewed CI/cluster pull-credential flow. The image must still pass the same ABI, imports,
  read-only execution and final scan checks; a catalog description is not a scan result.
- Chainguard's [public Python image](https://images.chainguard.dev/directory/image/python/versions)
  currently tracks Python 3.14 as `latest`; its Python 3.13 tags require an entitlement. A
  public `latest` pull is therefore not a compatible drop-in for Kavrigo's locked 3.13 build.
  An entitled 3.13 trial would still need native-wheel ABI, import, read-only and final-scan
  evidence before a runtime change.
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
