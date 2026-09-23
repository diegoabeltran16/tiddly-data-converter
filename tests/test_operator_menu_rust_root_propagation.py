#!/usr/bin/env python3
"""operator_menu passes the governed workspace root to every Rust doctor call
(S0187 P7-C): Python resolves, Rust validates."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import operator_menu as om  # noqa: E402
import path_governance as pg  # noqa: E402


class _Result:
    returncode = 0
    stdout = "{}"
    stderr = ""


class RustRootPropagationTests(unittest.TestCase):
    def capture(self, fn, *args, **kwargs) -> list[list[str]]:
        calls: list[list[str]] = []

        def fake_run(command, **_kw):
            calls.append(list(command))
            return _Result()

        with mock.patch.object(om.shutil, "which", return_value="/x/cargo"), \
                mock.patch.object(om, "run_command", side_effect=fake_run), \
                mock.patch("builtins.print"):
            try:
                fn(*args, **kwargs)
            except Exception:
                pass
        return calls

    def assert_workspace_root(self, calls: list[list[str]], subcommand: str) -> None:
        matching = [c for c in calls if subcommand in c]
        self.assertTrue(matching, f"no cargo call for {subcommand}")
        cmd = matching[0]
        self.assertEqual(cmd[cmd.index("--workspace-root") + 1], str(pg.WORKSPACE_ROOT))
        self.assertEqual(cmd[cmd.index(subcommand) + 1], str(pg.REPO_ROOT))  # repo_root stays the checkout

    def test_reconstruction_gate(self) -> None:
        calls = self.capture(om.run_reconstruction_gate, pg.DEFAULT_INPUT_HTML, "reverse_projection",
                             pg.DEFAULT_REVERSE_HTML, requires_backup=False, requires_hash_report=True, show_result=False)
        self.assert_workspace_root(calls, "reconstruction-plan")

    def test_rollback_gate(self) -> None:
        calls = self.capture(om.run_reconstruction_rollback_gate, pg.DEFAULT_TMP_DIR / "r.json")
        self.assert_workspace_root(calls, "reconstruction-rollback")

    def test_quality_reports(self) -> None:
        for kind in ("canonical-line-gate", "deep-node-inspect"):
            with self.subTest(kind=kind):
                calls = self.capture(om.run_doctor_quality_report, kind, pg.DEFAULT_TMP_DIR / "i.jsonl", pg.DEFAULT_TMP_DIR / "r.json")
                self.assert_workspace_root(calls, kind)

    def test_workspace_root_is_the_path_governance_object(self) -> None:
        self.assertIs(om.WORKSPACE_ROOT, pg.WORKSPACE_ROOT)


if __name__ == "__main__":
    unittest.main()
