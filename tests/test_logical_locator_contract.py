#!/usr/bin/env python3
"""Logical locator <-> physical workspace path contract (S0187 P7-C, D1).

The stored vocabulary "data/out/local/<tail>" is a LOGICAL LOCATOR; its
physical path is DEFAULT_LOCAL_OUT_DIR/<tail>. Written with unittest so it runs
under pytest and under a bare interpreter.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import path_governance as pg  # noqa: E402


class LogicalLocatorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name).resolve() / "workspace"
        self.local = self.workspace / "out" / "local"
        self.local.mkdir(parents=True)
        patcher = mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", self.local)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_namespace_is_the_stored_vocabulary(self) -> None:
        self.assertEqual(pg.LOGICAL_LOCATOR_NAMESPACE, "data/out/local")

    def test_resolve_root_and_tails(self) -> None:
        self.assertEqual(pg.resolve_logical_locator("data/out/local"), self.local)
        self.assertEqual(pg.resolve_logical_locator("data/out/local/sessions/x"), self.local / "sessions" / "x")
        self.assertEqual(pg.resolve_logical_locator("data/out/local/pipeline/x"), self.local / "pipeline" / "x")
        self.assertEqual(pg.resolve_logical_locator("data\\out\\local\\sessions\\x"), self.local / "sessions" / "x")
        self.assertEqual(pg.resolve_logical_locator("data/out/local/sessions/"), self.local / "sessions")

    def test_absolute_workspace_path_to_locator(self) -> None:
        self.assertEqual(pg.as_logical_locator(self.local), "data/out/local")
        self.assertEqual(
            pg.as_logical_locator(self.local / "sessions" / "x.md.json"),
            "data/out/local/sessions/x.md.json",
        )

    def test_round_trip_is_layout_independent(self) -> None:
        locator = "data/out/local/sessions/00_contratos/a.md.json"
        first = pg.resolve_logical_locator(locator)
        with tempfile.TemporaryDirectory() as other:
            other_local = Path(other).resolve() / "mount2" / "out" / "local"
            other_local.mkdir(parents=True)
            with mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", other_local):
                second = pg.resolve_logical_locator(locator)
                self.assertNotEqual(first, second)
                self.assertEqual(pg.as_logical_locator(second), locator)
        self.assertEqual(pg.as_logical_locator(first), locator)

    def test_canonical_logical_locator_compares_both_representations(self) -> None:
        stored = "data/out/local/sessions/x.md.json"
        physical = self.local / "sessions" / "x.md.json"
        self.assertEqual(pg.canonical_logical_locator(stored), pg.canonical_logical_locator(physical))
        self.assertEqual(pg.canonical_logical_locator(str(physical)), stored)

    def test_repo_owned_path_is_rejected(self) -> None:
        with self.assertRaises(pg.LogicalLocatorError):
            pg.as_logical_locator(pg.REPO_ROOT / "src" / "python_scripts" / "path_governance.py")
        with self.assertRaises(pg.LogicalLocatorError):
            pg.resolve_logical_locator("src/python_scripts/path_governance.py")

    def test_traversal_is_rejected(self) -> None:
        for bad in ("data/out/local/../x", "data/out/local/sessions/../../x", "../data/out/local/x"):
            with self.subTest(bad=bad), self.assertRaises(pg.LogicalLocatorError):
                pg.resolve_logical_locator(bad)
        with self.assertRaises(pg.LogicalLocatorError):
            pg.as_logical_locator(self.local / "sessions" / ".." / ".." / "x")

    def test_other_namespaces_are_rejected(self) -> None:
        for bad in ("out/local/sessions/x", "data/sessions/x", "data/out/remote/x", "data/out/localx/y",
                    "data/tmp/x", "/data/out/local/x", "", "data/out/local//x", "data/out/local/./x"):
            with self.subTest(bad=bad), self.assertRaises(pg.LogicalLocatorError):
                pg.resolve_logical_locator(bad)

    def test_non_out_local_workspace_surface_and_relative_are_rejected(self) -> None:
        with self.assertRaises(pg.LogicalLocatorError):
            pg.as_logical_locator(self.workspace / "tmp" / "x")
        with self.assertRaises(pg.LogicalLocatorError):
            pg.as_logical_locator("out/local/x")

    def test_symlink_escape_is_rejected(self) -> None:
        outside = Path(self._tmp.name).resolve() / "outside"
        outside.mkdir()
        (self.local / "escape").symlink_to(outside)
        with self.assertRaises(pg.LogicalLocatorError):
            pg.resolve_logical_locator("data/out/local/escape/secret")

    def test_display_path_is_not_a_locator(self) -> None:
        # presentation-only helper keeps its own (layout dependent) behaviour
        self.assertTrue(pg.as_display_path(self.local / "x").startswith(str(self.workspace)))


if __name__ == "__main__":
    unittest.main()
