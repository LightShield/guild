#!/usr/bin/env python3
"""Requirements Traceability Matrix (RTM) generator for Guild.

Parses REQUIREMENTS.md for all requirement IDs, scans test files for
@pytest.mark.req markers, and produces a coverage report.

Only E2E/acceptance tests count toward the primary coverage gate.
A test qualifies as E2E if it:
  - Has @pytest.mark.e2e on the same class or function (or parent class), OR
  - Lives under the tests/e2e/ directory, OR
  - Is a Playwright spec in ui/e2e/.

Unit-level coverage is reported separately as supplementary information.

Exit codes:
    0 — All P0 requirements have at least one E2E covering test
    1 — One or more P0 requirements have zero E2E covering tests
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

REQ_ID_PATTERN = re.compile(r"\bREQ-(\d+\.\d+[a-z]?)\b")
TIER_HEADING_PATTERN = re.compile(r"^##\s+P(\d)\s")
AC_ID_PATTERN = re.compile(r"^- (AC-(\d+\.\d+[a-z]?)\.(\d+)):")


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


def parse_acceptance_criteria(path: Path) -> dict[str, list[str]]:
    """Parse REQUIREMENTS.md and return {req_id: [ac_ids]}.

    Each AC ID like AC-01.2.3 maps to its parent requirement REQ-01.2.
    """
    ac_by_req: dict[str, list[str]] = defaultdict(list)

    with open(path, encoding="utf-8") as f:
        for line in f:
            match = AC_ID_PATTERN.match(line.strip())
            if match:
                ac_id = match.group(1)       # e.g. "AC-01.2.3"
                req_suffix = match.group(2)  # e.g. "01.2"
                req_id = f"REQ-{req_suffix}"
                ac_by_req[req_id].append(ac_id)

    return dict(ac_by_req)


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


def _has_e2e_marker(decorator_list: list[ast.expr]) -> bool:
    """Check whether a decorator list contains @pytest.mark.e2e."""
    for dec in decorator_list:
        # Plain attribute: @pytest.mark.e2e (no call parens)
        if isinstance(dec, ast.Attribute) and dec.attr == "e2e":
            return True
        # Called form: @pytest.mark.e2e() (unlikely but valid)
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr == "e2e":
                return True
    return False


def _is_e2e_path(path: Path) -> bool:
    """Check whether the test file lives under tests/e2e/."""
    try:
        path.relative_to(PROJECT_ROOT / "tests" / "e2e")
        return True
    except ValueError:
        return False


def scan_test_file(
    path: Path,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Scan a single test file and return (e2e_coverage, unit_coverage).

    Both are {req_id: [test_node_ids]}.

    A test counts as E2E if it (or its parent class) has @pytest.mark.e2e,
    or if the file lives under tests/e2e/. Otherwise it counts as unit.
    """
    e2e_cov: dict[str, list[str]] = defaultdict(list)
    unit_cov: dict[str, list[str]] = defaultdict(list)

    # Files under tests/e2e/ are E2E by definition
    file_is_e2e = _is_e2e_path(path)

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return dict(e2e_cov), dict(unit_cov)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            # Check class-level decorators
            class_req_ids: list[str] = []
            for decorator in node.decorator_list:
                class_req_ids.extend(_extract_req_ids_from_decorator(decorator))

            class_is_e2e = file_is_e2e or _has_e2e_marker(node.decorator_list)

            # Collect test methods in the class
            test_methods: list[str] = []
            for item in ast.iter_child_nodes(node):
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not item.name.startswith("test_"):
                    continue
                method_is_e2e = (
                    class_is_e2e
                    or _has_e2e_marker(item.decorator_list)
                )
                test_methods.append((item.name, method_is_e2e))

                # Check method-level decorators too
                for decorator in item.decorator_list:
                    method_req_ids = _extract_req_ids_from_decorator(
                        decorator,
                    )
                    for req_id in method_req_ids:
                        node_id = _get_test_node_id(
                            path, node.name, item.name,
                        )
                        if method_is_e2e:
                            e2e_cov[req_id].append(node_id)
                        else:
                            unit_cov[req_id].append(node_id)

            # Apply class-level req IDs to all test methods
            for req_id in class_req_ids:
                for method_name, method_is_e2e in test_methods:
                    node_id = _get_test_node_id(
                        path, node.name, method_name,
                    )
                    if method_is_e2e:
                        e2e_cov[req_id].append(node_id)
                    else:
                        unit_cov[req_id].append(node_id)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                func_is_e2e = (
                    file_is_e2e or _has_e2e_marker(node.decorator_list)
                )
                for decorator in node.decorator_list:
                    func_req_ids = _extract_req_ids_from_decorator(decorator)
                    for req_id in func_req_ids:
                        node_id = _get_test_node_id(path, None, node.name)
                        if func_is_e2e:
                            e2e_cov[req_id].append(node_id)
                        else:
                            unit_cov[req_id].append(node_id)

    return dict(e2e_cov), dict(unit_cov)


