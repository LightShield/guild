#!/usr/bin/env python3
"""Requirements Traceability Matrix (RTM) generator for Guild.

Parses REQUIREMENTS.md for all requirement IDs and acceptance criteria,
scans test files for @pytest.mark.req and @pytest.mark.ac markers, and
produces a coverage report at both requirement and AC granularity.

Only E2E/acceptance tests count toward the primary coverage gate.
A test qualifies as E2E if it:
  - Has @pytest.mark.e2e on the same class or function (or parent class), OR
  - Lives under the tests/e2e/ directory, OR
  - Is a Playwright spec in ui/e2e/.

Unit-level coverage is reported separately as supplementary information.

Backward compatibility:
  - @pytest.mark.req("REQ-XX.X") covers ALL ACs of that requirement
    (graceful migration path while tests are being retagged to AC-level).
  - Playwright E2E tests referencing REQ IDs in test.describe strings
    likewise cover all ACs of the referenced requirements.

Exit codes:
    0 — All P0 requirements have all ACs covered by at least one E2E test
    1 — One or more P0 requirements have ACs without E2E test coverage
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
AC_MARKER_PATTERN = re.compile(r"\bAC-(\d+\.\d+[a-z]?\.\d+)\b")


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


def _extract_ac_ids_from_decorator(node: ast.expr) -> list[str]:
    """Extract AC-XX.X.X strings from a pytest.mark.ac(...) decorator node."""
    # Match: @pytest.mark.ac("AC-XX.X.X")
    if not isinstance(node, ast.Call):
        return []

    func = node.func
    # Check for pytest.mark.ac or mark.ac attribute chain
    if isinstance(func, ast.Attribute) and func.attr == "ac":
        ids: list[str] = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if AC_MARKER_PATTERN.search(arg.value):
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


def _record_coverage(
    cov_map: dict[str, list[str]],
    ids: list[str],
    node_id: str,
) -> None:
    """Add *node_id* to *cov_map* for each id in *ids*."""
    for cov_id in ids:
        cov_map[cov_id].append(node_id)


def scan_test_file(
    path: Path,
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, list[str]],
]:
    """Scan a single test file.

    Returns (e2e_req_cov, unit_req_cov, e2e_ac_cov, unit_ac_cov).
    All are ``{id: [test_node_ids]}``.

    A test counts as E2E if it (or its parent class) has @pytest.mark.e2e,
    or if the file lives under tests/e2e/. Otherwise it counts as unit.
    """
    e2e_cov: dict[str, list[str]] = defaultdict(list)
    unit_cov: dict[str, list[str]] = defaultdict(list)
    e2e_ac: dict[str, list[str]] = defaultdict(list)
    unit_ac: dict[str, list[str]] = defaultdict(list)

    # Files under tests/e2e/ are E2E by definition
    file_is_e2e = _is_e2e_path(path)

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return dict(e2e_cov), dict(unit_cov), dict(e2e_ac), dict(unit_ac)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            # Check class-level decorators
            class_req_ids: list[str] = []
            class_ac_ids: list[str] = []
            for decorator in node.decorator_list:
                class_req_ids.extend(_extract_req_ids_from_decorator(decorator))
                class_ac_ids.extend(_extract_ac_ids_from_decorator(decorator))

            class_is_e2e = file_is_e2e or _has_e2e_marker(node.decorator_list)

            # Collect test methods in the class
            test_methods: list[tuple[str, bool]] = []
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

                # Check method-level decorators
                for decorator in item.decorator_list:
                    node_id = _get_test_node_id(
                        path, node.name, item.name,
                    )
                    target_req = e2e_cov if method_is_e2e else unit_cov
                    target_ac = e2e_ac if method_is_e2e else unit_ac
                    _record_coverage(
                        target_req,
                        _extract_req_ids_from_decorator(decorator),
                        node_id,
                    )
                    _record_coverage(
                        target_ac,
                        _extract_ac_ids_from_decorator(decorator),
                        node_id,
                    )

            # Apply class-level IDs to all test methods
            for method_name, method_is_e2e in test_methods:
                node_id = _get_test_node_id(
                    path, node.name, method_name,
                )
                target_req = e2e_cov if method_is_e2e else unit_cov
                target_ac = e2e_ac if method_is_e2e else unit_ac
                _record_coverage(target_req, class_req_ids, node_id)
                _record_coverage(target_ac, class_ac_ids, node_id)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                func_is_e2e = (
                    file_is_e2e or _has_e2e_marker(node.decorator_list)
                )
                for decorator in node.decorator_list:
                    node_id = _get_test_node_id(path, None, node.name)
                    target_req = e2e_cov if func_is_e2e else unit_cov
                    target_ac = e2e_ac if func_is_e2e else unit_ac
                    _record_coverage(
                        target_req,
                        _extract_req_ids_from_decorator(decorator),
                        node_id,
                    )
                    _record_coverage(
                        target_ac,
                        _extract_ac_ids_from_decorator(decorator),
                        node_id,
                    )

    return dict(e2e_cov), dict(unit_cov), dict(e2e_ac), dict(unit_ac)


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
) -> tuple[
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, list[str]],
]:
    """Scan all test files.

    Returns (e2e_req_cov, unit_req_cov, e2e_ac_cov, unit_ac_cov).

    E2E coverage includes:
      - Python tests with @pytest.mark.e2e (or in tests/e2e/)
      - Playwright specs in ui/e2e/

    Unit coverage includes:
      - Python tests with @pytest.mark.req/@pytest.mark.ac but NOT e2e-marked
    """
    all_e2e: dict[str, list[str]] = defaultdict(list)
    all_unit: dict[str, list[str]] = defaultdict(list)
    all_e2e_ac: dict[str, list[str]] = defaultdict(list)
    all_unit_ac: dict[str, list[str]] = defaultdict(list)

    # Python tests
    for test_file in sorted(tests_dir.rglob("test_*.py")):
        e2e_cov, unit_cov, e2e_ac, unit_ac = scan_test_file(test_file)
        for req_id, node_ids in e2e_cov.items():
            all_e2e[req_id].extend(node_ids)
        for req_id, node_ids in unit_cov.items():
            all_unit[req_id].extend(node_ids)
        for ac_id, node_ids in e2e_ac.items():
            all_e2e_ac[ac_id].extend(node_ids)
        for ac_id, node_ids in unit_ac.items():
            all_unit_ac[ac_id].extend(node_ids)

    # Playwright E2E tests (always E2E by definition)
    e2e_dir = PROJECT_ROOT / "ui" / "e2e"
    playwright_coverage = scan_e2e_tests(e2e_dir)
    for req_id, node_ids in playwright_coverage.items():
        all_e2e[req_id].extend(node_ids)

    return dict(all_e2e), dict(all_unit), dict(all_e2e_ac), dict(all_unit_ac)


def expand_req_to_ac_coverage(
    req_coverage: dict[str, list[str]],
    ac_by_req: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Expand requirement-level coverage to AC-level coverage.

    If a test has @pytest.mark.req("REQ-XX.X"), it counts as covering
    ALL ACs of that requirement. This provides backward compatibility
    during migration from req-level to ac-level markers.
    """
    expanded: dict[str, list[str]] = defaultdict(list)
    for req_id, test_nodes in req_coverage.items():
        if req_id in ac_by_req:
            for ac_id in ac_by_req[req_id]:
                expanded[ac_id].extend(test_nodes)
    return dict(expanded)


