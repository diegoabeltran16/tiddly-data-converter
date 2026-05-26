"""Tests for canon_sanitation.py — S0121.

Verifies scan, search, plan building, dry-run, and apply operations using
fixture shards.  The real canon is never modified; all tests use tmp_path.

Para ejecutar en aislamiento:
    pytest tests/test_canon_sanitation.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canon_sanitation import (  # noqa: E402
    EliminationPlan,
    NonConformingLine,
    REASON_DUPLICATE_ID,
    REASON_INVALID_JSON,
    REASON_MISSING_ID,
    REASON_MISSING_TEXT,
    REASON_MISSING_TITLE,
    apply_elimination_plan,
    build_elimination_plan,
    format_nonconforming_summary,
    load_last_plan,
    parse_index_selection,
    save_plan,
    scan_canon_for_nonconforming,
    search_canon_by_id,
    search_canon_by_title,
)


# ── Fixture helpers ───────────────────────────────────────────────────────────

def _canon_dir(tmp_path: Path) -> Path:
    d = tmp_path / "canon"
    d.mkdir(parents=True)
    return d


def _write_shard(canon_dir: Path, name: str, records: list) -> Path:
    """Write a shard file with the given records (one JSON per line)."""
    path = canon_dir / name
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            if isinstance(rec, str):
                fh.write(rec + "\n")
            else:
                fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def _valid_record(idx: int) -> dict:
    return {
        "id": f"id-{idx:04d}",
        "title": f"Título {idx}",
        "text": f"Texto del tiddler {idx}.",
        "schema_version": "v0",
    }


# ── TestScanCanonForNonconforming ─────────────────────────────────────────────

class TestScanCanonForNonconforming:
    def test_clean_shard_returns_empty(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            _valid_record(1),
            _valid_record(2),
        ])
        results = scan_canon_for_nonconforming(canon)
        assert results == []

    def test_invalid_json_detected(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            _valid_record(1),
            "{ this is not valid json }",
            _valid_record(3),
        ])
        results = scan_canon_for_nonconforming(canon)
        assert len(results) == 1
        assert results[0].reason == REASON_INVALID_JSON

    def test_missing_id_detected(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            {"title": "Sin ID", "text": "texto"},
        ])
        results = scan_canon_for_nonconforming(canon)
        assert any(nc.reason == REASON_MISSING_ID for nc in results)

    def test_missing_title_detected(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            {"id": "id-0001", "text": "texto"},
        ])
        results = scan_canon_for_nonconforming(canon)
        assert any(nc.reason == REASON_MISSING_TITLE for nc in results)

    def test_missing_text_field_detected(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            {"id": "id-0001", "title": "Sin text"},
        ])
        results = scan_canon_for_nonconforming(canon)
        assert any(nc.reason == REASON_MISSING_TEXT for nc in results)

    def test_duplicate_id_detected(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            _valid_record(1),
            _valid_record(1),  # duplicate
        ])
        results = scan_canon_for_nonconforming(canon)
        dup = [nc for nc in results if nc.reason == REASON_DUPLICATE_ID]
        assert len(dup) == 1
        assert dup[0].record_id == "id-0001"

    def test_multiple_shards_scanned(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        _write_shard(canon, "tiddlers_2.jsonl", [{"id": "", "title": "vacio", "text": "x"}])
        results = scan_canon_for_nonconforming(canon)
        assert len(results) == 1
        assert results[0].shard == "tiddlers_2.jsonl"

    def test_indices_are_unique_and_sequential(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            "bad json 1",
            "bad json 2",
            {"id": "", "title": "x", "text": "y"},
        ])
        results = scan_canon_for_nonconforming(canon)
        indices = [nc.index for nc in results]
        assert len(indices) == len(set(indices)), "indices are not unique"
        assert indices == list(range(1, len(indices) + 1)), "indices not sequential from 1"

    def test_empty_lines_ignored(self, tmp_path):
        canon = _canon_dir(tmp_path)
        path = canon / "tiddlers_1.jsonl"
        path.write_text(
            json.dumps(_valid_record(1)) + "\n\n\n" + json.dumps(_valid_record(2)) + "\n",
            encoding="utf-8",
        )
        results = scan_canon_for_nonconforming(canon)
        assert results == []

    def test_nonconforming_contains_shard_and_line_info(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            _valid_record(1),
            "broken",
        ])
        results = scan_canon_for_nonconforming(canon)
        assert results[0].shard == "tiddlers_1.jsonl"
        assert results[0].line_no == 2


# ── TestSearchCanonById ───────────────────────────────────────────────────────

class TestSearchCanonById:
    def test_exact_match(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            _valid_record(1),
            _valid_record(2),
        ])
        results = search_canon_by_id("id-0001", canon)
        assert len(results) == 1
        assert results[0]["id"] == "id-0001"

    def test_partial_match(self, tmp_path):
        canon = _canon_dir(tmp_path)
        # id-0001 and id-0010 both contain the fragment "id-00"
        _write_shard(canon, "tiddlers_1.jsonl", [
            _valid_record(1),
            _valid_record(10),
        ])
        results = search_canon_by_id("id-00", canon)
        assert len(results) == 2

    def test_case_insensitive(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            {"id": "AbCd-XyZ", "title": "t", "text": "x"},
        ])
        results = search_canon_by_id("abcd-xyz", canon)
        assert len(results) == 1

    def test_no_match_returns_empty(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        results = search_canon_by_id("nonexistent-id-999", canon)
        assert results == []

    def test_result_contains_shard_and_line_no(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        results = search_canon_by_id("id-0001", canon)
        assert "shard" in results[0]
        assert "line_no" in results[0]
        assert results[0]["shard"] == "tiddlers_1.jsonl"


# ── TestSearchCanonByTitle ────────────────────────────────────────────────────

class TestSearchCanonByTitle:
    def test_exact_title_match(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        results = search_canon_by_title("Título 1", canon)
        assert len(results) == 1

    def test_fragment_match(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            _valid_record(1),
            _valid_record(2),
            _valid_record(3),
        ])
        results = search_canon_by_title("Título", canon)
        assert len(results) == 3

    def test_case_insensitive(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            {"id": "id-x", "title": "MiTítulo", "text": "x"},
        ])
        results = search_canon_by_title("mitítulo", canon)
        assert len(results) == 1

    def test_no_match_returns_empty(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        results = search_canon_by_title("xyz-inexistente-abc", canon)
        assert results == []


# ── TestParseIndexSelection ───────────────────────────────────────────────────

class TestParseIndexSelection:
    def test_single_index(self):
        indices, errors = parse_index_selection("3", max_index=10)
        assert indices == [3]
        assert errors == []

    def test_comma_separated(self):
        indices, errors = parse_index_selection("1,3,5", max_index=10)
        assert indices == [1, 3, 5]
        assert errors == []

    def test_range(self):
        indices, errors = parse_index_selection("2-5", max_index=10)
        assert indices == [2, 3, 4, 5]
        assert errors == []

    def test_mixed(self):
        indices, errors = parse_index_selection("1,3,5-7", max_index=10)
        assert sorted(indices) == [1, 3, 5, 6, 7]
        assert errors == []

    def test_deduplication(self):
        indices, errors = parse_index_selection("1,1,2", max_index=10)
        assert indices == [1, 2]

    def test_out_of_range_reported_as_error(self):
        indices, errors = parse_index_selection("15", max_index=10)
        assert 15 not in indices
        assert any("15" in e for e in errors)

    def test_invalid_token_reported(self):
        _, errors = parse_index_selection("abc", max_index=10)
        assert len(errors) >= 1

    def test_empty_string_returns_empty(self):
        indices, errors = parse_index_selection("", max_index=10)
        assert indices == []


# ── TestBuildEliminationPlan ──────────────────────────────────────────────────

class TestBuildEliminationPlan:
    def _make_nonconforming(self, count: int) -> list[NonConformingLine]:
        return [
            NonConformingLine(
                index=i,
                shard="tiddlers_1.jsonl",
                line_no=i + 10,
                record_id=f"id-{i}",
                title=f"Título {i}",
                reason=REASON_MISSING_TEXT,
                description=f"sin text {i}",
            )
            for i in range(1, count + 1)
        ]

    def test_plan_contains_selected_targets(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        nc = self._make_nonconforming(5)
        plan = build_elimination_plan([1, 3], nc, canon)
        assert len(plan.targets) == 2
        assert {t.index for t in plan.targets} == {1, 3}

    def test_plan_is_dry_run_by_default(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        nc = self._make_nonconforming(3)
        plan = build_elimination_plan([1], nc, canon)
        assert plan.dry_run is True
        assert plan.applied is False

    def test_plan_has_run_id(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        nc = self._make_nonconforming(2)
        plan = build_elimination_plan([1], nc, canon)
        assert plan.run_id.startswith("sanitation-")

    def test_plan_has_canon_hash(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        nc = self._make_nonconforming(2)
        plan = build_elimination_plan([1], nc, canon)
        assert plan.canon_hash_before.startswith("sha256:")

    def test_selected_indices_stored_sorted(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        nc = self._make_nonconforming(5)
        plan = build_elimination_plan([5, 1, 3], nc, canon)
        assert plan.selected_indices == [1, 3, 5]


# ── TestApplyEliminationPlan ──────────────────────────────────────────────────

class TestApplyEliminationPlan:
    def _setup_canon_with_targets(self, tmp_path: Path) -> tuple[Path, list[NonConformingLine]]:
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [
            _valid_record(1),
            {"id": "", "title": "sin id", "text": "x"},      # line 2 — non-conforming
            _valid_record(3),
            "bad json",                                         # line 4 — non-conforming
            _valid_record(5),
        ])
        nc = scan_canon_for_nonconforming(canon)
        return canon, nc

    def test_dry_run_does_not_modify_canon(self, tmp_path):
        canon, nc = self._setup_canon_with_targets(tmp_path)
        hashes_before = {p.name: p.read_bytes() for p in canon.glob("tiddlers_*.jsonl")}
        plan = build_elimination_plan([nc[0].index], nc, canon)
        success, _, _ = apply_elimination_plan(plan, canon_dir=canon, confirm=False)
        assert success
        hashes_after = {p.name: p.read_bytes() for p in canon.glob("tiddlers_*.jsonl")}
        assert hashes_before == hashes_after, "dry-run should not modify canon"

    def test_dry_run_reports_success(self, tmp_path):
        canon, nc = self._setup_canon_with_targets(tmp_path)
        plan = build_elimination_plan([nc[0].index], nc, canon)
        success, msg, _ = apply_elimination_plan(plan, canon_dir=canon, confirm=False)
        assert success
        assert "dry-run" in msg.lower()

    def test_apply_with_confirm_removes_targeted_lines(self, tmp_path):
        canon, nc = self._setup_canon_with_targets(tmp_path)
        target_line_nos = {n.line_no for n in nc}
        plan = build_elimination_plan([n.index for n in nc], nc, canon)
        success, _, updated = apply_elimination_plan(plan, canon_dir=canon, confirm=True)
        assert success
        assert updated.applied is True
        assert updated.removed_count == len(nc)

        # Verify that the targeted lines are gone
        shard = canon / "tiddlers_1.jsonl"
        remaining = [l.strip() for l in shard.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(remaining) == 5 - len(nc)

    def test_apply_creates_backup(self, tmp_path):
        canon, nc = self._setup_canon_with_targets(tmp_path)
        plan = build_elimination_plan([nc[0].index], nc, canon)
        backup_dir = tmp_path / "backup"
        success, _, updated = apply_elimination_plan(
            plan, canon_dir=canon, backup_dir=backup_dir, confirm=True
        )
        assert success
        assert backup_dir.exists()
        backup_shards = list(backup_dir.glob("tiddlers_*.jsonl"))
        assert len(backup_shards) >= 1

    def test_apply_updates_plan_hash_after(self, tmp_path):
        canon, nc = self._setup_canon_with_targets(tmp_path)
        plan = build_elimination_plan([nc[0].index], nc, canon)
        hash_before = plan.canon_hash_before
        _, _, updated = apply_elimination_plan(plan, canon_dir=canon, confirm=True)
        assert updated.canon_hash_after != ""
        assert updated.canon_hash_after != hash_before  # canon changed

    def test_apply_fails_when_hash_mismatch(self, tmp_path):
        canon, nc = self._setup_canon_with_targets(tmp_path)
        plan = build_elimination_plan([nc[0].index], nc, canon)
        # Tamper with the canon after building the plan
        extra = canon / "tiddlers_2.jsonl"
        extra.write_text(json.dumps(_valid_record(99)) + "\n", encoding="utf-8")
        success, msg, _ = apply_elimination_plan(plan, canon_dir=canon, confirm=True)
        assert not success
        assert "hash" in msg.lower()

    def test_empty_plan_returns_failure(self, tmp_path):
        canon = _canon_dir(tmp_path)
        _write_shard(canon, "tiddlers_1.jsonl", [_valid_record(1)])
        plan = build_elimination_plan([], [], canon)
        success, msg, _ = apply_elimination_plan(plan, canon_dir=canon, confirm=True)
        assert not success


# ── TestSavePlanAndLoadLastPlan ───────────────────────────────────────────────

class TestSavePlanAndLoadLastPlan:
    def _make_plan(self, canon_dir: Path) -> EliminationPlan:
        _write_shard(canon_dir, "tiddlers_1.jsonl", [_valid_record(1)])
        nc = [NonConformingLine(
            index=1, shard="tiddlers_1.jsonl", line_no=2,
            record_id="id-x", title="t", reason=REASON_MISSING_TEXT, description="d",
        )]
        return build_elimination_plan([1], nc, canon_dir)

    def test_save_creates_json_file(self, tmp_path):
        canon = _canon_dir(tmp_path)
        plan = self._make_plan(canon)
        plan_dir = tmp_path / "sanitation"
        path = save_plan(plan, plan_dir)
        assert path.exists()
        assert path.suffix == ".json"

    def test_load_last_plan_returns_plan(self, tmp_path):
        canon = _canon_dir(tmp_path)
        plan = self._make_plan(canon)
        plan_dir = tmp_path / "sanitation"
        save_plan(plan, plan_dir)
        loaded = load_last_plan(plan_dir)
        assert loaded is not None
        assert loaded.run_id == plan.run_id

    def test_load_last_plan_empty_dir(self, tmp_path):
        empty_dir = tmp_path / "empty_sanitation"
        loaded = load_last_plan(empty_dir)
        assert loaded is None

    def test_load_last_plan_nonexistent_dir(self, tmp_path):
        loaded = load_last_plan(tmp_path / "does_not_exist")
        assert loaded is None

    def test_loaded_plan_preserves_targets(self, tmp_path):
        canon = _canon_dir(tmp_path)
        plan = self._make_plan(canon)
        plan_dir = tmp_path / "sanitation"
        save_plan(plan, plan_dir)
        loaded = load_last_plan(plan_dir)
        assert loaded is not None
        assert len(loaded.targets) == 1
        assert loaded.targets[0].reason == REASON_MISSING_TEXT


# ── TestFormatNonconformingSummary ────────────────────────────────────────────

class TestFormatNonconformingSummary:
    def test_empty_returns_no_results_message(self):
        msg = format_nonconforming_summary([])
        assert "No se encontraron" in msg or "no" in msg.lower()

    def test_non_empty_contains_shard_info(self):
        nc = [NonConformingLine(
            index=1, shard="tiddlers_1.jsonl", line_no=5,
            record_id="id-x", title="Mi título",
            reason=REASON_MISSING_TEXT, description="sin text",
        )]
        summary = format_nonconforming_summary(nc)
        assert "tiddlers_1.jsonl" in summary

    def test_contains_reason(self):
        nc = [NonConformingLine(
            index=1, shard="tiddlers_1.jsonl", line_no=5,
            record_id="id-x", title="",
            reason=REASON_INVALID_JSON, description="bad json",
        )]
        summary = format_nonconforming_summary(nc)
        assert REASON_INVALID_JSON in summary
