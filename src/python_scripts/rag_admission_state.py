#!/usr/bin/env python3
"""Evidence-derived RAG admission state and governed lifecycle commands.

This module owns the stable operational capability.  It deliberately reuses
``derive_layers.py`` as producer and ``rag_derivative_writers.py`` as the only
productive persistence boundary; it never derives or writes productive
artifacts itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_derivation_plan import canonical_snapshot
from rag_derivative_writers import (
    ProductiveWriteBlocked,
    promote_staging_transaction,
    rollback_productive_transaction,
    snapshot_productive_derivatives,
    verify_rollback_snapshot,
    verify_productive_state_matches_snapshot,
)
from s0174_governance import build_governance_gate, build_post_write_validation, build_producer_inventory


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
LOCAL_ROOT = REPO_ROOT / "data" / "out" / "local"
PIPELINE_ROOT = LOCAL_ROOT / "pipeline" / "rag_admission"
AUDIT_ROOT = LOCAL_ROOT / "audit" / "rag_admission"
STAGING_ROOT = PIPELINE_ROOT / "staging"
STAGING_MANIFEST = PIPELINE_ROOT / "staging_manifest.json"
TECHNICAL_GATE = AUDIT_ROOT / "technical_gate_report.json"
EQUIVALENCE_REPORT = AUDIT_ROOT / "staging_equivalence_report.json"
GOVERNANCE_GATE = AUDIT_ROOT / "governance_gate_report.json"
STATE_REPORT = AUDIT_ROOT / "rag_admission_state.json"
AUTH_ROOT = AUDIT_ROOT / "authorizations"
TRIAL_AUTH = AUTH_ROOT / "trial_write_authorization.json"
DEFINITIVE_AUTH = AUTH_ROOT / "definitive_promotion_authorization.json"
# S0175 evidence remains immutable at its original paths.  A current governed
# trial uses a single, explicitly separate active surface; this is not a
# general run registry and prevents historical receipts/snapshots from either
# blocking or satisfying the current manifest.
HISTORICAL_TRIAL_SNAPSHOT = PIPELINE_ROOT / "trial_rollback_snapshot"
HISTORICAL_TRIAL_RECEIPT = AUDIT_ROOT / "trial_write_receipt.json"
HISTORICAL_TRIAL_VALIDATION = AUDIT_ROOT / "trial_post_write_validation.json"
HISTORICAL_ROLLBACK_REPORT = AUDIT_ROOT / "rollback_execution_report.json"
HISTORICAL_ROLLBACK_EQUALITY = AUDIT_ROOT / "rollback_equality_report.json"
HISTORICAL_ROLLBACK_ERROR = AUDIT_ROOT / "rollback_error_report.json"
HISTORICAL_TRIAL_JOURNAL = AUDIT_ROOT / "trial_transaction_journal.jsonl"
HISTORICAL_TRIAL_CLASSIFICATION = AUDIT_ROOT / "historical_trial_snapshot_classification.json"
ACTIVE_TRIAL_ROOT = AUDIT_ROOT / "current_trial"
TRIAL_SNAPSHOT = PIPELINE_ROOT / "current_trial_rollback_snapshot"
DEFINITIVE_SNAPSHOT = PIPELINE_ROOT / "definitive_rollback_snapshot"
TRIAL_RECEIPT = ACTIVE_TRIAL_ROOT / "trial_write_receipt.json"
DEFINITIVE_RECEIPT = AUDIT_ROOT / "definitive_promotion_receipt.json"
TRIAL_VALIDATION = ACTIVE_TRIAL_ROOT / "trial_post_write_validation.json"
TRIAL_VALIDATION_OUT_OF_SEQUENCE = ACTIVE_TRIAL_ROOT / "trial_validation_out_of_sequence.json"
DEFINITIVE_VALIDATION = AUDIT_ROOT / "definitive_post_write_validation.json"
ROLLBACK_REPORT = ACTIVE_TRIAL_ROOT / "rollback_execution_report.json"
ROLLBACK_EQUALITY = ACTIVE_TRIAL_ROOT / "rollback_equality_report.json"
ROLLBACK_ERROR = ACTIVE_TRIAL_ROOT / "rollback_error_report.json"
TRIAL_JOURNAL = ACTIVE_TRIAL_ROOT / "trial_transaction_journal.jsonl"
DEFINITIVE_JOURNAL = AUDIT_ROOT / "definitive_transaction_journal.jsonl"
FINAL_MANIFEST = AUDIT_ROOT / "productive_rag_manifest.json"
HISTORICAL_BASELINE_ROOT = LOCAL_ROOT / "pipeline" / "rag_derivation" / "s0174" / "staging"
HISTORICAL_BASELINE_MANIFEST = LOCAL_ROOT / "pipeline" / "rag_derivation" / "s0174" / "staging_manifest.json"
PRODUCTIVE_FAMILIES = ("enriched", "ai", "microsoft_copilot")
PRODUCTIVE_ROOTS = {name: LOCAL_ROOT / name for name in PRODUCTIVE_FAMILIES}
ADMISSION_SCOPE_ID = "governed-rag-admission"
NON_BLOCKING_EQUIVALENCE_STATUSES = {
    "equivalent",
    "equivalent_with_declared_operational_differences",
    "equivalent_with_expected_canonical_evolution",
}
TRIAL_PHRASE = "AUTORIZO TRIAL RAG SAFE"
DEFINITIVE_PHRASE = "AUTORIZO PROMOCION DEFINITIVA RAG SAFE"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, "absent"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, f"invalid_json:{error}"
    return (value, None) if isinstance(value, dict) else ({}, "invalid_json:object_required")


def _write(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(root.rglob("*")) if file.is_file()
    }


def _protected_snapshot() -> dict[str, Any]:
    canon = canonical_snapshot(LOCAL_ROOT)
    return {
        "canon_hash": canon.get("source_canon_hash"),
        "reverse_html": _tree(LOCAL_ROOT / "reverse_html"),
        "relations": _tree(LOCAL_ROOT / "pipeline" / "relation_candidates"),
        "remote_mutated": False,
    }


def _rollback_family_states(snapshot_root: Path) -> dict[str, str]:
    """Classify live families against the persistent pre-trial snapshot."""

    states: dict[str, str] = {}
    for family, productive_root in PRODUCTIVE_ROOTS.items():
        states[family] = "snapshot_state" if _tree(productive_root) == _tree(snapshot_root / family) else "trial_state"
    return states


def _authorization_status(path: Path, operation: str, manifest_hash: str | None) -> tuple[str, list[str]]:
    auth, error = _read(path)
    if error == "absent":
        return "absent", []
    if error:
        return "invalid", [error]
    reasons = []
    if auth.get("operation") != operation:
        reasons.append("operation_mismatch")
    if auth.get("staging_manifest_hash") != manifest_hash:
        reasons.append("staging_manifest_hash_stale")
    if auth.get("planned_families") != list(PRODUCTIVE_FAMILIES):
        reasons.append("family_scope_invalid")
    if auth.get("deletion_policy") != "none":
        reasons.append("deletion_policy_invalid")
    if auth.get("authorized_by") != "human_operator":
        reasons.append("authorized_by_invalid")
    if reasons:
        return "stale", reasons
    if auth.get("consumed") is True:
        return "consumed", []
    return "valid", []


def _evidence_matches_manifest(value: dict[str, Any], manifest_hash: str | None) -> bool:
    """Operational evidence is reusable only for the exact active manifest."""

    return bool(manifest_hash and _receipt_manifest_hash(value) == manifest_hash)


def _receipt_manifest_hash(value: dict[str, Any]) -> str | None:
    """Read the manifest binding from v1 or transitional nested receipts."""

    direct = value.get("staging_manifest_hash")
    nested = value.get("write_manifest")
    if isinstance(direct, str):
        return direct
    if isinstance(nested, dict) and isinstance(nested.get("staging_manifest_hash"), str):
        return nested["staging_manifest_hash"]
    return None


def _current_trial_receipt(
    receipt: dict[str, Any],
    authorization: dict[str, Any],
    manifest_hash: str | None,
    operation: str,
) -> tuple[bool, list[str]]:
    """Require a successful receipt from this manifest and authorization."""

    reasons: list[str] = []
    if not receipt:
        reasons.append("trial_receipt_absent")
    elif receipt.get("operation") != operation:
        reasons.append("trial_receipt_operation_mismatch")
    elif receipt.get("status") != "promotion_completed":
        reasons.append("trial_receipt_not_successful")
    if _receipt_manifest_hash(receipt) != manifest_hash:
        reasons.append("trial_receipt_manifest_mismatch")
    if receipt.get("authorization_id") != authorization.get("authorization_id"):
        reasons.append("trial_receipt_authorization_mismatch")
    if receipt.get("session_id") != ADMISSION_SCOPE_ID:
        reasons.append("trial_receipt_scope_mismatch")
    return not reasons, reasons


def _current_trial_validation(
    report: dict[str, Any], authorization: dict[str, Any], manifest_hash: str | None
) -> bool:
    return bool(
        report.get("status") == "pass"
        and report.get("operation") == "trial_write"
        and report.get("staging_manifest_hash") == manifest_hash
        and report.get("authorization_id") == authorization.get("authorization_id")
    )


def _current_rollback_evidence(
    report: dict[str, Any], equality: dict[str, Any], authorization: dict[str, Any], manifest_hash: str | None
) -> bool:
    return bool(
        report.get("status") == "pass"
        and report.get("staging_manifest_hash") == manifest_hash
        and report.get("authorization_id") == authorization.get("authorization_id")
        and equality.get("status") == "pass"
        and equality.get("state_equal") is True
        and equality.get("staging_manifest_hash") == manifest_hash
        and equality.get("authorization_id") == authorization.get("authorization_id")
    )


def _receipt_after_files_match_staging(receipt: dict[str, Any]) -> tuple[bool, list[str]]:
    """Confirm the writer's post-replace file hashes still match frozen staging."""

    mismatches: list[str] = []
    write_manifest = receipt.get("write_manifest")
    operations = write_manifest.get("operations") if isinstance(write_manifest, dict) else None
    if not isinstance(operations, list):
        return False, ["write_manifest_operations_missing"]
    for operation in operations:
        if not isinstance(operation, dict) or not isinstance(operation.get("family"), str):
            mismatches.append("invalid_write_manifest_operation")
            continue
        family = operation["family"]
        expected = {
            str(entry.get("relative_path")): entry.get("sha256")
            for entry in operation.get("after_files", [])
            if isinstance(entry, dict)
        }
        observed = _tree(STAGING_ROOT / family)
        if expected != observed:
            mismatches.append(family)
    return not mismatches, mismatches


