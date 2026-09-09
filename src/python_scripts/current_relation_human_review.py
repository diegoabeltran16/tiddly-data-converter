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
import uuid
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
import relation_admission_gate as admission_gate
from current_relational_authority import (
    CurrentRelationalAuthorityError,
    compare_and_swap_current_pointer,
    resolve_current_relational_authority,
)
import current_relation_review_taxonomy as review_taxonomy


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_CURRENT_DIR = REPO_ROOT / "data/out/local/pipeline/relation_candidates/current"
DEFAULT_CANON_ROOT = REPO_ROOT / "data/out/local"
DEFAULT_S0181_AUDIT_ROOT = DEFAULT_CANON_ROOT / "audit" / "s0181"
DEFAULT_GATE_REPORT = DEFAULT_CANON_ROOT / "audit" / "relation_admission" / "current" / "admission_gate_dry_run.json"

DECISIONS_FILE = "human_review_decisions.jsonl"
EFFECTIVE_DECISIONS_FILE = "effective_human_review_decisions.jsonl"
AUDIT_FILE = "human_review_audit_log.jsonl"
QUEUE_FILE = "ready_for_human_review.jsonl"
MANIFEST_FILES = ("current_candidate_manifest.json", "reconciliation_manifest.json")
DECISIONS = {"approved_for_admission", "rejected", "deferred"}
MISSING = "no disponible"
BATCH_CONFIRMATION = "CONFIRM REVIEW BATCH"
CURRENT_BATCH_CONFIRMATION_PREFIX = "CONFIRM CURRENT REVIEW BATCH"
CURRENT_CANDIDATE_CONFIRMATION_PREFIX = "CONFIRM CANDIDATE"
MULTI_BATCH_CONFIRMATION_PREFIX = "CONFIRM MULTIPLE REVIEW BATCHES"
SUPERSESSION_CONFIRMATION = "SUPERSEDE CURRENT HUMAN REVIEW"
DECISION_SUPERSESSION_CONFIRMATION = "CONFIRM REVIEW SUPERSESSION"
DECISION_INITIAL_CONFIRMATION = "CONFIRM INITIAL REVIEW DECISION"
TECHNICAL_SUPERSESSION_CONFIRMATION_PREFIX = "CONFIRM CURRENT TECHNICAL SUPERSESSION"
TECHNICAL_SUPERSESSION_GATE_FAMILY_PREFIX = "GATE-020"
TECHNICAL_SUPERSESSION_DECISION = "deferred"
TECHNICAL_SUPERSESSION_REASON_CODE = "LIFECYCLE_UNRESOLVED"
TECHNICAL_SUPERSESSION_RECEIPTS_FILE = "current_technical_supersession_receipts.jsonl"
SUPERSESSION_REASON = "FREE_TEXT_RATIONALE_NOT_AUDITABLE"
MIGRATION_REPORT_SCHEMA = "human-decision-migration-report/v1"
MIGRATION_REPORT_FILE = "human_decision_migration_report.json"
MIGRATION_BACKUP_FILE = "human_review_decisions.pre-migration.jsonl"
MIGRATION_REASON_CODES = frozenset({
    "many_to_one_current_id_collision",
    "duplicate_source_decision_id",
    "duplicate_target_current_id",
    "source_decision_missing_identity",
    "source_decision_invalid",
    "current_candidate_not_found",
    "current_binding_stale",
    "candidate_manifest_hash_mismatch",
    "reconciliation_manifest_hash_mismatch",
    "historical_candidate_hash_mismatch",
    "migration_plan_not_atomic",
})
MIGRATION_PRESERVED_FIELDS = (
    "human_review_decision",
    "human_review_reason_code",
    "human_review_note",
    "human_review_actor",
    "human_review_timestamp",
    "approval_scope",
    "decision_mode",
    "decision_batch_id",
    "review_policy_id",
    "multi_review_operation_id",
    "supersedes_decision_hash",
    "evidence",
    # S0186 Unit H8 policy-derived provenance fields.
    "policy_version",
    "policy_hash",
    "human_authorization_id",
    "authorization_scope",
)


class ExistingDecisions(dict[str, dict[str, Any]]):
    """Current decisions plus their authoritative preservation classification."""

    def __init__(self) -> None:
        super().__init__()
        self.preserved_historical: set[str] = set()
        self.current_direct: set[str] = set()
        self.invalid_or_stale: set[str] = set()


class HumanDecisionMigrationBlocked(ValueError):
    """Fail-closed migration result with a persisted structured report."""

    def __init__(self, reason_codes: list[str], report_path: Path):
        self.reason_codes = reason_codes
        self.report_path = report_path
        super().__init__(", ".join(reason_codes))


class CurrentReviewWriteBlocked(ValueError):
    """Fail-closed result for the current single-batch write boundary."""

    def __init__(self, *reason_codes: str):
        self.reason_codes = sorted(set(reason_codes)) or ["review_write_validation_failed"]
        super().__init__(", ".join(self.reason_codes))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decision_authority_path(current_dir: Path) -> Path:
    """Use rebaseline-derived current authority while retaining source history."""
    effective = current_dir / EFFECTIVE_DECISIONS_FILE
    return effective if effective.is_file() else current_dir / DECISIONS_FILE


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


def resolve_current_gate_report(
    canon_root: Path,
    requested: Path,
) -> Path:
    """Resolve the governed delta gate from the atomic generation pointer.

    Legacy READY_FOR_AUTHORIZATION runs continue using the requested report.
    A current human-delta bundle owns its own immutable gate report, so batch
    review must not accidentally consume the older admission/current file.
    """
    pointer_path = canon_root / "audit" / "relation_admission" / "current_generation.json"
    if not pointer_path.is_file():
        return requested
    try:
        pointer = load_json(pointer_path)
        if pointer.get("terminal_state") != "READY_FOR_HUMAN_DELTA_REVIEW":
            return requested
        bundle = Path(str(pointer.get("bundle_path") or ""))
        manifest_path = bundle / "bundle_manifest.json"
        if (
            not bundle.is_dir()
            or not manifest_path.is_file()
            or sha256_file(manifest_path) != pointer.get("bundle_manifest_hash")
        ):
            return requested
        manifest = load_json(manifest_path)
        item = (manifest.get("artifacts") or {}).get("admission_gate") or {}
        resolved = bundle / str(item.get("path") or "")
        if resolved.is_file() and sha256_file(resolved) == item.get("sha256"):
            return resolved
    except (OSError, ValueError, json.JSONDecodeError):
        return requested
    return requested


# A candidate_id is only an operational identity inside one relational
# generation.  Batch previews must therefore bind every input that can change
# between preview and confirmation; historical ``current`` files are evidence,
# never a fallback authority.
BATCH_GENERATION_REASON_CODES = frozenset({
    "batch_preview_physical_canon_stale",
    "batch_preview_relational_generation_missing",
    "batch_preview_candidate_manifest_stale",
    "batch_preview_reconciliation_manifest_stale",
    "batch_preview_human_decisions_stale",
    "batch_preview_admission_gate_stale",
    "batch_preview_pending_queue_stale",
    "batch_preview_candidate_outside_current_queue",
    "batch_preview_candidate_not_pending",
    "batch_preview_duplicate_candidate",
    "batch_preview_partition_count_mismatch",
    "batch_preview_generation_changed_during_build",
    "batch_confirmation_preview_stale",
    "batch_confirmation_generation_changed",
})

CURRENT_DELTA_CLASSES = tuple(review_taxonomy.RECONCILIATION_CLASS_TO_REVIEW_REASON)
CURRENT_REVIEW_REQUIRED_ARTIFACTS = frozenset({
    "pending_queue", "batch_inventory", "current_human_delta",
    "review_rebaseline", "review_rebaseline_checkpoint",
    "independent_decision_preservation",
})


def _review_candidate_hash(candidate: dict[str, Any]) -> str:
    """Stable content hash used to bind a displayed candidate to its batch."""
    encoded = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _live_decisions_beyond_bundle(
    canon_root: Path, pending: set[str], bundle_effective_ids: set[str],
) -> tuple[set[str], dict[str, Any]]:
    """Candidates already effectively decided in the LIVE decision authority
    that the published bundle's own frozen effective_decisions snapshot does
    not yet know about.

    governed_relation_admission_policy.materialize_authorized_policy() (and,
    by the same pattern, any other writer) persists decisions straight to
    current/effective_human_review_decisions.jsonl without republishing a
    review-state bundle -- exactly the gap S0186 Unit H already fixed for
    generational preservation (prepare_current_relational_generation.py).
    This is the SAME gap surfacing in a second consumer: the human batch
    review surface built its "pending" set purely from the bundle's frozen
    snapshot, so a candidate decided by policy governance after publish kept
    reappearing in preview/batches as if still undecided.

    This is deliberately NOT the same thing as current_delta_covered_candidate
    (a pending candidate present in the BUNDLE's OWN effective_decisions --
    bundle self-contradiction, real corruption, still fail-closed below).
    A live-only decision is the normal, expected effect of a decision
    channel advancing between publish and review; it must be excluded from
    the reviewable set, not treated as an integrity violation.

    Each candidate is independently re-validated; a candidate whose live row
    fails validation is NOT excluded (it fails closed back into "pending",
    to surface the anomaly through review rather than hide it).
    """
    current_dir = canon_root / "pipeline" / "relation_candidates" / "current"
    decisions_path = decision_authority_path(current_dir)
    report: dict[str, Any] = {
        "schema_version": "current-human-delta-live-decision-exclusion/v1",
        "checked": False,
        "excluded_count": 0,
        "excluded_candidate_ids": [],
        "rejected": [],
    }
    if not decisions_path.is_file():
        return set(), report
    report["checked"] = True
    live_by_id = {
        str(row.get("candidate_id") or ""): row
        for row in load_jsonl(decisions_path)
    }
    candidate_ids = (pending & set(live_by_id)) - bundle_effective_ids
    excluded: set[str] = set()
    for candidate_id in sorted(candidate_ids):
        row = live_by_id[candidate_id]
        errors = validate_human_review_decision_record(row)
        if errors:
            report["rejected"].append({"candidate_id": candidate_id, "errors": errors})
            continue
        excluded.add(candidate_id)
    report["excluded_count"] = len(excluded)
    report["excluded_candidate_ids"] = sorted(excluded)
    return excluded, report


def resolve_current_human_delta_surface(canon_root: Path) -> dict[str, Any]:
    """Resolve the review surface only from the atomically published bundle.

    This is deliberately separate from the legacy low-level batch helpers:
    callers that have a current pointer never obtain operational data from
    ``pipeline/relation_candidates/current``.  The returned inventory is
    fail-closed; a pending candidate without one governed delta class cannot
    reach preview, let alone confirmation.
    """
    try:
        authority = resolve_current_relational_authority(canon_root)
    except CurrentRelationalAuthorityError as error:
        return {
            "allowed": False,
            "reason_codes": ["current_review_authority_invalid", *error.reason_codes],
        }
    manifest = authority["manifest"]
    reasons: list[str] = []
    if authority["terminal_state"] != "READY_FOR_HUMAN_DELTA_REVIEW":
        reasons.append("current_terminal_not_ready_for_human_delta_review")
    if manifest.get("next_action") != "REVIEW_CURRENT_RELATIONAL_DELTA":
        reasons.append("current_next_action_not_review_delta")
    artifacts = authority["artifacts"]
    missing = sorted(CURRENT_REVIEW_REQUIRED_ARTIFACTS - set(artifacts))
    if missing:
        reasons.append("current_review_authority_invalid")
        return {
            "allowed": False, "reason_codes": sorted(set(reasons)),
            "missing_artifacts": missing,
        }
    try:
        delta = load_json(artifacts["pending_queue"])
        batch_inventory = load_json(artifacts["batch_inventory"])
        delta_manifest = load_json(artifacts["current_human_delta"])
        candidate_manifest = load_json(artifacts["candidate_manifest"])
        reconciliation = load_json(artifacts["reconciliation_manifest"])
        checkpoint = load_json(artifacts["review_rebaseline_checkpoint"])
        queue = load_jsonl(artifacts["ready_queue"])
        effective = load_jsonl(artifacts["effective_decisions"])
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "allowed": False,
            "reason_codes": ["current_review_authority_invalid"],
            "error": str(error),
        }

    relation_generation_id = authority["relation_generation_id"]
    review_state_id = authority["review_state_id"]
    for value in (delta, batch_inventory, delta_manifest, checkpoint):
        if value.get("relation_generation_id") != relation_generation_id or value.get("review_state_id") != review_state_id:
            reasons.append("current_delta_binding_mismatch")
    if candidate_manifest.get("current") is not True or reconciliation.get("current") is not True:
        reasons.append("current_delta_binding_mismatch")

    raw_pending = list(delta.get("pending_candidate_ids") or [])
    inventory_pending = list(batch_inventory.get("pending_candidate_ids") or [])
    manifest_pending = list(delta_manifest.get("pending_candidate_ids") or [])
    pending = set(raw_pending)
    duplicate_ids = {
        candidate_id for candidate_id in raw_pending
        if raw_pending.count(candidate_id) > 1
    }
    if int(delta.get("pending") or 0) != len(raw_pending):
        reasons.append("current_delta_conservation_invalid")
    if pending != set(inventory_pending) or pending != set(manifest_pending):
        reasons.append("current_delta_conservation_invalid")

    taxonomy_validation = review_taxonomy.validate_published_review_taxonomy(
        raw_pending, delta.get("review_candidates") or [],
    )
    taxonomy_by_id = {
        str(row.get("candidate_id") or ""): row
        for row in delta.get("review_candidates") or []
        if str(row.get("candidate_id") or "")
    }
    classes = {
        candidate_id: str(row["reconciliation_class"])
        for candidate_id, row in taxonomy_by_id.items()
        if row.get("reconciliation_class") is not None
    }
    review_reasons = {
        candidate_id: str(row["review_reason"])
        for candidate_id, row in taxonomy_by_id.items()
        if row.get("review_reason")
    }
    declared_class_ids = {
        name: {str(candidate_id) for candidate_id in delta.get(name) or []}
        for name in CURRENT_DELTA_CLASSES
    }
    derived_class_ids = {
        name: {candidate_id for candidate_id, value in classes.items() if value == name}
        for name in CURRENT_DELTA_CLASSES
    }
    declared_reason_ids = {
        reason: {str(candidate_id) for candidate_id in (delta.get("review_reasons") or {}).get(reason, [])}
        for reason in review_taxonomy.ALLOWED_REVIEW_REASONS
    }
    derived_reason_ids = {
        reason: {candidate_id for candidate_id, value in review_reasons.items() if value == reason}
        for reason in review_taxonomy.ALLOWED_REVIEW_REASONS
    }
    if declared_class_ids != derived_class_ids or declared_reason_ids != derived_reason_ids:
        reasons.append("current_delta_taxonomy_binding_mismatch")
    if (
        delta.get("review_reason_counts") != taxonomy_validation["review_reason_counts"]
        or batch_inventory.get("review_reason_counts") != taxonomy_validation["review_reason_counts"]
        or delta_manifest.get("review_reason_counts") != taxonomy_validation["review_reason_counts"]
    ):
        reasons.append("current_delta_taxonomy_binding_mismatch")
    invalid_ids = {str(candidate_id) for candidate_id in list(delta.get("invalid") or [])}
    queue_by_id: dict[str, dict[str, Any]] = {}
    for candidate in queue:
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id or candidate_id in queue_by_id:
            duplicate_ids.add(candidate_id or "<missing>")
        else:
            queue_by_id[candidate_id] = candidate
    bundle_effective_ids = {str(row.get("candidate_id") or "") for row in effective}
    covered = pending & bundle_effective_ids
    live_excluded_ids, live_exclusion_report = _live_decisions_beyond_bundle(
        canon_root, pending, bundle_effective_ids,
    )
    reviewable_pending = pending - live_excluded_ids
    unaccounted = pending - set(queue_by_id)
    missing_review_reason = set(
        taxonomy_validation["missing_review_reason_candidate_ids"]
        + taxonomy_validation["missing_candidate_ids"]
    )
    unsupported_review_reason = set(
        taxonomy_validation["unsupported_review_reason_candidate_ids"]
        + taxonomy_validation["inconsistent_candidate_ids"]
        + taxonomy_validation["outside_candidate_ids"]
    )
    duplicate_ids.update(taxonomy_validation["duplicate_candidate_ids"])
    invalid = set(invalid_ids)
    for candidate_id in pending & set(queue_by_id):
        disposition = ((queue_by_id[candidate_id].get("reconciliation") or {}).get("disposition"))
        if disposition not in (None, "ready_for_review"):
            invalid.add(candidate_id)
    if duplicate_ids:
        reasons.append("current_delta_duplicate_candidate")
    if covered:
        reasons.append("current_delta_covered_candidate")
    if invalid:
        reasons.append("current_delta_invalid_candidate")
    if unaccounted:
        reasons.append("current_delta_unaccounted_candidate")
    if missing_review_reason:
        reasons.append("current_review_reason_missing")
    if unsupported_review_reason:
        reasons.append("current_review_reason_unsupported")
    if not taxonomy_validation["valid"] or len(pending) != sum(
        taxonomy_validation["review_reason_counts"].values()
    ):
        reasons.append("current_delta_conservation_invalid")

    candidates = []
    for candidate_id in sorted(reviewable_pending):
        candidate = queue_by_id.get(candidate_id, {})
        candidates.append({
            "candidate_id": candidate_id,
            "candidate_hash": _review_candidate_hash(candidate) if candidate else None,
            "reconciliation_class": classes.get(candidate_id),
            "review_reason": review_reasons.get(candidate_id),
            "review_reason_evidence": (taxonomy_by_id.get(candidate_id) or {}).get("evidence"),
            "source": candidate.get("source"),
            "predicate": candidate.get("relation_type") or (candidate.get("relation") or {}).get("type"),
            "target": candidate.get("target"),
            "evidence": candidate.get("evidence"),
            "review_status": "awaiting_human_review" if candidate_id not in covered else "already_covered",
        })
    inventory = {
        "relation_generation_id": relation_generation_id,
        "review_state_id": review_state_id,
        "bundle_manifest_hash": authority["bundle_manifest_hash"],
        "total_pending": len(reviewable_pending),
        "total_pending_declared_by_bundle": len(pending),
        "live_decided_excluded": len(live_excluded_ids),
        "live_decision_exclusion": live_exclusion_report,
        **{
            name: sum(
                1 for candidate_id, value in classes.items()
                if value == name and candidate_id in reviewable_pending
            )
            for name in CURRENT_DELTA_CLASSES
        },
        **{
            reason: sum(
                1 for candidate_id, value in review_reasons.items()
                if value == reason and candidate_id in reviewable_pending
            )
            for reason in review_taxonomy.ALLOWED_REVIEW_REASONS
        },
        "invalid": len(invalid), "duplicated": len(duplicate_ids), "covered": len(covered),
        "missing_review_reason": len(missing_review_reason),
        "unsupported_review_reason": len(unsupported_review_reason),
        "unclassified": len(missing_review_reason),
        "unaccounted": len(unaccounted),
        "conservation_valid": not reasons,
        "candidates": candidates,
    }
    return {
        "allowed": not reasons,
        "reason_codes": sorted(set(reasons)),
        "authority": authority,
        "bundle_path": authority["bundle_path"],
        "artifacts": artifacts,
        "inventory": inventory,
    }


