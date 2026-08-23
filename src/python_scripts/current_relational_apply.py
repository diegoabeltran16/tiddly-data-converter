#!/usr/bin/env python3
"""Authorization boundary for the current relational bundle.

This module deliberately separates authorization from the later apply.  It is
also the only menu-facing consumer of the current-authority resolver.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import relation_admission_gate as admission_gate
from current_relational_authority import CurrentRelationalAuthorityError, resolve_current_relational_authority, sha256_file


SCHEMA = "current-relational-authorization/v1"


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def authorization_path(local_root: Path, readiness_id: str) -> Path:
    return local_root / "audit" / "relation_admission" / "authorizations" / readiness_id / "authorization.json"


def preflight(local_root: Path) -> dict[str, Any]:
    authority = resolve_current_relational_authority(local_root)
    if authority["terminal_state"] != "READY_FOR_AUTHORIZATION":
        if authority["terminal_state"] == "READY_FOR_HUMAN_DELTA_REVIEW":
            raise CurrentRelationalAuthorityError(
                "current_bundle_human_delta_pending", "awaiting_human_review",
            )
        raise CurrentRelationalAuthorityError("authorization_not_current")
    artifacts = authority["artifacts"]
    plan = json.loads(artifacts["apply_plan"].read_text())
    gate = json.loads(artifacts["gate_g"].read_text())
    if gate.get("ready") is not True or gate.get("apply_plan_hash") != sha256_file(artifacts["apply_plan"]):
        raise CurrentRelationalAuthorityError("readiness_identity_mismatch")
    if plan.get("canon_before_hash") != admission_gate.aggregate_canon_hash(
        str(local_root / "tiddlers_*.jsonl")
    ) or int(plan.get("canon_before_count") or -1) != admission_gate.count_canon_records(
        str(local_root / "tiddlers_*.jsonl")
    ):
        raise CurrentRelationalAuthorityError("current_bundle_canon_stale")
    if plan.get("payload_candidates_path") != "ready_for_human_review.jsonl" or (
        plan.get("payload_candidates_hash") != sha256_file(artifacts["ready_queue"])
    ):
        raise CurrentRelationalAuthorityError("apply_plan_payload_mismatch")
    auth_path = authorization_path(local_root, str(authority["readiness_id"]))
    authorization: dict[str, Any] | None = None
    if auth_path.is_file():
        authorization = json.loads(auth_path.read_text())
        required = {
            "readiness_id": authority["readiness_id"],
            "bundle_manifest_hash": authority["bundle_manifest_hash"],
            "apply_plan_hash": sha256_file(artifacts["apply_plan"]),
            "gate_g_hash": sha256_file(artifacts["gate_g"]),
            "decision_checkpoint_hash": sha256_file(artifacts["decision_checkpoint"]),
            "rollback_snapshot_hash": sha256_file(artifacts["rollback_snapshot"]),
        }
        if authorization.get("schema_version") != SCHEMA or authorization.get("consumed") is not False or any(authorization.get(k) != v for k, v in required.items()):
            raise CurrentRelationalAuthorityError("authorization_not_current")
    return {"authority": authority, "plan": plan, "authorization_path": auth_path, "authorization": authorization}


def authorize(local_root: Path, reviewer: str, confirmation: str) -> dict[str, Any]:
    result = preflight(local_root)
    if result["authorization"] is not None:
        raise CurrentRelationalAuthorityError("authorization_not_current")
    authority, plan, path = result["authority"], result["plan"], result["authorization_path"]
    expected = f"AUTHORIZE CURRENT RELATIONAL APPLY {authority['readiness_id']}"
    if not reviewer.strip() or confirmation != expected:
        raise CurrentRelationalAuthorityError("authorization_confirmation_invalid")
    material = {"readiness_id": authority["readiness_id"], "bundle_manifest_hash": authority["bundle_manifest_hash"], "reviewer_identity": reviewer.strip()}
    authorization = {
        "schema_version": SCHEMA,
        "authorization_id": "cra_" + hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:24],
        "reviewer_identity": reviewer.strip(),
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "canon_generation_id": authority["canon_generation_id"],
        "relation_generation_id": authority["relation_generation_id"],
        "review_state_id": authority["review_state_id"],
        "readiness_id": authority["readiness_id"],
        "bundle_manifest_hash": authority["bundle_manifest_hash"],
        "gate_g_hash": sha256_file(authority["artifacts"]["gate_g"]),
        "apply_plan_hash": sha256_file(authority["artifacts"]["apply_plan"]),
        "decision_checkpoint_hash": sha256_file(authority["artifacts"]["decision_checkpoint"]),
        "rollback_snapshot_hash": sha256_file(authority["artifacts"]["rollback_snapshot"]),
        "required_confirmation": expected,
        "apply_confirmation": "CONFIRM APPLY CURRENT RELATIONS <authorization_id>",
        "consumed": False,
        "planned_unique_relations": plan["planned_unique_relations"],
    }
    _write(path, authorization)
    return authorization


def _validate_plan_against_bundle(result: dict[str, Any]) -> None:
    """Prove the sealed plan still equals a fresh read of its sealed inputs."""
    authority, plan = result["authority"], result["plan"]
    artifacts = authority["artifacts"]
    decisions, errors = admission_gate.load_persistent_human_review_decisions(
        artifacts["effective_decisions"]
    )
    if errors:
        raise CurrentRelationalAuthorityError("effective_decisions_invalid")
    observed = admission_gate.build_apply_plan(
        candidates=admission_gate.load_jsonl(artifacts["ready_queue"]),
        canon_glob=str(authority["pointer_path"].parents[2] / "tiddlers_*.jsonl"),
        human_review_decisions=decisions,
        dry_run_report=admission_gate.load_dry_run_report(artifacts["admission_gate"]),
        dry_run_report_path=artifacts["admission_gate"],
        dry_run_recent=True,
        binding_paths={
            "candidate_manifest": artifacts["candidate_manifest"],
            "validation_report": artifacts["validation_report"],
            "reconciliation_manifest": artifacts["reconciliation_manifest"],
            "reviewable_manifest": artifacts["reviewable_manifest"],
            "human_review_decisions": artifacts["effective_decisions"],
        },
    )
    fields = (
        "candidate_count", "approved_count", "blocked_count", "would_apply_count",
        "would_apply_candidate_ids", "omitted_planned_count",
        "omitted_planned_candidate_ids", "canon_before_count", "canon_before_hash",
    )
    sealed_binding_hashes = {
        name: (binding or {}).get("sha256")
        for name, binding in sorted(
            (plan.get("exact_bindings") or {}).items()
        )
    }
    observed_binding_hashes = {
        name: (binding or {}).get("sha256")
        for name, binding in sorted(
            (observed.get("exact_bindings") or {}).items()
        )
    }
    if (
        any(plan.get(field) != observed.get(field) for field in fields)
        or observed.get("block_reasons")
        or plan.get("apply_plan_id")
        != admission_gate.semantic_apply_plan_id(observed)
        or plan.get("apply_plan_id")
        != admission_gate.semantic_apply_plan_id(plan)
        or sealed_binding_hashes != observed_binding_hashes
    ):
        raise CurrentRelationalAuthorityError("sealed_apply_plan_drift")


def apply(local_root: Path, authorization_id: str, confirmation: str) -> dict[str, Any]:
    """Execute only a still-current, single-use authorization and sealed plan."""
    result = preflight(local_root)
    authorization = result["authorization"]
    if authorization is None or authorization.get("authorization_id") != authorization_id:
        raise CurrentRelationalAuthorityError("authorization_not_current")
    expected = f"CONFIRM APPLY CURRENT RELATIONS {authorization_id}"
    if confirmation != expected:
        raise CurrentRelationalAuthorityError("apply_confirmation_invalid")
    _validate_plan_against_bundle(result)
    authority = result["authority"]
    receipt_dir = (
        local_root / "audit" / "relation_admission" / "apply_receipts"
        / str(authority["readiness_id"]) / authorization_id
    )
    code, report = admission_gate.guarded_apply_relations(
        candidates_file=authority["artifacts"]["ready_queue"],
        canon_glob=str(local_root / "tiddlers_*.jsonl"),
        human_review_decisions_file=authority["artifacts"]["effective_decisions"],
        dry_run_report_path=authority["artifacts"]["admission_gate"],
        out_dir=receipt_dir,
        terminal_confirmation=admission_gate.APPLY_CONFIRMATION,
        perform_write=True,
        target_scope="current_relational_bundle",
        binding_paths={
            "candidate_manifest": authority["artifacts"]["candidate_manifest"],
            "validation_report": authority["artifacts"]["validation_report"],
            "reconciliation_manifest": authority["artifacts"]["reconciliation_manifest"],
            "reviewable_manifest": authority["artifacts"]["reviewable_manifest"],
            "human_review_decisions": authority["artifacts"]["effective_decisions"],
        },
        prevalidated_plan_path=authority["artifacts"]["apply_plan"],
    )
    if code != 0:
        raise CurrentRelationalAuthorityError("sealed_apply_execution_blocked")
    receipt_path = receipt_dir / "relation_apply_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.update({
        "current_relational_authorization_id": authorization_id,
        "readiness_id": authority["readiness_id"],
        "bundle_manifest_hash": authority["bundle_manifest_hash"],
        "sealed_apply_plan_hash": sha256_file(authority["artifacts"]["apply_plan"]),
    })
    _write(receipt_path, receipt)
    authorization.update({
        "consumed": True,
        "consumed_at": datetime.now(timezone.utc).isoformat(),
        "consumption_state": "consumed",
        "receipt_path": str(receipt_path),
        "receipt_hash": sha256_file(receipt_path),
        "canon_modified": report.get("canon_modified") is True,
        "relations_written": report.get("applied_count", 0),
    })
    _write(result["authorization_path"], authorization)

    # Publish the successful immutable generational apply as the operational
    # current projection. The authoritative evidence remains under
    # apply_receipts/<readiness>/<authorization>/.
    current_audit_dir = local_root / "audit" / "relation_admission" / "current"
    _write(current_audit_dir / "relation_apply_report.json", report)
    _write(current_audit_dir / "relation_apply_receipt.json", receipt)

    return report | {"authorization_id": authorization_id, "receipt_path": str(receipt_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "authorize", "apply"))
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--authorization-id", default="")
    args = parser.parse_args()
    try:
        value: Any = (
            preflight(args.local_root) if args.command == "preflight"
            else authorize(args.local_root, args.reviewer, args.confirmation)
            if args.command == "authorize"
            else apply(args.local_root, args.authorization_id, args.confirmation)
        )
        if args.command == "preflight":
            value = {
    "allowed": True,
    "authorization_present": value["authorization"] is not None,
    "readiness_id": value["authority"]["readiness_id"],
    "plan": value["plan"],
    "authorization": value["authorization"],
}
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return 0
    except CurrentRelationalAuthorityError as error:
        print(json.dumps({"allowed": False, "reason_codes": error.reason_codes}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
