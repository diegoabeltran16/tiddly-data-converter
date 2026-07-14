"""S0173 deterministic equivalence and authorization-boundary tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

from rag_derivative_writers import ProductiveWriteBlocked  # noqa: E402
from rag_derivation_profile import build_profile  # noqa: E402
from validate_productive_equivalence import build_equivalence_report  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _write_surface(root: Path, *, semantic: str = "same", run_id: str = "preview") -> None:
    record = {
        "id": "record-1",
        "schema_version": "surface/v1",
        "semantic_text": semantic,
        "retrieval_hints": ["rag"],
        "embedding_metadata": {"promoted_metadata": {"topics": ["rag"]}},
        "source_refs": {"ai": {"path": f"{root}/ai/tiddlers_ai_1.jsonl"}},
        "run_id": run_id,
    }
    chunk = {
        "chunk_id": "record-1::chunk:1",
        "source_id": "record-1",
        "chunk_index": 1,
        "chunk_total": 1,
        "text": "same chunk",
        "schema_version": "chunk/v1",
    }
    for relative, rows in (
        ("enriched/tiddlers_enriched_1.jsonl", [record]),
        ("ai/tiddlers_ai_1.jsonl", [record]),
        ("ai/chunks_ai_1.jsonl", [chunk]),
        ("semantic_text/run_semantic_text_records.jsonl", [record]),
    ):
        _write_jsonl(root / relative, rows)
    entities = {"generated_from_session": run_id, "entities": [record]}
    (root / "microsoft_copilot").mkdir(parents=True, exist_ok=True)
    (root / "microsoft_copilot" / "entities.json").write_text(json.dumps(entities), encoding="utf-8")


def test_equivalence_ignores_only_declared_operational_differences(tmp_path: Path) -> None:
    preview = tmp_path / "preview"
    staging = tmp_path / "staging"
    _write_surface(preview, run_id="preview")
    _write_surface(staging, run_id="staging")
    report = build_equivalence_report(preview, staging)
    assert report["equivalence_status"] == "equivalent_with_declared_operational_differences"
    assert report["blocking"] is False
    assert all(value["equivalence_status"] == "equivalent" for value in report["families"].values())


def test_equivalence_rejects_semantic_text_mismatch(tmp_path: Path) -> None:
    preview = tmp_path / "preview"
    staging = tmp_path / "staging"
    _write_surface(preview)
    _write_surface(staging, semantic="changed")
    report = build_equivalence_report(preview, staging)
    assert report["equivalence_status"] == "not_equivalent"
    assert report["blocking"] is True
    assert report["families"]["ai"]["semantic_text_mismatches"] == 1


def test_profile_can_pin_orchestrator_hash() -> None:
    profile = build_profile(productive_orchestrator_hash="a" * 64)
    assert profile["productive_orchestrator_hash"] == "a" * 64


def test_productive_write_boundary_rejects_missing_exact_authorization() -> None:
    with pytest.raises(ProductiveWriteBlocked, match="exact S0173 authorization phrase"):
        from rag_derivative_writers import promote_staging_transaction

        promote_staging_transaction(
            staging_root=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "staging",
            rollback_root=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "rollback_snapshot",
            authorization={},
            planned_families=["enriched"],
            transaction_journal=REPO_ROOT / "data" / "out" / "local" / "audit" / "rag_derivation" / "s0173" / "test-journal.jsonl",
            receipt_path=REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_derivation" / "s0173" / "test-receipt.json",
        )