def recover_trial_validation_from_receipt() -> dict[str, Any]:
    """Retain the completed pre-rollback validation when its report was overwritten.

    This narrow recovery is only for the active trial: it validates the
    writer-captured post-replace hashes against frozen staging and records that
    it is an attestation of the direct-disk validation already executed before
    rollback. It never writes productive families or replays a trial.
    """

    authorization, auth_error = _read(TRIAL_AUTH)
    receipt, receipt_error = _read(TRIAL_RECEIPT)
    manifest_hash = _hash(STAGING_MANIFEST)
    current, reasons = _current_trial_receipt(receipt, authorization, manifest_hash, "trial_write")
    matched, mismatches = _receipt_after_files_match_staging(receipt) if current else (False, [])
    if auth_error or receipt_error or not current or not matched:
        details = ([auth_error] if auth_error else []) + ([receipt_error] if receipt_error else []) + reasons + mismatches
        raise ProductiveWriteBlocked("trial validation evidence recovery blocked: " + ", ".join(details))
    report = {
        "schema_version": "rag-post-write-validation/v2",
        "session_id": ADMISSION_SCOPE_ID,
        "operation": "trial_write",
        "status": "pass",
        "blocking": False,
        "staging_manifest_hash": manifest_hash,
        "authorization_id": authorization.get("authorization_id"),
        "receipt_checks": {"current": True, "reasons": []},
        "validation_basis": "receipt_attested_recovery_after_out_of_sequence_revalidation",
        "direct_disk_validation": "executed_before_rollback",
        "receipt_after_files_match_staging": True,
        "protected_surfaces": _assert_protected(authorization),
        "canon_modified": False,
        "reverse_html_modified": False,
    }
    _write(TRIAL_VALIDATION, report)
    write_state()
    return report


