#!/usr/bin/env python3
"""Reject float annotations on money and quantity fields in the domain contracts.

``AGENTS.md`` domain rule 6: money and quantity use decimal/fixed-point types, never binary
floats. ``ExactDecimal`` enforces this at runtime; this hook catches the case where someone
annotates a *new* monetary field as ``float`` and never exercises it in a test.

Bounded scores (confidence, sentiment, quality) are legitimately floats — nothing is accounted
for in them — so the check keys on the field name, not on the type alone.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MONETARY_HINTS = (
    "amount",
    "notional",
    "price",
    "quantity",
    "qty",
    "cash",
    "equity",
    "balance",
    "pnl",
    "fee",
    "cost_usd",
    "usd",
    "exposure",
)

ALLOWED_FLOAT_NAMES = ("score", "confidence", "uncertainty", "sentiment", "ratio", "agreement")

# Containers whose fields are bounded model or heuristic outputs rather than accounted values.
# `SignalScores.price` is a signal in [-1, 1], not a price, so the field name alone is not enough
# to classify it.
SCORE_CONTAINER_SUFFIXES = ("Scores", "Score", "Quality", "Requirements")


def _mentions_float(node: ast.expr | None) -> bool:
    if node is None:
        return False
    return any(isinstance(child, ast.Name) and child.id == "float" for child in ast.walk(node))


def _check_class(path: Path, cls: ast.ClassDef) -> list[str]:
    if cls.name.endswith(SCORE_CONTAINER_SUFFIXES):
        return []
    problems: list[str] = []
    for node in cls.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        name = node.target.id.lower()
        if any(ok in name for ok in ALLOWED_FLOAT_NAMES):
            continue
        if any(hint in name for hint in MONETARY_HINTS) and _mentions_float(node.annotation):
            problems.append(
                f"{path}:{node.lineno}: field '{cls.name}.{node.target.id}' is monetary but "
                "annotated with float; use ExactDecimal, Money or Quantity "
                "(AGENTS.md domain rule 6)"
            )
    return problems


def check(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    problems: list[str] = []

    # Classes anywhere in the file, including nested ones, are checked with class context so
    # that score containers can be exempted.
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            problems.extend(_check_class(path, node))

    # Module-level annotations only: iterating tree.body rather than walking avoids reporting
    # class fields a second time.
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        name = node.target.id.lower()
        if any(ok in name for ok in ALLOWED_FLOAT_NAMES):
            continue
        if any(hint in name for hint in MONETARY_HINTS) and _mentions_float(node.annotation):
            problems.append(
                f"{path}:{node.lineno}: '{node.target.id}' is monetary but annotated with "
                "float; use ExactDecimal, Money or Quantity (AGENTS.md domain rule 6)"
            )
    return sorted(problems)


def main(argv: list[str]) -> int:
    problems: list[str] = []
    for arg in argv:
        path = Path(arg)
        if path.suffix == ".py" and path.exists():
            problems.extend(check(path))
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