SEMANTIC_REVIEW_DECISION_FIELDS = (
    "candidate_id", "candidate_hash", "human_review_decision",
    "human_review_reason_code", "human_review_note", "human_review_actor",
    "approval_scope", "decision_mode", "review_policy_id",
    "human_confirmation",
)


def semantic_review_decisions_hash(rows: list[dict[str, Any]]) -> str:
    """Hash decision meaning without time, paths or physical hash bindings."""
    normalized = [
        {
            field: row.get(field)
            for field in SEMANTIC_REVIEW_DECISION_FIELDS
            if field in row
        }
        for row in rows
    ]
    normalized.sort(key=lambda row: str(row.get("candidate_id") or ""))
    return semantic_hash(normalized)


def _current_review_state_semantic_hash(surface: dict[str, Any]) -> str:
    inventory = surface["inventory"]
    decisions_path = (surface.get("artifacts") or {}).get("effective_decisions")
    decisions = (
        load_jsonl(decisions_path)
        if isinstance(decisions_path, Path) and decisions_path.is_file()
        else []
    )
    pending = [{
        key: item.get(key)
        for key in (
            "candidate_id", "candidate_hash", "reconciliation_class",
            "review_reason",
        )
    } for item in inventory["candidates"]]
    pending.sort(key=lambda item: str(item.get("candidate_id") or ""))
    return semantic_hash({
        "identity_schema": "current-review-state-semantic/v2",
        "relation_generation_id": inventory["relation_generation_id"],
        "effective_decisions_semantic_hash": semantic_review_decisions_hash(
            decisions
        ),
        "pending_review": pending,
    })