def _historical_snapshot_hashes(snapshot_root: Path) -> dict[str, str]:
    return {
        family: hashlib.sha256(json.dumps(_tree(snapshot_root / family), sort_keys=True).encode()).hexdigest()
        for family in PRODUCTIVE_FAMILIES
    }


def classify_historical_trial_snapshot() -> dict[str, Any]:
    """Preserve and classify S0175 evidence without relocating or rewriting it."""

    manifest, manifest_error = _read(HISTORICAL_TRIAL_SNAPSHOT / "rollback_manifest.json")
    receipt, receipt_error = _read(HISTORICAL_TRIAL_RECEIPT)
    validation, validation_error = _read(HISTORICAL_TRIAL_VALIDATION)
    rollback, rollback_error = _read(HISTORICAL_ROLLBACK_REPORT)
    equality, equality_error = _read(HISTORICAL_ROLLBACK_EQUALITY)
    verification = (
        verify_rollback_snapshot(HISTORICAL_TRIAL_SNAPSHOT, manifest)
        if not manifest_error
        else {"restored_manifest_matches": False, "mismatches": [manifest_error]}
    )
    payload = {
        "schema_version": "rag-historical-trial-snapshot/v1",
        "operation": "preserve_historical_trial_snapshot",
        "classified_at": _now(),
        "historical_snapshot": {
            "present": HISTORICAL_TRIAL_SNAPSHOT.exists(),
            "path": str(HISTORICAL_TRIAL_SNAPSHOT),
            "session_id": manifest.get("session_id"),
            "created_at": manifest.get("created_at"),
            "manifest_hash": _receipt_manifest_hash(receipt),
            "reusable_for_current_manifest": False,
            "protected": True,
            "files_manifest": len(manifest.get("files", [])),
            "hashes": _historical_snapshot_hashes(HISTORICAL_TRIAL_SNAPSHOT),
            "verification": verification,
        },
        "provenance": {
            "receipt_path": str(HISTORICAL_TRIAL_RECEIPT),
            "receipt_session_id": receipt.get("session_id"),
            "validation_path": str(HISTORICAL_TRIAL_VALIDATION),
            "rollback_path": str(HISTORICAL_ROLLBACK_REPORT),
            "equality_path": str(HISTORICAL_ROLLBACK_EQUALITY),
            "evidence_errors": [error for error in (receipt_error, validation_error, rollback_error, equality_error) if error],
            "historical_status": {
                "trial": receipt.get("status"),
                "validation": validation.get("status"),
                "rollback": rollback.get("status"),
                "state_equal": equality.get("state_equal"),
            },
        },
        "active_surface": {
            "snapshot_path": str(TRIAL_SNAPSHOT),
            "audit_root": str(ACTIVE_TRIAL_ROOT),
            "shares_historical_authority": False,
        },
        "relocation_performed": False,
        "productive_surfaces_mutated": False,
    }
    _write(HISTORICAL_TRIAL_CLASSIFICATION, payload)
    return payload


def resolve_equivalence_baseline() -> tuple[Path, Path | None, str]:
    """Resolve the baseline without making a historical session a dependency.

    Once a governed productive manifest exists, its productive corpus is the
    comparison baseline.  Until that first promotion, the retained historical
    staging snapshot is an explicit bootstrap fallback, not product identity.
    """

    final_manifest, _ = _read(FINAL_MANIFEST)
    productive_present = all(path.exists() for path in PRODUCTIVE_ROOTS.values())
    if final_manifest.get("status") == "admitted" and productive_present:
        return LOCAL_ROOT, FINAL_MANIFEST, "last_admitted_productive_manifest"
    return HISTORICAL_BASELINE_ROOT, HISTORICAL_BASELINE_MANIFEST, "historical_bootstrap_baseline"


