from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "src/python_scripts/relation_admission_state.py"
sys.path.insert(0, str(REPO_ROOT / "src" / "python_scripts"))
import relation_admission_state as relation_state  # noqa: E402
import prepare_current_relational_generation as preparation  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_current_fixture(tmp_path: Path, *, with_run_manifest: bool = True) -> tuple[Path, dict[str, Path]]:
    local = tmp_path / "local"
    current = local / "pipeline/relation_candidates/current"
    audit = local / "audit/relation_admission/current"
    current.mkdir(parents=True)
    audit.mkdir(parents=True)
    canon_path = local / "tiddlers_1.jsonl"
    canon_path.write_text(json.dumps({"id": "fixture", "title": "Fixture", "relations": []}) + "\n", encoding="utf-8")
    canon_hash = _sha256(canon_path)
    batch = current / "relation_candidates.jsonl"
    batch.write_text(json.dumps({"candidate_id": "fixture"}) + "\n", encoding="utf-8")

    generator = REPO_ROOT / "src/python_scripts/generate_technical_relation_candidates.py"
    contract = REPO_ROOT / "src/python_scripts/relation_candidate_contract.py"
    policy = REPO_ROOT / "src/python_scripts/relation_admission_policy.py"
    reconciler = REPO_ROOT / "src/python_scripts/reconcile_current_relation_candidates.py"
    candidate_manifest = current / "current_candidate_manifest.json"
    candidate_manifest.write_text(json.dumps({
        "canon_binding": {"canon_hash": canon_hash},
        "producer": {"hash": _sha256(generator), "contract_hash": _sha256(contract)},
        "candidate_batch": {"hash": _sha256(batch), "record_count": 1},
    }), encoding="utf-8")
    validation = current / "validation_report.json"
    validation.write_text(json.dumps({"summary": {"total": 1, "valid": 1, "invalid": 0, "unresolved_target": 0, "duplicate": 0}}), encoding="utf-8")
    reconciliation = current / "reconciliation_manifest.json"
    reconciliation.write_text(json.dumps({
        "candidate_manifest_hash": _sha256(candidate_manifest),
        "canon_hash": canon_hash,
        "predicate_policy_hash": _sha256(policy),
        "candidate_contract_hash": _sha256(contract),
        "reconciler_hash": _sha256(reconciler),
        "total": 1,
        "unclassified": 0,
        "dispositions": {"ready_for_review": 1},
    }), encoding="utf-8")
    reviewable = current / "reviewable_candidate_manifest.json"
    reviewable.write_text(json.dumps({
        "canon_hash": canon_hash,
        "candidate_manifest_hash": _sha256(candidate_manifest),
        "reconciliation_manifest_hash": _sha256(reconciliation),
        "predicate_policy_hash": _sha256(policy),
    }), encoding="utf-8")
    (current / "human_review_decisions.jsonl").write_text("", encoding="utf-8")
    report = audit / "admission_gate_dry_run.json"
    report.write_text(json.dumps({"summary": {"total_evaluated": 1, "awaiting_human_review": 1}}), encoding="utf-8")
    log = audit / "current_relation_admission_log.jsonl"
    log.write_text("\n", encoding="utf-8")
    if with_run_manifest:
        decisions = current / "human_review_decisions.jsonl"
        gate_contract = REPO_ROOT / "src/python_scripts/relation_admission_gate.py"
        (audit / "current_run_manifest.json").write_text(json.dumps({
            "canon_hash": canon_hash,
            "candidate_manifest_hash": _sha256(candidate_manifest),
            "reviewable_manifest_hash": _sha256(reviewable),
            "report_hash": _sha256(report),
            "log_hash": _sha256(log),
            "human_review_decisions_hash": _sha256(decisions),
            "gate_contract_hash": _sha256(gate_contract),
        }), encoding="utf-8")
    return local, {
        "candidate": candidate_manifest,
        "reconciliation": reconciliation,
        "reviewable": reviewable,
        "policy": policy,
        "contract": contract,
        "reconciler": reconciler,
    }


