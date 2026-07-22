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
    assert state["verdict"] == "READY_FOR_HUMAN_RELATIONAL_REVIEW"
    assert state["next_action"] == relation_state.RECORD_CURRENT_HUMAN_RELATIONAL_DECISIONS
    assert "current_run_manifest_missing" in state["admission_gate"]["stale_reasons"]


def test_current_review_action_is_unique_and_operational(tmp_path: Path) -> None:
    local, _ = _write_current_fixture(tmp_path)
    state = relation_state.build_state(local)
    assert state["next_action"] == relation_state.RECORD_CURRENT_HUMAN_RELATIONAL_DECISIONS
    assert "OPEN_S0181" not in state["next_action"]


def test_legacy_review_is_counted_as_evidence_but_requires_supersession(tmp_path: Path) -> None:
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
    assert state["verdict"] == "LEGACY_HUMAN_RELATIONAL_REVIEW_NOT_AUTHORITATIVE"
    assert state["next_action"] == relation_state.SUPERSEDE_LEGACY_HUMAN_RELATIONAL_DECISIONS


def test_technically_invalid_approvals_emit_partial_verdict(tmp_path: Path) -> None:
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
    assert state["verdict"] == "RELATIONAL_ADMISSION_PARTIALLY_READY"
    assert state["next_action"] == "RESOLVE_OR_DEFER_TECHNICALLY_INVALID_APPROVALS"
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
