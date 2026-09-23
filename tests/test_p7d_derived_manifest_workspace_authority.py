#!/usr/bin/env python3
"""S0187 P7-D: derived-layer manifests read the governed workspace and persist logical locators.

unittest style: runs under pytest and under a bare interpreter.
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
import rag_derivation_preflight as preflight  # noqa: E402
import s0174_governance as s0174  # noqa: E402

FAMILIES = ("enriched", "ai", "microsoft_copilot")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class _Layout:
    """External workspace + a repo checkout that carries DECOY material at the legacy location."""

    def __init__(self, base: Path) -> None:
        self.workspace = base / "workspace"
        self.local = self.workspace / "out" / "local"
        self.repo = base / "repo"
        for fam in FAMILIES:
            _write(self.local / fam / "workspace-only.json", '{"w": 1}\n')
            _write(self.repo / "data" / "out" / "local" / fam / "repo-decoy.json", '{"decoy": 1}\n')
        _write(self.local / "reverse_html" / "derived.html", "<html></html>\n")


class DerivedManifestWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.layout = _Layout(Path(self._tmp.name).resolve())
        patcher = mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", self.layout.local)
        patcher.start()
        self.addCleanup(patcher.stop)
        pr = mock.patch.object(pg, "REPO_ROOT", self.layout.repo)
        pr.start()
        self.addCleanup(pr.stop)

    def test_manifest_reads_the_governed_workspace_and_not_the_repo_decoy(self) -> None:
        manifest = preflight.productive_derivatives_manifest()
        by_family = {f["artifact_family"]: f for f in manifest["families"]}
        for fam in FAMILIES:
            self.assertEqual(by_family[fam]["status"], "present")
            self.assertEqual(by_family[fam]["file_count"], 1)
        paths = [f["path"] for f in manifest["files"]]
        self.assertTrue(all(p.endswith("workspace-only.json") or p.endswith("derived.html") for p in paths), paths)
        self.assertFalse([p for p in paths if "repo-decoy" in p])

    def test_persisted_paths_are_logical_locators_never_physical(self) -> None:
        manifest = preflight.productive_derivatives_manifest()
        for fam in FAMILIES:
            self.assertIn(f"data/out/local/{fam}/workspace-only.json", [f["path"] for f in manifest["files"]])
        for entry in manifest["files"]:
            self.assertTrue(entry["path"].startswith("data/out/local/"), entry["path"])
            self.assertNotIn(str(self.layout.workspace), entry["path"])
            self.assertFalse(entry["path"].startswith("/"))
        for fam in manifest["families"]:
            self.assertEqual(fam["path"], f"data/out/local/{fam['artifact_family']}")

    def test_declared_families_and_diff_key_are_stable(self) -> None:
        manifest = preflight.productive_derivatives_manifest()
        self.assertEqual([f["artifact_family"] for f in manifest["families"]], [*FAMILIES, "reverse_html"])
        self.assertEqual(preflight.manifest_diff(manifest, manifest)["productive_derivatives_diff"], "empty")

    def test_explicit_root_injection_is_preserved(self) -> None:
        manifest = preflight.productive_derivatives_manifest(repo_root=self.layout.repo)
        paths = [f["path"] for f in manifest["files"]]
        self.assertEqual(sorted(paths), sorted(f"data/out/local/{fam}/repo-decoy.json" for fam in FAMILIES))

    def test_manifest_is_read_only_and_does_not_touch_canon_flags(self) -> None:
        before = sorted(p.name for p in self.layout.local.rglob("*"))
        manifest = preflight.productive_derivatives_manifest()
        self.assertEqual(before, sorted(p.name for p in self.layout.local.rglob("*")))
        self.assertIs(manifest["canon_modified"], False)
        self.assertIs(manifest["productive_derivatives_modified"], False)

    def test_root_manifest_accepts_external_workspace_roots_without_repo_relativisation(self) -> None:
        roots = {fam: self.layout.local / fam for fam in FAMILIES}
        with mock.patch.object(s0174, "PRODUCTIVE_ROOTS", roots):
            result = s0174._root_manifest()  # used to raise ValueError (relative_to(REPO_ROOT))
        self.assertEqual([f["artifact_family"] for f in result["families"]], list(FAMILIES))
        for fam in result["families"]:
            self.assertEqual(fam["path"], f"data/out/local/{fam['artifact_family']}")
            self.assertEqual(fam["status"], "present")
            self.assertEqual([f["relative_path"] for f in fam["files"]], ["workspace-only.json"])
            self.assertFalse(fam["path"].startswith("/"))

    def test_root_manifest_missing_family_reports_not_present(self) -> None:
        roots = {"enriched": self.layout.local / "enriched", "ai": self.layout.local / "absent"}
        with mock.patch.object(s0174, "PRODUCTIVE_ROOTS", roots):
            result = s0174._root_manifest()
        states = {f["artifact_family"]: f["status"] for f in result["families"]}
        self.assertEqual(states, {"enriched": "present", "ai": "not_present"})

    def test_root_manifest_rejects_material_outside_the_governed_workspace(self) -> None:
        outside = Path(self._tmp.name).resolve() / "elsewhere" / "enriched"
        outside.mkdir(parents=True)
        with mock.patch.object(s0174, "PRODUCTIVE_ROOTS", {"enriched": outside}):
            with self.assertRaises(pg.LogicalLocatorError):
                s0174._root_manifest()


class DefaultRepoDataWorkspaceTests(unittest.TestCase):
    """repo/data is a legitimate workspace when nothing external is configured: same contract."""

    def test_repo_data_workspace_gives_the_same_locators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve() / "repo"
            local = repo / "data" / "out" / "local"
            for fam in FAMILIES:
                _write(local / fam / "x.json", "{}\n")
            with mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", local), mock.patch.object(pg, "REPO_ROOT", repo):
                manifest = preflight.productive_derivatives_manifest()
                with mock.patch.object(s0174, "PRODUCTIVE_ROOTS", {f: local / f for f in FAMILIES}):
                    root = s0174._root_manifest()
            self.assertEqual(
                sorted(f["path"] for f in manifest["files"]),
                sorted(f"data/out/local/{fam}/x.json" for fam in FAMILIES),
            )
            self.assertEqual([f["path"] for f in root["families"]], [f"data/out/local/{fam}" for fam in FAMILIES])


class ContractStabilityTests(unittest.TestCase):
    def test_declared_locators_stay_in_the_stored_namespace(self) -> None:
        for family, locator in preflight.PRODUCTIVE_FAMILIES.items():
            self.assertEqual(locator, f"{pg.LOGICAL_LOCATOR_NAMESPACE}/{family}")

    def test_no_new_workspace_authority_in_the_target_modules(self) -> None:
        for module in (preflight, s0174):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for forbidden in ("TDC_WORKSPACE_ROOT", "workspace_storage.json", "os.environ"):
                self.assertNotIn(forbidden, source, f"{module.__name__} re-implements workspace resolution")


if __name__ == "__main__":
    unittest.main()
