#!/usr/bin/env python3
"""PI-15 consumer: admission validators resolve logical locators (S0187)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import admit_session_candidates as adm  # noqa: E402
import path_governance as pg  # noqa: E402

REL = "sessions/01_procedencia/x.md.json"


class AdmitValidatorsLocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.local = self.base / "ws" / "out" / "local"
        self.sessions = self.local / "sessions"
        (self.sessions / "01_procedencia").mkdir(parents=True)
        (self.local / "audit").mkdir()
        self.file = self.local / REL
        self.file.write_text("{}", encoding="utf-8")
        (self.local / "audit" / "y.json").write_text("{}", encoding="utf-8")
        p = mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", self.local)
        p.start()
        self.addCleanup(p.stop)

    def test_1_source_path_logical_resolves_to_workspace(self) -> None:
        self.assertEqual(adm._validate_source_path("data/out/local/" + REL, self.sessions), (True, ""))

    def test_2_provenance_ref_logical_resolves_to_workspace(self) -> None:
        self.assertEqual(adm._validate_provenance_path("data/out/local/" + REL, self.sessions), (True, ""))

    def test_3_repo_relative_keeps_previous_behavior(self) -> None:
        for fn in (adm._validate_source_path, adm._validate_provenance_path):
            ok, msg = fn("tests/fixtures/x.md.json", self.sessions)
            self.assertFalse(ok)
            self.assertIn("must stay under", msg)
        repo = self.base / "repo"
        s = repo / "data" / "sessions"
        s.mkdir(parents=True)
        (s / "a.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(adm, "resolve_repo_path", side_effect=lambda v, d: repo / v):
            self.assertEqual(adm._validate_source_path("data/sessions/a.json", s), (True, ""))

    def test_4_absolute_legacy_still_accepted(self) -> None:
        self.assertEqual(adm._validate_source_path(str(self.file), self.sessions), (True, ""))
        self.assertEqual(adm._validate_provenance_path(str(self.file), self.sessions), (True, ""))

    def test_5_locator_outside_sessions_rejected(self) -> None:
        for fn in (adm._validate_source_path, adm._validate_provenance_path):
            ok, msg = fn("data/out/local/audit/y.json", self.sessions)
            self.assertFalse(ok)
            self.assertIn("must stay under", msg)

    def test_6_traversal_rejected(self) -> None:
        for fn in (adm._validate_source_path, adm._validate_provenance_path):
            ok, msg = fn("data/out/local/sessions/../audit/y.json", self.sessions)
            self.assertFalse(ok)
            self.assertIn("logical locator", msg)

    def test_missing_file_still_rejected(self) -> None:
        ok, msg = adm._validate_source_path("data/out/local/sessions/none.md.json", self.sessions)
        self.assertFalse(ok)
        self.assertIn("does not exist", msg)


if __name__ == "__main__":
    unittest.main()
