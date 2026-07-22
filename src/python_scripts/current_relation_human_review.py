#!/usr/bin/env python3
"""Persist operator-owned decisions for the current relational review queue.

This is a review-only surface: it cannot plan or apply a canonical mutation.
It writes one durable, hash-bound decision per candidate for the admission gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from relation_admission_gate import (
    DECISION_REASON_CODES,
    EXCEPTION_REASON_CODES,
    NOTE_REQUIRED_REASON_CODES,
    SCHEMA_HUMAN_DECISION_LINE,
    SCHEMA_HUMAN_DECISION_LINE_LEGACY,
    validate_human_review_decision_record,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_CURRENT_DIR = REPO_ROOT / "data/out/local/pipeline/relation_candidates/current"
DEFAULT_CANON_ROOT = REPO_ROOT / "data/out/local"
DEFAULT_S0181_AUDIT_ROOT = DEFAULT_CANON_ROOT / "audit" / "s0181"
DEFAULT_GATE_REPORT = DEFAULT_CANON_ROOT / "audit" / "relation_admission" / "current" / "admission_gate_dry_run.json"

DECISIONS_FILE = "human_review_decisions.jsonl"
AUDIT_FILE = "human_review_audit_log.jsonl"
QUEUE_FILE = "ready_for_human_review.jsonl"
MANIFEST_FILES = ("current_candidate_manifest.json", "reconciliation_manifest.json")
DECISIONS = {"approved_for_admission", "rejected", "deferred"}
MISSING = "no disponible"
BATCH_CONFIRMATION = "CONFIRM REVIEW BATCH"
MULTI_BATCH_CONFIRMATION_PREFIX = "CONFIRM MULTIPLE REVIEW BATCHES"
SUPERSESSION_CONFIRMATION = "SUPERSEDE CURRENT HUMAN REVIEW"
DECISION_SUPERSESSION_CONFIRMATION = "CONFIRM REVIEW SUPERSESSION"
SUPERSESSION_REASON = "FREE_TEXT_RATIONALE_NOT_AUDITABLE"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no} must contain an object")
        rows.append(value)
    return rows


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def canon_hash(canon_root: Path) -> str:
    digest = hashlib.sha256()
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        digest.update(shard.read_bytes())
    return digest.hexdigest()


def current_bindings(current_dir: Path, canon_root: Path) -> dict[str, str]:
    candidate_manifest, reconciliation_manifest = (current_dir / name for name in MANIFEST_FILES)
    for path in (current_dir / QUEUE_FILE, candidate_manifest, reconciliation_manifest):
        if not path.exists():
            raise ValueError(f"required current artifact does not exist: {path}")
    return {
        "canon_hash": canon_hash(canon_root),
        "candidate_manifest_hash": sha256_file(candidate_manifest),
        "reconciliation_manifest_hash": sha256_file(reconciliation_manifest),
    }


def load_existing_decisions(
    path: Path, allowed_ids: set[str], bindings: dict[str, str], *, allow_legacy: bool = False,
) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    for line_no, record in enumerate(load_jsonl(path), start=1):
        errors = validate_human_review_decision_record(record, allow_legacy=allow_legacy)
        candidate_id = str(record.get("candidate_id") or "")
        if candidate_id in decisions:
            errors.append("duplicate candidate_id")
        if candidate_id not in allowed_ids:
            errors.append("candidate_id is not in current review queue")
        for key, value in bindings.items():
            if record.get(key) != value:
                errors.append(f"stale {key}")
        if errors:
            raise ValueError(f"{path}:{line_no}: {'; '.join(errors)}")
        decisions[candidate_id] = record
    return decisions


def validate_actor(actor: str) -> str:
    normalized = actor.strip()
    if not normalized:
        raise ValueError("human review actor cannot be empty")
    return normalized


def candidate_endpoint(candidate: dict[str, Any], name: str) -> str:
    endpoint = candidate.get(name) or {}
    return str(endpoint.get("canonical_id") or endpoint.get("tiddler_id") or "")


def build_decision_record(
    candidate: dict[str, Any], *, decision: str, reason_code: str, actor: str,
    bindings: dict[str, str], note: str | None = None,
    decision_mode: str = "individual", decision_batch_id: str | None = None,
    review_policy_id: str | None = None, supersedes_decision_hash: str | None = None,
    multi_review_operation_id: str | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ValueError(f"unsupported decision: {decision}")
    actor = validate_actor(actor)
    record = {
        "schema_version": SCHEMA_HUMAN_DECISION_LINE,
        "session_id": "S0181",
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "source_canon_id": candidate_endpoint(candidate, "source"),
        "target_canon_id": candidate_endpoint(candidate, "target"),
        "predicate": str(candidate.get("relation_type") or (candidate.get("relation") or {}).get("type") or ""),
        "relation_schema_version": str(candidate.get("candidate_schema_version") or candidate.get("schema_version") or ""),
        "evidence": candidate.get("evidence") or {},
        "human_review_decision": decision,
        "human_review_reason_code": reason_code.strip(),
        "human_review_note": note.strip() if isinstance(note, str) and note.strip() else None,
        "decision_mode": decision_mode,
        "decision_batch_id": decision_batch_id,
        "review_policy_id": review_policy_id,
        "multi_review_operation_id": multi_review_operation_id,
        "supersedes_decision_hash": supersedes_decision_hash,
        "human_review_actor": actor,
        "human_review_timestamp": reviewed_at or utc_now(),
        "approval_scope": "canonical_admission" if decision == "approved_for_admission" else "review_queue",
        "reviewed_evidence_paths": [QUEUE_FILE],
        **bindings,
    }
    errors = validate_human_review_decision_record(record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def atomic_write_jsonl(path: Path, decisions: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
            temporary = Path(fh.name)
            for record in decisions.values():
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if load_jsonl(temporary) != list(decisions.values()):
            raise RuntimeError("temporary decision authority failed round-trip validation")
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def decision_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def append_auxiliary_event(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def append_audit(
    path: Path, record: dict[str, Any], *, previous: dict[str, Any] | None = None,
) -> None:
    """Append auxiliary evidence; the decisions JSONL remains authoritative."""
    entry = {
        "schema_version": "relation-human-review-audit/v1",
        "session_id": "S0181",
        "recorded_at": utc_now(),
        "candidate_id": record["candidate_id"],
        "human_review_decision": record["human_review_decision"],
        "human_review_reason_code": record["human_review_reason_code"],
        "human_review_note": record.get("human_review_note"),
        "decision_batch_id": record.get("decision_batch_id"),
        "multi_review_operation_id": record.get("multi_review_operation_id"),
        "human_review_actor": record["human_review_actor"],
        "canon_hash": record["canon_hash"],
        "candidate_manifest_hash": record["candidate_manifest_hash"],
        "reconciliation_manifest_hash": record["reconciliation_manifest_hash"],
        "canon_modified": False,
        "action": "decision_superseded" if previous else "decision_recorded",
        "previous_decision": previous,
        "previous_decision_hash": decision_hash(previous) if previous else None,
        "new_decision_hash": decision_hash(record),
    }
    append_auxiliary_event(path, entry)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
            temporary = Path(fh.name)
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def repo_path_status(path: str, repo_root: Path = REPO_ROOT) -> str:
    if not path:
        return "not_available"
    return "current" if (repo_root / path).exists() else "stale"


def path_family(path: str) -> str:
    parts = Path(path).parts
    return "/".join(parts[:2]) if parts else MISSING


def proposed_decision_for(candidate: dict[str, Any], gate_item: dict[str, Any]) -> tuple[str, str, str | None]:
    reasons = gate_item.get("all_block_reasons") or gate_item.get("blocking_reasons") or []
    if any("GATE-022" in str(reason) for reason in reasons):
        return "deferred", "STALE_TARGET_PATH", "S0181_GATE_022_DEFERRAL_V1"
    predicate = str(candidate.get("relation_type") or "")
    evidence = candidate.get("evidence") or {}
    technical_kind = str(evidence.get("technical_evidence_kind") or "")
    parser = str(evidence.get("parser") or "")
    if predicate == "depende_de" and (technical_kind == "ast_import" or parser == "python_ast"):
        return "approved_for_admission", "DIRECT_CODE_DEPENDENCY_CONFIRMED", "S0181_DIRECT_AST_IMPORT_V1"
    if predicate == "valida" or technical_kind == "test_imports_subject":
        return "approved_for_admission", "TEST_VALIDATES_TARGET_CONFIRMED", "S0181_TEST_VALIDATION_V1"
    if predicate == "references":
        return "approved_for_admission", "EXPLICIT_REFERENCE_CONFIRMED", "S0181_EXPLICIT_REFERENCE_V1"
    return "approved_for_admission", "ARCHITECTURAL_RELATION_CONFIRMED", "S0181_ARCHITECTURAL_RELATION_V1"


def candidate_group_criterion(candidate: dict[str, Any], gate_item: dict[str, Any]) -> dict[str, Any]:
    reasons = gate_item.get("all_block_reasons") or gate_item.get("blocking_reasons") or []
    if any("GATE-022" in str(reason) for reason in reasons):
        return {"gate_code": "GATE-022", "target_repo_path_status": "stale"}
    source, target, evidence = candidate.get("source") or {}, candidate.get("target") or {}, candidate.get("evidence") or {}
    source_path = str(source.get("repo_path") or "")
    target_path = str(target.get("repo_path") or "")
    return {
        "predicate": candidate.get("relation_type"),
        "evidence_kind": evidence.get("evidence_kind"),
        "technical_evidence_kind": evidence.get("technical_evidence_kind"),
        "parser": evidence.get("parser"),
        "confidence_band": evidence.get("confidence") or "unknown",
        "source_class": source.get("artifact_family") or MISSING,
        "source_path_family": path_family(source_path),
        "target_class": target.get("artifact_family") or MISSING,
        "target_path_family": path_family(target_path),
        "source_repo_path_status": repo_path_status(source_path),
        "target_repo_path_status": repo_path_status(target_path),
        "source_lifecycle": source.get("repo_lifecycle_state") or MISSING,
        "target_lifecycle": target.get("repo_lifecycle_state") or MISSING,
        "gate_outcome": gate_item.get("decision") or gate_item.get("gate_status") or MISSING,
    }


def batch_set_hash(
    criterion: dict[str, Any], candidate_ids: list[str], decision: str, reason_code: str,
) -> str:
    payload = {
        "criterion": criterion,
        "candidate_ids": sorted(candidate_ids),
        "proposed_decision": decision,
        "proposed_reason_code": reason_code,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_batch_previews(
    queue: list[dict[str, Any]], gate_report: dict[str, Any], *,
    exclusions: set[str] | None = None, decided_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclusions = exclusions or set()
    decided_ids = decided_ids or set()
    by_id = {str(item.get("candidate_id") or ""): item for item in queue}
    gate_by_id = {
        str(item.get("candidate_id") or ""): item
        for item in gate_report.get("items") or [] if isinstance(item, dict)
    }
    unknown = (exclusions | decided_ids) - set(by_id)
    if unknown:
        raise ValueError(f"candidate IDs outside current queue: {sorted(unknown)}")
    groups: dict[str, list[str]] = defaultdict(list)
    criteria: dict[str, dict[str, Any]] = {}
    for candidate_id, candidate in by_id.items():
        if candidate_id in decided_ids:
            continue
        gate_item = gate_by_id.get(candidate_id, {})
        criterion = candidate_group_criterion(candidate, gate_item)
        key = json.dumps(criterion, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        criteria[key] = criterion
        groups[key].append(candidate_id)
    previews: list[dict[str, Any]] = []
    for key in sorted(groups):
        group_candidate_ids = sorted(groups[key])
        group_exclusions = sorted(exclusions.intersection(group_candidate_ids))
        candidate_ids = sorted(set(group_candidate_ids) - exclusions)
        if not candidate_ids:
            continue
        criterion = criteria[key]
        representative = by_id[candidate_ids[0]]
        decision, reason_code, policy_id = proposed_decision_for(representative, gate_by_id.get(candidate_ids[0], {}))
        set_hash = batch_set_hash(criterion, candidate_ids, decision, reason_code)
        batch_id = "hrb_" + hashlib.sha256(key.encode()).hexdigest()[:24]
        previews.append({
            "schema_version": "relation-human-review-batch-preview/v1",
            "batch_id": batch_id,
            "selection_rule": criterion,
            "candidate_count": len(candidate_ids),
            "candidate_ids": candidate_ids,
            "candidate_set_hash": set_hash,
            "proposed_decision": decision,
            "proposed_reason_code": reason_code,
            "review_policy_id": policy_id,
            "examples": [
                {
                    "candidate_id": cid,
                    "source": (by_id[cid].get("source") or {}).get("repo_path"),
                    "target": (by_id[cid].get("target") or {}).get("repo_path"),
                    "predicate": by_id[cid].get("relation_type"),
                    "evidence": (by_id[cid].get("evidence") or {}).get("raw_observation"),
                }
                for cid in candidate_ids[:5]
            ],
            "exclusions": group_exclusions,
            "confirmation_required": BATCH_CONFIRMATION,
            "writes_performed": False,
        })
    return previews


def batch_compatibility_signature(
    preview: dict[str, Any], bindings: dict[str, str],
) -> dict[str, Any]:
    """Return the structured minimum that may share one human confirmation."""
    rule = preview.get("selection_rule") or {}
    treatment_class = (
        "gate_022_stale_deferral"
        if rule.get("gate_code") == "GATE-022"
        else "admission_ready_homogeneous"
    )
    return {
        "decision_proposed": preview.get("proposed_decision"),
        "reason_code": preview.get("proposed_reason_code"),
        "review_policy_id": preview.get("review_policy_id"),
        "gate_outcome": rule.get("gate_outcome"),
        "predicate": rule.get("predicate"),
        "technical_evidence_kind": rule.get("technical_evidence_kind"),
        "treatment_class": treatment_class,
        **bindings,
    }


def decision_matches_batch(record: dict[str, Any], preview: dict[str, Any]) -> bool:
    return bool(
        record.get("decision_mode") == "batch"
        and record.get("decision_batch_id") == preview.get("batch_id")
        and record.get("human_review_decision") == preview.get("proposed_decision")
        and record.get("human_review_reason_code") == preview.get("proposed_reason_code")
        and record.get("review_policy_id") == preview.get("review_policy_id")
    )


def build_batch_inventory(
    queue: list[dict[str, Any]], gate_report: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Describe full, pending, resolved, and conflicting membership per live batch."""
    full_previews = build_batch_previews(queue, gate_report)
    pending_previews = {
        preview["batch_id"]: preview
        for preview in build_batch_previews(queue, gate_report, decided_ids=set(decisions))
    }
    inventory: list[dict[str, Any]] = []
    for full in full_previews:
        pending = pending_previews.get(full["batch_id"])
        resolved_ids: list[str] = []
        conflict_ids: list[str] = []
        for candidate_id in full["candidate_ids"]:
            existing = decisions.get(candidate_id)
            if existing is None:
                continue
            if decision_matches_batch(existing, full):
                resolved_ids.append(candidate_id)
            else:
                conflict_ids.append(candidate_id)
        inventory.append({
            "batch_id": full["batch_id"],
            "full_preview": full,
            "pending_preview": pending,
            "total_candidates": full["candidate_count"],
            "pending_candidates": pending["candidate_count"] if pending else 0,
            "already_reviewed_candidates": len(resolved_ids),
            "already_reviewed_candidate_ids": sorted(resolved_ids),
            "conflict_candidate_ids": sorted(conflict_ids),
            "status": (
                "conflict" if conflict_ids
                else "pending" if pending
                else "resolved_idempotent"
            ),
        })
    return inventory