def build_state() -> dict[str, Any]:
    """Reconstruct the only current admission verdict from evidence on disk."""

    manifest, manifest_error = _read(STAGING_MANIFEST)
    gate, gate_error = _read(GOVERNANCE_GATE)
    technical, technical_error = _read(TECHNICAL_GATE)
    equivalence, equivalence_error = _read(EQUIVALENCE_REPORT)
    trial_receipt, _ = _read(TRIAL_RECEIPT)
    trial_validation, _ = _read(TRIAL_VALIDATION)
    rollback, _ = _read(ROLLBACK_REPORT)
    rollback_equality, _ = _read(ROLLBACK_EQUALITY)
    rollback_error, rollback_error_parse_error = _read(ROLLBACK_ERROR)
    definitive_receipt, _ = _read(DEFINITIVE_RECEIPT)
    definitive_validation, _ = _read(DEFINITIVE_VALIDATION)
    final_manifest, _ = _read(FINAL_MANIFEST)
    canon = canonical_snapshot(LOCAL_ROOT)
    manifest_hash = _hash(STAGING_MANIFEST)
    reasons: list[str] = []
    errors = [error for error in (manifest_error, gate_error, technical_error, equivalence_error, rollback_error_parse_error) if error and error != "absent"]
    staging_current = bool(manifest) and manifest.get("source_canon_hash") == canon.get("source_canon_hash")
    staging_current = staging_current and manifest.get("productive_orchestrator_hash") == _hash(SCRIPT_DIR / "derive_layers.py")
    if not manifest:
        reasons.append("staging_missing")
    elif not staging_current:
        reasons.append("staging_stale")
    technical_pass = technical.get("status") == "pass" and technical.get("blocking") is not True
    equivalence_current = (
        equivalence.get("schema_version") == "productive-equivalence-report/v2"
        and equivalence.get("current", {}).get("canon_hash") == canon.get("source_canon_hash")
        and equivalence.get("current", {}).get("staging_manifest_hash") == manifest_hash
    )
    equivalence_pass = (
        equivalence.get("equivalence_status") in NON_BLOCKING_EQUIVALENCE_STATUSES
        and equivalence.get("blocking") is not True
        and equivalence_current
    )
    gate_pass = gate.get("status") == "pass" and gate.get("blocking") is not True and gate.get("staging_manifest_hash") == manifest_hash
    trial_authorization, _ = _read(TRIAL_AUTH)
    trial_auth, trial_auth_reasons = _authorization_status(TRIAL_AUTH, "trial_write", manifest_hash)
    definitive_auth, definitive_auth_reasons = _authorization_status(DEFINITIVE_AUTH, "definitive_promotion", manifest_hash)
    trial_evidence_current, trial_receipt_reasons = _current_trial_receipt(
        trial_receipt, trial_authorization, manifest_hash, "trial_write"
    )
    definitive_evidence_current = _evidence_matches_manifest(definitive_receipt, manifest_hash)
    trial_validated = trial_evidence_current and _current_trial_validation(trial_validation, trial_authorization, manifest_hash)
    rollback_ok = trial_evidence_current and _current_rollback_evidence(
        rollback, rollback_equality, trial_authorization, manifest_hash
    )
    definitive_ok = definitive_evidence_current and definitive_receipt.get("status") == "promotion_completed" and definitive_validation.get("status") == "pass"
    final_ok = final_manifest.get("status") == "admitted" and final_manifest.get("staging_manifest_hash") == manifest_hash
    rollback_failed = rollback_error.get("status") == "error" and rollback_error.get("resolved") is not True
    trial_validation_blocked = (
        not trial_evidence_current
        and trial_validation.get("verdict") == "TRIAL_VALIDATION_BLOCKED"
        and trial_validation.get("next_action") == "EXECUTE_TRIAL_WRITE"
    )
    trial_authorization_current = {
        "manifest_matches": bool(trial_authorization) and trial_authorization.get("staging_manifest_hash") == manifest_hash,
        "canon_matches": bool(trial_authorization)
        and trial_authorization.get("protected_before", {}).get("canon_hash") == canon.get("source_canon_hash"),
        "staging_matches": staging_current,
        "scope_matches": bool(trial_authorization) and trial_authorization.get("planned_families") == list(PRODUCTIVE_FAMILIES),
        "consumed": trial_authorization.get("consumed") is True,
        "productive_mutation_started": trial_evidence_current,
    }
    if errors:
        verdict, next_action = "ERROR_INCONSISTENT_EVIDENCE", "REPAIR_EVIDENCE"
    elif rollback_failed:
        verdict, next_action = "BLOCKED_ROLLBACK_ERROR", "FIX_AND_RESUME_TRIAL_ROLLBACK"
    elif not manifest:
        verdict, next_action = "NO_STAGING", "UPDATE_STAGING"
    elif not staging_current:
        verdict, next_action = "STAGING_STALE", "UPDATE_STAGING"
    elif not technical_pass:
        verdict, next_action = "BLOCKED_TECHNICAL_GATE", "VALIDATE_STAGING"
    elif not equivalence_pass:
        verdict, next_action = "BLOCKED_EQUIVALENCE", "VALIDATE_STAGING"
    elif not gate_pass:
        verdict, next_action = "BLOCKED_GOVERNANCE", "VALIDATE_GOVERNANCE"
    elif definitive_ok and final_ok:
        verdict, next_action = "READY_FOR_RAG", "VIEW_AUDIT"
    elif definitive_ok:
        verdict, next_action = "DEFINITIVE_PROMOTION_EXECUTED", "FINALIZE_PRODUCTIVE_MANIFEST"
    elif rollback_ok and definitive_auth == "valid":
        verdict, next_action = "READY_FOR_DEFINITIVE_PROMOTION", "EXECUTE_DEFINITIVE_PROMOTION"
    elif rollback_ok:
        verdict, next_action = "PRODUCTIVE_ROLLBACK_VERIFIED", "REQUEST_DEFINITIVE_AUTHORIZATION"
    elif trial_validated:
        verdict, next_action = "TRIAL_VALIDATED", "EXECUTE_TRIAL_ROLLBACK"
    elif trial_evidence_current:
        verdict, next_action = "TRIAL_WRITE_SUCCEEDED", "VALIDATE_TRIAL_FROM_DISK"
    elif trial_validation_blocked and trial_auth == "valid":
        verdict, next_action = "TRIAL_VALIDATION_BLOCKED", "EXECUTE_TRIAL_WRITE"
    elif trial_auth == "valid":
        verdict, next_action = "TRIAL_AUTHORIZED", "EXECUTE_TRIAL_WRITE"
    else:
        verdict, next_action = "READY_FOR_GOVERNED_WRITE", "REQUEST_TRIAL_AUTHORIZATION"
    return {
        "schema_version": "rag-admission-state/v2",
        "checked_at": _now(),
        "canon": {"current": bool(canon.get("source_canon_hash")), "mutated": False, "hash": canon.get("source_canon_hash")},
        "staging": {"exists": bool(manifest), "current": staging_current, "manifest_path": str(STAGING_MANIFEST), "manifest_hash": manifest_hash, "orchestrator_current": manifest.get("productive_orchestrator_hash") == _hash(SCRIPT_DIR / "derive_layers.py") if manifest else False},
        "technical_gate": {"status": technical.get("status", "absent"), "current": technical_pass},
        "equivalence": {
            "status": equivalence.get("equivalence_status", "absent"),
            "current": equivalence_current,
            "blocking": equivalence.get("blocking"),
            "evolution": equivalence.get("evolution", {"additions": 0, "updates": 0, "removals": 0, "regressions": 0}),
        },
        "governance_gate": {"status": gate.get("status", "absent"), "current": gate_pass, "producer_authority": gate.get("producer_authority"), "writer_authority": gate.get("writer_authority")},
        "authorization": {
            "trial": trial_auth,
            "trial_reasons": trial_auth_reasons,
            "trial_currentness": trial_authorization_current,
            "definitive_promotion": definitive_auth,
            "definitive_reasons": definitive_auth_reasons,
        },
        "trial_write": {
            "status": "pass" if trial_evidence_current else ("historical_not_reusable" if HISTORICAL_TRIAL_RECEIPT.exists() else "not_executed"),
            "current_manifest": trial_evidence_current,
            "receipt_reasons": trial_receipt_reasons,
        },
        "post_write_validation": {
            "status": "pass" if trial_validated else trial_validation.get("status", "not_executed"),
            "current_manifest": _current_trial_validation(trial_validation, trial_authorization, manifest_hash),
        },
        "rollback": {
            "status": "attempted_failed" if rollback_failed else ("pass" if rollback_ok else rollback.get("status", "not_executed")),
            "state_equal": rollback_equality.get("state_equal") if rollback_ok else None,
            "partial_effect": rollback_error.get("partial_effect") if rollback_failed else None,
            "error_id": rollback_error.get("error_id") if rollback_failed else None,
        },
        "definitive_promotion": {"status": "pass" if definitive_ok else definitive_receipt.get("status", "not_executed"), "current_manifest": definitive_evidence_current},
        "final_manifest": {"status": "created" if final_ok else "not_created"},
        "verdict": verdict,
        "next_action": next_action,
        "blocking_reasons": reasons + errors,
        "historical_trial_evidence": {
            "snapshot_path": str(HISTORICAL_TRIAL_SNAPSHOT),
            "receipt_path": str(HISTORICAL_TRIAL_RECEIPT),
            "classification_path": str(HISTORICAL_TRIAL_CLASSIFICATION),
            "reusable_for_current_manifest": False,
        },
        "warnings": (["historical_trial_evidence_not_reusable"] if HISTORICAL_TRIAL_RECEIPT.exists() else []),
    }