def build_current_human_delta_batches(
    surface: dict[str, Any], *, identity_schema: str = "v2",
) -> list[dict[str, Any]]:
    """Build stable, class-homogeneous batches without selecting a decision."""
    if not surface.get("allowed"):
        raise ValueError("current delta review surface is not admissible")
    inventory = surface["inventory"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in inventory["candidates"]:
        grouped[str(candidate["review_reason"])].append(candidate)
    batches: list[dict[str, Any]] = []
    for reason in review_taxonomy.ALLOWED_REVIEW_REASONS:
        members = sorted(grouped.get(reason, []), key=lambda item: item["candidate_id"])
        if not members:
            continue
        reconciliation_classes = {item["reconciliation_class"] for item in members}
        if len(reconciliation_classes) != 1:
            raise ValueError("current delta batch mixes reconciliation classes")
        classification = next(iter(reconciliation_classes))
        semantic = {
            "relation_generation_id": inventory["relation_generation_id"],
            "review_reason": reason,
            "reconciliation_class": classification,
            "candidate_ids": [item["candidate_id"] for item in members],
            "candidate_hashes": [item["candidate_hash"] for item in members],
        }
        if identity_schema == "v1":
            semantic["review_state_id"] = inventory["review_state_id"]
            semantic["bundle_manifest_hash"] = inventory["bundle_manifest_hash"]
        elif identity_schema != "v2":
            raise ValueError("unsupported current review batch identity schema")
        else:
            semantic["identity_schema"] = "current-human-delta-review-batch/v2"
            semantic["source_review_state_semantic_hash"] = (
                _current_review_state_semantic_hash(surface)
            )
        batch_hash = "sha256:" + hashlib.sha256(
            json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        batches.append({
            "schema_version": f"current-human-delta-review-batch/{identity_schema}",
            "batch_id": "hrb_" + batch_hash.removeprefix("sha256:")[:24],
            "batch_hash": batch_hash,
            **semantic,
            "review_state_id": inventory["review_state_id"],
            "bundle_manifest_hash": inventory["bundle_manifest_hash"],
            "candidate_count": len(members),
            "consumed": False,
            "action_required": True,
        })
    if sum(item["candidate_count"] for item in batches) != inventory["total_pending"]:
        raise ValueError("current delta batches do not conserve pending candidates")
    return batches


def current_candidate_confirmation(candidate_id: str, action: str) -> str:
    return f"{CURRENT_CANDIDATE_CONFIRMATION_PREFIX} {candidate_id} {action}"


def current_batch_confirmation(batch_id: str) -> str:
    return f"{CURRENT_BATCH_CONFIRMATION_PREFIX} {batch_id}"


def _current_review_receipts(surface: dict[str, Any]) -> list[dict[str, Any]]:
    path = surface.get("artifacts", {}).get("review_receipts")
    return load_jsonl(path) if isinstance(path, Path) and path.is_file() else []


def _validate_current_batch_proposals(
    surface: dict[str, Any], batch: dict[str, Any], proposals: list[dict[str, Any]], actor: str,
) -> list[dict[str, Any]]:
    """Validate explicit per-candidate choices without inferring any action."""
    actor = validate_actor(actor)
    expected_ids = list(batch["candidate_ids"])
    expected_hashes = dict(zip(expected_ids, batch["candidate_hashes"], strict=True))
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for proposal in proposals:
        candidate_id = str(proposal.get("candidate_id") or "")
        if not candidate_id or candidate_id in seen:
            raise CurrentReviewWriteBlocked("review_decision_conflict")
        seen.add(candidate_id)
        action = str(proposal.get("action") or proposal.get("decision") or "")
        reason_code = str(proposal.get("reason_code") or "").strip().upper()
        note = str(proposal.get("note") or "").strip()
        confirmation = str(proposal.get("human_confirmation") or "")
        if candidate_id not in expected_hashes:
            raise CurrentReviewWriteBlocked("review_candidate_changed")
        if proposal.get("candidate_hash") != expected_hashes[candidate_id]:
            raise CurrentReviewWriteBlocked("review_candidate_changed")
        if action not in DECISIONS or reason_code not in DECISION_REASON_CODES[action] | EXCEPTION_REASON_CODES:
            raise CurrentReviewWriteBlocked("review_write_validation_failed")
        if reason_code in NOTE_REQUIRED_REASON_CODES and not note:
            raise CurrentReviewWriteBlocked("review_write_validation_failed")
        if confirmation != current_candidate_confirmation(candidate_id, action):
            raise CurrentReviewWriteBlocked("review_write_validation_failed")
        normalized.append({
            "candidate_id": candidate_id,
            "candidate_hash": expected_hashes[candidate_id],
            "batch_id": batch["batch_id"],
            "batch_hash": batch["batch_hash"],
            "relation_generation_id": batch["relation_generation_id"],
            "source_review_state_id": batch["review_state_id"],
            "action": action,
            "reason_code": reason_code,
            "note": note,
            "actor": actor,
            "human_confirmation": confirmation,
        })
    if seen != set(expected_ids):
        raise CurrentReviewWriteBlocked("review_write_validation_failed")
    return sorted(normalized, key=lambda item: item["candidate_id"])


def _current_review_semantic_identity(
    surface: dict[str, Any], batch: dict[str, Any], proposals: list[dict[str, Any]],
    *, identity_schema: str = "v2",
) -> tuple[str, str]:
    semantic = {
        "source_relation_generation_id": batch["relation_generation_id"],
        "batch_id": batch["batch_id"],
        "batch_hash": batch["batch_hash"],
        "decisions": [{
            key: proposal[key]
            for key in ("candidate_id", "candidate_hash", "action", "reason_code", "note", "actor", "human_confirmation")
        } for proposal in proposals],
    }
    if identity_schema == "v1":
        semantic["source_review_state_id"] = batch["review_state_id"]
        semantic["source_bundle_manifest_hash"] = batch["bundle_manifest_hash"]
    elif identity_schema != "v2":
        raise ValueError("unsupported current review result identity schema")
    else:
        semantic["identity_schema"] = "current-single-batch-review-result/v2"
        semantic["source_review_state_semantic_hash"] = batch[
            "source_review_state_semantic_hash"
        ]
    identity_hash = semantic_hash(semantic).removeprefix("sha256:")
    return "rv_" + identity_hash[:24], "hrr_" + identity_hash[24:48]


def _rewrite_pending_delta(payload: dict[str, Any], consumed: set[str], result_review_state_id: str) -> None:
    """Apply the same conserved partition rewrite to the three delta views."""
    pending = [str(value) for value in payload.get("pending_candidate_ids") or [] if str(value) not in consumed]
    candidates = [
        value for value in payload.get("review_candidates") or []
        if str(value.get("candidate_id") or "") not in consumed
    ]
    payload["pending_candidate_ids"] = pending
    if "pending" in payload:
        payload["pending"] = len(pending)
    payload["review_state_id"] = result_review_state_id
    for classification in CURRENT_DELTA_CLASSES:
        if classification in payload:
            payload[classification] = [
                str(value) for value in payload.get(classification) or [] if str(value) not in consumed
            ]
    if "invalid" in payload:
        payload["invalid"] = [str(value) for value in payload.get("invalid") or [] if str(value) not in consumed]
    payload["review_candidates"] = candidates
    if "review_reasons" in payload or "review_reason_counts" in payload:
        by_reason = {
            reason: sorted(
                str(value.get("candidate_id")) for value in candidates
                if value.get("review_reason") == reason
            )
            for reason in review_taxonomy.ALLOWED_REVIEW_REASONS
        }
        payload["review_reasons"] = by_reason
        payload["review_reason_counts"] = {reason: len(values) for reason, values in by_reason.items()}
    payload["conservation_valid"] = len(pending) == len(candidates)


def _review_receipt_segments(
    descriptor: dict[str, Any], receipts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate and normalize the explicitly ordered cross-generation ledger."""
    schema = descriptor.get("schema_version")
    if schema == "current-review-receipt-lineage/v1":
        segments = [{
            "relation_generation_id": descriptor.get(
                "source_relation_generation_id"
            ),
            "root_review_state_id": descriptor.get("root_review_state_id"),
            "tip_review_state_id": descriptor.get("tip_review_state_id"),
            "receipt_ids": list(descriptor.get("receipt_ids") or []),
        }]
    elif schema == "current-review-receipt-lineage/v2":
        segments = list(descriptor.get("segments") or [])
    else:
        raise ValueError("review receipt lineage schema invalid")
    receipt_by_id = {
        str(receipt.get("receipt_id") or ""): receipt for receipt in receipts
    }
    if (
        "" in receipt_by_id
        or len(receipt_by_id) != len(receipts)
        or descriptor.get("integrity_verified") is not True
        or int(descriptor.get("receipt_count") or 0) != len(receipts)
        or sorted(descriptor.get("receipt_ids") or [])
        != sorted(receipt_by_id)
        or not segments
    ):
        raise ValueError("review receipt lineage conservation invalid")
    segment_ids: list[str] = []
    relation_ids: set[str] = set()
    for segment in segments:
        relation_id = str(segment.get("relation_generation_id") or "")
        receipt_ids = [str(value) for value in segment.get("receipt_ids") or []]
        if (
            not relation_id
            or relation_id in relation_ids
            or not receipt_ids
            or len(receipt_ids) != len(set(receipt_ids))
            or any(receipt_id not in receipt_by_id for receipt_id in receipt_ids)
            or any(
                receipt_by_id[receipt_id].get("source_relation_generation_id")
                != relation_id
                for receipt_id in receipt_ids
            )
        ):
            raise ValueError("review receipt segment invalid")
        relation_ids.add(relation_id)
        segment_ids.extend(receipt_ids)
    if sorted(segment_ids) != sorted(receipt_by_id):
        raise ValueError("review receipt segment coverage invalid")
    return segments


def _validate_staged_current_review_bundle(
    staged: Path, *, relation_generation_id: str, review_state_id: str,
) -> None:
    try:
        manifest = load_json(staged / "bundle_manifest.json")
        if (
            manifest.get("relation_generation_id") != relation_generation_id
            or manifest.get("review_state_id") != review_state_id
        ):
            raise ValueError("staged identity mismatch")
        resolved_artifacts: dict[str, Path] = {}
        for name, item in (manifest.get("artifacts") or {}).items():
            if not isinstance(item, dict) or str(item.get("status") or "").startswith("not_applicable"):
                continue
            raw = str(item.get("path") or "")
            path = staged / raw
            if not raw or Path(raw).is_absolute() or not path.is_file() or sha256_file(path) != item.get("sha256"):
                raise ValueError("staged artifact mismatch")
            resolved_artifacts[name] = path

        decisions = load_jsonl(resolved_artifacts["effective_decisions"])
        decisions_by_id = {
            str(row.get("candidate_id") or ""): row for row in decisions
        }
        checkpoint = load_json(resolved_artifacts["decision_checkpoint"])
        declared = list(checkpoint.get("individual_decision_hashes") or [])
        declared_by_id = {
            str(row.get("candidate_id") or ""): row for row in declared
        }
        if (
            "" in decisions_by_id
            or "" in declared_by_id
            or len(decisions_by_id) != len(decisions)
            or len(declared_by_id) != len(declared)
            or set(declared_by_id) != set(decisions_by_id)
            or int(checkpoint.get("total_decisions") or 0) != len(decisions)
            or checkpoint.get("decisions_file_hash")
            != sha256_file(resolved_artifacts["effective_decisions"])
        ):
            raise ValueError("decision checkpoint conservation mismatch")
        for candidate_id, decision in decisions_by_id.items():
            if (
                declared_by_id[candidate_id].get("decision_sha256")
                != decision_hash(decision).removeprefix("sha256:")
            ):
                raise ValueError("individual decision hash mismatch")
        classifications = Counter(
            str(row.get("classification") or "") for row in declared
        )
        for field in (
            "current_direct", "preserved_equivalent", "preserved_historical",
        ):
            if int(checkpoint.get(field) or 0) != classifications[field]:
                raise ValueError("decision classification conservation mismatch")

        delta = load_json(resolved_artifacts["pending_queue"])
        pending_ids = [
            str(value) for value in delta.get("pending_candidate_ids") or []
        ]
        queue = load_jsonl(resolved_artifacts["ready_queue"])
        queue_ids = {str(row.get("candidate_id") or "") for row in queue}
        if (
            len(set(pending_ids)) != len(pending_ids)
            or set(pending_ids).intersection(decisions_by_id)
            or set(pending_ids).union(decisions_by_id) != queue_ids
            or int(checkpoint.get("pending_delta") or 0) != len(pending_ids)
        ):
            raise ValueError("review coverage conservation mismatch")

        receipts_path = resolved_artifacts.get("review_receipts")
        receipts = load_jsonl(receipts_path) if receipts_path is not None else []
        lineage_path = resolved_artifacts.get("review_receipt_lineage")
        lineage_segments: list[dict[str, Any]] = []
        if lineage_path is not None:
            lineage = load_json(lineage_path)
            if (
                receipts_path is None
                or lineage.get("carried_review_receipts_hash")
                != sha256_file(receipts_path)
            ):
                raise ValueError("review receipt lineage hash mismatch")
            lineage_segments = _review_receipt_segments(lineage, receipts)
        historical_receipt_ids = {
            str(receipt_id)
            for segment in lineage_segments
            if segment.get("relation_generation_id") != relation_generation_id
            for receipt_id in segment.get("receipt_ids") or []
        }
        for receipt in receipts:
            if receipt.get("schema_version") not in {
                "current-single-batch-review-receipt/v1",
                "current-single-batch-review-receipt/v2",
            }:
                raise ValueError("receipt schema invalid")
            candidate_ids = [
                str(value) for value in receipt.get("candidate_ids") or []
            ]
            if str(receipt.get("receipt_id") or "") in historical_receipt_ids:
                # These hashes certify the pre-rebind decision bytes and remain
                # immutable provenance; their segment was certified upstream.
                continue
            if not set(candidate_ids).issubset(decisions_by_id):
                raise ValueError("receipt candidate binding mismatch")
            expected_hash = semantic_hash([
                decision_hash(decisions_by_id[candidate_id])
                for candidate_id in sorted(candidate_ids)
            ])
            if receipt.get("decisions_hash") != expected_hash:
                raise ValueError("receipt decision hash mismatch")
        if manifest.get("terminal_state") == "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION":
            if pending_ids or not receipts or not any(
                receipt.get("result_review_state_id") == review_state_id
                for receipt in receipts
            ):
                raise ValueError("review complete receipt conservation mismatch")

        rebaseline_path = resolved_artifacts.get("review_rebaseline")
        if rebaseline_path is not None:
            rebaseline = load_json(rebaseline_path)
            partition = rebaseline.get("current_candidate_partition") or {}
            if "reviewable_total" in partition:
                total = int(partition.get("reviewable_total") or 0)
                accounted = sum(
                    int(partition.get(field) or 0)
                    for field in (
                        "independently_covered", "human_reviewed_covered",
                        "pending_human_review", "conflict_blocked", "unaccounted",
                    )
                )
                if total != accounted:
                    raise ValueError("rebaseline candidate conservation mismatch")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise CurrentReviewWriteBlocked("review_write_validation_failed") from error


def _review_receipts_retry_semantics(
    receipt_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project receipt meaning while keeping v1 physical bindings exact."""
    receipt_fields = (
        "schema_version", "receipt_id", "source_relation_generation_id",
        "source_review_state_id", "source_review_state_semantic_hash",
        "result_review_state_id", "source_bundle_manifest_hash", "batch_id",
        "batch_hash", "candidate_ids", "candidate_hashes", "human_confirmation",
    )
    receipts: list[dict[str, Any]] = []
    for receipt in receipt_rows:
        projected = {
            field: receipt.get(field) for field in receipt_fields
        }
        if receipt.get("schema_version") == (
            "current-single-batch-review-receipt/v2"
        ):
            # V2 binds source meaning through the semantic state hash.  The
            # manifest hash and representational review-state ID remain physical
            # provenance and may differ across equivalent source publications.
            projected.pop("source_bundle_manifest_hash", None)
            projected.pop("source_review_state_id", None)
        receipts.append(projected)
    receipts.sort(key=lambda item: str(item.get("receipt_id") or ""))
    return receipts


def _review_bundle_retry_semantics(bundle: Path) -> dict[str, Any]:
    """Project only semantic state for safe reuse of a validated orphan."""
    manifest = load_json(bundle / "bundle_manifest.json")
    artifacts = manifest.get("artifacts") or {}

    def artifact_path(name: str) -> Path:
        return bundle / str((artifacts.get(name) or {}).get("path") or "")

    receipts = _review_receipts_retry_semantics(
        load_jsonl(artifact_path("review_receipts"))
    )

    def derived_payload(name: str) -> dict[str, Any]:
        payload = load_json(artifact_path(name))

        def normalize(value: Any) -> Any:
            if isinstance(value, dict):
                semantic_v2 = bool(value.get("source_review_state_semantic_hash"))
                return {
                    key: normalize(item)
                    for key, item in sorted(value.items())
                    if not (
                        semantic_v2
                        and key in {
                            "bundle_manifest_hash",
                            "source_bundle_manifest_hash",
                            "source_review_state_id",
                        }
                    )
                }
            if isinstance(value, list):
                return [normalize(item) for item in value]
            return value

        return normalize(payload)

    return {
        "relation_generation_id": manifest.get("relation_generation_id"),
        "review_state_id": manifest.get("review_state_id"),
        "terminal_state": manifest.get("terminal_state"),
        "next_action": manifest.get("next_action"),
        "effective_decisions_semantic_hash": semantic_review_decisions_hash(
            load_jsonl(artifact_path("effective_decisions"))
        ),
        "pending_queue": derived_payload("pending_queue"),
        "batch_inventory": derived_payload("batch_inventory"),
        "current_human_delta": derived_payload("current_human_delta"),
        "receipts": receipts,
    }


def _assert_current_review_source_unchanged(
    canon_root: Path,
    surface: dict[str, Any],
    *,
    protected_canon_hash: str,
    source_pointer_bytes: bytes,
) -> None:
    """Re-resolve every source binding immediately before publication."""
    if canon_hash(canon_root) != protected_canon_hash:
        raise CurrentReviewWriteBlocked("current_authority_changed")
    pointer_path = Path(surface["authority"]["pointer_path"])
    if not pointer_path.is_file() or pointer_path.read_bytes() != source_pointer_bytes:
        raise CurrentReviewWriteBlocked("current_authority_changed")
    try:
        resolved = resolve_current_relational_authority(canon_root)
    except CurrentRelationalAuthorityError as error:
        raise CurrentReviewWriteBlocked("current_authority_changed") from error
    if (
        Path(resolved["bundle_path"]) != Path(surface["bundle_path"])
        or resolved["bundle_manifest_hash"]
        != surface["inventory"]["bundle_manifest_hash"]
        or resolved["relation_generation_id"]
        != surface["inventory"]["relation_generation_id"]
        or resolved["review_state_id"]
        != surface["inventory"]["review_state_id"]
    ):
        raise CurrentReviewWriteBlocked("current_authority_changed")


def _restore_current_review_pointer_if_owned(
    pointer_path: Path,
    *,
    before: bytes,
    written: bytes | None,
) -> None:
    if written is None:
        return
    try:
        compare_and_swap_current_pointer(
            pointer_path, expected=written, replacement=before,
        )
    except CurrentRelationalAuthorityError:
        pass


def persist_current_human_delta_batch(
    canon_root: Path, *, batch: dict[str, Any], proposals: list[dict[str, Any]], actor: str,
    confirmation: str | None = None, failure_hook: str | None = None, dry_run: bool = False,
) -> dict[str, Any]:
    """Publish all decisions for exactly one current batch or publish nothing.

    dry_run=True runs every staging step -- including the full staged-bundle
    conservation validation (_validate_staged_current_review_bundle), which
    is the ONLY thing that can prove a batch of proposals will actually
    persist -- but returns before touching the real bundle/pointer, and the
    staging directory is discarded either way (see the shared `finally`
    below). The human confirmation phrase is not required yet at this point
    (the operator surface calls this before asking for it); the real write
    below still requires it unconditionally.
    """
    if not dry_run:
        if confirmation != current_batch_confirmation(str(batch.get("batch_id") or "")):
            return {"cancelled": True, "decisions_written": False, "receipt_created": False}

    surface = resolve_current_human_delta_surface(canon_root)
    if not surface.get("allowed"):
        raise CurrentReviewWriteBlocked("current_authority_changed")
    inventory = surface["inventory"]
    if inventory["relation_generation_id"] != batch.get("relation_generation_id"):
        raise CurrentReviewWriteBlocked("current_authority_changed")
    if inventory["review_state_id"] != batch.get("review_state_id"):
        if any(receipt.get("batch_id") == batch.get("batch_id") for receipt in _current_review_receipts(surface)):
            raise CurrentReviewWriteBlocked("review_batch_already_consumed")
        raise CurrentReviewWriteBlocked("review_state_changed")
    if inventory["bundle_manifest_hash"] != batch.get("bundle_manifest_hash"):
        raise CurrentReviewWriteBlocked("bundle_manifest_changed")
    fresh_batches = build_current_human_delta_batches(surface)
    fresh = next((item for item in fresh_batches if item["batch_id"] == batch.get("batch_id")), None)
    if fresh is None:
        if any(receipt.get("batch_id") == batch.get("batch_id") for receipt in _current_review_receipts(surface)):
            raise CurrentReviewWriteBlocked("review_batch_already_consumed")
        raise CurrentReviewWriteBlocked("review_batch_changed")
    if fresh["batch_hash"] != batch.get("batch_hash"):
        raise CurrentReviewWriteBlocked("review_batch_changed")
    if fresh["candidate_ids"] != batch.get("candidate_ids") or fresh["candidate_hashes"] != batch.get("candidate_hashes"):
        raise CurrentReviewWriteBlocked("review_candidate_changed")
    normalized = _validate_current_batch_proposals(surface, fresh, proposals, actor)

    authority = surface["authority"]
    source_bundle = Path(surface["bundle_path"])
    source_pointer = Path(authority["pointer_path"])
    source_pointer_bytes = source_pointer.read_bytes()
    protected_canon_hash = canon_hash(canon_root)
    result_review_state_id, receipt_id = _current_review_semantic_identity(surface, fresh, normalized)
    relation_generation_id = inventory["relation_generation_id"]
    destination = source_bundle.parent.parent / result_review_state_id / source_bundle.name
    staging = destination.parent / (
        f".staging-{destination.name}-{os.getpid()}-{uuid.uuid4().hex}"
    )
    pointer_written_bytes: bytes | None = None
    bundle_published = False
    try:
        staging.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_bundle, staging)
        queue_by_id = {
            str(row.get("candidate_id") or ""): row
            for row in load_jsonl(staging / Path(surface["artifacts"]["ready_queue"]).name)
        }
        decision_path = staging / Path(surface["artifacts"]["effective_decisions"]).name
        existing_rows = load_jsonl(decision_path)
        existing = {str(row.get("candidate_id") or ""): row for row in existing_rows}
        # S0186 Unit H (batch-publish coverage fix): the published bundle's own
        # effective_decisions snapshot is frozen at publish time and does not
        # know about decisions written straight to the live decisions file
        # afterward (e.g. governed_relation_admission_policy.
        # materialize_authorized_policy(), or any other out-of-band writer) --
        # resolve_current_human_delta_surface() already recovers and excludes
        # them from the reviewable set (inventory['live_decision_exclusion']),
        # but publishing a NEW review-state bundle must fold them into its
        # own decisions snapshot too, or _validate_staged_current_review_
        # bundle's coverage conservation check (pending ∪ decided == queue)
        # fails: the staged pending list still carries them (the bundle
        # never learned they were decided) while the staged decisions file
        # does not. This publish is exactly the natural place to catch the
        # bundle chain back up -- it does not re-run any policy or create
        # any new decision, it only carries an ALREADY-WRITTEN one forward.
        live_recovered_ids: list[str] = list(
            (inventory.get("live_decision_exclusion") or {}).get("excluded_candidate_ids") or []
        )
        if live_recovered_ids:
            live_decisions_path = decision_authority_path(
                canon_root / "pipeline" / "relation_candidates" / "current"
            )
            live_rows = {
                str(row.get("candidate_id") or ""): row
                for row in load_jsonl(live_decisions_path)
            }
            for candidate_id in live_recovered_ids:
                if candidate_id in live_rows:
                    existing[candidate_id] = live_rows[candidate_id]
        if any(proposal["candidate_id"] in existing for proposal in normalized):
            raise CurrentReviewWriteBlocked("review_decision_conflict")
        bindings = current_bindings(staging, canon_root)
        reviewed_at = utc_now()
        for proposal in normalized:
            candidate = queue_by_id.get(proposal["candidate_id"])
            if candidate is None:
                raise CurrentReviewWriteBlocked("review_candidate_changed")
            record = build_decision_record(
                candidate,
                decision=proposal["action"],
                reason_code=proposal["reason_code"],
                note=proposal["note"],
                actor=proposal["actor"],
                bindings=bindings,
                decision_mode="batch",
                decision_batch_id=fresh["batch_id"],
                reviewed_at=reviewed_at,
            )
            record.update({
                "candidate_hash": proposal["candidate_hash"],
                "batch_hash": fresh["batch_hash"],
                "relation_generation_id": relation_generation_id,
                "source_review_state_id": inventory["review_state_id"],
                "result_review_state_id": result_review_state_id,
                "human_confirmation": proposal["human_confirmation"],
                # S0186 Unit H: preserve the ORIGINAL taxonomy classification
                # that put this candidate in this batch in the first place --
                # a uniform batch disposition still records, per candidate,
                # why it was pending (not just what was decided).
                "review_reason": fresh.get("review_reason"),
                "reconciliation_class": fresh.get("reconciliation_class"),
            })
            existing[proposal["candidate_id"]] = record
        atomic_write_jsonl(decision_path, dict(sorted(existing.items())))

        consumed = set(fresh["candidate_ids"])
        # The staged pending_candidate_ids list must drop BOTH this batch's
        # own consumed ids AND the live-recovered ones folded into `existing`
        # above -- otherwise the bundle's raw pending list keeps declaring
        # them pending while the decisions file now covers them, breaking
        # the pending ∪ decided == queue conservation invariant.
        removed_from_declared_pending = consumed | set(live_recovered_ids)
        for artifact_name in ("pending_queue", "batch_inventory", "current_human_delta"):
            path = staging / Path(surface["artifacts"][artifact_name]).name
            payload = load_json(path)
            _rewrite_pending_delta(payload, removed_from_declared_pending, result_review_state_id)
            atomic_write_json(path, payload)
        remaining = inventory["total_pending"] - len(consumed)

        checkpoint_path = staging / Path(surface["artifacts"]["review_rebaseline_checkpoint"]).name
        checkpoint = load_json(checkpoint_path)
        checkpoint["review_state_id"] = result_review_state_id
        checkpoint["pending_human_delta"] = remaining
        checkpoint["current_direct_effective_decisions"] = (
            int(checkpoint.get("current_direct_effective_decisions") or 0)
            + len(consumed)
        )
        atomic_write_json(checkpoint_path, checkpoint)
        rebaseline_path = staging / Path(surface["artifacts"]["review_rebaseline"]).name
        rebaseline = load_json(rebaseline_path)
        rebaseline["previous_review_state_id"] = inventory["review_state_id"]
        rebaseline["new_review_state_id"] = result_review_state_id
        if isinstance(rebaseline.get("current_candidate_partition"), dict):
            rebaseline["current_candidate_partition"]["pending_human_review"] = remaining
            rebaseline["current_candidate_partition"]["human_reviewed_covered"] = (
                int(rebaseline["current_candidate_partition"].get("human_reviewed_covered") or 0)
                + len(consumed)
            )
            # Candidates covered by a decision channel independent of this
            # batch review (governed policy materialization writing straight
            # to the live decisions file) belong in independently_covered,
            # not human_reviewed_covered -- this batch did not review them,
            # it only carried their already-made decision forward so the
            # reviewable_total = independently_covered + human_reviewed_covered
            # + pending_human_review + conflict_blocked + unaccounted
            # conservation invariant stays true for the new review state.
            rebaseline["current_candidate_partition"]["independently_covered"] = (
                int(rebaseline["current_candidate_partition"].get("independently_covered") or 0)
                + len(live_recovered_ids)
            )
        atomic_write_json(rebaseline_path, rebaseline)
        decision_checkpoint_path = staging / Path(surface["artifacts"]["decision_checkpoint"]).name
        decision_checkpoint = load_json(decision_checkpoint_path)
        decision_checkpoint["review_state_id"] = result_review_state_id
        decision_checkpoint["decisions_file_hash"] = sha256_file(decision_path)
        decision_checkpoint["decisions_file_path"] = str(destination / decision_path.name)
        decision_checkpoint["total_decisions"] = len(existing)
        decision_checkpoint["pending_delta"] = remaining
        decision_checkpoint["previous_checkpoint_or_receipt"] = str(source_bundle)
        decision_checkpoint["previous_bundle_manifest_hash"] = inventory[
            "bundle_manifest_hash"
        ]
        individual_hashes = list(decision_checkpoint.get("individual_decision_hashes") or [])
        prior_hash_ids = {str(item.get("candidate_id") or "") for item in individual_hashes}
        individual_hashes.extend({
            "candidate_id": candidate_id,
            "classification": "current_direct",
            "decision_sha256": decision_hash(existing[candidate_id]).removeprefix("sha256:"),
        } for candidate_id in sorted(consumed) if candidate_id not in prior_hash_ids)
        # The checkpoint must declare a hash for EVERY candidate now covered
        # by the decisions file, including the ones folded in from the live
        # decision authority above (declared_by_id must equal decisions_by_id
        # in _validate_staged_current_review_bundle) -- a distinct
        # classification keeps them out of the current_direct/preserved_*
        # conservation counters below, which this publish does not affect.
        individual_hashes.extend({
            "candidate_id": candidate_id,
            "classification": "live_recovered",
            "decision_sha256": decision_hash(existing[candidate_id]).removeprefix("sha256:"),
        } for candidate_id in sorted(live_recovered_ids) if candidate_id not in prior_hash_ids and candidate_id in existing)
        decision_checkpoint["individual_decision_hashes"] = sorted(
            individual_hashes, key=lambda item: str(item.get("candidate_id") or ""),
        )
        classifications = Counter(
            str(item.get("classification") or "")
            for item in individual_hashes
        )
        decision_checkpoint["current_direct"] = classifications["current_direct"]
        decision_checkpoint["preserved_equivalent"] = classifications[
            "preserved_equivalent"
        ]
        decision_checkpoint["preserved_historical"] = classifications[
            "preserved_historical"
        ]
        # S0186 Unit H: declare this checkpoint's own live_recovered count
        # explicitly (mirroring the three fields above) so prepare_current_
        # relational_generation.py's predecessor-checkpoint conservation
        # check (DECISION_CHECKPOINT_CLASSIFICATIONS) can verify it against
        # the freshly recomputed classification counter, not silently treat
        # a missing/stale declared value as drift.
        decision_checkpoint["live_recovered"] = classifications["live_recovered"]
        atomic_write_json(decision_checkpoint_path, decision_checkpoint)

        decisions_hash = semantic_hash([decision_hash(existing[item]) for item in sorted(consumed)])
        receipt_path = staging / "current_review_batch_receipts.jsonl"
        receipts = load_jsonl(receipt_path)
        receipt = {
            "schema_version": "current-single-batch-review-receipt/v2",
            "receipt_id": receipt_id,
            "source_relation_generation_id": relation_generation_id,
            "source_review_state_id": inventory["review_state_id"],
            "source_review_state_semantic_hash": fresh.get(
                "source_review_state_semantic_hash"
            ),
            "result_review_state_id": result_review_state_id,
            "source_bundle_manifest_hash": inventory["bundle_manifest_hash"],
            "batch_id": fresh["batch_id"],
            "batch_hash": fresh["batch_hash"],
            "candidate_ids": fresh["candidate_ids"],
            "candidate_hashes": fresh["candidate_hashes"],
            "decisions_hash": decisions_hash,
            "human_confirmation": confirmation,
            "published_at": reviewed_at,
        }
        receipts.append(receipt)
        atomic_write_jsonl(receipt_path, {item["receipt_id"]: item for item in receipts})
        lineage_artifact = (surface.get("artifacts") or {}).get(
            "review_receipt_lineage"
        )
        lineage_path: Path | None = None
        lineage_descriptor: dict[str, Any] | None = None
        if lineage_artifact:
            lineage_path = staging / Path(str(lineage_artifact)).name
            lineage_descriptor = load_json(lineage_path)
            segments = _review_receipt_segments(
                lineage_descriptor,
                receipts[:-1],
            )
            current_segment = next(
                (
                    segment for segment in segments
                    if segment.get("relation_generation_id")
                    == relation_generation_id
                ),
                None,
            )
            if current_segment is None:
                current_segment = {
                    "relation_generation_id": relation_generation_id,
                    "root_review_state_id": inventory["review_state_id"],
                    "tip_review_state_id": result_review_state_id,
                    "receipt_ids": [receipt_id],
                }
                segments.append(current_segment)
            else:
                if (
                    current_segment.get("tip_review_state_id")
                    != inventory["review_state_id"]
                ):
                    raise CurrentReviewWriteBlocked("review_write_validation_failed")
                current_segment["tip_review_state_id"] = result_review_state_id
                current_segment.setdefault("receipt_ids", []).append(receipt_id)
            lineage_descriptor.update({
                "schema_version": "current-review-receipt-lineage/v2",
                "segments": segments,
                "receipt_count": len(receipts),
                "receipt_ids": [
                    str(item.get("receipt_id") or "") for item in receipts
                ],
                "carried_review_receipts_hash": sha256_file(receipt_path),
                "tip_review_state_id": result_review_state_id,
                "integrity_verified": True,
            })
            atomic_write_json(lineage_path, lineage_descriptor)
        decision_checkpoint["review_receipts_hash"] = sha256_file(receipt_path)
        atomic_write_json(decision_checkpoint_path, decision_checkpoint)

        manifest_path = staging / "bundle_manifest.json"
        manifest = load_json(manifest_path)
        manifest["review_state_id"] = result_review_state_id
        manifest["readiness_id"] = None
        manifest["terminal_state"] = (
            "READY_FOR_HUMAN_DELTA_REVIEW" if remaining
            else "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION"
        )
        manifest["next_action"] = (
            "REVIEW_CURRENT_RELATIONAL_DELTA" if remaining
            else "PREPARE_CURRENT_RELATIONAL_READINESS"
        )
        manifest["authorization_created"] = False
        manifest["apply_executed"] = False
        if lineage_path is not None:
            lineage_item = manifest.setdefault("artifacts", {}).get(
                "review_receipt_lineage"
            )
            if not isinstance(lineage_item, dict):
                raise CurrentReviewWriteBlocked("review_write_validation_failed")
            lineage_item["schema_version"] = (
                "current-review-receipt-lineage/v2"
            )
        manifest.setdefault("artifacts", {})["review_receipts"] = {
            "authority": "current_relational_generation",
            "path": receipt_path.name,
            "schema_version": "jsonl/v1",
        }
        for item in manifest["artifacts"].values():
            if not isinstance(item, dict) or str(item.get("status") or "").startswith("not_applicable"):
                continue
            path = staging / str(item.get("path") or "")
            if path.is_file():
                item["sha256"] = sha256_file(path)
        atomic_write_json(manifest_path, manifest)
        if failure_hook == "validation":
            raise CurrentReviewWriteBlocked("review_write_validation_failed")
        _validate_staged_current_review_bundle(
            staging, relation_generation_id=relation_generation_id, review_state_id=result_review_state_id,
        )
        _assert_current_review_source_unchanged(
            canon_root,
            surface,
            protected_canon_hash=protected_canon_hash,
            source_pointer_bytes=source_pointer_bytes,
        )
        if dry_run:
            # Proven persistable: the full staged bundle -- decisions,
            # pending-delta rewrite, checkpoint, receipt, lineage, manifest --
            # passed the same conservation validation a real write depends
            # on. Nothing beyond this point has run: no swap, no pointer
            # update. `finally` below discards `staging` unconditionally.
            return {
                "dry_run": True,
                "status": "READY_TO_CONFIRM",
                "candidates": len(normalized),
                "valid": len(normalized),
                "invalid": 0,
                "batch_id": fresh["batch_id"],
                "would_write": len(consumed),
                "would_remaining_pending": remaining,
            }
        if failure_hook == "publication":
            raise CurrentReviewWriteBlocked("review_publication_failed")
        if destination.exists():
            _validate_staged_current_review_bundle(
                destination,
                relation_generation_id=relation_generation_id,
                review_state_id=result_review_state_id,
            )
            if _review_bundle_retry_semantics(staging) != (
                _review_bundle_retry_semantics(destination)
            ):
                raise CurrentReviewWriteBlocked("review_publication_failed")
            shutil.rmtree(staging)
            retained_receipts = load_jsonl(
                destination / "current_review_batch_receipts.jsonl"
            )
            retained = next(
                (
                    item for item in retained_receipts
                    if item.get("receipt_id") == receipt_id
                ),
                None,
            )
            if retained is None:
                raise CurrentReviewWriteBlocked("review_publication_failed")
            receipt = retained
            manifest = load_json(destination / "bundle_manifest.json")
        else:
            os.replace(staging, destination)
        _validate_staged_current_review_bundle(
            destination,
            relation_generation_id=relation_generation_id,
            review_state_id=result_review_state_id,
        )
        bundle_published = True
        _assert_current_review_source_unchanged(
            canon_root,
            surface,
            protected_canon_hash=protected_canon_hash,
            source_pointer_bytes=source_pointer_bytes,
        )
        if failure_hook == "pointer":
            raise CurrentReviewWriteBlocked("review_pointer_update_failed")
        pointer = dict(authority["pointer"])
        pointer.update({
            "bundle_path": str(destination),
            "bundle_manifest_path": str(destination / "bundle_manifest.json"),
            "bundle_manifest_hash": sha256_file(destination / "bundle_manifest.json"),
            "relation_generation_id": relation_generation_id,
            "review_state_id": result_review_state_id,
            "readiness_id": None,
            "terminal_state": manifest["terminal_state"],
            "next_action": manifest["next_action"],
            "published_at": utc_now(),
        })
        _assert_current_review_source_unchanged(
            canon_root,
            surface,
            protected_canon_hash=protected_canon_hash,
            source_pointer_bytes=source_pointer_bytes,
        )
        pointer_candidate_bytes = (
            json.dumps(pointer, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        try:
            pointer_installed = compare_and_swap_current_pointer(
                source_pointer,
                expected=source_pointer_bytes,
                replacement=pointer_candidate_bytes,
            )
        except CurrentRelationalAuthorityError as error:
            raise CurrentReviewWriteBlocked("current_authority_changed") from error
        if pointer_installed:
            pointer_written_bytes = pointer_candidate_bytes
        resolved = resolve_current_relational_authority(canon_root)
        if resolved["review_state_id"] != result_review_state_id or resolved["bundle_path"] != destination:
            raise CurrentReviewWriteBlocked("review_pointer_update_failed")
        if canon_hash(canon_root) != protected_canon_hash:
            raise CurrentReviewWriteBlocked("current_authority_changed")
        return {
            "cancelled": False,
            "decisions_written": len(consumed),
            "receipt_created": True,
            "receipt": receipt,
            "source_review_state_id": inventory["review_state_id"],
            "result_review_state_id": result_review_state_id,
            "relation_generation_id": relation_generation_id,
            "remaining_pending": remaining,
            "terminal_state": manifest["terminal_state"],
            "next_action": manifest["next_action"],
            "bundle_path": str(destination),
        }
    except CurrentReviewWriteBlocked:
        _restore_current_review_pointer_if_owned(
            source_pointer,
            before=source_pointer_bytes,
            written=pointer_written_bytes,
        )
        # Once validated and renamed, keep the immutable bundle as recoverable
        # evidence.  A concurrent successor may already reference it.
        raise
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _restore_current_review_pointer_if_owned(
            source_pointer,
            before=source_pointer_bytes,
            written=pointer_written_bytes,
        )
        # A fully published bundle is never deleted by rollback cleanup.
        raise CurrentReviewWriteBlocked(
            "review_pointer_update_failed"
            if bundle_published else "review_publication_failed"
        ) from error
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if not destination.exists():
            try:
                destination.parent.rmdir()
            except OSError:
                pass


def _check_current_batch_proposals_individually(
    batch: dict[str, Any], proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-candidate proposal shape check, mirroring _validate_current_batch_
    proposals()'s conditions but never raising and never stopping at the
    first failure -- every candidate gets its own valid/errors verdict, for
    the operator's pre-confirmation summary (candidates/valid/invalid).
    """
    expected_ids = list(batch["candidate_ids"])
    expected_hashes = dict(zip(expected_ids, batch["candidate_hashes"], strict=True))
    by_id = {str(p.get("candidate_id") or ""): p for p in proposals}
    results: list[dict[str, Any]] = []
    for candidate_id in expected_ids:
        proposal = by_id.get(candidate_id)
        errors: list[str] = []
        if proposal is None:
            errors.append("no_proposal_for_candidate")
        else:
            action = str(proposal.get("action") or proposal.get("decision") or "")
            reason_code = str(proposal.get("reason_code") or "").strip().upper()
            note = str(proposal.get("note") or "").strip()
            confirmation = str(proposal.get("human_confirmation") or "")
            if proposal.get("candidate_hash") != expected_hashes.get(candidate_id):
                errors.append("candidate_hash_mismatch")
            if action not in DECISIONS:
                errors.append("action_invalid")
            elif reason_code not in DECISION_REASON_CODES[action] | EXCEPTION_REASON_CODES:
                errors.append("reason_code_invalid_for_action")
            if reason_code in NOTE_REQUIRED_REASON_CODES and not note:
                errors.append("note_required_for_reason_code")
            if action in DECISIONS and confirmation != current_candidate_confirmation(candidate_id, action):
                errors.append("human_confirmation_mismatch")
        results.append({"candidate_id": candidate_id, "valid": not errors, "errors": errors})
    extra_ids = sorted(set(by_id) - set(expected_ids))
    for candidate_id in extra_ids:
        results.append({
            "candidate_id": candidate_id, "valid": False, "errors": ["candidate_not_in_batch"],
        })
    return results


def validate_current_batch_write_readiness(
    canon_root: Path, *, surface: dict[str, Any], batch: dict[str, Any],
    proposals: list[dict[str, Any]], actor: str, sample_limit: int = 5,
) -> dict[str, Any]:
    """Read-only: can this exact set of proposals actually be persisted?

    Two layers, cheapest first:
    1. Per-candidate proposal shape (hash/action/reason_code/confirmation) --
       fast, no I/O beyond what's already in memory. Reports candidates/
       valid/invalid with a small sample of candidate_id + error.
    2. If every proposal is individually valid, a full staged dry-run
       (persist_current_human_delta_batch(..., dry_run=True)) -- the only
       way to prove the whole-batch conservation invariants (pending ∪
       decided == queue, checkpoint hash coverage, rebaseline partition
       totals, etc.) will hold. This is the layer that actually caught the
       real 211-candidate batch's failure; per-candidate checks alone
       cannot see it.

    Never writes anything -- persist_current_human_delta_batch(dry_run=True)
    discards its staging directory unconditionally before returning.
    """
    per_candidate = _check_current_batch_proposals_individually(batch, proposals)
    invalid = [item for item in per_candidate if not item["valid"]]
    if invalid:
        return {
            "schema_version": "current-batch-write-readiness/v1",
            "status": "BLOCKED",
            "stage": "per_candidate_proposal_validation",
            "candidates": len(per_candidate),
            "valid": len(per_candidate) - len(invalid),
            "invalid": len(invalid),
            "sample_errors": invalid[:sample_limit],
        }
    try:
        outcome = persist_current_human_delta_batch(
            canon_root, batch=batch, proposals=proposals, actor=actor, dry_run=True,
        )
    except CurrentReviewWriteBlocked as error:
        return {
            "schema_version": "current-batch-write-readiness/v1",
            "status": "BLOCKED",
            "stage": "staged_bundle_conservation_validation",
            "candidates": len(per_candidate),
            "valid": len(per_candidate),
            "invalid": 0,
            "reason_codes": error.reason_codes,
            "underlying_cause": str(error.__cause__) if error.__cause__ else None,
        }
    return {
        "schema_version": "current-batch-write-readiness/v1",
        "status": outcome["status"],
        "stage": "complete",
        "candidates": outcome["candidates"],
        "valid": outcome["valid"],
        "invalid": outcome["invalid"],
        "would_write": outcome["would_write"],
        "would_remaining_pending": outcome["would_remaining_pending"],
    }


def render_current_batch_summary(batch: dict[str, Any]) -> None:
    print("\nLote current no consumido")
    print(f"Batch ID: {batch['batch_id']}")
    print(f"Motivo: {batch['review_reason']}")
    print(f"Candidatas: {batch['candidate_count']}")
    print(f"Relation generation: {batch['relation_generation_id']}")
    print(f"Review state fuente: {batch['review_state_id']}")
    print(f"Batch hash: {batch['batch_hash']}")


def _persist_current_batch_or_report(
    canon_root: Path, *, batch: dict[str, Any], proposals: list[dict[str, Any]],
    actor: str, confirmation: str,
) -> int:
    try:
        result = persist_current_human_delta_batch(
            canon_root, batch=batch, proposals=proposals, actor=actor, confirmation=confirmation,
        )
    except CurrentReviewWriteBlocked as error:
        print("CURRENT_REVIEW_WRITE_BLOCKED")
        print(json.dumps({
            "allowed": False,
            "reason_codes": error.reason_codes,
            "decisions_written": False,
            "receipt_created": False,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_current_batch_uniform_disposition(
    canon_root: Path, surface: dict[str, Any], batch: dict[str, Any], *, reviewer: str,
) -> tuple[list[dict[str, Any]], str] | None:
    """Prompt ONE action/reason_code/note for the whole homogeneous batch.

    Returns (proposals, confirmation) ready for persist_current_human_delta_
    batch(), or None if the human cancels. Each of batch['candidate_count']
    candidates still gets its own proposal (own candidate_id, own hash) --
    only the disposition (action/reason_code/note) is uniform, never an
    aggregated decision.
    """
    by_id = {item["candidate_id"]: item for item in surface["inventory"]["candidates"]}
    action = input(
        "Acción para TODO el lote [approved_for_admission/rejected/deferred; q=cancelar]: "
    ).strip()
    if action.lower() == "q" or action not in DECISIONS:
        print("Revisión cancelada; no se escribió ninguna decisión.")
        return None
    allowed_codes = sorted(DECISION_REASON_CODES[action] | EXCEPTION_REASON_CODES)
    print("Reason codes permitidos: " + ", ".join(allowed_codes))
    reason_code = input("Reason code (uniforme para todo el lote): ").strip().upper()
    if reason_code not in DECISION_REASON_CODES[action] | EXCEPTION_REASON_CODES:
        print("Reason code inválido; no se escribió ninguna decisión.")
        return None
    note = input("Nota humana opcional (uniforme para todo el lote): ").strip()
    if reason_code in NOTE_REQUIRED_REASON_CODES and not note:
        print(f"Nota requerida para {reason_code}; no se escribió ninguna decisión.")
        return None
    proposals = [
        {
            "candidate_id": candidate_id,
            "candidate_hash": by_id[candidate_id]["candidate_hash"],
            "action": action,
            "reason_code": reason_code,
            "note": note,
            "human_confirmation": current_candidate_confirmation(candidate_id, action),
        }
        for candidate_id in batch["candidate_ids"]
    ]

    readiness = validate_current_batch_write_readiness(
        canon_root, surface=surface, batch=batch, proposals=proposals, actor=reviewer,
    )
    print("\nwrite_validation:")
    print(json.dumps({
        "candidates": readiness["candidates"],
        "valid": readiness["valid"],
        "invalid": readiness["invalid"],
        "status": readiness["status"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    if readiness["status"] != "READY_TO_CONFIRM":
        print(f"Etapa bloqueada: {readiness.get('stage')}")
        if readiness.get("underlying_cause"):
            print(f"Causa exacta: {readiness['underlying_cause']}")
        if readiness.get("reason_codes"):
            print(f"Reason codes: {', '.join(readiness['reason_codes'])}")
        if readiness.get("sample_errors"):
            print("Muestra de candidatas inválidas:")
            for item in readiness["sample_errors"]:
                print(f"  - {item['candidate_id']}: {', '.join(item['errors'])}")
        print("No se solicitará confirmación humana; no se escribió ninguna decisión.")
        return None

    print("\nResumen final de la disposición uniforme del lote")
    print(json.dumps({
        "batch_id": batch["batch_id"],
        "review_reason": batch["review_reason"],
        "reconciliation_class": batch["reconciliation_class"],
        "candidate_count": batch["candidate_count"],
        "accion_uniforme": action,
        "reason_code_uniforme": reason_code,
        "nota_uniforme": note or None,
        "relation_generation_id": batch["relation_generation_id"],
        "source_review_state_id": batch["review_state_id"],
        "batch_hash": batch["batch_hash"],
        "bundle_manifest_hash": batch["bundle_manifest_hash"],
        "resultado": f"{batch['candidate_count']} decisiones individuales auditables, una por candidata",
    }, ensure_ascii=False, indent=2, sort_keys=True))
    required = current_batch_confirmation(batch["batch_id"])
    confirmation = input(f"Confirmar lote -- escriba exactamente {required}: ").strip()
    if confirmation != required:
        print("Confirmación final inválida; no se escribió ninguna decisión.")
        return None
    return proposals, confirmation


def _run_current_batch_per_candidate(
    canon_root: Path, surface: dict[str, Any], batch: dict[str, Any], *, reviewer: str,
) -> tuple[list[dict[str, Any]], str] | None:
    """Advanced route: ask action/reason_code/confirmation for each candidate
    individually. Kept available, but no longer the default for a
    class-homogeneous batch (see _run_current_batch_uniform_disposition).
    """
    by_id = {item["candidate_id"]: item for item in surface["inventory"]["candidates"]}
    proposals: list[dict[str, Any]] = []
    for index, candidate_id in enumerate(batch["candidate_ids"], start=1):
        candidate = by_id[candidate_id]
        print(f"\nCandidata {index}/{batch['candidate_count']}")
        print(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True))
        action = input("Acción [approved_for_admission/rejected/deferred; q=cancelar]: ").strip()
        if action.lower() == "q" or action not in DECISIONS:
            print("Revisión cancelada; no se escribió ninguna decisión.")
            return None
        allowed_codes = sorted(DECISION_REASON_CODES[action] | EXCEPTION_REASON_CODES)
        print("Reason codes permitidos: " + ", ".join(allowed_codes))
        reason_code = input("Reason code: ").strip().upper()
        if reason_code not in DECISION_REASON_CODES[action] | EXCEPTION_REASON_CODES:
            print("Reason code inválido; no se escribió ninguna decisión.")
            return None
        note = input("Nota humana opcional: ").strip()
        required = current_candidate_confirmation(candidate_id, action)
        candidate_confirmation = input(f"Escriba exactamente {required}: ").strip()
        if candidate_confirmation != required:
            print("Confirmación de candidata inválida; no se escribió ninguna decisión.")
            return None
        proposals.append({
            "candidate_id": candidate_id,
            "candidate_hash": candidate["candidate_hash"],
            "action": action,
            "reason_code": reason_code,
            "note": note,
            "human_confirmation": candidate_confirmation,
        })
    readiness = validate_current_batch_write_readiness(
        canon_root, surface=surface, batch=batch, proposals=proposals, actor=reviewer,
    )
    print("\nwrite_validation:")
    print(json.dumps({
        "candidates": readiness["candidates"],
        "valid": readiness["valid"],
        "invalid": readiness["invalid"],
        "status": readiness["status"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    if readiness["status"] != "READY_TO_CONFIRM":
        print(f"Etapa bloqueada: {readiness.get('stage')}")
        if readiness.get("underlying_cause"):
            print(f"Causa exacta: {readiness['underlying_cause']}")
        if readiness.get("reason_codes"):
            print(f"Reason codes: {', '.join(readiness['reason_codes'])}")
        if readiness.get("sample_errors"):
            print("Muestra de candidatas inválidas:")
            for item in readiness["sample_errors"]:
                print(f"  - {item['candidate_id']}: {', '.join(item['errors'])}")
        print("No se solicitará confirmación humana; no se escribió ninguna decisión.")
        return None

    print("\nResumen final de decisiones propuestas")
    print(json.dumps({
        "batch_id": batch["batch_id"],
        "review_reason": batch["review_reason"],
        "candidate_count": batch["candidate_count"],
        "decisions_summary": Counter(item["action"] for item in proposals),
        "relation_generation_id": batch["relation_generation_id"],
        "source_review_state_id": batch["review_state_id"],
        "batch_hash": batch["batch_hash"],
        "bundle_manifest_hash": batch["bundle_manifest_hash"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    required = current_batch_confirmation(batch["batch_id"])
    confirmation = input(f"Escriba exactamente {required}: ").strip()
    if confirmation != required:
        print("Confirmación final inválida; no se escribió ninguna decisión.")
        return None
    return proposals, confirmation


def run_current_single_batch_review(canon_root: Path, actor: str | None = None) -> int:
    """Interactive current route; every exit before final confirmation is a no-op."""
    surface = resolve_current_human_delta_surface(canon_root)
    if not surface.get("allowed"):
        print("BATCH_CONFIRMATION_BLOCKED")
        print(json.dumps(surface, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 2
    batches = build_current_human_delta_batches(surface)
    if not batches:
        print("No existen lotes current no consumidos.")
        return 0
    print("\nLotes current no consumidos (resumen compacto)")
    for item in batches:
        print(f"- {item['batch_id']} | {item['review_reason']} | {item['candidate_count']} candidatas")
    try:
        selected_id = input("Batch ID a revisar [q=salir]: ").strip()
        if selected_id.lower() == "q" or not selected_id:
            print("Revisión cancelada; no se escribió ninguna decisión.")
            return 0
        batch = next((item for item in batches if item["batch_id"] == selected_id), None)
        if batch is None:
            print("Batch no reconocido; no se escribió ninguna decisión.")
            return 0
        render_current_batch_summary(batch)
        reviewer = validate_actor(actor if actor is not None else input("Identidad del revisor humano: "))
        mode = input(
            "Modo de revisión [U=disposición uniforme para todo el lote (recomendado) / "
            "c=candidata por candidata (avanzado); q=cancelar]: "
        ).strip().lower()
        if mode == "q":
            print("Revisión cancelada; no se escribió ninguna decisión.")
            return 0
        if mode == "c":
            outcome = _run_current_batch_per_candidate(canon_root, surface, batch, reviewer=reviewer)
        elif mode in ("", "u"):
            outcome = _run_current_batch_uniform_disposition(canon_root, surface, batch, reviewer=reviewer)
        else:
            print("Opción inválida; no se escribió ninguna decisión.")
            return 0
        if outcome is None:
            return 0
        proposals, confirmation = outcome
    except (EOFError, KeyboardInterrupt):
        print("\nRevisión cancelada; no se escribió ninguna decisión.")
        return 0
    return _persist_current_batch_or_report(
        canon_root, batch=batch, proposals=proposals, actor=reviewer, confirmation=confirmation,
    )


def _canon_record_count(canon_root: Path) -> int:
    return sum(1 for path in canon_root.glob("tiddlers_*.jsonl") for line in path.open(encoding="utf-8") if line.strip())


def build_human_review_partition(
    queue: list[dict[str, Any]], decisions: dict[str, dict[str, Any]], bindings: dict[str, str],
) -> list[dict[str, Any]]:
    """Derive the authoritative per-candidate partition; never infer it from totals."""
    ids = [str(row.get("candidate_id") or "") for row in queue]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("batch_preview_duplicate_candidate")
    return [{
        "candidate_id": candidate_id,
        "generation_id": semantic_hash(bindings),
        "disposition": "awaiting_human_review" if candidate_id not in decisions else decisions[candidate_id]["human_review_decision"],
        "decision_id": decision_hash(decisions[candidate_id]) if candidate_id in decisions else None,
        "decision_state": "current" if candidate_id in decisions else "pending",
        "candidate_manifest_hash": bindings["candidate_manifest_hash"],
        "gate_run_id": bindings.get("admission_gate_hash"),
        "reason_code": "pending_generation_partition" if candidate_id not in decisions else "bound_human_decision",
    } for candidate_id in sorted(ids)]


def validate_human_review_batch_generation(
    current_dir: Path, canon_root: Path, gate_report_path: Path, *, preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared fail-closed generation preflight for menu options 7, 8 and 10."""
    reasons: list[str] = []
    try:
        # A published pointer changes this from a generic helper into the
        # operational route: no pipeline artifact may survive as authority.
        review_surface: dict[str, Any] | None = None
        pointer = canon_root / "audit" / "relation_admission" / "current_generation.json"
        if pointer.is_file():
            review_surface = resolve_current_human_delta_surface(canon_root)
            if not review_surface["allowed"]:
                return {
                    "allowed": False,
                    "reason_codes": review_surface["reason_codes"],
                    "current_delta": review_surface.get("inventory"),
                    "current_review_surface": True,
                }
            current_dir = Path(review_surface["bundle_path"])
            gate_report_path = Path(review_surface["artifacts"]["admission_gate"])
        bindings = current_bindings(current_dir, canon_root)
        candidate_manifest = load_json(current_dir / "current_candidate_manifest.json")
        reconciliation = load_json(current_dir / "reconciliation_manifest.json")
        gate = load_json(gate_report_path)
        records = _canon_record_count(canon_root)
        declared = (candidate_manifest.get("canon_binding") or {})
        if not candidate_manifest.get("current") or not reconciliation.get("current"):
            reasons.append("batch_preview_relational_generation_missing")
        if declared.get("record_count") is not None and declared["record_count"] != records:
            reasons.append("batch_preview_relational_generation_missing")
        if reconciliation.get("candidate_manifest_hash") not in (None, bindings["candidate_manifest_hash"]):
            reasons.append("batch_preview_reconciliation_manifest_stale")
        queue = load_jsonl(current_dir / QUEUE_FILE)
        decisions_path = decision_authority_path(current_dir)
        decisions = load_existing_decisions(decisions_path, {str(x.get("candidate_id") or "") for x in queue}, bindings) if decisions_path.exists() else {}
        bindings.update({
            "human_decisions_hash": sha256_file(decisions_path) if decisions_path.exists() else semantic_hash([]),
            "admission_gate_hash": sha256_file(gate_report_path),
            "pending_queue_hash": semantic_hash(sorted(str(x.get("candidate_id") or "") for x in queue if str(x.get("candidate_id") or "") not in decisions)),
        })
        if review_surface is not None:
            inventory = review_surface["inventory"]
            bindings.update({
                "relation_generation_id": inventory["relation_generation_id"],
                "review_state_id": inventory["review_state_id"],
                "bundle_manifest_hash": inventory["bundle_manifest_hash"],
            })
        partition = build_human_review_partition(queue, decisions, bindings)
        if preview and (preview.get("bindings") != bindings or not preview.get("status", {}).get("confirmable")):
            reasons.append("batch_confirmation_preview_stale")
        return {
            "allowed": not reasons, "reason_codes": sorted(set(reasons)),
            "bindings": bindings, "partition": partition, "gate": gate,
            "current_delta": review_surface.get("inventory") if review_surface else None,
            "current_review_surface": review_surface is not None,
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"allowed": False, "reason_codes": ["batch_preview_relational_generation_missing"], "error": str(error), "partition": []}


def build_generation_batch_preview(previews: list[dict[str, Any]], preflight: dict[str, Any]) -> dict[str, Any]:
    partition = preflight["partition"]
    pending = [row["candidate_id"] for row in partition if row["disposition"] == "awaiting_human_review"]
    selected = [candidate_id for preview in previews for candidate_id in preview["candidate_ids"]]
    bindings = preflight["bindings"]
    return {
        "schema_version": "human-review-batch-preview/v1",
        "preview_id": "hrp_" + semantic_hash({"bindings": bindings, "selected": selected})[:24],
        "generation_id": semantic_hash(bindings), "mode": "dry-run", "bindings": bindings,
        "partition": {"valid": len(partition), "approved": sum(x["disposition"] == "approved_for_admission" for x in partition), "deferred": sum(x["disposition"] == "deferred" for x in partition), "rejected": sum(x["disposition"] == "rejected" for x in partition), "pending": len(pending)},
        "selection": {"selected": len(selected), "batch_count": len(previews), "outside_current_queue": len(set(selected) - set(pending)), "already_decided": len(set(selected) - set(pending)), "duplicates": len(selected) - len(set(selected)), "missing": 0},
        "status": {"generated_atomically": True, "current_at_generation": True, "confirmable": True}, "previews": previews,
    }


def load_existing_decisions(
    path: Path, allowed_ids: set[str], bindings: dict[str, str], *, allow_legacy: bool = False,
) -> ExistingDecisions:
    """Load current decisions, retaining S0183 authority at record granularity.

    A preservation receipt certifies the historical source set and its
    migration, not a permanently frozen byte representation of the current
    file.  Therefore later directly-current decisions are allowed only after
    every certified historical decision has been independently verified.
    """
    preservation_manifest = DEFAULT_CANON_ROOT / "audit" / "s0183" / "current" / "cross_batch_reconciliation_manifest.json"
    preservation_receipt_path = preservation_manifest.parent / "human_decision_preservation_manifest.json"
    if preservation_manifest.exists() != preservation_receipt_path.exists():
        raise ValueError("preservation receipt or manifest is missing")
    if not preservation_manifest.exists():
        preservation = {}
        preservation_receipt = {}
        historical: dict[str, dict[str, Any]] = {}
        mappings: dict[str, dict[str, Any]] = {}
        expected_preserved: dict[str, dict[str, Any]] = {}
    else:
        preservation = load_json(preservation_manifest)
        preservation_receipt = load_json(preservation_receipt_path)
        certified_current_path = Path(str(preservation_receipt.get("current_decisions_path") or ""))
        if not certified_current_path.is_absolute():
            certified_current_path = REPO_ROOT / certified_current_path
        # The repository can host fixture or historical decision files while a
        # production receipt exists.  Its certificate applies only to its
        # declared current authority, never to an unrelated caller path.
        if not str(certified_current_path) or certified_current_path.resolve() != path.resolve():
            preservation = {}
            preservation_receipt = {}
            historical = {}
            mappings = {}
            expected_preserved = {}
        else:
            manifest_hash = sha256_file(preservation_manifest)
            if preservation.get("schema_version") != "s0183-cross-batch-reconciliation/v1":
                raise ValueError("invalid preservation manifest schema")
            if preservation_receipt.get("cross_batch_manifest_hash") != manifest_hash:
                raise ValueError("preservation receipt cross-batch manifest hash mismatch")
            if not isinstance(preservation_receipt.get("current_decisions_hash"), str) or len(preservation_receipt["current_decisions_hash"]) != 64:
                raise ValueError("preservation receipt current decisions hash is invalid")
            matrix_path = preservation_manifest.parent / "old_to_current_reconciliation.jsonl"
            if not matrix_path.exists() or preservation.get("old_to_current_hash") != sha256_file(matrix_path):
                raise ValueError("preservation reconciliation matrix hash mismatch")
            historical_path_value = str(preservation_receipt.get("historical_decisions_path") or "")
            historical_path = Path(historical_path_value)
            if not historical_path.is_absolute():
                historical_path = REPO_ROOT / historical_path
            if not historical_path.exists() or preservation_receipt.get("historical_decisions_hash") != sha256_file(historical_path):
                raise ValueError("preservation historical decisions hash mismatch")

            historical = {}
            for line_no, record in enumerate(load_jsonl(historical_path), start=1):
                candidate_id = str(record.get("candidate_id") or "")
                if not candidate_id or candidate_id in historical:
                    raise ValueError(f"historical decisions contain duplicate or empty candidate_id at line {line_no}")
                errors = validate_human_review_decision_record(record, allow_legacy=allow_legacy)
                if errors:
                    raise ValueError(f"historical decisions:{line_no}: {'; '.join(errors)}")
                historical[candidate_id] = record
            if preservation_receipt.get("historical_decision_count") != len(historical):
                raise ValueError("preservation historical decision count mismatch")

            mappings = {}
            mapped_targets: set[str] = set()
            for line_no, mapping in enumerate(load_jsonl(matrix_path), start=1):
                old_id = str(mapping.get("candidate_id") or "")
                target_id = str(mapping.get("counterpart_candidate_id") or "")
                if not old_id or old_id in mappings:
                    raise ValueError(f"preservation mapping is ambiguous for historical candidate at line {line_no}")
                if mapping.get("classification") == "equivalent" and mapping.get("decision_reusable") is True:
                    if not target_id or target_id in mapped_targets:
                        raise ValueError(f"preservation mapping is ambiguous for current candidate at line {line_no}")
                    mapped_targets.add(target_id)
                mappings[old_id] = mapping
            expected_preserved = {
                old_id: mapping for old_id, mapping in mappings.items()
                if old_id in historical
                and mapping.get("classification") == "equivalent"
                and mapping.get("decision_reusable") is True
            }
            if preservation_receipt.get("migrated_equivalent_count") != len(expected_preserved):
                raise ValueError("preservation certified equivalent decision count mismatch")

    candidate_source = path.parent / "relation_candidates.jsonl"
    current_candidate_ids = (
        {str(row.get("candidate_id") or "") for row in load_jsonl(candidate_source)}
        if candidate_source.exists() else set(allowed_ids)
    )
    decisions = ExistingDecisions()
    for line_no, record in enumerate(load_jsonl(path), start=1):
        errors = validate_human_review_decision_record(record, allow_legacy=allow_legacy)
        candidate_id = str(record.get("candidate_id") or "")
        if candidate_id in decisions:
            errors.append("duplicate candidate_id")
        origin_id = str(record.get("preserved_from_candidate_id") or "")
        mapping = expected_preserved.get(origin_id)
        has_preservation_marker = any(record.get(key) is not None for key in (
            "preserved_from_candidate_id", "preserved_from_decision_hash",
            "preservation_classification", "preservation_manifest_hash",
        ))
        preserved = bool(mapping)
        if preserved:
            historical_record = historical[origin_id]
            if (
                record.get("preservation_classification") != "equivalent"
                or record.get("preservation_manifest_hash") != sha256_file(preservation_manifest)
                    or mapping.get("counterpart_candidate_id") != candidate_id
                    or record.get("preserved_from_decision_hash") != decision_hash(historical_record)
                    or (
                        record.get("preserved_from_bindings") is not None
                        and record.get("preserved_from_bindings") != {
                            "canon_hash": historical_record.get("canon_hash"),
                            "candidate_manifest_hash": historical_record.get("candidate_manifest_hash"),
                            "reconciliation_manifest_hash": historical_record.get("reconciliation_manifest_hash"),
                        }
                    )
                    # Evidence is rebound to the equivalent current candidate;
                    # human authority/provenance fields remain immutable.
                    or any(
                        record.get(field) != historical_record.get(field)
                        for field in MIGRATION_PRESERVED_FIELDS if field != "evidence"
                    )
            ):
                errors.append("preserved historical decision integrity mismatch")
            errors = [error for error in errors if not error.startswith("stale ")]
            errors = [error for error in errors if error != "candidate_id is not in current review queue"]
            decisions.preserved_historical.add(candidate_id)
        else:
            if has_preservation_marker:
                errors.append("unclassifiable preserved decision")
            if candidate_id not in allowed_ids:
                errors.append("candidate_id is not in current review queue")
            if candidate_id not in current_candidate_ids:
                errors.append("candidate_id is not in current generation")
            for key, value in bindings.items():
                if record.get(key) != value:
                    errors.append(f"stale {key}")
            decisions.current_direct.add(candidate_id)
        if errors:
            decisions.invalid_or_stale.add(candidate_id or f"line:{line_no}")
            raise ValueError(f"{path}:{line_no}: {'; '.join(errors)}")
        decisions[candidate_id] = record
    if preservation and decisions.preserved_historical != {
        str(mapping.get("counterpart_candidate_id") or "") for mapping in expected_preserved.values()
    }:
        missing = sorted({str(mapping.get("counterpart_candidate_id") or "") for mapping in expected_preserved.values()} - decisions.preserved_historical)
        raise ValueError(f"preserved historical decision missing: {', '.join(missing)}")
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
    policy_version: str | None = None, policy_hash: str | None = None,
    human_authorization_id: str | None = None, authorization_scope: str | None = None,
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
    if decision_mode == "policy_derived":
        # S0186 Unit H8: distinguish a machine-derived-from-an-authorized-
        # policy decision from an individual or batch human review that
        # actually happened. review_policy_id carries the governed policy's
        # own identity (RelationPolicy.policy_id); these four fields are
        # what make that identity verifiable and scope-bound rather than a
        # free-text label.
        record["policy_version"] = policy_version
        record["policy_hash"] = policy_hash
        record["human_authorization_id"] = human_authorization_id
        record["authorization_scope"] = authorization_scope
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


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as fh:
            temporary = Path(fh.name)
            fh.write(payload)
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


def semantic_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def migrate_equivalent_decisions(
    *,
    historical_decisions_file: Path,
    current_dir: Path,
    canon_root: Path,
    cross_batch_manifest_path: Path,
    audit_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Plan and atomically publish one-to-one equivalent decision rebindings."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / MIGRATION_REPORT_FILE
    destination = decision_authority_path(current_dir)
    destination_before = destination.read_bytes() if destination.exists() else None
    bindings: dict[str, str] = {}
    historical_count = 0
    selected_count = 0
    not_reused: list[dict[str, Any]] = []

    def block(
        reason_codes: list[str], *, collisions: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
        planned_count: int = 0,
        backup_path: Path | None = None,
    ) -> None:
        unknown = sorted(set(reason_codes) - MIGRATION_REASON_CODES)
        if unknown:
            raise RuntimeError(f"unregistered migration reason codes: {unknown}")
        report = {
            "schema_version": MIGRATION_REPORT_SCHEMA,
            "operation": {
                "mode": "dry-run" if dry_run else "apply",
                "source_count": selected_count,
                "historical_count": historical_count,
                "planned_count": planned_count,
                "written_count": 0,
                "collision_count": len(collisions or []),
                "allowed": False,
            },
            "bindings": bindings,
            "reason_codes": sorted(set(reason_codes)),
            "collisions": collisions or [],
            "details": details or {},
            "not_reused": not_reused,
            "output": {
                "target_path": str(destination),
                "backup_path": str(backup_path) if backup_path else None,
                "report_path": str(audit_path),
                "atomic_publish": False,
                "target_will_change": False,
                "target_modified": False,
                "partial_output": False,
            },
        }
        atomic_write_json(audit_path, report)
        if destination_before is None:
            if destination.exists():
                raise RuntimeError("blocked migration created the decision target")
        elif not destination.exists() or destination.read_bytes() != destination_before:
            raise RuntimeError("blocked migration modified the decision target")
        raise HumanDecisionMigrationBlocked(report["reason_codes"], audit_path)

    def restore_destination() -> None:
        """Restore the exact pre-migration authority after a failed publish."""
        if destination_before is None:
            destination.unlink(missing_ok=True)
        elif not destination.exists() or destination.read_bytes() != destination_before:
            atomic_write_bytes(destination, destination_before)

    manifest = load_json(cross_batch_manifest_path)
    if manifest.get("schema_version") != "s0183-cross-batch-reconciliation/v1":
        block(["reconciliation_manifest_hash_mismatch"], details={"message": "unsupported cross-batch reconciliation manifest"})
    old_matrix_path = REPO_ROOT / str(manifest.get("old_to_current_path") or "")
    if not old_matrix_path.exists():
        old_matrix_path = cross_batch_manifest_path.parent / "old_to_current_reconciliation.jsonl"
    if sha256_file(old_matrix_path) != manifest.get("old_to_current_hash"):
        block(["reconciliation_manifest_hash_mismatch"], details={"message": "old-to-current reconciliation matrix hash mismatch"})
    if sha256_file(Path(manifest["historical_candidates_path"]) if Path(str(manifest["historical_candidates_path"])).is_absolute()
                   else REPO_ROOT / str(manifest["historical_candidates_path"])) != manifest.get("historical_candidates_hash"):
        block(["historical_candidate_hash_mismatch"], details={"message": "historical candidate batch hash mismatch"})
    if sha256_file(current_dir / "relation_candidates.jsonl") != manifest.get("current_candidates_hash"):
        block(["candidate_manifest_hash_mismatch"], details={"message": "current candidate batch hash mismatch"})

    historical_rows = load_jsonl(historical_decisions_file)
    historical_count = len(historical_rows)
    historical: dict[str, dict[str, Any]] = {}
    for line_no, row in enumerate(historical_rows, start=1):
        errors = validate_human_review_decision_record(row)
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            block(["source_decision_missing_identity"], details={"line": line_no})
        if candidate_id in historical:
            block(["duplicate_source_decision_id"], details={"historical_candidate_id": candidate_id, "line": line_no})
        if errors:
            block(["source_decision_invalid"], details={"line": line_no, "errors": errors})
        historical[candidate_id] = row

    queue = load_jsonl(current_dir / QUEUE_FILE)
    queue_by_id: dict[str, dict[str, Any]] = {}
    for line_no, row in enumerate(queue, start=1):
        current_id = str(row.get("candidate_id") or "")
        if not current_id:
            block(["duplicate_target_current_id"], details={"message": "current queue contains an empty candidate_id", "line": line_no})
        if current_id in queue_by_id:
            block(["duplicate_target_current_id"], details={"current_id": current_id, "line": line_no})
        queue_by_id[current_id] = row
    try:
        decision_bindings = current_bindings(current_dir, canon_root)
    except ValueError as error:
        block(["current_binding_stale"], details={"message": str(error)})
    candidate_manifest = load_json(current_dir / "current_candidate_manifest.json")
    reconciliation_manifest = load_json(current_dir / "reconciliation_manifest.json")
    candidate_canon_hash = str((candidate_manifest.get("canon_binding") or {}).get("canon_hash") or "")
    if candidate_canon_hash != decision_bindings["canon_hash"]:
        block(["current_binding_stale"], details={
            "binding": "candidate_manifest.canon_binding.canon_hash",
            "expected": decision_bindings["canon_hash"],
            "observed": candidate_canon_hash,
        })
    if str(reconciliation_manifest.get("canon_hash") or "") != decision_bindings["canon_hash"]:
        block(["current_binding_stale"], details={
            "binding": "reconciliation_manifest.canon_hash",
            "expected": decision_bindings["canon_hash"],
            "observed": reconciliation_manifest.get("canon_hash"),
        })
    if reconciliation_manifest.get("candidate_manifest_hash") != decision_bindings["candidate_manifest_hash"]:
        block(["candidate_manifest_hash_mismatch"], details={
            "binding": "reconciliation_manifest.candidate_manifest_hash",
            "expected": decision_bindings["candidate_manifest_hash"],
            "observed": reconciliation_manifest.get("candidate_manifest_hash"),
        })
    bindings = {
        **decision_bindings,
        "canon_hash_domain": "logical-content-concatenation",
        "candidate_manifest_hash_domain": "sha256-file",
        "reconciliation_manifest_hash_domain": "sha256-file",
        "source_decisions_hash": sha256_file(historical_decisions_file),
    }
    mappings: dict[str, dict[str, Any]] = {}
    for line_no, row in enumerate(load_jsonl(old_matrix_path), start=1):
        old_id = str(row.get("candidate_id") or "")
        if not old_id or old_id in mappings:
            block(["duplicate_source_decision_id"], details={"historical_candidate_id": old_id, "mapping_line": line_no})
        mappings[old_id] = row

    planned_by_current_id: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for old_id, old_decision in sorted(historical.items()):
        mapping = mappings.get(old_id)
        current_id = str((mapping or {}).get("counterpart_candidate_id") or "")
        candidate = queue_by_id.get(current_id)
        if (
            mapping
            and mapping.get("classification") == "equivalent"
            and mapping.get("decision_reusable") is True
            and candidate is None
        ):
            block(["current_candidate_not_found"], details={
                "historical_candidate_id": old_id,
                "current_id": current_id,
            })
        if (
            not mapping
            or mapping.get("classification") != "equivalent"
            or mapping.get("decision_reusable") is not True
            or candidate is None
        ):
            not_reused.append({
                "historical_candidate_id": old_id,
                "classification": (mapping or {}).get("classification") or "not_equivalent_or_not_reviewable",
                "reason_code": "current_candidate_not_found" if mapping and mapping.get("classification") == "equivalent" else None,
            })
            continue
        selected_count += 1
        rebound = dict(old_decision)
        rebound.update({
            "session_id": "S0183",
            "candidate_id": current_id,
            "source_canon_id": candidate_endpoint(candidate, "source"),
            "target_canon_id": candidate_endpoint(candidate, "target"),
            "predicate": str(candidate.get("relation_type") or ""),
            "relation_schema_version": str(candidate.get("candidate_schema_version") or candidate.get("schema_version") or ""),
            "reviewed_evidence_paths": list(old_decision.get("reviewed_evidence_paths") or []) + [
                str(cross_batch_manifest_path),
            ],
            "preserved_from_candidate_id": old_id,
            "preserved_from_decision_hash": decision_hash(old_decision),
            "preserved_from_bindings": {
                "canon_hash": old_decision.get("canon_hash"),
                "candidate_manifest_hash": old_decision.get("candidate_manifest_hash"),
                "reconciliation_manifest_hash": old_decision.get("reconciliation_manifest_hash"),
            },
            "preservation_classification": "equivalent",
            "preservation_manifest_hash": sha256_file(cross_batch_manifest_path),
            **decision_bindings,
        })
        errors = validate_human_review_decision_record(rebound)
        if errors:
            block(["source_decision_invalid"], details={"historical_candidate_id": old_id, "current_id": current_id, "errors": errors})
        changed_preserved = [
            field for field in MIGRATION_PRESERVED_FIELDS
            if rebound.get(field) != old_decision.get(field)
        ]
        if changed_preserved:
            block(["source_decision_invalid"], details={
                "historical_candidate_id": old_id,
                "message": "authority or provenance field changed during planning",
                "changed_fields": changed_preserved,
            })
        planned_by_current_id[current_id].append((old_id, old_decision, rebound))

    collisions: list[dict[str, Any]] = []
    for current_id in sorted(planned_by_current_id):
        origins = planned_by_current_id[current_id]
        if len(origins) < 2:
            continue
        collisions.append({
            "current_id": current_id,
            "source_decision_ids": [old_id for old_id, _, _ in origins],
            "source_states": [str(old.get("human_review_decision") or "") for _, old, _ in origins],
            "source_authorities": [str(old.get("human_review_actor") or "") for _, old, _ in origins],
            "source_bindings": [
                {
                    "historical_candidate_id": old_id,
                    "canon_hash": old.get("canon_hash"),
                    "candidate_manifest_hash": old.get("candidate_manifest_hash"),
                    "reconciliation_manifest_hash": old.get("reconciliation_manifest_hash"),
                }
                for old_id, old, _ in origins
            ],
            "reason_code": "many_to_one_current_id_collision",
        })
    if collisions:
        block(
            ["many_to_one_current_id_collision"],
            collisions=collisions,
            planned_count=selected_count,
        )

    ordered = {
        current_id: origins[0][2]
        for current_id, origins in sorted(planned_by_current_id.items())
    }
    if len(ordered) != selected_count:
        block(["duplicate_target_current_id"], details={
            "source_selected_count": selected_count,
            "planned_count": len(ordered),
        })
    if len(historical) != len(set(historical)):
        block(["duplicate_source_decision_id"])

    backup_path: Path | None = None
    written_count = 0
    target_modified = False
    if not dry_run:
        try:
            if destination_before is not None:
                backup_path = audit_dir / MIGRATION_BACKUP_FILE
                atomic_write_bytes(backup_path, destination_before)
                if backup_path.read_bytes() != destination_before:
                    raise OSError("migration backup verification failed")
            atomic_write_jsonl(destination, ordered)
            if load_jsonl(destination) != list(ordered.values()):
                raise OSError("published migration failed round-trip validation")
        except Exception as error:
            restore_destination()
            block(
                ["migration_plan_not_atomic"],
                details={"message": str(error)},
                planned_count=len(ordered),
                backup_path=backup_path,
            )
        written_count = len(ordered)
        target_modified = destination_before is None or destination.read_bytes() != destination_before

    counts = Counter(str(row.get("human_review_decision") or "") for row in ordered.values())
    pending_reviewable = sorted(set(queue_by_id) - set(ordered))
    report = {
        "schema_version": MIGRATION_REPORT_SCHEMA,
        "session_id": "m04-s0183",
        "operation": {
            "mode": "dry-run" if dry_run else "apply",
            "source_count": selected_count,
            "historical_count": historical_count,
            "planned_count": len(ordered),
            "written_count": written_count,
            "collision_count": 0,
            "allowed": True,
        },
        "bindings": bindings,
        "reason_codes": [],
        "collisions": [],
        "historical_decisions_path": str(historical_decisions_file),
        "historical_decisions_hash": sha256_file(historical_decisions_file),
        "historical_decision_count": len(historical),
        "cross_batch_manifest_path": str(cross_batch_manifest_path),
        "cross_batch_manifest_hash": sha256_file(cross_batch_manifest_path),
        "current_decisions_path": str(destination),
        "current_decisions_hash": sha256_file(destination) if destination.exists() else None,
        "migration_plan_hash": semantic_hash(ordered),
        "migrated_equivalent_count": written_count,
        "planned_equivalent_count": len(ordered),
        "approved": counts.get("approved_for_admission", 0),
        "deferred": counts.get("deferred", 0),
        "rejected": counts.get("rejected", 0),
        "not_reused": not_reused,
        "pending_reviewable_candidate_ids": pending_reviewable,
        "human_reauthorization_performed": False,
        "canon_modified": False,
        "output": {
            "target_path": str(destination),
            "backup_path": str(backup_path) if backup_path else None,
            "report_path": str(audit_path),
            "atomic_publish": not dry_run,
            "target_will_change": bool(ordered),
            "target_modified": target_modified,
            "partial_output": False,
        },
    }
    atomic_write_json(audit_path, report)
    return report | {"manifest_path": str(audit_path)}


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
    # Preserved historical decisions outside the current review queue are
    # provenance only.  They cannot be selected and must not make P(G) fail.
    unknown = exclusions - set(by_id)
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
    decisions_path = decision_authority_path(current_dir)
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
    # Revalidate after planning and immediately before the single atomic
    # replacement.  No subset has been published at this point.
    if current_bindings(current_dir, canon_root) != bindings:
        raise ValueError("batch_confirmation_generation_changed")
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
    decisions_path = decision_authority_path(current_dir)
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
    if current_bindings(current_dir, canon_root) != bindings:
        raise ValueError("batch_confirmation_generation_changed")
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
    decisions_path = decision_authority_path(current_dir)
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
    decisions_path = decision_authority_path(current_dir)
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
    decisions_path = decision_authority_path(current_dir)
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


def record_individual_decision(
    current_dir: Path, canon_root: Path, *, candidate_id: str, decision: str,
    reason_code: str, note: str, actor: str, confirmation: str,
) -> dict[str, Any]:
    """Record the FIRST governed decision for one named CURRENT candidate.

    S0186 Unit H (targeted initial decision): supersede_individual_decision()
    exists for an already-decided candidate; run_review() and the batch
    surfaces only ever record an initial decision by traversing/disposing an
    entire queue or batch. Nothing let an operator record a first decision
    for exactly one named, currently-undecided candidate_id without either
    deciding unrelated pending candidates first or requiring a decision that
    doesn't yet exist. This is that primitive -- same exact-candidate write
    path as supersede_individual_decision(), inverse precondition (no
    existing decision; if one exists, fail closed and require the
    supersession path instead), and no supersedes_decision_hash, since there
    is no prior decision to chain from.
    """
    if confirmation != DECISION_INITIAL_CONFIRMATION:
        raise ValueError(f"exact confirmation required: {DECISION_INITIAL_CONFIRMATION}")
    if decision not in DECISIONS:
        raise ValueError(f"unsupported decision: {decision}")
    reason_code = reason_code.strip().upper()
    if reason_code not in DECISION_REASON_CODES[decision] | EXCEPTION_REASON_CODES:
        raise ValueError(f"reason_code not valid for decision {decision!r}: {reason_code!r}")
    if not note.strip():
        raise ValueError("human_review_note required for an individually recorded decision")
    actor = validate_actor(actor)
    bindings = current_bindings(current_dir, canon_root)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    by_id = {str(row.get("candidate_id") or ""): row for row in queue}
    if candidate_id not in by_id:
        raise ValueError("candidate_id is not in current review queue")
    decisions_path = decision_authority_path(current_dir)
    decisions = load_existing_decisions(decisions_path, set(by_id), bindings)
    if candidate_id in decisions:
        raise ValueError(
            "candidate already has a current decision; use supersede_individual_decision() instead"
        )
    record = build_decision_record(
        by_id[candidate_id], decision=decision, reason_code=reason_code, note=note,
        actor=actor, bindings=bindings,
    )
    decisions[candidate_id] = record
    atomic_write_jsonl(decisions_path, decisions)
    try:
        append_audit(current_dir / AUDIT_FILE, record)
    except OSError as error:
        raise RuntimeError("authoritative decision persisted, but auxiliary audit append failed") from error
    return record


def _resolve_current_effective_decisions_path(current_dir: Path, canon_root: Path) -> Path:
    """Same 'prefer the published generational authority, fall back to the
    pipeline/current convenience file' rule the S0186 Unit H final
    intervention already established for tdc.sh's admission-gate dry-run
    (resolve_relation_human_review_decisions()) -- reused here for the
    read-only technically_invalid preview, not reinvented.
    """
    try:
        authority = resolve_current_relational_authority(canon_root)
        path = authority["artifacts"].get("effective_decisions")
        if path is not None:
            return path
    except CurrentRelationalAuthorityError:
        pass
    return decision_authority_path(current_dir)


def technically_invalid_approved_candidates(
    current_dir: Path = DEFAULT_CURRENT_DIR,
    canon_root: Path = DEFAULT_CANON_ROOT,
    gate_report: Path = DEFAULT_GATE_REPORT,
) -> list[dict[str, Any]]:
    """Read-only: CURRENT approved_for_admission candidates the admission
    gate marks technically_invalid (GATE-020 and any other admission-gate
    P0 reason). Reuses relation_admission_gate.build_apply_plan()'s own
    computation and its own full audit-detail payload per candidate
    (candidate_id, human_review_decision, gate_reasons, technical_evidence,
    audit_lineage, admitted=False) -- no new classification logic, zero
    writes.
    """
    candidates = admission_gate.load_jsonl(current_dir / QUEUE_FILE)
    candidates_by_id = {str(row.get("candidate_id") or ""): row for row in candidates}
    decisions_path = _resolve_current_effective_decisions_path(current_dir, canon_root)
    decisions, errors = admission_gate.load_persistent_human_review_decisions(decisions_path)
    if errors:
        raise ValueError("; ".join(errors))
    dry_run_report = admission_gate.load_dry_run_report(gate_report)
    plan = admission_gate.build_apply_plan(
        candidates=candidates,
        canon_glob=str(canon_root / "tiddlers_*.jsonl"),
        human_review_decisions=decisions,
        dry_run_report=dry_run_report,
        dry_run_report_path=gate_report,
        dry_run_recent=True,
    )
    details = list(plan.get("technically_invalid_candidates") or [])
    for detail in details:
        candidate = candidates_by_id.get(str(detail.get("candidate_id") or "")) or {}
        detail["source"] = candidate.get("source") or {}
        detail["target"] = candidate.get("target") or {}
        detail["relation_type"] = candidate.get("relation_type") or (candidate.get("relation") or {}).get("type")
    return details


def render_technically_invalid_candidate(detail: dict[str, Any]) -> None:
    review = detail.get("human_review_decision") or {}
    source = detail.get("source") or {}
    target = detail.get("target") or {}
    print(f"\nCandidate ID: {detail.get('candidate_id')}")
    print(
        f"  Relación: {source.get('canonical_id', '?')} -> {target.get('canonical_id', '?')} "
        f"({detail.get('relation_type', '?')})"
    )
    print(f"  Razones GATE: {', '.join(detail.get('gate_reasons') or []) or '(ninguna registrada)'}")
    print(f"  Decisión humana vigente: {review.get('human_review_decision')} "
          f"(actor={review.get('human_review_actor')}, "
          f"razón={review.get('human_review_reason_code')}, "
          f"fecha={review.get('human_review_timestamp')})")
    print(f"  Admitida: {detail.get('admitted')}")
    print(f"  Evidencia técnica: {json.dumps(detail.get('technical_evidence') or {}, ensure_ascii=False, sort_keys=True)}")
    print(f"  Linaje de auditoría: {json.dumps(detail.get('audit_lineage') or {}, ensure_ascii=False, sort_keys=True)}")


def current_technical_supersession_eligible_candidates(
    current_dir: Path, canon_root: Path, gate_report: Path,
) -> list[dict[str, Any]]:
    """Read-only: CURRENT (live) approved_for_admission candidates blocked
    as technically_invalid whose ENTIRE gate_reasons set belongs
    exclusively to the GATE-020 (repo lifecycle metadata) family.

    Reuses relation_admission_gate.build_apply_plan()'s own technically_
    invalid partition -- no new classification logic, zero writes -- and
    reads the LIVE decision authority (decision_authority_path), never the
    last published bundle: a candidate already superseded individually but
    not yet republished must be excluded here, not double-counted.

    Automatically excludes (by construction, via build_apply_plan's own
    partition): candidates already deferred/rejected, candidates that are
    not approved_for_admission, admission_ready candidates, candidates
    already canonically admitted, and anything outside the live CURRENT
    review queue. Also excludes any candidate carrying even one non-
    GATE-020 reason alongside GATE-020 ones -- mixed-cause candidates are
    never eligible for this homogeneous batch.
    """
    candidates = admission_gate.load_jsonl(current_dir / QUEUE_FILE)
    candidates_by_id = {str(row.get("candidate_id") or ""): row for row in candidates}
    decisions_path = decision_authority_path(current_dir)
    decisions, errors = admission_gate.load_persistent_human_review_decisions(decisions_path)
    if errors:
        raise ValueError("; ".join(errors))
    dry_run_report = admission_gate.load_dry_run_report(gate_report)
    plan = admission_gate.build_apply_plan(
        candidates=candidates,
        canon_glob=str(canon_root / "tiddlers_*.jsonl"),
        human_review_decisions=decisions,
        dry_run_report=dry_run_report,
        dry_run_report_path=gate_report,
        dry_run_recent=True,
    )
    eligible: list[dict[str, Any]] = []
    for detail in plan.get("technically_invalid_candidates") or []:
        reasons = list(detail.get("gate_reasons") or [])
        if not reasons or any(
            not str(reason).startswith(TECHNICAL_SUPERSESSION_GATE_FAMILY_PREFIX)
            for reason in reasons
        ):
            continue
        candidate_id = str(detail.get("candidate_id") or "")
        candidate = candidates_by_id.get(candidate_id) or {}
        eligible.append({
            "candidate_id": candidate_id,
            "gate_reasons": sorted(reasons),
            "human_review_decision": detail.get("human_review_decision") or {},
            "source": candidate.get("source") or {},
            "target": candidate.get("target") or {},
            "relation_type": candidate.get("relation_type"),
        })
    return sorted(eligible, key=lambda item: str(item["candidate_id"]))


def technical_supersession_candidate_set_hash(
    candidate_ids: list[str], decision: str, reason_code: str, note: str,
) -> str:
    payload = {
        "candidate_ids": sorted(candidate_ids),
        "decision": decision,
        "reason_code": reason_code,
        "note": note.strip(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def technical_supersession_operation_id(
    candidate_set_hash: str, bindings: dict[str, str],
) -> str:
    payload = {"candidate_set_hash": candidate_set_hash, "bindings": bindings}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "hrm_" + hashlib.sha256(encoded).hexdigest()[:24]


def build_current_technical_supersession_preview(
    current_dir: Path, canon_root: Path, gate_report: Path, *, note: str,
) -> dict[str, Any]:
    """Read-only preview for a single governed operation that supersedes
    every CURRENT approved_for_admission candidate blocked exclusively by
    the GATE-020 family, to one uniform deferred/LIFECYCLE_UNRESOLVED
    decision. Zero writes; only the paired persist function (given this
    exact preview, unmodified) writes anything.
    """
    if not note.strip():
        raise ValueError("human_review_note required for technical supersession preview")
    eligible = current_technical_supersession_eligible_candidates(current_dir, canon_root, gate_report)
    if not eligible:
        raise ValueError(
            "no CURRENT approved_for_admission candidates are blocked exclusively by GATE-020"
        )
    candidate_ids = [item["candidate_id"] for item in eligible]
    bindings = current_bindings(current_dir, canon_root)
    candidate_set_hash = technical_supersession_candidate_set_hash(
        candidate_ids, TECHNICAL_SUPERSESSION_DECISION, TECHNICAL_SUPERSESSION_REASON_CODE, note,
    )
    batch_id = "hrb_" + candidate_set_hash[:24]
    operation_id = technical_supersession_operation_id(candidate_set_hash, bindings)
    partitions: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for item in eligible:
        partitions[tuple(item["gate_reasons"])].append(item["candidate_id"])
    pointer_path = canon_root / "audit" / "relation_admission" / "current_generation.json"
    pointer = load_json(pointer_path) if pointer_path.is_file() else {}
    return {
        "schema_version": "current-technical-supersession-preview/v1",
        "batch_id": batch_id,
        "operation_id": operation_id,
        "candidate_set_hash": candidate_set_hash,
        "relation_generation_id": pointer.get("relation_generation_id"),
        "review_state_id": pointer.get("review_state_id"),
        "current_terminal_state": pointer.get("terminal_state"),
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "partitions": [
            {
                "gate_reasons": list(key),
                "candidate_count": len(ids),
                "candidate_ids": sorted(ids),
            }
            for key, ids in sorted(partitions.items())
        ],
        "current_decisions": {
            item["candidate_id"]: {
                "human_review_decision": (item["human_review_decision"] or {}).get(
                    "human_review_decision"
                ),
                "human_review_reason_code": (item["human_review_decision"] or {}).get(
                    "human_review_reason_code"
                ),
            }
            for item in eligible
        },
        "proposed_decision": TECHNICAL_SUPERSESSION_DECISION,
        "proposed_reason_code": TECHNICAL_SUPERSESSION_REASON_CODE,
        "proposed_note": note.strip(),
        "bindings": bindings,
        "confirmation_required": f"{TECHNICAL_SUPERSESSION_CONFIRMATION_PREFIX} {batch_id}",
        "writes_performed": False,
    }


def render_current_technical_supersession_preview(preview: dict[str, Any]) -> None:
    print("\nLote CURRENT GATE-020 -- aprobadas con bloqueo técnico homogéneo")
    print(f"Batch ID: {preview['batch_id']}")
    print(f"Operación: {preview['operation_id']}")
    print(f"relation_generation_id: {preview.get('relation_generation_id')}")
    print(f"review_state_id: {preview.get('review_state_id')}")
    print(f"Candidatas: {preview['candidate_count']}")
    print(f"Decisión propuesta: {preview['proposed_decision']}")
    print(f"Razón propuesta: {preview['proposed_reason_code']}")
    print(f"Nota: {preview['proposed_note']}")
    print("Partición por razones GATE exactas:")
    for partition in preview["partitions"]:
        print(
            f"  - {partition['candidate_count']} candidatas | "
            + " + ".join(partition["gate_reasons"])
        )
    print(f"Hash del lote: {preview['candidate_set_hash']}")
    print(f"Confirmación requerida: {preview['confirmation_required']}")


def persist_current_technical_supersession(
    current_dir: Path, canon_root: Path, gate_report: Path, *,
    preview: dict[str, Any], actor: str, confirmation: str,
) -> dict[str, Any]:
    """Persist one governed multi-candidate supersession: one individually
    hashed, individually audited decision record per candidate, all
    sharing one multi_review_operation_id, written in a single atomic
    replace of the decision authority file (all-or-nothing -- there is no
    code path that leaves a subset silently written). Never touches Canon.

    Fail-closed by re-derivation, not by trusting the given preview: the
    eligible universe, CURRENT bindings, and candidate_set_hash are all
    recomputed fresh from live CURRENT authority and required to match the
    preview bit-for-bit. Any drift at all -- a candidate resolved or newly
    ineligible, canon/candidate/reconciliation state changed since preview,
    a tampered candidate list -- blocks the WHOLE operation, never a
    partial or silently-adjusted write.
    """
    batch_id = str(preview.get("batch_id") or "")
    expected_confirmation = f"{TECHNICAL_SUPERSESSION_CONFIRMATION_PREFIX} {batch_id}"
    if not batch_id or confirmation != expected_confirmation:
        raise ValueError(f"exact confirmation required: {expected_confirmation}")
    note = str(preview.get("proposed_note") or "")
    if not note.strip():
        raise ValueError("human_review_note required for technical supersession")
    decision = str(preview.get("proposed_decision") or "")
    reason_code = str(preview.get("proposed_reason_code") or "")
    if decision not in DECISIONS:
        raise ValueError(f"unsupported decision: {decision}")
    if reason_code not in DECISION_REASON_CODES[decision] | EXCEPTION_REASON_CODES:
        raise ValueError(f"reason_code not valid for decision {decision!r}: {reason_code!r}")
    actor = validate_actor(actor)
    operation_id = str(preview.get("operation_id") or "")
    if not operation_id:
        raise ValueError("technical supersession preview is missing operation_id")

    fresh_eligible = current_technical_supersession_eligible_candidates(
        current_dir, canon_root, gate_report,
    )
    fresh_candidate_ids = [item["candidate_id"] for item in fresh_eligible]
    bindings = current_bindings(current_dir, canon_root)
    expected_candidate_set_hash = technical_supersession_candidate_set_hash(
        fresh_candidate_ids, decision, reason_code, note,
    )
    if (
        bindings != (preview.get("bindings") or {})
        or fresh_candidate_ids != list(preview.get("candidate_ids") or [])
        or expected_candidate_set_hash != preview.get("candidate_set_hash")
    ):
        raise ValueError("current_technical_supersession_batch_stale")

    queue = load_jsonl(current_dir / QUEUE_FILE)
    by_id = {str(row.get("candidate_id") or ""): row for row in queue}
    missing = sorted(set(fresh_candidate_ids) - set(by_id))
    if missing:
        raise ValueError(f"candidate_id not in current review queue: {missing}")

    decisions_path = decision_authority_path(current_dir)
    decisions = load_existing_decisions(decisions_path, set(by_id), bindings)
    missing_previous = sorted(cid for cid in fresh_candidate_ids if cid not in decisions)
    if missing_previous:
        raise ValueError(f"candidate has no current decision to supersede: {missing_previous}")

    new_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate_id in fresh_candidate_ids:
        previous = decisions[candidate_id]
        record = build_decision_record(
            by_id[candidate_id], decision=decision, reason_code=reason_code, note=note,
            actor=actor, bindings=bindings, decision_mode="batch",
            decision_batch_id=batch_id, multi_review_operation_id=operation_id,
            supersedes_decision_hash=decision_hash(previous),
        )
        decisions[candidate_id] = record
        new_records.append((record, previous))

    # Revalidate immediately before the single atomic replacement, exactly
    # like the existing single-batch/multi-batch primitives: no subset has
    # been published at this point.
    if current_bindings(current_dir, canon_root) != bindings:
        raise ValueError("current_technical_supersession_batch_stale")
    atomic_write_jsonl(decisions_path, decisions)

    receipt = {
        "schema_version": "current-technical-supersession-receipt/v1",
        "operation_id": operation_id,
        "batch_id": batch_id,
        "eligible_count": len(fresh_candidate_ids),
        "candidate_ids": fresh_candidate_ids,
        "candidate_decision_hashes": {
            record["candidate_id"]: decision_hash(record) for record, _ in new_records
        },
        "decision": decision,
        "reason_code": reason_code,
        "note": note.strip(),
        "actor": actor,
        "confirmation": confirmation,
        "source_review_state_id": preview.get("review_state_id"),
        "relation_generation_id": preview.get("relation_generation_id"),
        "canon_hash": bindings["canon_hash"],
        "decisions_written": len(new_records),
        "failures": 0,
        "recorded_at": utc_now(),
    }
    append_auxiliary_event(current_dir / TECHNICAL_SUPERSESSION_RECEIPTS_FILE, receipt)

    try:
        for record, previous in new_records:
            append_audit(current_dir / AUDIT_FILE, record, previous=previous)
    except OSError as error:
        raise RuntimeError(
            "authoritative technical supersession batch persisted, "
            "but auxiliary audit append failed"
        ) from error
    return receipt


def _run_current_technical_supersession_batch(
    current_dir: Path, canon_root: Path, gate_report: Path,
) -> int:
    """Interactive wrapper around build_current_technical_supersession_
    preview()/persist_current_technical_supersession(): preview is entirely
    read-only; only the final, explicit, batch-specific confirmation calls
    the write primitive. The machine never proposes or defers a decision
    on the human's behalf beyond the single, already-confirmed, uniform
    deferred/LIFECYCLE_UNRESOLVED proposal for the exact GATE-020-only
    homogeneous universe.
    """
    try:
        note = input(
            "Nota común obligatoria para las 170 (o el universo vigente): "
        ).strip()
    except EOFError:
        note = ""
    if not note:
        print("Nota obligatoria; no se escribió ninguna decisión.")
        return 2
    try:
        preview = build_current_technical_supersession_preview(
            current_dir, canon_root, gate_report, note=note,
        )
    except ValueError as error:
        print(f"[ERROR] {error}")
        return 2
    render_current_technical_supersession_preview(preview)
    print(
        "\nNinguna decisión se ha escrito todavía. La supersesión NO es automática:\n"
        "usted debe confirmar explícitamente el lote completo."
    )
    try:
        proceed = input("¿Confirmar la supersesión de todo el lote? (s/N): ").strip().lower()
    except EOFError:
        proceed = ""
    if proceed != "s":
        print("Sin cambios; no se escribió ninguna decisión.")
        return 0
    try:
        actor = input("Identidad del revisor humano: ").strip()
        confirmation = input(
            f"Escriba exactamente {preview['confirmation_required']}: "
        ).strip()
    except EOFError:
        print("Entrada incompleta; no se escribió ninguna decisión.")
        return 2
    try:
        receipt = persist_current_technical_supersession(
            current_dir, canon_root, gate_report,
            preview=preview, actor=actor, confirmation=confirmation,
        )
    except ValueError as error:
        print(f"[ERROR] {error}")
        return 2
    print(f"Lote persistido: {receipt['decisions_written']} decisiones individuales "
          f"ligadas a la operación {receipt['operation_id']}.")
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def review_technically_invalid_candidates_menu(
    current_dir: Path = DEFAULT_CURRENT_DIR,
    canon_root: Path = DEFAULT_CANON_ROOT,
    gate_report: Path = DEFAULT_GATE_REPORT,
) -> int:
    """Operator surface for TASK B: expose the existing, already-governed
    supersede_individual_decision() primitive for CURRENT approved
    candidates blocked as technically_invalid. Preview is entirely
    read-only (zero decision or Canon writes); only the final, explicit
    confirmation step calls the existing write primitive. The machine
    never proposes or defers a decision on the human's behalf.
    """
    try:
        candidates = technically_invalid_approved_candidates(current_dir, canon_root, gate_report)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[ERROR] no se pudo resolver el universo technically_invalid: {error}")
        return 2
    if not candidates:
        print("No hay candidatas approved_for_admission bloqueadas como technically_invalid en CURRENT.")
        return 0
    print(f"\nRevisar aprobadas con bloqueo técnico (CURRENT) -- {len(candidates)} candidatas")
    for index, detail in enumerate(candidates, start=1):
        print(f"{index}) {detail.get('candidate_id')}")
    try:
        choice = input(
            "Seleccione número para inspeccionar individualmente, "
            "'b' para el lote homogéneo GATE-020 [Enter/0 = volver]: "
        ).strip()
    except EOFError:
        choice = ""
    if not choice or choice == "0":
        return 0
    if choice.lower() == "b":
        return _run_current_technical_supersession_batch(current_dir, canon_root, gate_report)
    try:
        selected = candidates[int(choice) - 1]
    except (ValueError, IndexError):
        print("Selección inválida.")
        return 2
    render_technically_invalid_candidate(selected)
    candidate_id = str(selected.get("candidate_id") or "")
    print(
        "\nEsta candidata permanece approved_for_admission y technically_invalid.\n"
        "Ninguna decisión se ha escrito todavía. El diferimiento NO es automático:\n"
        "usted debe elegir explícitamente."
    )
    try:
        proceed = input("¿Proponer una decisión superseding para esta candidata? (s/N): ").strip().lower()
    except EOFError:
        proceed = ""
    if proceed != "s":
        print("Sin cambios; no se escribió ninguna decisión.")
        return 0
    print(f"Decisiones válidas: {sorted(DECISIONS)}")
    try:
        new_decision = input("Nueva decisión: ").strip()
        reason_code = input("Código de razón: ").strip()
        note = input("Nota (obligatoria): ").strip()
        actor = input("Identidad del revisor humano: ").strip()
        confirmation = input(f"Escriba exactamente {DECISION_SUPERSESSION_CONFIRMATION}: ").strip()
    except EOFError:
        print("Entrada incompleta; no se escribió ninguna decisión.")
        return 2
    if confirmation != DECISION_SUPERSESSION_CONFIRMATION:
        print("Confirmación inválida; no se escribió ninguna decisión.")
        return 2
    try:
        record = supersede_individual_decision(
            current_dir, canon_root, candidate_id=candidate_id, decision=new_decision,
            reason_code=reason_code, note=note, actor=actor, confirmation=confirmation,
        )
    except ValueError as error:
        print(f"[ERROR] {error}")
        return 2
    print("Decisión de supersesión persistida:")
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


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
    preflight = validate_human_review_batch_generation(current_dir, canon_root, gate_report_path)
    if not preflight["allowed"]:
        print("BATCH_CONFIRMATION_BLOCKED")
        print(json.dumps(preflight, ensure_ascii=False, sort_keys=True))
        return 2
    actor = validate_actor(actor)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    gate_report = load_json(gate_report_path)
    bindings = current_bindings(current_dir, canon_root)
    decisions = load_existing_decisions(
        decision_authority_path(current_dir),
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
    preflight = validate_human_review_batch_generation(current_dir, canon_root, gate_report_path)
    if not preflight["allowed"]:
        print("BATCH_CONFIRMATION_BLOCKED")
        print(json.dumps(preflight, ensure_ascii=False, sort_keys=True))
        return 2
    actor = validate_actor(actor)
    queue = load_jsonl(current_dir / QUEUE_FILE)
    gate_report = load_json(gate_report_path)
    bindings = current_bindings(current_dir, canon_root)
    decisions = load_existing_decisions(
        decision_authority_path(current_dir),
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
    parser.add_argument(
        "--detail", action="store_true",
        help="with --preview-batches on the current review surface, print full per-candidate rows instead of the compact summary",
    )
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
    parser.add_argument(
        "--review-technically-invalid", action="store_true",
        help="inspect CURRENT approved_for_admission candidates blocked as technically_invalid; propose a superseding decision only on explicit confirmation",
    )
    parser.add_argument("--supersede-candidate", metavar="CANDIDATE_ID")
    parser.add_argument(
        "--decide-candidate", metavar="CANDIDATE_ID",
        help="record the FIRST decision for one named, currently-undecided CURRENT candidate; fails closed if a decision already exists (use --supersede-candidate instead)",
    )
    parser.add_argument("--decision", choices=sorted(DECISIONS))
    parser.add_argument("--reason-code")
    parser.add_argument("--note", default="")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--audit-root", type=Path, default=DEFAULT_S0181_AUDIT_ROOT)
    parser.add_argument("--migrate-equivalent", action="store_true")
    parser.add_argument("--historical-decisions", type=Path)
    parser.add_argument("--cross-batch-manifest", type=Path)
    parser.add_argument("--migration-audit-dir", type=Path)
    parser.add_argument(
        "--migration-apply",
        action="store_true",
        help="publish a validated one-to-one migration; default is fail-safe dry-run",
    )
    args = parser.parse_args(argv)
    if args.preview_batches or args.review_batches or args.review_multiple_batches or args.apply_batch:
        args.gate_report = resolve_current_gate_report(args.canon_root, args.gate_report)
    if args.migrate_equivalent:
        if not args.historical_decisions or not args.cross_batch_manifest:
            print("[ERROR] --historical-decisions and --cross-batch-manifest are required")
            return 2
        try:
            report = migrate_equivalent_decisions(
                historical_decisions_file=args.historical_decisions,
                current_dir=args.current_dir,
                canon_root=args.canon_root,
                cross_batch_manifest_path=args.cross_batch_manifest,
                audit_dir=args.migration_audit_dir or args.audit_root,
                dry_run=not args.migration_apply,
            )
        except HumanDecisionMigrationBlocked as error:
            print("HUMAN_DECISION_MIGRATION_BLOCKED")
            blocked_report = load_json(error.report_path)
            collisions = blocked_report.get("collisions") or []
            if collisions:
                print("Se detectó una convergencia many-to-one:")
                for collision in collisions:
                    print(f"- current_id: {collision.get('current_id')}")
                    origins = ", ".join(collision.get("source_decision_ids") or [])
                    print(f"  decisiones históricas implicadas: {origins}")
            else:
                print("Se detectó una migración de decisiones humanas no autorizable.")
            print(f"Reason codes: {', '.join(error.reason_codes)}")
            print(f"Reporte: {error.report_path}")
            print("No se migró ninguna decisión.")
            print("No se modificó el canon.")
            print("No se creó un gate.")
            return 2
        except ValueError as error:
            print(f"[ERROR] {error}")
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if not report["pending_reviewable_candidate_ids"] else 3
    if args.status:
        bindings = current_bindings(args.current_dir, args.canon_root)
        queue = load_jsonl(args.current_dir / QUEUE_FILE)
        decisions_path = decision_authority_path(args.current_dir)
        raw = load_jsonl(decisions_path)
        official = [row for row in raw if row.get("schema_version") == SCHEMA_HUMAN_DECISION_LINE]
        legacy = [row for row in raw if row.get("schema_version") == SCHEMA_HUMAN_DECISION_LINE_LEGACY]
        if official:
            load_existing_decisions(
                decisions_path,
                {str(x.get("candidate_id") or "") for x in queue}, bindings,
            )
        print(json.dumps({
            "queue": len(queue), "official_decisions": len(official),
            "legacy_decisions_pending_supersession": len(legacy),
            "pending": len(queue) - len(official), **bindings,
        }, indent=2))
        return 0
    if args.review_technically_invalid:
        return review_technically_invalid_candidates_menu(
            args.current_dir, args.canon_root, args.gate_report,
        )
    try:
        if args.preview_batches or args.apply_batch:
            preflight = validate_human_review_batch_generation(
                args.current_dir, args.canon_root, args.gate_report,
            )
            if not preflight["allowed"]:
                print("BATCH_PREVIEW_BLOCKED")
                print(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True))
                return 2
            if args.preview_batches and preflight.get("current_review_surface"):
                # The current human delta has no implied approve/defer/reject
                # action.  Its preview is strictly an inspection surface;
                # only a later explicit human decision may select an action.
                surface = resolve_current_human_delta_surface(args.canon_root)
                batches = build_current_human_delta_batches(surface)
                if args.detail:
                    current_human_delta: dict[str, Any] = surface["inventory"]
                    review_batches: list[dict[str, Any]] = batches
                else:
                    current_human_delta = {
                        key: value for key, value in surface["inventory"].items()
                        if key != "candidates"
                    }
                    review_batches = [
                        {
                            key: value for key, value in batch.items()
                            if key not in ("candidate_ids", "candidate_hashes")
                        } | {"candidate_count": len(batch["candidate_ids"])}
                        for batch in batches
                    ]
                print(json.dumps({
                    "schema_version": "current-human-delta-review-preview/v1",
                    "verdict": "BATCH_PREVIEW_READY",
                    "mode": "read_only_preview",
                    "writes_performed": False,
                    "detail": bool(args.detail),
                    "current_authority": {
                        "relation_generation_id": surface["inventory"]["relation_generation_id"],
                        "review_state_id": surface["inventory"]["review_state_id"],
                        "bundle_manifest_hash": surface["inventory"]["bundle_manifest_hash"],
                    },
                    "current_human_delta": current_human_delta,
                    "review_batches": review_batches,
                    "next_action": "HUMAN_SELECTS_ACTION_FOR_CURRENT_DELTA",
                    "detail_instruction": (
                        None if args.detail
                        else "re-run with --detail for full per-candidate rows"
                    ),
                }, ensure_ascii=False, indent=2, sort_keys=True))
                return 0
            if args.apply_batch and preflight.get("current_review_surface"):
                print("BATCH_CONFIRMATION_BLOCKED")
                print(json.dumps({
                    "allowed": False,
                    "reason_codes": ["current_review_write_boundary_not_prepared"],
                    "instruction": "re-preview after an explicit current review write boundary is published",
                }, ensure_ascii=False, indent=2, sort_keys=True))
                return 2
            queue = load_jsonl(args.current_dir / QUEUE_FILE)
            gate_report = preflight["gate"]
            raw = load_jsonl(decision_authority_path(args.current_dir))
            decided_ids = {
                str(row.get("candidate_id") or "")
                for row in raw if row.get("schema_version") == SCHEMA_HUMAN_DECISION_LINE
            }
            previews = build_batch_previews(
                queue, gate_report, exclusions=set(args.exclude), decided_ids=decided_ids,
            )
            if args.preview_batches:
                print(json.dumps(build_generation_batch_preview(previews, preflight), ensure_ascii=False, indent=2, sort_keys=True))
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
        if args.review_batches or args.review_multiple_batches:
            # Do not request a human identity until the operation itself is
            # generationally admissible.  A stale generation is not a review.
            preflight = validate_human_review_batch_generation(
                args.current_dir, args.canon_root, args.gate_report,
            )
            if not preflight["allowed"]:
                print("BATCH_CONFIRMATION_BLOCKED")
                print(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True))
                return 2
            if preflight.get("current_review_surface"):
                if args.review_multiple_batches:
                    print("BATCH_CONFIRMATION_BLOCKED")
                    print(json.dumps({
                        "allowed": False,
                        "reason_codes": ["current_multiple_review_out_of_scope"],
                        "instruction": "use the single current batch review boundary",
                    }, ensure_ascii=False, indent=2, sort_keys=True))
                    return 2
                return run_current_single_batch_review(args.canon_root, args.reviewer)
            actor = args.reviewer if args.reviewer is not None else input("Identidad del revisor humano: ")
            actor = validate_actor(actor)
            if args.review_batches:
                return run_batch_review(args.current_dir, args.canon_root, args.gate_report, actor)
            return run_multiple_batch_review(args.current_dir, args.canon_root, args.gate_report, actor)
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
        if args.decide_candidate:
            if not args.decision or not args.reason_code:
                raise ValueError("--decision and --reason-code are required")
            record = record_individual_decision(
                args.current_dir, args.canon_root, candidate_id=args.decide_candidate,
                decision=args.decision, reason_code=args.reason_code, note=args.note,
                actor=actor, confirmation=args.confirmation,
            )
            print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
    except ValueError as error:
        print(f"[ERROR] {error}")
        return 2
    return run_review(args.current_dir, args.canon_root, actor)


if __name__ == "__main__":
    raise SystemExit(main())
