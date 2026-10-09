"""Check that final-image scan failures remain enforceable and publicly diagnosable."""

# This suite runs with system Python before workspace dependencies are installed.
# ruff: noqa: PT009

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).with_name("check_trivy_image_report.py")
_TEST_TEMP = _MODULE_PATH.parents[1] / ".local" / "trivy-report-tests"
_TEST_TEMP.mkdir(parents=True, exist_ok=True)
_SPEC = importlib.util.spec_from_file_location("kavrigo_trivy_report", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
check_report = _MODULE.check_report


class TrivyReportTests(unittest.TestCase):
    def test_vulnerability_fails_and_sanitizes_annotation(self) -> None:
        with tempfile.TemporaryDirectory(dir=_TEST_TEMP) as directory:
            path = Path(directory) / "report.json"
            path.write_text(
                json.dumps(
                    {
                        "Results": [
                            {
                                "Vulnerabilities": [
                                    {
                                        "Severity": "HIGH",
                                        "VulnerabilityID": "CVE-2026-1234\n::warning::unsafe",
                                        "PkgName": "example",
                                        "InstalledVersion": "1.0",
                                        "FixedVersion": "1.1",
                                    }
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(check_report(path, "api"), 1)
            self.assertIn("CVE-2026-1234?::warning::unsafe", output.getvalue())
            self.assertEqual(output.getvalue().count("::error::"), 1)

    def test_empty_report_passes_but_missing_report_fails(self) -> None:
        with tempfile.TemporaryDirectory(dir=_TEST_TEMP) as directory:
            path = Path(directory) / "report.json"
            path.write_text('{"Results": []}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_report(path, "api"), 0)
                path.unlink()
                self.assertEqual(check_report(path, "api"), 1)


if __name__ == "__main__":
    unittest.main()