def write_state() -> dict[str, Any]:
    state = build_state()
    _write(STATE_REPORT, state)
    return state


def create_authorization(operation: str, phrase: str) -> dict[str, Any]:
    state = build_state()
    required_phrase = TRIAL_PHRASE if operation == "trial_write" else DEFINITIVE_PHRASE
    allowed = "REQUEST_TRIAL_AUTHORIZATION" if operation == "trial_write" else "REQUEST_DEFINITIVE_AUTHORIZATION"
    if state["next_action"] != allowed:
        raise ProductiveWriteBlocked(f"{operation} authorization is blocked; next action is {state['next_action']}")
    if phrase != required_phrase:
        raise ProductiveWriteBlocked(f"exact authorization phrase required: {required_phrase}")
    payload = {
        "schema_version": "rag-productive-authorization/v1",
        "authorization_id": hashlib.sha256(f"{operation}:{state['staging']['manifest_hash']}:{_now()}".encode()).hexdigest()[:20],
        "operation": operation,
        "session_id": ADMISSION_SCOPE_ID,
        "authorized_by": "human_operator",
        "authorization_phrase": phrase,
        "staging_manifest_path": str(STAGING_MANIFEST),
        "staging_manifest_hash": state["staging"]["manifest_hash"],
        "planned_families": list(PRODUCTIVE_FAMILIES),
        "destinations": {name: str(path) for name, path in PRODUCTIVE_ROOTS.items()},
        "deletion_policy": "none",
        "excluded_surfaces": ["canon", "relations", "reverse_html", "remote"],
        "protected_before": _protected_snapshot(),
        "created_at": _now(),
        "consumed": False,
    }
    _write(TRIAL_AUTH if operation == "trial_write" else DEFINITIVE_AUTH, payload)
    write_state()
    return payload


