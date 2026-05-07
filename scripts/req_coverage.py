#!/usr/bin/env python3
"""Requirements Traceability Matrix (RTM) generator for Guild.

Parses REQUIREMENTS.md for all requirement IDs, scans test files for
@pytest.mark.req markers, and produces a coverage report.

Exit codes:
    0 — All P0 requirements have at least one covering test
    1 — One or more P0 requirements have zero covering tests
"""

from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

__all__ = ["main"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_FILE = PROJECT_ROOT / "REQUIREMENTS.md"
TESTS_DIR = PROJECT_ROOT / "tests"

REQ_ID_PATTERN = re.compile(r"\bREQ-(\d+\.\d+)\b")
TIER_HEADING_PATTERN = re.compile(r"^##\s+P(\d)\s")


# ---------------------------------------------------------------------------
# Requirement parsing
# ---------------------------------------------------------------------------


def parse_requirements(path: Path) -> dict[str, dict[str, str]]:
    """Parse REQUIREMENTS.md and return {tier: {req_id: description}}.

    Tiers are strings like "P0", "P1", etc.
    """
    tiers: dict[str, dict[str, str]] = defaultdict(dict)
    current_tier: str | None = None

    with open(path, encoding="utf-8") as f:
        for line in f:
            # Detect tier headings like "## P0 — ..."
            tier_match = TIER_HEADING_PATTERN.match(line)
            if tier_match:
                current_tier = f"P{tier_match.group(1)}"
                continue

            if current_tier is None:
                continue

            # Look for requirement IDs in table rows: | REQ-XX.X | text | ... |
            if "|" in line and REQ_ID_PATTERN.search(line):
                cells = [c.strip() for c in line.split("|")]
                # Find the cell containing the REQ ID
                for i, cell in enumerate(cells):
                    match = REQ_ID_PATTERN.search(cell)
                    if match:
                        req_id = f"REQ-{match.group(1)}"
                        # Description is typically the next cell
                        desc = cells[i + 1] if i + 1 < len(cells) else ""
                        tiers[current_tier][req_id] = desc
                        break

    return dict(tiers)


# ---------------------------------------------------------------------------
# Test file scanning (AST-based)
# ---------------------------------------------------------------------------


def _extract_req_ids_from_decorator(node: ast.expr) -> list[str]:
    """Extract REQ-XX.X strings from a pytest.mark.req(...) decorator node."""
    # Match: @pytest.mark.req("REQ-XX.X")
    if not isinstance(node, ast.Call):
        return []

    func = node.func
    # Check for pytest.mark.req or mark.req attribute chain
    if isinstance(func, ast.Attribute) and func.attr == "req":
        # Verify it's pytest.mark.req or just mark.req
        ids: list[str] = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if REQ_ID_PATTERN.search(arg.value):
                    ids.append(arg.value)
        return ids

    return []


def _get_test_node_id(file_path: Path, class_name: str | None, func_name: str) -> str:
    """Build a pytest-style test node ID."""
    rel = file_path.relative_to(PROJECT_ROOT)
    if class_name:
        return f"{rel}::{class_name}::{func_name}"
    return f"{rel}::{func_name}"


def scan_test_file(path: Path) -> dict[str, list[str]]:
    """Scan a single test file and return {req_id: [test_node_ids]}.

    Uses the AST to find @pytest.mark.req decorators on classes and functions.
    """
    coverage: dict[str, list[str]] = defaultdict(list)

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return dict(coverage)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            # Check class-level decorators
            class_req_ids: list[str] = []
            for decorator in node.decorator_list:
                class_req_ids.extend(_extract_req_ids_from_decorator(decorator))

            # Collect test methods in the class
            test_methods: list[str] = []
            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("test_"):
                        test_methods.append(item.name)

                        # Check method-level decorators too
                        for decorator in item.decorator_list:
                            method_req_ids = _extract_req_ids_from_decorator(decorator)
                            for req_id in method_req_ids:
                                node_id = _get_test_node_id(
                                    path, node.name, item.name
                                )
                                coverage[req_id].append(node_id)

            # Apply class-level req IDs to all test methods
            for req_id in class_req_ids:
                for method_name in test_methods:
                    node_id = _get_test_node_id(path, node.name, method_name)
                    coverage[req_id].append(node_id)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                for decorator in node.decorator_list:
                    func_req_ids = _extract_req_ids_from_decorator(decorator)
                    for req_id in func_req_ids:
                        node_id = _get_test_node_id(path, None, node.name)
                        coverage[req_id].append(node_id)

    return dict(coverage)


def scan_all_tests(tests_dir: Path) -> dict[str, list[str]]:
    """Scan all test files and return {req_id: [test_node_ids]}."""
    all_coverage: dict[str, list[str]] = defaultdict(list)

    for test_file in sorted(tests_dir.rglob("test_*.py")):
        file_coverage = scan_test_file(test_file)
        for req_id, node_ids in file_coverage.items():
            all_coverage[req_id].extend(node_ids)

    return dict(all_coverage)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _sort_req_id(req_id: str) -> tuple[int, int]:
    """Sort key for requirement IDs: REQ-01.2 -> (1, 2)."""
    match = REQ_ID_PATTERN.search(req_id)
    if match:
        parts = match.group(1).split(".")
        return (int(parts[0]), int(parts[1]))
    return (999, 999)


def generate_report(
    tiers: dict[str, dict[str, str]],
    coverage: dict[str, list[str]],
) -> str:
    """Generate the full RTM report as a string."""
    lines: list[str] = []
    lines.append("=== Requirements Traceability Matrix ===")
    lines.append("")

    tier_order = sorted(tiers.keys())

    # Summary per tier
    for tier in tier_order:
        reqs = tiers[tier]
        total = len(reqs)
        covered = sum(1 for r in reqs if r in coverage and len(coverage[r]) > 0)
        uncovered = total - covered
        suffix = f" ({uncovered} uncovered)" if uncovered > 0 else ""
        lines.append(f"{tier}: {covered}/{total} requirements covered{suffix}")

    lines.append("")

    # Uncovered requirements per tier
    for tier in tier_order:
        reqs = tiers[tier]
        uncovered_reqs = sorted(
            [(req_id, desc) for req_id, desc in reqs.items() if req_id not in coverage],
            key=lambda x: _sort_req_id(x[0]),
        )
        if uncovered_reqs:
            lines.append(f"--- Uncovered {tier} Requirements ---")
            for req_id, desc in uncovered_reqs:
                lines.append(f"{req_id}  {desc}")
            lines.append("")

    # Coverage details per tier (only for tiers with coverage)
    for tier in tier_order:
        reqs = tiers[tier]
        covered_reqs = sorted(
            [
                (req_id, coverage[req_id])
                for req_id in reqs
                if req_id in coverage and len(coverage[req_id]) > 0
            ],
            key=lambda x: _sort_req_id(x[0]),
        )
        if covered_reqs:
            lines.append(f"--- Coverage Details ({tier}) ---")
            for req_id, tests in covered_reqs:
                lines.append(f"{req_id} ({len(tests)} tests)")
                for test in sorted(tests):
                    lines.append(f"  {test}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the RTM generator. Returns exit code."""
    if not REQUIREMENTS_FILE.exists():
        print(f"ERROR: {REQUIREMENTS_FILE} not found", file=sys.stderr)
        return 1

    if not TESTS_DIR.exists():
        print(f"ERROR: {TESTS_DIR} not found", file=sys.stderr)
        return 1

    tiers = parse_requirements(REQUIREMENTS_FILE)
    coverage = scan_all_tests(TESTS_DIR)

    report = generate_report(tiers, coverage)
    print(report)

    # Check P0 coverage for exit code
    p0_reqs = tiers.get("P0", {})
    all_p0_covered = all(
        req_id in coverage and len(coverage[req_id]) > 0 for req_id in p0_reqs
    )

    if not all_p0_covered:
        uncovered_count = sum(
            1 for r in p0_reqs if r not in coverage or len(coverage[r]) == 0
        )
        print(
            f"\nFAILED: {uncovered_count} P0 requirement(s) without test coverage.",
            file=sys.stderr,
        )
        return 1

    print("\nPASSED: All P0 requirements have test coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