def parse_multi_batch_ids(raw: str) -> list[str]:
    if not raw.strip():
        raise ValueError("at least one batch_id is required")
    parts = raw.split(",")
    normalized = [part.strip() for part in parts]
    if any(not part for part in normalized):
        raise ValueError("empty batch_id is not allowed")
    if len(normalized) != len(set(normalized)):
        raise ValueError("duplicate batch_id is not allowed")
    return sorted(normalized)


def multi_review_operation_id(
    selected: list[dict[str, Any]], signature: dict[str, Any],
) -> tuple[str, str]:
    scope = {
        "selected_batches": [
            {
                "batch_id": item["batch_id"],
                "candidate_set_hash": item["full_preview"]["candidate_set_hash"],
            }
            for item in selected
        ],
        "compatibility_signature": signature,
    }
    encoded = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    scope_hash = hashlib.sha256(encoded).hexdigest()
    return "hrm_" + scope_hash[:24], scope_hash


def build_multi_batch_preview(
    inventory: list[dict[str, Any]], selected_batch_ids: list[str],
    bindings: dict[str, str],
) -> dict[str, Any]:
    if not selected_batch_ids or len(selected_batch_ids) != len(set(selected_batch_ids)):
        raise ValueError("selected batch IDs must be unique and non-empty")
    by_id = {item["batch_id"]: item for item in inventory}
    unknown = set(selected_batch_ids) - set(by_id)
    if unknown:
        raise ValueError(f"batch_id is not live in the current inventory: {sorted(unknown)}")
    selected = [by_id[batch_id] for batch_id in sorted(selected_batch_ids)]
    conflicts = {
        item["batch_id"]: item["conflict_candidate_ids"]
        for item in selected if item["conflict_candidate_ids"]
    }
    if conflicts:
        raise ValueError(f"selected batches conflict with current decisions: {conflicts}")
    signatures = [batch_compatibility_signature(item["full_preview"], bindings) for item in selected]
    if any(signature != signatures[0] for signature in signatures[1:]):
        raise ValueError("selected batches do not share one structured compatibility signature")
    signature = signatures[0]
    operation_id, scope_hash = multi_review_operation_id(selected, signature)
    pending_ids: list[str] = []
    reviewed_ids: list[str] = []
    examples: list[dict[str, Any]] = []
    batches: list[dict[str, Any]] = []
    for item in selected:
        pending = item["pending_preview"]
        if pending:
            pending_ids.extend(pending["candidate_ids"])
            for example in pending["examples"]:
                if len(examples) < 5:
                    examples.append({"batch_id": item["batch_id"], **example})
        reviewed_ids.extend(item["already_reviewed_candidate_ids"])
        batches.append({
            "batch_id": item["batch_id"],
            "total_candidates": item["total_candidates"],
            "pending_candidates": item["pending_candidates"],
            "already_reviewed_candidates": item["already_reviewed_candidates"],
            "full_candidate_set_hash": item["full_preview"]["candidate_set_hash"],
            "pending_candidate_set_hash": pending["candidate_set_hash"] if pending else None,
        })
    if len(pending_ids) != len(set(pending_ids)):
        raise ValueError("candidate_id appears in more than one selected batch")
    confirmation = f"{MULTI_BATCH_CONFIRMATION_PREFIX} {operation_id}"
    return {
        "schema_version": "relation-human-review-multi-batch-preview/v1",
        "multi_review_operation_id": operation_id,
        "operation_scope_hash": scope_hash,
        "selected_batch_ids": [item["batch_id"] for item in selected],
        "selected_batches": len(selected),
        "pending_candidate_ids": sorted(pending_ids),
        "pending_candidates": len(pending_ids),
        "already_reviewed_candidate_ids": sorted(reviewed_ids),
        "already_reviewed_candidates": len(reviewed_ids),
        "decision": signature["decision_proposed"],
        "reason_code": signature["reason_code"],
        "review_policy_id": signature["review_policy_id"],
        "compatibility_signature": signature,
        "batches": batches,
        "examples": examples,
        "excluded_candidates": 0,
        "confirmation_required": confirmation,
        "writes_performed": False,
    }