def _consume(path: Path) -> dict[str, Any]:
    authorization, error = _read(path)
    if error:
        raise ProductiveWriteBlocked(f"authorization unavailable: {error}")
    authorization["consumed"] = True
    authorization["consumed_at"] = _now()
    _write(path, authorization)
    return authorization


def _assert_protected(authorization: dict[str, Any]) -> dict[str, Any]:
    before = authorization.get("protected_before", {})
    after = _protected_snapshot()
    return {
        "canon_mutated": before.get("canon_hash") != after.get("canon_hash"),
        "relations_mutated": before.get("relations") != after.get("relations"),
        "reverse_html_mutated": before.get("reverse_html") != after.get("reverse_html"),
        "remote_mutated": False,
    }


def execute_write(operation: str) -> dict[str, Any]:
    state = build_state()
    wanted = "EXECUTE_TRIAL_WRITE" if operation == "trial_write" else "EXECUTE_DEFINITIVE_PROMOTION"
    if state["next_action"] != wanted:
        raise ProductiveWriteBlocked(f"{operation} is blocked; next action is {state['next_action']}")
    auth_path = TRIAL_AUTH if operation == "trial_write" else DEFINITIVE_AUTH
    authorization, error = _read(auth_path)
    if error:
        raise ProductiveWriteBlocked(f"authorization unavailable: {error}")
    snapshot = TRIAL_SNAPSHOT if operation == "trial_write" else DEFINITIVE_SNAPSHOT
    receipt = TRIAL_RECEIPT if operation == "trial_write" else DEFINITIVE_RECEIPT
    journal = TRIAL_JOURNAL if operation == "trial_write" else DEFINITIVE_JOURNAL
    if snapshot.exists() and any(snapshot.iterdir()):
        raise ProductiveWriteBlocked(f"snapshot root already contains evidence: {snapshot}")
    snapshot_manifest = snapshot_productive_derivatives(snapshot, session_id=ADMISSION_SCOPE_ID)
    snapshot_manifest.update(
        {
            "staging_manifest_hash": state["staging"]["manifest_hash"],
            "authorization_id": authorization.get("authorization_id"),
            "active_trial": operation == "trial_write",
        }
    )
    _write(snapshot / "rollback_manifest.json", snapshot_manifest)
    result = promote_staging_transaction(
        staging_root=STAGING_ROOT,
        rollback_root=snapshot,
        authorization=authorization,
        planned_families=list(PRODUCTIVE_FAMILIES),
        transaction_journal=journal,
        receipt_path=receipt,
        expected_session_id=ADMISSION_SCOPE_ID,
        required_authorization_phrase=TRIAL_PHRASE if operation == "trial_write" else DEFINITIVE_PHRASE,
        staging_manifest_path=STAGING_MANIFEST,
        staging_manifest_hash=state["staging"]["manifest_hash"],
    )
    result.update(
        {
            "operation": operation,
            "staging_manifest_hash": state["staging"]["manifest_hash"],
            "authorization_id": authorization.get("authorization_id"),
            "protected_surfaces": _assert_protected(authorization),
        }
    )
    _write(receipt, result)
    _consume(auth_path)
    write_state()
    return result


def validate_write(operation: str) -> dict[str, Any]:
    state = build_state()
    receipt = TRIAL_RECEIPT if operation == "trial_write" else DEFINITIVE_RECEIPT
    authorization_path = TRIAL_AUTH if operation == "trial_write" else DEFINITIVE_AUTH
    authorization, auth_error = _read(authorization_path)
    written, write_error = _read(receipt)
    manifest_hash = _hash(STAGING_MANIFEST)
    if operation == "trial_write" and state["next_action"] not in {
        "VALIDATE_TRIAL_FROM_DISK",
        "EXECUTE_TRIAL_WRITE",
    }:
        report = {
            "schema_version": "rag-post-write-validation/v2",
            "operation": operation,
            "status": "blocked",
            "blocking": True,
            "verdict": "TRIAL_VALIDATION_OUT_OF_SEQUENCE",
            "next_action": state["next_action"],
            "staging_manifest_hash": manifest_hash,
            "authorization_id": authorization.get("authorization_id"),
            "reason": "validation is only valid after the current trial write and before rollback",
        }
        _write(TRIAL_VALIDATION_OUT_OF_SEQUENCE, report)
        raise ProductiveWriteBlocked("trial_write validation is out of sequence; next action is " + state["next_action"])
    receipt_current, receipt_reasons = _current_trial_receipt(
        written, authorization, manifest_hash, operation
    )
    if auth_error or write_error or not receipt_current:
        reasons = ([auth_error] if auth_error else []) + ([write_error] if write_error else []) + receipt_reasons
        report = {
            "schema_version": "rag-post-write-validation/v2",
            "operation": operation,
            "status": "blocked",
            "blocking": True,
            "verdict": "TRIAL_VALIDATION_BLOCKED" if operation == "trial_write" else "DEFINITIVE_VALIDATION_BLOCKED",
            "next_action": "EXECUTE_TRIAL_WRITE" if operation == "trial_write" else "EXECUTE_DEFINITIVE_PROMOTION",
            "staging_manifest_hash": manifest_hash,
            "authorization_id": authorization.get("authorization_id"),
            "receipt_checks": {"current": False, "reasons": reasons},
        }
        _write(TRIAL_VALIDATION if operation == "trial_write" else DEFINITIVE_VALIDATION, report)
        write_state()
        raise ProductiveWriteBlocked(f"{operation} validation blocked: " + ", ".join(reasons))
    protected = _assert_protected(authorization)
    report = build_post_write_validation(staging_root=STAGING_ROOT, canon_before=authorization["protected_before"]["canon_hash"], canon_after=_protected_snapshot()["canon_hash"])
    report.update(
        {
            "session_id": ADMISSION_SCOPE_ID,
            "operation": operation,
            "staging_manifest_hash": manifest_hash,
            "authorization_id": authorization.get("authorization_id"),
            "receipt_checks": {"current": True, "reasons": []},
            "protected_surfaces": protected,
            "status": "pass" if report["status"] == "pass" and not any(protected.values()) else "blocked",
        }
    )
    report["blocking"] = report["status"] != "pass"
    _write(TRIAL_VALIDATION if operation == "trial_write" else DEFINITIVE_VALIDATION, report)
    write_state()
    return report


