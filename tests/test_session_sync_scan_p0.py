"""P0 contract tests for session_sync.scan_session_sync — S0117.

Verifies classification of session artifacts: missing_by_id, existing_by_id,
blocked_same_id_different_content, replaceable_same_id_different_content,
invalid, and unsupported. _run_normalize and _load_canon_index are mocked to
avoid Go binary dependencies and real canon access.

Para ejecutar en aislamiento:
    pytest tests/test_session_sync_scan_p0.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "src" / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import session_sync as ss  # noqa: E402
from admit_session_candidates import (  # noqa: E402
    CanonIndex,
    CanonRecord,
    _canonical_json,
    _project_candidate_record_as_admitted,
)

FIXTURES_S0117 = REPO_ROOT / "tests" / "fixtures" / "s0117"
SESSIONS_DIR = FIXTURES_S0117 / "sessions"
VALID_CONTRATO = SESSIONS_DIR / "00_contratos" / "m04-s0117-fixture-contrato.md.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_canon_index() -> CanonIndex:
    return CanonIndex(
        by_id={}, by_key={}, by_slug={}, by_source_path={},
        by_session_family={}, by_hash={}, by_title={},
    )


def _normalize_mock(id_prefix: str = "test-id"):
    """Return a _run_normalize mock that stamps records with deterministic ids."""
    def _mock(raw_records, work_dir):
        normalized = [{**r, "id": f"{id_prefix}-{i}"} for i, r in enumerate(raw_records)]
        return normalized, MagicMock()
    return _mock


def _canon_record_for(normalized_record: dict, source_path: str = "") -> CanonRecord:
    """Build a CanonRecord whose serialized form matches the normalized record."""
    rec = normalized_record.copy()
    if source_path:
        rec.setdefault("source_fields", {})["source_path"] = source_path
    return CanonRecord(
        record=rec,
        serialized=_canonical_json(normalized_record),
        shard="tiddlers_1.jsonl",
        line_no=1,
    )


def _canon_index_with(record_id: str, canon_record: CanonRecord) -> CanonIndex:
    return CanonIndex(
        by_id={record_id: canon_record},
        by_key={}, by_slug={}, by_source_path={},
        by_session_family={}, by_hash={}, by_title={},
    )


def _run_scan(
    sessions_dir: Path,
    out_dir: Path,
    normalize_mock=None,
    canon_index: CanonIndex | None = None,
    run_id: str = "test-run",
) -> dict:
    if normalize_mock is None:
        normalize_mock = _normalize_mock()
    if canon_index is None:
        canon_index = _empty_canon_index()
    with (
        patch.object(ss, "_run_normalize", side_effect=normalize_mock),
        patch.object(ss, "_load_canon_index", return_value=canon_index),
    ):
        return ss.scan_session_sync(
            sessions_dir=sessions_dir,
            canon_dir=REPO_ROOT / "data" / "out" / "local",
            out_dir=out_dir,
            run_id=run_id,
        )


# ── Preconditions ─────────────────────────────────────────────────────────────

class TestS0117FixturesExist:
    def test_sessions_dir_exists(self):
        assert SESSIONS_DIR.exists(), f"Fixture sessions dir missing: {SESSIONS_DIR}"

    def test_valid_contrato_fixture_exists(self):
        assert VALID_CONTRATO.exists(), f"Fixture missing: {VALID_CONTRATO}"

    def test_valid_contrato_is_valid_json(self):
        # S0128: fixture updated to canonical dict format (generator schema).
        # Old TiddlyWiki list format [{"title": ...}] is no longer valid per schema.
        payload = json.loads(VALID_CONTRATO.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        assert payload.get("title")

    def test_module_imports_cleanly(self):
        assert hasattr(ss, "scan_session_sync")
        assert hasattr(ss, "build_candidate_from_artifact")


# ── B1: valid artifact → missing_by_id ────────────────────────────────────────

class TestB1ValidArtifact:
    """A valid .md.json in a known family folder lands in missing_by_id."""

    def test_missing_by_id_has_one_entry(self, tmp_path):
        inv = _run_scan(SESSIONS_DIR, tmp_path)
        assert len(inv["missing_by_id"]) == 1

    def test_missing_entry_has_correct_classification(self, tmp_path):
        inv = _run_scan(SESSIONS_DIR, tmp_path)
        entry = inv["missing_by_id"][0]
        assert entry["classification"] == "missing_by_id"

    def test_total_session_records_equals_one(self, tmp_path):
        inv = _run_scan(SESSIONS_DIR, tmp_path)
        assert inv["total_session_records"] == 1

    def test_inventory_json_written_to_run_dir(self, tmp_path):
        _run_scan(SESSIONS_DIR, tmp_path, run_id="inv-b1")
        inventory_path = tmp_path / "inv-b1" / "inventory.json"
        assert inventory_path.exists()
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
        assert data["run_id"] == "inv-b1"

    def test_no_invalid_entries(self, tmp_path):
        inv = _run_scan(SESSIONS_DIR, tmp_path)
        assert inv["invalid"] == []


# ── B2: invalid JSON → invalid ────────────────────────────────────────────────

class TestB2InvalidJson:
    """A .md.json file with malformed JSON is classified as invalid."""

    def test_invalid_json_file_lands_in_invalid(self, tmp_path):
        sess = tmp_path / "sessions" / "00_contratos"
        sess.mkdir(parents=True)
        bad = sess / "m04-s0117-bad.md.json"
        bad.write_text("{ this is not valid json }", encoding="utf-8")

        inv = _run_scan(tmp_path / "sessions", tmp_path / "out")
        assert len(inv["invalid"]) == 1

    def test_invalid_json_classification_field(self, tmp_path):
        sess = tmp_path / "sessions" / "00_contratos"
        sess.mkdir(parents=True)
        (sess / "m04-s0117-bad.md.json").write_text("{broken", encoding="utf-8")

        inv = _run_scan(tmp_path / "sessions", tmp_path / "out")
        assert inv["invalid"][0]["classification"] == "invalid"

    def test_invalid_json_entry_contains_path(self, tmp_path):
        sess = tmp_path / "sessions" / "00_contratos"
        sess.mkdir(parents=True)
        bad_path = sess / "m04-s0117-bad.md.json"
        bad_path.write_text("not-json", encoding="utf-8")

        inv = _run_scan(tmp_path / "sessions", tmp_path / "out")
        assert any("m04-s0117-bad" in entry["path"] for entry in inv["invalid"])


# ── B3: missing title → invalid ───────────────────────────────────────────────

class TestB3MissingTitle:
    """A .md.json with an empty title field is classified as invalid."""

    def _write_notitle(self, target_dir: Path, name: str = "m04-s0117-notitle.md.json"):
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / name).write_text(
            json.dumps([{
                "created": "20260516000000000",
                "modified": "20260516000000000",
                "title": "",
                "type": "text/markdown",
                "text": "Sin título.",
            }]),
            encoding="utf-8",
        )

    def test_missing_title_lands_in_invalid(self, tmp_path):
        sess = tmp_path / "sessions" / "00_contratos"
        self._write_notitle(sess)
        inv = _run_scan(tmp_path / "sessions", tmp_path / "out")
        assert len(inv["invalid"]) == 1

    def test_missing_title_classification_field(self, tmp_path):
        sess = tmp_path / "sessions" / "00_contratos"
        self._write_notitle(sess)
        inv = _run_scan(tmp_path / "sessions", tmp_path / "out")
        # S0128: files with structural schema errors (list format, missing title)
        # are now classified as "schema_invalid" by the pre-build schema gate.
        assert inv["invalid"][0]["classification"] in ("invalid", "schema_invalid")

    def test_missing_title_does_not_appear_in_missing_by_id(self, tmp_path):
        sess = tmp_path / "sessions" / "00_contratos"
        self._write_notitle(sess)
        inv = _run_scan(tmp_path / "sessions", tmp_path / "out")
        assert inv["missing_by_id"] == []


# ── B4: same ID + same content → existing_by_id ───────────────────────────────

class TestB4ExistingById:
    """A candidate whose id and content already exist in canon is existing_by_id."""

    def _build_normalized(self) -> dict:
        # _normalize_candidates adds raw_payload_ref after the mock returns, so
        # the final candidate.record in scan_session_sync has all three mutations.
        candidate = ss.build_candidate_from_artifact(VALID_CONTRATO, SESSIONS_DIR)
        return {**candidate.record, "id": "test-id-0", "raw_payload_ref": "node:test-id-0"}

    def test_existing_by_id_when_content_matches(self, tmp_path):
        normalized_record = self._build_normalized()
        canon_rec = _canon_record_for(normalized_record)
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx)
        assert len(inv["existing_by_id"]) == 1

    def test_existing_entry_has_correct_classification(self, tmp_path):
        normalized_record = self._build_normalized()
        canon_rec = _canon_record_for(normalized_record)
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx)
        assert inv["existing_by_id"][0]["classification"] == "existing_by_id"

    def test_existing_by_id_not_in_missing(self, tmp_path):
        normalized_record = self._build_normalized()
        canon_rec = _canon_record_for(normalized_record)
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx)
        assert inv["missing_by_id"] == []


# ── B5: same ID + different content + different source → blocked ───────────────

class TestB5BlockedSameId:
    """Same id, different content, unrelated source_path → blocked_same_id_different_content."""

    def test_blocked_classification(self, tmp_path):
        different_content_record = {"id": "test-id-0", "key": "different-content"}
        canon_rec = CanonRecord(
            record={"source_fields": {"source_path": "/completely/different/source.md.json"}},
            serialized=_canonical_json(different_content_record),
            shard="tiddlers_1.jsonl",
            line_no=1,
        )
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx)
        assert len(inv["blocked_same_id_different_content"]) == 1

    def test_blocked_entry_has_correct_classification(self, tmp_path):
        different_content_record = {"id": "test-id-0", "key": "other"}
        canon_rec = CanonRecord(
            record={"source_fields": {"source_path": "/unrelated/path.md.json"}},
            serialized=_canonical_json(different_content_record),
            shard="tiddlers_1.jsonl",
            line_no=1,
        )
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx)
        entry = inv["blocked_same_id_different_content"][0]
        assert entry["classification"] == "blocked_same_id_different_content"

    def test_blocked_not_in_missing_or_existing(self, tmp_path):
        different_content_record = {"id": "test-id-0", "key": "other"}
        canon_rec = CanonRecord(
            record={"source_fields": {"source_path": "/unrelated/path.md.json"}},
            serialized=_canonical_json(different_content_record),
            shard="tiddlers_1.jsonl",
            line_no=1,
        )
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx)
        assert inv["missing_by_id"] == []
        assert inv["existing_by_id"] == []


# ── B6: same ID + different content + same source → replaceable ───────────────

class TestB6ReplaceSameSource:
    """Same id, different content, same source_path → replaceable_same_id_different_content."""

    def test_replaceable_classification(self, tmp_path):
        candidate = ss.build_candidate_from_artifact(VALID_CONTRATO, SESSIONS_DIR)
        fixture_source_path = candidate.record["source_fields"]["source_path"]
        different_content_record = {"id": "test-id-0", "different": "content"}
        canon_rec = CanonRecord(
            record={"source_fields": {"source_path": fixture_source_path}},
            serialized=_canonical_json(different_content_record),
            shard="tiddlers_1.jsonl",
            line_no=1,
        )
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx)
        assert len(inv["replaceable_same_id_different_content"]) >= 1

    def test_replaceable_entry_classification_field(self, tmp_path):
        candidate = ss.build_candidate_from_artifact(VALID_CONTRATO, SESSIONS_DIR)
        fixture_source_path = candidate.record["source_fields"]["source_path"]
        canon_rec = CanonRecord(
            record={"source_fields": {"source_path": fixture_source_path}},
            serialized=_canonical_json({"id": "test-id-0", "x": "y"}),
            shard="tiddlers_1.jsonl",
            line_no=1,
        )
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx)
        entry = inv["replaceable_same_id_different_content"][0]
        assert entry["classification"] in (
            "replaceable_same_id_different_content",
            "replaceable_migrated_source_path",
        )


# ── B7: generated_candidate_file when missing candidates exist ─────────────────

class TestB7GeneratedCandidateFile:
    """sync-candidates.canon-candidates.jsonl is written when missing_by_id > 0."""

    def test_sync_candidates_file_created(self, tmp_path):
        _run_scan(SESSIONS_DIR, tmp_path, run_id="b7-run")
        candidate_file = tmp_path / "b7-run" / "sync-candidates.canon-candidates.jsonl"
        assert candidate_file.exists(), "sync-candidates.canon-candidates.jsonl not created"

    def test_missing_candidates_file_created(self, tmp_path):
        _run_scan(SESSIONS_DIR, tmp_path, run_id="b7-missing")
        candidate_file = tmp_path / "b7-missing" / "missing-candidates.canon-candidates.jsonl"
        assert candidate_file.exists(), "missing-candidates.canon-candidates.jsonl not created"

    def test_sync_candidates_file_contains_valid_jsonl(self, tmp_path):
        _run_scan(SESSIONS_DIR, tmp_path, run_id="b7-valid")
        candidate_file = tmp_path / "b7-valid" / "sync-candidates.canon-candidates.jsonl"
        lines = [l for l in candidate_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) >= 1
        for line in lines:
            json.loads(line)  # must be valid JSON

    def test_no_candidate_file_when_all_existing(self, tmp_path):
        candidate = ss.build_candidate_from_artifact(VALID_CONTRATO, SESSIONS_DIR)
        # raw_payload_ref is added by _normalize_candidates before comparison
        normalized_record = {**candidate.record, "id": "test-id-0", "raw_payload_ref": "node:test-id-0"}
        canon_rec = _canon_record_for(normalized_record)
        idx = _canon_index_with("test-id-0", canon_rec)

        inv = _run_scan(SESSIONS_DIR, tmp_path, canon_index=idx, run_id="b7-existing")
        assert inv["generated_candidate_file"] is None


# ── B8: migrated path → replaceable_migrated_source_path ─────────────────────

class TestB8MigratedPath:
    """An artifact whose canon entry has the old data/sessions/ prefix is replaceable."""

    def test_migrated_source_path_classified_as_replaceable(self, tmp_path):
        # The migration check compares source_paths with the prefix pairs in
        # _MIGRATION_PATH_PREFIXES: "data/sessions/" → "data/out/local/sessions/".
        # We inject the new path via a custom normalize mock so the test doesn't
        # depend on the fixture's actual location on disk.
        suffix = "00_contratos/m04-s0117-migrated-test.md.json"
        new_source = f"data/out/local/sessions/{suffix}"
        old_source = f"data/sessions/{suffix}"

        def normalize_with_migration_path(raw_records, work_dir):
            normalized = []
            for i, r in enumerate(raw_records):
                rec = dict(r)
                rec["id"] = f"b8-id-{i}"
                rec.setdefault("source_fields", {})["source_path"] = new_source
                normalized.append(rec)
            return normalized, MagicMock()

        canon_rec = CanonRecord(
            record={"source_fields": {"source_path": old_source}},
            serialized=_canonical_json({"id": "b8-id-0", "different": "old-content"}),
            shard="tiddlers_1.jsonl",
            line_no=1,
        )
        idx = _canon_index_with("b8-id-0", canon_rec)

        inv = _run_scan(
            SESSIONS_DIR, tmp_path,
            normalize_mock=normalize_with_migration_path,
            canon_index=idx,
        )
        replaceable = inv["replaceable_same_id_different_content"]
        assert len(replaceable) >= 1
        assert any(e["classification"] == "replaceable_migrated_source_path" for e in replaceable)

    def test_unsupported_file_classified_correctly(self, tmp_path):
        sess = tmp_path / "sessions" / "00_contratos"
        sess.mkdir(parents=True)
        # Put a non-.md.json file in the sessions dir
        (sess / "README.txt").write_text("not a tiddler", encoding="utf-8")
        inv = _run_scan(tmp_path / "sessions", tmp_path / "out")
        assert len(inv["unsupported"]) == 1
        assert inv["unsupported"][0]["classification"] == "unsupported"