def merge_ac_coverage(
    *sources: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Merge multiple AC coverage dicts, deduplicating test node IDs."""
    merged: dict[str, list[str]] = defaultdict(list)
    for source in sources:
        for ac_id, nodes in source.items():
            for node in nodes:
                if node not in merged[ac_id]:
                    merged[ac_id].append(node)
    return dict(merged)


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


def _sort_ac_id(ac_id: str) -> tuple[int, int, str, int]:
    """Sort key for AC IDs: AC-01.2.3 -> (1, 2, '', 3)."""
    match = AC_MARKER_PATTERN.search(ac_id)
    if match:
        raw = match.group(1)  # e.g. "01.2.3" or "05.4a.2"
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
        ac_num = int(parts[2]) if len(parts) > 2 else 0
        return (major, int(minor_digits) if minor_digits else 0, suffix, ac_num)
    return (999, 999, "", 999)


def generate_report(
    tiers: dict[str, dict[str, str]],
    e2e_coverage: dict[str, list[str]],
    unit_coverage: dict[str, list[str]],
    ac_by_req: dict[str, list[str]] | None = None,
    e2e_ac_coverage: dict[str, list[str]] | None = None,
    unit_ac_coverage: dict[str, list[str]] | None = None,
) -> str:
    """Generate the full RTM report as a string."""
    if ac_by_req is None:
        ac_by_req = {}
    if e2e_ac_coverage is None:
        e2e_ac_coverage = {}
    if unit_ac_coverage is None:
        unit_ac_coverage = {}

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

    # --- AC coverage summary ---
    total_acs = sum(len(acs) for acs in ac_by_req.values())
    reqs_with_acs = len(ac_by_req)
    acs_with_e2e_tests = sum(
        1 for ac_id_list in ac_by_req.values()
        for ac_id in ac_id_list
        if ac_id in e2e_ac_coverage and len(e2e_ac_coverage[ac_id]) > 0
    )
    lines.append(
        f"AC Coverage: {acs_with_e2e_tests}/{total_acs} acceptance criteria "
        f"have linked tests"
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

    # --- Per-requirement AC coverage ---
    lines.append("--- AC Coverage by Requirement ---")
    for tier in tier_order:
        for req_id in sorted(tiers[tier], key=_sort_req_id):
            acs = ac_by_req.get(req_id, [])
            if not acs:
                continue
            covered_acs = [
                ac for ac in acs
                if ac in e2e_ac_coverage and len(e2e_ac_coverage[ac]) > 0
            ]
            missing_acs = [
                ac for ac in acs
                if ac not in e2e_ac_coverage or len(e2e_ac_coverage[ac]) == 0
            ]
            n_covered = len(covered_acs)
            n_total = len(acs)
            if missing_acs:
                missing_str = ", ".join(sorted(missing_acs, key=_sort_ac_id))
                lines.append(
                    f"{req_id}: {n_covered}/{n_total} ACs covered "
                    f"(missing: {missing_str})"
                )
            else:
                lines.append(f"{req_id}: {n_covered}/{n_total} ACs covered")
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

    # --- ACs without linked tests ---
    all_uncovered_acs = sorted(
        [
            ac_id
            for acs in ac_by_req.values()
            for ac_id in acs
            if ac_id not in e2e_ac_coverage or len(e2e_ac_coverage[ac_id]) == 0
        ],
        key=_sort_ac_id,
    )
    if all_uncovered_acs:
        lines.append(f"--- ACs Without Linked Tests ({len(all_uncovered_acs)}) ---")
        for ac_id in all_uncovered_acs:
            lines.append(f"  {ac_id}")
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
    e2e_coverage, unit_coverage, e2e_ac_direct, unit_ac_direct = scan_all_tests(
        TESTS_DIR,
    )

    # Backward compatibility: @pytest.mark.req("REQ-XX.X") covers ALL ACs
    # of that requirement. Expand req-level coverage to AC-level.
    e2e_ac_from_req = expand_req_to_ac_coverage(e2e_coverage, ac_by_req)
    unit_ac_from_req = expand_req_to_ac_coverage(unit_coverage, ac_by_req)

    # Merge direct AC markers with expanded req-level coverage
    e2e_ac_coverage = merge_ac_coverage(e2e_ac_direct, e2e_ac_from_req)
    unit_ac_coverage = merge_ac_coverage(unit_ac_direct, unit_ac_from_req)

    # Derive requirement-level coverage from AC coverage:
    # A requirement is "E2E covered" if ALL its ACs have linked tests,
    # OR if it has a direct @pytest.mark.req marker (backward compat).
    for req_id, ac_ids in ac_by_req.items():
        if req_id in e2e_coverage:
            continue  # Already covered via @pytest.mark.req
        if not ac_ids:
            continue
        all_covered = all(
            ac_id in e2e_ac_coverage and len(e2e_ac_coverage[ac_id]) > 0
            for ac_id in ac_ids
        )
        if all_covered:
            # Synthesize requirement-level coverage from AC tests
            tests: list[str] = []
            for ac_id in ac_ids:
                tests.extend(e2e_ac_coverage.get(ac_id, []))
            e2e_coverage[req_id] = tests

    report = generate_report(
        tiers, e2e_coverage, unit_coverage, ac_by_req,
        e2e_ac_coverage, unit_ac_coverage,
    )
    print(report)

    # Exit code gate: all P0 requirement ACs must be covered.
    # A P0 requirement is fully covered when ALL its ACs have at least
    # one E2E test tagged with that AC ID (directly or via req expansion).
    p0_reqs = tiers.get("P0", {})
    p0_uncovered_acs: list[str] = []
    for req_id in p0_reqs:
        for ac_id in ac_by_req.get(req_id, []):
            if ac_id not in e2e_ac_coverage or len(e2e_ac_coverage[ac_id]) == 0:
                p0_uncovered_acs.append(ac_id)

    if p0_uncovered_acs:
        # Count how many P0 requirements are not fully covered
        p0_incomplete_reqs = set()
        for ac_id in p0_uncovered_acs:
            # Extract parent req from AC ID: AC-01.2.3 -> REQ-01.2
            ac_match = AC_MARKER_PATTERN.search(ac_id)
            if ac_match:
                parts = ac_match.group(1).rsplit(".", 1)
                parent_req = f"REQ-{parts[0]}"
                if parent_req in p0_reqs:
                    p0_incomplete_reqs.add(parent_req)

        print(
            f"\nFAILED: {len(p0_uncovered_acs)} P0 AC(s) without E2E "
            f"test coverage across {len(p0_incomplete_reqs)} requirement(s).",
            file=sys.stderr,
        )
        return 1

    print("\nPASSED: All P0 requirement ACs have E2E test coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
