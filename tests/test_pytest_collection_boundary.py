#!/usr/bin/env python3
"""S0187 Unit E (F-06 / C-R handoff) — pytest collection boundary.

Proves the guard declared in ../pytest.ini is actually enforced, not just
documented: a bare `pytest` invocation from the repo root must only ever
collect nodeids under tests/, never from vendored or externally-sourced
material such as .venv/ or data/refs/ (a path that has existed in prior
checkouts). GIT_IGNORED != TOOL_EXECUTION_BOUNDARY.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from path_governance import REPO_ROOT  # noqa: E402


def test_bare_pytest_invocation_never_collects_outside_tests():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    nodeids = [line for line in result.stdout.splitlines() if "::" in line]
    assert nodeids, f"no nodeids collected; stdout={result.stdout!r} stderr={result.stderr!r}"
    for nodeid in nodeids:
        assert nodeid.startswith("tests/"), f"pytest collection escaped tests/: {nodeid}"
        assert ".venv" not in nodeid
        assert "data/refs" not in nodeid
