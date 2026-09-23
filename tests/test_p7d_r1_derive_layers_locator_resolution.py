#!/usr/bin/env python3
"""S0187 P7-D-R1: derive_layers._resolve_rag_path resolves stored logical locators through the
governed workspace (never REPO_ROOT) while preserving absolute and repo-owned relative semantics.

unittest style: runs under pytest and under a bare interpreter.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import derive_layers as dl  # noqa: E402
import path_governance as pg  # noqa: E402

POLICIES = {
    "tag_policy_path": "data/out/local/pipeline/tag_sanitation/s0169/tag_sanitation_policy.json",
    "metadata_policy_path": "data/out/local/pipeline/metadata_promotion/s0171/metadata_promotion_policy.json",
    "semantic_type_policy_path": "data/out/local/pipeline/relation_type_governance/s0139/s0139_historical_relation_type_decisions.json",
}


class ResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()
        self.local = base / "workspace" / "out" / "local"
        self.repo = base / "repo"
        for locator in POLICIES.values():
            tail = locator[len("data/out/local/"):]
            for root, marker in ((self.local, "WORKSPACE"), (self.repo / "data" / "out" / "local", "REPO_DECOY")):
                target = root / tail
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"marker": marker}), encoding="utf-8")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "x.md").write_text("repo-owned", encoding="utf-8")
        for patcher in (
            mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", self.local),
            mock.patch.object(dl, "REPO_ROOT", self.repo),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def marker(self, path: Path) -> str:
        return json.loads(path.read_text(encoding="utf-8"))["marker"]

    def test_logical_locator_resolves_to_the_governed_workspace(self) -> None:
        resolved = dl._resolve_rag_path("data/out/local/pipeline/tag_sanitation/s0169/tag_sanitation_policy.json", Path("/unused"))
        self.assertEqual(resolved, (self.local / "pipeline/tag_sanitation/s0169/tag_sanitation_policy.json").resolve())
        self.assertFalse(str(resolved).startswith(str(self.repo)))

    def test_workspace_wins_against_repo_decoy_for_all_three_profile_policies(self) -> None:
        for key, locator in POLICIES.items():
            with self.subTest(policy=key):
                resolved = dl._resolve_rag_path(locator, Path("/unused-default"))
                self.assertEqual(self.marker(resolved), "WORKSPACE")
                self.assertTrue(str(resolved).startswith(str(self.local)))
                self.assertFalse(str(resolved).startswith(str(self.repo)))

    def test_absolute_path_is_kept_absolute(self) -> None:
        absolute = self.repo / "data" / "out" / "local" / "pipeline" / "tag_sanitation" / "s0169" / "tag_sanitation_policy.json"
        self.assertEqual(dl._resolve_rag_path(str(absolute), Path("/x")), absolute.resolve())

    def test_repo_owned_relative_path_keeps_repo_semantics(self) -> None:
        self.assertEqual(dl._resolve_rag_path("docs/x.md", Path("/x")), (self.repo / "docs" / "x.md").resolve())

    def test_empty_value_uses_the_default_as_before(self) -> None:
        default = self.local / "pipeline" / "d.json"
        self.assertEqual(dl._resolve_rag_path(None, default), default.resolve())
        self.assertEqual(dl._resolve_rag_path("", default), default.resolve())

    def test_locator_with_traversal_fails_closed_never_repo_relative(self) -> None:
        with self.assertRaises(pg.LogicalLocatorError):
            dl._resolve_rag_path("data/out/local/../../docs/x.md", Path("/x"))

    def test_similar_prefix_is_not_the_namespace(self) -> None:
        resolved = dl._resolve_rag_path("data/out/localx/y.json", Path("/x"))
        self.assertEqual(resolved, (self.repo / "data" / "out" / "localx" / "y.json").resolve())

    def test_resolution_does_not_write_or_touch_the_profile(self) -> None:
        profile = self.local / "pipeline" / "rag_derivation" / "s0172" / "rag_derivation_profile.json"
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(json.dumps({**POLICIES}), encoding="utf-8")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        stored = json.loads(profile.read_text(encoding="utf-8"))
        for key in POLICIES:
            dl._resolve_rag_path(stored[key], Path("/x"))
            self.assertTrue(stored[key].startswith("data/out/local/"))  # stored value stays a locator
        self.assertEqual(before, hashlib.sha256(profile.read_bytes()).hexdigest())

    def test_default_layout_repo_data_is_the_same_contract(self) -> None:
        local = self.repo / "data" / "out" / "local"
        with mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", local):
            resolved = dl._resolve_rag_path(POLICIES["tag_policy_path"], Path("/x"))
        self.assertEqual(self.marker(resolved), "REPO_DECOY")  # here repo/data IS the workspace
        self.assertEqual(resolved, (self.repo / POLICIES["tag_policy_path"]).resolve())

if __name__ == "__main__":
    unittest.main()