def scan_e2e_tests(e2e_dir: Path) -> dict[str, list[str]]:
    """Scan Playwright E2E test files for REQ-XX.X in test.describe strings."""
    coverage: dict[str, list[str]] = defaultdict(list)
    if not e2e_dir.is_dir():
        return dict(coverage)

    for spec_file in sorted(e2e_dir.glob("*.spec.ts")):
        content = spec_file.read_text(encoding="utf-8")
        rel_path = spec_file.relative_to(PROJECT_ROOT)

        # Find test.describe('... (REQ-XX.X, REQ-YY.Y) ...')
        describe_blocks = re.finditer(
            r"test\.describe\(['\"]([^'\"]+)['\"]\s*,", content
        )
        current_req_ids: list[str] = []
        for desc_match in describe_blocks:
            desc_text = desc_match.group(1)
            current_req_ids = [
                f"REQ-{m.group(1)}" for m in REQ_ID_PATTERN.finditer(desc_text)
            ]

        # Count individual test(...) calls in the file
        test_calls = re.findall(r"test\(['\"]([^'\"]+)['\"]", content)
        for test_name in test_calls:
            if test_name == "beforeEach":
                continue
            for req_id in current_req_ids:
                node_id = f"{rel_path}::{test_name}"
                coverage[req_id].append(node_id)

    return dict(coverage)


