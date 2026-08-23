"""S0181 structured current-review, batch, and supersession guarantees."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import current_relation_human_review as review  # noqa: E402


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _candidate(candidate_id: str = "rc_current_aabb1122334455667788") -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_schema_version": "technical-relation-candidates/v1",
        "relation_type": "depende_de",
        "source": {
            "canonical_id": "src", "canonical_title": "Source",
            "repo_path": "src/example.py", "artifact_family": "python_source",
            "repo_lifecycle_state": "current_repo_artifact",
        },
        "target": {
            "canonical_id": "tgt", "canonical_title": "Target",
            "repo_path": "src/target.py", "artifact_family": "python_source",
            "repo_lifecycle_state": "current_repo_artifact",
        },
        "evidence": {
            "file": "src/example.py", "line": 1, "raw_observation": "import target",
            "evidence_kind": "technical", "technical_evidence_kind": "ast_import",
            "parser": "python_ast", "confidence": "high",
        },
    }


def _fixture(tmp_path: Path, candidates: list[dict] | None = None) -> tuple[Path, Path, list[dict]]:
    current, canon = tmp_path / "current", tmp_path / "canon"
    canon.mkdir()
    (canon / "tiddlers_1.jsonl").write_text('{"id":"src"}\n', encoding="utf-8")
    candidates = candidates or [_candidate()]
    current.mkdir()
    (current / review.QUEUE_FILE).write_text(
        "".join(json.dumps(candidate) + "\n" for candidate in candidates), encoding="utf-8",
    )
    logical_canon_hash = review.canon_hash(canon)
    candidate_manifest = current / "current_candidate_manifest.json"
    _write(candidate_manifest, {
        "current": True,
        "canon_binding": {"canon_hash": logical_canon_hash},
    })
    _write(current / "reconciliation_manifest.json", {
        "current": True,
        "canon_hash": logical_canon_hash,
        "candidate_manifest_hash": hashlib.sha256(candidate_manifest.read_bytes()).hexdigest(),
    })
    return current, canon, candidates


def _current_delta_authority_fixture(
    tmp_path: Path, *, classes: dict[str, list[str]] | None = None,
    candidate_count: int = 3, rebaseline_uncovered_ids: list[str] | None = None,
) -> tuple[Path, Path, list[dict]]:
    """Create an isolated, immutable current human-delta bundle."""
    local = tmp_path / "local"
    local.mkdir()
    (local / "tiddlers_1.jsonl").write_text('{"id":"src"}\n', encoding="utf-8")
    candidates = [
        _candidate("rc_current_" + f"{number:024x}")
        for number in range(1, candidate_count + 1)
    ]
    classes = classes or {
        "new": [candidates[0]["candidate_id"]],
        "modified": [candidates[1]["candidate_id"]],
        "ambiguous": [candidates[2]["candidate_id"]],
    }
    rebaseline_uncovered_ids = rebaseline_uncovered_ids or []
    generation, review_state, canon_generation = "rg_fixture", "rv_fixture", "cg_fixture"
    bundle = local / "audit/relation_admission/generations" / generation / review_state / "human_delta"
    bundle.mkdir(parents=True)
    candidate_manifest = {
        "current": True,
        "canon_binding": {"canon_hash": review.canon_hash(local), "record_count": 1},
    }
    _write(bundle / "current_candidate_manifest.json", candidate_manifest)
    reconciliation = {
        "current": True,
        "candidate_manifest_hash": review.sha256_file(bundle / "current_candidate_manifest.json"),
    }
    _write(bundle / "reconciliation_manifest.json", reconciliation)
    queue = [{**candidate, "reconciliation": {"disposition": "ready_for_review"}} for candidate in candidates]
    for name, value in {
        "ready_for_human_review.jsonl": queue,
        "relation_candidates.jsonl": queue,
        "effective_human_review_decisions.jsonl": [],
    }.items():
        (bundle / name).write_text("".join(json.dumps(row) + "\n" for row in value), encoding="utf-8")
    pending = [candidate["candidate_id"] for candidate in candidates]
    class_to_reason = {
        "new": "reconciliation_new", "modified": "reconciliation_modified",
        "ambiguous": "reconciliation_ambiguous",
    }
    review_candidates = [
        {
            "candidate_id": candidate["candidate_id"],
            "reconciliation_class": next(
                (name for name, ids in classes.items() if candidate["candidate_id"] in ids),
                None,
            ),
            "review_reason": (
                "rebaseline_uncovered"
                if candidate["candidate_id"] in rebaseline_uncovered_ids
                else next(
                    (class_to_reason[name] for name, ids in classes.items() if candidate["candidate_id"] in ids),
                    None,
                )
            ),
            "evidence": {},
        }
        for candidate in candidates
    ]
    review_reasons = {
        reason: [row["candidate_id"] for row in review_candidates if row["review_reason"] == reason]
        for reason in (*class_to_reason.values(), "rebaseline_uncovered")
    }
    reason_counts = {reason: len(ids) for reason, ids in review_reasons.items()}
    taxonomy_complete = all(row["review_reason"] for row in review_candidates)
    delta = {
        "schema_version": "current-relational-human-delta/v2",
        "pending": len(pending), "pending_candidate_ids": pending,
        "invalid": [], "relation_generation_id": generation, "review_state_id": review_state,
        **{name: classes.get(name, []) for name in ("new", "modified", "ambiguous")},
        "review_candidates": review_candidates, "review_reasons": review_reasons,
        "review_reason_counts": reason_counts, "conservation_valid": taxonomy_complete,
    }
    _write(bundle / "human_delta.json", delta)
    _write(bundle / "human_delta_inventory.json", {
        "schema_version": "current-relational-human-delta-inventory/v2",
        "pending": len(pending), "pending_candidate_ids": pending,
        "relation_generation_id": generation, "review_state_id": review_state,
        "review_reason_counts": reason_counts, "review_candidates": review_candidates,
        "conservation_valid": taxonomy_complete,
    })
    _write(bundle / "current_human_delta_manifest.json", {
        "schema_version": "current-governed-review-human-delta/v1",
        "pending_candidate_ids": pending,
        "relation_generation_id": generation, "review_state_id": review_state,
        "review_reason_counts": reason_counts, "review_candidates": review_candidates,
        "conservation_valid": taxonomy_complete,
    })
    _write(bundle / "review_rebaseline_manifest.json", {
        "relation_generation_id": generation, "new_review_state_id": review_state,
        "current_candidate_partition": {
            "reviewable_total": len(queue),
            "independently_covered": 0,
            "human_reviewed_covered": 0,
            "pending_human_review": len(pending),
        },
    })
    _write(bundle / "review_rebaseline_checkpoint.json", {
        "relation_generation_id": generation, "review_state_id": review_state,
        "independently_preserved_effective_decisions": 0,
        "current_direct_effective_decisions": 0,
        "pending_human_delta": len(pending),
    })
    _write(bundle / "independent_decision_preservation_manifest.json", {"items": []})
    _write(bundle / "admission_gate_dry_run.json", _gate(queue))
    _write(bundle / "validation_report.json", {})
    _write(bundle / "reviewable_manifest.json", {})
    _write(bundle / "decision_checkpoint.json", {
        "canon_generation_id": canon_generation, "relation_generation_id": generation,
        "review_state_id": review_state, "readiness_id": None,
        "decisions_file_hash": review.sha256_file(
            bundle / "effective_human_review_decisions.jsonl"
        ),
        "total_decisions": 0,
        "pending_delta": len(pending),
        "current_direct": 0,
        "preserved_equivalent": 0,
        "preserved_historical": 0,
        "individual_decision_hashes": [],
    })
    artifacts = {}
    names = {
        "candidate_manifest": "current_candidate_manifest.json",
        "validation_report": "validation_report.json",
        "reconciliation_manifest": "reconciliation_manifest.json",
        "reviewable_manifest": "reviewable_manifest.json",
        "relation_candidates": "relation_candidates.jsonl",
        "ready_queue": "ready_for_human_review.jsonl",
        "effective_decisions": "effective_human_review_decisions.jsonl",
        "decision_checkpoint": "decision_checkpoint.json",
        "admission_gate": "admission_gate_dry_run.json",
        "pending_queue": "human_delta.json",
        "batch_inventory": "human_delta_inventory.json",
        "current_human_delta": "current_human_delta_manifest.json",
        "review_rebaseline": "review_rebaseline_manifest.json",
        "review_rebaseline_checkpoint": "review_rebaseline_checkpoint.json",
        "independent_decision_preservation": "independent_decision_preservation_manifest.json",
    }
    for key, name in names.items():
        artifacts[key] = {"path": name, "sha256": review.sha256_file(bundle / name)}
        if name.endswith(".json"):
            schema = review.load_json(bundle / name).get("schema_version")
            if schema:
                artifacts[key]["schema_version"] = schema
    for key in ("gate_g", "apply_plan", "rollback_snapshot", "authorization_request"):
        artifacts[key] = {"status": "not_applicable_pending_human_review"}
    manifest = {
        "schema_version": "current-relational-generation-bundle/v1",
        "canon_generation_id": canon_generation, "relation_generation_id": generation,
        "review_state_id": review_state, "readiness_id": None,
        "terminal_state": "READY_FOR_HUMAN_DELTA_REVIEW",
        "next_action": "REVIEW_CURRENT_RELATIONAL_DELTA", "artifacts": artifacts,
    }
    _write(bundle / "bundle_manifest.json", manifest)
    pointer = local / "audit/relation_admission/current_generation.json"
    _write(pointer, {
        "schema_version": "current-relational-generation-pointer/v1", "bundle_path": str(bundle),
        "bundle_manifest_path": str(bundle / "bundle_manifest.json"),
        "bundle_manifest_hash": review.sha256_file(bundle / "bundle_manifest.json"),
        "canon_generation_id": canon_generation, "relation_generation_id": generation,
        "review_state_id": review_state, "readiness_id": None,
        "terminal_state": "READY_FOR_HUMAN_DELTA_REVIEW",
        "next_action": "REVIEW_CURRENT_RELATIONAL_DELTA",
    })
    return local, bundle, queue


def _refresh_current_bundle_hashes(local: Path, bundle: Path) -> None:
    manifest = review.load_json(bundle / "bundle_manifest.json")
    for item in (manifest.get("artifacts") or {}).values():
        if item.get("path"):
            item["sha256"] = review.sha256_file(bundle / item["path"])
    _write(bundle / "bundle_manifest.json", manifest)
    pointer = local / "audit/relation_admission/current_generation.json"
    pointer_payload = review.load_json(pointer)
    pointer_payload["bundle_manifest_hash"] = review.sha256_file(bundle / "bundle_manifest.json")
    _write(pointer, pointer_payload)


def _decision(current: Path, canon: Path, candidate: dict, **overrides: object) -> dict:
    values = {
        "decision": "approved_for_admission",
        "reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED",
        "actor": "operator",
        "bindings": review.current_bindings(current, canon),
    }
    values.update(overrides)
    return review.build_decision_record(candidate, **values)


def _gate(candidates: list[dict], *, gate_022: set[str] | None = None) -> dict:
    gate_022 = gate_022 or set()
    return {
        "items": [
            {
                "candidate_id": candidate["candidate_id"],
                "decision": "blocked_technical" if candidate["candidate_id"] in gate_022 else "admission_ready_dry_run",
                "all_block_reasons": (
                    ["GATE-022: target.repo_path no existe"]
                    if candidate["candidate_id"] in gate_022 else []
                ),
            }
            for candidate in candidates
        ]
    }


def _migration_case(
    tmp_path: Path,
    target_numbers: list[int],
    states: list[str] | None = None,
) -> dict[str, object]:
    states = states or ["approved_for_admission"] * len(target_numbers)
    current_candidates = {
        number: _candidate("rc_current_" + str(number) * 24)
        for number in sorted(set(target_numbers))
    }
    current, canon, _ = _fixture(tmp_path, list(current_candidates.values()))
    current_candidates_path = current / "relation_candidates.jsonl"
    current_candidates_path.write_text(
        "".join(json.dumps(candidate) + "\n" for candidate in current_candidates.values()),
        encoding="utf-8",
    )
    old_candidates = [
        _candidate("rc_current_" + str(index) * 24)
        for index in range(1, len(target_numbers) + 1)
    ]
    historical_candidates = tmp_path / "historical_candidates.jsonl"
    historical_candidates.write_text(
        "".join(json.dumps(candidate) + "\n" for candidate in old_candidates),
        encoding="utf-8",
    )
    reasons = {
        "approved_for_admission": "DIRECT_CODE_DEPENDENCY_CONFIRMED",
        "deferred": "INSUFFICIENT_CONTEXT",
        "rejected": "WRONG_PREDICATE",
    }
    decisions = [
        _decision(
            current,
            canon,
            candidate,
            decision=state,
            reason_code=reasons[state],
            actor=f"operator-{index}",
        )
        for index, (candidate, state) in enumerate(zip(old_candidates, states), start=1)
    ]
    historical_decisions = tmp_path / "historical_decisions.jsonl"
    historical_decisions.write_text(
        "".join(json.dumps(decision) + "\n" for decision in decisions),
        encoding="utf-8",
    )
    audit = tmp_path / "audit"
    audit.mkdir()
    matrix = audit / "old_to_current_reconciliation.jsonl"
    matrix.write_text(
        "".join(
            json.dumps({
                "candidate_id": old["candidate_id"],
                "counterpart_candidate_id": current_candidates[target]["candidate_id"],
                "classification": "equivalent",
                "decision_reusable": True,
            }) + "\n"
            for old, target in zip(old_candidates, target_numbers)
        ),
        encoding="utf-8",
    )
    cross_manifest = audit / "cross_batch_reconciliation_manifest.json"
    _write(cross_manifest, {
        "schema_version": "s0183-cross-batch-reconciliation/v1",
        "historical_candidates_path": str(historical_candidates),
        "historical_candidates_hash": hashlib.sha256(historical_candidates.read_bytes()).hexdigest(),
        "current_candidates_hash": hashlib.sha256(current_candidates_path.read_bytes()).hexdigest(),
        "old_to_current_path": str(matrix),
        "old_to_current_hash": hashlib.sha256(matrix.read_bytes()).hexdigest(),
    })
    return {
        "current": current,
        "canon": canon,
        "old_candidates": old_candidates,
        "current_candidates": current_candidates,
        "historical_decisions": historical_decisions,
        "decisions": decisions,
        "audit": audit,
        "cross_manifest": cross_manifest,
    }


def _preserved_extension_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, historical_count: int = 155,
    direct_count: int = 5, pending_count: int = 7,
) -> tuple[Path, Path, list[dict], list[dict], list[dict]]:
    """A receipt-certified historical subset plus direct current extensions."""
    candidates = [_candidate("rc_current_" + f"{index:024x}") for index in range(
        1, historical_count + direct_count + pending_count + 1,
    )]
    current, canon, _ = _fixture(tmp_path, candidates)
    (current / "relation_candidates.jsonl").write_text(
        "".join(json.dumps(candidate) + "\n" for candidate in candidates), encoding="utf-8",
    )
    bindings = review.current_bindings(current, canon)
    historical = [_decision(current, canon, candidate) for candidate in candidates[:historical_count]]
    audit = tmp_path / "audit" / "s0183" / "current"
    historical_path = tmp_path / "historical_decisions.jsonl"
    historical_path.write_text(
        "".join(json.dumps(record) + "\n" for record in historical), encoding="utf-8",
    )
    matrix = audit / "old_to_current_reconciliation.jsonl"
    matrix.parent.mkdir(parents=True)
    matrix.write_text("".join(json.dumps({
        "candidate_id": record["candidate_id"],
        "counterpart_candidate_id": record["candidate_id"],
        "classification": "equivalent", "decision_reusable": True,
    }) + "\n" for record in historical), encoding="utf-8")
    manifest = audit / "cross_batch_reconciliation_manifest.json"
    _write(manifest, {
        "schema_version": "s0183-cross-batch-reconciliation/v1",
        "old_to_current_hash": review.sha256_file(matrix),
    })
    preserved = [{
        **record,
        "session_id": "S0183",
        "preserved_from_candidate_id": record["candidate_id"],
        "preserved_from_decision_hash": review.decision_hash(record),
        "preserved_from_bindings": {key: record[key] for key in bindings},
        "preservation_classification": "equivalent",
        "preservation_manifest_hash": review.sha256_file(manifest),
    } for record in historical]
    direct = [_decision(current, canon, candidate) for candidate in candidates[historical_count:historical_count + direct_count]]
    decision_path = current / review.DECISIONS_FILE
    decision_path.write_text("".join(json.dumps(record) + "\n" for record in preserved), encoding="utf-8")
    _write(audit / "human_decision_preservation_manifest.json", {
        "cross_batch_manifest_hash": review.sha256_file(manifest),
        "current_decisions_path": str(decision_path),
        "current_decisions_hash": review.sha256_file(decision_path),
        "historical_decisions_path": str(historical_path),
        "historical_decisions_hash": review.sha256_file(historical_path),
        "historical_decision_count": historical_count,
        "migrated_equivalent_count": historical_count,
    })
    decision_path.write_text(
        "".join(json.dumps(record) + "\n" for record in preserved + direct), encoding="utf-8",
    )
    monkeypatch.setattr(review, "DEFAULT_CANON_ROOT", tmp_path)
    return current, canon, candidates, preserved, direct


def test_preserved_subset_allows_current_direct_extensions_and_order_independence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, canon, candidates, preserved, direct = _preserved_extension_fixture(tmp_path, monkeypatch)
    path = current / review.DECISIONS_FILE
    assert review.sha256_file(path) != review.load_json(current.parent / "audit/s0183/current/human_decision_preservation_manifest.json")["current_decisions_hash"]
    loaded = review.load_existing_decisions(path, {row["candidate_id"] for row in candidates}, review.current_bindings(current, canon))
    assert len(loaded.preserved_historical) == 155
    assert len(loaded.current_direct) == 5
    path.write_text("".join(json.dumps(record) + "\n" for record in reversed(preserved + direct)), encoding="utf-8")
    reordered = review.load_existing_decisions(path, {row["candidate_id"] for row in candidates}, review.current_bindings(current, canon))
    assert len(reordered) == 160
    assert len(reordered.preserved_historical) == 155
    gate_path = tmp_path / "gate.json"
    _write(gate_path, _gate(candidates))
    preflight = review.validate_human_review_batch_generation(current, canon, gate_path)
    assert preflight["allowed"]
    assert sum(row["disposition"] == "awaiting_human_review" for row in preflight["partition"]) == 7


@pytest.mark.parametrize("mutation, error", [
    ("missing", "preserved historical decision missing"),
    ("modified", "preserved historical decision integrity mismatch"),
    ("duplicate", "duplicate candidate_id"),
    ("bad_historical_hash", "preserved historical decision integrity mismatch"),
    ("stale_direct", "stale canon_hash"),
    ("bad_direct_manifest", "stale candidate_manifest_hash"),
    ("duplicate_direct", "duplicate candidate_id"),
    ("unclassifiable", "unclassifiable preserved decision"),
    ("bad_receipt", "preservation receipt cross-batch manifest hash mismatch"),
])
def test_preserved_subset_and_direct_extensions_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, error: str,
) -> None:
    current, canon, candidates, preserved, direct = _preserved_extension_fixture(
        tmp_path, monkeypatch, historical_count=2, direct_count=1, pending_count=1,
    )
    path = current / review.DECISIONS_FILE
    rows = review.load_jsonl(path)
    if mutation == "missing":
        rows.pop(0)
    elif mutation == "modified":
        rows[0]["human_review_actor"] = "tampered"
    elif mutation == "duplicate":
        rows.append(dict(rows[0]))
    elif mutation == "bad_historical_hash":
        rows[0]["preserved_from_decision_hash"] = "sha256:" + "0" * 64
    elif mutation == "stale_direct":
        rows[-1]["canon_hash"] = "0" * 64
    elif mutation == "bad_direct_manifest":
        rows[-1]["candidate_manifest_hash"] = "0" * 64
    elif mutation == "duplicate_direct":
        rows.append(dict(rows[-1]))
    elif mutation == "unclassifiable":
        rows[-1]["preservation_classification"] = "equivalent"
    elif mutation == "bad_receipt":
        receipt = current.parent / "audit/s0183/current/human_decision_preservation_manifest.json"
        value = review.load_json(receipt)
        value["cross_batch_manifest_hash"] = "0" * 64
        _write(receipt, value)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        review.load_existing_decisions(path, {row["candidate_id"] for row in candidates}, review.current_bindings(current, canon))


def test_v2_record_is_structured_and_bound(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    record = _decision(current, canon, candidate)
    assert record["schema_version"] == "relation-human-review-decision/v2"
    assert record["human_review_reason_code"] == "DIRECT_CODE_DEPENDENCY_CONFIRMED"
    assert record["human_review_note"] is None
    assert record["approval_scope"] == "canonical_admission"
    assert record["candidate_manifest_hash"] == hashlib.sha256(
        (current / "current_candidate_manifest.json").read_bytes()
    ).hexdigest()


def test_generation_preflight_derives_pending_partition_and_preview(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path, [_candidate("rc_current_" + "a" * 24), _candidate("rc_current_" + "b" * 24)])
    gate_path = tmp_path / "gate.json"
    _write(gate_path, _gate(candidates))
    preflight = review.validate_human_review_batch_generation(current, canon, gate_path)
    assert preflight["allowed"]
    assert [row["candidate_id"] for row in preflight["partition"]] == ["rc_current_" + "a" * 24, "rc_current_" + "b" * 24]
    previews = review.build_batch_previews(candidates, preflight["gate"])
    manifest = review.build_generation_batch_preview(previews, preflight)
    assert manifest["selection"]["selected"] == manifest["partition"]["pending"]
    assert manifest["selection"]["outside_current_queue"] == 0


def test_generation_preflight_blocks_manifest_record_count_drift(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    manifest = review.load_json(current / "current_candidate_manifest.json")
    manifest["canon_binding"]["record_count"] = 2
    _write(current / "current_candidate_manifest.json", manifest)
    reconciliation = review.load_json(current / "reconciliation_manifest.json")
    reconciliation["candidate_manifest_hash"] = hashlib.sha256((current / "current_candidate_manifest.json").read_bytes()).hexdigest()
    _write(current / "reconciliation_manifest.json", reconciliation)
    gate_path = tmp_path / "gate.json"
    _write(gate_path, _gate(candidates))
    preflight = review.validate_human_review_batch_generation(current, canon, gate_path)
    assert not preflight["allowed"]
    assert "batch_preview_relational_generation_missing" in preflight["reason_codes"]


def test_current_delta_inventory_is_pointer_bound_complete_and_deterministically_batched(
    tmp_path: Path,
) -> None:
    local, _bundle, queue = _current_delta_authority_fixture(tmp_path)
    surface = review.resolve_current_human_delta_surface(local)
    assert surface["allowed"] is True
    inventory = surface["inventory"]
    assert inventory["total_pending"] == 3
    assert (inventory["new"], inventory["modified"], inventory["ambiguous"]) == (1, 1, 1)
    assert all(inventory[key] == 0 for key in ("invalid", "duplicated", "covered", "unclassified", "unaccounted"))
    first = review.build_current_human_delta_batches(surface)
    second = review.build_current_human_delta_batches(surface)
    assert first == second
    assert {item["reconciliation_class"] for item in first} == {"new", "modified", "ambiguous"}
    assert sum(item["candidate_count"] for item in first) == len(queue)
    assert len({candidate_id for item in first for candidate_id in item["candidate_ids"]}) == len(queue)


def test_current_delta_taxonomy_conserves_ambiguous_and_rebaseline_batches(
    tmp_path: Path,
) -> None:
    ambiguous_ids = ["rc_current_" + f"{number:024x}" for number in range(1, 5)]
    rebaseline_ids = ["rc_current_" + f"{number:024x}" for number in range(5, 13)]
    local, _bundle, queue = _current_delta_authority_fixture(
        tmp_path,
        candidate_count=12,
        classes={"new": [], "modified": [], "ambiguous": ambiguous_ids},
        rebaseline_uncovered_ids=rebaseline_ids,
    )

    surface = review.resolve_current_human_delta_surface(local)
    assert surface["allowed"] is True
    inventory = surface["inventory"]
    assert inventory["total_pending"] == 12
    assert inventory["reconciliation_ambiguous"] == 4
    assert inventory["rebaseline_uncovered"] == 8
    assert inventory["conservation_valid"] is True

    batches = review.build_current_human_delta_batches(surface)
    assert [batch["review_reason"] for batch in batches] == [
        "reconciliation_ambiguous", "rebaseline_uncovered",
    ]
    assert [batch["candidate_count"] for batch in batches] == [4, 8]
    assert batches[0]["reconciliation_class"] == "ambiguous"
    assert batches[1]["reconciliation_class"] is None
    assert sum(batch["candidate_count"] for batch in batches) == len(queue)
    assert len({candidate_id for batch in batches for candidate_id in batch["candidate_ids"]}) == 12
    assert batches == review.build_current_human_delta_batches(surface)


def test_current_delta_unclassified_candidate_blocks_preview_without_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    local, bundle, _queue = _current_delta_authority_fixture(tmp_path, classes={
        "new": [], "modified": [], "ambiguous": ["rc_current_" + f"{1:024x}"],
    })
    protected = {
        path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in bundle.rglob("*") if path.is_file()
    }
    pointer = local / "audit/relation_admission/current_generation.json"
    pointer_before = pointer.read_bytes()
    surface = review.resolve_current_human_delta_surface(local)
    assert surface["allowed"] is False
    assert "current_review_reason_missing" in surface["reason_codes"]
    assert surface["inventory"]["unclassified"] == 2
    assert review.main([
        "--canon-root", str(local), "--current-dir", str(tmp_path / "pipeline-current"),
        "--preview-batches",
    ]) == 2
    assert "current_review_reason_missing" in capsys.readouterr().out
    assert pointer.read_bytes() == pointer_before
    assert protected == {
        path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in bundle.rglob("*") if path.is_file()
    }


def test_current_delta_covered_candidate_cannot_reenter_preview(
    tmp_path: Path,
) -> None:
    local, bundle, queue = _current_delta_authority_fixture(tmp_path)
    (bundle / "effective_human_review_decisions.jsonl").write_text(
        json.dumps({"candidate_id": queue[0]["candidate_id"]}) + "\n",
        encoding="utf-8",
    )
    _refresh_current_bundle_hashes(local, bundle)

    surface = review.resolve_current_human_delta_surface(local)

    assert surface["allowed"] is False
    assert "current_delta_covered_candidate" in surface["reason_codes"]
    assert surface["inventory"]["covered"] == 1


def test_current_delta_invalid_candidate_cannot_enter_preview(
    tmp_path: Path,
) -> None:
    local, bundle, queue = _current_delta_authority_fixture(tmp_path)
    queue[0]["reconciliation"]["disposition"] = "blocked_technical"
    (bundle / "ready_for_human_review.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in queue), encoding="utf-8",
    )
    _refresh_current_bundle_hashes(local, bundle)

    surface = review.resolve_current_human_delta_surface(local)

    assert surface["allowed"] is False
    assert "current_delta_invalid_candidate" in surface["reason_codes"]
    assert surface["inventory"]["invalid"] == 1


def test_current_delta_preview_is_read_only_and_uses_bundle_not_pipeline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    local, bundle, _queue = _current_delta_authority_fixture(tmp_path)
    pointer = local / "audit/relation_admission/current_generation.json"
    before = {
        "pointer": pointer.read_bytes(),
        "bundle": {
            path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in bundle.rglob("*") if path.is_file()
        },
    }
    assert review.main([
        "--canon-root", str(local), "--current-dir", str(tmp_path / "mutable-pipeline"),
        "--preview-batches",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "read_only_preview"
    assert output["writes_performed"] is False
    assert output["current_authority"]["relation_generation_id"] == "rg_fixture"
    assert output["current_human_delta"]["total_pending"] == 3
    assert before["pointer"] == pointer.read_bytes()
    assert before["bundle"] == {
        path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in bundle.rglob("*") if path.is_file()
    }


def _current_batch_write_case(tmp_path: Path) -> tuple[Path, Path, dict, list[dict]]:
    ambiguous_ids = ["rc_current_" + f"{number:024x}" for number in range(1, 5)]
    rebaseline_ids = ["rc_current_" + f"{number:024x}" for number in range(5, 13)]
    local, bundle, _queue = _current_delta_authority_fixture(
        tmp_path,
        candidate_count=12,
        classes={"new": [], "modified": [], "ambiguous": ambiguous_ids},
        rebaseline_uncovered_ids=rebaseline_ids,
    )
    surface = review.resolve_current_human_delta_surface(local)
    batch = review.build_current_human_delta_batches(surface)[0]
    choices = (
        ("approved_for_admission", "DIRECT_CODE_DEPENDENCY_CONFIRMED"),
        ("rejected", "WRONG_PREDICATE"),
        ("deferred", "INSUFFICIENT_CONTEXT"),
        ("approved_for_admission", "EVIDENCE_AND_ENDPOINTS_VERIFIED"),
    )
    proposals = [{
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "action": action,
        "reason_code": reason,
        "note": "",
        "human_confirmation": review.current_candidate_confirmation(candidate_id, action),
    } for candidate_id, candidate_hash, (action, reason) in zip(
        batch["candidate_ids"], batch["candidate_hashes"], choices, strict=True,
    )]
    return local, bundle, batch, proposals


def test_current_single_batch_write_publishes_receipt_and_new_review_state(
    tmp_path: Path,
) -> None:
    local, source_bundle, batch, proposals = _current_batch_write_case(tmp_path)
    source_before = {
        path.relative_to(source_bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_bundle.rglob("*") if path.is_file()
    }
    canon_before = review.canon_hash(local)

    result = review.persist_current_human_delta_batch(
        local,
        batch=batch,
        proposals=proposals,
        actor="operator",
        confirmation=review.current_batch_confirmation(batch["batch_id"]),
    )

    assert result["decisions_written"] == 4
    assert result["receipt_created"] is True
    assert result["relation_generation_id"] == batch["relation_generation_id"]
    assert result["result_review_state_id"] != batch["review_state_id"]
    assert result["remaining_pending"] == 8
    assert result["terminal_state"] == "READY_FOR_HUMAN_DELTA_REVIEW"
    authority = review.resolve_current_human_delta_surface(local)
    assert authority["allowed"] is True
    assert authority["inventory"]["total_pending"] == 8
    assert authority["inventory"]["rebaseline_uncovered"] == 8
    remaining_batches = review.build_current_human_delta_batches(authority)
    assert [item["review_reason"] for item in remaining_batches] == ["rebaseline_uncovered"]
    receipt = review.load_jsonl(authority["artifacts"]["review_receipts"])[0]
    for field in (
        "receipt_id", "source_relation_generation_id", "source_review_state_id",
        "result_review_state_id", "source_bundle_manifest_hash", "batch_id", "batch_hash",
        "candidate_ids", "candidate_hashes", "decisions_hash", "human_confirmation", "published_at",
    ):
        assert receipt.get(field) not in (None, "", [])
    assert len(review.load_jsonl(authority["artifacts"]["effective_decisions"])) == 4
    published_pointer = review.load_json(
        local / "audit/relation_admission/current_generation.json"
    )
    assert published_pointer["bundle_path"] == result["bundle_path"]
    assert published_pointer["bundle_manifest_path"] == str(
        Path(result["bundle_path"]) / "bundle_manifest.json"
    )
    assert published_pointer["bundle_manifest_hash"] == review.sha256_file(
        Path(result["bundle_path"]) / "bundle_manifest.json"
    )
    assert published_pointer["published_at"]
    assert review.canon_hash(local) == canon_before
    assert source_before == {
        path.relative_to(source_bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_bundle.rglob("*") if path.is_file()
    }
    assert not any("authorization" in path.name for path in Path(result["bundle_path"]).glob("*receipt*"))

    with pytest.raises(review.CurrentReviewWriteBlocked) as blocked:
        review.persist_current_human_delta_batch(
            local,
            batch=batch,
            proposals=proposals,
            actor="operator",
            confirmation=review.current_batch_confirmation(batch["batch_id"]),
        )
    assert blocked.value.reason_codes == ["review_batch_already_consumed"]


@pytest.mark.parametrize(
    ("failure_hook", "reason_code"),
    [
        ("validation", "review_write_validation_failed"),
        ("publication", "review_publication_failed"),
        ("pointer", "review_pointer_update_failed"),
    ],
)
def test_current_single_batch_failures_preserve_pointer_and_only_keep_valid_orphan(
    tmp_path: Path, failure_hook: str, reason_code: str,
) -> None:
    local, source_bundle, batch, proposals = _current_batch_write_case(tmp_path)
    pointer = local / "audit/relation_admission/current_generation.json"
    pointer_before = pointer.read_bytes()
    source_before = {
        path.relative_to(source_bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_bundle.rglob("*") if path.is_file()
    }
    with pytest.raises(review.CurrentReviewWriteBlocked) as blocked:
        review.persist_current_human_delta_batch(
            local,
            batch=batch,
            proposals=proposals,
            actor="operator",
            confirmation=review.current_batch_confirmation(batch["batch_id"]),
            failure_hook=failure_hook,
        )
    assert reason_code in blocked.value.reason_codes
    assert pointer.read_bytes() == pointer_before
    assert source_before == {
        path.relative_to(source_bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_bundle.rglob("*") if path.is_file()
    }
    extra_bundles = [
        path for path in source_bundle.parent.parent.glob("rv_*/human_delta")
        if path != source_bundle
    ]
    if failure_hook == "pointer":
        assert len(extra_bundles) == 1
        orphan = extra_bundles[0]
        manifest = review.load_json(orphan / "bundle_manifest.json")
        review._validate_staged_current_review_bundle(
            orphan,
            relation_generation_id=manifest["relation_generation_id"],
            review_state_id=manifest["review_state_id"],
        )
    else:
        assert extra_bundles == []


def test_current_single_batch_retry_reuses_valid_orphan_idempotently(
    tmp_path: Path,
) -> None:
    local, source_bundle, batch, proposals = _current_batch_write_case(tmp_path)
    pointer = local / "audit/relation_admission/current_generation.json"
    pointer_before = pointer.read_bytes()
    with pytest.raises(review.CurrentReviewWriteBlocked):
        review.persist_current_human_delta_batch(
            local,
            batch=batch,
            proposals=proposals,
            actor="operator",
            confirmation=review.current_batch_confirmation(batch["batch_id"]),
            failure_hook="pointer",
        )
    orphan = next(
        path for path in source_bundle.parent.parent.glob("rv_*/human_delta")
        if path != source_bundle
    )
    orphan_before = {
        path.relative_to(orphan).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in orphan.rglob("*") if path.is_file()
    }
    assert pointer.read_bytes() == pointer_before

    result = review.persist_current_human_delta_batch(
        local,
        batch=batch,
        proposals=proposals,
        actor="operator",
        confirmation=review.current_batch_confirmation(batch["batch_id"]),
    )

    assert Path(result["bundle_path"]) == orphan
    assert orphan_before == {
        path.relative_to(orphan).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in orphan.rglob("*") if path.is_file()
    }
    assert review.load_json(pointer)["bundle_path"] == str(orphan)


def test_current_single_batch_revalidates_batch_candidates_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    local, _source_bundle, batch, proposals = _current_batch_write_case(tmp_path)
    stale_batch = {**batch, "batch_hash": "sha256:" + "0" * 64}
    with pytest.raises(review.CurrentReviewWriteBlocked) as stale:
        review.persist_current_human_delta_batch(
            local, batch=stale_batch, proposals=proposals, actor="operator",
            confirmation=review.current_batch_confirmation(stale_batch["batch_id"]),
        )
    assert stale.value.reason_codes == ["review_batch_changed"]
    duplicate = [proposals[0], proposals[0], *proposals[2:]]
    with pytest.raises(review.CurrentReviewWriteBlocked) as conflict:
        review.persist_current_human_delta_batch(
            local, batch=batch, proposals=duplicate, actor="operator",
            confirmation=review.current_batch_confirmation(batch["batch_id"]),
        )
    assert conflict.value.reason_codes == ["review_decision_conflict"]

    changed = [dict(item) for item in proposals]
    changed[0]["candidate_hash"] = "sha256:" + "f" * 64
    with pytest.raises(review.CurrentReviewWriteBlocked) as candidate_changed:
        review.persist_current_human_delta_batch(
            local, batch=batch, proposals=changed, actor="operator",
            confirmation=review.current_batch_confirmation(batch["batch_id"]),
        )
    assert candidate_changed.value.reason_codes == ["review_candidate_changed"]


def test_current_batch_and_result_ids_ignore_manifest_representation(
    tmp_path: Path,
) -> None:
    local, _source_bundle, first_batch, proposals = _current_batch_write_case(
        tmp_path
    )
    surface = review.resolve_current_human_delta_surface(local)
    second_surface = {
        **surface,
        "inventory": {
            **surface["inventory"],
            "bundle_manifest_hash": "f" * 64,
        },
    }

    second_batch = review.build_current_human_delta_batches(second_surface)[0]
    normalized = review._validate_current_batch_proposals(
        surface, first_batch, proposals, "operator",
    )
    first_ids = review._current_review_semantic_identity(
        surface, first_batch, normalized,
    )
    second_ids = review._current_review_semantic_identity(
        second_surface, second_batch, normalized,
    )

    assert second_batch["batch_id"] == first_batch["batch_id"]
    assert second_batch["batch_hash"] == first_batch["batch_hash"]
    assert second_batch["bundle_manifest_hash"] != first_batch[
        "bundle_manifest_hash"
    ]
    assert second_ids == first_ids


def test_v2_orphan_receipt_retry_ignores_only_source_representation() -> None:
    base = {
        "schema_version": "current-single-batch-review-receipt/v2",
        "receipt_id": "hrr_fixture",
        "source_relation_generation_id": "rg_fixture",
        "source_review_state_id": "rv_physical_a",
        "source_review_state_semantic_hash": "sha256:semantic-source",
        "result_review_state_id": "rv_result",
        "source_bundle_manifest_hash": "a" * 64,
        "batch_id": "hrb_fixture",
        "batch_hash": "sha256:batch",
        "candidate_ids": ["rc_current_" + "a" * 24],
        "candidate_hashes": ["sha256:candidate"],
        "human_confirmation": "confirmed",
    }
    equivalent = {
        **base,
        "source_review_state_id": "rv_physical_b",
        "source_bundle_manifest_hash": "b" * 64,
    }

    assert review._review_receipts_retry_semantics([base]) == (
        review._review_receipts_retry_semantics([equivalent])
    )

    legacy = {**base, "schema_version": "current-single-batch-review-receipt/v1"}
    legacy_equivalent = {
        **equivalent,
        "schema_version": "current-single-batch-review-receipt/v1",
    }
    assert review._review_receipts_retry_semantics([legacy]) != (
        review._review_receipts_retry_semantics([legacy_equivalent])
    )


def test_current_single_batch_invalid_confirmation_and_menu_cancel_are_noops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    local, source_bundle, batch, proposals = _current_batch_write_case(tmp_path)
    pointer = local / "audit/relation_admission/current_generation.json"
    before = pointer.read_bytes()
    assert review.persist_current_human_delta_batch(
        local, batch=batch, proposals=proposals, actor="operator", confirmation="",
    ) == {"cancelled": True, "decisions_written": False, "receipt_created": False}
    monkeypatch.setattr("builtins.input", lambda _: "q")
    assert review.run_current_single_batch_review(local) == 0
    assert pointer.read_bytes() == before
    assert not (source_bundle / "current_review_batch_receipts.jsonl").exists()


def test_current_menu_reaches_final_confirmation_and_invalid_input_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    local, source_bundle, _queue = _current_delta_authority_fixture(
        tmp_path, candidate_count=1,
        classes={"new": ["rc_current_" + f"{1:024x}"], "modified": [], "ambiguous": []},
    )
    surface = review.resolve_current_human_delta_surface(local)
    batch = review.build_current_human_delta_batches(surface)[0]
    candidate_id = batch["candidate_ids"][0]
    answers = iter((
        batch["batch_id"], "operator", "approved_for_admission",
        "DIRECT_CODE_DEPENDENCY_CONFIRMED", "",
        review.current_candidate_confirmation(candidate_id, "approved_for_admission"),
        "NO ES LA CONFIRMACION FINAL",
    ))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    pointer = local / "audit/relation_admission/current_generation.json"
    before = pointer.read_bytes()

    assert review.run_current_single_batch_review(local) == 0

    output = capsys.readouterr().out
    assert "Resumen final de decisiones propuestas" in output
    assert "Confirmación final inválida" in output
    assert pointer.read_bytes() == before
    assert not (source_bundle / "current_review_batch_receipts.jsonl").exists()


def test_current_last_batch_stops_before_readiness_and_authorization(tmp_path: Path) -> None:
    local, source_bundle, _queue = _current_delta_authority_fixture(
        tmp_path, candidate_count=1,
        classes={"new": ["rc_current_" + f"{1:024x}"], "modified": [], "ambiguous": []},
    )
    surface = review.resolve_current_human_delta_surface(local)
    batch = review.build_current_human_delta_batches(surface)[0]
    candidate_id, candidate_hash = batch["candidate_ids"][0], batch["candidate_hashes"][0]
    action = "deferred"
    result = review.persist_current_human_delta_batch(
        local,
        batch=batch,
        proposals=[{
            "candidate_id": candidate_id,
            "candidate_hash": candidate_hash,
            "action": action,
            "reason_code": "INSUFFICIENT_CONTEXT",
            "note": "",
            "human_confirmation": review.current_candidate_confirmation(candidate_id, action),
        }],
        actor="operator",
        confirmation=review.current_batch_confirmation(batch["batch_id"]),
    )
    assert result["remaining_pending"] == 0
    assert result["terminal_state"] == "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION"
    authority = review.resolve_current_relational_authority(local)
    assert authority["terminal_state"] == "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION"
    assert authority["readiness_id"] is None
    manifest = authority["manifest"]
    assert manifest["authorization_created"] is False
    assert manifest["apply_executed"] is False
    assert (manifest["artifacts"].get("authorization_request") or {}).get("status") != "created"
    checkpoint = review.load_json(authority["artifacts"]["decision_checkpoint"])
    assert checkpoint["total_decisions"] == 1
    assert checkpoint["pending_delta"] == 0
    assert checkpoint["previous_checkpoint_or_receipt"] == str(source_bundle)
    assert checkpoint["review_receipts_hash"] == review.sha256_file(
        authority["artifacts"]["review_receipts"]
    )


def test_review_complete_authority_requires_declared_receipt_ledger(
    tmp_path: Path,
) -> None:
    local, _source_bundle, _queue = _current_delta_authority_fixture(
        tmp_path, candidate_count=1,
        classes={"new": ["rc_current_" + f"{1:024x}"], "modified": [], "ambiguous": []},
    )
    surface = review.resolve_current_human_delta_surface(local)
    batch = review.build_current_human_delta_batches(surface)[0]
    candidate_id, candidate_hash = batch["candidate_ids"][0], batch["candidate_hashes"][0]
    result = review.persist_current_human_delta_batch(
        local,
        batch=batch,
        proposals=[{
            "candidate_id": candidate_id,
            "candidate_hash": candidate_hash,
            "action": "deferred",
            "reason_code": "INSUFFICIENT_CONTEXT",
            "note": "",
            "human_confirmation": review.current_candidate_confirmation(
                candidate_id, "deferred",
            ),
        }],
        actor="operator",
        confirmation=review.current_batch_confirmation(batch["batch_id"]),
    )
    bundle = Path(result["bundle_path"])
    manifest = review.load_json(bundle / "bundle_manifest.json")
    manifest["artifacts"].pop("review_receipts")
    _write(bundle / "bundle_manifest.json", manifest)
    pointer = local / "audit/relation_admission/current_generation.json"
    pointer_payload = review.load_json(pointer)
    pointer_payload["bundle_manifest_hash"] = review.sha256_file(
        bundle / "bundle_manifest.json"
    )
    _write(pointer, pointer_payload)

    with pytest.raises(review.CurrentRelationalAuthorityError) as blocked:
        review.resolve_current_relational_authority(local)

    assert "current_bundle_incomplete" in blocked.value.reason_codes


def test_stale_batch_review_does_not_request_reviewer_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    current, canon, candidates = _fixture(tmp_path)
    manifest = review.load_json(current / "current_candidate_manifest.json")
    manifest["canon_binding"]["record_count"] = 2
    _write(current / "current_candidate_manifest.json", manifest)
    reconciliation = review.load_json(current / "reconciliation_manifest.json")
    reconciliation["candidate_manifest_hash"] = hashlib.sha256((current / "current_candidate_manifest.json").read_bytes()).hexdigest()
    _write(current / "reconciliation_manifest.json", reconciliation)
    gate_path = tmp_path / "gate.json"
    _write(gate_path, _gate(candidates))
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("reviewer identity requested"))
    assert review.main(["--current-dir", str(current), "--canon-root", str(canon), "--gate-report", str(gate_path), "--review-batches"]) == 2


def test_batch_confirmation_revalidates_before_atomic_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    current, canon, candidates = _fixture(tmp_path)
    preview = review.build_batch_previews(candidates, _gate(candidates))[0]
    original = review.current_bindings
    calls = 0
    def drifting(*args: object, **kwargs: object) -> dict[str, str]:
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls > 1:
            result["canon_hash"] = "changed"
        return result
    monkeypatch.setattr(review, "current_bindings", drifting)
    with pytest.raises(ValueError, match="batch_confirmation_generation_changed"):
        review.persist_batch_preview(current, canon, preview=preview, actor="operator", confirmation=review.BATCH_CONFIRMATION)
    assert not (current / review.DECISIONS_FILE).exists()


def test_multi_batch_confirmation_revalidates_atomically_before_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    current, canon, candidates = _fixture(tmp_path, [_candidate("rc_current_" + "a" * 24), _candidate("rc_current_" + "b" * 24)])
    gate = _gate(candidates)
    bindings = review.current_bindings(current, canon)
    inventory = review.build_batch_inventory(candidates, gate, {})
    preview = review.build_multi_batch_preview(inventory, [item["batch_id"] for item in inventory], bindings)
    original = review.current_bindings
    calls = 0
    def drifting(*args: object, **kwargs: object) -> dict[str, str]:
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls > 1:
            result["candidate_manifest_hash"] = "changed"
        return result
    monkeypatch.setattr(review, "current_bindings", drifting)
    with pytest.raises(ValueError, match="batch_confirmation_generation_changed"):
        review.persist_multi_batch_preview(
            current, canon, gate_report=gate, preview=preview, actor="operator",
            confirmation=preview["confirmation_required"],
        )
    assert not (current / review.DECISIONS_FILE).exists()


def test_migrate_equivalent_decisions_preserves_authority_and_rebinds(tmp_path: Path) -> None:
    old_candidate = _candidate("rc_current_" + "1" * 24)
    current_candidate = json.loads(json.dumps(old_candidate))
    current_candidate["candidate_id"] = "rc_current_" + "2" * 24
    current_candidate["evidence"]["line"] = 40
    current, canon, _ = _fixture(tmp_path, [current_candidate])
    (current / "relation_candidates.jsonl").write_text(
        json.dumps(current_candidate) + "\n", encoding="utf-8",
    )
    historical_candidates = tmp_path / "historical_candidates.jsonl"
    historical_candidates.write_text(json.dumps(old_candidate) + "\n", encoding="utf-8")
    historical_decisions = tmp_path / "historical_decisions.jsonl"
    old_decision = _decision(current, canon, old_candidate)
    historical_decisions.write_text(json.dumps(old_decision) + "\n", encoding="utf-8")
    historical_bytes = historical_decisions.read_bytes()

    audit = tmp_path / "audit"
    audit.mkdir()
    matrix = audit / "old_to_current_reconciliation.jsonl"
    matrix.write_text(json.dumps({
        "candidate_id": old_candidate["candidate_id"],
        "counterpart_candidate_id": current_candidate["candidate_id"],
        "classification": "equivalent",
        "decision_reusable": True,
    }) + "\n", encoding="utf-8")
    cross_manifest = audit / "cross_batch_reconciliation_manifest.json"
    _write(cross_manifest, {
        "schema_version": "s0183-cross-batch-reconciliation/v1",
        "historical_candidates_path": str(historical_candidates),
        "historical_candidates_hash": hashlib.sha256(historical_candidates.read_bytes()).hexdigest(),
        "current_candidates_hash": hashlib.sha256((current / "relation_candidates.jsonl").read_bytes()).hexdigest(),
        "old_to_current_path": str(matrix),
        "old_to_current_hash": hashlib.sha256(matrix.read_bytes()).hexdigest(),
    })

    report = review.migrate_equivalent_decisions(
        historical_decisions_file=historical_decisions,
        current_dir=current,
        canon_root=canon,
        cross_batch_manifest_path=cross_manifest,
        audit_dir=audit,
    )
    migrated = review.load_jsonl(current / review.DECISIONS_FILE)
    assert report["migrated_equivalent_count"] == 1
    assert report["pending_reviewable_candidate_ids"] == []
    assert migrated[0]["candidate_id"] == current_candidate["candidate_id"]
    assert migrated[0]["human_review_actor"] == old_decision["human_review_actor"]
    assert migrated[0]["human_review_timestamp"] == old_decision["human_review_timestamp"]
    assert migrated[0]["candidate_manifest_hash"] == review.current_bindings(current, canon)["candidate_manifest_hash"]
    assert historical_decisions.read_bytes() == historical_bytes


def test_migrate_equivalent_decisions_blocks_many_to_one_before_writing(tmp_path: Path) -> None:
    old_a = _candidate("rc_current_" + "1" * 24)
    old_b = _candidate("rc_current_" + "2" * 24)
    current_candidate = _candidate("rc_current_" + "3" * 24)
    current, canon, _ = _fixture(tmp_path, [current_candidate])
    current_candidates = current / "relation_candidates.jsonl"
    current_candidates.write_text(json.dumps(current_candidate) + "\n", encoding="utf-8")

    historical_candidates = tmp_path / "historical_candidates.jsonl"
    historical_candidates.write_text(
        json.dumps(old_a) + "\n" + json.dumps(old_b) + "\n", encoding="utf-8",
    )
    historical_decisions = tmp_path / "historical_decisions.jsonl"
    decision_a = _decision(current, canon, old_a, decision="approved_for_admission")
    decision_b = _decision(
        current,
        canon,
        old_b,
        decision="deferred",
        reason_code="INSUFFICIENT_CONTEXT",
    )
    historical_decisions.write_text(
        json.dumps(decision_a) + "\n" + json.dumps(decision_b) + "\n", encoding="utf-8",
    )

    audit = tmp_path / "audit"
    audit.mkdir()
    matrix = audit / "old_to_current_reconciliation.jsonl"
    matrix.write_text(
        "".join(
            json.dumps({
                "candidate_id": old["candidate_id"],
                "counterpart_candidate_id": current_candidate["candidate_id"],
                "classification": "equivalent",
                "decision_reusable": True,
            }) + "\n"
            for old in (old_a, old_b)
        ),
        encoding="utf-8",
    )
    cross_manifest = audit / "cross_batch_reconciliation_manifest.json"
    _write(cross_manifest, {
        "schema_version": "s0183-cross-batch-reconciliation/v1",
        "historical_candidates_path": str(historical_candidates),
        "historical_candidates_hash": hashlib.sha256(historical_candidates.read_bytes()).hexdigest(),
        "current_candidates_hash": hashlib.sha256(current_candidates.read_bytes()).hexdigest(),
        "old_to_current_path": str(matrix),
        "old_to_current_hash": hashlib.sha256(matrix.read_bytes()).hexdigest(),
    })
    destination = current / review.DECISIONS_FILE
    destination.write_bytes(b"original-authority\n")

    with pytest.raises(review.HumanDecisionMigrationBlocked, match="many_to_one_current_id_collision") as blocked:
        review.migrate_equivalent_decisions(
            historical_decisions_file=historical_decisions,
            current_dir=current,
            canon_root=canon,
            cross_batch_manifest_path=cross_manifest,
            audit_dir=audit,
        )

    assert destination.read_bytes() == b"original-authority\n"
    report = review.load_json(blocked.value.report_path)
    assert report["schema_version"] == review.MIGRATION_REPORT_SCHEMA
    assert report["operation"] == {
        "mode": "apply",
        "source_count": 2,
        "historical_count": 2,
        "planned_count": 2,
        "written_count": 0,
        "collision_count": 1,
        "allowed": False,
    }
    assert report["reason_codes"] == ["many_to_one_current_id_collision"]
    assert report["collisions"][0]["current_id"] == current_candidate["candidate_id"]
    assert report["collisions"][0]["source_decision_ids"] == [
        old_a["candidate_id"], old_b["candidate_id"],
    ]
    assert report["collisions"][0]["source_states"] == [
        "approved_for_admission", "deferred",
    ]
    assert report["output"]["target_modified"] is False
    assert report["output"]["partial_output"] is False


def test_migration_late_collision_leaves_no_partial_output(tmp_path: Path) -> None:
    case = _migration_case(tmp_path, [7, 8, 8])
    destination = case["current"] / review.DECISIONS_FILE
    before = b"existing-authority\n"
    destination.write_bytes(before)

    with pytest.raises(review.HumanDecisionMigrationBlocked) as blocked:
        review.migrate_equivalent_decisions(
            historical_decisions_file=case["historical_decisions"],
            current_dir=case["current"],
            canon_root=case["canon"],
            cross_batch_manifest_path=case["cross_manifest"],
            audit_dir=case["audit"],
        )

    report = review.load_json(blocked.value.report_path)
    assert report["operation"]["source_count"] == 3
    assert report["operation"]["written_count"] == 0
    assert report["collisions"][0]["source_decision_ids"] == [
        case["old_candidates"][1]["candidate_id"],
        case["old_candidates"][2]["candidate_id"],
    ]
    assert destination.read_bytes() == before


def test_migration_duplicate_historical_identity_blocks_with_report(tmp_path: Path) -> None:
    case = _migration_case(tmp_path, [7])
    decisions_path = case["historical_decisions"]
    decisions_path.write_bytes(decisions_path.read_bytes() * 2)
    destination = case["current"] / review.DECISIONS_FILE

    with pytest.raises(review.HumanDecisionMigrationBlocked) as blocked:
        review.migrate_equivalent_decisions(
            historical_decisions_file=decisions_path,
            current_dir=case["current"],
            canon_root=case["canon"],
            cross_batch_manifest_path=case["cross_manifest"],
            audit_dir=case["audit"],
        )

    report = review.load_json(blocked.value.report_path)
    assert report["reason_codes"] == ["duplicate_source_decision_id"]
    assert report["operation"]["written_count"] == 0
    assert not destination.exists()


def test_current_single_batch_pointer_drift_is_not_overwritten_by_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    local, source_bundle, batch, proposals = _current_batch_write_case(tmp_path)
    pointer = local / "audit/relation_admission/current_generation.json"
    concurrent_pointer = review.load_json(pointer)
    concurrent_pointer["concurrent_writer_marker"] = "preserve-me"
    original_validate = review._validate_staged_current_review_bundle
    calls = 0

    def validate_then_advance(*args: object, **kwargs: object) -> None:
        nonlocal calls
        original_validate(*args, **kwargs)
        calls += 1
        if calls == 1:
            review.atomic_write_json(pointer, concurrent_pointer)

    monkeypatch.setattr(
        review, "_validate_staged_current_review_bundle", validate_then_advance,
    )
    with pytest.raises(review.CurrentReviewWriteBlocked) as error:
        review.persist_current_human_delta_batch(
            local,
            batch=batch,
            proposals=proposals,
            actor="operator",
            confirmation=review.current_batch_confirmation(batch["batch_id"]),
        )

    assert "current_authority_changed" in error.value.reason_codes
    assert review.load_json(pointer)["concurrent_writer_marker"] == "preserve-me"
    assert [
        path.name for path in source_bundle.parent.parent.iterdir()
        if path.name != source_bundle.parent.name
    ] == []


def test_current_single_batch_checkpoint_classifications_conserve_direct_review(
    tmp_path: Path,
) -> None:
    local, _source_bundle, batch, proposals = _current_batch_write_case(tmp_path)
    result = review.persist_current_human_delta_batch(
        local,
        batch=batch,
        proposals=proposals,
        actor="operator",
        confirmation=review.current_batch_confirmation(batch["batch_id"]),
    )
    bundle = Path(result["bundle_path"])
    checkpoint = review.load_json(bundle / "decision_checkpoint.json")
    rebaseline_checkpoint = review.load_json(
        bundle / "review_rebaseline_checkpoint.json"
    )
    rebaseline = review.load_json(bundle / "review_rebaseline_manifest.json")

    assert checkpoint["total_decisions"] == len(batch["candidate_ids"])
    assert checkpoint["current_direct"] == len(batch["candidate_ids"])
    assert checkpoint["preserved_equivalent"] == 0
    assert checkpoint["preserved_historical"] == 0
    assert {
        item["classification"]
        for item in checkpoint["individual_decision_hashes"]
    } == {"current_direct"}
    assert rebaseline_checkpoint["independently_preserved_effective_decisions"] == 0
    assert rebaseline_checkpoint["current_direct_effective_decisions"] == len(
        batch["candidate_ids"]
    )
    partition = rebaseline["current_candidate_partition"]
    assert partition["independently_covered"] == 0
    assert partition["human_reviewed_covered"] == len(batch["candidate_ids"])
    assert partition["reviewable_total"] == (
        partition["independently_covered"]
        + partition["human_reviewed_covered"]
        + partition["pending_human_review"]
    )


def test_migration_one_to_one_preserves_all_human_states_and_authority(tmp_path: Path) -> None:
    case = _migration_case(
        tmp_path,
        [7, 8, 9],
        states=["approved_for_admission", "deferred", "rejected"],
    )
    report = review.migrate_equivalent_decisions(
        historical_decisions_file=case["historical_decisions"],
        current_dir=case["current"],
        canon_root=case["canon"],
        cross_batch_manifest_path=case["cross_manifest"],
        audit_dir=case["audit"],
    )

    migrated = review.load_jsonl(case["current"] / review.DECISIONS_FILE)
    migrated_by_origin = {row["preserved_from_candidate_id"]: row for row in migrated}
    assert report["operation"]["source_count"] == 3
    assert report["operation"]["planned_count"] == 3
    assert report["operation"]["written_count"] == 3
    assert report["operation"]["allowed"] is True
    assert report["current_decisions_hash"] == review.sha256_file(
        case["current"] / review.DECISIONS_FILE,
    )
    assert len({row["candidate_id"] for row in migrated}) == 3
    for original in case["decisions"]:
        rebound = migrated_by_origin[original["candidate_id"]]
        for field in review.MIGRATION_PRESERVED_FIELDS:
            assert rebound.get(field) == original.get(field), field
        assert rebound["preserved_from_decision_hash"] == review.decision_hash(original)
        assert rebound["preserved_from_bindings"] == {
            "canon_hash": original["canon_hash"],
            "candidate_manifest_hash": original["candidate_manifest_hash"],
            "reconciliation_manifest_hash": original["reconciliation_manifest_hash"],
        }


def test_migration_dry_run_is_deterministic_and_does_not_publish(tmp_path: Path) -> None:
    case = _migration_case(tmp_path, [7, 8])
    kwargs = {
        "historical_decisions_file": case["historical_decisions"],
        "current_dir": case["current"],
        "canon_root": case["canon"],
        "cross_batch_manifest_path": case["cross_manifest"],
        "audit_dir": case["audit"],
        "dry_run": True,
    }
    first = review.migrate_equivalent_decisions(**kwargs)
    first_report_bytes = Path(first["manifest_path"]).read_bytes()
    second = review.migrate_equivalent_decisions(**kwargs)

    assert first["migration_plan_hash"] == second["migration_plan_hash"]
    assert Path(second["manifest_path"]).read_bytes() == first_report_bytes
    assert second["operation"]["written_count"] == 0
    assert second["output"]["target_modified"] is False
    assert second["output"]["target_will_change"] is True
    assert not (case["current"] / review.DECISIONS_FILE).exists()


def test_migration_atomic_publish_failure_preserves_original_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _migration_case(tmp_path, [7])
    destination = case["current"] / review.DECISIONS_FILE
    before = b"existing-authority\n"
    destination.write_bytes(before)
    monkeypatch.setattr(review, "atomic_write_jsonl", mock.Mock(side_effect=OSError("replace failed")))

    with pytest.raises(review.HumanDecisionMigrationBlocked) as blocked:
        review.migrate_equivalent_decisions(
            historical_decisions_file=case["historical_decisions"],
            current_dir=case["current"],
            canon_root=case["canon"],
            cross_batch_manifest_path=case["cross_manifest"],
            audit_dir=case["audit"],
        )

    report = review.load_json(blocked.value.report_path)
    assert report["reason_codes"] == ["migration_plan_not_atomic"]
    assert report["operation"]["written_count"] == 0
    assert Path(report["output"]["backup_path"]).read_bytes() == before
    assert destination.read_bytes() == before


def test_migration_stale_canon_binding_blocks_without_writing(tmp_path: Path) -> None:
    case = _migration_case(tmp_path, [7])
    reconciliation = case["current"] / "reconciliation_manifest.json"
    payload = review.load_json(reconciliation)
    payload["canon_hash"] = "stale-canon-hash"
    _write(reconciliation, payload)

    with pytest.raises(review.HumanDecisionMigrationBlocked) as blocked:
        review.migrate_equivalent_decisions(
            historical_decisions_file=case["historical_decisions"],
            current_dir=case["current"],
            canon_root=case["canon"],
            cross_batch_manifest_path=case["cross_manifest"],
            audit_dir=case["audit"],
        )

    report = review.load_json(blocked.value.report_path)
    assert report["reason_codes"] == ["current_binding_stale"]
    assert report["operation"]["allowed"] is False
    assert report["operation"]["written_count"] == 0
    assert not (case["current"] / review.DECISIONS_FILE).exists()


def test_migration_duplicate_current_queue_identity_blocks(tmp_path: Path) -> None:
    case = _migration_case(tmp_path, [7])
    queue = case["current"] / review.QUEUE_FILE
    queue.write_bytes(queue.read_bytes() * 2)

    with pytest.raises(review.HumanDecisionMigrationBlocked) as blocked:
        review.migrate_equivalent_decisions(
            historical_decisions_file=case["historical_decisions"],
            current_dir=case["current"],
            canon_root=case["canon"],
            cross_batch_manifest_path=case["cross_manifest"],
            audit_dir=case["audit"],
        )

    report = review.load_json(blocked.value.report_path)
    assert report["reason_codes"] == ["duplicate_target_current_id"]
    assert report["operation"]["written_count"] == 0
    assert not (case["current"] / review.DECISIONS_FILE).exists()


def test_migration_equivalent_mapping_to_missing_current_candidate_blocks(tmp_path: Path) -> None:
    case = _migration_case(tmp_path, [7])
    matrix = case["audit"] / "old_to_current_reconciliation.jsonl"
    row = review.load_jsonl(matrix)[0]
    row["counterpart_candidate_id"] = "rc_current_" + "9" * 24
    matrix.write_text(json.dumps(row) + "\n", encoding="utf-8")
    cross_manifest = case["cross_manifest"]
    manifest = review.load_json(cross_manifest)
    manifest["old_to_current_hash"] = hashlib.sha256(matrix.read_bytes()).hexdigest()
    _write(cross_manifest, manifest)

    with pytest.raises(review.HumanDecisionMigrationBlocked) as blocked:
        review.migrate_equivalent_decisions(
            historical_decisions_file=case["historical_decisions"],
            current_dir=case["current"],
            canon_root=case["canon"],
            cross_batch_manifest_path=cross_manifest,
            audit_dir=case["audit"],
        )

    report = review.load_json(blocked.value.report_path)
    assert report["reason_codes"] == ["current_candidate_not_found"]
    assert report["operation"]["written_count"] == 0
    assert not (case["current"] / review.DECISIONS_FILE).exists()


def test_migration_failure_after_replace_rolls_back_original_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _migration_case(tmp_path, [7])
    destination = case["current"] / review.DECISIONS_FILE
    before = b"existing-authority\n"
    destination.write_bytes(before)

    def replace_then_fail(path: Path, decisions: dict[str, dict]) -> None:
        path.write_text("partially-replaced\n", encoding="utf-8")
        raise OSError("directory fsync failed")

    monkeypatch.setattr(review, "atomic_write_jsonl", replace_then_fail)
    with pytest.raises(review.HumanDecisionMigrationBlocked) as blocked:
        review.migrate_equivalent_decisions(
            historical_decisions_file=case["historical_decisions"],
            current_dir=case["current"],
            canon_root=case["canon"],
            cross_batch_manifest_path=case["cross_manifest"],
            audit_dir=case["audit"],
        )

    report = review.load_json(blocked.value.report_path)
    assert report["reason_codes"] == ["migration_plan_not_atomic"]
    assert report["output"]["target_modified"] is False
    assert destination.read_bytes() == before


def test_migration_cli_reports_collision_and_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    case = _migration_case(tmp_path, [7, 7])
    result = review.main([
        "--migrate-equivalent",
        "--historical-decisions", str(case["historical_decisions"]),
        "--cross-batch-manifest", str(case["cross_manifest"]),
        "--migration-audit-dir", str(case["audit"]),
        "--current-dir", str(case["current"]),
        "--canon-root", str(case["canon"]),
    ])
    output = capsys.readouterr().out

    assert result == 2
    assert "HUMAN_DECISION_MIGRATION_BLOCKED" in output
    assert "Se detectó una convergencia many-to-one:" in output
    assert case["current_candidates"][7]["candidate_id"] in output
    assert case["old_candidates"][0]["candidate_id"] in output
    assert case["old_candidates"][1]["candidate_id"] in output
    assert "many_to_one_current_id_collision" in output
    assert "No se migró ninguna decisión." in output
    assert "No se modificó el canon." in output
    assert "No se creó un gate." in output


@pytest.mark.parametrize("reason", ["NA", "na", "N/A", "ok", "approved", ""])
def test_free_text_placeholders_are_not_reason_codes(tmp_path: Path, reason: str) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    with pytest.raises(ValueError, match="human_review_reason_code"):
        _decision(current, canon, candidate, reason_code=reason)


def test_normal_reason_allows_no_note_but_exception_requires_one(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    assert _decision(current, canon, candidate)["human_review_note"] is None
    with pytest.raises(ValueError, match="human_review_note required"):
        _decision(current, canon, candidate, reason_code="OTHER")
    assert _decision(current, canon, candidate, reason_code="OTHER", note="Caso excepcional.")[
        "human_review_note"
    ] == "Caso excepcional."


def test_batch_mode_requires_batch_id(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    with pytest.raises(ValueError, match="decision_batch_id"):
        _decision(current, canon, candidate, decision_mode="batch")


def test_stale_and_duplicate_decisions_fail_closed(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    bindings = review.current_bindings(current, canon)
    record = _decision(current, canon, candidate)
    record["canon_hash"] = "0" * 64
    path = current / review.DECISIONS_FILE
    path.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale canon_hash"):
        review.load_existing_decisions(path, {record["candidate_id"]}, bindings)


def test_legacy_is_recognized_only_when_explicitly_allowed(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    bindings = review.current_bindings(current, canon)
    legacy = {
        "schema_version": review.SCHEMA_HUMAN_DECISION_LINE_LEGACY,
        "candidate_id": candidate["candidate_id"], "human_review_decision": "approved_for_admission",
        "human_review_actor": "operator", "human_review_timestamp": "2026-07-20T00:00:00Z",
        "human_review_rationale": "na", "approval_scope": "canonical_admission",
        **bindings,
    }
    path = current / review.DECISIONS_FILE
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="audit/migration only"):
        review.load_existing_decisions(path, {candidate["candidate_id"]}, bindings)
    assert review.load_existing_decisions(
        path, {candidate["candidate_id"]}, bindings, allow_legacy=True,
    )[candidate["candidate_id"]] == legacy


def test_preview_is_deterministic_and_never_writes(tmp_path: Path) -> None:
    candidates = [_candidate(), _candidate("rc_current_bbbb1122334455667788")]
    current, _, candidates = _fixture(tmp_path, candidates)
    first = review.build_batch_previews(candidates, _gate(candidates))
    second = review.build_batch_previews(list(reversed(candidates)), _gate(candidates))
    assert first == second
    assert first[0]["candidate_count"] == 2
    assert first[0]["writes_performed"] is False
    assert len(first[0]["examples"]) <= 5
    assert not (current / review.DECISIONS_FILE).exists()


def test_gate_022_has_one_explicit_deferred_batch(tmp_path: Path) -> None:
    candidates = [
        _candidate(f"rc_current_{index:016x}") for index in range(17)
    ] + [_candidate("rc_current_eeee1122334455667788")]
    _, _, candidates = _fixture(tmp_path, candidates)
    stale = {candidate["candidate_id"] for candidate in candidates[:17]}
    previews = review.build_batch_previews(candidates, _gate(candidates, gate_022=stale))
    gate_batch = next(item for item in previews if item["selection_rule"].get("gate_code") == "GATE-022")
    assert gate_batch["candidate_count"] == 17
    assert gate_batch["proposed_decision"] == "deferred"
    assert gate_batch["proposed_reason_code"] == "STALE_TARGET_PATH"
    assert gate_batch["review_policy_id"] == "S0181_GATE_022_DEFERRAL_V1"


def test_wrong_confirmation_cancels_batch_without_write(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    preview = review.build_batch_previews(candidates, _gate(candidates))[0]
    assert review.persist_batch_preview(
        current, canon, preview=preview, actor="operator", confirmation="CONFIRM",
    ) == 0
    assert not (current / review.DECISIONS_FILE).exists()


def test_exclusion_remains_pending_and_confirmation_persists_individual_records(tmp_path: Path) -> None:
    candidates = [_candidate(), _candidate("rc_current_bbbb1122334455667788")]
    current, canon, candidates = _fixture(tmp_path, candidates)
    excluded = candidates[1]["candidate_id"]
    preview = review.build_batch_previews(candidates, _gate(candidates), exclusions={excluded})[0]
    assert preview["exclusions"] == [excluded]
    assert preview["candidate_ids"] == [candidates[0]["candidate_id"]]
    assert review.persist_batch_preview(
        current, canon, preview=preview, actor="operator", confirmation=review.BATCH_CONFIRMATION,
    ) == 1
    rows = review.load_jsonl(current / review.DECISIONS_FILE)
    assert [row["candidate_id"] for row in rows] == [candidates[0]["candidate_id"]]
    assert rows[0]["decision_batch_id"] == preview["batch_id"]
    assert excluded not in {row["candidate_id"] for row in rows}


def test_tampered_batch_preview_is_rejected(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    preview = review.build_batch_previews(candidates, _gate(candidates))[0]
    preview["candidate_set_hash"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        review.persist_batch_preview(
            current, canon, preview=preview, actor="operator",
            confirmation=review.BATCH_CONFIRMATION,
        )


def _separate_batch_candidates() -> list[dict]:
    first = _candidate("rc_current_1111111111111111")
    second = _candidate("rc_current_2222222222222222")
    stale = _candidate("rc_current_3333333333333333")
    first["source"]["repo_path"] = "tests/first_test.py"
    second["source"]["repo_path"] = "tests/second_test.py"
    stale["source"]["repo_path"] = "tests/stale_test.py"
    return [first, second, stale]


def _multi_inventory(
    current: Path, canon: Path, candidates: list[dict], gate: dict,
) -> tuple[dict[str, str], dict[str, dict], list[dict]]:
    bindings = review.current_bindings(current, canon)
    decisions = review.load_existing_decisions(
        current / review.DECISIONS_FILE,
        {candidate["candidate_id"] for candidate in candidates},
        bindings,
    )
    return bindings, decisions, review.build_batch_inventory(candidates, gate, decisions)


def test_multi_selection_normalizes_spaces_and_rejects_empty_or_duplicate_ids() -> None:
    assert review.parse_multi_batch_ids(" hrb_b ,hrb_a ") == ["hrb_a", "hrb_b"]
    for invalid in ("", "  ", "hrb_a,", "hrb_a,,hrb_b", "hrb_a, hrb_a"):
        with pytest.raises(ValueError):
            review.parse_multi_batch_ids(invalid)


def test_multiple_homogeneous_batches_persist_individually_and_are_idempotent(tmp_path: Path) -> None:
    candidates = _separate_batch_candidates()[:2]
    current, canon, candidates = _fixture(tmp_path, candidates)
    gate = _gate(candidates)
    bindings = review.current_bindings(current, canon)
    inventory = review.build_batch_inventory(candidates, gate, {})
    selected = [item["batch_id"] for item in inventory]
    preview = review.build_multi_batch_preview(inventory, selected, bindings)
    result = review.persist_multi_batch_preview(
        current, canon, gate_report=gate, preview=preview, actor="operator",
        confirmation=preview["confirmation_required"], note="Revisión homogénea.",
    )
    assert result["persisted"] == 2
    rows = review.load_jsonl(current / review.DECISIONS_FILE)
    assert len(rows) == 2
    assert {row["decision_batch_id"] for row in rows} == set(selected)
    assert {row["multi_review_operation_id"] for row in rows} == {
        preview["multi_review_operation_id"]
    }
    assert len({row["human_review_timestamp"] for row in rows}) == 1
    assert all(row["decision_mode"] == "batch" for row in rows)

    repeated = review.persist_multi_batch_preview(
        current, canon, gate_report=gate, preview=preview, actor="operator",
        confirmation=preview["confirmation_required"], note="Revisión homogénea.",
    )
    assert repeated["persisted"] == 0
    assert repeated["already_reviewed"] == 2
    assert len(review.load_jsonl(current / review.DECISIONS_FILE)) == 2


def test_partial_batch_reports_resolved_and_writes_only_pending_candidate(tmp_path: Path) -> None:
    candidates = [_candidate(), _candidate("rc_current_bbbb1122334455667788")]
    current, canon, candidates = _fixture(tmp_path, candidates)
    gate = _gate(candidates)
    full = review.build_batch_previews(candidates, gate)[0]
    existing = _decision(
        current, canon, candidates[0], decision_mode="batch",
        decision_batch_id=full["batch_id"], review_policy_id=full["review_policy_id"],
    )
    review.atomic_write_jsonl(current / review.DECISIONS_FILE, {existing["candidate_id"]: existing})
    bindings, decisions, inventory = _multi_inventory(current, canon, candidates, gate)
    item = inventory[0]
    assert item["pending_candidates"] == 1
    assert item["already_reviewed_candidates"] == 1
    preview = review.build_multi_batch_preview(inventory, [item["batch_id"]], bindings)
    result = review.persist_multi_batch_preview(
        current, canon, gate_report=gate, preview=preview, actor="operator",
        confirmation=preview["confirmation_required"],
    )
    rows = {row["candidate_id"]: row for row in review.load_jsonl(current / review.DECISIONS_FILE)}
    assert result["persisted"] == 1
    assert result["already_reviewed"] == 1
    assert rows[existing["candidate_id"]] == decisions[existing["candidate_id"]]


def test_multiple_review_rejects_unknown_mixed_or_incompatible_batches(tmp_path: Path) -> None:
    candidates = _separate_batch_candidates()
    current, canon, candidates = _fixture(tmp_path, candidates)
    stale_id = candidates[-1]["candidate_id"]
    gate = _gate(candidates, gate_022={stale_id})
    bindings = review.current_bindings(current, canon)
    inventory = review.build_batch_inventory(candidates, gate, {})
    approved = [item for item in inventory if item["full_preview"]["proposed_decision"] == "approved_for_admission"]
    deferred = next(item for item in inventory if item["full_preview"]["proposed_decision"] == "deferred")
    with pytest.raises(ValueError, match="not live"):
        review.build_multi_batch_preview(inventory, ["hrb_missing"], bindings)
    with pytest.raises(ValueError, match="compatibility signature"):
        review.build_multi_batch_preview(
            inventory, [approved[0]["batch_id"], deferred["batch_id"]], bindings,
        )
    approved[1]["full_preview"]["proposed_reason_code"] = "EVIDENCE_AND_ENDPOINTS_VERIFIED"
    with pytest.raises(ValueError, match="compatibility signature"):
        review.build_multi_batch_preview(
            inventory, [approved[0]["batch_id"], approved[1]["batch_id"]], bindings,
        )
    approved[1]["full_preview"]["proposed_reason_code"] = approved[0]["full_preview"]["proposed_reason_code"]
    approved[1]["full_preview"]["review_policy_id"] = "INCOMPATIBLE_POLICY"
    with pytest.raises(ValueError, match="compatibility signature"):
        review.build_multi_batch_preview(
            inventory, [approved[0]["batch_id"], approved[1]["batch_id"]], bindings,
        )


def test_multiple_review_conflict_does_not_overwrite_existing_decision(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    gate = _gate(candidates)
    full = review.build_batch_previews(candidates, gate)[0]
    conflicting = _decision(
        current, canon, candidates[0], decision="deferred", reason_code="INSUFFICIENT_CONTEXT",
    )
    review.atomic_write_jsonl(current / review.DECISIONS_FILE, {conflicting["candidate_id"]: conflicting})
    before = (current / review.DECISIONS_FILE).read_bytes()
    bindings, _, inventory = _multi_inventory(current, canon, candidates, gate)
    assert inventory[0]["status"] == "conflict"
    with pytest.raises(ValueError, match="conflict"):
        review.build_multi_batch_preview(inventory, [full["batch_id"]], bindings)
    assert (current / review.DECISIONS_FILE).read_bytes() == before


@pytest.mark.parametrize("confirmation", ["", "CONFIRM MULTIPLE REVIEW BATCHES", "wrong"])
def test_multiple_review_wrong_confirmation_writes_nothing(tmp_path: Path, confirmation: str) -> None:
    current, canon, candidates = _fixture(tmp_path)
    gate = _gate(candidates)
    bindings = review.current_bindings(current, canon)
    inventory = review.build_batch_inventory(candidates, gate, {})
    preview = review.build_multi_batch_preview(inventory, [inventory[0]["batch_id"]], bindings)
    result = review.persist_multi_batch_preview(
        current, canon, gate_report=gate, preview=preview, actor="operator",
        confirmation=confirmation,
    )
    assert result["cancelled"] is True
    assert not (current / review.DECISIONS_FILE).exists()


def test_multiple_review_atomic_replace_failure_preserves_existing_authority(tmp_path: Path) -> None:
    candidates = _separate_batch_candidates()[:2]
    current, canon, candidates = _fixture(tmp_path, candidates)
    gate = _gate(candidates)
    existing = _decision(current, canon, candidates[0])
    review.atomic_write_jsonl(current / review.DECISIONS_FILE, {existing["candidate_id"]: existing})
    before = (current / review.DECISIONS_FILE).read_bytes()
    bindings, decisions, inventory = _multi_inventory(current, canon, candidates, gate)
    pending_item = next(item for item in inventory if item["pending_candidates"])
    preview = review.build_multi_batch_preview(inventory, [pending_item["batch_id"]], bindings)
    with mock.patch.object(review.os, "replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            review.persist_multi_batch_preview(
                current, canon, gate_report=gate, preview=preview, actor="operator",
                confirmation=preview["confirmation_required"],
            )
    assert (current / review.DECISIONS_FILE).read_bytes() == before
    assert review.load_jsonl(current / review.DECISIONS_FILE) == list(decisions.values())


def test_multiple_review_interruption_before_confirmation_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, canon, candidates = _fixture(tmp_path)
    gate_path = tmp_path / "gate.json"
    _write(gate_path, _gate(candidates))
    batch_id = review.build_batch_previews(candidates, _gate(candidates))[0]["batch_id"]
    answers: list[object] = [batch_id, KeyboardInterrupt()]

    def interrupted_input(_: str) -> str:
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return str(answer)

    monkeypatch.setattr("builtins.input", interrupted_input)
    assert review.run_multiple_batch_review(current, canon, gate_path, "operator") == 0
    assert not (current / review.DECISIONS_FILE).exists()


def test_cli_apply_batch_requires_the_hash_printed_by_preview(tmp_path: Path) -> None:
    current, canon, candidates = _fixture(tmp_path)
    gate_path = tmp_path / "gate.json"
    _write(gate_path, _gate(candidates))
    preview = review.build_batch_previews(candidates, _gate(candidates))[0]
    base = [
        "--current-dir", str(current), "--canon-root", str(canon),
        "--gate-report", str(gate_path), "--apply-batch", preview["batch_id"],
        "--reviewer", "operator", "--confirmation", review.BATCH_CONFIRMATION,
    ]
    assert review.main(base) == 2
    assert not (current / review.DECISIONS_FILE).exists()
    assert review.main(base + ["--candidate-set-hash", preview["candidate_set_hash"]]) == 0
    assert len(review.load_jsonl(current / review.DECISIONS_FILE)) == 1


def _legacy_supersession_fixture(tmp_path: Path) -> tuple[Path, Path, Path, bytes, bytes]:
    local = tmp_path / "local"
    current = local / "pipeline" / "relation_candidates" / "current"
    canon = local
    candidate = _candidate()
    current.mkdir(parents=True)
    (canon / "tiddlers_1.jsonl").write_text('{"id":"src"}\n', encoding="utf-8")
    (current / review.QUEUE_FILE).write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    _write(current / "current_candidate_manifest.json", {"current": True})
    _write(current / "reconciliation_manifest.json", {"current": True})
    bindings = review.current_bindings(current, canon)
    legacy = {
        "schema_version": review.SCHEMA_HUMAN_DECISION_LINE_LEGACY,
        "candidate_id": candidate["candidate_id"], "human_review_decision": "approved_for_admission",
        "human_review_actor": "operator", "human_review_timestamp": "2026-07-20T00:00:00Z",
        "human_review_rationale": "na", "approval_scope": "canonical_admission", **bindings,
    }
    decisions_bytes = (json.dumps(legacy, sort_keys=True) + "\n").encode()
    audit_bytes = b'{"legacy_event":true}\n'
    (current / review.DECISIONS_FILE).write_bytes(decisions_bytes)
    (current / review.AUDIT_FILE).write_bytes(audit_bytes)
    gate_dir = local / "audit" / "relation_admission" / "current"
    gate_path = gate_dir / "admission_gate_dry_run.json"
    _write(gate_path, {"summary": {
        "total_evaluated": 1, "approved_for_admission": 1,
        "human_rejected": 0, "human_deferred": 0,
    }})
    _write(gate_dir / "current_run_manifest.json", {
        "human_review_decisions_hash": hashlib.sha256(decisions_bytes).hexdigest(),
        "report_hash": hashlib.sha256(gate_path.read_bytes()).hexdigest(),
    })
    return current, canon, local / "audit" / "s0181", decisions_bytes, audit_bytes


def test_supersession_preserves_bytes_hash_and_resets_current_authority(tmp_path: Path) -> None:
    current, canon, audit_root, decisions_before, audit_before = _legacy_supersession_fixture(tmp_path)
    canon_before = review.canon_hash(canon)
    manifest_path = review.supersede_legacy_current(
        current, canon, audit_root, actor="operator", note="La justificación libre no es auditable.",
        confirmation=review.SUPERSESSION_CONFIRMATION, timestamp="20260721T120000Z",
    )
    history = manifest_path.parent
    manifest = review.load_json(manifest_path)
    assert (history / review.DECISIONS_FILE).read_bytes() == decisions_before
    assert (history / review.AUDIT_FILE).read_bytes() == audit_before
    assert manifest["previous_hash"] == hashlib.sha256(decisions_before).hexdigest()
    assert manifest["status"] == "superseded_not_authoritative"
    assert manifest["apply_executed"] is False
    assert manifest["canon_modified"] is False
    assert (current / review.DECISIONS_FILE).read_bytes() == b""
    assert review.canon_hash(canon) == canon_before
    assert (history / review.AUDIT_FILE).read_bytes() == audit_before


def test_supersession_requires_exact_confirmation_and_complete_evidence(tmp_path: Path) -> None:
    current, canon, audit_root, decisions_before, _ = _legacy_supersession_fixture(tmp_path)
    with pytest.raises(ValueError, match="exact confirmation"):
        review.supersede_legacy_current(
            current, canon, audit_root, actor="operator", note="Motivo.", confirmation="WRONG",
        )
    assert (current / review.DECISIONS_FILE).read_bytes() == decisions_before
    (audit_root.parent / "relation_admission" / "current" / "current_run_manifest.json").unlink()
    with pytest.raises(ValueError, match="gate report and run manifest"):
        review.supersede_legacy_current(
            current, canon, audit_root, actor="operator", note="Motivo.",
            confirmation=review.SUPERSESSION_CONFIRMATION, timestamp="20260721T130000Z",
        )
    assert not (audit_root / "human_review_superseded" / "20260721T130000Z").exists()
    assert (current / review.DECISIONS_FILE).read_bytes() == decisions_before


def test_individual_supersession_records_previous_hash_and_note(tmp_path: Path) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    previous = _decision(current, canon, candidate)
    review.atomic_write_jsonl(current / review.DECISIONS_FILE, {candidate["candidate_id"]: previous})
    new = review.supersede_individual_decision(
        current, canon, candidate_id=candidate["candidate_id"], decision="deferred",
        reason_code="INSUFFICIENT_CONTEXT", note="Revisión manual posterior.", actor="operator-2",
        confirmation=review.DECISION_SUPERSESSION_CONFIRMATION,
    )
    assert new["supersedes_decision_hash"] == review.decision_hash(previous)
    event = review.load_jsonl(current / review.AUDIT_FILE)[0]
    assert event["action"] == "decision_superseded"
    assert event["previous_decision"] == previous


def test_quit_and_audit_failure_keep_safe_authority_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, canon, (candidate,) = _fixture(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: "q")
    assert review.run_review(current, canon, "operator") == 0
    assert not (current / review.DECISIONS_FILE).exists()

    answers = iter(("d", "INSUFFICIENT_CONTEXT", ""))
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(review, "append_audit", mock.Mock(side_effect=OSError("audit unavailable")))
    with pytest.raises(RuntimeError, match="authoritative decision persisted"):
        review.run_review(current, canon, "operator")
    assert review.load_jsonl(current / review.DECISIONS_FILE)[0]["candidate_id"] == candidate["candidate_id"]


def test_empty_actor_is_rejected_before_queue_is_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review, "current_bindings", lambda *_: pytest.fail("queue opened before actor validation"))
    assert review.main([
        "--current-dir", str(tmp_path), "--canon-root", str(tmp_path), "--reviewer", "  ",
    ]) == 2