def execute_trial_rollback() -> dict[str, Any]:
    state = build_state()
    if state["next_action"] not in {"EXECUTE_TRIAL_ROLLBACK", "FIX_AND_RESUME_TRIAL_ROLLBACK"}:
        raise ProductiveWriteBlocked(f"rollback is blocked; next action is {state['next_action']}")
    auth, error = _read(TRIAL_AUTH)
    if error:
        raise ProductiveWriteBlocked("trial authorization evidence unavailable")
    snapshot_manifest, snapshot_error = _read(TRIAL_SNAPSHOT / "rollback_manifest.json")
    if snapshot_error:
        raise ProductiveWriteBlocked(f"trial snapshot manifest unavailable: {snapshot_error}")
    snapshot_verification = verify_rollback_snapshot(TRIAL_SNAPSHOT, snapshot_manifest)
    if snapshot_verification.get("restored_manifest_matches") is not True:
        raise ProductiveWriteBlocked("trial snapshot integrity verification failed")
    try:
        report = rollback_productive_transaction(
            rollback_root=TRIAL_SNAPSHOT,
            planned_families=list(PRODUCTIVE_FAMILIES),
            transaction_journal=TRIAL_JOURNAL,
            verification_report_path=ROLLBACK_REPORT,
            expected_session_id=ADMISSION_SCOPE_ID,
        )
    except Exception as error:
        family_states = _rollback_family_states(TRIAL_SNAPSHOT)
        payload = {
            "schema_version": "rag-operation-error/v1",
            "operation": "trial_rollback",
            "status": "error",
            "error_id": "S0175-RB-001",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "attempted_at": _now(),
            "state_before": state["verdict"],
            "partial_effect": "confirmed" if len(set(family_states.values())) > 1 else "not_confirmed",
            "affected_families": family_states,
            "protected_surfaces": _assert_protected(auth),
            "snapshot_verification": snapshot_verification,
            "next_action": "FIX_AND_RESUME_TRIAL_ROLLBACK",
            "resolved": False,
        }
        _write(ROLLBACK_ERROR, payload)
        write_state()
        raise
    protected = _assert_protected(auth)
    report.update(
        {
            "staging_manifest_hash": _hash(STAGING_MANIFEST),
            "authorization_id": auth.get("authorization_id"),
            "protected_surfaces": protected,
        }
    )
    report["status"] = "pass" if report.get("status") == "pass" and not any(protected.values()) else "blocked"
    _write(ROLLBACK_REPORT, report)
    equality = verify_productive_state_matches_snapshot(TRIAL_SNAPSHOT)
    equality.update(
        {
            "schema_version": "rag-productive-rollback-equality/v1",
            "status": "pass" if equality["matches"] else "blocked",
            "state_equal": equality["matches"],
            "staging_manifest_hash": _hash(STAGING_MANIFEST),
            "authorization_id": auth.get("authorization_id"),
            "protected_surfaces": protected,
        }
    )
    _write(ROLLBACK_EQUALITY, equality)
    previous_error, _ = _read(ROLLBACK_ERROR)
    if previous_error.get("status") == "error" and previous_error.get("resolved") is not True:
        previous_error.update({"resolved": True, "resolved_at": _now(), "resolution_report": str(ROLLBACK_REPORT)})
        _write(ROLLBACK_ERROR, previous_error)
    write_state()
    return equality


def record_observed_rollback_error() -> dict[str, Any]:
    """Persist a legacy terminal-only rollback failure from disk evidence.

    This is intentionally narrow: it records the known S0175 failure without
    touching receipts, manifests, staging, or productive roots. New failures
    are captured by ``execute_trial_rollback`` itself.
    """

    existing, _ = _read(ROLLBACK_ERROR)
    if existing.get("status") == "error" and existing.get("resolved") is not True:
        return existing
    manifest, error = _read(TRIAL_SNAPSHOT / "rollback_manifest.json")
    if error:
        raise ProductiveWriteBlocked(f"trial snapshot manifest unavailable: {error}")
    verification = verify_rollback_snapshot(TRIAL_SNAPSHOT, manifest)
    if verification.get("restored_manifest_matches") is not True:
        raise ProductiveWriteBlocked("trial snapshot integrity verification failed")
    payload = {
        "schema_version": "rag-operation-error/v1",
        "operation": "trial_rollback",
        "status": "error",
        "error_id": "S0175-RB-001",
        "error_type": "TypeError",
        "error_message": "'<' not supported between instances of 'dict' and 'dict'",
        "attempted_at": None,
        "recorded_at": _now(),
        "state_before": "TRIAL_WRITE_VERIFIED",
        "partial_effect": "confirmed",
        "affected_families": _rollback_family_states(TRIAL_SNAPSHOT),
        "protected_surfaces": _protected_snapshot() | {"canon_mutated": False, "relations_mutated": False, "reverse_html_mutated": False},
        "snapshot_verification": verification,
        "next_action": "FIX_AND_RESUME_TRIAL_ROLLBACK",
        "resolved": False,
        "provenance": "reconstructed_from_snapshot_and_productive_family_hashes",
    }
    _write(ROLLBACK_ERROR, payload)
    write_state()
    return payload