def scan_all_tests(
    tests_dir: Path,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Scan all test files and return (e2e_coverage, unit_coverage).

    E2E coverage includes:
      - Python tests with @pytest.mark.e2e (or in tests/e2e/)
      - Playwright specs in ui/e2e/

    Unit coverage includes:
      - Python tests with @pytest.mark.req but NOT e2e-marked
    """
    all_e2e: dict[str, list[str]] = defaultdict(list)
    all_unit: dict[str, list[str]] = defaultdict(list)

    # Python tests
    for test_file in sorted(tests_dir.rglob("test_*.py")):
        e2e_cov, unit_cov = scan_test_file(test_file)
        for req_id, node_ids in e2e_cov.items():
            all_e2e[req_id].extend(node_ids)
        for req_id, node_ids in unit_cov.items():
            all_unit[req_id].extend(node_ids)

    # Playwright E2E tests (always E2E by definition)
    e2e_dir = PROJECT_ROOT / "ui" / "e2e"
    playwright_coverage = scan_e2e_tests(e2e_dir)
    for req_id, node_ids in playwright_coverage.items():
        all_e2e[req_id].extend(node_ids)

    return dict(all_e2e), dict(all_unit)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _sort_req_id(req_id: str) -> tuple[int, int]:
    """Sort key for requirement IDs: REQ-01.2 -> (1, 2, ''), REQ-05.4a -> (5, 4, 'a')."""
    match = REQ_ID_PATTERN.search(req_id)
    if match:
        raw = match.group(1)
        parts = raw.split(".")
        major = int(parts[0])
        minor_str = parts[1] if len(parts) > 1 else "0"
        suffix = ""
        minor_digits = ""
        for ch in minor_str:
            if ch.isdigit():
                minor_digits += ch
            else:
                suffix = ch
                break
        return (major, int(minor_digits) if minor_digits else 0, suffix)
    return (999, 999, "")


def generate_report(
    tiers: dict[str, dict[str, str]],
    e2e_coverage: dict[str, list[str]],
    unit_coverage: dict[str, list[str]],
    ac_by_req: dict[str, list[str]] | None = None,
) -> str:
    """Generate the full RTM report as a string."""
    if ac_by_req is None:
        ac_by_req = {}

    lines: list[str] = []
    lines.append("=== Requirements Traceability Matrix ===")
    lines.append("")

    tier_order = sorted(tiers.keys())
    all_req_ids = [rid for tier in tier_order for rid in tiers[tier]]
    total_reqs = len(all_req_ids)

    # --- Top-level summary ---
    e2e_covered_total = sum(
        1 for r in all_req_ids
        if r in e2e_coverage and len(e2e_coverage[r]) > 0
    )
    unit_covered_total = sum(
        1 for r in all_req_ids
        if r in unit_coverage and len(unit_coverage[r]) > 0
    )
    lines.append(
        f"E2E Coverage: {e2e_covered_total}/{total_reqs} requirements "
        f"(PRIMARY -- this is the gate)"
    )
    lines.append(
        f"Unit Coverage: {unit_covered_total}/{total_reqs} requirements "
        f"(supplementary -- informational only)"
    )

    # --- AC completeness summary ---
    total_acs = sum(len(acs) for acs in ac_by_req.values())
    reqs_with_acs = len(ac_by_req)
    lines.append(
        f"AC Completeness: {total_acs} ACs defined across "
        f"{reqs_with_acs} requirements"
    )
    lines.append("")

    # --- Per-tier E2E summary ---
    lines.append("--- E2E Coverage by Tier (PRIMARY) ---")
    for tier in tier_order:
        reqs = tiers[tier]
        total = len(reqs)
        covered = sum(
            1 for r in reqs
            if r in e2e_coverage and len(e2e_coverage[r]) > 0
        )
        uncovered = total - covered
        suffix = f" ({uncovered} uncovered)" if uncovered > 0 else ""
        lines.append(f"{tier}: {covered}/{total} requirements e2e-covered{suffix}")
    lines.append("")

    # --- Per-tier unit summary ---
    lines.append("--- Unit Coverage by Tier (supplementary) ---")
    for tier in tier_order:
        reqs = tiers[tier]
        total = len(reqs)
        covered = sum(
            1 for r in reqs
            if r in unit_coverage and len(unit_coverage[r]) > 0
        )
        uncovered = total - covered
        suffix = f" ({uncovered} uncovered)" if uncovered > 0 else ""
        lines.append(f"{tier}: {covered}/{total} requirements unit-covered{suffix}")
    lines.append("")

    # --- Uncovered E2E requirements per tier ---
    for tier in tier_order:
        reqs = tiers[tier]
        uncovered_reqs = sorted(
            [
                (req_id, desc)
                for req_id, desc in reqs.items()
                if req_id not in e2e_coverage
            ],
            key=lambda x: _sort_req_id(x[0]),
        )
        if uncovered_reqs:
            lines.append(f"--- Uncovered {tier} Requirements (E2E) ---")
            for req_id, desc in uncovered_reqs:
                lines.append(f"{req_id}  {desc}")
            lines.append("")

    # --- E2E coverage details per tier ---
    for tier in tier_order:
        reqs = tiers[tier]
        covered_reqs = sorted(
            [
                (req_id, e2e_coverage[req_id])
                for req_id in reqs
                if req_id in e2e_coverage and len(e2e_coverage[req_id]) > 0
            ],
            key=lambda x: _sort_req_id(x[0]),
        )
        if covered_reqs:
            lines.append(f"--- E2E Coverage Details ({tier}) ---")
            for req_id, tests in covered_reqs:
                lines.append(f"{req_id} ({len(tests)} e2e tests)")
                for test in sorted(tests):
                    lines.append(f"  {test}")
            lines.append("")

    # --- Unit coverage details per tier ---
    for tier in tier_order:
        reqs = tiers[tier]
        covered_reqs = sorted(
            [
                (req_id, unit_coverage[req_id])
                for req_id in reqs
                if req_id in unit_coverage and len(unit_coverage[req_id]) > 0
            ],
            key=lambda x: _sort_req_id(x[0]),
        )
        if covered_reqs:
            lines.append(f"--- Unit Coverage Details ({tier}) ---")
            for req_id, tests in covered_reqs:
                lines.append(f"{req_id} ({len(tests)} unit tests)")
                for test in sorted(tests):
                    lines.append(f"  {test}")
            lines.append("")

    # --- AC-level report (informational) ---
    if ac_by_req:
        lines.append("--- Acceptance Criteria Summary (informational) ---")
        lines.append(
            f"Total ACs: {total_acs} across {reqs_with_acs} requirements"
        )

        # Count ACs whose parent requirement has at least one E2E test
        acs_with_e2e = sum(
            len(acs) for req_id, acs in ac_by_req.items()
            if req_id in e2e_coverage and len(e2e_coverage[req_id]) > 0
        )
        lines.append(
            f"ACs under E2E-covered requirements: {acs_with_e2e}/{total_acs} "
            f"(parent requirement has >= 1 E2E test)"
        )

        # Flag requirements that have ACs but no E2E test at all
        reqs_with_acs_no_e2e = sorted(
            [
                (req_id, ac_by_req[req_id])
                for req_id in ac_by_req
                if req_id not in e2e_coverage or len(e2e_coverage.get(req_id, [])) == 0
            ],
            key=lambda x: _sort_req_id(x[0]),
        )
        if reqs_with_acs_no_e2e:
            lines.append(
                f"Requirements with ACs but NO E2E test: "
                f"{len(reqs_with_acs_no_e2e)}"
            )
            for req_id, acs in reqs_with_acs_no_e2e:
                lines.append(f"  {req_id} ({len(acs)} ACs)")
        else:
            lines.append(
                "All requirements with ACs have at least one E2E test."
            )

        lines.append("")
        lines.append(
            "Note: AC-to-test-assertion mapping is not yet automated. "
            "The above tracks requirement-level coverage only."
        )
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
    ac_by_req = parse_acceptance_criteria(REQUIREMENTS_FILE)
    e2e_coverage, unit_coverage = scan_all_tests(TESTS_DIR)

    report = generate_report(tiers, e2e_coverage, unit_coverage, ac_by_req)
    print(report)

    # Check P0 E2E coverage for exit code
    p0_reqs = tiers.get("P0", {})
    all_p0_covered = all(
        req_id in e2e_coverage and len(e2e_coverage[req_id]) > 0
        for req_id in p0_reqs
    )

    if not all_p0_covered:
        uncovered_count = sum(
            1
            for r in p0_reqs
            if r not in e2e_coverage or len(e2e_coverage[r]) == 0
        )
        print(
            f"\nFAILED: {uncovered_count} P0 requirement(s) without E2E "
            f"test coverage.",
            file=sys.stderr,
        )
        return 1

    print("\nPASSED: All P0 requirements have E2E test coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