def persist_multi_batch_preview(
    current_dir: Path, canon_root: Path, *, gate_report: dict[str, Any],
    preview: dict[str, Any], actor: str, confirmation: str, note: str | None = None,
) -> dict[str, Any]:
    if confirmation != preview.get("confirmation_required"):
        return {
            "persisted": 0,
            "already_reviewed": int(preview.get("already_reviewed_candidates") or 0),
            "cancelled": True,
        }
    actor = validate_actor(actor)
    bindings = current_bindings(current_dir, canon_root)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    by_id = {str(item.get("candidate_id") or ""): item for item in queue}
    decisions_path = current_dir / DECISIONS_FILE
    decisions = load_existing_decisions(decisions_path, set(by_id), bindings)
    inventory = build_batch_inventory(queue, gate_report, decisions)
    fresh = build_multi_batch_preview(inventory, list(preview.get("selected_batch_ids") or []), bindings)
    if fresh["operation_scope_hash"] != preview.get("operation_scope_hash"):
        raise ValueError("multiple-review scope changed since preview")
    expected_confirmation = fresh["confirmation_required"]
    if confirmation != expected_confirmation:
        return {
            "persisted": 0,
            "already_reviewed": fresh["already_reviewed_candidates"],
            "cancelled": True,
        }
    batch_by_candidate: dict[str, dict[str, Any]] = {}
    inventory_by_id = {item["batch_id"]: item for item in inventory}
    for batch_id in fresh["selected_batch_ids"]:
        item = inventory_by_id[batch_id]
        pending = item["pending_preview"]
        if pending:
            for candidate_id in pending["candidate_ids"]:
                batch_by_candidate[candidate_id] = pending
    reviewed_at = utc_now()
    new_records: list[dict[str, Any]] = []
    updated = dict(decisions)
    for candidate_id in fresh["pending_candidate_ids"]:
        batch = batch_by_candidate[candidate_id]
        record = build_decision_record(
            by_id[candidate_id],
            decision=str(batch["proposed_decision"]),
            reason_code=str(batch["proposed_reason_code"]),
            actor=actor,
            bindings=bindings,
            note=note,
            decision_mode="batch",
            decision_batch_id=str(batch["batch_id"]),
            review_policy_id=batch.get("review_policy_id"),
            multi_review_operation_id=fresh["multi_review_operation_id"],
            reviewed_at=reviewed_at,
        )
        updated[candidate_id] = record
        new_records.append(record)
    if new_records:
        atomic_write_jsonl(decisions_path, updated)
        try:
            for record in new_records:
                append_audit(current_dir / AUDIT_FILE, record)
        except OSError as error:
            raise RuntimeError(
                "authoritative multiple review persisted atomically, but auxiliary audit append failed"
            ) from error
    return {
        "persisted": len(new_records),
        "already_reviewed": fresh["already_reviewed_candidates"],
        "total_current_decisions": len(updated),
        "multi_review_operation_id": fresh["multi_review_operation_id"],
        "cancelled": False,
    }


