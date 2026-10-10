"""Fail-closed checks for the internal, paper-only Kubernetes staging candidate.

Validate rendered Kustomize output, not individual source files. This is a static release
boundary: it cannot prove that a cluster enforces NetworkPolicy or that an image is signed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

NAMESPACE = "kavrigo-paper-staging"
ZERO_DIGEST = "0" * 64
EXPECTED_RESOURCES = {
    ("Namespace", NAMESPACE),
    ("Service", "kavrigo-api"),
    ("Service", "kavrigo-web"),
    ("Deployment", "kavrigo-api"),
    ("Deployment", "kavrigo-web"),
    ("PodDisruptionBudget", "kavrigo-api"),
    ("PodDisruptionBudget", "kavrigo-web"),
    ("NetworkPolicy", "deny-ingress"),
    ("NetworkPolicy", "web-to-api"),
}
RELEASE_IMAGE = re.compile(
    r"registry\.digitalocean\.com/([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/"
    r"kavrigo-(web|api)@sha256:([0-9a-f]{64})\Z"
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _environment(container: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = container.get("env", [])
    _require(isinstance(entries, list), "container environment must be a list")
    names = [entry.get("name") for entry in entries]
    _require(len(names) == len(set(names)), "duplicate environment variable")
    return {entry["name"]: entry for entry in entries}


def validate_manifest(rendered: str, *, release: bool = False) -> None:
    """Reject any manifest outside the reviewed internal paper-staging boundary."""
    documents = list(yaml.safe_load_all(rendered))
    _require(all(isinstance(item, dict) for item in documents), "empty or invalid YAML document")
    resources: dict[tuple[str, str], dict[str, Any]] = {}
    for item in documents:
        key = (item.get("kind"), item.get("metadata", {}).get("name"))
        _require(key not in resources, f"duplicate resource: {key}")
        resources[key] = item
        if key[0] != "Namespace":
            _require(item["metadata"].get("namespace") == NAMESPACE, f"wrong namespace: {key}")
    _require(set(resources) == EXPECTED_RESOURCES, "resource inventory changed; review required")

    namespace = resources[("Namespace", NAMESPACE)]
    labels = namespace.get("metadata", {}).get("labels", {})
    _require(
        labels.get("pod-security.kubernetes.io/enforce") == "restricted",
        "pod security must be restricted",
    )

    for name, port in (("kavrigo-api", 8000), ("kavrigo-web", 3000)):
        service = resources[("Service", name)]["spec"]
        _require(service.get("type") == "ClusterIP", f"{name} must be ClusterIP")
        _require(
            not any(
                key in service
                for key in ("externalIPs", "externalName", "loadBalancerIP", "loadBalancerClass")
            ),
            f"{name} has external routing",
        )
        _require(
            service.get("ports") == [{"name": "http", "port": port, "targetPort": "http"}],
            f"{name} service ports changed",
        )
        _require(service.get("selector") == {"app": name}, f"{name} service selector changed")
        budget = resources[("PodDisruptionBudget", name)]["spec"]
        _require(
            budget == {"minAvailable": 1, "selector": {"matchLabels": {"app": name}}},
            f"{name} disruption budget changed",
        )

    images: dict[str, str] = {}
    registries: set[str] = set()
    release_digests: set[str] = set()
    for name in ("kavrigo-api", "kavrigo-web"):
        deployment = resources[("Deployment", name)]["spec"]
        _require(deployment.get("replicas") == 2, f"{name} replica count changed")
        template = deployment["template"]
        _require(
            template.get("metadata", {}).get("labels") == {"app": name},
            f"{name} pod labels changed",
        )
        pod = template["spec"]
        _require(
            pod.get("automountServiceAccountToken") is False,
            f"{name} mounts a service account token",
        )
        _require(
            not any(
                pod.get(key)
                for key in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace")
            ),
            f"{name} uses host or shared namespaces",
        )
        _require(
            not pod.get("initContainers") and len(pod.get("containers", [])) == 1,
            f"{name} container inventory changed",
        )
        _require(
            all("hostPath" not in volume for volume in pod.get("volumes", [])),
            f"{name} uses a host path",
        )
        pod_security = pod.get("securityContext", {})
        _require(
            pod_security.get("runAsNonRoot") is True and pod_security.get("runAsUser", 0) > 0,
            f"{name} must run as non-root",
        )
        _require(
            pod_security.get("seccompProfile", {}).get("type") == "RuntimeDefault",
            f"{name} needs runtime seccomp",
        )

        container = pod["containers"][0]
        _require(
            container.get("name") == name.removeprefix("kavrigo-"), f"{name} container name changed"
        )
        _require(
            all("hostPort" not in item for item in container.get("ports", [])),
            f"{name} uses hostPort",
        )
        security = container.get("securityContext", {})
        _require(
            security.get("allowPrivilegeEscalation") is False
            and security.get("readOnlyRootFilesystem") is True,
            f"{name} container security changed",
        )
        _require(
            security.get("capabilities", {}).get("drop") == ["ALL"]
            and security.get("privileged") is not True,
            f"{name} container capabilities changed",
        )
        _require(
            all(
                container.get(probe)
                for probe in ("startupProbe", "livenessProbe", "readinessProbe")
            ),
            f"{name} probes missing",
        )
        resources_spec = container.get("resources", {})
        _require(
            bool(resources_spec.get("requests")) and bool(resources_spec.get("limits")),
            f"{name} resources unbounded",
        )

        env = _environment(container)
        for key, value in (
            ("KAVRIGO_ENV", "staging"),
            ("LIVE_TRADING_ENABLED", "false"),
            ("DEFAULT_TRADING_MODE", "paper"),
        ):
            _require(env.get(key) == {"name": key, "value": value}, f"{name} {key} is not pinned")
        auth_key, auth_value = (
            ("AUTH_PROVIDER", "jwks")
            if name == "kavrigo-api"
            else ("KAVRIGO_WEB_AUTH_PROVIDER", "clerk")
        )
        _require(
            env.get(auth_key) == {"name": auth_key, "value": auth_value},
            f"{name} auth provider changed",
        )
        if name == "kavrigo-api":
            _require(
                env.get("AUTH_SESSION_PROFILE")
                == {"name": "AUTH_SESSION_PROFILE", "value": "clerk_v2"},
                "API session profile changed",
            )
        else:
            _require(
                env.get("KAVRIGO_API_ORIGIN")
                == {
                    "name": "KAVRIGO_API_ORIGIN",
                    "value": "http://kavrigo-api.kavrigo-paper-staging.svc.cluster.local:8000",
                },
                "web API origin changed",
            )
        secret_keys = (
            {"POSTGRES_DSN", "AUTH_ISSUER", "AUTH_JWKS_URL", "AUTH_ALLOWED_PARTIES"}
            if name == "kavrigo-api"
            else {"KAVRIGO_WEB_ORIGIN", "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "CLERK_SECRET_KEY"}
        )
        for key in secret_keys:
            source = env.get(key, {}).get("valueFrom", {}).get("secretKeyRef", {})
            _require(
                source.get("name")
                == ("kavrigo-api-runtime" if name == "kavrigo-api" else "kavrigo-web-runtime")
                and bool(source.get("key"))
                and "value" not in env[key],
                f"{name} {key} must come from the runtime Secret",
            )

        image = container.get("image", "")
        if release:
            match = RELEASE_IMAGE.fullmatch(image)
            _require(
                match is not None
                and match.group(2) == name.removeprefix("kavrigo-")
                and match.group(3) != ZERO_DIGEST,
                f"{name} needs a DigitalOcean image digest",
            )
            registries.add(match.group(1))
            release_digests.add(match.group(3))
        else:
            _require(
                image == f"registry.invalid/{name}@sha256:{ZERO_DIGEST}",
                f"{name} base image must remain invalid",
            )
        images[name] = image
    _require(images["kavrigo-api"] != images["kavrigo-web"], "web and API images must differ")
    if release:
        _require(len(registries) == 1, "web and API images must use one registry")
        _require(len(release_digests) == 2, "web and API digests must differ")

    deny = resources[("NetworkPolicy", "deny-ingress")]["spec"]
    _require(
        deny == {"podSelector": {}, "policyTypes": ["Ingress"]}, "default ingress isolation changed"
    )
    web_to_api = resources[("NetworkPolicy", "web-to-api")]["spec"]
    _require(
        web_to_api
        == {
            "podSelector": {"matchLabels": {"app": "kavrigo-api"}},
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": [{"podSelector": {"matchLabels": {"app": "kavrigo-web"}}}],
                    "ports": [{"protocol": "TCP", "port": 8000}],
                }
            ],
        },
        "web-to-API ingress policy changed",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="kubectl kustomize output file, or - for stdin")
    parser.add_argument("--release", action="store_true", help="expect immutable DOCR images")
    args = parser.parse_args()
    try:
        rendered = (
            sys.stdin.read()
            if args.manifest == "-"
            else Path(args.manifest).read_text(encoding="utf-8")
        )
        validate_manifest(rendered, release=args.release)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    print("Internal paper-staging manifest policy passed")


if __name__ == "__main__":
    main()
