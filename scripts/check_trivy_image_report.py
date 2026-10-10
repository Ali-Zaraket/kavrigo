"""Fail CI on high/critical findings in a final image's Trivy JSON report.

Only bounded vulnerability identifiers and package versions reach public CI annotations.
The full report is retained with the candidate SBOM for a short-lived review artifact.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_SAFE = re.compile(r"[^a-zA-Z0-9._:+/@-]")
_BLOCKING = {"HIGH", "CRITICAL"}


def _public(value: object) -> str:
    return _SAFE.sub("?", str(value))[:120]


def check_report(path: Path, image: str) -> int:
    """Return nonzero for a missing, invalid, or vulnerable final-image report."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("Results"), list):
            raise ValueError("missing Results array")
    except (OSError, ValueError) as exc:
        print(f"::error::Trivy {_public(image)} report unavailable or invalid: {_public(exc)}")
        return 1

    findings = [
        vulnerability
        for result in report["Results"]
        if isinstance(result, dict)
        for vulnerability in result.get("Vulnerabilities") or []
        if isinstance(vulnerability, dict) and vulnerability.get("Severity") in _BLOCKING
    ]
    details = []
    for vulnerability in findings[:20]:
        cve = _public(vulnerability.get("VulnerabilityID", "unknown"))
        package = _public(vulnerability.get("PkgName", "unknown"))
        installed = _public(vulnerability.get("InstalledVersion", "unknown"))
        fixed = _public(vulnerability.get("FixedVersion", "unfixed"))
        severity = _public(vulnerability.get("Severity", "unknown"))
        details.append(f"{severity} {cve} {package} {installed} fixed-in {fixed}")
    if findings:
        preview = "; ".join(details[:3])
        print(
            f"::error::Trivy {_public(image)} has {len(findings)} HIGH/CRITICAL findings: {preview}"
        )
        for detail in details:
            print(f"Trivy {_public(image)} {detail}")
        return 1
    print(f"Trivy {_public(image)}: no HIGH/CRITICAL findings")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    return check_report(args.report, args.image)


if __name__ == "__main__":
    raise SystemExit(main())