def persist_batch_preview(
    current_dir: Path, canon_root: Path, *, preview: dict[str, Any], actor: str,
    confirmation: str, note: str | None = None,
) -> int:
    if confirmation != BATCH_CONFIRMATION:
        return 0
    actor = validate_actor(actor)
    bindings = current_bindings(current_dir, canon_root)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    by_id = {str(item.get("candidate_id") or ""): item for item in queue}
    candidate_ids = list(preview.get("candidate_ids") or [])
    if not candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("batch must contain unique candidate IDs")
    expected_hash = batch_set_hash(
        preview.get("selection_rule") or {}, candidate_ids,
        str(preview.get("proposed_decision") or ""), str(preview.get("proposed_reason_code") or ""),
    )
    if expected_hash != preview.get("candidate_set_hash"):
        raise ValueError("batch preview hash mismatch")
    if set(candidate_ids) - set(by_id):
        raise ValueError("batch contains candidate outside current queue")
    decisions_path = current_dir / DECISIONS_FILE
    decisions = load_existing_decisions(decisions_path, set(by_id), bindings)
    new_records: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for candidate_id in candidate_ids:
        previous = decisions.get(candidate_id)
        if previous and not str(note or "").strip():
            raise ValueError("human_review_note required when batch supersedes an existing decision")
        record = build_decision_record(
            by_id[candidate_id],
            decision=str(preview.get("proposed_decision") or ""),
            reason_code=str(preview.get("proposed_reason_code") or ""),
            actor=actor,
            bindings=bindings,
            note=note,
            decision_mode="batch",
            decision_batch_id=str(preview.get("batch_id") or ""),
            review_policy_id=preview.get("review_policy_id"),
            supersedes_decision_hash=decision_hash(previous) if previous else None,
        )
        decisions[candidate_id] = record
        new_records.append((record, previous))
    atomic_write_jsonl(decisions_path, decisions)
    try:
        for record, previous in new_records:
            append_audit(current_dir / AUDIT_FILE, record, previous=previous)
    except OSError as error:
        raise RuntimeError("authoritative batch persisted, but auxiliary audit append failed") from error
    return len(new_records)


