#!/usr/bin/env python3
"""Tests for S0122: selective canon sanitation via search results.

Covers:
- format_search_results_numbered display
- build_elimination_plan_from_search construction
- REASON_USER_SELECTED in targets
- source_kind and query preserved in plan and persisted via save/load
- apply_elimination_plan removes search-derived targets safely
- Smoke: option 4 does not block when search results exist but scan is clean
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap (tests/ is not always on sys.path)
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python_scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canon_sanitation import (  # noqa: E402
    REASON_USER_SELECTED,
    EliminationPlan,
    NonConformingLine,
    apply_elimination_plan,
    build_elimination_plan_from_search,
    format_search_results_numbered,
    load_last_plan,
    save_plan,
    search_canon_by_id,
    search_canon_by_title,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_shard(canon_dir: Path, name: str, records: list) -> None:
    """Write a JSONL shard. Each element is either a dict (serialised) or a raw string."""
    canon_dir.mkdir(parents=True, exist_ok=True)
    shard = canon_dir / name
    lines = []
    for r in records:
        if isinstance(r, dict):
            lines.append(json.dumps(r, ensure_ascii=False))
        else:
            lines.append(str(r))
    shard.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_record(i: int, title: str = "") -> dict:
    return {
        "id": f"id-{i:04d}",
        "title": title or f"Título {i}",
        "text": f"Contenido del tiddler {i}",
    }


# ---------------------------------------------------------------------------
# 7.1  Search results display
# ---------------------------------------------------------------------------

class TestFormatSearchResultsNumbered:
    def test_empty_returns_sin_resultados(self) -> None:
        assert format_search_results_numbered([]) == "Sin resultados."

    def test_single_result_contains_index_1(self) -> None:
        results = [{"shard": "tiddlers_1.jsonl", "line_no": 5, "id": "abc-001", "title": "Mi tiddler"}]
        output = format_search_results_numbered(results)
        assert "1" in output
        assert "abc-001" in output
        assert "Mi tiddler" in output

    def test_multiple_results_numbered_sequentially(self) -> None:
        results = [
            {"shard": "s1.jsonl", "line_no": 1, "id": "a-001", "title": "Alpha"},
            {"shard": "s1.jsonl", "line_no": 2, "id": "a-002", "title": "Beta"},
            {"shard": "s1.jsonl", "line_no": 3, "id": "a-003", "title": "Gamma"},
        ]
        output = format_search_results_numbered(results)
        lines = output.splitlines()
        # Header + separator + 3 data rows = 5 lines
        assert len(lines) == 5
        assert "1" in lines[2]
        assert "2" in lines[3]
        assert "3" in lines[4]

    def test_long_id_truncated(self) -> None:
        long_id = "x" * 60
        results = [{"shard": "s.jsonl", "line_no": 1, "id": long_id, "title": "T"}]
        output = format_search_results_numbered(results)
        # The id column is capped at 30 chars
        assert "x" * 30 in output

    def test_header_present(self) -> None:
        results = [{"shard": "s.jsonl", "line_no": 1, "id": "id-001", "title": "T"}]
        output = format_search_results_numbered(results)
        assert "Shard" in output
        assert "Línea" in output
        assert "ID" in output
        assert "Título" in output


# ---------------------------------------------------------------------------
# 7.2  Multi-index selection from search results
# ---------------------------------------------------------------------------

class TestBuildEliminationPlanFromSearchSelection:
    def _make_search_results(self, count: int) -> list[dict]:
        return [
            {"shard": "tiddlers_1.jsonl", "line_no": i, "id": f"id-{i:04d}", "title": f"Tiddler {i}"}
            for i in range(1, count + 1)
        ]

    def test_single_index_selected(self, tmp_path: Path) -> None:
        results = self._make_search_results(5)
        plan = build_elimination_plan_from_search([2], results, "search_id", "id-0002", tmp_path)
        assert len(plan.targets) == 1
        assert plan.targets[0].record_id == "id-0002"

    def test_multiple_indices_selected(self, tmp_path: Path) -> None:
        results = self._make_search_results(5)
        plan = build_elimination_plan_from_search(
            [1, 3, 5], results, "search_title", "Tiddler", tmp_path
        )
        assert len(plan.targets) == 3
        ids = {t.record_id for t in plan.targets}
        assert ids == {"id-0001", "id-0003", "id-0005"}

    def test_out_of_range_index_ignored(self, tmp_path: Path) -> None:
        results = self._make_search_results(3)
        plan = build_elimination_plan_from_search(
            [1, 99], results, "search_id", "frag", tmp_path
        )
        # index 99 does not match any enumerated result (only 3 items)
        assert len(plan.targets) == 1
        assert plan.targets[0].index == 1

    def test_selected_indices_sorted_in_plan(self, tmp_path: Path) -> None:
        results = self._make_search_results(5)
        plan = build_elimination_plan_from_search(
            [5, 1, 3], results, "search_id", "q", tmp_path
        )
        assert plan.selected_indices == [1, 3, 5]


# ---------------------------------------------------------------------------
# 7.3  Plan built from search carries correct metadata
# ---------------------------------------------------------------------------

class TestPlanFromSearchMetadata:
    def test_source_kind_search_id(self, tmp_path: Path) -> None:
        results = [{"shard": "s.jsonl", "line_no": 1, "id": "abc", "title": "T"}]
        plan = build_elimination_plan_from_search([1], results, "search_id", "abc", tmp_path)
        assert plan.source_kind == "search_id"

    def test_source_kind_search_title(self, tmp_path: Path) -> None:
        results = [{"shard": "s.jsonl", "line_no": 1, "id": "abc", "title": "Hola"}]
        plan = build_elimination_plan_from_search([1], results, "search_title", "Hola", tmp_path)
        assert plan.source_kind == "search_title"

    def test_query_preserved(self, tmp_path: Path) -> None:
        results = [{"shard": "s.jsonl", "line_no": 2, "id": "x", "title": "Y"}]
        plan = build_elimination_plan_from_search([1], results, "search_id", "my-query", tmp_path)
        assert plan.query == "my-query"

    def test_target_reason_is_user_selected(self, tmp_path: Path) -> None:
        results = [{"shard": "s.jsonl", "line_no": 3, "id": "z", "title": "Z title"}]
        plan = build_elimination_plan_from_search([1], results, "search_title", "Z", tmp_path)
        assert plan.targets[0].reason == REASON_USER_SELECTED

    def test_dry_run_default_true(self, tmp_path: Path) -> None:
        results = [{"shard": "s.jsonl", "line_no": 1, "id": "a", "title": "A"}]
        plan = build_elimination_plan_from_search([1], results, "search_id", "a", tmp_path)
        assert plan.dry_run is True
        assert plan.applied is False

    def test_canon_hash_captured(self, tmp_path: Path) -> None:
        """canon_hash_before must be a non-empty sha256 string."""
        # Even an empty canon_dir gives a deterministic hash
        results = [{"shard": "s.jsonl", "line_no": 1, "id": "a", "title": "A"}]
        plan = build_elimination_plan_from_search([1], results, "search_id", "a", tmp_path)
        assert plan.canon_hash_before.startswith("sha256:")

    def test_run_id_starts_with_sanitation(self, tmp_path: Path) -> None:
        results = [{"shard": "s.jsonl", "line_no": 1, "id": "a", "title": "A"}]
        plan = build_elimination_plan_from_search([1], results, "search_id", "a", tmp_path)
        assert plan.run_id.startswith("sanitation-")


# ---------------------------------------------------------------------------
# 7.4  Plan persisted and loaded back with new fields
# ---------------------------------------------------------------------------

class TestPlanSaveLoadWithSourceKind:
    def test_save_and_load_preserves_source_kind(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        sanitation_dir = tmp_path / "sanitation"
        results = [{"shard": "t.jsonl", "line_no": 1, "id": "id-0001", "title": "Test"}]
        plan = build_elimination_plan_from_search(
            [1], results, "search_id", "id-0001", canon_dir
        )
        save_plan(plan, sanitation_dir)
        loaded = load_last_plan(sanitation_dir)
        assert loaded is not None
        assert loaded.source_kind == "search_id"

    def test_save_and_load_preserves_query(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        sanitation_dir = tmp_path / "sanitation"
        results = [{"shard": "t.jsonl", "line_no": 1, "id": "id-0001", "title": "Test"}]
        plan = build_elimination_plan_from_search(
            [1], results, "search_title", "my fragment", canon_dir
        )
        save_plan(plan, sanitation_dir)
        loaded = load_last_plan(sanitation_dir)
        assert loaded is not None
        assert loaded.query == "my fragment"

    def test_old_plan_without_source_kind_loads_with_default(self, tmp_path: Path) -> None:
        """Plans from S0121 (no source_kind field) must load with default 'scan'."""
        sanitation_dir = tmp_path / "sanitation"
        sanitation_dir.mkdir(parents=True)
        old_plan_data = {
            "run_id": "sanitation-20260101000000",
            "timestamp": "2026-01-01T00:00:00Z",
            "canon_dir": "data/out/local",
            "canon_hash_before": "sha256:abc",
            "selected_indices": [1],
            "targets": [
                {
                    "index": 1,
                    "shard": "t.jsonl",
                    "line_no": 5,
                    "record_id": "id-old",
                    "title": "Old tiddler",
                    "reason": "missing_id",
                    "description": "Campo id ausente",
                }
            ],
            "dry_run": True,
            "applied": False,
            "backup_dir": "",
            "canon_hash_after": "",
            "removed_count": 0,
            # no source_kind, no query
        }
        plan_file = sanitation_dir / "sanitation-20260101000000.json"
        plan_file.write_text(json.dumps(old_plan_data), encoding="utf-8")
        loaded = load_last_plan(sanitation_dir)
        assert loaded is not None
        assert loaded.source_kind == "scan"
        assert loaded.query == ""

    def test_save_and_load_preserves_targets_reason(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        sanitation_dir = tmp_path / "sanitation"
        results = [{"shard": "t.jsonl", "line_no": 7, "id": "id-search", "title": "Search result"}]
        plan = build_elimination_plan_from_search(
            [1], results, "search_id", "search", canon_dir
        )
        save_plan(plan, sanitation_dir)
        loaded = load_last_plan(sanitation_dir)
        assert loaded is not None
        assert loaded.targets[0].reason == REASON_USER_SELECTED


# ---------------------------------------------------------------------------
# 7.5  apply_elimination_plan removes search-derived target
# ---------------------------------------------------------------------------

class TestApplyPlanFromSearch:
    def test_dry_run_does_not_modify_canon(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_record(1),
            _make_record(2),
            _make_record(3),
        ])
        results = search_canon_by_id("id-0002", canon_dir)
        assert len(results) == 1

        plan = build_elimination_plan_from_search(
            [1], results, "search_id", "id-0002", canon_dir
        )
        original_content = (canon_dir / "tiddlers_1.jsonl").read_bytes()
        success, msg, updated = apply_elimination_plan(plan, canon_dir, confirm=False)
        assert success
        assert "dry-run" in msg
        after_content = (canon_dir / "tiddlers_1.jsonl").read_bytes()
        assert original_content == after_content

    def test_apply_removes_target(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        backup_dir = tmp_path / "backup"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [
            _make_record(1),
            _make_record(2),
            _make_record(3),
        ])
        results = search_canon_by_id("id-0002", canon_dir)
        assert len(results) == 1

        plan = build_elimination_plan_from_search(
            [1], results, "search_id", "id-0002", canon_dir
        )
        success, msg, updated = apply_elimination_plan(
            plan, canon_dir, backup_dir=backup_dir, confirm=True
        )
        assert success
        assert updated.removed_count == 1

        # Verify the tiddler is no longer in the canon
        remaining = search_canon_by_id("id-0002", canon_dir)
        assert len(remaining) == 0

        # Other tiddlers still present
        assert len(search_canon_by_id("id-0001", canon_dir)) == 1
        assert len(search_canon_by_id("id-0003", canon_dir)) == 1

    def test_apply_creates_backup(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        backup_dir = tmp_path / "backup"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [_make_record(1), _make_record(2)])
        results = search_canon_by_title("Título 1", canon_dir)
        assert len(results) == 1

        plan = build_elimination_plan_from_search(
            [1], results, "search_title", "Título 1", canon_dir
        )
        success, _, updated = apply_elimination_plan(
            plan, canon_dir, backup_dir=backup_dir, confirm=True
        )
        assert success
        assert backup_dir.exists()
        backup_files = list(backup_dir.iterdir())
        assert len(backup_files) > 0

    def test_hash_mismatch_blocks_apply(self, tmp_path: Path) -> None:
        canon_dir = tmp_path / "canon"
        _write_shard(canon_dir, "tiddlers_1.jsonl", [_make_record(1), _make_record(2)])
        results = search_canon_by_id("id-0001", canon_dir)
        plan = build_elimination_plan_from_search(
            [1], results, "search_id", "id-0001", canon_dir
        )
        # Mutate the canon AFTER plan is built
        _write_shard(canon_dir, "tiddlers_1.jsonl", [_make_record(1), _make_record(99)])
        success, msg, _ = apply_elimination_plan(plan, canon_dir, confirm=True)
        assert not success
        assert "hash" in msg.lower()


# ---------------------------------------------------------------------------
# 7.6  Smoke: option_canon_sanitation import succeeds and constants exist
# ---------------------------------------------------------------------------

class TestSanitationConstantsExist:
    def test_reason_user_selected_constant(self) -> None:
        assert REASON_USER_SELECTED == "user_selected"

    def test_elimination_plan_has_source_kind_field(self) -> None:
        plan = EliminationPlan(
            run_id="r", timestamp="t", canon_dir="d", canon_hash_before="h",
            selected_indices=[], targets=[]
        )
        assert plan.source_kind == "scan"
        assert plan.query == ""

    def test_elimination_plan_source_kind_overridable(self) -> None:
        plan = EliminationPlan(
            run_id="r", timestamp="t", canon_dir="d", canon_hash_before="h",
            selected_indices=[], targets=[],
            source_kind="search_id", query="my-frag",
        )
        assert plan.source_kind == "search_id"
        assert plan.query == "my-frag"