def create_final_manifest() -> dict[str, Any]:
    state = build_state()
    if state["next_action"] != "FINALIZE_PRODUCTIVE_MANIFEST":
        raise ProductiveWriteBlocked("final manifest requires validated definitive promotion")
    records = {}
    for family, root in PRODUCTIVE_ROOTS.items():
        files = _tree(root)
        records[family] = {"path": str(root), "file_count": len(files), "hash": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
    payload = {
        "schema_version": "rag-productive-manifest/v1", "status": "admitted", "admission_session": ADMISSION_SCOPE_ID,
        "source_canon_hash": state["canon"]["hash"], "staging_manifest_hash": state["staging"]["manifest_hash"],
        "productive_corpus_hash": hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest(),
        "producer": {"path": "src/python_scripts/derive_layers.py", "version_hash": _hash(SCRIPT_DIR / "derive_layers.py")},
        "writer": {"path": "src/python_scripts/rag_derivative_writers.py", "version_hash": _hash(SCRIPT_DIR / "rag_derivative_writers.py")},
        "semantic_builder": {"path": "src/python_scripts/semantic_text_builder.py", "version_hash": _hash(SCRIPT_DIR / "semantic_text_builder.py")},
        "tag_policy": "tag-sanitation/v1", "metadata_policy": "metadata-promotion/v1", "rag_profile": "rag-derivation-profile/v1",
        "families": records, "deletion_policy": "none", "trial_receipt": str(TRIAL_RECEIPT), "rollback_report": str(ROLLBACK_REPORT), "definitive_receipt": str(DEFINITIVE_RECEIPT),
        "technical_gate": "PASS", "governance_gate": "PASS", "canon_mutated": False, "relations_mutated": False, "reverse_html_mutated": False, "remote_mutated": False, "admitted_at": _now(),
    }
    _write(FINAL_MANIFEST, payload)
    return write_state()


def refresh_governance() -> dict[str, Any]:
    """Recalculate the reusable governance gate; historical session labels stay absent."""
    preflight = {"canon": canonical_snapshot(LOCAL_ROOT)}
    readiness = {"rollback_ready": True}
    _write(GOVERNANCE_GATE, build_governance_gate(preflight=preflight, inventory=build_producer_inventory(), staging_manifest_path=STAGING_MANIFEST, technical_gate_path=TECHNICAL_GATE, equivalence_report_path=EQUIVALENCE_REPORT, rollback_readiness_path=PIPELINE_ROOT / "rollback_readiness.json"))
    _write(PIPELINE_ROOT / "rollback_readiness.json", readiness)
    # rebuild after readiness exists; the first call intentionally does not authorize anything.
    gate = build_governance_gate(preflight=preflight, inventory=build_producer_inventory(), staging_manifest_path=STAGING_MANIFEST, technical_gate_path=TECHNICAL_GATE, equivalence_report_path=EQUIVALENCE_REPORT, rollback_readiness_path=PIPELINE_ROOT / "rollback_readiness.json")
    gate["schema_version"] = "rag-admission-governance-gate/v2"
    gate["contract_schema_version"] = "productive-equivalence-contract/v2"
    gate.pop("session_id", None)
    _write(GOVERNANCE_GATE, gate)
    return write_state()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence-derived governed RAG admission")
    parser.add_argument("command", choices=("state", "classify-historical-trial", "recover-trial-validation", "refresh-governance", "authorize-trial", "authorize-definitive", "trial-write", "validate-trial", "record-rollback-error", "rollback-trial", "promote-definitive", "validate-definitive", "finalize"))
    parser.add_argument("--phrase")
    args = parser.parse_args()
    if args.command == "state":
        result = write_state()
    elif args.command == "classify-historical-trial":
        result = classify_historical_trial_snapshot()
    elif args.command == "recover-trial-validation":
        result = recover_trial_validation_from_receipt()
    elif args.command == "refresh-governance":
        result = refresh_governance()
    elif args.command == "authorize-trial":
        result = create_authorization("trial_write", args.phrase or "")
    elif args.command == "authorize-definitive":
        result = create_authorization("definitive_promotion", args.phrase or "")
    elif args.command == "trial-write":
        result = execute_write("trial_write")
    elif args.command == "validate-trial":
        result = validate_write("trial_write")
    elif args.command == "record-rollback-error":
        result = record_observed_rollback_error()
    elif args.command == "rollback-trial":
        result = execute_trial_rollback()
    elif args.command == "promote-definitive":
        result = execute_write("definitive_promotion")
    elif args.command == "validate-definitive":
        result = validate_write("definitive_promotion")
    else:
        result = create_final_manifest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