def supersede_legacy_current(
    current_dir: Path, canon_root: Path, audit_root: Path, *, actor: str,
    note: str, confirmation: str, timestamp: str | None = None,
) -> Path:
    if confirmation != SUPERSESSION_CONFIRMATION:
        raise ValueError(f"exact confirmation required: {SUPERSESSION_CONFIRMATION}")
    actor = validate_actor(actor)
    if not note.strip():
        raise ValueError("supersession note cannot be empty")
    bindings = current_bindings(current_dir, canon_root)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    decisions_path = current_dir / DECISIONS_FILE
    decisions = load_existing_decisions(
        decisions_path, {str(row.get("candidate_id") or "") for row in queue}, bindings,
        allow_legacy=True,
    )
    if not decisions or any(row.get("schema_version") != SCHEMA_HUMAN_DECISION_LINE_LEGACY for row in decisions.values()):
        raise ValueError("current authority must contain only legacy v1 decisions")
    gate_report_path = audit_root.parent / "relation_admission" / "current" / "admission_gate_dry_run.json"
    run_manifest_path = audit_root.parent / "relation_admission" / "current" / "current_run_manifest.json"
    if not gate_report_path.is_file() or not run_manifest_path.is_file():
        raise ValueError("current gate report and run manifest are required for supersession")
    gate_report = load_json(gate_report_path)
    run_manifest = load_json(run_manifest_path)
    previous_hash = sha256_file(decisions_path)
    if run_manifest.get("human_review_decisions_hash") != previous_hash:
        raise ValueError("current gate run is not bound to the legacy decision authority")
    if run_manifest.get("report_hash") != sha256_file(gate_report_path):
        raise ValueError("current gate report hash does not match its run manifest")
    historical_counts = Counter(row["human_review_decision"] for row in decisions.values())
    gate_summary = gate_report.get("summary") or {}
    expected_gate_counts = {
        "total_evaluated": len(queue),
        "approved_for_admission": historical_counts["approved_for_admission"],
        "human_rejected": historical_counts["rejected"],
        "human_deferred": historical_counts["deferred"],
    }
    mismatches = {
        key: {"expected": expected, "observed": int(gate_summary.get(key) or 0)}
        for key, expected in expected_gate_counts.items()
        if int(gate_summary.get(key) or 0) != expected
    }
    if mismatches:
        raise ValueError(f"current gate did not consume the legacy decisions: {mismatches}")
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history_dir = audit_root / "human_review_superseded" / stamp
    if history_dir.exists():
        raise ValueError(f"supersession destination already exists: {history_dir}")
    sources = {
        "human_review_decisions.jsonl": decisions_path,
        "human_review_audit_log.jsonl": current_dir / AUDIT_FILE,
        "admission_gate_dry_run.json": gate_report_path,
        "current_run_manifest.json": run_manifest_path,
        "current_candidate_manifest.json": current_dir / "current_candidate_manifest.json",
        "reconciliation_manifest.json": current_dir / "reconciliation_manifest.json",
    }
    for source in sources.values():
        if not source.is_file():
            raise ValueError(f"required supersession evidence missing: {source}")
    history_dir.mkdir(parents=True)
    file_evidence: dict[str, dict[str, Any]] = {}
    for name, source in sources.items():
        destination = history_dir / name
        shutil.copyfile(source, destination)
        if source.read_bytes() != destination.read_bytes():
            raise RuntimeError(f"byte verification failed for {name}")
        file_evidence[name] = {
            "source_path": str(source),
            "archived_path": str(destination),
            "sha256": sha256_file(destination),
            "bytes_verified": True,
        }
    canon_before = canon_hash(canon_root)
    manifest = {
        "schema_version": "relation-human-review-supersession/v1",
        "session_id": "S0181",
        "superseded_count": len(decisions),
        "previous_schema": SCHEMA_HUMAN_DECISION_LINE_LEGACY,
        "previous_hash": previous_hash,
        "actor": actor,
        "superseded_at": utc_now(),
        "reason": SUPERSESSION_REASON,
        "human_review_note": note.strip(),
        "status": "superseded_not_authoritative",
        "files": file_evidence,
        "canon_hash_before": canon_before,
        "canon_hash_after": canon_before,
        "canon_modified": False,
        "apply_executed": False,
        "current_authority_schema": SCHEMA_HUMAN_DECISION_LINE,
        "current_authority_reset_to_empty": True,
    }
    manifest_path = history_dir / "supersession_manifest.json"
    atomic_write_json(manifest_path, manifest)
    if sha256_file(history_dir / DECISIONS_FILE) != manifest["previous_hash"]:
        raise RuntimeError("archived decision hash changed before authority reset")
    atomic_write_jsonl(decisions_path, {})
    append_auxiliary_event(current_dir / AUDIT_FILE, {
        "schema_version": "relation-human-review-supersession-audit/v1",
        "session_id": "S0181",
        "recorded_at": utc_now(),
        "actor": actor,
        "reason": SUPERSESSION_REASON,
        "human_review_note": note.strip(),
        "superseded_count": len(decisions),
        "supersession_manifest": str(manifest_path),
        "supersession_manifest_hash": sha256_file(manifest_path),
        "previous_hash": manifest["previous_hash"],
        "status": "superseded_not_authoritative",
        "canon_modified": False,
        "apply_executed": False,
    })
    if canon_hash(canon_root) != canon_before:
        raise RuntimeError("canon changed during human-review supersession")
    return manifest_path


