from __future__ import annotations

import ast
from pathlib import Path


def imports(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.split(".")[0]


def test_domain_and_services_cannot_import_model_vendor_sdks():
    root = Path(__file__).resolve().parents[4]
    vendor_modules = {"openai", "anthropic", "agents", "litellm", "langchain_openai"}
    for tree in (root / "kavrigo-engine", root / "kavrigo-platform"):
        for path in tree.rglob("*.py"):
            if "src" in path.parts and "model-gateway" not in path.parts:
                assert not (set(imports(path)) & vendor_modules), path


def test_local_gateway_has_no_credential_or_io_dependency():
    source = Path(__file__).resolve().parents[1] / "src"
    prohibited = {
        "os",
        "pathlib",
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "kavrigo_api",
        "kavrigo_nautilus",
    }
    for path in source.rglob("*.py"):
        assert not (set(imports(path)) & prohibited), path


def test_restricted_execution_repository_still_contains_no_code():
    boundary = Path(__file__).resolve().parents[4] / "kavrigo-execution-security"
    assert not [p for p in boundary.rglob("*") if p.suffix in {".py", ".js", ".ts", ".go", ".rs"}]
