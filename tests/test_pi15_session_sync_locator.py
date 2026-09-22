#!/usr/bin/env python3
"""PI-15: session_sync persists the logical locator, never a physical path (S0187).

Written with unittest so it runs under pytest and under a bare interpreter.
_run_normalize and _load_canon_index are mocked (no Go, no real Canon).
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import path_governance as pg  # noqa: E402
import session_sync as ss  # noqa: E402
from admit_session_candidates import (  # noqa: E402
    CanonIndex,
    CanonRecord,
    _canonical_json,
    _project_candidate_record_as_admitted,
)

FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "s0117" / "sessions" / "00_contratos" / "m04-s0117-fixture-contrato.md.json"
)
REL = "sessions/00_contratos/m04-s0117-fixture-contrato.md.json"


def _normalize(raw_records, work_dir):
    return [{**r, "id": f"pi15-{i}"} for i, r in enumerate(raw_records)], mock.MagicMock()


def _index(record_id: str, record: dict) -> CanonIndex:
    canon_record = CanonRecord(record=record, serialized=_canonical_json(record), shard="tiddlers_1.jsonl", line_no=1)
    return CanonIndex(
        by_id={record_id: canon_record}, by_key={}, by_slug={}, by_source_path={},
        by_session_family={}, by_hash={}, by_title={},
    )


def _empty_index() -> CanonIndex:
    return CanonIndex(
        by_id={}, by_key={}, by_slug={}, by_source_path={}, by_session_family={}, by_hash={}, by_title={},
    )


class PI15SessionSyncLocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.local = self.base / "external_workspace" / "out" / "local"
        self.artifact = self.local / REL
        self.artifact.parent.mkdir(parents=True)
        shutil.copy(FIXTURE, self.artifact)
        self.sessions = self.local / "sessions"
        patcher = mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", self.local)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _scan(self, index: CanonIndex) -> dict:
        with mock.patch.object(ss, "_run_normalize", side_effect=_normalize), mock.patch.object(
            ss, "_load_canon_index", return_value=index
        ):
            return ss.scan_session_sync(
                sessions_dir=self.sessions, canon_dir=self.base / "canon", out_dir=self.base / "out", run_id="pi15"
            )

    def _scanned_record(self) -> dict:
        inv = self._scan(_empty_index())
        line = Path(inv["generated_missing_candidate_file"]).read_text(encoding="utf-8").splitlines()[0]
        return json.loads(line)

    # A: external workspace: physical path differs from the persisted value
    def test_a_external_workspace_persists_logical_locator(self) -> None:
        cand = ss.build_candidate_from_artifact(self.artifact, self.sessions)
        expected = "data/out/local/" + REL
        fields = cand.record["source_fields"]
        self.assertEqual(fields["source_path"], expected)
        self.assertEqual(cand.record["source_position"], expected)
        self.assertTrue(fields["provenance_ref"].startswith("data/out/local/sessions/"))
        self.assertNotEqual(fields["source_path"], str(self.artifact))
        self.assertEqual(pg.resolve_logical_locator(fields["source_path"]), self.artifact)

    # B: default in-repo workspace: display path and logical locator coincide
    def test_b_in_repo_workspace_representations_coincide(self) -> None:
        repo = self.base / "repo"
        local = repo / "data" / "out" / "local"
        artifact = local / REL
        artifact.parent.mkdir(parents=True)
        shutil.copy(FIXTURE, artifact)
        with mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", local), mock.patch.object(pg, "REPO_ROOT", repo):
            cand = ss.build_candidate_from_artifact(artifact, local / "sessions")
            self.assertEqual(cand.record["source_fields"]["source_path"], pg.as_display_path(artifact))
        self.assertEqual(cand.record["source_fields"]["source_path"], "data/out/local/" + REL)

    # C: no physical prefix is persisted in any of the three path fields
    def test_c_no_absolute_or_physical_path_persisted(self) -> None:
        cand = ss.build_candidate_from_artifact(self.artifact, self.sessions)
        values = [
            cand.record["source_fields"]["source_path"],
            cand.record["source_fields"]["provenance_ref"],
            cand.record["source_position"],
        ]
        for value in values:
            self.assertFalse(value.startswith("/"), value)
            self.assertNotIn(str(self.base), value)
            for forbidden in ("/tdc/workspace", "/home", "/repositorios"):
                self.assertNotIn(forbidden, value)

    # D: prior states are still recognised
    def test_d_migration_and_canonical_comparison_still_work(self) -> None:
        self.assertTrue(ss._is_migration_equivalent_path("data/sessions/a/b.json", "data/out/local/sessions/a/b.json"))
        self.assertTrue(ss._is_migration_equivalent_path("data/out/sessions/a/b.json", "data/out/local/sessions/a/b.json"))
        self.assertFalse(ss._is_migration_equivalent_path("data/sessions/a/b.json", "data/out/local/sessions/a/c.json"))
        self.assertEqual(pg.canonical_logical_locator(self.local / REL), "data/out/local/" + REL)
        self.assertEqual(pg.canonical_logical_locator("data/out/local/" + REL), "data/out/local/" + REL)

    # E: an existing deliverable persisted with physical paths is not a new identity
    def test_e_existing_physical_record_is_same_not_new_identity(self) -> None:
        legacy = copy.deepcopy(_project_candidate_record_as_admitted(self._scanned_record()))
        legacy["source_fields"]["source_path"] = str(self.artifact)
        legacy["source_fields"]["provenance_ref"] = str(self.artifact)
        legacy["source_position"] = str(self.artifact)
        inv = self._scan(_index("pi15-0", legacy))
        self.assertEqual(len(inv["existing_by_id"]), 1)
        self.assertEqual(len(inv["missing_by_id"]), 0)
        self.assertEqual(len(inv["replaceable_same_id_different_content"]), 0)
        self.assertEqual(len(inv["source_path_identity_drift"]), 0)
        self.assertEqual([d["canonical_compare"] for d in inv["family_decisions"]], ["SAME"])

    def test_e2_content_change_is_replacement_without_path_change(self) -> None:
        legacy = copy.deepcopy(_project_candidate_record_as_admitted(self._scanned_record()))
        legacy["source_fields"]["source_path"] = str(self.artifact)
        legacy["text"] = "older text"
        inv = self._scan(_index("pi15-0", legacy))
        self.assertEqual(len(inv["existing_by_id"]), 0)
        entries = inv["replaceable_same_id_different_content"]
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["source_path_changed"])
        self.assertEqual(entries[0]["source_path"], "data/out/local/" + REL)
        self.assertEqual([d["canonical_compare"] for d in inv["family_decisions"]], ["REPLACEMENT"])

    def test_e3_out_of_workspace_fixture_keeps_display_path(self) -> None:
        with mock.patch.object(pg, "DEFAULT_LOCAL_OUT_DIR", self.base / "elsewhere" / "out" / "local"):
            cand = ss.build_candidate_from_artifact(self.artifact, self.sessions)
        self.assertEqual(cand.record["source_fields"]["source_path"], pg.as_display_path(self.artifact))


if __name__ == "__main__":
    unittest.main()
