"""Render an unpublished, digest-pinned DOCR overlay for operator review.

This tool never contacts a registry or cluster and never reads credentials. A rendered overlay
is not a signature verification or an authorization to apply it.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

_REGISTRY = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")
_BASE = Path(__file__).resolve().parent


def _validated_digest(value: str) -> str:
    match = _DIGEST.fullmatch(value)
    if match is None or match.group(1) == "0" * 64:
        raise ValueError("image digest must be a nonzero sha256:<64 lowercase hex> value")
    return value


def render_overlay(*, registry: str, web_digest: str, api_digest: str, output: Path) -> Path:
    """Write a new Kustomize overlay after validating its two immutable image references."""
    if _REGISTRY.fullmatch(registry) is None:
        raise ValueError("registry must be a lowercase DigitalOcean registry name")
    web_digest = _validated_digest(web_digest)
    api_digest = _validated_digest(api_digest)
    if web_digest == api_digest:
        raise ValueError("web and API must reference distinct image digests")

    destination = output.resolve()
    if destination.exists():
        raise FileExistsError(f"output directory already exists: {destination}")
    base_path = Path(os.path.relpath(_BASE, destination)).as_posix()
    content = (
        "apiVersion: kustomize.config.k8s.io/v1beta1\n"
        "kind: Kustomization\n"
        "resources:\n"
        f"  - {base_path}\n"
        "images:\n"
        "  - name: registry.invalid/kavrigo-web\n"
        f"    newName: registry.digitalocean.com/{registry}/kavrigo-web\n"
        f"    digest: {web_digest}\n"
        "  - name: registry.invalid/kavrigo-api\n"
        f"    newName: registry.digitalocean.com/{registry}/kavrigo-api\n"
        f"    digest: {api_digest}\n"
    )
    destination.mkdir(parents=True, exist_ok=False)
    manifest = destination / "kustomization.yaml"
    manifest.write_text(content, encoding="utf-8", newline="\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, help="DigitalOcean registry name")
    parser.add_argument("--web-digest", required=True, help="Signed web manifest digest")
    parser.add_argument("--api-digest", required=True, help="Signed API manifest digest")
    parser.add_argument("--output", required=True, type=Path, help="New directory for preview")
    args = parser.parse_args()
    try:
        manifest = render_overlay(
            registry=args.registry,
            web_digest=args.web_digest,
            api_digest=args.api_digest,
            output=args.output,
        )
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f"Wrote review-only overlay: {manifest}")


if __name__ == "__main__":
    main()
