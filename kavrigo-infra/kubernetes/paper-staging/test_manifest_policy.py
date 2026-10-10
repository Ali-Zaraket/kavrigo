"""Mutation tests for the rendered internal paper-staging release boundary."""

# This script runs as standalone unittest before the workspace test dependencies are installed.
# ruff: noqa: PT027

from __future__ import annotations

import copy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from manifest_policy import validate_manifest
from release_overlay import render_overlay

BASE = Path(__file__).resolve().parent
TEST_TEMP = BASE.parents[2] / ".local" / "manifest-policy-tests"
TEST_TEMP.mkdir(parents=True, exist_ok=True)


def _render(path: Path) -> str:
    return subprocess.run(  # noqa: S603 - fixed kubectl executable; no shell
        ["kubectl", "kustomize", str(path)],  # noqa: S607 - resolved by PATH
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _resource(items: list[dict], kind: str, name: str) -> dict:
    return next(item for item in items if item["kind"] == kind and item["metadata"]["name"] == name)


class ManifestPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("kubectl") is None:
            raise unittest.SkipTest("kubectl is needed to render Kustomize")
        cls.base = _render(BASE)

    def test_base_and_digest_overlay_pass(self) -> None:
        validate_manifest(self.base)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temporary:
            overlay = Path(temporary) / "overlay"
            render_overlay(
                registry="kavrigo-staging",
                web_digest="sha256:" + "a" * 64,
                api_digest="sha256:" + "b" * 64,
                output=overlay,
            )
            validate_manifest(_render(overlay), release=True)

    def test_exposure_and_paper_boundary_mutations_fail(self) -> None:
        def node_port(items: list[dict]) -> None:
            _resource(items, "Service", "kavrigo-web")["spec"]["type"] = "NodePort"

        def external_ip(items: list[dict]) -> None:
            _resource(items, "Service", "kavrigo-web")["spec"]["externalIPs"] = ["203.0.113.10"]

        def ingress(items: list[dict]) -> None:
            items.append(
                {
                    "apiVersion": "networking.k8s.io/v1",
                    "kind": "Ingress",
                    "metadata": {"name": "public", "namespace": "kavrigo-paper-staging"},
                    "spec": {},
                }
            )

        def host_port(items: list[dict]) -> None:
            _resource(items, "Deployment", "kavrigo-api")["spec"]["template"]["spec"]["containers"][
                0
            ]["ports"][0]["hostPort"] = 8000

        def host_network(items: list[dict]) -> None:
            _resource(items, "Deployment", "kavrigo-web")["spec"]["template"]["spec"][
                "hostNetwork"
            ] = True

        def live_trading(items: list[dict]) -> None:
            env = _resource(items, "Deployment", "kavrigo-api")["spec"]["template"]["spec"][
                "containers"
            ][0]["env"]
            next(item for item in env if item["name"] == "LIVE_TRADING_ENABLED")["value"] = "true"

        def inline_secret(items: list[dict]) -> None:
            env = _resource(items, "Deployment", "kavrigo-web")["spec"]["template"]["spec"][
                "containers"
            ][0]["env"]
            next(item for item in env if item["name"] == "CLERK_SECRET_KEY").update(
                {"value": "unsafe"}
            )

        def remove_isolation(items: list[dict]) -> None:
            items.remove(_resource(items, "NetworkPolicy", "deny-ingress"))

        def broad_allow(items: list[dict]) -> None:
            _resource(items, "NetworkPolicy", "web-to-api")["spec"]["ingress"][0]["from"] = [
                {"podSelector": {}}
            ]

        def extra_container(items: list[dict]) -> None:
            pod = _resource(items, "Deployment", "kavrigo-api")["spec"]["template"]["spec"]
            pod["containers"].append({"name": "sidecar", "image": "example.invalid/sidecar:latest"})

        original = list(yaml.safe_load_all(self.base))
        for mutate in (
            node_port,
            external_ip,
            ingress,
            host_port,
            host_network,
            live_trading,
            inline_secret,
            remove_isolation,
            broad_allow,
            extra_container,
        ):
            with self.subTest(mutation=mutate.__name__):
                items = copy.deepcopy(original)
                mutate(items)
                with self.assertRaises(ValueError):
                    validate_manifest(yaml.safe_dump_all(items))

    def test_release_rejects_mutable_wrong_registry_and_duplicate_digests(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as temporary:
            overlay = Path(temporary) / "overlay"
            render_overlay(
                registry="kavrigo-staging",
                web_digest="sha256:" + "a" * 64,
                api_digest="sha256:" + "b" * 64,
                output=overlay,
            )
            original = list(yaml.safe_load_all(_render(overlay)))
        for image in (
            "registry.digitalocean.com/kavrigo-staging/kavrigo-web:latest",
            "registry.invalid/kavrigo-web@sha256:" + "a" * 64,
            "registry.digitalocean.com/kavrigo-staging/kavrigo-web@sha256:" + "0" * 64,
            "registry.digitalocean.com/kavrigo-staging/kavrigo-web@sha256:" + "b" * 64,
            "registry.digitalocean.com/other-registry/kavrigo-web@sha256:" + "a" * 64,
        ):
            with self.subTest(image=image):
                items = copy.deepcopy(original)
                web = _resource(items, "Deployment", "kavrigo-web")["spec"]["template"]["spec"][
                    "containers"
                ][0]
                web["image"] = image
                with self.assertRaises(ValueError):
                    validate_manifest(yaml.safe_dump_all(items), release=True)


if __name__ == "__main__":
    unittest.main()
