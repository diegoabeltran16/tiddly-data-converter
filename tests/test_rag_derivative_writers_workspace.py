#!/usr/bin/env python3
"""rag_derivative_writers authority = governed workspace (S0187 P7-C)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "src" / "python_scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import path_governance as pg  # noqa: E402
import rag_derivative_writers as w  # noqa: E402


class WritersAuthorityTests(unittest.TestCase):
    def test_constants_are_the_governed_workspace_defaults(self) -> None:
        self.assertEqual(w.CANON_ROOT, pg.DEFAULT_LOCAL_OUT_DIR)
        self.assertEqual(
            dict(w.PRODUCTIVE_FAMILIES),
            {"enriched": pg.DEFAULT_ENRICHED_DIR, "ai": pg.DEFAULT_AI_DIR, "microsoft_copilot": pg.DEFAULT_MICROSOFT_COPILOT_DIR},
        )
        self.assertEqual(
            set(w.PRODUCTIVE_DERIVATIVE_ROOTS),
            {pg.DEFAULT_ENRICHED_DIR, pg.DEFAULT_AI_DIR, pg.DEFAULT_MICROSOFT_COPILOT_DIR, pg.DEFAULT_REVERSE_HTML_DIR},
        )
        self.assertEqual(set(w.EVIDENCE_ROOTS), {pg.DEFAULT_LOCAL_OUT_DIR / "pipeline", pg.DEFAULT_AUDIT_DIR})

    def test_default_family_roots_resolve_to_the_workspace(self) -> None:
        roots = w._family_roots()
        for name, path in roots.items():
            self.assertEqual(path, Path(pg.DEFAULT_LOCAL_OUT_DIR / name).resolve())

    def test_guard_protects_workspace_canon_and_productive_roots(self) -> None:
        for target in (
            pg.DEFAULT_CANON_DIR / "tiddlers_1.jsonl",
            pg.DEFAULT_CANON_DIR,
            pg.DEFAULT_ENRICHED_DIR / "x.json",
            pg.DEFAULT_AI_DIR / "x.json",
            pg.DEFAULT_MICROSOFT_COPILOT_DIR / "x.json",
            pg.DEFAULT_REVERSE_HTML_DIR / "x.html",
            pg.DEFAULT_SESSIONS_DIR / "x.md.json",
        ):
            with self.subTest(target=str(target)), self.assertRaises(w.ProductiveWriteBlocked):
                w.require_nonproductive_evidence_target(target)

    def test_guard_allows_governed_evidence_roots(self) -> None:
        for target in (pg.DEFAULT_AUDIT_DIR / "p7c" / "r.json", pg.DEFAULT_LOCAL_OUT_DIR / "pipeline" / "x" / "r.json"):
            with self.subTest(target=str(target)):
                self.assertEqual(w.require_nonproductive_evidence_target(target), Path(target).resolve())

    def test_repo_code_config_and_tests_are_not_evidence_targets(self) -> None:
        for target in (pg.REPO_ROOT / "src" / "x.py", pg.REPO_ROOT / "tests" / "x.py", pg.REPO_ROOT / ".tdc" / "x.json"):
            with self.subTest(target=str(target)), self.assertRaises(w.ProductiveWriteBlocked):
                w.require_nonproductive_evidence_target(target)

    def test_repo_pinned_legacy_locations_are_not_the_workspace(self) -> None:
        if pg.WORKSPACE_ROOT == pg.REPO_DATA_DIR:
            self.skipTest("repo-layout workspace: repo/data IS the workspace")
        legacy = pg.REPO_ROOT / "data" / "out" / "local" / "audit" / "x.json"
        with self.assertRaises(w.ProductiveWriteBlocked):
            w.require_nonproductive_evidence_target(legacy)  # D3: no evidence inside the repo by default

    def test_external_temp_targets_remain_allowed_for_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "evidence.json"
            self.assertEqual(w.require_nonproductive_evidence_target(target), target.resolve())

    def test_snapshot_observes_explicit_families_and_the_default_workspace_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            fam = {"enriched": base / "src" / "enriched"}
            (fam["enriched"]).mkdir(parents=True)
            (fam["enriched"] / "a.json").write_text("{}", encoding="utf-8")
            manifest = w.snapshot_productive_derivatives(base / "snap", productive_families=fam, session_id="T")
            self.assertEqual([f["relative_path"] for f in manifest["files"]], ["a.json"])
            self.assertEqual(sorted(w._family_roots()), ["ai", "enriched", "microsoft_copilot"])


if __name__ == "__main__":
    unittest.main()
