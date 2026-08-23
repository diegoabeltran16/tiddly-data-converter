#!/usr/bin/env python3
"""Read-only assembler for the live relational admission state.

The assembler owns no generation, reconciliation, review, gate, apply, or
rollback behavior.  It validates bindings between their durable artifacts and
the runtime canon, then emits one operator-facing state and next action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
LOCAL_ROOT = REPO_ROOT / "data" / "out" / "local"
CURRENT_DIR = LOCAL_ROOT / "pipeline" / "relation_candidates" / "current"
AUDIT_DIR = LOCAL_ROOT / "audit" / "relation_admission" / "current"
S0180_AUDIT = LOCAL_ROOT / "audit" / "s0180"
BASELINE = S0180_AUDIT / "pre_relational_rag_baseline_manifest.json"
STATE_REPORT = AUDIT_DIR / "relational_operational_state.json"
AUDIT_INDEX = AUDIT_DIR / "relational_audit_index.json"
RECORD_CURRENT_HUMAN_RELATIONAL_DECISIONS = "RECORD_CURRENT_HUMAN_RELATIONAL_DECISIONS"
SUPERSEDE_LEGACY_HUMAN_RELATIONAL_DECISIONS = "SUPERSEDE_LEGACY_HUMAN_RELATIONAL_DECISIONS"
CURRENT_RELATIONAL_AUTHORITY_MISSING_FOR_CURRENT_CANON = (
    "CURRENT_RELATIONAL_AUTHORITY_MISSING_FOR_CURRENT_CANON"
)
PREPARE_CURRENT_RELATIONAL_GENERATION = "PREPARE_CURRENT_RELATIONAL_GENERATION"
CURRENT_CANON_AUTHORITY_REASONS = frozenset({
    "current_bundle_canon_stale",
    "current_bundle_missing",
})


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, "missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, f"invalid:{error}"
    return (value, None) if isinstance(value, dict) else ({}, "invalid:object_required")


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not path.exists():
        return [], "missing"
    rows: list[dict[str, Any]] = []
    try:
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                return [], f"invalid:line_{line_no}_object_required"
            rows.append(value)
    except (OSError, json.JSONDecodeError) as error:
        return [], f"invalid:{error}"
    return rows, None


def write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def display(path: Path, repo_root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def canon_snapshot(local_root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    records = 0
    shards = sorted(local_root.glob("tiddlers_*.jsonl"))
    for shard in shards:
        data = shard.read_bytes()
        digest.update(data)
        records += sum(1 for line in data.splitlines() if line.strip())
    return {"hash": digest.hexdigest(), "records": records, "shards": len(shards), "current": True}


def count_decisions(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("human_review_decision") or row.get("decision") or "unknown") for row in rows)
    return {
        "total": len(rows),
        "approved": counts.get("approved_for_admission", 0),
        "rejected": counts.get("rejected", 0),
        "deferred": counts.get("deferred", 0),
    }


def canonical_relation_v1_count(local_root: Path) -> int:
    total = 0
    for shard in sorted(local_root.glob("tiddlers_*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            for relation in row.get("relations") or []:
                if isinstance(relation, dict) and (
                    relation.get("relation_schema_version")
                    or relation.get("schema_version")
                    or relation.get("relation_schema")
                ) == "canonical-relation/v1":
                    total += 1
    return total


def build_state(
    local_root: Path = LOCAL_ROOT,
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    audit_dir = local_root / "audit" / "relation_admission" / "current"
    s0180_audit = local_root / "audit" / "s0180"
    baseline_path = s0180_audit / "pre_relational_rag_baseline_manifest.json"
    candidate_manifest_path = current_dir / "current_candidate_manifest.json"
    validation_path = current_dir / "validation_report.json"
    reconciliation_path = current_dir / "reconciliation_manifest.json"
    reviewable_path = current_dir / "reviewable_candidate_manifest.json"
    decisions_path = current_dir / "human_review_decisions.jsonl"
    gate_path = audit_dir / "admission_gate_dry_run.json"
    run_manifest_path = audit_dir / "current_run_manifest.json"
    apply_path = audit_dir / "relation_apply_report.json"
    apply_receipt_path = audit_dir / "relation_apply_receipt.json"
    s0183_dir = local_root / "audit" / "s0183" / "current"
    cross_batch_path = s0183_dir / "cross_batch_reconciliation_manifest.json"
    preservation_path = s0183_dir / "human_decision_preservation_manifest.json"
    gate_g_path = local_root / "audit" / "s0183" / "gate-g" / "gate_g_readiness.json"
    authorization_path = local_root / "audit" / "s0183" / "gate-g" / "gate_g_authorization.json"
    productive_reconciliation_path = (
        local_root / "audit" / "s0183" / "reconciliation"
        / "productive_apply_reconciliation.json"
    )
    authorization_reconciliation_path = (
        local_root / "audit" / "s0183" / "reconciliation"
        / "authorization_consumption_reconciliation.json"
    )

    canon = canon_snapshot(local_root)
    baseline, baseline_error = read_json(baseline_path)
    candidate, candidate_error = read_json(candidate_manifest_path)
    validation, validation_error = read_json(validation_path)
    reconciliation, reconciliation_error = read_json(reconciliation_path)
    reviewable, reviewable_error = read_json(reviewable_path)
    decisions, decisions_error = read_jsonl(decisions_path)
    gate, gate_error = read_json(gate_path)
    run_manifest, run_manifest_error = read_json(run_manifest_path)
    apply_report, apply_error = read_json(apply_path)
    apply_receipt, apply_receipt_error = read_json(apply_receipt_path)
    cross_batch, cross_batch_error = read_json(cross_batch_path)
    preservation, preservation_error = read_json(preservation_path)
    gate_g, gate_g_error = read_json(gate_g_path)
    authorization, authorization_error = read_json(authorization_path)
    productive_reconciliation, productive_reconciliation_error = read_json(
        productive_reconciliation_path,
    )
    authorization_reconciliation, authorization_reconciliation_error = read_json(
        authorization_reconciliation_path,
    )
    try:
        from prepare_current_relational_generation import (
            Paths as CurrentGenerationPaths,
            inspect_review_coverage,
            read_current_bundle_status,
        )

        current_bundle = read_current_bundle_status(local_root)
        review_coverage = inspect_review_coverage(
            CurrentGenerationPaths.from_local_root(local_root)
        )
    except (ImportError, OSError, ValueError) as error:
        current_bundle = {
            "valid": False,
            "reason_codes": ["current_bundle_status_failed"],
            "error": str(error),
        }
        review_coverage = {
            "valid": False,
            "technical_reviewable": None,
            "effective_decision_covered": None,
            "effective_pending": None,
            "coverage_source": None,
        }

    generator = REPO_ROOT / "src" / "python_scripts" / "generate_technical_relation_candidates.py"
    contract = REPO_ROOT / "src" / "python_scripts" / "relation_candidate_contract.py"
    policy = REPO_ROOT / "src" / "python_scripts" / "relation_admission_policy.py"
    reconciler = REPO_ROOT / "src" / "python_scripts" / "reconcile_current_relation_candidates.py"
    candidate_manifest_hash = sha256_file(candidate_manifest_path)
    reconciliation_hash = sha256_file(reconciliation_path)
    reviewable_hash = sha256_file(reviewable_path)

    candidate_reasons: list[str] = []
    if candidate_error:
        candidate_reasons.append(f"candidate_manifest_{candidate_error}")
    else:
        binding = candidate.get("canon_binding") or {}
        producer = candidate.get("producer") or {}
        if binding.get("canon_hash") != canon["hash"]:
            candidate_reasons.append("stale_canon_changed")
        if producer.get("hash") != sha256_file(generator):
            candidate_reasons.append("stale_candidate_generator_changed")
        if producer.get("contract_hash") != sha256_file(contract):
            candidate_reasons.append("stale_candidate_contract_changed")
        batch = candidate.get("candidate_batch") or {}
        batch_path = current_dir / "relation_candidates.jsonl"
        if batch.get("hash") != sha256_file(batch_path):
            candidate_reasons.append("stale_candidate_batch_changed")

    reconciliation_reasons: list[str] = []
    if reconciliation_error:
        reconciliation_reasons.append(f"reconciliation_manifest_{reconciliation_error}")
    else:
        if reconciliation.get("candidate_manifest_hash") != candidate_manifest_hash:
            reconciliation_reasons.append("stale_candidate_manifest_changed")
        if reconciliation.get("canon_hash") != canon["hash"]:
            reconciliation_reasons.append("stale_canon_changed")
        if reconciliation.get("predicate_policy_hash") != sha256_file(policy):
            reconciliation_reasons.append("stale_predicate_policy_changed")
        if reconciliation.get("candidate_contract_hash") != sha256_file(contract):
            reconciliation_reasons.append("stale_candidate_contract_changed")
        if reconciliation.get("reconciler_hash") != sha256_file(reconciler):
            reconciliation_reasons.append("stale_reconciler_changed")

    reviewable_reasons: list[str] = []
    if reviewable_error:
        reviewable_reasons.append(f"reviewable_manifest_{reviewable_error}")
    else:
        if reviewable.get("canon_hash") != canon["hash"]:
            reviewable_reasons.append("stale_canon_changed")
        if reviewable.get("candidate_manifest_hash") != candidate_manifest_hash:
            reviewable_reasons.append("stale_candidate_manifest_changed")
        if reviewable.get("reconciliation_manifest_hash") != reconciliation_hash:
            reviewable_reasons.append("stale_reconciliation_manifest_changed")
        if reviewable.get("predicate_policy_hash") != sha256_file(policy):
            reviewable_reasons.append("stale_predicate_policy_changed")

    validation_summary = validation.get("summary") or {}
    reconciliation_counts = reconciliation.get("dispositions") or {}
    ready_count = int(reconciliation_counts.get("ready_for_review") or 0)
    blocked_count = max(0, int(reconciliation.get("total") or 0) - ready_count)
    legacy_decisions = [row for row in decisions if row.get("schema_version") == "relation-human-review-decision/v1"]
    official_decisions = [row for row in decisions if row.get("schema_version") == "relation-human-review-decision/v2"]
    decision_counts = count_decisions(official_decisions)
    decision_stale = bool(official_decisions and (candidate_reasons or reconciliation_reasons or reviewable_reasons))
    gate_summary = gate.get("summary") or {}
    gate_items = gate.get("items") or []
    gate_decisions = Counter(str(item.get("decision") or "unknown") for item in gate_items if isinstance(item, dict))
    gate_reasons: list[str] = []
    if gate_error:
        gate_reasons.append(f"admission_gate_report_{gate_error}")
    if run_manifest_error:
        gate_reasons.append(f"current_run_manifest_{run_manifest_error}")
    log_path = audit_dir / "current_relation_admission_log.jsonl"
    if not gate_error and run_manifest.get("report_hash") != sha256_file(gate_path):
        gate_reasons.append("current_run_manifest_report_hash_mismatch")
    if not run_manifest_error and run_manifest.get("log_hash") != sha256_file(log_path):
        gate_reasons.append("current_run_manifest_log_hash_mismatch")
    if not run_manifest_error and run_manifest.get("human_review_decisions_hash") != sha256_file(decisions_path):
        gate_reasons.append("current_run_manifest_human_review_decisions_hash_mismatch")
    if (
        not run_manifest_error
        and "reconciliation_manifest_hash" in run_manifest
        and run_manifest.get("reconciliation_manifest_hash") != reconciliation_hash
    ):
        gate_reasons.append("current_run_manifest_reconciliation_manifest_hash_mismatch")
    gate_contract = REPO_ROOT / "src" / "python_scripts" / "relation_admission_gate.py"
    if not run_manifest_error and run_manifest.get("gate_contract_hash") != sha256_file(gate_contract):
        gate_reasons.append("current_run_manifest_gate_contract_hash_mismatch")
    gate_current = bool(
        not gate_reasons
        and run_manifest.get("canon_hash") == canon["hash"]
        and run_manifest.get("candidate_manifest_hash") == candidate_manifest_hash
        and run_manifest.get("reviewable_manifest_hash") == reviewable_hash
    )
    evaluated = int(gate_summary.get("evaluated", gate_summary.get("total_evaluated", 0)) or 0)
    partition_total = sum(
        int(gate_summary.get(name) or 0)
        for name in ("approved_for_admission", "human_deferred", "human_rejected", "awaiting_human_review")
    )
    partition_complete = evaluated == partition_total
    if gate_current and not partition_complete:
        gate_reasons.append("gate_human_partition_incomplete")
        gate_current = False

    s0183_reasons: list[str] = []
    if cross_batch_path.exists() or preservation_path.exists():
        if cross_batch_error:
            s0183_reasons.append(f"cross_batch_manifest_{cross_batch_error}")
        else:
            if cross_batch.get("current_candidates_hash") != sha256_file(current_dir / "relation_candidates.jsonl"):
                s0183_reasons.append("cross_batch_current_candidates_hash_mismatch")
            for key, filename in (
                ("old_to_current_hash", "old_to_current_reconciliation.jsonl"),
                ("current_to_old_hash", "current_to_old_reconciliation.jsonl"),
            ):
                if cross_batch.get(key) != sha256_file(s0183_dir / filename):
                    s0183_reasons.append(f"cross_batch_{key}_mismatch")
            if cross_batch.get("coverage_complete") is not True:
                s0183_reasons.append("cross_batch_coverage_incomplete")
        if preservation_error:
            s0183_reasons.append(f"decision_preservation_manifest_{preservation_error}")
        else:
            if preservation.get("current_decisions_hash") != sha256_file(decisions_path):
                s0183_reasons.append("decision_preservation_current_hash_mismatch")
            if preservation.get("cross_batch_manifest_hash") != sha256_file(cross_batch_path):
                s0183_reasons.append("decision_preservation_cross_batch_hash_mismatch")
            if preservation.get("pending_reviewable_candidate_ids"):
                s0183_reasons.append("decision_preservation_pending_human_review")

    gate_g_reasons: list[str] = []
    snapshot_path = Path(str(gate_g.get("snapshot_path") or ""))
    plan_path = Path(str(gate_g.get("apply_plan_path") or ""))
    safety_path = Path(str(gate_g.get("safety_verification_report_path") or ""))
    productive_apply_current = bool(
        not apply_error
        and apply_report.get("status") == "applied"
        and apply_report.get("canon_after_hash") == canon["hash"]
    )

    current_apply_receipt_bound = bool(
        productive_apply_current
        and not apply_receipt_error
        and apply_receipt.get("status") == "applied"
        and apply_receipt.get("apply_id") == apply_report.get("apply_id")
        and apply_receipt.get("canon_after_hash") == canon["hash"]
        and apply_receipt.get("rollback_snapshot")
        == apply_report.get("rollback_snapshot")
        and apply_receipt.get("rollback_snapshot_hash")
        == apply_report.get("rollback_snapshot_hash")
    )

    current_apply_readiness_id = str(
        apply_receipt.get("readiness_id") or ""
    )
    current_apply_authorization_id = str(
        apply_receipt.get("current_relational_authorization_id") or ""
    )
    current_apply_authorization_path = (
        local_root / "audit" / "relation_admission" / "authorizations"
        / current_apply_readiness_id / "authorization.json"
        if current_apply_readiness_id else Path()
    )
    current_apply_authorization, current_apply_authorization_error = (
        read_json(current_apply_authorization_path)
        if current_apply_readiness_id else ({}, "missing")
    )

    current_generational_apply_reconciled = bool(
        current_apply_receipt_bound
        and current_apply_authorization_id
        and not current_apply_authorization_error
        and current_apply_authorization.get("schema_version")
        == "current-relational-authorization/v1"
        and current_apply_authorization.get("authorization_id")
        == current_apply_authorization_id
        and current_apply_authorization.get("readiness_id")
        == current_apply_readiness_id
        and current_apply_authorization.get("bundle_manifest_hash")
        == apply_receipt.get("bundle_manifest_hash")
        and current_apply_authorization.get("apply_plan_hash")
        == apply_receipt.get("sealed_apply_plan_hash")
        and current_apply_authorization.get("consumed") is True
        and current_apply_authorization.get("receipt_hash")
        == sha256_file(apply_receipt_path)
        and current_apply_authorization.get("relations_written") is not None
        and apply_receipt.get("applied_count") is not None
        and int(current_apply_authorization.get("relations_written"))
        == int(apply_receipt.get("applied_count"))
    )

    legacy_productive_apply_reconciled = bool(
        productive_apply_current
        and not productive_reconciliation_error
        and productive_reconciliation.get("status") == "reconciled"
        and (productive_reconciliation.get("canon") or {}).get("post_hash")
        == canon["hash"]
    )
    productive_apply_reconciled = bool(
        current_generational_apply_reconciled
        or legacy_productive_apply_reconciled
    )
    if gate_g_path.exists() and not productive_apply_current:
        if gate_g_error:
            gate_g_reasons.append(f"gate_g_readiness_{gate_g_error}")
        else:
            if gate_g.get("canon_hash") != canon["hash"]:
                gate_g_reasons.append("gate_g_canon_hash_mismatch")
            if gate_g.get("apply_authorized") is not False or gate_g.get("apply_executed") is not False:
                gate_g_reasons.append("gate_g_must_remain_unauthorized_and_unexecuted")
            if gate_g.get("apply_plan_hash") != sha256_file(plan_path):
                gate_g_reasons.append("gate_g_apply_plan_hash_mismatch")
            if gate_g.get("snapshot_hash") != sha256_file(snapshot_path):
                gate_g_reasons.append("gate_g_snapshot_hash_mismatch")
            if gate_g.get("safety_verification_report_hash") != sha256_file(safety_path):
                gate_g_reasons.append("gate_g_safety_report_hash_mismatch")
            snapshot, snapshot_error = read_json(snapshot_path)
            if snapshot_error or snapshot.get("canon_before_hash") != canon["hash"]:
                gate_g_reasons.append("gate_g_snapshot_not_bound_to_current_canon")
            safety, safety_error = read_json(safety_path)
            if safety_error or safety.get("passed") is not True or safety.get("production_canon_unchanged") is not True:
                gate_g_reasons.append("gate_g_safety_verification_not_passed")
    gate_g_current = bool(
        gate_g_path.exists() and not gate_g_reasons and not productive_apply_current
    )

    preapply_stale_reasons = (
        candidate_reasons + reconciliation_reasons + reviewable_reasons
        + s0183_reasons + gate_g_reasons
    )
    current_bundle_valid = current_bundle.get("valid") is True
    current_bundle_terminal = str(current_bundle.get("terminal_state") or "")
    current_bundle_human = bool(
        current_bundle_valid
        and current_bundle_terminal == "READY_FOR_HUMAN_DELTA_REVIEW"
    )
    current_bundle_authorization = bool(
        current_bundle_valid
        and current_bundle_terminal == "READY_FOR_AUTHORIZATION"
    )
    current_bundle_pending = int(
        (current_bundle.get("planning") or {}).get("pending_human_review") or 0
    )
    current_bundle_reasons = sorted(set(current_bundle.get("reason_codes") or []))
    authority_missing_for_current_canon = bool(
        not current_bundle_valid
        and current_bundle_reasons
        and set(current_bundle_reasons).issubset(CURRENT_CANON_AUTHORITY_REASONS)
        and not candidate_reasons
        and not reconciliation_reasons
        and not reviewable_reasons
    )
    current_planning = current_bundle.get("planning") or {}
    technical_reviewable = current_planning.get("technical_reviewable")
    effective_decision_covered = current_planning.get(
        "effective_decision_covered"
    )
    effective_pending: int | None = current_planning.get("effective_pending")
    if current_bundle_valid:
        technical_reviewable = (
            ready_count if technical_reviewable is None else technical_reviewable
        )
        effective_pending = (
            current_bundle_pending
            if current_bundle_terminal in {
                "READY_FOR_HUMAN_DELTA_REVIEW",
                "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION",
            }
            else 0 if current_bundle_terminal == "READY_FOR_AUTHORIZATION" else None
        )
    elif review_coverage.get("valid") is True:
        technical_reviewable = review_coverage.get("technical_reviewable")
        effective_decision_covered = review_coverage.get(
            "effective_decision_covered"
        )
        effective_pending = review_coverage.get("effective_pending")
    historical_stale_reasons = sorted(set(s0183_reasons + gate_g_reasons))
    blocking_reasons = (
        [] if productive_apply_reconciled or current_bundle_valid
        else preapply_stale_reasons
    )
    if authority_missing_for_current_canon:
        # Historical S0183 staleness is provenance here, not the operational
        # cause.  Preserve the exact current-authority reason for the operator.
        blocking_reasons = current_bundle_reasons
    if productive_apply_reconciled:
        verdict = "RELATIONAL_PRODUCTIVE_APPLY_RECONCILED"
        next_action = "START_POSTIMPACT_CLOSURE"
    elif current_bundle_valid:
        verdict = str(current_bundle.get("terminal_state") or "READY_FOR_AUTHORIZATION")
        next_action = str(current_bundle.get("next_action") or "AUTHORIZE_CURRENT_RELATIONAL_APPLY")
    elif candidate_error == "missing":
        verdict = "NO_CURRENT_RELATION_CANDIDATE_MANIFEST"
        next_action = "GENERATE_CURRENT_RELATION_CANDIDATES"
    elif candidate_reasons:
        verdict = "CURRENT_RELATION_CANDIDATES_STALE"
        next_action = "REFRESH_CURRENT_RELATION_CANDIDATES"
    elif reconciliation_reasons or reviewable_reasons:
        verdict = "CURRENT_RELATION_CANDIDATES_REQUIRE_RECONCILIATION"
        next_action = "VALIDATE_AND_RECONCILE_CURRENT_CANDIDATES"
    elif authority_missing_for_current_canon:
        verdict = CURRENT_RELATIONAL_AUTHORITY_MISSING_FOR_CURRENT_CANON
        next_action = PREPARE_CURRENT_RELATIONAL_GENERATION
    elif s0183_reasons:
        verdict = "IMPACT_BLOCKED"
        next_action = "RESOLVE_S0183_RECONCILIATION_OR_REVIEW"
    elif legacy_decisions:
        verdict = "LEGACY_HUMAN_RELATIONAL_REVIEW_NOT_AUTHORITATIVE"
        next_action = SUPERSEDE_LEGACY_HUMAN_RELATIONAL_DECISIONS
    elif ready_count > 0 and decision_counts["total"] == 0:
        verdict = "READY_FOR_HUMAN_RELATIONAL_REVIEW"
        next_action = RECORD_CURRENT_HUMAN_RELATIONAL_DECISIONS
    elif decision_counts["total"] < ready_count:
        verdict = "HUMAN_RELATIONAL_REVIEW_INCOMPLETE"
        next_action = RECORD_CURRENT_HUMAN_RELATIONAL_DECISIONS
    elif not gate_current:
        verdict = "RELATIONAL_ADMISSION_CURRENT_RUN_INCOMPLETE"
        next_action = "RUN_RELATIONAL_ADMISSION_GATE_DRY_RUN"
    elif int(gate_summary.get("technically_invalid") or 0) > 0 and int(gate_summary.get("approved_for_admission") or 0) > 0:
        verdict = "RELATIONAL_ADMISSION_PARTIALLY_READY"
        next_action = "RESOLVE_OR_DEFER_TECHNICALLY_INVALID_APPROVALS"
    elif gate_summary.get("admission_ready_dry_run", 0) and gate_g_current:
        verdict = "IMPACT_REQUIRES_REAUTHORIZATION"
        next_action = "REQUEST_EXPLICIT_REAUTHORIZATION_FOR_APPLY_RELATIONS"
    elif gate_summary.get("admission_ready_dry_run", 0):
        verdict = "READY_FOR_RELATIONAL_ADMISSION"
        next_action = "APPLY_REQUIRES_EXPLICIT_CONFIRMATION"
    else:
        verdict = "RELATIONAL_ADMISSION_BLOCKED"
        next_action = "RUN_RELATIONAL_ADMISSION_GATE_DRY_RUN"

    state = {
        "schema_version": "relational-operational-state/v1",
        "checked_at": checked_at or now(),
        "canon": canon,
        "baseline": {
            "path": display(baseline_path),
            "hash": sha256_file(baseline_path),
            "canon_hash": baseline.get("canon_hash"),
            "immutable": True,
            "authority_for_current_operation": False,
            "error": baseline_error,
        },
        "candidate_generation": {
            "manifest_path": display(candidate_manifest_path),
            "manifest_hash": candidate_manifest_hash,
            "bound_canon_hash": (candidate.get("canon_binding") or {}).get("canon_hash"),
            "total": (candidate.get("candidate_batch") or {}).get("record_count", 0),
            "current": not candidate_reasons,
            "stale_reasons": candidate_reasons,
        },
        "validation": {
            "report_path": display(validation_path),
            "total": validation_summary.get("total", 0),
            "valid": validation_summary.get("valid", 0),
            "invalid": validation_summary.get("invalid", 0),
            "unresolved": validation_summary.get("unresolved_target", 0),
            "duplicates": validation_summary.get("duplicate", 0),
            "current": not validation_error and int(validation_summary.get("total") or 0) == int((candidate.get("candidate_batch") or {}).get("record_count") or 0),
        },
        "reconciliation": {
            "manifest_path": display(reconciliation_path),
            "total": reconciliation.get("total", 0),
            "unclassified": reconciliation.get("unclassified", 0),
            "ready_for_review": ready_count,
            "blocked": blocked_count,
            "dispositions": reconciliation_counts,
            "historical_occurrences": reconciliation.get("historical_occurrences") or {},
            "current": not reconciliation_reasons,
            "stale_reasons": reconciliation_reasons,
        },
        "cross_batch_reconciliation": {
            "manifest_path": display(cross_batch_path),
            "manifest_hash": sha256_file(cross_batch_path),
            "taxonomy": cross_batch.get("taxonomy") or [],
            "old_counts": cross_batch.get("old_counts") or {},
            "current_counts": cross_batch.get("current_counts") or {},
            "coverage_complete": cross_batch.get("coverage_complete") is True,
            "current": bool(cross_batch_path.exists() and not s0183_reasons),
            "stale_reasons": s0183_reasons,
        },
        "current_authority": {
            "valid": current_bundle_valid,
            "bundle_path": current_bundle.get("bundle_path"),
            "terminal_state": current_bundle.get("terminal_state"),
            "planning": current_bundle.get("planning") or {},
            "stale_reasons": current_bundle.get("reason_codes") or [],
        },
        "historical_artifacts": {
            "s0183_preserved": True,
            "stale_reasons": historical_stale_reasons,
            "blocking_current_generation": False if current_bundle_valid else bool(historical_stale_reasons),
            "authorization_path": display(authorization_path) if not authorization_error else None,
            "authorization_consumed": authorization.get("consumed") is True,
            "apply_id": apply_report.get("apply_id") or productive_reconciliation.get("apply_id"),
        },
        "human_review": {
            "decisions_path": display(decisions_path),
            **decision_counts,
            # This is the technical queue cardinality, not a count of human
            # decisions still required.  Effective coverage is owned by the
            # generational producer and is intentionally not inferred from
            # raw decision rows.
            "technical_reviewable": (
                ready_count if technical_reviewable is None else technical_reviewable
            ),
            "effective_decision_covered": effective_decision_covered,
            "effective_pending": effective_pending,
            "coverage_source": (
                "current_generation_bundle" if current_bundle_valid
                else review_coverage.get("coverage_source")
            ),
            "legacy_supersession_required": len(legacy_decisions),
            "stale": len(decisions) if decision_stale else 0,
            "current": not decisions_error and not decision_stale and not legacy_decisions,
            "preservation_manifest_path": display(preservation_path) if preservation_path.exists() else None,
            "preserved_equivalent": preservation.get("migrated_equivalent_count", 0),
            "pending_after_preservation": (
                current_bundle_pending if current_bundle_human
                else len(preservation.get("pending_reviewable_candidate_ids") or [])
            ),
        },
        "admission_gate": {
            "report_path": display(gate_path),
            "evaluated": gate_summary.get("total_evaluated", 0),
            "technically_invalid": gate_summary.get("technically_invalid", 0),
            "awaiting_human_review": (
                current_bundle_pending if current_bundle_human
                else effective_pending if effective_pending is not None
                else gate_summary.get("awaiting_human_review", gate_decisions.get("blocked_missing_human_review", 0))
            ),
            "human_rejected": gate_summary.get("human_rejected", gate_decisions.get("rejected_by_human", 0)),
            "human_deferred": gate_summary.get("human_deferred", 0),
            "approved_for_admission": gate_summary.get("approved_for_admission", 0),
            "admission_ready": (
                0 if current_bundle_human
                else gate_summary.get("admission_ready_dry_run", 0)
            ),
            "current": gate_current or current_bundle_valid,
            "partition_complete": partition_complete,
            "partition_total": partition_total,
            "stale_reasons": [] if current_bundle_valid else gate_reasons,
        },
        "apply": {
            "executed": bool(apply_report.get("status") == "applied"),
            "apply_id": (
                apply_report.get("apply_id")
                or productive_reconciliation.get("apply_id")
            ),
            "applied_count": apply_report.get("applied_count", 0),
            "receipt_path": (
                display(apply_receipt_path) if not apply_receipt_error else None
            ),
            "receipt_hash": sha256_file(apply_receipt_path),
            "canon_modified": bool(apply_report.get("canon_modified") is True),
            "current": productive_apply_current,
            "authorized": (
                True if current_generational_apply_reconciled
                else False if current_bundle_valid else bool(
                    authorization.get("decision") == "authorized"
                    or (authorization_reconciliation.get("authorization") or {}).get(
                        "valid_at_execution"
                    ) is True
                )
            ),
            "authorized_at_execution": bool(
                current_generational_apply_reconciled
                or (
                    not authorization_error
                    and authorization.get("decision") == "authorized"
                )
                or (
                    not authorization_reconciliation_error
                    and (authorization_reconciliation.get("authorization") or {}).get(
                        "valid_at_execution"
                    ) is True
                )
            ),
            "authorization_consumed": (
                True if current_generational_apply_reconciled
                else False if current_bundle_valid else bool(
                    authorization.get("consumed") is True
                    or (authorization_reconciliation.get("consumption") or {}).get(
                        "consumed_once"
                    ) is True
                )
            ),
            "authorization_path": (
                display(current_apply_authorization_path)
                if current_generational_apply_reconciled
                else None if current_bundle_valid
                else display(authorization_path) if not authorization_error else None
            ),
            "authorization_current": current_generational_apply_reconciled,
            "authorization_reconciliation_path": (
                display(authorization_reconciliation_path)
                if not authorization_reconciliation_error else None
            ),
            "productive_reconciliation_path": (
                display(productive_reconciliation_path)
                if not productive_reconciliation_error else None
            ),
            "reconciled": productive_apply_reconciled,
            "gate_g_ready": gate_g_current or current_bundle_authorization,
            "gate_g_readiness_path": (
                str(Path(str(current_bundle.get("bundle_path"))) / "gate_g_readiness.json")
                if current_bundle_authorization else display(gate_g_path) if gate_g_path.exists() and not current_bundle_human else None
            ),
            "plan_path": (
                str(Path(str(current_bundle.get("bundle_path"))) / "relation_apply_plan.json")
                if current_bundle_authorization else gate_g.get("apply_plan_path") if not current_bundle_human else None
            ),
            "planning": current_bundle.get("planning") or {},
        },
        "rollback": {
            "available": bool(
                (gate_g_current and not current_bundle_valid)
                or (apply_report.get("canon_modified") is True and apply_report.get("rollback_snapshot"))
            ),
            "receipt_bound": bool(
                not apply_receipt_error
                and apply_receipt.get("rollback_snapshot") == apply_report.get("rollback_snapshot")
                and apply_receipt.get("rollback_snapshot_hash")
                == apply_report.get("rollback_snapshot_hash")
            ),
            "snapshot_path": (
                str(next((Path(str(current_bundle.get("bundle_path"))) / "rollback_snapshots").glob("*/snapshot_manifest.json"), ""))
                if current_bundle_authorization
                else gate_g.get("snapshot_path") if gate_g_current else apply_report.get("rollback_snapshot")
            ),
            "ready": bool(
                productive_apply_reconciled
                and apply_report.get("rollback_snapshot")
                and Path(str(apply_report.get("rollback_snapshot"))).is_file()
                and not apply_receipt_error
                and apply_receipt.get("rollback_snapshot")
                == apply_report.get("rollback_snapshot")
                and apply_receipt.get("rollback_snapshot_hash")
                == apply_report.get("rollback_snapshot_hash")
            ) or current_bundle_authorization or gate_g_current,
            "current": bool(
                productive_apply_current
                and apply_report.get("rollback_snapshot")
                and Path(str(apply_report.get("rollback_snapshot"))).is_file()
            ) or gate_g_current or current_bundle_authorization,
            "stale_reasons": (
                [] if productive_apply_reconciled or current_bundle_valid
                else gate_g_reasons
            ),
        },
        "canonical_relation_v1": canonical_relation_v1_count(local_root),
        "verdict": verdict,
        "next_action": next_action,
        "blocking_reasons": sorted(set(blocking_reasons)),
        "expected_postapply_staleness": {
            "recognized": productive_apply_reconciled,
            "historical_preapply_artifacts_invalidated_by_authorized_mutation": (
                sorted(set(preapply_stale_reasons)) if productive_apply_reconciled else []
            ),
        },
        "warnings": [
            warning for warning in (
                "baseline_is_historical_not_operational" if baseline else None,
                "admission_gate_current_run_missing_or_stale" if not gate_current and not current_bundle_valid else None,
                "data_tmp_is_not_an_operational_dependency",
                "historical_relational_artifacts_are_stale_provenance" if current_bundle_valid and historical_stale_reasons else None,
            ) if warning
        ],
    }
    return state


def relational_apply_precondition(state: dict[str, Any]) -> dict[str, Any]:
    """Return the single authoritative precondition used before apply prompt."""
    reasons: list[str] = []
    gate = state.get("admission_gate") or {}
    review = state.get("human_review") or {}
    reconciliation = state.get("reconciliation") or {}
    apply = state.get("apply") or {}
    if gate.get("current") is not True:
        reasons.append("admission_gate_not_current")
    if gate.get("stale_reasons"):
        reasons.append("admission_gate_has_stale_reasons")
    if "partition_complete" in gate and gate.get("partition_complete") is not True:
        reasons.append("admission_gate_partition_incomplete")
    if int(review.get("total") or 0) < int(reconciliation.get("ready_for_review") or 0):
        reasons.append("human_review_incomplete")
    if int(gate.get("admission_ready") or 0) <= 0:
        reasons.append("no_admission_ready_relations")
    if int(gate.get("technically_invalid") or 0) > 0:
        reasons.append("technically_invalid_approvals_present")
    if apply.get("executed") is True:
        reasons.append("apply_already_executed")
    return {
        "schema_version": "relational-apply-precondition/v1",
        "allowed": not reasons,
        "reasons": reasons,
        "admission_ready": int(gate.get("admission_ready") or 0),
        "gate_current": gate.get("current") is True,
        "gate_partition_complete": gate.get("partition_complete", True) is True,
        "human_review_total": int(review.get("total") or 0),
        "reviewable_total": int(reconciliation.get("ready_for_review") or 0),
        "apply_executed": apply.get("executed") is True,
    }


def build_audit_index(local_root: Path = LOCAL_ROOT, *, checked_at: str | None = None) -> dict[str, Any]:
    state = build_state(local_root, checked_at=checked_at)
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    audit_dir = local_root / "audit" / "relation_admission" / "current"
    paths = [
        current_dir / "current_candidate_manifest.json",
        current_dir / "validation_report.json",
        current_dir / "reconciliation_manifest.json",
        current_dir / "reviewable_candidate_manifest.json",
        current_dir / "human_review_decisions.jsonl",
        audit_dir / "current_run_manifest.json",
        audit_dir / "admission_gate_dry_run.json",
        audit_dir / "relation_apply_report.json",
        audit_dir / "relation_apply_receipt.json",
        local_root / "audit" / "s0183" / "current" / "cross_batch_reconciliation_manifest.json",
        local_root / "audit" / "s0183" / "current" / "human_decision_preservation_manifest.json",
        local_root / "audit" / "s0183" / "gate-f-safety-verification.json",
        local_root / "audit" / "s0183" / "gate-g" / "gate_g_readiness.json",
        local_root / "audit" / "s0183" / "gate-g" / "gate_g_authorization.json",
        local_root / "audit" / "s0183" / "reconciliation" / "productive_apply_reconciliation.json",
        local_root / "audit" / "s0183" / "gate-h" / "gate_h_revalidation.json",
    ]
    return {
        "schema_version": "relational-audit-index/v1",
        "checked_at": checked_at or now(),
        "state": state,
        "artifacts": [
            {"path": display(path), "exists": path.exists(), "sha256": sha256_file(path)}
            for path in paths
        ],
        "history_path": display(local_root / "audit" / "relation_admission" / "history"),
        "tmp_dependency": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble live relational admission state")
    parser.add_argument("command", choices=("state", "audit", "validate-currentness", "apply-preflight", "next-action"))
    parser.add_argument("--local-root", type=Path, default=LOCAL_ROOT)
    args = parser.parse_args(argv)
    audit_dir = args.local_root / "audit" / "relation_admission" / "current"
    if args.command == "audit":
        payload = build_audit_index(args.local_root)
        write_json(audit_dir / "relational_operational_state.json", payload["state"])
        write_json(audit_dir / "relational_audit_index.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    state = build_state(args.local_root)
    if args.command == "next-action":
        print(state["next_action"])
        return 0
    if args.command == "apply-preflight":
        precondition = relational_apply_precondition(state)
        print(json.dumps(precondition, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if precondition["allowed"] else 2
    if args.command == "state":
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    if any(reason.startswith("invalid") for reason in state["blocking_reasons"]):
        return 1
    return 0 if state["candidate_generation"]["current"] and state["reconciliation"]["current"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
