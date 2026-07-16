"""Regression coverage for productive equivalence contract v2.

The filename is kept for the historical test location.  The assertions are
contractual rather than tied to S0173 counts, paths, or identifiers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from rag_derivative_writers import ProductiveWriteBlocked  # noqa: E402
from validate_productive_equivalence import build_equivalence_report  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _canon_record(record_id: str, version_id: str) -> dict:
    return {
        "id": record_id,
        "version_id": version_id,
        "title": f"Title {record_id}",
        "canonical_slug": record_id,
        "schema_version": "v0",
    }


def _write_canon(root: Path, records: list[dict]) -> None:
    _write_jsonl(root / "tiddlers_1.jsonl", records)


def _record(record_id: str, version_id: str, *, semantic: str = "same", schema: str = "surface/v1", artifact_family: str | None = None) -> dict:
    record = {
        "id": record_id,
        "version_id": version_id,
        "schema_version": schema,
        "semantic_text": semantic,
        "retrieval_hints": ["rag"],
        "embedding_metadata": {"promoted_metadata": {"topics": ["rag"]}},
        "rag_allowed_tags": ["rag"],
    }
    if artifact_family:
        record["artifact_family"] = artifact_family
    return record


def _write_enriched(root: Path, rows: list[dict]) -> None:
    _write_jsonl(root / "enriched" / "tiddlers_enriched_1.jsonl", rows)


def _report(tmp_path: Path, baseline_rows: list[dict], staging_rows: list[dict], canon_rows: list[dict]) -> dict:
    baseline = tmp_path / "baseline"
    staging = tmp_path / "staging"
    canon = tmp_path / "canon"
    _write_enriched(baseline, baseline_rows)
    _write_enriched(staging, staging_rows)
    _write_canon(canon, canon_rows)
    return build_equivalence_report(baseline, staging, canon_dir=canon, families=["enriched"])


def test_unchanged_record_is_equivalent(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("same", "v1")], [_record("same", "v1")], [_canon_record("same", "v1")])
    assert report["equivalence_status"] == "equivalent"
    assert report["blocking"] is False
    assert report["families"]["enriched"]["unchanged_shared_records"] == 1


def test_same_version_semantic_change_is_blocking_regression(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("same", "v1")], [_record("same", "v1", semantic="changed")], [_canon_record("same", "v1")])
    family = report["families"]["enriched"]
    assert report["equivalence_status"] == "not_equivalent"
    assert family["unexpected_semantic_regressions"] == 1
    assert family["blocking"] is True


def test_current_canonical_update_is_non_blocking(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("same", "v1")], [_record("same", "v2", semantic="changed")], [_canon_record("same", "v2")])
    assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"
    assert report["evolution"] == {"additions": 0, "updates": 1, "removals": 0, "regressions": 0}
    assert report["families"]["enriched"]["canonical_updates"] == 1


def test_invalid_version_transition_blocks_even_when_content_changed(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("same", "v1")], [_record("same", "v3", semantic="changed")], [_canon_record("same", "v2")])
    assert report["families"]["enriched"]["invalid_version_transitions"] == 1
    assert report["blocking"] is True


def test_new_record_requires_current_canonical_membership_and_version(tmp_path: Path) -> None:
    report = _report(tmp_path, [], [_record("new", "v1")], [_canon_record("new", "v1")])
    assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"
    assert report["families"]["enriched"]["added_from_current_canon"] == 1


def test_orphaned_derived_record_is_blocking(tmp_path: Path) -> None:
    report = _report(tmp_path, [], [_record("orphan", "v1")], [])
    assert report["families"]["enriched"]["invalid_canonical_membership"] == 1
    assert report["blocking"] is True


def test_historical_removal_remains_blocking(tmp_path: Path) -> None:
    report = _report(tmp_path, [_record("lost", "v1")], [], [_canon_record("lost", "v1")])
    assert report["families"]["enriched"]["removed_historical_records"] == 1
    assert report["blocking"] is True


def test_mixed_growth_and_updates_are_counted_without_hardcoded_incident_values(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("unchanged", "v1"), _record("updated", "v1")],
        [_record("unchanged", "v1"), _record("updated", "v2", semantic="new"), _record("added", "v1")],
        [_canon_record("unchanged", "v1"), _canon_record("updated", "v2"), _canon_record("added", "v1")],
    )
    assert report["equivalence_status"] == "equivalent_with_expected_canonical_evolution"
    assert report["evolution"] == {"additions": 1, "updates": 1, "removals": 0, "regressions": 0}


def test_schema_and_explicit_family_mismatches_block_a_version_update(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [_record("same", "v1")],
        [_record("same", "v2", schema="surface/v2", artifact_family="ai")],
        [_canon_record("same", "v2")],
    )
    family = report["families"]["enriched"]
    assert family["schema_mismatches"] == 1
    assert family["family_mismatches"] == 1
    assert report["blocking"] is True


def test_duplicate_staging_identity_blocks(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [],
        [_record("duplicate", "v1"), _record("duplicate", "v1")],
        [_canon_record("duplicate", "v1")],
    )
    assert report["families"]["enriched"]["duplicate_records"] == 1
    assert report["blocking"] is True


def test_unchanged_chunks_need_not_grow_for_new_non_chunkable_canon_record(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    staging = tmp_path / "staging"
    canon = tmp_path / "canon"
    chunk = {
        "chunk_id": "existing::chunk:0",
        "source_id": "existing",
        "source_version_id": "v1",
        "text": "stable chunk",
        "chunk_index": 0,
        "chunk_total": 1,
        "within_hard_max": True,
        "source_anchor": {"canon_id": "existing", "shard_file": "old.jsonl", "shard_line": 1},
    }
    changed_location = chunk | {"source_anchor": {"canon_id": "existing", "shard_file": "new.jsonl", "shard_line": 99}}
    _write_jsonl(baseline / "ai" / "chunks_ai_1.jsonl", [chunk])
    _write_jsonl(staging / "ai" / "chunks_ai_1.jsonl", [changed_location])
    _write_canon(canon, [_canon_record("existing", "v1"), _canon_record("non-chunkable", "v1")])
    report = build_equivalence_report(baseline, staging, canon_dir=canon, families=["chunks_ai"])
    assert report["equivalence_status"] == "equivalent"
    assert report["families"]["chunks_ai"]["chunk_mismatches"] == 0


def test_productive_write_boundary_rejects_missing_exact_authorization() -> None:
    with pytest.raises(ProductiveWriteBlocked, match="exact S0173 authorization phrase"):
        from rag_derivative_writers import promote_staging_transaction

        promote_staging_transaction(
            staging_root=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "staging",
            rollback_root=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "rollback_snapshot",
            authorization={},
            planned_families=["enriched"],
            transaction_journal=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "test-journal.jsonl",
            receipt_path=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "test-receipt.json",
        )
