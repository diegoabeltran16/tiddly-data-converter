#!/usr/bin/env python3
"""Productive reverse route passes --store-policy replace explicitly (S0187 P7-C-R1)."""

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
    def __init__(self, rc=0):
        self.returncode = rc
        self.stdout = ""
        self.stderr = ""


class ReverseStorePolicyTests(unittest.TestCase):
    def run_route(self) -> list[list[str]]:
        calls: list[list[str]] = []

        def fake_run(command, **_kw):
            calls.append([str(c) for c in command])
            return _Result()

        html = Path("/x/data/in/base.html")
        with mock.patch.object(om, "choose_html", return_value=html), \
                mock.patch.object(om, "run_reconstruction_gate", return_value=(True, {"verdict": "allowed"}, _Result())), \
                mock.patch.object(om, "run_preflight", return_value=_Result()), \
                mock.patch.object(om, "prompt", return_value="REVERSE"), \
                mock.patch.object(om, "tdc_cat_loading"), \
                mock.patch.object(om, "run_command", side_effect=fake_run), \
                mock.patch.object(om, "print_command_result"), \
                mock.patch.object(om, "write_reconstruction_report", return_value=Path("/tmp/r.json")), \
                mock.patch("builtins.print"):
            try:
                om.option_reverse(om.MenuState())
            except Exception:
                pass
        return calls

    def reverse_cmd(self) -> list[str]:
        cmds = [c for c in self.run_route() if "./cmd/reverse_tiddlers" in c]
        self.assertEqual(len(cmds), 1)
        return cmds[0]

    def test_store_policy_is_explicit_replace(self) -> None:
        cmd = self.reverse_cmd()
        self.assertIn("--store-policy", cmd)
        self.assertEqual(cmd[cmd.index("--store-policy") + 1], "replace")

    def test_route_does_not_depend_on_cli_default(self) -> None:
        cmd = self.reverse_cmd()
        self.assertNotIn("preserve", cmd)
        self.assertEqual(om.REVERSE_PRODUCTIVE_STORE_POLICY, "replace")

    def test_mode_and_governed_paths_unchanged(self) -> None:
        cmd = self.reverse_cmd()
        self.assertEqual(cmd[cmd.index("--mode") + 1], "authoritative-upsert")
        self.assertEqual(cmd[cmd.index("--canon") + 1], str(pg.DEFAULT_CANON_DIR))
        self.assertEqual(cmd[cmd.index("--out-html") + 1], str(pg.DEFAULT_REVERSE_HTML))


if __name__ == "__main__":
    unittest.main()