def test_state_audit_works_without_data_tmp(tmp_path: Path) -> None:
    local = tmp_path / "data/out/local"
    local.mkdir(parents=True)
    (local / "tiddlers_1.jsonl").write_text(
        json.dumps({"id": "fixture", "title": "Fixture", "relations": []}) + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "audit", "--local-root", str(local)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["tmp_dependency"] is False
    assert not (tmp_path / "data/tmp").exists()
    assert (local / "audit/relation_admission/current/relational_operational_state.json").exists()


def test_state_command_is_read_only_and_preserves_existing_report(
    tmp_path: Path,
) -> None:
    local, _ = _write_current_fixture(tmp_path)
    report = (
        local
        / "audit/relation_admission/current/relational_operational_state.json"
    )
    original = b'{"authority":"preexisting-audit-evidence"}\n'
    report.write_bytes(original)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "state", "--local-root", str(local)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["schema_version"] == (
        "relational-operational-state/v1"
    )
    assert report.read_bytes() == original


def test_validate_currentness_returns_two_for_incomplete_fixture(tmp_path: Path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    (local / "tiddlers_1.jsonl").write_text("{}\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate-currentness", "--local-root", str(local)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["verdict"] == "NO_CURRENT_RELATION_CANDIDATE_MANIFEST"


def test_stale_reasons_name_the_exact_changed_binding(tmp_path: Path) -> None:
    local, paths = _write_current_fixture(tmp_path)

    candidate = json.loads(paths["candidate"].read_text())
    candidate["producer"]["contract_hash"] = "changed"
    paths["candidate"].write_text(json.dumps(candidate), encoding="utf-8")
    state = relation_state.build_state(local)
    assert state["candidate_generation"]["stale_reasons"] == ["stale_candidate_contract_changed"]
    assert state["reconciliation"]["stale_reasons"] == ["stale_candidate_manifest_changed"]

    local, paths = _write_current_fixture(tmp_path / "reconciliation")
    reviewable = json.loads(paths["reviewable"].read_text())
    reviewable["reconciliation_manifest_hash"] = "changed"
    paths["reviewable"].write_text(json.dumps(reviewable), encoding="utf-8")
    state = relation_state.build_state(local)
    assert state["reconciliation"]["stale_reasons"] == []
    assert state["blocking_reasons"] == ["stale_reconciliation_manifest_changed"]
    assert "stale_reconciliation_contract_changed" not in state["blocking_reasons"]


def test_stale_reason_controls_and_missing_current_manifest_are_fail_closed(tmp_path: Path) -> None:
    local, paths = _write_current_fixture(tmp_path)
    reconciliation = json.loads(paths["reconciliation"].read_text())
    reconciliation["predicate_policy_hash"] = "changed"
    paths["reconciliation"].write_text(json.dumps(reconciliation), encoding="utf-8")
    state = relation_state.build_state(local)
    assert state["reconciliation"]["stale_reasons"] == ["stale_predicate_policy_changed"]

    local, paths = _write_current_fixture(tmp_path / "reconciler")
    reconciliation = json.loads(paths["reconciliation"].read_text())
    reconciliation["reconciler_hash"] = "changed"
    paths["reconciliation"].write_text(json.dumps(reconciliation), encoding="utf-8")
    state = relation_state.build_state(local)
    assert state["reconciliation"]["stale_reasons"] == ["stale_reconciler_changed"]

    local, paths = _write_current_fixture(tmp_path / "candidate-manifest")
    reconciliation = json.loads(paths["reconciliation"].read_text())
    reconciliation["candidate_manifest_hash"] = "changed"
    paths["reconciliation"].write_text(json.dumps(reconciliation), encoding="utf-8")
    state = relation_state.build_state(local)
    assert state["reconciliation"]["stale_reasons"] == ["stale_candidate_manifest_changed"]

    local, _ = _write_current_fixture(tmp_path / "missing-manifest", with_run_manifest=False)
    state = relation_state.build_state(local)
    assert state["admission_gate"]["current"] is False
    assert state["verdict"] == relation_state.CURRENT_RELATIONAL_AUTHORITY_MISSING_FOR_CURRENT_CANON
    assert state["next_action"] == relation_state.PREPARE_CURRENT_RELATIONAL_GENERATION
    assert state["blocking_reasons"] == ["current_bundle_missing"]
    assert "current_run_manifest_missing" in state["admission_gate"]["stale_reasons"]


def test_current_review_action_is_unique_and_operational(tmp_path: Path) -> None:
    local, _ = _write_current_fixture(tmp_path)
    state = relation_state.build_state(local)
    assert state["verdict"] == relation_state.CURRENT_RELATIONAL_AUTHORITY_MISSING_FOR_CURRENT_CANON
    assert state["next_action"] == relation_state.PREPARE_CURRENT_RELATIONAL_GENERATION
    assert state["blocking_reasons"] == ["current_bundle_missing"]
    assert state["human_review"]["technical_reviewable"] == 1
    assert state["human_review"]["effective_decision_covered"] is None
    assert state["human_review"]["effective_pending"] is None
    assert "OPEN_S0181" not in state["next_action"]


def test_stale_bundle_for_current_pipeline_preserves_causal_authority_reason(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local, _ = _write_current_fixture(tmp_path)
    monkeypatch.setattr(
        preparation,
        "read_current_bundle_status",
        lambda _local_root: {
            "valid": False,
            "reason_codes": ["current_bundle_canon_stale"],
            "bundle_path": "/immutable/previous-canon/bundle",
            "terminal_state": "READY_FOR_HUMAN_DELTA_REVIEW",
            "planning": {"pending_human_review": 12},
        },
    )

    state = relation_state.build_state(local)

    assert state["candidate_generation"]["current"] is True
    assert state["reconciliation"]["current"] is True
    assert state["verdict"] == relation_state.CURRENT_RELATIONAL_AUTHORITY_MISSING_FOR_CURRENT_CANON
    assert state["next_action"] == relation_state.PREPARE_CURRENT_RELATIONAL_GENERATION
    assert state["blocking_reasons"] == ["current_bundle_canon_stale"]
    assert state["current_authority"]["stale_reasons"] == ["current_bundle_canon_stale"]
    assert state["human_review"]["technical_reviewable"] == 1
    assert state["human_review"]["effective_decision_covered"] is None
    assert state["human_review"]["effective_pending"] is None


def test_effective_pending_is_exposed_only_from_a_valid_current_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local, _ = _write_current_fixture(tmp_path)
    monkeypatch.setattr(
        preparation,
        "read_current_bundle_status",
        lambda _local_root: {
            "valid": True,
            "reason_codes": [],
            "bundle_path": "/immutable/current/bundle",
            "terminal_state": "READY_FOR_HUMAN_DELTA_REVIEW",
            "next_action": "REVIEW_CURRENT_RELATIONAL_DELTA",
            "planning": {"pending_human_review": 1},
        },
    )

    state = relation_state.build_state(local)

    assert state["human_review"]["technical_reviewable"] == 1
    assert state["human_review"]["effective_decision_covered"] is None
    assert state["human_review"]["effective_pending"] == 1


def test_legacy_review_remains_visible_while_missing_current_authority_is_prioritized(
    tmp_path: Path,
) -> None:
    local, _ = _write_current_fixture(tmp_path)
    decisions = local / "pipeline/relation_candidates/current/human_review_decisions.jsonl"
    decisions.write_text(json.dumps({
        "schema_version": "relation-human-review-decision/v1",
        "candidate_id": "rc_current_aabb112233445566",
        "human_review_decision": "approved_for_admission",
    }) + "\n", encoding="utf-8")
    state = relation_state.build_state(local)
    assert state["human_review"]["total"] == 0
    assert state["human_review"]["legacy_supersession_required"] == 1
    assert state["human_review"]["current"] is False
    assert state["verdict"] == relation_state.CURRENT_RELATIONAL_AUTHORITY_MISSING_FOR_CURRENT_CANON
    assert state["next_action"] == relation_state.PREPARE_CURRENT_RELATIONAL_GENERATION
    assert state["blocking_reasons"] == ["current_bundle_missing"]


def test_missing_current_authority_precedes_legacy_gate_projection(tmp_path: Path) -> None:
    local, _ = _write_current_fixture(tmp_path)
    current = local / "pipeline/relation_candidates/current"
    audit = local / "audit/relation_admission/current"
    decisions = current / "human_review_decisions.jsonl"
    decisions.write_text(json.dumps({
        "schema_version": "relation-human-review-decision/v2",
        "candidate_id": "rc_current_aabb112233445566",
        "human_review_decision": "approved_for_admission",
    }) + "\n", encoding="utf-8")
    report = audit / "admission_gate_dry_run.json"
    report.write_text(json.dumps({
        "summary": {
            "total_evaluated": 1, "approved_for_admission": 1,
            "admission_ready_dry_run": 0, "technically_invalid": 1,
            "awaiting_human_review": 0,
        }
    }), encoding="utf-8")
    manifest_path = audit / "current_run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["report_hash"] = _sha256(report)
    manifest["human_review_decisions_hash"] = _sha256(decisions)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    state = relation_state.build_state(local)
    assert state["admission_gate"]["technically_invalid"] == 1
    assert state["verdict"] == relation_state.CURRENT_RELATIONAL_AUTHORITY_MISSING_FOR_CURRENT_CANON
    assert state["next_action"] == relation_state.PREPARE_CURRENT_RELATIONAL_GENERATION
    assert state["blocking_reasons"] == ["current_bundle_missing"]
    preflight = relation_state.relational_apply_precondition(state)
    assert "technically_invalid_approvals_present" in preflight["reasons"]


def test_apply_precondition_blocks_incomplete_or_stale_state() -> None:
    state = {
        "admission_gate": {"current": False, "stale_reasons": ["changed"], "admission_ready": 0},
        "human_review": {"total": 0},
        "reconciliation": {"ready_for_review": 157},
        "apply": {"executed": False},
    }
    result = relation_state.relational_apply_precondition(state)
    assert result["allowed"] is False
    assert result["reasons"] == [
        "admission_gate_not_current",
        "admission_gate_has_stale_reasons",
        "human_review_incomplete",
        "no_admission_ready_relations",
    ]


def test_apply_precondition_allows_only_current_complete_ready_state() -> None:
    state = {
        "admission_gate": {"current": True, "stale_reasons": [], "admission_ready": 2},
        "human_review": {"total": 157},
        "reconciliation": {"ready_for_review": 157},
        "apply": {"executed": False},
    }
    result = relation_state.relational_apply_precondition(state)
    assert result["allowed"] is True
    assert result["reasons"] == []


def test_postapply_reconciliation_projects_authority_receipt_and_expected_staleness(
    tmp_path: Path,
) -> None:
    local, _ = _write_current_fixture(tmp_path)
    canon_path = local / "tiddlers_1.jsonl"
    canon_path.write_text(json.dumps({
        "id": "fixture",
        "title": "Fixture",
        "relations": [{
            "relation_schema_version": "canonical-relation/v1",
            "relation_id": "cr1_fixture",
            "source_id": "fixture",
            "target_id": "target",
            "relation_type": "references",
        }],
    }) + "\n", encoding="utf-8")
    post_hash = _sha256(canon_path)
    audit = local / "audit/relation_admission/current"
    snapshot = audit / "rollback_snapshots/apply_exec_fixture/snapshot_manifest.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("{}\n", encoding="utf-8")
    apply_report = {
        "status": "applied",
        "apply_id": "apply_exec_fixture",
        "applied_count": 1,
        "canon_modified": True,
        "canon_after_hash": post_hash,
        "rollback_snapshot": str(snapshot),
        "rollback_snapshot_hash": _sha256(snapshot),
    }
    (audit / "relation_apply_report.json").write_text(
        json.dumps(apply_report), encoding="utf-8",
    )
    (audit / "relation_apply_receipt.json").write_text(json.dumps({
        "apply_id": "apply_exec_fixture",
        "rollback_snapshot": str(snapshot),
        "rollback_snapshot_hash": _sha256(snapshot),
    }), encoding="utf-8")
    gate_g = local / "audit/s0183/gate-g"
    gate_g.mkdir(parents=True)
    (gate_g / "gate_g_authorization.json").write_text(json.dumps({
        "schema_version": "gate-g-authorization/v1",
        "authorization_id": "auth_fixture",
        "decision": "authorized",
        "consumed": True,
        "consumed_by_apply_id": "apply_exec_fixture",
    }), encoding="utf-8")
    reconciliation = local / "audit/s0183/reconciliation"
    reconciliation.mkdir(parents=True)
    (reconciliation / "authorization_consumption_reconciliation.json").write_text(
        json.dumps({
            "authorization": {"valid_at_execution": True},
            "consumption": {"consumed_once": True},
        }),
        encoding="utf-8",
    )
    (reconciliation / "productive_apply_reconciliation.json").write_text(
        json.dumps({
            "status": "reconciled",
            "apply_id": "apply_exec_fixture",
            "canon": {"post_hash": post_hash},
        }),
        encoding="utf-8",
    )

    state = relation_state.build_state(local)

    assert state["canonical_relation_v1"] == 1
    assert state["apply"]["executed"] is True
    assert state["apply"]["authorized_at_execution"] is True
    assert state["apply"]["authorization_consumed"] is True
    assert state["apply"]["receipt_path"].endswith("relation_apply_receipt.json")
    assert state["apply"]["reconciled"] is True
    assert state["rollback"]["receipt_bound"] is True
    assert state["expected_postapply_staleness"]["recognized"] is True
    assert state["blocking_reasons"] == []
    assert state["verdict"] == "RELATIONAL_PRODUCTIVE_APPLY_RECONCILED"
    assert state["next_action"] == "START_POSTIMPACT_CLOSURE"


def test_current_generational_postapply_is_reconciled_without_s0183(
    tmp_path: Path,
) -> None:
    local, _ = _write_current_fixture(tmp_path)

    canon_path = local / "tiddlers_1.jsonl"
    canon_path.write_text(json.dumps({
        "id": "fixture",
        "title": "Fixture",
        "relations": [{
            "relation_schema_version": "canonical-relation/v1",
            "relation_id": "cr1_current_fixture",
            "source_id": "fixture",
            "target_id": "target",
            "relation_type": "references",
        }],
    }) + "\n", encoding="utf-8")
    post_hash = _sha256(canon_path)

    readiness_id = "rd_current_fixture"
    authorization_id = "cra_current_fixture"
    apply_id = "apply_exec_current_fixture"

    current_audit = local / "audit/relation_admission/current"
    receipt_dir = (
        local / "audit/relation_admission/apply_receipts"
        / readiness_id / authorization_id
    )
    snapshot = (
        receipt_dir / "rollback_snapshots"
        / apply_id / "snapshot_manifest.json"
    )
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("{}\n", encoding="utf-8")

    report = {
        "schema": "relation-admission-apply-report/v1",
        "status": "applied",
        "apply_executed": True,
        "apply_id": apply_id,
        "applied_count": 1,
        "failed_count": 0,
        "canon_modified": True,
        "canon_before_hash": "pre_current_fixture",
        "canon_after_hash": post_hash,
        "rollback_snapshot": str(snapshot),
        "rollback_snapshot_hash": _sha256(snapshot),
    }
    (current_audit / "relation_apply_report.json").write_text(
        json.dumps(report), encoding="utf-8",
    )

    receipt = {
        "schema_version": "relation-admission-apply-receipt/v1",
        "status": "applied",
        "apply_id": apply_id,
        "current_relational_authorization_id": authorization_id,
        "readiness_id": readiness_id,
        "bundle_manifest_hash": "bundle_current_fixture",
        "sealed_apply_plan_hash": "plan_current_fixture",
        "canon_before_hash": "pre_current_fixture",
        "canon_after_hash": post_hash,
        "applied_count": 1,
        "failed_count": 0,
        "rollback_snapshot": str(snapshot),
        "rollback_snapshot_hash": _sha256(snapshot),
    }
    current_receipt = current_audit / "relation_apply_receipt.json"
    current_receipt.write_text(json.dumps(receipt), encoding="utf-8")

    auth_path = (
        local / "audit/relation_admission/authorizations"
        / readiness_id / "authorization.json"
    )
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text(json.dumps({
        "schema_version": "current-relational-authorization/v1",
        "authorization_id": authorization_id,
        "readiness_id": readiness_id,
        "bundle_manifest_hash": "bundle_current_fixture",
        "apply_plan_hash": "plan_current_fixture",
        "consumed": True,
        "canon_modified": True,
        "relations_written": 1,
        "receipt_hash": _sha256(current_receipt),
    }), encoding="utf-8")

    state = relation_state.build_state(local)

    assert state["canonical_relation_v1"] == 1
    assert state["apply"]["executed"] is True
    assert state["apply"]["apply_id"] == apply_id
    assert state["apply"]["authorization_current"] is True
    assert state["apply"]["authorized_at_execution"] is True
    assert state["apply"]["authorization_consumed"] is True
    assert state["apply"]["reconciled"] is True
    assert state["rollback"]["available"] is True
    assert state["rollback"]["ready"] is True
    assert state["rollback"]["current"] is True
    assert state["rollback"]["receipt_bound"] is True
    assert state["expected_postapply_staleness"]["recognized"] is True
    assert state["blocking_reasons"] == []
    assert state["verdict"] == "RELATIONAL_PRODUCTIVE_APPLY_RECONCILED"
    assert state["next_action"] == "START_POSTIMPACT_CLOSURE"


def test_current_generational_convergent_noop_is_reconciled_without_s0183(
    tmp_path: Path,
) -> None:
    local, _ = _write_current_fixture(tmp_path)

    canon_path = local / "tiddlers_1.jsonl"
    canon_path.write_text(json.dumps({
        "id": "fixture",
        "title": "Fixture",
        "relations": [{
            "relation_schema_version": "canonical-relation/v1",
            "relation_id": "cr1_current_fixture",
            "source_id": "fixture",
            "target_id": "target",
            "relation_type": "references",
        }],
    }) + "\n", encoding="utf-8")
    post_hash = _sha256(canon_path)

    readiness_id = "rd_current_noop_fixture"
    authorization_id = "cra_current_noop_fixture"
    apply_id = "apply_exec_current_noop_fixture"

    current_audit = local / "audit/relation_admission/current"
    receipt_dir = (
        local / "audit/relation_admission/apply_receipts"
        / readiness_id / authorization_id
    )
    snapshot = (
        receipt_dir / "rollback_snapshots"
        / apply_id / "snapshot_manifest.json"
    )
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("{}\n", encoding="utf-8")

    report = {
        "schema": "relation-admission-apply-report/v1",
        "status": "applied",
        "apply_executed": False,
        "apply_id": apply_id,
        "applied_count": 0,
        "omitted_existing_count": 1,
        "failed_count": 0,
        "canon_modified": False,
        "canon_before_hash": post_hash,
        "canon_after_hash": post_hash,
        "rollback_snapshot": str(snapshot),
        "rollback_snapshot_hash": _sha256(snapshot),
    }
    (current_audit / "relation_apply_report.json").write_text(
        json.dumps(report), encoding="utf-8",
    )

    receipt = {
        "schema_version": "relation-admission-apply-receipt/v1",
        "status": "applied",
        "apply_id": apply_id,
        "current_relational_authorization_id": authorization_id,
        "readiness_id": readiness_id,
        "bundle_manifest_hash": "bundle_current_noop_fixture",
        "sealed_apply_plan_hash": "plan_current_noop_fixture",
        "canon_before_hash": post_hash,
        "canon_after_hash": post_hash,
        "applied_count": 0,
        "failed_count": 0,
        "rollback_snapshot": str(snapshot),
        "rollback_snapshot_hash": _sha256(snapshot),
    }
    current_receipt = current_audit / "relation_apply_receipt.json"
    current_receipt.write_text(json.dumps(receipt), encoding="utf-8")

    auth_path = (
        local / "audit/relation_admission/authorizations"
        / readiness_id / "authorization.json"
    )
    auth_path.parent.mkdir(parents=True)
    auth_path.write_text(json.dumps({
        "schema_version": "current-relational-authorization/v1",
        "authorization_id": authorization_id,
        "readiness_id": readiness_id,
        "bundle_manifest_hash": "bundle_current_noop_fixture",
        "apply_plan_hash": "plan_current_noop_fixture",
        "consumed": True,
        "canon_modified": False,
        "relations_written": 0,
        "receipt_hash": _sha256(current_receipt),
    }), encoding="utf-8")

    state = relation_state.build_state(local)

    assert state["canonical_relation_v1"] == 1
    assert state["apply"]["executed"] is True
    assert state["apply"]["apply_id"] == apply_id
    assert state["apply"]["authorization_current"] is True
    assert state["apply"]["authorized_at_execution"] is True
    assert state["apply"]["authorization_consumed"] is True
    assert state["apply"]["reconciled"] is True
    assert state["rollback"]["available"] is False
    assert state["rollback"]["ready"] is True
    assert state["rollback"]["current"] is True
    assert state["rollback"]["receipt_bound"] is True
    assert state["expected_postapply_staleness"]["recognized"] is True
    assert state["blocking_reasons"] == []
    assert state["verdict"] == "RELATIONAL_PRODUCTIVE_APPLY_RECONCILED"
    assert state["next_action"] == "START_POSTIMPACT_CLOSURE"