def available(value: Any) -> str:
    rendered = str(value).strip() if value is not None else ""
    return rendered or MISSING


def endpoint_description(endpoint: dict[str, Any]) -> str:
    title = available(endpoint.get("canonical_title") or endpoint.get("title"))
    path = available(endpoint.get("repo_path"))
    kind = available(endpoint.get("artifact_family") or endpoint.get("content_type"))
    return f"title={title}; path={path}; type={kind}"


def describe(candidate: dict[str, Any], position: int, total: int) -> None:
    source, target, evidence = candidate.get("source") or {}, candidate.get("target") or {}, candidate.get("evidence") or {}
    history = ((candidate.get("reconciliation") or {}).get("historical_occurrence") or {})
    print(f"\n[{position}/{total}] {candidate.get('candidate_id', '')}")
    print(f"  predicate: {available(candidate.get('relation_type') or (candidate.get('relation') or {}).get('type'))}")
    print(f"  source:    {endpoint_description(source)}")
    print(f"  target:    {endpoint_description(target)}")
    print(f"  evidence location: {available(evidence.get('location') or evidence.get('file'))}")
    print(f"  evidence excerpt:  {available(evidence.get('raw_observation') or evidence.get('excerpt'))}")
    print(f"  historical occurrence: {'yes' if history.get('observed') is True else 'no'}")
    print(f"  historical authority: {available(history.get('authority'))}")
    print(f"  technical disposition: {available(candidate.get('status'))}")


def run_review(current_dir: Path, canon_root: Path, actor: str) -> int:
    actor = validate_actor(actor)
    bindings = current_bindings(current_dir, canon_root)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    allowed_ids = {str(item.get("candidate_id") or "") for item in queue}
    if not queue or "" in allowed_ids or len(allowed_ids) != len(queue):
        raise ValueError("current review queue must contain unique non-empty candidate IDs")
    decisions_path = current_dir / DECISIONS_FILE
    decisions = load_existing_decisions(decisions_path, allowed_ids, bindings)
    pending = [item for item in queue if str(item.get("candidate_id")) not in decisions]
    print(f"Revisión humana S0181: {len(decisions)} decididas, {len(pending)} pendientes. Canon protegido.")
    for index, candidate in enumerate(pending, start=1):
        describe(candidate, index, len(pending))
        while True:
            choice = input("Decisión [a=aprobar, r=rechazar, d=diferir, q=salir]: ").strip().lower()
            if choice == "q":
                print("Revisión detenida por el operador. Las decisiones ya persistidas se conservan.")
                return 0
            decision = {"a": "approved_for_admission", "r": "rejected", "d": "deferred"}.get(choice)
            if decision is None:
                print("Opción inválida.")
                continue
            allowed_codes = sorted(DECISION_REASON_CODES[decision] | EXCEPTION_REASON_CODES)
            print("Reason codes permitidos: " + ", ".join(allowed_codes))
            reason_code = input("Reason code: ").strip().upper()
            if reason_code not in DECISION_REASON_CODES[decision] | EXCEPTION_REASON_CODES:
                print("Reason code inválido para la decisión.")
                continue
            note = input("Nota humana opcional: ").strip()
            if reason_code in NOTE_REQUIRED_REASON_CODES and not note:
                print(f"La nota es obligatoria para {reason_code}.")
                continue
            record = build_decision_record(
                candidate, decision=decision, reason_code=reason_code, note=note,
                actor=actor, bindings=bindings,
            )
            decisions[record["candidate_id"]] = record
            atomic_write_jsonl(decisions_path, decisions)
            try:
                append_audit(current_dir / AUDIT_FILE, record)
            except OSError as error:
                raise RuntimeError(
                    "authoritative decision persisted, but auxiliary audit append failed"
                ) from error
            break
    print(f"Revisión completa: {len(decisions)}/{len(queue)} decisiones persistidas. Ejecute el admission gate dry-run.")
    return 0


def supersede_individual_decision(
    current_dir: Path, canon_root: Path, *, candidate_id: str, decision: str,
    reason_code: str, note: str, actor: str, confirmation: str,
) -> dict[str, Any]:
    if confirmation != DECISION_SUPERSESSION_CONFIRMATION:
        raise ValueError(f"exact confirmation required: {DECISION_SUPERSESSION_CONFIRMATION}")
    if not note.strip():
        raise ValueError("human_review_note required for manual supersession")
    actor = validate_actor(actor)
    bindings = current_bindings(current_dir, canon_root)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    by_id = {str(row.get("candidate_id") or ""): row for row in queue}
    if candidate_id not in by_id:
        raise ValueError("candidate_id is not in current review queue")
    decisions_path = current_dir / DECISIONS_FILE
    decisions = load_existing_decisions(decisions_path, set(by_id), bindings)
    previous = decisions.get(candidate_id)
    if previous is None:
        raise ValueError("candidate has no current decision to supersede")
    record = build_decision_record(
        by_id[candidate_id], decision=decision, reason_code=reason_code, note=note,
        actor=actor, bindings=bindings, supersedes_decision_hash=decision_hash(previous),
    )
    decisions[candidate_id] = record
    atomic_write_jsonl(decisions_path, decisions)
    try:
        append_audit(current_dir / AUDIT_FILE, record, previous=previous)
    except OSError as error:
        raise RuntimeError("authoritative supersession persisted, but auxiliary audit append failed") from error
    return record


def render_batch_preview(preview: dict[str, Any]) -> None:
    print(f"\nGrupo: {json.dumps(preview['selection_rule'], ensure_ascii=False, sort_keys=True)}")
    print(f"Batch ID: {preview['batch_id']}")
    print(f"Candidatas: {preview['candidate_count']}")
    print(f"Decisión propuesta: {preview['proposed_decision']}")
    print(f"Razón propuesta: {preview['proposed_reason_code']}")
    print(f"Exclusiones: {len(preview['exclusions'])}")
    print(f"Hash: {preview['candidate_set_hash']}")
    print("Ejemplos:")
    for example in preview["examples"]:
        print(f"  - {example['candidate_id']} | {example['predicate']} | {example['source']} -> {example['target']}")


