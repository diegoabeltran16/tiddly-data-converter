#!/usr/bin/env python3
"""GATE-022 repo_path_status (S0187 P7-C, B4): no lstrip("./"), no cwd, locators
resolved through path_governance."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import path_governance as pg  # noqa: E402
import relation_admission_gate as gate  # noqa: E402


class RepoPathStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.local = base / "workspace" / "out" / "local"
        (self.local / "sessions").mkdir(parents=True)
        (self.local / "sessions" / "a.md.json").write_text("{}", encoding="utf-8")
        self.repo = base / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "m.py").write_text("", encoding="utf-8")
        (self.repo / ".github" / "workflows").mkdir(parents=True)
        (self.repo / ".github" / "workflows" / "ci.yml").write_text("", encoding="utf-8")
        mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", self.local).start()
        mock.patch.object(gate, "REPO_ROOT", self.repo).start()
        self.addCleanup(mock.patch.stopall)
        # the process cwd is deliberately unrelated to both roots
        self._cwd = os.getcwd()

    def status(self, value: str, lifecycle: str = "active") -> str:
        return gate.repo_path_status(value, lifecycle)

    def test_existing_absolute_workspace_path_is_current(self) -> None:
        self.assertEqual(self.status(str(self.local / "sessions" / "a.md.json")), "current")

    def test_existing_absolute_repo_path_is_current(self) -> None:
        self.assertEqual(self.status(str(self.repo / "src" / "m.py")), "current")

    def test_dot_slash_relative_repo_path_is_current(self) -> None:
        self.assertEqual(self.status("./src/m.py"), "current")
        self.assertEqual(self.status("src/m.py"), "current")

    def test_hidden_directory_keeps_its_dot(self) -> None:
        self.assertEqual(self.status(".github/workflows/ci.yml"), "current")
        self.assertEqual(self.status("./.github/workflows/ci.yml"), "current")

    def test_logical_locator_resolves_through_workspace(self) -> None:
        self.assertEqual(self.status("data/out/local/sessions/a.md.json"), "current")

    def test_missing_governed_locator_is_stale(self) -> None:
        self.assertEqual(self.status("data/out/local/sessions/missing.md.json"), "stale")

    def test_locator_with_traversal_is_stale_not_repo_relative(self) -> None:
        self.assertEqual(self.status("data/out/local/../../src/m.py"), "stale")

    def test_repo_relative_is_checked_against_repo_root_not_cwd(self) -> None:
        self.assertNotEqual(Path(self._cwd).resolve(), self.repo)
        self.assertEqual(self.status("src/m.py"), "current")
        self.assertEqual(self.status("src/absent.py"), "stale")

    def test_legacy_data_sessions_is_repo_relative_and_stale(self) -> None:
        # contract: data/sessions/ is the pre-S66 legacy root, not the workspace locator
        self.assertEqual(self.status("data/sessions/00_contratos/x.md.json"), "stale")
        self.assertEqual(self.status("data/sessions/00_contratos/x.md.json", "historical_snapshot"), "historical")

    def test_lifecycle_and_special_values_follow_existing_contract(self) -> None:
        self.assertEqual(self.status(""), "not_applicable")
        self.assertEqual(self.status("src/absent.py", "deleted_historical"), "historical")
        self.assertEqual(self.status("src/rust/doctor/target/debug/x"), "build_artifact")
        self.assertEqual(self.status(".pytest_cache/v/cache"), "build_artifact")
        self.assertEqual(self.status("data/out/local/enriched/x.json"), "build_artifact")
        self.assertEqual(self.status(str(self.local / "ai" / "x.jsonl")), "build_artifact")


if __name__ == "__main__":
    unittest.main()
