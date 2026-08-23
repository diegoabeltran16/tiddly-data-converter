from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))

import prepare_current_relational_generation as preparation  # noqa: E402
import current_relation_human_review as human_review  # noqa: E402
import current_relational_apply as current_apply  # noqa: E402
import current_relational_authority as current_authority  # noqa: E402
import relation_admission_gate as gate  # noqa: E402
import relation_admission_state as admission_state  # noqa: E402


def _candidate(candidate_id: str, *, target: str = "target") -> dict:
    return {
        "candidate_id": candidate_id,
        "candidate_schema_version": "technical-relation-candidates/v1",
        "artifact_family": "relation_candidate",
        "status": "resolved_for_human_review",
        "relation_type": "references",
        "source": {"canonical_id": "source"},
        "target": {"canonical_id": target},
        "evidence": {"evidence_kind": "path_literal", "confidence": "high"},
    }


def _decision() -> dict:
    return {
        "human_review_decision": "approved_for_admission",
        "approval_scope": "canonical_admission",
        "human_review_reason_code": "EXPLICIT_REFERENCE_CONFIRMED",
    }


def _plan(tmp_path: Path, candidates: list[dict]) -> dict:
    report_path = tmp_path / "gate.json"
    report_path.write_text("{}\n", encoding="utf-8")
    decisions = {candidate["candidate_id"]: _decision() for candidate in candidates}
    return gate.build_apply_plan(
        candidates=candidates,
        canon_glob=str(tmp_path / "tiddlers_*.jsonl"),
        human_review_decisions=decisions,
        dry_run_report={
            "items": [
                {"candidate_id": candidate["candidate_id"], "gate_status": gate.ADMISSION_READY}
                for candidate in candidates
            ],
        },
        dry_run_report_path=report_path,
        dry_run_recent=True,
    )


def test_authoritative_plan_traces_duplicate_representation_and_conserves_partition(
    tmp_path: Path,
) -> None:
    first = _candidate("rc_current_" + "1" * 24)
    duplicate = _candidate("rc_current_" + "2" * 24)

    plan = _plan(tmp_path, [first, duplicate])

    assert plan["approved_candidate_representations"] == 2
    assert plan["planned_unique_relations"] == 1
    assert plan["omitted_planned_count"] == 1
    assert plan["unaccounted_approved_representations"] == 0
    assert plan["conservation_valid"] is True
    assert plan["approved_candidate_representations"] == (
        plan["planned_unique_relations"]
        + plan["omitted_planned_count"]
        + plan["unaccounted_approved_representations"]
    )
    omission = plan["omitted_duplicate_representations"][0]
    assert omission["candidate_id"] == duplicate["candidate_id"]
    assert omission["selected_representative_candidate_id"] == first["candidate_id"]
    assert omission["omission_reason"] == "duplicate_representation_omitted"
    assert len(omission["canonical_relation_identity"]) == 64
    preparation.validate_plan_conservation(plan)


def test_exact_duplicate_representations_produce_one_planned_relation(tmp_path: Path) -> None:
    candidates = [_candidate("rc_current_" + f"{number:024x}") for number in range(1, 10)]
    plan = _plan(tmp_path, candidates)

    assert plan["approved_candidate_representations"] == 9
    assert plan["planned_unique_relations"] == 1
    assert plan["omitted_planned_count"] == 8
    assert len(plan["omitted_duplicate_representations"]) == 8


def test_unaccounted_approved_representation_blocks(tmp_path: Path) -> None:
    plan = _plan(tmp_path, [_candidate("rc_current_" + "3" * 24)])
    plan["unaccounted_approved_candidate_ids"] = plan["approved_candidate_ids"][:]
    plan["unaccounted_approved_representations"] = 1
    plan["conservation_valid"] = False

    with pytest.raises(preparation.PreparationBlocked) as error:
        preparation.validate_plan_conservation(plan)

    assert "approved_representation_unaccounted" in error.value.reason_codes
    assert "approved_partition_conservation_failed" in error.value.reason_codes


def test_representation_accounted_twice_blocks(tmp_path: Path) -> None:
    plan = _plan(tmp_path, [_candidate("rc_current_" + "4" * 24)])
    plan["omitted_duplicate_representations"] = [{
        "candidate_id": plan["would_apply_candidate_ids"][0],
        "selected_representative_candidate_id": plan["would_apply_candidate_ids"][0],
        "omission_reason": "duplicate_representation_omitted",
        "canonical_relation_identity": "a" * 64,
        "evidence": {"source_id": "source", "target_id": "target", "relation_type": "references"},
    }]

    with pytest.raises(preparation.PreparationBlocked) as error:
        preparation.validate_plan_conservation(plan)

    assert "approved_representation_accounted_more_than_once" in error.value.reason_codes


def test_duplicate_with_conflicting_effective_identity_blocks(tmp_path: Path) -> None:
    first = _candidate("rc_current_" + "5" * 24)
    duplicate = _candidate("rc_current_" + "6" * 24)
    plan = _plan(tmp_path, [first, duplicate])
    plan["omitted_duplicate_representations"][0]["evidence"]["target_id"] = "different-target"

    with pytest.raises(preparation.PreparationBlocked) as error:
        preparation.validate_plan_conservation(plan)

    assert "duplicate_group_identity_conflict" in error.value.reason_codes


