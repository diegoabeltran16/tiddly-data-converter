from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from test_prepare_current_relational_generation import (
    _canon_record,
    _rebuild_fixture,
    _review_all_pending,
    _write_canon,
)

import prepare_current_relational_generation as preparation
import reconcile_current_relation_candidates as reconciliation
import current_relation_human_review as human_review


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def test_corrupt_operational_pointer_never_falls_back_to_s0183_rebaseline(
    tmp_path: Path,
) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    (source_root / "src/python_scripts/c.py").write_text("import b\n", encoding="utf-8")
    canon_rows.append(_canon_record("source-c", "src/python_scripts/c.py", "import b\n"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    preparation.execute(paths, source_root=source_root)
    _review_all_pending(paths)

    source_path = paths.current_dir / "human_review_decisions.jsonl"
    source_rows = preparation.read_jsonl(source_path)
    source = source_rows[0]
    historical = dict(source)
    historical_hash = human_review.decision_hash(historical)
    source.update({
        "preserved_from_candidate_id": source["candidate_id"],
        "preserved_from_decision_hash": historical_hash,
        "preservation_classification": "equivalent",
        "preservation_manifest_hash": "fixture-manifest-hash",
    })
    _write_jsonl(source_path, [source, source_rows[1]])
    source_before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    candidate = preparation.read_jsonl(paths.current_dir / "relation_candidates.jsonl")[0]
    candidate_id = candidate["candidate_id"]
    fingerprint = reconciliation._payload_hash(reconciliation.candidate_semantic_payload(candidate))
    audit = paths.local_root / "audit" / "s0183" / "current"
    historical_path = paths.local_root / "audit" / "s0183" / "entry" / "human_review_decisions.jsonl"
    _write_jsonl(historical_path, [historical])
    matrix_path = audit / "old_to_current_reconciliation.jsonl"
    _write_jsonl(matrix_path, [{
        "candidate_id": candidate_id,
        "counterpart_candidate_id": candidate_id,
        "classification": "equivalent",
        "decision_reusable": True,
        "semantic_fingerprint": fingerprint,
    }])
    snapshot = paths.local_root / "audit" / "s0183" / "entry" / "relation_candidates.jsonl"
    _write_jsonl(snapshot, [candidate])
    manifest_path = audit / "cross_batch_reconciliation_manifest.json"
    _write_json(manifest_path, {
        "schema_version": "s0183-cross-batch-reconciliation/v1",
        "current_candidates_path": str(paths.current_dir / "relation_candidates.jsonl"),
        "current_candidates_hash": "0" * 64,
        "historical_candidates_path": str(snapshot),
        "historical_candidates_hash": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "old_to_current_hash": hashlib.sha256(matrix_path.read_bytes()).hexdigest(),
    })
    receipt_path = audit / "human_decision_preservation_manifest.json"
    _write_json(receipt_path, {
        "cross_batch_manifest_hash": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "historical_decisions_path": str(historical_path),
        "historical_decisions_hash": hashlib.sha256(historical_path.read_bytes()).hexdigest(),
    })
    # A present operational pointer with an invalid manifest binding must not
    # degrade to S0183, even when a legacy Gate-P fixture is available.
    pointer = preparation.read_json(paths.pointer)
    pointer["bundle_manifest_hash"] = "f" * 64
    _write_json(paths.pointer, pointer)
    pointer_before = paths.pointer.read_bytes()
    generations_before = {
        path.relative_to(paths.generations).as_posix()
        for path in paths.generations.rglob("*")
    }

    with pytest.raises(preparation.PreparationBlocked) as error:
        preparation._rebuild_and_execute(
            paths, keep_safety_work=False, source_root=source_root,
            failure_hook=None,
        )

    assert "review_predecessor_manifest_hash_mismatch" in error.value.reason_codes
    assert paths.pointer.read_bytes() == pointer_before
    assert hashlib.sha256((paths.current_dir / "human_review_decisions.jsonl").read_bytes()).hexdigest() == source_before
    assert generations_before == {
        path.relative_to(paths.generations).as_posix()
        for path in paths.generations.rglob("*")
    }
    assert not list(paths.current_dir.parent.glob(".staging-*"))
