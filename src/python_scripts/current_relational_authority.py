"""Single fail-closed resolver for the current relational generation.

The pointer is the only operational root.  Pipeline ``current`` and S0183
remain useful review/provenance surfaces, but never decide an authorization or
an apply.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import Any, Iterator


SCHEMA_POINTER = "current-relational-generation-pointer/v1"
SCHEMA_BUNDLE = "current-relational-generation-bundle/v1"
REQUIRED_AUTHORIZATION_ARTIFACTS = {
    "candidate_manifest", "validation_report", "reconciliation_manifest",
    "reviewable_manifest", "relation_candidates", "ready_queue",
    "effective_decisions", "decision_checkpoint", "admission_gate", "gate_g",
    "apply_plan", "rollback_snapshot", "authorization_request",
}
REQUIRED_HUMAN_DELTA_ARTIFACTS = {
    "candidate_manifest", "validation_report", "reconciliation_manifest",
    "reviewable_manifest", "relation_candidates", "ready_queue",
    "effective_decisions", "decision_checkpoint", "admission_gate",
    "pending_queue", "batch_inventory", "current_human_delta",
    "review_rebaseline", "review_rebaseline_checkpoint",
    "independent_decision_preservation",
}
HUMAN_PENDING_PLACEHOLDER_ARTIFACTS = {
    "gate_g", "apply_plan", "rollback_snapshot", "authorization_request",
}
TERMINAL_NEXT_ACTION = {
    "READY_FOR_HUMAN_DELTA_REVIEW": "REVIEW_CURRENT_RELATIONAL_DELTA",
    "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION": (
        "PREPARE_CURRENT_RELATIONAL_READINESS"
    ),
    "READY_FOR_AUTHORIZATION": "AUTHORIZE_CURRENT_RELATIONAL_APPLY",
}


class CurrentRelationalAuthorityError(ValueError):
    def __init__(self, *reason_codes: str) -> None:
        self.reason_codes = sorted(set(reason_codes)) or ["current_bundle_invalid"]
        super().__init__(", ".join(self.reason_codes))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def current_pointer_lock(pointer_path: Path) -> Iterator[None]:
    """Hold the process-shared publication lock for one pointer directory."""
    pointer_path = Path(pointer_path)
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = pointer_path.parent / ".current_generation.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def compare_and_swap_current_pointer(
    pointer_path: Path,
    *,
    expected: bytes | None,
    replacement: bytes | None,
) -> bool:
    """Atomically install ``replacement`` iff current bytes equal ``expected``.

    ``None`` represents an absent pointer on either side of the comparison.
    This makes the same primitive suitable for publication and rollback.  JSON
    serialization deliberately remains a caller responsibility so that the
    comparison is byte-exact.  The return value is ``True`` only when this
    caller installed (or removed) the pointer.  Even a byte-identical value
    installed by a peer is a failed comparison: treating it as success would
    let this caller return while the peer still owns a possible rollback.
    """
    pointer_path = Path(pointer_path)
    temporary_path: Path | None = None
    with current_pointer_lock(pointer_path):
        try:
            observed = pointer_path.read_bytes()
        except FileNotFoundError:
            observed = None
        if observed != expected:
            raise CurrentRelationalAuthorityError("current_pointer_changed")

        if replacement is None:
            if observed is not None:
                pointer_path.unlink()
                _fsync_directory(pointer_path.parent)
            return True

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{pointer_path.name}.",
            suffix=".tmp",
            dir=pointer_path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(replacement)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, pointer_path)
            temporary_path = None
            _fsync_directory(pointer_path.parent)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return True


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CurrentRelationalAuthorityError("current_bundle_invalid") from error
    if not isinstance(value, dict):
        raise CurrentRelationalAuthorityError("current_bundle_invalid")
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _receipt_lineage_coverage_valid(
    descriptor: dict[str, Any], receipts: list[Any],
) -> bool:
    """Validate that v1/v2 segments form exact, uniquely ordered review chains."""
    if not receipts or any(not isinstance(receipt, dict) for receipt in receipts):
        return False
    receipt_ids = [receipt.get("receipt_id") for receipt in receipts]
    if (
        any(not isinstance(receipt_id, str) or not receipt_id for receipt_id in receipt_ids)
        or len(receipt_ids) != len(set(receipt_ids))
    ):
        return False
    declared_ids = descriptor.get("receipt_ids")
    if (
        not isinstance(declared_ids, list)
        or any(not isinstance(receipt_id, str) or not receipt_id for receipt_id in declared_ids)
        or len(declared_ids) != len(set(declared_ids))
        or set(declared_ids) != set(receipt_ids)
    ):
        return False
    receipt_by_id = {
        str(receipt["receipt_id"]): receipt for receipt in receipts
    }
    schema = descriptor.get("schema_version")
    if schema == "current-review-receipt-lineage/v1":
        segments = [{
            "relation_generation_id": descriptor.get(
                "source_relation_generation_id"
            ),
            "root_review_state_id": descriptor.get("root_review_state_id"),
            "tip_review_state_id": descriptor.get("tip_review_state_id"),
            "receipt_ids": descriptor.get("receipt_ids"),
        }]
    elif schema == "current-review-receipt-lineage/v2":
        segments = descriptor.get("segments")
    else:
        return False
    if not isinstance(segments, list) or not segments:
        return False
    relation_ids: set[str] = set()
    covered_ids: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            return False
        relation_id = segment.get("relation_generation_id")
        segment_receipt_ids = segment.get("receipt_ids")
        if (
            not isinstance(relation_id, str)
            or not relation_id
            or relation_id in relation_ids
            or not isinstance(segment_receipt_ids, list)
            or not segment_receipt_ids
            or any(
                not isinstance(receipt_id, str) or not receipt_id
                for receipt_id in segment_receipt_ids
            )
            or len(segment_receipt_ids) != len(set(segment_receipt_ids))
        ):
            return False
        relation_ids.add(relation_id)
        segment_receipts: list[dict[str, Any]] = []
        for receipt_id in segment_receipt_ids:
            receipt = receipt_by_id.get(receipt_id)
            if (
                receipt is None
                or receipt.get("source_relation_generation_id") != relation_id
            ):
                return False
            segment_receipts.append(receipt)
            covered_ids.append(receipt_id)
        sources = [
            receipt.get("source_review_state_id")
            for receipt in segment_receipts
        ]
        results = [
            receipt.get("result_review_state_id")
            for receipt in segment_receipts
        ]
        if (
            any(not isinstance(value, str) or not value for value in sources + results)
            or len(sources) != len(set(sources))
            or len(results) != len(set(results))
        ):
            return False
        roots = set(sources) - set(results)
        tips = set(results) - set(sources)
        if len(roots) != 1 or len(tips) != 1:
            return False
        root = next(iter(roots))
        tip = next(iter(tips))
        if (
            segment.get("root_review_state_id") != root
            or segment.get("tip_review_state_id") != tip
        ):
            return False
        by_source = {
            str(receipt["source_review_state_id"]): receipt
            for receipt in segment_receipts
        }
        cursor = root
        visited = 0
        while cursor in by_source:
            cursor = str(by_source[cursor]["result_review_state_id"])
            visited += 1
            if visited > len(segment_receipts):
                return False
        if visited != len(segment_receipts) or cursor != tip:
            return False
    return (
        len(covered_ids) == len(set(covered_ids))
        and set(covered_ids) == set(receipt_ids)
    )


def resolve_current_relational_authority(local_root: Path) -> dict[str, Any]:
    """Resolve and validate the immutable current bundle without fallbacks."""
    local_root = local_root.resolve()
    admission_root = local_root / "audit" / "relation_admission"
    generations = admission_root / "generations"
    pointer_path = admission_root / "current_generation.json"
    if not pointer_path.is_file():
        raise CurrentRelationalAuthorityError("current_bundle_missing")
    pointer = read_json(pointer_path)
    if pointer.get("schema_version") != SCHEMA_POINTER:
        raise CurrentRelationalAuthorityError("current_bundle_invalid")
    raw_bundle = str(pointer.get("bundle_path") or "")
    bundle = Path(raw_bundle)
    if not bundle.is_absolute():
        bundle = (admission_root / bundle).resolve()
    if not _inside(bundle, generations) or not bundle.is_dir():
        raise CurrentRelationalAuthorityError("current_bundle_path_escape")
    manifest_path = bundle / "bundle_manifest.json"
    raw_manifest_path = str(pointer.get("bundle_manifest_path") or "")
    declared_manifest_path = Path(raw_manifest_path)
    if not declared_manifest_path.is_absolute():
        declared_manifest_path = admission_root / declared_manifest_path
    if (
        not raw_manifest_path
        or declared_manifest_path.resolve() != manifest_path.resolve()
    ):
        raise CurrentRelationalAuthorityError(
            "current_bundle_manifest_path_mismatch"
        )
    if not manifest_path.is_file() or sha256_file(manifest_path) != pointer.get("bundle_manifest_hash"):
        raise CurrentRelationalAuthorityError("current_bundle_manifest_hash_mismatch")
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_BUNDLE:
        raise CurrentRelationalAuthorityError("current_bundle_invalid")
    identities = ("canon_generation_id", "relation_generation_id", "review_state_id", "readiness_id")
    for name in identities:
        if pointer.get(name) != manifest.get(name):
            raise CurrentRelationalAuthorityError(f"{name}_identity_mismatch")
    terminal = str(manifest.get("terminal_state") or "")
    expected_next_action = TERMINAL_NEXT_ACTION.get(terminal)
    if expected_next_action is None:
        raise CurrentRelationalAuthorityError("current_bundle_terminal_invalid")
    if pointer.get("terminal_state") != terminal:
        raise CurrentRelationalAuthorityError("terminal_state_identity_mismatch")
    if manifest.get("next_action") != expected_next_action:
        raise CurrentRelationalAuthorityError("current_bundle_next_action_invalid")
    if (
        "next_action" in pointer
        and pointer.get("next_action") != expected_next_action
    ):
        raise CurrentRelationalAuthorityError("next_action_identity_mismatch")
    artifacts: dict[str, Path] = {}
    reasons: list[str] = []
    manifest_artifacts = manifest.get("artifacts") or {}
    for name, item in manifest_artifacts.items():
        if not isinstance(item, dict) or str(item.get("status") or "").startswith("not_applicable"):
            continue
        raw = str(item.get("path") or "")
        path = (bundle / raw).resolve()
        if not raw or Path(raw).is_absolute() or not _inside(path, bundle):
            reasons.append("current_bundle_path_escape")
            continue
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            reasons.append("current_bundle_artifact_hash_mismatch")
            continue
        artifacts[name] = path
    if terminal == "READY_FOR_AUTHORIZATION":
        missing = REQUIRED_AUTHORIZATION_ARTIFACTS - set(artifacts)
        if missing:
            reasons.append("current_bundle_incomplete")
    elif terminal in {
        "READY_FOR_HUMAN_DELTA_REVIEW",
        "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION",
    }:
        missing = REQUIRED_HUMAN_DELTA_ARTIFACTS - set(artifacts)
        missing_placeholders = (
            HUMAN_PENDING_PLACEHOLDER_ARTIFACTS - set(manifest_artifacts)
        )
        missing.update(missing_placeholders)
        for name in HUMAN_PENDING_PLACEHOLDER_ARTIFACTS - missing_placeholders:
            item = manifest_artifacts.get(name)
            if (
                not isinstance(item, dict)
                or item.get("status")
                != "not_applicable_pending_human_review"
            ):
                reasons.append("current_bundle_artifact_state_invalid")
        if (
            terminal == "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION"
            and "review_receipts" not in artifacts
        ):
            missing.add("review_receipts")
        if missing:
            reasons.append("current_bundle_incomplete")
        schema_contracts = {
            "pending_queue": {
                "current-relational-human-delta/v1",
                "current-relational-human-delta/v2",
            },
            "batch_inventory": {
                "current-relational-human-delta-inventory/v2",
            },
            "current_human_delta": {
                "current-governed-review-human-delta/v1",
            },
        }
        for role, allowed_schemas in schema_contracts.items():
            path = artifacts.get(role)
            if path is None:
                continue
            payload = read_json(path)
            payload_schema = payload.get("schema_version")
            declared_schema = (manifest_artifacts.get(role) or {}).get(
                "schema_version"
            )
            if (
                payload_schema not in allowed_schemas
                or declared_schema != payload_schema
            ):
                reasons.append("current_bundle_artifact_schema_invalid")
    lineage_required = manifest.get("review_lineage_required") is True
    if lineage_required and not {
        "review_receipts", "review_receipt_lineage",
    }.issubset(artifacts):
        reasons.extend([
            "current_bundle_incomplete", "review_receipt_lineage_incomplete",
        ])
    receipts_path = artifacts.get("review_receipts")
    receipts: list[Any] = []
    if receipts_path is not None:
        try:
            receipts = [
                json.loads(line)
                for line in receipts_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            receipts = [None]
        allowed_receipts = {
            "current-single-batch-review-receipt/v1",
            "current-single-batch-review-receipt/v2",
        }
        if any(
            not isinstance(receipt, dict)
            or receipt.get("schema_version") not in allowed_receipts
            for receipt in receipts
        ):
            reasons.append("current_bundle_artifact_schema_invalid")
    lineage_path = artifacts.get("review_receipt_lineage")
    if lineage_path is not None:
        descriptor = read_json(lineage_path)
        descriptor_schema = descriptor.get("schema_version")
        declared_schema = (
            manifest_artifacts.get("review_receipt_lineage") or {}
        ).get("schema_version")
        if (
            descriptor_schema
            not in {
                "current-review-receipt-lineage/v1",
                "current-review-receipt-lineage/v2",
            }
            or declared_schema != descriptor_schema
            or descriptor.get("integrity_verified") is not True
            or receipts_path is None
            or descriptor.get("carried_review_receipts_hash")
            != sha256_file(receipts_path)
            or int(descriptor.get("receipt_count") or 0) != len(receipts)
            or not _receipt_lineage_coverage_valid(descriptor, receipts)
        ):
            reasons.append("review_receipt_lineage_invalid")
    if reasons:
        raise CurrentRelationalAuthorityError("current_bundle_invalid", *reasons)
    # Every JSON authority artifact that declares a generation identity must
    # agree with the pointer.  The authorization request only carries readiness.
    for name in ("decision_checkpoint", "gate_g", "apply_plan", "rollback_snapshot"):
        path = artifacts.get(name)
        if path is None:
            continue
        value = read_json(path)
        for identity in identities:
            if identity in value and value.get(identity) != pointer.get(identity):
                raise CurrentRelationalAuthorityError(f"{identity}_identity_mismatch")
    plan = read_json(artifacts["apply_plan"]) if "apply_plan" in artifacts else {}
    for binding in (plan.get("exact_bindings") or {}).values():
        if not isinstance(binding, dict):
            raise CurrentRelationalAuthorityError("apply_plan_external_binding")
        raw = str(binding.get("path") or "")
        candidate = (bundle / raw).resolve()
        if not raw or Path(raw).is_absolute() or not _inside(candidate, bundle):
            raise CurrentRelationalAuthorityError("apply_plan_external_binding")
        if ".staging-" in raw or not candidate.is_file() or sha256_file(candidate) != binding.get("sha256"):
            raise CurrentRelationalAuthorityError("apply_plan_staging_binding_missing")
    return {
        "pointer_path": pointer_path,
        "bundle_path": bundle,
        "bundle_manifest_path": manifest_path,
        "bundle_manifest_hash": pointer["bundle_manifest_hash"],
        "pointer": pointer,
        "manifest": manifest,
        "artifacts": artifacts,
        **{name: pointer.get(name) for name in identities},
        "terminal_state": manifest.get("terminal_state"),
    }