def test_productive_dry_run_derives_136_as_128_plus_8_without_writes() -> None:
    paths = preparation.Paths.from_local_root(REPO_ROOT / "data/out/local")
    canon_paths = sorted(paths.local_root.glob("tiddlers_*.jsonl"))
    decisions_path = paths.current_dir / "human_review_decisions.jsonl"
    effective_path = paths.current_dir / preparation.EFFECTIVE_DECISIONS_FILE
    pointer_payload = preparation.read_json(paths.pointer)
    pointer_bundle = Path(pointer_payload["bundle_path"])
    pointer_manifest = preparation.read_json(pointer_bundle / "bundle_manifest.json")
    checkpoint_item = pointer_manifest["artifacts"]["decision_checkpoint"]
    pointer_checkpoint = preparation.read_json(pointer_bundle / checkpoint_item["path"])
    certified_predecessor = Path(pointer_checkpoint["previous_checkpoint_or_receipt"])
    predecessor_review_state = preparation.read_json(
        certified_predecessor / "bundle_manifest.json"
    )["review_state_id"]
    protected_history = [pointer_bundle, certified_predecessor]
    def protected_hashes() -> dict[str, str]:
        return {
            str(path.relative_to(paths.local_root)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for root in protected_history for path in root.rglob("*")
            if path.is_file()
        }
    before = {
        "canon": [(path.name, hashlib.sha256(path.read_bytes()).hexdigest()) for path in canon_paths],
        "decisions": hashlib.sha256(decisions_path.read_bytes()).hexdigest(),
        "effective_decisions": hashlib.sha256(effective_path.read_bytes()).hexdigest(),
        "historical_bundles": protected_hashes(),
        "pointer": paths.pointer.read_bytes() if paths.pointer.exists() else None,
    }

    first = preparation.dry_run(paths)
    second = preparation.dry_run(paths)

    # The technical pipeline is current while the generational authority is
    # stale.  The receipt-certified review lineage must recover coverage
    # without publishing the productive successor.
    assert first["expected_terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert first["ids"]["review_state_id"]
    assert first["ids"]["readiness_id"]
    assert first["review_coverage"] == {
        "technical_reviewable": 153,
        "expected_equivalent_covered": 153,
        "effective_decision_covered": 153,
        "effective_pending": 0,
        "predecessor_review_state_id": predecessor_review_state,
        "receipt_count": 2,
        "monotonic": True,
    }
    assert first["planning"] == {
        "approved_candidate_representations": 136,
        "planned_unique_relations": 128,
        "omitted_duplicate_representations": 8,
        "unaccounted_approved_representations": 0,
        "conservation_valid": True,
    }
    assert "current_bundle_canon_stale" in first["reason_codes"]
    assert second == first
    assert first["writes_performed"] is False
    after = {
        "canon": [(path.name, hashlib.sha256(path.read_bytes()).hexdigest()) for path in canon_paths],
        "decisions": hashlib.sha256(decisions_path.read_bytes()).hexdigest(),
        "effective_decisions": hashlib.sha256(effective_path.read_bytes()).hexdigest(),
        "historical_bundles": protected_hashes(),
        "pointer": paths.pointer.read_bytes() if paths.pointer.exists() else None,
    }
    assert after == before


def test_missing_current_bundle_status_is_fail_closed(tmp_path: Path) -> None:
    status = preparation.read_current_bundle_status(tmp_path / "local")
    assert status == {"valid": False, "reason_codes": ["current_bundle_missing"]}


def test_semantic_review_hashes_ignore_physical_paths_hashes_and_timestamps(
    tmp_path: Path,
) -> None:
    first_decisions = tmp_path / "first-decisions.jsonl"
    second_decisions = tmp_path / "second-decisions.jsonl"
    base = {
        "candidate_id": "rc_current_" + "1" * 24,
        "candidate_hash": "sha256:" + "2" * 64,
        "human_review_decision": "approved_for_admission",
        "human_review_reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED",
        "human_review_actor": "operator",
        "human_review_timestamp": "2026-01-01T00:00:00Z",
        "canon_hash": "3" * 64,
        "candidate_manifest_hash": "4" * 64,
        "reconciliation_manifest_hash": "5" * 64,
        "reviewed_evidence_paths": ["/first/location"],
    }
    preparation.write_jsonl(first_decisions, [base])
    preparation.write_jsonl(second_decisions, [{
        **base,
        "human_review_timestamp": "2030-12-31T23:59:59Z",
        "canon_hash": "6" * 64,
        "candidate_manifest_hash": "7" * 64,
        "reconciliation_manifest_hash": "8" * 64,
        "reviewed_evidence_paths": ["/relocated/evidence"],
    }])
    assert preparation._semantic_human_decisions_hash(
        first_decisions
    ) == preparation._semantic_human_decisions_hash(second_decisions)

    changed = {**base, "human_review_decision": "deferred"}
    preparation.write_jsonl(second_decisions, [changed])
    assert preparation._semantic_human_decisions_hash(
        first_decisions
    ) != preparation._semantic_human_decisions_hash(second_decisions)

    first_lineage = tmp_path / "first-lineage.json"
    second_lineage = tmp_path / "second-lineage.json"
    lineage = {
        "schema_version": "current-review-receipt-lineage/v1",
        "source_bundle_path": "/first/bundle",
        "source_bundle_manifest_hash": "a" * 64,
        "source_relation_generation_id": "rg_semantic",
        "source_review_state_id": "rv_source",
        "source_effective_decisions_hash": "b" * 64,
        "source_review_receipts_path": "/first/receipts.jsonl",
        "source_review_receipts_hash": "c" * 64,
        "carried_review_receipts_hash": "d" * 64,
        "receipt_count": 1,
        "receipt_ids": ["hrr_semantic"],
        "receipt_candidate_ids": [base["candidate_id"]],
        "root_review_state_id": "rv_root",
        "tip_review_state_id": "rv_tip",
        "preserved_equivalent": 1,
        "preservation_mapping_hash": "e" * 64,
        "integrity_verified": True,
    }
    preparation.write_json(first_lineage, lineage)
    preparation.write_json(second_lineage, {
        **lineage,
        "source_bundle_path": "/relocated/bundle",
        "source_bundle_manifest_hash": "1" * 64,
        "source_effective_decisions_hash": "2" * 64,
        "source_review_receipts_path": "/relocated/receipts.jsonl",
        "source_review_receipts_hash": "3" * 64,
        "carried_review_receipts_hash": "4" * 64,
        "receipt_ids": ["hrr_representationally_different"],
        "root_review_state_id": "rv_representational_root",
        "tip_review_state_id": "rv_representational_tip",
        "preservation_mapping_hash": "5" * 64,
    })
    assert preparation._review_lineage_semantic_hash(
        first_lineage
    ) == preparation._review_lineage_semantic_hash(second_lineage)


def test_relation_generation_identity_ignores_candidate_inventory_path(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    analysis = preparation.analyze(paths)
    first = analysis["ids"]
    candidate_manifest_path = analysis["inputs"]["candidate_manifest"]
    candidate_manifest = preparation.read_json(candidate_manifest_path)
    candidate_manifest["candidate_batch"]["path"] = (
        "/relocated/without/semantic/change/relation_candidates.jsonl"
    )
    preparation.write_json(candidate_manifest_path, candidate_manifest)

    relocated = preparation.generation_ids(
        analysis["canon"],
        analysis["inputs"],
        preparation._semantic_human_decisions_hash(
            analysis["inputs"]["human_decisions"]
        ),
        analysis["pending_ids"],
        analysis["gate_report"],
        analysis["review_taxonomy"],
        preparation._review_lineage_semantic_hash(
            analysis["inputs"].get("review_lineage")
        ),
    )

    assert relocated["relation_generation_id"] == first[
        "relation_generation_id"
    ]
    assert relocated["review_state_id"] == first["review_state_id"]


def test_status_revalidates_artifact_hash_instead_of_trusting_pointer(tmp_path: Path) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    result = preparation.execute(paths, source_root=source_root)
    bundle = Path(result["bundle_path"])
    assert preparation.read_current_bundle_status(paths.local_root)["valid"] is True

    with (bundle / "relation_candidates.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")

    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["valid"] is False
    assert "current_bundle_artifact_hash_mismatch" in status["reason_codes"]


@pytest.mark.parametrize(
    ("corruption", "reason_code"),
    [
        ("unknown_terminal", "current_bundle_terminal_invalid"),
        ("pointer_terminal_mismatch", "terminal_state_identity_mismatch"),
        ("terminal_next_action_mismatch", "current_bundle_next_action_invalid"),
    ],
)
def test_current_authority_rejects_terminal_and_next_action_incoherence(
    tmp_path: Path,
    corruption: str,
    reason_code: str,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    pointer = preparation.read_json(paths.pointer)
    bundle = Path(pointer["bundle_path"])
    manifest_path = bundle / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)

    if corruption == "unknown_terminal":
        manifest["terminal_state"] = "UNKNOWN_RELATIONAL_TERMINAL"
        manifest["next_action"] = "UNKNOWN_RELATIONAL_ACTION"
        pointer["terminal_state"] = manifest["terminal_state"]
    elif corruption == "pointer_terminal_mismatch":
        pointer["terminal_state"] = preparation.TERMINAL_AUTHORIZATION
    else:
        manifest["next_action"] = "AUTHORIZE_CURRENT_RELATIONAL_APPLY"
        pointer["next_action"] = "REVIEW_CURRENT_RELATIONAL_DELTA"

    if corruption != "pointer_terminal_mismatch":
        preparation.write_json(manifest_path, manifest)
        pointer["bundle_manifest_hash"] = preparation.sha256_file(manifest_path)
    preparation.write_json(paths.pointer, pointer)

    with pytest.raises(
        current_authority.CurrentRelationalAuthorityError,
    ) as blocked:
        current_authority.resolve_current_relational_authority(paths.local_root)

    assert reason_code in blocked.value.reason_codes


def test_authorization_request_schema_never_represents_an_authorization() -> None:
    assert preparation.SCHEMA_AUTHORIZATION_REQUEST.endswith("request/v1")
    source = (REPO_ROOT / "src/python_scripts/prepare_current_relational_generation.py").read_text()
    assert '"authorization_present": False' in source
    assert '"authorization_created": False' in source


def _canon_record(identifier: str, repo_path: str, text: str) -> dict:
    return {
        "id": identifier,
        "title": repo_path,
        "key": repo_path,
        "version_id": f"sha256:{identifier}",
        "text": text,
        "source_fields": {
            "repo_path": repo_path,
            "artifact_family": "python_script",
            "authority_level": "canonical",
            # The gate resolves repo paths against the real repository root;
            # fixture-only paths are therefore declared historical explicitly.
            "repo_lifecycle_state": "historical_snapshot",
            "canonical_status": "active",
        },
        "relations": [],
    }


def _write_canon(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _rebuild_fixture(tmp_path: Path) -> tuple[preparation.Paths, Path, list[dict]]:
    local = tmp_path / "local"
    source_root = tmp_path / "repo"
    scripts = source_root / "src" / "python_scripts"
    scripts.mkdir(parents=True)
    (scripts / "a.py").write_text("import b\n", encoding="utf-8")
    (scripts / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
    rows = [
        _canon_record("source-a", "src/python_scripts/a.py", "import b\n"),
        _canon_record("target-b", "src/python_scripts/b.py", "VALUE = 1\n"),
    ]
    _write_canon(local / "tiddlers_1.jsonl", rows)
    baseline = local / "audit" / "s0180" / "pre_relational_rag_baseline_manifest.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        json.dumps({"schema_version": "pre-relational-rag-baseline/v1", "fixture": True}) + "\n",
        encoding="utf-8",
    )
    return preparation.Paths.from_local_root(local), source_root, rows


def _review_all_pending(paths: preparation.Paths) -> None:
    queue = preparation.read_jsonl(paths.current_dir / "ready_for_human_review.jsonl")
    bindings = human_review.current_bindings(paths.current_dir, paths.local_root)
    decisions_path = paths.current_dir / "human_review_decisions.jsonl"
    existing = {
        str(row["candidate_id"]): row
        for row in preparation.read_jsonl(decisions_path)
    }
    for candidate in queue:
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in existing:
            continue
        existing[candidate_id] = human_review.build_decision_record(
            candidate,
            decision="approved_for_admission",
            reason_code="DIRECT_CODE_DEPENDENCY_CONFIRMED",
            actor="fixture-reviewer",
            bindings=bindings,
            note="fixture review",
            reviewed_at="2026-08-03T00:00:00+00:00",
        )
    human_review.atomic_write_jsonl(decisions_path, existing)


def _complete_current_review_transactionally(
    paths: preparation.Paths,
) -> tuple[Path, Path, dict]:
    """Consume the isolated fixture's last batch through the governed writer."""
    surface = human_review.resolve_current_human_delta_surface(paths.local_root)
    assert surface["allowed"] is True
    batches = human_review.build_current_human_delta_batches(surface)
    assert len(batches) == 1
    batch = batches[0]
    proposals = [{
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "action": "approved_for_admission",
        "reason_code": "DIRECT_CODE_DEPENDENCY_CONFIRMED",
        "note": "fixture review",
        "human_confirmation": human_review.current_candidate_confirmation(
            candidate_id, "approved_for_admission",
        ),
    } for candidate_id, candidate_hash in zip(
        batch["candidate_ids"], batch["candidate_hashes"], strict=True,
    )]
    source_bundle = Path(surface["bundle_path"])
    result = human_review.persist_current_human_delta_batch(
        paths.local_root,
        batch=batch,
        proposals=proposals,
        actor="fixture-reviewer",
        confirmation=human_review.current_batch_confirmation(batch["batch_id"]),
    )
    assert result["remaining_pending"] == 0
    assert result["terminal_state"] == preparation.TERMINAL_REVIEW_COMPLETE
    return source_bundle, Path(result["bundle_path"]), result


def _point_to_regressive_review_bundle(
    paths: preparation.Paths,
    source_bundle: Path,
    certified_predecessor: Path,
) -> Path:
    """Publish a fixture pointer whose checkpoint names its advanced ancestor."""
    source_manifest = preparation.read_json(source_bundle / "bundle_manifest.json")
    relation_id = str(source_manifest["relation_generation_id"])
    regression = (
        paths.generations / relation_id
        / "rv_regressive_fixture" / "human_delta"
    )
    shutil.copytree(source_bundle, regression)
    manifest = preparation.read_json(regression / "bundle_manifest.json")
    checkpoint_item = manifest["artifacts"]["decision_checkpoint"]
    checkpoint_path = regression / checkpoint_item["path"]
    checkpoint = preparation.read_json(checkpoint_path)
    checkpoint["previous_checkpoint_or_receipt"] = str(certified_predecessor)
    preparation.write_json(checkpoint_path, checkpoint)
    checkpoint_item["sha256"] = preparation.sha256_file(checkpoint_path)
    preparation.write_json(regression / "bundle_manifest.json", manifest)
    preparation.write_json(paths.pointer, {
        "schema_version": preparation.SCHEMA_POINTER,
        "bundle_path": str(regression),
        "bundle_manifest_path": str(regression / "bundle_manifest.json"),
        "bundle_manifest_hash": preparation.sha256_file(
            regression / "bundle_manifest.json"
        ),
        "canon_generation_id": manifest.get("canon_generation_id"),
        "relation_generation_id": manifest.get("relation_generation_id"),
        "review_state_id": manifest.get("review_state_id"),
        "readiness_id": manifest.get("readiness_id"),
        "terminal_state": manifest.get("terminal_state"),
    })
    return regression


def test_regressive_pointer_recovers_explicit_receipt_certified_predecessor(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    source_bundle, complete_bundle, _ = _complete_current_review_transactionally(paths)
    regression = _point_to_regressive_review_bundle(
        paths, source_bundle, complete_bundle,
    )

    predecessor = preparation._resolve_monotonic_review_predecessor(paths)

    assert predecessor["recovered_from_regression"] is True
    assert predecessor["bundle"] == complete_bundle.resolve()
    assert predecessor["pointer_bundle"] == regression.resolve()
    assert len(predecessor["decision_by_id"]) == 1
    assert predecessor["receipt_lineage"] == {
        "root_review_state_id": preparation.read_json(
            source_bundle / "bundle_manifest.json"
        )["review_state_id"],
        "tip_review_state_id": preparation.read_json(
            complete_bundle / "bundle_manifest.json"
        )["review_state_id"],
        "receipt_count": 1,
        "receipt_ids": [predecessor["receipts"][0]["receipt_id"]],
        "consumed_candidate_ids": sorted(predecessor["decision_by_id"]),
        "integrity_verified": True,
    }


def test_equal_decision_coverage_recovers_receipt_complete_predecessor(
    tmp_path: Path,
) -> None:
    """Dropping the ledger is a regression even when all decision rows remain."""
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _source_bundle, complete_bundle, _ = _complete_current_review_transactionally(
        paths,
    )
    complete_manifest_path = complete_bundle / "bundle_manifest.json"
    complete_manifest_hash = preparation.sha256_file(complete_manifest_path)
    regression = complete_bundle.parent.parent / "rv_receiptless_fixture" / "human_delta"
    shutil.copytree(complete_bundle, regression)
    manifest = preparation.read_json(regression / "bundle_manifest.json")
    receipt_item = manifest["artifacts"]["review_receipts"]
    receipt_path = regression / receipt_item["path"]
    receipt_path.write_bytes(b"")
    receipt_item["sha256"] = preparation.sha256_file(receipt_path)
    checkpoint_item = manifest["artifacts"]["decision_checkpoint"]
    checkpoint_path = regression / checkpoint_item["path"]
    checkpoint = preparation.read_json(checkpoint_path)
    checkpoint["previous_checkpoint_or_receipt"] = str(complete_bundle)
    checkpoint["previous_bundle_manifest_hash"] = complete_manifest_hash
    checkpoint["review_receipts_hash"] = preparation.sha256_file(receipt_path)
    preparation.write_json(checkpoint_path, checkpoint)
    checkpoint_item["sha256"] = preparation.sha256_file(checkpoint_path)
    preparation.write_json(regression / "bundle_manifest.json", manifest)
    preparation.write_json(paths.pointer, {
        "schema_version": preparation.SCHEMA_POINTER,
        "bundle_path": str(regression),
        "bundle_manifest_path": str(regression / "bundle_manifest.json"),
        "bundle_manifest_hash": preparation.sha256_file(
            regression / "bundle_manifest.json"
        ),
        "canon_generation_id": manifest.get("canon_generation_id"),
        "relation_generation_id": manifest.get("relation_generation_id"),
        "review_state_id": manifest.get("review_state_id"),
        "readiness_id": manifest.get("readiness_id"),
        "terminal_state": manifest.get("terminal_state"),
        "next_action": manifest.get("next_action"),
    })

    predecessor = preparation._resolve_monotonic_review_predecessor(paths)

    assert predecessor["recovered_from_regression"] is True
    assert predecessor["bundle"] == complete_bundle.resolve()
    assert len(predecessor["decision_by_id"]) == len(
        preparation.read_jsonl(
            complete_bundle / "effective_human_review_decisions.jsonl"
        )
    )
    assert predecessor["receipt_lineage"]["receipt_count"] == 1


def test_authorization_noop_requires_exact_receipt_lineage(
    tmp_path: Path,
) -> None:
    """A receiptless READY pointer cannot mask its certified predecessor."""
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _source_bundle, complete_bundle, _ = _complete_current_review_transactionally(
        paths,
    )
    ready = preparation.execute(paths, source_root=source_root)
    ready_bundle = Path(ready["bundle_path"])
    ready_pointer = preparation.read_json(paths.pointer)

    regression = ready_bundle.with_name(ready_bundle.name + "--receiptless-fixture")
    shutil.copytree(ready_bundle, regression)
    manifest_path = regression / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)
    manifest["review_lineage_required"] = False
    manifest["artifacts"].pop("review_receipts")
    manifest["artifacts"].pop("review_receipt_lineage")
    preparation.write_json(manifest_path, manifest)
    regressive_pointer = dict(ready_pointer)
    regressive_pointer.update({
        "bundle_path": str(regression),
        "bundle_manifest_path": str(manifest_path),
        "bundle_manifest_hash": preparation.sha256_file(manifest_path),
    })
    preparation.write_json(paths.pointer, regressive_pointer)
    assert preparation.read_current_bundle_status(paths.local_root)["valid"] is True

    recovered = preparation.execute(paths, source_root=source_root)

    assert recovered["idempotent_noop"] is False
    assert Path(recovered["bundle_path"]) == ready_bundle
    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["valid"] is True
    assert status["manifest"]["review_lineage_required"] is True
    assert {
        "review_receipts", "review_receipt_lineage",
    }.issubset(status["manifest"]["artifacts"])


def test_regressive_pointer_blocks_when_certified_receipt_hash_is_altered(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    source_bundle, complete_bundle, _ = _complete_current_review_transactionally(paths)
    _point_to_regressive_review_bundle(paths, source_bundle, complete_bundle)
    manifest_path = complete_bundle / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)
    receipt_item = manifest["artifacts"]["review_receipts"]
    receipt_path = complete_bundle / receipt_item["path"]
    receipts = preparation.read_jsonl(receipt_path)
    receipts[0]["source_bundle_manifest_hash"] = "0" * 64
    preparation.write_jsonl(receipt_path, receipts)
    receipt_item["sha256"] = preparation.sha256_file(receipt_path)
    preparation.write_json(manifest_path, manifest)

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation._resolve_monotonic_review_predecessor(paths)

    assert blocked.value.reason_codes == ["review_receipt_lineage_invalid"]


@pytest.mark.parametrize(
    ("corruption", "reason_code"),
    [
        ("receipt_artifact_hash", "bundle_artifact_invalid:review_receipts"),
        (
            "declared_previous_manifest_hash",
            "review_predecessor_manifest_hash_mismatch",
        ),
        (
            "checkpoint_decisions_hash",
            "review_predecessor_decision_hash_mismatch",
        ),
    ],
)
def test_public_execute_never_falls_back_from_corrupt_declared_review_lineage(
    tmp_path: Path,
    corruption: str,
    reason_code: str,
) -> None:
    """A corrupt declared predecessor must not degrade to S0183 or no lineage."""
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    source_bundle, complete_bundle, _ = _complete_current_review_transactionally(
        paths,
    )
    regression = _point_to_regressive_review_bundle(
        paths, source_bundle, complete_bundle,
    )

    if corruption == "receipt_artifact_hash":
        complete_manifest = preparation.read_json(
            complete_bundle / "bundle_manifest.json"
        )
        receipt_path = complete_bundle / complete_manifest["artifacts"][
            "review_receipts"
        ]["path"]
        receipt_path.write_bytes(receipt_path.read_bytes() + b"\n")
    elif corruption == "declared_previous_manifest_hash":
        regression_manifest_path = regression / "bundle_manifest.json"
        regression_manifest = preparation.read_json(regression_manifest_path)
        checkpoint_item = regression_manifest["artifacts"]["decision_checkpoint"]
        checkpoint_path = regression / checkpoint_item["path"]
        checkpoint = preparation.read_json(checkpoint_path)
        checkpoint["previous_bundle_manifest_hash"] = "0" * 64
        preparation.write_json(checkpoint_path, checkpoint)
        checkpoint_item["sha256"] = preparation.sha256_file(checkpoint_path)
        preparation.write_json(regression_manifest_path, regression_manifest)
        pointer = preparation.read_json(paths.pointer)
        pointer["bundle_manifest_hash"] = preparation.sha256_file(
            regression_manifest_path
        )
        preparation.write_json(paths.pointer, pointer)
    else:
        complete_manifest_path = complete_bundle / "bundle_manifest.json"
        complete_manifest = preparation.read_json(complete_manifest_path)
        checkpoint_item = complete_manifest["artifacts"]["decision_checkpoint"]
        checkpoint_path = complete_bundle / checkpoint_item["path"]
        checkpoint = preparation.read_json(checkpoint_path)
        checkpoint["decisions_file_hash"] = "0" * 64
        preparation.write_json(checkpoint_path, checkpoint)
        checkpoint_item["sha256"] = preparation.sha256_file(checkpoint_path)
        preparation.write_json(complete_manifest_path, complete_manifest)

    pointer_before = paths.pointer.read_bytes()
    current_before = {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    generations_before = {
        path.relative_to(paths.generations).as_posix()
        for path in paths.generations.rglob("*")
    }

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation.execute(paths, source_root=source_root)

    assert reason_code in blocked.value.reason_codes
    assert paths.pointer.read_bytes() == pointer_before
    assert current_before == {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    assert generations_before == {
        path.relative_to(paths.generations).as_posix()
        for path in paths.generations.rglob("*")
    }


def test_review_state_identity_ignores_relocated_lineage_provenance_paths(
    tmp_path: Path,
) -> None:
    """Physical recovery locations are provenance, not semantic identity input."""
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _complete_current_review_transactionally(paths)
    work, staged_current, _ = preparation.recompose_current_decision_authority(
        paths,
    )
    staged_paths = preparation.Paths(
        local_root=paths.local_root,
        current_dir=staged_current,
        audit_root=paths.audit_root,
        admission_current=paths.admission_current,
        generations=paths.generations,
        pointer=paths.pointer,
    )
    try:
        first = preparation.analyze(staged_paths)
        descriptor_path = staged_current / preparation.REVIEW_LINEAGE_FILE
        descriptor = preparation.read_json(descriptor_path)
        descriptor["source_bundle_path"] = (
            "/relocated/equivalent/history/human_delta"
        )
        descriptor["source_review_receipts_path"] = (
            "/relocated/equivalent/history/current_review_batch_receipts.jsonl"
        )
        preparation.write_json(descriptor_path, descriptor)

        relocated = preparation.analyze(staged_paths)

        assert relocated["ids"]["relation_generation_id"] == first["ids"][
            "relation_generation_id"
        ]
        assert relocated["ids"]["review_state_id"] == first["ids"][
            "review_state_id"
        ]
    finally:
        if work.exists():
            shutil.rmtree(work)


def test_predecessor_resolution_uses_declared_genealogy_not_directory_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    source_bundle, complete_bundle, _ = _complete_current_review_transactionally(paths)
    regression = _point_to_regressive_review_bundle(
        paths, source_bundle, complete_bundle,
    )
    relation_dir = paths.generations / preparation.read_json(
        complete_bundle / "bundle_manifest.json"
    )["relation_generation_id"]
    decoys = []
    for review_id in ("rv_000000000000000000000000", "rv_zzzzzzzzzzzzzzzzzzzzzzzz"):
        decoy = relation_dir / review_id / "human_delta"
        decoy.mkdir(parents=True)
        (decoy / "bundle_manifest.json").write_text(
            "not a valid bundle\n", encoding="utf-8",
        )
        (decoy / "bundle_manifest.json").touch()
        decoys.append(decoy.resolve())
    loaded: list[Path] = []
    original_load = preparation._load_review_bundle

    def tracked_load(
        fixture_paths: preparation.Paths,
        bundle: Path,
        *,
        expected_manifest_hash: str | None = None,
    ) -> dict:
        loaded.append(Path(bundle).resolve())
        return original_load(
            fixture_paths,
            bundle,
            expected_manifest_hash=expected_manifest_hash,
        )

    monkeypatch.setattr(preparation, "_load_review_bundle", tracked_load)

    predecessor = preparation._resolve_monotonic_review_predecessor(paths)

    assert predecessor["bundle"] == complete_bundle.resolve()
    assert regression.resolve() in loaded
    assert complete_bundle.resolve() in loaded
    assert not set(decoys).intersection(loaded)


def test_last_transactional_batch_recomposition_preserves_receipt_and_readiness(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    first = preparation.execute(paths, source_root=source_root)
    _source_bundle, complete_bundle, review_result = (
        _complete_current_review_transactionally(paths)
    )
    complete_manifest = preparation.read_json(
        complete_bundle / "bundle_manifest.json"
    )
    receipt_path = complete_bundle / complete_manifest["artifacts"][
        "review_receipts"
    ]["path"]
    receipt_before = receipt_path.read_bytes()
    decisions_before = (
        complete_bundle / complete_manifest["artifacts"]["effective_decisions"]["path"]
    ).read_bytes()

    ready = preparation.execute(paths, source_root=source_root)

    assert ready["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert ready["ids"]["relation_generation_id"] == first["ids"][
        "relation_generation_id"
    ]
    assert ready["ids"]["review_state_id"] != first["ids"]["review_state_id"]
    assert ready["decision_preservation"]["pending_delta"] == 0
    authority = current_authority.resolve_current_relational_authority(
        paths.local_root
    )
    assert authority["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert preparation.read_jsonl(authority["artifacts"]["effective_decisions"])
    assert authority["artifacts"]["review_receipts"].read_bytes() == receipt_before
    assert receipt_path.read_bytes() == receipt_before
    assert (
        complete_bundle / complete_manifest["artifacts"]["effective_decisions"]["path"]
    ).read_bytes() == decisions_before
    assert len(preparation.read_jsonl(authority["artifacts"]["review_receipts"])) == 1
    assert review_result["receipt_created"] is True


@pytest.mark.parametrize(
    "corruption",
    ["empty_individual_hashes", "wrong_total", "wrong_classification", "wrong_identity"],
)
def test_certified_predecessor_checkpoint_is_complete_and_conserved(
    tmp_path: Path, corruption: str,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _source, complete_bundle, _review = _complete_current_review_transactionally(
        paths
    )
    manifest_path = complete_bundle / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)
    checkpoint_path = complete_bundle / manifest["artifacts"][
        "decision_checkpoint"
    ]["path"]
    checkpoint = preparation.read_json(checkpoint_path)
    if corruption == "empty_individual_hashes":
        checkpoint["individual_decision_hashes"] = []
    elif corruption == "wrong_total":
        checkpoint["total_decisions"] = 0
    elif corruption == "wrong_classification":
        checkpoint["current_direct"] = 0
    else:
        checkpoint["review_state_id"] = "rv_not_the_manifest_state"
    preparation.write_json(checkpoint_path, checkpoint)
    manifest["artifacts"]["decision_checkpoint"]["sha256"] = (
        preparation.sha256_file(checkpoint_path)
    )
    preparation.write_json(manifest_path, manifest)

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation._load_review_bundle(
            paths,
            complete_bundle,
            expected_manifest_hash=preparation.sha256_file(manifest_path),
        )

    assert blocked.value.reason_codes == [
        "review_predecessor_decision_hash_mismatch"
    ]


def test_unknown_review_receipt_schema_is_rejected_fail_closed(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _source, complete_bundle, _review = _complete_current_review_transactionally(
        paths
    )
    manifest_path = complete_bundle / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)
    receipt_path = complete_bundle / manifest["artifacts"]["review_receipts"][
        "path"
    ]
    receipts = preparation.read_jsonl(receipt_path)
    receipts[0]["schema_version"] = "current-single-batch-review-receipt/v999"
    preparation.write_jsonl(receipt_path, receipts)
    manifest["artifacts"]["review_receipts"]["sha256"] = (
        preparation.sha256_file(receipt_path)
    )
    preparation.write_json(manifest_path, manifest)
    record = preparation._load_review_bundle(
        paths,
        complete_bundle,
        expected_manifest_hash=preparation.sha256_file(manifest_path),
    )

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation._validate_review_receipt_lineage(paths, record)

    assert blocked.value.reason_codes == ["review_receipt_lineage_invalid"]


def _review_current_batch(
    paths: preparation.Paths, *, action: str = "approved_for_admission",
) -> dict:
    surface = human_review.resolve_current_human_delta_surface(paths.local_root)
    assert surface["allowed"] is True
    batch = human_review.build_current_human_delta_batches(surface)[0]
    reason = (
        "DIRECT_CODE_DEPENDENCY_CONFIRMED"
        if action == "approved_for_admission" else "INSUFFICIENT_CONTEXT"
    )
    proposals = [{
        "candidate_id": candidate_id,
        "candidate_hash": candidate_hash,
        "action": action,
        "reason_code": reason,
        "note": "",
        "human_confirmation": human_review.current_candidate_confirmation(
            candidate_id, action,
        ),
    } for candidate_id, candidate_hash in zip(
        batch["candidate_ids"], batch["candidate_hashes"], strict=True,
    )]
    return human_review.persist_current_human_delta_batch(
        paths.local_root,
        batch=batch,
        proposals=proposals,
        actor="fixture-reviewer",
        confirmation=human_review.current_batch_confirmation(batch["batch_id"]),
    )


def test_review_complete_recomposition_preserves_receipt_and_is_idempotent(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    initial = preparation.execute(paths, source_root=source_root)
    assert initial["terminal_state"] == preparation.TERMINAL_HUMAN
    raw_decisions = paths.current_dir / "human_review_decisions.jsonl"
    raw_before = raw_decisions.read_bytes()
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    reviewed = _review_current_batch(paths)
    assert reviewed["terminal_state"] == preparation.TERMINAL_REVIEW_COMPLETE
    completed_bundle = Path(reviewed["bundle_path"])
    completed_before = {
        path.relative_to(completed_bundle).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in completed_bundle.rglob("*") if path.is_file()
    }
    source_receipts = completed_bundle / preparation.REVIEW_RECEIPTS_FILE
    pointer_before_preview = paths.pointer.read_bytes()

    preview = preparation.dry_run(paths)

    assert preview["expected_terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert preview["review_coverage"]["effective_pending"] == 0
    assert preview["review_coverage"]["receipt_count"] == 1
    assert preview["authorization_created"] is False
    assert paths.pointer.read_bytes() == pointer_before_preview
    assert raw_decisions.read_bytes() == raw_before

    ready = preparation.execute(paths, source_root=source_root)

    assert ready["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert ready["decision_preservation"]["preserved_equivalent"] == 1
    assert ready["decision_preservation"]["pending_delta"] == 0
    ready_bundle = Path(ready["bundle_path"])
    assert (ready_bundle / preparation.REVIEW_RECEIPTS_FILE).read_bytes() == (
        source_receipts.read_bytes()
    )
    lineage = preparation.read_json(ready_bundle / preparation.REVIEW_LINEAGE_FILE)
    assert lineage["integrity_verified"] is True
    assert lineage["receipt_count"] == 1
    assert lineage["source_review_state_id"] == reviewed["result_review_state_id"]
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    assert raw_decisions.read_bytes() == raw_before
    assert completed_before == {
        path.relative_to(completed_bundle).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in completed_bundle.rglob("*") if path.is_file()
    }

    pointer_after_ready = paths.pointer.read_bytes()
    receipts_after_ready = (
        ready_bundle / preparation.REVIEW_RECEIPTS_FILE
    ).read_bytes()
    repeated = preparation.execute(paths, source_root=source_root)
    assert repeated["idempotent_noop"] is True
    assert paths.pointer.read_bytes() == pointer_after_ready
    assert (ready_bundle / preparation.REVIEW_RECEIPTS_FILE).read_bytes() == receipts_after_ready


@pytest.mark.parametrize(
    "failpoint",
    [
        "before_candidate_publication",
        "bundle_validation",
        "before_publication",
        "after_bundle_publication",
        "before_pointer_update",
        "pointer_update",
    ],
)
def test_decision_recomposition_publication_failures_restore_all_authorities(
    tmp_path: Path, failpoint: str,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    reviewed = _review_current_batch(paths)
    completed_bundle = Path(reviewed["bundle_path"])
    pointer_before = paths.pointer.read_bytes()
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]
    current_before = {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    historical_before = {
        path.relative_to(completed_bundle).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in completed_bundle.rglob("*") if path.is_file()
    }
    manifests_before = {
        path.parent.resolve()
        for path in paths.generations.rglob("bundle_manifest.json")
    }

    def fail(name: str) -> None:
        if name == failpoint:
            raise RuntimeError(f"injected {name}")

    with pytest.raises(preparation.PreparationBlocked):
        preparation.execute(
            paths, source_root=source_root, failure_hook=fail,
        )

    assert paths.pointer.read_bytes() == pointer_before
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    current_after = {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    assert current_before == current_after
    assert historical_before == {
        path.relative_to(completed_bundle).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in completed_bundle.rglob("*") if path.is_file()
    }
    manifests_after = {
        path.parent.resolve()
        for path in paths.generations.rglob("bundle_manifest.json")
    }
    added = manifests_after - manifests_before
    if failpoint in {
        "after_bundle_publication", "before_pointer_update", "pointer_update",
    }:
        assert len(added) == 1
        orphan = next(iter(added))
        preparation._validate_staged_bundle(
            orphan, preparation.read_json(orphan / "bundle_manifest.json"),
        )
    else:
        assert added == set()
    assert not list(paths.current_dir.parent.glob(".staging-*"))


def test_decision_recomposition_retry_reuses_only_semantically_equal_orphan(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    pointer_before = paths.pointer.read_bytes()

    def fail(name: str) -> None:
        if name == "pointer_update":
            raise RuntimeError("injected pointer failure")

    with pytest.raises(preparation.PreparationBlocked):
        preparation.execute(paths, source_root=source_root, failure_hook=fail)
    pointer_manifest_dirs = [
        path.parent for path in paths.generations.rglob("bundle_manifest.json")
        if path.parent.name != "human_delta"
    ]
    assert len(pointer_manifest_dirs) == 1
    orphan = pointer_manifest_dirs[0]
    orphan_before = {
        path.relative_to(orphan).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in orphan.rglob("*") if path.is_file()
    }
    assert paths.pointer.read_bytes() == pointer_before

    result = preparation.execute(paths, source_root=source_root)

    assert Path(result["bundle_path"]) == orphan
    assert orphan_before == {
        path.relative_to(orphan).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in orphan.rglob("*") if path.is_file()
    }

    representation = tmp_path / "equivalent-readiness-representation"
    shutil.copytree(orphan, representation)
    representation_manifest = preparation.read_json(
        representation / "bundle_manifest.json"
    )
    representation_manifest["source_bindings"]["review_receipts"][
        "sha256"
    ] = "f" * 64
    receipt_item = representation_manifest["artifacts"]["review_receipts"]
    receipt_path = representation / receipt_item["path"]
    receipt_rows = preparation.read_jsonl(receipt_path)
    assert all(
        row["schema_version"] == "current-single-batch-review-receipt/v2"
        for row in receipt_rows
    )
    for row in receipt_rows:
        row["source_bundle_manifest_hash"] = "f" * 64
    preparation.write_jsonl(receipt_path, receipt_rows)
    descriptor_item = representation_manifest["artifacts"][
        "review_receipt_lineage"
    ]
    descriptor_path = representation / descriptor_item["path"]
    descriptor = preparation.read_json(descriptor_path)
    descriptor["carried_review_receipts_hash"] = preparation.sha256_file(
        receipt_path
    )
    preparation.write_json(descriptor_path, descriptor)

    assert preparation._bundle_retry_semantics(
        orphan, preparation.read_json(orphan / "bundle_manifest.json")
    ) != preparation._bundle_retry_semantics(
        representation, representation_manifest,
    )


def test_equivalent_peer_pointer_commit_blocks_without_claiming_rollback_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    pointer_before = paths.pointer.read_bytes()
    real_cas = preparation.current_authority.compare_and_swap_current_pointer

    def peer_wins_with_identical_bytes(
        pointer_path: Path, *, expected: bytes | None, replacement: bytes | None,
    ) -> bool:
        assert replacement is not None
        assert real_cas(
            pointer_path, expected=expected, replacement=replacement,
        ) is True
        return real_cas(
            pointer_path, expected=expected, replacement=replacement,
        )

    monkeypatch.setattr(
        preparation.current_authority,
        "compare_and_swap_current_pointer",
        peer_wins_with_identical_bytes,
    )

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation.execute(paths, source_root=source_root)

    assert "current_pointer_changed" in blocked.value.reason_codes
    assert paths.pointer.read_bytes() != pointer_before


@pytest.mark.parametrize("peer_action", ["replace_identical", "remove"])
def test_pipeline_rollback_never_overwrites_noncooperative_peer_current(
    tmp_path: Path, peer_action: str,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    observed: dict[str, object] = {}

    def peer_intervenes(name: str) -> None:
        if name != "before_publication" or observed:
            return
        peer = paths.current_dir.with_name(f".peer-{peer_action}")
        if peer_action == "replace_identical":
            displaced = paths.current_dir.with_name(".displaced-owned-current")
            shutil.copytree(paths.current_dir, peer)
            paths.current_dir.replace(displaced)
            peer.replace(paths.current_dir)
            shutil.rmtree(displaced)
            observed["identity"] = preparation._directory_identity(paths.current_dir)
            observed["fingerprint"] = preparation._directory_fingerprint(
                paths.current_dir
            )
        else:
            paths.current_dir.replace(peer)
            observed["removed_path"] = peer
        raise RuntimeError("noncooperative peer changed current")

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation.execute(
            paths, source_root=source_root, failure_hook=peer_intervenes,
        )

    assert "current_pipeline_descendant_advanced" in blocked.value.reason_codes
    assert list(paths.current_dir.parent.glob(".previous-current-*"))
    if peer_action == "replace_identical":
        assert preparation._directory_identity(paths.current_dir) == observed["identity"]
        assert preparation._directory_fingerprint(paths.current_dir) == observed["fingerprint"]
    else:
        assert not paths.current_dir.exists()
        assert Path(observed["removed_path"]).is_dir()


def test_postpublication_resolution_must_match_published_candidate(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "expected"
    destination.mkdir()
    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation._assert_published_candidate_is_current(
            {
                "valid": True,
                "bundle_path": str(tmp_path / "successor"),
                "terminal_state": preparation.TERMINAL_AUTHORIZATION,
                "ids": {
                    "relation_generation_id": "rg_successor",
                    "review_state_id": "rv_successor",
                    "readiness_id": "rd_successor",
                },
            },
            destination=destination,
            ids={
                "relation_generation_id": "rg_expected",
                "review_state_id": "rv_expected",
                "readiness_id": "rd_expected",
            },
            terminal_state=preparation.TERMINAL_AUTHORIZATION,
            failure_reason="bundle_publication_failed",
        )

    assert blocked.value.reason_codes == ["current_pointer_descendant_advanced"]


def test_decision_recomposition_rejects_self_hashed_semantic_orphan_collision(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    pointer_before = paths.pointer.read_bytes()

    def fail(name: str) -> None:
        if name == "pointer_update":
            raise RuntimeError("injected pointer failure")

    with pytest.raises(preparation.PreparationBlocked):
        preparation.execute(paths, source_root=source_root, failure_hook=fail)
    orphan = next(
        path.parent for path in paths.generations.rglob("bundle_manifest.json")
        if path.parent.name != "human_delta"
    )
    manifest_path = orphan / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)
    preservation_item = manifest["artifacts"]["cross_generation_reconciliation"]
    preservation_path = orphan / preservation_item["path"]
    preservation = preparation.read_json(preservation_path)
    preservation["decision_reuse_rule"] = "forged_semantic_collision"
    preparation.write_json(preservation_path, preservation)
    preservation_item["sha256"] = preparation.sha256_file(preservation_path)
    preparation.write_json(manifest_path, manifest)

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation.execute(paths, source_root=source_root)

    assert "bundle_publication_failed" in blocked.value.reason_codes
    assert "semantic destination collision" in blocked.value.detail
    assert paths.pointer.read_bytes() == pointer_before


@pytest.mark.parametrize(
    "artifact_role",
    ["pending_queue", "review_receipt_lineage"],
)
def test_unknown_derived_bundle_schemas_fail_closed(
    tmp_path: Path, artifact_role: str,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    initial = preparation.execute(paths, source_root=source_root)
    if artifact_role == "pending_queue":
        bundle = Path(initial["bundle_path"])
    else:
        _review_current_batch(paths)
        bundle = Path(preparation.execute(paths, source_root=source_root)["bundle_path"])
    manifest_path = bundle / "bundle_manifest.json"
    manifest = preparation.read_json(manifest_path)
    item = manifest["artifacts"][artifact_role]
    artifact_path = bundle / item["path"]
    payload = preparation.read_json(artifact_path)
    payload["schema_version"] = "unknown-derived-schema/v999"
    preparation.write_json(artifact_path, payload)
    item["sha256"] = preparation.sha256_file(artifact_path)
    item["schema_version"] = payload["schema_version"]
    preparation.write_json(manifest_path, manifest)

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation._validate_staged_bundle(bundle, manifest)

    assert "bundle_publication_failed" in blocked.value.reason_codes
    expected = (
        "bundle_review_delta_schema_invalid"
        if artifact_role == "pending_queue"
        else "review_receipt_lineage_invalid"
    )
    assert expected in blocked.value.reason_codes
    pointer = preparation.read_json(paths.pointer)
    pointer["bundle_manifest_hash"] = preparation.sha256_file(manifest_path)
    preparation.write_json(paths.pointer, pointer)
    with pytest.raises(
        preparation.current_authority.CurrentRelationalAuthorityError
    ) as authority_blocked:
        preparation.current_authority.resolve_current_relational_authority(
            paths.local_root
        )
    assert (
        "current_bundle_artifact_schema_invalid"
        in authority_blocked.value.reason_codes
        or "review_receipt_lineage_invalid"
        in authority_blocked.value.reason_codes
    )


@pytest.mark.parametrize(
    ("surface", "reason_code"),
    [
        (
            "candidate_manifest",
            "current_relational_source_changed",
        ),
        (
            "reconciliation_manifest",
            "current_relational_source_changed",
        ),
        (
            "review_receipts",
            "review_receipt_lineage_changed",
        ),
        (
            "current_pointer",
            "current_pointer_changed",
        ),
    ],
)
def test_decision_recomposition_revalidates_every_authority_before_publication(
    tmp_path: Path,
    surface: str,
    reason_code: str,
) -> None:
    """A drift observed at the publication boundary must prevent the rename."""
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    pointer_before = paths.pointer.read_bytes()
    current_before = {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    generations_before = {
        path.relative_to(paths.generations).as_posix()
        for path in paths.generations.rglob("*")
    }
    observed_phases: list[str] = []
    drift_injected = False

    def drift(name: str) -> None:
        nonlocal drift_injected
        observed_phases.append(name)
        if name != "before_publication" or drift_injected:
            return
        drift_injected = True
        if surface == "current_pointer":
            pointer = preparation.read_json(paths.pointer)
            pointer["publication_drift_fixture"] = True
            preparation.write_json(paths.pointer, pointer)
            return
        filename = {
            "candidate_manifest": "current_candidate_manifest.json",
            "reconciliation_manifest": "reconciliation_manifest.json",
            "review_receipts": preparation.REVIEW_RECEIPTS_FILE,
        }[surface]
        target = paths.current_dir / filename
        target.write_bytes(target.read_bytes() + b"\n")

    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation.execute(
            paths,
            source_root=source_root,
            failure_hook=drift,
        )

    assert reason_code in blocked.value.reason_codes
    assert "after_bundle_publication" not in observed_phases
    if surface == "current_pointer":
        # The failing writer must not clobber a pointer value it did not write.
        assert preparation.read_json(paths.pointer)[
            "publication_drift_fixture"
        ] is True
    else:
        assert paths.pointer.read_bytes() == pointer_before
    current_after = {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    if surface == "current_pointer":
        assert current_before == current_after
    else:
        assert "current_pipeline_descendant_advanced" in blocked.value.reason_codes
        assert current_before != current_after
        assert list(paths.current_dir.parent.glob(".previous-current-*"))
    assert generations_before == {
        path.relative_to(paths.generations).as_posix()
        for path in paths.generations.rglob("*")
    }
    assert not list(paths.current_dir.parent.glob(".staging-*"))


def test_canon_evolution_with_only_nonreviewable_addition_preserves_ready_review(
    tmp_path: Path,
) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    first_delta = preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    first_ready = preparation.execute(paths, source_root=source_root)
    assert first_ready["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    first_bundle = Path(first_ready["bundle_path"])
    receipt_bytes = (first_bundle / preparation.REVIEW_RECEIPTS_FILE).read_bytes()

    scripts = source_root / "src/python_scripts"
    (scripts / "unresolved.py").write_text("import absent_target\n", encoding="utf-8")
    canon_rows.append(_canon_record(
        "source-unresolved", "src/python_scripts/unresolved.py",
        "import absent_target\n",
    ))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    evolved_canon = preparation.canon_snapshot(paths.local_root)["hash"]

    evolved = preparation.execute(paths, source_root=source_root)

    assert evolved["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert evolved["ids"]["canon_generation_id"] != first_ready["ids"]["canon_generation_id"]
    assert evolved["ids"]["relation_generation_id"] != first_ready["ids"]["relation_generation_id"]
    assert evolved["decision_preservation"]["preserved_equivalent"] == 1
    assert evolved["decision_preservation"]["pending_delta"] == 0
    evolved_bundle = Path(evolved["bundle_path"])
    assert (evolved_bundle / preparation.REVIEW_RECEIPTS_FILE).read_bytes() == receipt_bytes
    assert preparation.read_json(
        evolved_bundle / preparation.REVIEW_LINEAGE_FILE
    )["integrity_verified"] is True
    assert preparation.canon_snapshot(paths.local_root)["hash"] == evolved_canon
    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["valid"] is True
    assert status["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert status["planning"]["effective_pending"] == 0


def test_canon_evolution_queues_only_genuine_delta_with_receipt_lineage(
    tmp_path: Path,
) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    scripts = source_root / "src/python_scripts"
    for name in ("d", "f", "g"):
        (scripts / f"{name}.py").write_text("import b\n", encoding="utf-8")
        canon_rows.append(_canon_record(
            f"source-{name}", f"src/python_scripts/{name}.py", "import b\n",
        ))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    first_ready = preparation.execute(paths, source_root=source_root)
    assert first_ready["terminal_state"] == preparation.TERMINAL_AUTHORIZATION

    (scripts / "a.py").write_text("from b import VALUE\n", encoding="utf-8")
    canon_rows[0]["text"] = "from b import VALUE\n"
    (scripts / "d.py").write_text("import b\nimport b\n", encoding="utf-8")
    canon_rows[2]["text"] = "import b\nimport b\n"
    (scripts / "e.py").write_text("import b\n", encoding="utf-8")
    canon_rows.append(_canon_record(
        "source-e", "src/python_scripts/e.py", "import b\n",
    ))
    (scripts / "g.py").unlink()
    canon_rows[4]["text"] = "historical source removed\n"
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    delta = preparation.execute(paths, source_root=source_root)

    assert delta["terminal_state"] == preparation.TERMINAL_HUMAN
    assert delta["decision_preservation"]["preserved_equivalent"] >= 1
    assert delta["decision_preservation"]["disappeared_provenance"] == 1
    bundle = Path(delta["bundle_path"])
    human_delta = preparation.read_json(bundle / "human_delta.json")
    pending = set(human_delta["pending_candidate_ids"])
    genuine = set(human_delta["new"] + human_delta["modified"] + human_delta["ambiguous"])
    assert pending == genuine
    assert human_delta["new"]
    assert human_delta["modified"]
    assert human_delta["ambiguous"]
    assert human_delta["disappeared_provenance"] == 1
    assert (bundle / preparation.REVIEW_RECEIPTS_FILE).is_file()
    assert preparation.read_json(
        bundle / preparation.REVIEW_LINEAGE_FILE
    )["integrity_verified"] is True


def test_multigeneration_lineage_validates_two_review_segments(
    tmp_path: Path,
) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    scripts = source_root / "src/python_scripts"
    preparation.execute(paths, source_root=source_root)
    _review_current_batch(paths)
    first_ready = preparation.execute(paths, source_root=source_root)
    first_receipts = preparation.read_jsonl(
        Path(first_ready["bundle_path"]) / preparation.REVIEW_RECEIPTS_FILE
    )

    (scripts / "a.py").write_text("from b import VALUE\n", encoding="utf-8")
    canon_rows[0]["text"] = "from b import VALUE\n"
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    delta = preparation.execute(paths, source_root=source_root)
    delta_payload = preparation.read_json(Path(delta["bundle_path"]) / "human_delta.json")
    modified_ids = set(delta_payload["modified"])
    assert modified_ids

    result: dict = delta
    while result["terminal_state"] == preparation.TERMINAL_HUMAN:
        result = _review_current_batch(paths)
    assert result["terminal_state"] == preparation.TERMINAL_REVIEW_COMPLETE
    completed_bundle = Path(result["bundle_path"])
    all_receipts = preparation.read_jsonl(
        completed_bundle / preparation.REVIEW_RECEIPTS_FILE
    )
    first_relation = str(first_receipts[0]["source_relation_generation_id"])
    later_receipts = [
        receipt for receipt in all_receipts
        if receipt["source_relation_generation_id"] != first_relation
    ]
    assert later_receipts
    ready = preparation.execute(paths, source_root=source_root)
    assert ready["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    ready_bundle = Path(ready["bundle_path"])
    descriptor = preparation.read_json(
        ready_bundle / preparation.REVIEW_LINEAGE_FILE
    )
    assert descriptor["schema_version"] == "current-review-receipt-lineage/v2"
    assert len(descriptor["segments"]) == 2
    record = preparation._load_review_bundle(
        paths,
        ready_bundle,
        expected_manifest_hash=preparation.sha256_file(
            ready_bundle / "bundle_manifest.json"
        ),
    )
    validated = preparation._validate_review_receipt_lineage(paths, record)
    assert validated["receipt_count"] == len(all_receipts)
    assert len(validated["segments"]) == 2
    assert preparation.execute(
        paths, source_root=source_root,
    )["idempotent_noop"] is True


def test_lineage_candidate_consumption_is_scoped_per_relation_generation() -> None:
    repeated = "rc_current_" + "a" * 24
    receipts = [
        {
            "source_relation_generation_id": "rg_first",
            "candidate_ids": [repeated],
        },
        {
            "source_relation_generation_id": "rg_second",
            "candidate_ids": [repeated],
        },
    ]

    assert preparation._lineage_consumed_candidate_ids(receipts) == [repeated]

    receipts[1]["source_relation_generation_id"] = "rg_first"
    with pytest.raises(preparation.PreparationBlocked) as blocked:
        preparation._lineage_consumed_candidate_ids(receipts)
    assert blocked.value.reason_codes == ["review_receipt_lineage_invalid"]


def test_stale_canon_rebuilds_in_staging_publishes_delta_and_resumes(
    tmp_path: Path,
) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)

    first = preparation.execute(paths, source_root=source_root)
    assert first["terminal_state"] == preparation.TERMINAL_HUMAN
    assert first["ids"]["readiness_id"] is None
    assert first["decision_preservation"]["pending_delta"] == 1
    first_bundle = Path(first["bundle_path"])
    first_manifest = preparation.read_json(first_bundle / "bundle_manifest.json")
    for name in ("gate_g", "apply_plan", "rollback_snapshot", "authorization_request"):
        assert first_manifest["artifacts"][name]["status"] == "not_applicable_pending_human_review"
        assert "path" not in first_manifest["artifacts"][name]
    resolved_gate = human_review.resolve_current_gate_report(
        paths.local_root,
        paths.admission_current / "admission_gate_dry_run.json",
    )
    assert resolved_gate == first_bundle / "admission_gate_dry_run.json"
    review_preflight = human_review.validate_human_review_batch_generation(
        paths.current_dir, paths.local_root, resolved_gate
    )
    assert review_preflight["allowed"] is True
    assert sum(
        row["disposition"] == "awaiting_human_review"
        for row in review_preflight["partition"]
    ) == 1
    state = admission_state.build_state(paths.local_root, checked_at="fixture")
    assert state["verdict"] == preparation.TERMINAL_HUMAN
    assert state["blocking_reasons"] == []
    assert state["admission_gate"]["awaiting_human_review"] == 1
    assert state["next_action"] == "REVIEW_CURRENT_RELATIONAL_DELTA"

    repeated_delta = preparation.execute(paths, source_root=source_root)
    assert repeated_delta["idempotent_noop"] is True
    assert repeated_delta["ids"] == first["ids"]

    _review_current_batch(paths)
    ready_one = preparation.execute(paths, source_root=source_root)
    assert ready_one["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert ready_one["ids"]["relation_generation_id"] == first["ids"]["relation_generation_id"]
    assert ready_one["ids"]["review_state_id"] != first["ids"]["review_state_id"]
    assert ready_one["ids"]["readiness_id"]

    scripts = source_root / "src" / "python_scripts"
    (scripts / "c.py").write_text("import b\n", encoding="utf-8")
    canon_rows.append(
        _canon_record("source-c", "src/python_scripts/c.py", "import b\n")
    )
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    canon_hash_after_growth = preparation.canon_snapshot(paths.local_root)["hash"]
    pointer_before_dry_run = paths.pointer.read_bytes()
    planned = preparation.dry_run(paths)
    assert planned["expected_terminal_state"] == "RECOMPUTATION_PLANNED"
    assert planned["reason_codes"] == ["candidate_generation_stale_rebuild_planned"]
    assert "candidates" in planned["execution_plan"]["regenerate"]
    assert paths.pointer.read_bytes() == pointer_before_dry_run

    delta = preparation.execute(paths, source_root=source_root)
    assert delta["terminal_state"] == preparation.TERMINAL_HUMAN
    assert delta["ids"]["canon_generation_id"] != ready_one["ids"]["canon_generation_id"]
    assert delta["ids"]["relation_generation_id"] != ready_one["ids"]["relation_generation_id"]
    assert delta["decision_preservation"]["preserved_equivalent"] == 1
    assert delta["decision_preservation"]["pending_delta"] == 1
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_hash_after_growth
    preserved_rows = preparation.read_jsonl(
        paths.current_dir / "human_review_decisions.jsonl"
    )
    assert len(preserved_rows) == 1
    assert preserved_rows[0]["generational_preservation"]["classification"] == "equivalent"
    delta_ids = dict(delta["ids"])

    delta_noop = preparation.execute(paths, source_root=source_root)
    assert delta_noop["idempotent_noop"] is True
    assert delta_noop["ids"] == delta_ids

    _review_current_batch(paths)
    ready_two = preparation.execute(paths, source_root=source_root)
    assert ready_two["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert ready_two["ids"]["canon_generation_id"] == delta_ids["canon_generation_id"]
    assert ready_two["ids"]["relation_generation_id"] == delta_ids["relation_generation_id"]
    assert ready_two["ids"]["review_state_id"] != delta_ids["review_state_id"]


    assert ready_two["ids"]["readiness_id"]
    assert ready_two["planning"]["approved_candidate_representations"] == 2
    assert ready_two["planning"]["planned_unique_relations"] == 2
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_hash_after_growth

    # Evidence changes with stable endpoints/predicate are a human delta.
    (scripts / "a.py").write_text("from b import VALUE\n", encoding="utf-8")
    canon_rows[0]["text"] = "from b import VALUE\n"
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    modified_delta = preparation.execute(paths, source_root=source_root)
    assert modified_delta["terminal_state"] == preparation.TERMINAL_HUMAN
    modified_manifest = preparation.read_json(
        Path(modified_delta["bundle_path"]) / "human_delta.json"
    )
    assert len(modified_manifest["modified"]) == 1
    assert modified_delta["decision_preservation"]["preserved_equivalent"] == 1
    _review_current_batch(paths)
    modified_ready = preparation.execute(paths, source_root=source_root)
    assert modified_ready["terminal_state"] == preparation.TERMINAL_AUTHORIZATION

    # A disappeared candidate remains provenance and is absent from the queue.
    (scripts / "c.py").unlink()
    canon_rows[2]["text"] = "historical source removed\n"
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    disappeared_ready = preparation.execute(paths, source_root=source_root)
    assert disappeared_ready["terminal_state"] == preparation.TERMINAL_AUTHORIZATION
    assert disappeared_ready["decision_preservation"]["disappeared_provenance"] == 1
    assert disappeared_ready["decision_preservation"]["pending_delta"] == 0

    # Two non-bijective matches are never reused automatically.
    (scripts / "a.py").write_text("import b\nimport b\n", encoding="utf-8")
    canon_rows[0]["text"] = "import b\nimport b\n"
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    ambiguous_delta = preparation.execute(paths, source_root=source_root)
    assert ambiguous_delta["terminal_state"] == preparation.TERMINAL_HUMAN
    ambiguous_manifest = preparation.read_json(
        Path(ambiguous_delta["bundle_path"]) / "human_delta.json"
    )
    assert len(ambiguous_manifest["ambiguous"]) == 2
    assert ambiguous_delta["decision_preservation"]["preserved_equivalent"] == 0


def test_review_reason_change_changes_review_state_not_relation_generation(
    tmp_path: Path,
) -> None:
    paths, source_root, _canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    analysis = preparation.analyze(paths)
    changed_taxonomy = json.loads(json.dumps(analysis["review_taxonomy"]))
    changed_taxonomy["items"][0]["reconciliation_class"] = "ambiguous"
    changed_taxonomy["items"][0]["review_reason"] = "reconciliation_ambiguous"

    changed = preparation.generation_ids(
        analysis["canon"], analysis["inputs"],
        str(preparation.sha256_file(analysis["inputs"]["human_decisions"])),
        analysis["pending_ids"], analysis["gate_report"], changed_taxonomy,
    )

    assert changed["relation_generation_id"] == analysis["ids"]["relation_generation_id"]
    assert changed["review_state_id"] != analysis["ids"]["review_state_id"]


def test_exact_previous_v1_delta_classes_are_recovered_without_id_mapping(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    current_candidates = tmp_path / "current.jsonl"
    rows = [_candidate("rc_current_" + f"{number:024x}") for number in range(1, 4)]
    encoded = "".join(json.dumps(row) + "\n" for row in rows)
    current_candidates.write_text(encoded, encoding="utf-8")
    (bundle / "relation_candidates.jsonl").write_text(encoded, encoding="utf-8")
    pending = [row["candidate_id"] for row in rows]
    (bundle / "human_delta.json").write_text(json.dumps({
        "schema_version": "current-relational-human-delta/v1",
        "pending_candidate_ids": pending,
        "new": [],
        "modified": [],
        "ambiguous": [pending[1]],
    }) + "\n", encoding="utf-8")

    recovered = preparation.previous_published_review_classes(
        str(bundle), current_candidates, pending,
    )

    assert recovered == {pending[1]: "ambiguous"}


@pytest.mark.parametrize(
    ("failpoint", "reason_code"),
    [
        ("candidate_generation", "candidate_generation_rebuild_failed"),
        ("candidate_validation", "candidate_validation_rebuild_failed"),
        ("candidate_reconciliation", "cross_generation_reconciliation_failed"),
        ("decision_preservation", "decision_preservation_failed"),
        ("bundle_validation", "human_delta_bundle_publication_failed"),
    ],
)
def test_rebuild_failures_leave_no_current_pointer_or_partial_bundle(
    tmp_path: Path,
    failpoint: str,
    reason_code: str,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    def fail(name: str) -> None:
        if name == failpoint:
            raise RuntimeError(f"injected {name}")

    with pytest.raises((preparation.PreparationBlocked, RuntimeError)) as error:
        preparation.execute(paths, source_root=source_root, failure_hook=fail)

    if isinstance(error.value, preparation.PreparationBlocked):
        assert reason_code in error.value.reason_codes
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before
    assert not paths.pointer.exists()
    assert not paths.current_dir.exists()
    assert not paths.generations.exists() or not any(paths.generations.iterdir())
    assert not list(paths.current_dir.parent.glob(".staging-*"))


def test_failed_rebuild_never_deletes_concurrent_foreign_generation(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    foreign = paths.generations / "rg_foreign" / "rv_foreign" / "human_delta"
    marker = foreign / "owned-by-concurrent-writer.txt"

    def fail(name: str) -> None:
        if name == "bundle_validation":
            foreign.mkdir(parents=True, exist_ok=True)
            marker.write_text("foreign\n", encoding="utf-8")
            raise RuntimeError("injected bundle_validation")

    with pytest.raises(preparation.PreparationBlocked):
        preparation.execute(paths, source_root=source_root, failure_hook=fail)

    assert marker.read_text(encoding="utf-8") == "foreign\n"
    assert not paths.pointer.exists()
    assert not paths.current_dir.exists()
    assert not list(paths.current_dir.parent.glob(".staging-*"))


def test_failed_second_current_swap_restores_previous_current_byte_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    pointer_before = paths.pointer.read_bytes()
    current_before = {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    new_script = source_root / "src/python_scripts/c.py"
    new_script.write_text("import b\n", encoding="utf-8")
    canon_rows.append(_canon_record(
        "source-c", "src/python_scripts/c.py", "import b\n",
    ))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)
    real_replace = preparation.os.replace

    def fail_staging_to_current(source: str | Path, target: str | Path) -> None:
        source_path, target_path = Path(source), Path(target)
        if (
            target_path == paths.current_dir
            and source_path.name == "current"
            and source_path.parent.name.startswith(".staging-")
        ):
            raise OSError("injected second current swap failure")
        real_replace(source, target)

    monkeypatch.setattr(preparation.os, "replace", fail_staging_to_current)

    with pytest.raises(OSError, match="second current swap failure"):
        preparation.execute(paths, source_root=source_root)

    assert paths.pointer.read_bytes() == pointer_before
    assert current_before == {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    assert not list(paths.current_dir.parent.glob(".previous-current-*"))
    assert not list(paths.current_dir.parent.glob(".failed-current-*"))
    assert not list(paths.current_dir.parent.glob(".staging-*"))


def test_incomplete_human_delta_bundle_is_rejected(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    manifest = {
        "terminal_state": preparation.TERMINAL_HUMAN,
        "readiness_id": None,
        "artifacts": {},
    }
    with pytest.raises(preparation.PreparationBlocked) as error:
        preparation._validate_staged_bundle(bundle, manifest)
    assert "bundle_incomplete" in error.value.reason_codes


@pytest.mark.parametrize("failpoint", ["candidate_validation", "bundle_validation"])
def test_failed_rebuild_restores_previous_current_and_pointer_byte_exact(
    tmp_path: Path,
    failpoint: str,
) -> None:
    paths, source_root, canon_rows = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    pointer_before = paths.pointer.read_bytes()
    current_before = {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    (source_root / "src/python_scripts/c.py").write_text("import b\n", encoding="utf-8")
    canon_rows.append(_canon_record("source-c", "src/python_scripts/c.py", "import b\n"))
    _write_canon(paths.local_root / "tiddlers_1.jsonl", canon_rows)

    def fail(name: str) -> None:
        if name == failpoint:
            raise RuntimeError(f"injected {name}")

    with pytest.raises(preparation.PreparationBlocked):
        preparation.execute(paths, source_root=source_root, failure_hook=fail)

    current_after = {
        path.relative_to(paths.current_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths.current_dir.rglob("*") if path.is_file()
    }
    assert current_after == current_before
    assert paths.pointer.read_bytes() == pointer_before
    status = preparation.read_current_bundle_status(paths.local_root)
    assert status["bundle_path"] == preparation.read_json(paths.pointer)["bundle_path"]
    assert not list(paths.current_dir.parent.glob(".staging-*"))


@pytest.mark.parametrize(
    ("surface", "reason_code"),
    [
        ("canon", "generation_drift_during_rebuild"),
        ("decisions", "decisions_drift_during_rebuild"),
    ],
)
def test_drift_before_bundle_publication_blocks_without_partial_current(
    tmp_path: Path,
    surface: str,
    reason_code: str,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)

    def drift(name: str) -> None:
        if name != "bundle_validation":
            return
        if surface == "canon":
            with (paths.local_root / "tiddlers_1.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_canon_record("drift", "drift.py", "")) + "\n")
        else:
            with (paths.current_dir / "human_review_decisions.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{}\n")

    with pytest.raises(preparation.PreparationBlocked) as error:
        preparation.execute(paths, source_root=source_root, failure_hook=drift)

    assert reason_code in error.value.reason_codes
    assert not paths.pointer.exists()
    if surface == "canon":
        assert not paths.current_dir.exists()
    else:
        assert "current_pipeline_descendant_advanced" in error.value.reason_codes
        assert paths.current_dir.exists()
    assert not paths.generations.exists() or not any(paths.generations.iterdir())


def test_generator_can_exclude_stale_current_from_prior_duplicate_detection(
    tmp_path: Path,
) -> None:
    import generate_technical_relation_candidates as generator

    prior = tmp_path / "pipeline" / "current"
    prior.mkdir(parents=True)
    candidate = _candidate("rc_current_" + "a" * 24)
    candidate["source"]["canonical_id"] = "source"
    candidate["target"]["canonical_id"] = "target"
    preparation.write_jsonl(prior / "relation_candidates.jsonl", [candidate])

    included = generator.load_prior_signatures(tmp_path / "pipeline")
    excluded = generator.load_prior_signatures(
        tmp_path / "pipeline", exclude_dirs=[prior]
    )
    assert included
    assert excluded == {}


def test_rebuild_semantic_ids_are_stable_across_staging_retries(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    observed: list[dict[str, str]] = []
    for _ in range(2):
        work, staged_current, _report = preparation.rebuild_source_generation(
            paths, source_root=source_root
        )
        staged_paths = preparation.Paths(
            local_root=paths.local_root,
            current_dir=staged_current,
            audit_root=paths.audit_root,
            admission_current=paths.admission_current,
            generations=paths.generations,
            pointer=paths.pointer,
        )
        observed.append(preparation.analyze(staged_paths)["ids"])
        shutil.rmtree(work)

    assert observed[0] == observed[1]


def test_ready_bundle_is_self_contained_and_current_authorization_is_separate(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_all_pending(paths)
    ready = preparation.execute(paths, source_root=source_root)
    canon_before = preparation.canon_snapshot(paths.local_root)["hash"]

    authority = current_authority.resolve_current_relational_authority(paths.local_root)
    assert authority["readiness_id"] == ready["ids"]["readiness_id"]
    assert all(
        not str(path).startswith(str(paths.current_dir))
        for path in authority["artifacts"].values()
    )
    plan = preparation.read_json(authority["artifacts"]["apply_plan"])
    assert all(not Path(item["path"]).is_absolute() for item in plan["exact_bindings"].values())

    with pytest.raises(current_authority.CurrentRelationalAuthorityError) as error:
        current_apply.authorize(paths.local_root, "fixture-reviewer", "NO")
    assert "authorization_confirmation_invalid" in error.value.reason_codes
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before

    authorization = current_apply.authorize(
        paths.local_root,
        "fixture-reviewer",
        f"AUTHORIZE CURRENT RELATIONAL APPLY {authority['readiness_id']}",
    )
    assert authorization["consumed"] is False
    assert preparation.canon_snapshot(paths.local_root)["hash"] == canon_before


def test_current_apply_requires_second_confirmation_and_consumes_authorization(
    tmp_path: Path,
) -> None:
    paths, source_root, _ = _rebuild_fixture(tmp_path)
    preparation.execute(paths, source_root=source_root)
    _review_all_pending(paths)
    preparation.execute(paths, source_root=source_root)
    authorization = current_apply.authorize(
        paths.local_root,
        "fixture-reviewer",
        f"AUTHORIZE CURRENT RELATIONAL APPLY {current_apply.preflight(paths.local_root)['authority']['readiness_id']}",
    )
    before = preparation.canon_snapshot(paths.local_root)["hash"]
    with pytest.raises(current_authority.CurrentRelationalAuthorityError) as error:
        current_apply.apply(paths.local_root, authorization["authorization_id"], "NO")
    assert "apply_confirmation_invalid" in error.value.reason_codes
    assert preparation.canon_snapshot(paths.local_root)["hash"] == before

    report = current_apply.apply(
        paths.local_root,
        authorization["authorization_id"],
        f"CONFIRM APPLY CURRENT RELATIONS {authorization['authorization_id']}",
    )
    assert report["status"] == "applied"
    assert report["exact_authorized_plan_reused"] is True
    assert Path(report["receipt_path"]).is_file()

    current_audit = paths.local_root / "audit" / "relation_admission" / "current"
    current_report = preparation.read_json(
        current_audit / "relation_apply_report.json"
    )
    current_receipt = preparation.read_json(
        current_audit / "relation_apply_receipt.json"
    )
    assert current_report["apply_id"] == report["apply_id"]
    assert current_report["canon_after_hash"] == report["canon_after_hash"]
    assert current_receipt["apply_id"] == report["apply_id"]
    assert (
        current_receipt["current_relational_authorization_id"]
        == authorization["authorization_id"]
    )

    assert preparation.read_json(
        current_apply.authorization_path(paths.local_root, authorization["readiness_id"])
    )["consumed"] is True
    with pytest.raises(current_authority.CurrentRelationalAuthorityError) as repeated:
        current_apply.apply(
            paths.local_root,
            authorization["authorization_id"],
            f"CONFIRM APPLY CURRENT RELATIONS {authorization['authorization_id']}",
        )
    assert set(repeated.value.reason_codes) & {
        "authorization_not_current", "current_bundle_canon_stale",
    }
