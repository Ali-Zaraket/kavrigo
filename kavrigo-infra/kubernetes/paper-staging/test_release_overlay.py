"""Digest-only release preview guards; no registry or cluster is needed."""

# This suite runs with system Python before workspace dependencies are installed.
# ruff: noqa: PT009, PT027

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).with_name("release_overlay.py")
_TEST_TEMP = _MODULE_PATH.parents[3] / ".local" / "release-overlay-tests"
_TEST_TEMP.mkdir(parents=True, exist_ok=True)
_SPEC = importlib.util.spec_from_file_location("kavrigo_release_overlay", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
render_overlay = _MODULE.render_overlay


class ReleaseOverlayTests(unittest.TestCase):
    def test_rejects_mutable_or_placeholder_references(self) -> None:
        with tempfile.TemporaryDirectory(dir=_TEST_TEMP) as temporary:
            output = Path(temporary) / "overlay"
            for digest in ("latest", "sha256:" + "0" * 64, "sha256:" + "A" * 64):
                with self.subTest(digest=digest), self.assertRaises(ValueError):
                    render_overlay(
                        registry="kavrigo-staging",
                        web_digest=digest,
                        api_digest="sha256:" + "b" * 64,
                        output=output,
                    )
            with self.assertRaises(ValueError):
                render_overlay(
                    registry="invalid/name",
                    web_digest="sha256:" + "a" * 64,
                    api_digest="sha256:" + "b" * 64,
                    output=output,
                )
            with self.assertRaises(ValueError):
                render_overlay(
                    registry="kavrigo-staging",
                    web_digest="sha256:" + "a" * 64,
                    api_digest="sha256:" + "a" * 64,
                    output=output,
                )
            self.assertFalse(output.exists())

    def test_renders_two_distinct_digests_without_public_endpoint(self) -> None:
        with tempfile.TemporaryDirectory(dir=_TEST_TEMP) as temporary:
            output = Path(temporary) / "overlay"
            manifest = render_overlay(
                registry="kavrigo-staging",
                web_digest="sha256:" + "a" * 64,
                api_digest="sha256:" + "b" * 64,
                output=output,
            )
            self.assertTrue(manifest.exists())
            with self.assertRaises(FileExistsError):
                render_overlay(
                    registry="kavrigo-staging",
                    web_digest="sha256:" + "a" * 64,
                    api_digest="sha256:" + "b" * 64,
                    output=output,
                )
            if shutil.which("kubectl") is None:
                self.skipTest("kubectl is needed to validate Kustomize rendering")
            result = subprocess.run(  # noqa: S603 - fixed executable and arguments; no shell
                ["kubectl", "kustomize", str(output)],  # noqa: S607 - resolved by PATH
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn(
                "registry.digitalocean.com/kavrigo-staging/kavrigo-web@sha256:", result.stdout
            )
            self.assertIn(
                "registry.digitalocean.com/kavrigo-staging/kavrigo-api@sha256:", result.stdout
            )
            self.assertNotIn("registry.invalid", result.stdout)
            self.assertNotIn("kind: Ingress\n", result.stdout)
            self.assertNotIn("type: LoadBalancer", result.stdout)


if __name__ == "__main__":
    unittest.main()