def run_batch_review(current_dir: Path, canon_root: Path, gate_report_path: Path, actor: str) -> int:
    actor = validate_actor(actor)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    gate_report = load_json(gate_report_path)
    bindings = current_bindings(current_dir, canon_root)
    decisions = load_existing_decisions(
        current_dir / DECISIONS_FILE,
        {str(row.get("candidate_id") or "") for row in queue}, bindings,
    )
    previews = build_batch_previews(queue, gate_report, decided_ids=set(decisions))
    if not previews:
        print("No existen lotes pendientes.")
        return 0
    for preview in previews:
        render_batch_preview(preview)
    selected_id = input("Batch ID a revisar [q=salir]: ").strip()
    if selected_id.lower() == "q":
        return 0
    selected = next((item for item in previews if item["batch_id"] == selected_id), None)
    if selected is None:
        raise ValueError("batch_id is not in current preview")
    raw_exclusions = input("Candidate IDs a excluir (separados por coma, vacío=ninguno): ").strip()
    exclusions = {item.strip() for item in raw_exclusions.split(",") if item.strip()}
    outside_selected = exclusions - set(selected["candidate_ids"])
    if outside_selected:
        raise ValueError(f"exclusions outside selected batch: {sorted(outside_selected)}")
    previews = build_batch_previews(queue, gate_report, exclusions=exclusions, decided_ids=set(decisions))
    selected = next((item for item in previews if item["batch_id"] == selected_id), None)
    if selected is None:
        raise ValueError("all candidates in selected batch were excluded")
    render_batch_preview(selected)
    note = input("Nota común opcional: ").strip()
    confirmation = input(f"Escriba exactamente {BATCH_CONFIRMATION}: ").strip()
    persisted = persist_batch_preview(
        current_dir, canon_root, preview=selected, actor=actor,
        confirmation=confirmation, note=note,
    )
    if not persisted:
        print("Batch cancelado; no se escribió ninguna decisión.")
        return 0
    print(f"Batch persistido: {persisted} decisiones individuales ligadas a {selected_id}.")
    if exclusions:
        print(f"Exclusiones pendientes para revisión individual: {len(exclusions)}.")
    return 0


def render_multi_batch_inventory(
    inventory: list[dict[str, Any]], bindings: dict[str, str],
) -> None:
    pending = [item for item in inventory if item["pending_candidates"]]
    resolved = [item for item in inventory if item["status"] == "resolved_idempotent"]
    print("\nInventario compacto de lotes current")
    print(f"Lotes pendientes: {len(pending)}; lotes resueltos omitidos: {len(resolved)}")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    signatures: dict[str, dict[str, Any]] = {}
    for item in pending:
        signature = batch_compatibility_signature(item["full_preview"], bindings)
        key = json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        signatures[key] = signature
        groups[key].append(item)
    for index, key in enumerate(sorted(groups), start=1):
        items = sorted(groups[key], key=lambda item: item["batch_id"])
        signature = signatures[key]
        print(
            f"\nGrupo compatible {index}: {len(items)} lotes, "
            f"{sum(item['pending_candidates'] for item in items)} candidatas pendientes"
        )
        print(
            f"  decisión={signature['decision_proposed']} | razón={signature['reason_code']} | "
            f"policy={signature['review_policy_id']} | treatment={signature['treatment_class']}"
        )
        print(
            "  batch_ids: "
            + ", ".join(
                f"{item['batch_id']}[pending={item['pending_candidates']},"
                f"reviewed={item['already_reviewed_candidates']}]"
                for item in items
            )
        )


def render_multi_batch_preview(preview: dict[str, Any]) -> None:
    print("\nResumen consolidado — revisión múltiple gobernada")
    print(f"Operación: {preview['multi_review_operation_id']}")
    print(f"Lotes seleccionados: {preview['selected_batches']}")
    print(f"Candidatas pendientes: {preview['pending_candidates']}")
    print(f"Candidatas ya revisadas compatibles: {preview['already_reviewed_candidates']}")
    print(f"Decisión: {preview['decision']}")
    print(f"Razón: {preview['reason_code']}")
    print(f"Política: {preview['review_policy_id']}")
    print(f"Exclusiones: {preview['excluded_candidates']}")
    signature = preview["compatibility_signature"]
    print(f"Canon hash: {signature['canon_hash']}")
    print(f"Candidate manifest hash: {signature['candidate_manifest_hash']}")
    print(f"Reconciliation manifest hash: {signature['reconciliation_manifest_hash']}")
    print("Batch IDs: " + ", ".join(preview["selected_batch_ids"]))
    if preview["examples"]:
        print("Muestra limitada:")
        for example in preview["examples"]:
            print(
                f"  - {example['batch_id']} | {example['candidate_id']} | "
                f"{example['predicate']} | {example['source']} -> {example['target']}"
            )
    print("Confirmación requerida: " + preview["confirmation_required"])


def run_multiple_batch_review(
    current_dir: Path, canon_root: Path, gate_report_path: Path, actor: str,
) -> int:
    actor = validate_actor(actor)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    gate_report = load_json(gate_report_path)
    bindings = current_bindings(current_dir, canon_root)
    decisions = load_existing_decisions(
        current_dir / DECISIONS_FILE,
        {str(row.get("candidate_id") or "") for row in queue},
        bindings,
    )
    inventory = build_batch_inventory(queue, gate_report, decisions)
    pending = [item for item in inventory if item["pending_candidates"]]
    if not pending:
        print("No existen lotes pendientes; la autoridad current ya está completa.")
        return 0
    render_multi_batch_inventory(inventory, bindings)
    try:
        raw_selection = input("Batch IDs homogéneos (separados por coma; q=salir): ").strip()
        if raw_selection.lower() == "q":
            print("Revisión múltiple cancelada; no se escribió ninguna decisión.")
            return 0
        selected_ids = parse_multi_batch_ids(raw_selection)
        preview = build_multi_batch_preview(inventory, selected_ids, bindings)
        render_multi_batch_preview(preview)
        note = input("Nota común opcional: ").strip()
        confirmation = input(
            f"Escriba exactamente {preview['confirmation_required']}: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nRevisión múltiple interrumpida; no se escribió ninguna decisión.")
        return 0
    result = persist_multi_batch_preview(
        current_dir,
        canon_root,
        gate_report=gate_report,
        preview=preview,
        actor=actor,
        confirmation=confirmation,
        note=note,
    )
    if result["cancelled"]:
        print("Confirmación incorrecta; no se escribió ninguna decisión.")
        return 0
    print(
        f"Operación múltiple {result['multi_review_operation_id']}: "
        f"{result['persisted']} decisiones individuales persistidas; "
        f"{result['already_reviewed']} ya revisadas compatibles omitidas idempotentemente."
    )
    print("El admission gate no fue ejecutado. Canon protegido.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S0181 current human review; never applies canon changes.")
    parser.add_argument("--current-dir", type=Path, default=DEFAULT_CURRENT_DIR)
    parser.add_argument("--canon-root", type=Path, default=DEFAULT_CANON_ROOT)
    parser.add_argument("--reviewer", default=None, help="identity of the human operator")
    parser.add_argument("--status", action="store_true", help="show review counts without writing")
    parser.add_argument("--preview-batches", action="store_true", help="print deterministic batch previews without writing")
    parser.add_argument("--review-batches", action="store_true", help="open governed batch review")
    parser.add_argument(
        "--review-multiple-batches",
        action="store_true",
        help="open one governed confirmation for multiple homogeneous pending batches",
    )
    parser.add_argument("--apply-batch", metavar="BATCH_ID", help="persist one previously previewed batch")
    parser.add_argument(
        "--candidate-set-hash",
        help="exact candidate-set hash printed by --preview-batches; required with --apply-batch",
    )
    parser.add_argument("--exclude", action="append", default=[], help="candidate ID excluded from batch preview")
    parser.add_argument("--gate-report", type=Path, default=DEFAULT_GATE_REPORT)
    parser.add_argument("--supersede-current", action="store_true", help="archive and retire legacy current authority")
    parser.add_argument("--supersede-candidate", metavar="CANDIDATE_ID")
    parser.add_argument("--decision", choices=sorted(DECISIONS))
    parser.add_argument("--reason-code")
    parser.add_argument("--note", default="")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--audit-root", type=Path, default=DEFAULT_S0181_AUDIT_ROOT)
    args = parser.parse_args(argv)
    if args.status:
        bindings = current_bindings(args.current_dir, args.canon_root)
        queue = load_jsonl(args.current_dir / QUEUE_FILE)
        raw = load_jsonl(args.current_dir / DECISIONS_FILE)
        official = [row for row in raw if row.get("schema_version") == SCHEMA_HUMAN_DECISION_LINE]
        legacy = [row for row in raw if row.get("schema_version") == SCHEMA_HUMAN_DECISION_LINE_LEGACY]
        if official:
            load_existing_decisions(
                args.current_dir / DECISIONS_FILE,
                {str(x.get("candidate_id") or "") for x in queue}, bindings,
            )
        print(json.dumps({
            "queue": len(queue), "official_decisions": len(official),
            "legacy_decisions_pending_supersession": len(legacy),
            "pending": len(queue) - len(official), **bindings,
        }, indent=2))
        return 0
    try:
        if args.preview_batches or args.apply_batch:
            queue = load_jsonl(args.current_dir / QUEUE_FILE)
            gate_report = load_json(args.gate_report)
            raw = load_jsonl(args.current_dir / DECISIONS_FILE)
            decided_ids = {
                str(row.get("candidate_id") or "")
                for row in raw if row.get("schema_version") == SCHEMA_HUMAN_DECISION_LINE
            }
            previews = build_batch_previews(
                queue, gate_report, exclusions=set(args.exclude), decided_ids=decided_ids,
            )
            if args.preview_batches:
                print(json.dumps({
                    "schema_version": "relation-human-review-batch-preview-set/v1",
                    "batch_count": len(previews),
                    "candidate_count": sum(item["candidate_count"] for item in previews),
                    "previews": previews,
                    "writes_performed": False,
                }, ensure_ascii=False, indent=2, sort_keys=True))
                return 0
            selected = next((item for item in previews if item["batch_id"] == args.apply_batch), None)
            if selected is None:
                raise ValueError("batch_id is not in current preview")
            if not args.candidate_set_hash or args.candidate_set_hash != selected["candidate_set_hash"]:
                raise ValueError("--candidate-set-hash must match the current batch preview")
            actor = args.reviewer if args.reviewer is not None else ""
            count = persist_batch_preview(
                args.current_dir, args.canon_root, preview=selected, actor=actor,
                confirmation=args.confirmation, note=args.note,
            )
            print(json.dumps({"persisted": count, "batch_id": args.apply_batch}, indent=2))
            return 0 if count else 2
        actor = args.reviewer if args.reviewer is not None else input("Identidad del revisor humano: ")
        actor = validate_actor(actor)
        if args.supersede_current:
            manifest = supersede_legacy_current(
                args.current_dir, args.canon_root, args.audit_root, actor=actor,
                note=args.note, confirmation=args.confirmation,
            )
            print(json.dumps({"supersession_manifest": str(manifest), "current_authority_reset": True}, indent=2))
            return 0
        if args.supersede_candidate:
            if not args.decision or not args.reason_code:
                raise ValueError("--decision and --reason-code are required")
            record = supersede_individual_decision(
                args.current_dir, args.canon_root, candidate_id=args.supersede_candidate,
                decision=args.decision, reason_code=args.reason_code, note=args.note,
                actor=actor, confirmation=args.confirmation,
            )
            print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.review_batches:
            return run_batch_review(args.current_dir, args.canon_root, args.gate_report, actor)
        if args.review_multiple_batches:
            return run_multiple_batch_review(args.current_dir, args.canon_root, args.gate_report, actor)
    except ValueError as error:
        print(f"[ERROR] {error}")
        return 2
    return run_review(args.current_dir, args.canon_root, actor)


if __name__ == "__main__":
    raise SystemExit(main())
