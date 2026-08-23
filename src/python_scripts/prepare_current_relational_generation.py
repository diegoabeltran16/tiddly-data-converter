#!/usr/bin/env python3
"""Prepare an immutable, generation-bound relational admission bundle.

This coordinator intentionally delegates candidate semantics, reconciliation,
human-decision validation, admission gating, apply planning, safety checks and
snapshot construction to their existing authoritative modules.  It never
creates an authorization and never applies to the production canon.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import current_relation_human_review as human_review
import reconcile_current_relation_candidates as reconciliation
import relation_admission_gate as admission_gate
import current_relational_authority as current_authority
import current_relation_review_taxonomy as review_taxonomy


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_ROOT = REPO_ROOT / "data" / "out" / "local"
SCHEMA_BUNDLE = "current-relational-generation-bundle/v1"
SCHEMA_POINTER = "current-relational-generation-pointer/v1"
SCHEMA_CHECKPOINT = "current-relational-decision-checkpoint/v1"
SCHEMA_GATE_G = "current-relational-gate-g/v1"
SCHEMA_AUTHORIZATION_REQUEST = "current-relational-authorization-request/v1"
TERMINAL_HUMAN = "READY_FOR_HUMAN_DELTA_REVIEW"
TERMINAL_REVIEW_COMPLETE = "REVIEW_COMPLETE_PENDING_READINESS_RECOMPOSITION"
TERMINAL_AUTHORIZATION = "READY_FOR_AUTHORIZATION"
TERMINAL_BLOCKED = "BLOCKED"
TERMINAL_NEXT_ACTION = {
    TERMINAL_HUMAN: "REVIEW_CURRENT_RELATIONAL_DELTA",
    TERMINAL_REVIEW_COMPLETE: "PREPARE_CURRENT_RELATIONAL_READINESS",
    TERMINAL_AUTHORIZATION: "AUTHORIZE_CURRENT_RELATIONAL_APPLY",
}
TRACE_ENV = "TDC_CURRENT_RECOMPOSITION_TRACE"
EFFECTIVE_DECISIONS_FILE = "effective_human_review_decisions.jsonl"
GOVERNED_REBASELINE_REQUEST = "governed_review_rebaseline_request.json"
PREDECESSOR_UNRECOVERABLE_REASONS = frozenset({
    "predecessor_manifest_bound_to_mutable_inventory",
    "certified_predecessor_inventory_unrecoverable",
})
DECISION_RECOMPOSITION_REASONS = frozenset({
    "review_decision_recomposition_required",
    "review_semantic_coverage_regression",
})
REVIEW_RECEIPTS_FILE = "current_review_batch_receipts.jsonl"
REVIEW_LINEAGE_FILE = "review_receipt_lineage.json"


def _trace_event(**event: Any) -> None:
    """Append runtime evidence without making it authority or semantic input."""
    raw = os.environ.get(TRACE_ENV)
    if not raw:
        return
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": utc_now(), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class PreparationBlocked(RuntimeError):
    def __init__(self, reason_codes: Iterable[str], detail: str = "") -> None:
        self.reason_codes = sorted(set(reason_codes))
        self.detail = detail
        super().__init__(", ".join(self.reason_codes) + (f": {detail}" if detail else ""))


@dataclass(frozen=True)
class Paths:
    local_root: Path
    current_dir: Path
    audit_root: Path
    admission_current: Path
    generations: Path
    pointer: Path

    @classmethod
    def from_local_root(cls, local_root: Path) -> "Paths":
        root = local_root.resolve()
        audit_root = root / "audit" / "relation_admission"
        return cls(
            local_root=root,
            current_dir=root / "pipeline" / "relation_candidates" / "current",
            audit_root=audit_root,
            admission_current=audit_root / "current",
            generations=audit_root / "generations",
            pointer=audit_root / "current_generation.json",
        )


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def stable_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(stable_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _path_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _source_hashes(inputs: dict[str, Path]) -> dict[str, str | None]:
    return {name: sha256_file(path) for name, path in sorted(inputs.items())}


def _directory_fingerprint(root: Path) -> str | None:
    if not root.is_dir():
        return None
    rows = [
        {
            "path": str(path.relative_to(root)),
            "sha256": sha256_file(path),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]
    return semantic_hash(rows)


def _directory_identity(root: Path) -> tuple[int, int] | None:
    """Return the physical directory token used to prove swap ownership.

    Content equality is insufficient here: another publisher can install a
    byte-identical directory while this process is unwinding.  Device/inode
    identity lets rollback distinguish the directory installed by this swap
    from an indistinguishable concurrent successor.
    """
    try:
        stat = root.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino


def _review_lineage_semantic_hash(path: Path | None) -> str | None:
    """Hash lineage meaning without physical integrity bindings.

    Manifest, decision-file and receipt-file hashes remain mandatory integrity
    checks, but they are deliberately excluded here because their bytes can
    contain paths or publication timestamps.  Semantic identity is carried by
    the reviewed state transition and its candidate mapping.
    """
    if path is None or not path.is_file():
        return None
    descriptor = read_json(path)
    identity = {
        "schema_version": descriptor.get("schema_version"),
        "source_relation_generation_id": descriptor.get(
            "source_relation_generation_id"
        ),
        "source_review_state_id": descriptor.get("source_review_state_id"),
        "receipt_count": descriptor.get("receipt_count"),
        "receipt_candidate_ids": sorted(
            descriptor.get("receipt_candidate_ids") or []
        ),
        "preserved_equivalent": descriptor.get("preserved_equivalent"),
        "segments": [
            {
                "relation_generation_id": segment.get("relation_generation_id"),
                "root_review_state_id": segment.get("root_review_state_id"),
                "tip_review_state_id": segment.get("tip_review_state_id"),
            }
            for segment in descriptor.get("segments") or []
        ],
        "integrity_verified": descriptor.get("integrity_verified") is True,
    }
    return semantic_hash(identity)


def _semantic_human_decisions_hash(path: Path) -> str:
    """Hash operator decisions without timestamps or mutable path bindings."""
    return human_review.semantic_review_decisions_hash(read_jsonl(path))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"JSON object required at {path}:{line_number}")
        rows.append(value)
    return rows


def effective_decisions_path(current_dir: Path) -> Path:
    """Prefer rebaseline-derived authority without rewriting source decisions."""
    derived = current_dir / EFFECTIVE_DECISIONS_FILE
    return derived if derived.is_file() else current_dir / "human_review_decisions.jsonl"


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
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


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
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


def canon_snapshot(local_root: Path) -> dict[str, Any]:
    canon_glob = str(local_root / "tiddlers_*.jsonl")
    shards = sorted(local_root.glob("tiddlers_*.jsonl"))
    if not shards:
        raise PreparationBlocked(["canon_not_available"])
    try:
        for shard in shards:
            for line_number, raw in enumerate(
                shard.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not raw.strip():
                    continue
                value = json.loads(raw)
                if not isinstance(value, dict) or not str(value.get("id") or ""):
                    raise ValueError(f"invalid canon record at {shard}:{line_number}")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise PreparationBlocked(["canon_not_readable"], str(error)) from error
    return {
        "hash": admission_gate.aggregate_canon_hash(canon_glob),
        "records": admission_gate.count_canon_records(canon_glob),
        "shards": len(shards),
        "glob": canon_glob,
        "files": [
            {"name": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in shards
        ],
    }


def _required_inputs(paths: Paths) -> dict[str, Path]:
    inputs = {
        "candidate_batch": paths.current_dir / "relation_candidates.jsonl",
        "ready_queue": paths.current_dir / "ready_for_human_review.jsonl",
        "candidate_manifest": paths.current_dir / "current_candidate_manifest.json",
        "validation_report": paths.current_dir / "validation_report.json",
        "reconciliation_manifest": paths.current_dir / "reconciliation_manifest.json",
        "reviewable_manifest": paths.current_dir / "reviewable_candidate_manifest.json",
        "human_decisions": effective_decisions_path(paths.current_dir),
    }
    optional = {
        "review_receipts": paths.current_dir / REVIEW_RECEIPTS_FILE,
        "review_lineage": paths.current_dir / REVIEW_LINEAGE_FILE,
    }
    inputs.update({name: path for name, path in optional.items() if path.is_file()})
    return inputs


def producer_bindings() -> dict[str, Path]:
    return {
        "candidate_generator": REPO_ROOT / "src" / "python_scripts" / "generate_technical_relation_candidates.py",
        "candidate_validator": REPO_ROOT / "src" / "python_scripts" / "validate_relation_candidates.py",
        "preparation_orchestrator": Path(__file__).resolve(),
        "admission_gate_contract": Path(admission_gate.__file__).resolve(),
        "human_review_contract": Path(human_review.__file__).resolve(),
        "cross_generation_reconciler": Path(reconciliation.__file__).resolve(),
    }


def validate_source_generation(paths: Paths, canon: dict[str, Any]) -> dict[str, Path]:
    inputs = _required_inputs(paths)
    missing = [name for name, path in inputs.items() if not path.is_file()]
    if missing:
        raise PreparationBlocked(
            ["candidate_generation_failed"], "missing: " + ", ".join(sorted(missing)),
        )
    try:
        candidate = read_json(inputs["candidate_manifest"])
        validation = read_json(inputs["validation_report"])
        reconciled = read_json(inputs["reconciliation_manifest"])
        reviewable = read_json(inputs["reviewable_manifest"])
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise PreparationBlocked(["candidate_generation_failed"], str(error)) from error
    reasons: list[str] = []
    if candidate.get("current") is not True:
        reasons.append("candidate_generation_failed")
    binding = candidate.get("canon_binding") or {}
    producer = candidate.get("producer") or {}
    if binding.get("canon_hash") != canon["hash"]:
        reasons.append("candidate_generation_stale")
    if producer.get("hash") != sha256_file(producer_bindings()["candidate_generator"]):
        reasons.append("candidate_generation_stale")
    if producer.get("contract_hash") != sha256_file(REPO_ROOT / "src" / "python_scripts" / "relation_candidate_contract.py"):
        reasons.append("candidate_generation_stale")
    if (candidate.get("candidate_batch") or {}).get("hash") != sha256_file(inputs["candidate_batch"]):
        reasons.append("candidate_generation_stale")
    validation_summary = validation.get("summary") or {}
    if int(validation_summary.get("total") or 0) != int((candidate.get("candidate_batch") or {}).get("record_count") or 0):
        reasons.append("candidate_validation_incomplete")
    if reconciled.get("current") is not True or reconciled.get("canon_hash") != canon["hash"]:
        reasons.append("cross_generation_reconciliation_incomplete")
    if reconciled.get("candidate_manifest_hash") != sha256_file(inputs["candidate_manifest"]):
        reasons.append("cross_generation_reconciliation_incomplete")
    if reviewable.get("candidate_manifest_hash") != sha256_file(inputs["candidate_manifest"]):
        reasons.append("candidate_validation_incomplete")
    if reviewable.get("reconciliation_manifest_hash") != sha256_file(inputs["reconciliation_manifest"]):
        reasons.append("cross_generation_reconciliation_incomplete")
    if ("review_receipts" in inputs) != ("review_lineage" in inputs):
        reasons.append("review_receipt_lineage_incomplete")
    elif "review_lineage" in inputs:
        try:
            lineage = read_json(inputs["review_lineage"])
            receipts = read_jsonl(inputs["review_receipts"])
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            reasons.append("review_receipt_lineage_invalid")
        else:
            invalid_lineage = (
                lineage.get("schema_version")
                not in {
                    "current-review-receipt-lineage/v1",
                    "current-review-receipt-lineage/v2",
                }
                or lineage.get("integrity_verified") is not True
                or lineage.get("carried_review_receipts_hash")
                != sha256_file(inputs["review_receipts"])
                or int(lineage.get("receipt_count") or 0) != len(receipts)
                or any(
                    receipt.get("schema_version")
                    not in {
                        "current-single-batch-review-receipt/v1",
                        "current-single-batch-review-receipt/v2",
                    }
                    for receipt in receipts
                )
            )
            try:
                human_review._review_receipt_segments(lineage, receipts)
            except ValueError:
                invalid_lineage = True
            if invalid_lineage:
                reasons.append("review_receipt_lineage_invalid")
    if reasons:
        raise PreparationBlocked(reasons)
    return inputs


def _assert_publication_sources_unchanged(
    paths: Paths,
    analysis: dict[str, Any],
    *,
    canon_hash: str,
    input_hashes: dict[str, str | None],
    pointer_bytes: bytes | None,
) -> None:
    """Revalidate every mutable source immediately before a publish boundary."""
    reasons: list[str] = []
    if canon_snapshot(paths.local_root)["hash"] != canon_hash:
        reasons.append("generation_drift_during_rebuild")
    observed = _source_hashes(analysis["inputs"])
    changed = sorted(
        name for name, expected in input_hashes.items()
        if observed.get(name) != expected
    )
    if changed:
        technical = {
            "candidate_batch", "ready_queue", "candidate_manifest",
            "validation_report", "reconciliation_manifest",
            "reviewable_manifest",
        }
        if technical.intersection(changed):
            reasons.append("current_relational_source_changed")
        if "human_decisions" in changed:
            reasons.append("decisions_drift_during_rebuild")
        if {"review_receipts", "review_lineage"}.intersection(changed):
            reasons.append("review_receipt_lineage_changed")
    if _path_bytes(paths.pointer) != pointer_bytes:
        reasons.append("current_pointer_changed")
    if reasons:
        raise PreparationBlocked(
            reasons,
            "changed sources: " + ", ".join(changed) if changed else "",
        )


def _restore_pointer_if_owned(
    path: Path,
    *,
    before: bytes | None,
    written: bytes | None,
) -> bool:
    """Restore our pointer update only; never overwrite a concurrent writer."""
    if written is None:
        return True
    try:
        current_authority.compare_and_swap_current_pointer(
            path, expected=written, replacement=before,
        )
        return True
    except current_authority.CurrentRelationalAuthorityError:
        return False


def _assert_published_candidate_is_current(
    status: dict[str, Any],
    *,
    destination: Path,
    ids: dict[str, Any],
    terminal_state: str,
    failure_reason: str,
) -> None:
    """Require postpublication resolution to name the candidate just published.

    A merely valid current authority is not enough: a concurrent successor may
    have advanced the pointer after this writer's CAS.  Such an advance is
    preserved and reported instead of being misreported as this publication's
    success.
    """
    if status.get("valid") is not True:
        raise PreparationBlocked(
            [failure_reason], str(status.get("reason_codes")),
        )
    mismatches: list[str] = []
    observed_path = status.get("bundle_path")
    if (
        not observed_path
        or Path(str(observed_path)).resolve() != destination.resolve()
    ):
        mismatches.append("bundle_path")
    if status.get("terminal_state") != terminal_state:
        mismatches.append("terminal_state")
    observed_ids = status.get("ids") or {}
    for name, expected in ids.items():
        if expected is not None and observed_ids.get(name) != expected:
            mismatches.append(name)
    if mismatches:
        raise PreparationBlocked(
            ["current_pointer_descendant_advanced"],
            "postpublication current mismatch: " + ", ".join(sorted(mismatches)),
        )


REBUILDABLE_SOURCE_REASONS = {
    "candidate_generation_stale",
    "candidate_validation_incomplete",
    "cross_generation_reconciliation_incomplete",
}


def _run_failure_hook(
    failure_hook: Any, name: str, reason_code: str,
) -> None:
    if failure_hook is None:
        return
    try:
        failure_hook(name)
    except PreparationBlocked:
        raise
    except RuntimeError as error:
        raise PreparationBlocked([reason_code], str(error)) from error


def _call_rebuild_step(
    command: list[str],
    *,
    reason_code: str,
    failpoint: str,
    failure_hook: Any = None,
) -> None:
    started = datetime.now(timezone.utc)
    _trace_event(phase=failpoint, status="started", command=command, cwd=str(REPO_ROOT))
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        _trace_event(
            phase=failpoint, status="completed",
            duration_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            exit_code=completed.returncode,
            stdout_tail=completed.stdout[-2000:], stderr_tail=completed.stderr[-2000:],
        )
        if failure_hook is not None:
            failure_hook(failpoint)
    except PreparationBlocked:
        raise
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        detail = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            detail = (error.stderr or error.stdout or detail).strip()
        _trace_event(phase=failpoint, status="failed", reason_code=reason_code,
                     error_type=type(error).__name__, error_message=detail)
        raise PreparationBlocked([reason_code], detail) from error
    except subprocess.TimeoutExpired as error:
        _trace_event(phase=failpoint, status="failed", reason_code=f"{reason_code}_timeout",
                     error_type=type(error).__name__, error_message=str(error))
        raise PreparationBlocked([f"{reason_code}_timeout"], str(error)) from error


def _rebase_staged_candidate_generation(current_dir: Path, final_dir: Path) -> None:
    """Replace staging-only paths and refresh the manifest hash chain."""
    report_path = current_dir / "relation_candidates_report.json"
    if report_path.is_file():
        report = read_json(report_path)
        report["output_dir"] = str(final_dir)
        write_json(report_path, report)
    candidate_path = current_dir / "current_candidate_manifest.json"
    candidate = read_json(candidate_path)
    (candidate.setdefault("candidate_batch", {}))["path"] = str(
        final_dir / "relation_candidates.jsonl"
    )
    write_json(candidate_path, candidate)
    reconciliation_path = current_dir / "reconciliation_manifest.json"
    reconciled = read_json(reconciliation_path)
    reconciled["candidate_manifest_hash"] = sha256_file(candidate_path)
    reconciled["matrix_path"] = str(final_dir / "candidate_reconciliation_matrix.jsonl")
    write_json(reconciliation_path, reconciled)
    reviewable_path = current_dir / "reviewable_candidate_manifest.json"
    reviewable = read_json(reviewable_path)
    reviewable["candidate_manifest_hash"] = sha256_file(candidate_path)
    reviewable["reconciliation_manifest_hash"] = sha256_file(reconciliation_path)
    write_json(reviewable_path, reviewable)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _bundle_artifact_path(
    bundle: Path, manifest: dict[str, Any], role: str,
) -> Path:
    item = (manifest.get("artifacts") or {}).get(role) or {}
    raw = str(item.get("path") or "")
    path = (bundle / raw).resolve()
    if (
        not raw
        or Path(raw).is_absolute()
        or not _inside(path, bundle)
        or not path.is_file()
        or sha256_file(path) != item.get("sha256")
    ):
        raise PreparationBlocked(
            ["review_predecessor_artifact_invalid"], f"{role}: {bundle}",
        )
    return path


def _load_review_bundle(
    paths: Paths, bundle: Path, *, expected_manifest_hash: str | None = None,
) -> dict[str, Any]:
    """Load immutable review evidence without making it operational current."""
    bundle = bundle.resolve()
    if not _inside(bundle, paths.generations) or not bundle.is_dir():
        raise PreparationBlocked(["review_predecessor_path_invalid"], str(bundle))
    manifest_path = bundle / "bundle_manifest.json"
    manifest_hash = sha256_file(manifest_path)
    if not manifest_hash or (
        expected_manifest_hash is not None
        and manifest_hash != expected_manifest_hash
    ):
        raise PreparationBlocked(
            ["review_predecessor_manifest_hash_mismatch"], str(bundle),
        )
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_BUNDLE:
        raise PreparationBlocked(["review_predecessor_manifest_invalid"], str(bundle))
    _validate_staged_bundle(bundle, manifest)
    candidates_path = _bundle_artifact_path(bundle, manifest, "relation_candidates")
    ready_queue_path = _bundle_artifact_path(bundle, manifest, "ready_queue")
    decisions_path = _bundle_artifact_path(bundle, manifest, "effective_decisions")
    checkpoint_path = _bundle_artifact_path(bundle, manifest, "decision_checkpoint")
    candidates = read_jsonl(candidates_path)
    candidate_by_id = {
        str(row.get("candidate_id") or ""): row for row in candidates
    }
    queue_by_id = {
        str(row.get("candidate_id") or ""): row
        for row in read_jsonl(ready_queue_path)
    }
    decisions = read_jsonl(decisions_path)
    decision_by_id = {
        str(row.get("candidate_id") or ""): row for row in decisions
    }
    if (
        "" in candidate_by_id
        or len(candidate_by_id) != len(candidates)
        or "" in decision_by_id
        or len(decision_by_id) != len(decisions)
        or not set(decision_by_id).issubset(candidate_by_id)
    ):
        raise PreparationBlocked(["review_predecessor_decision_binding_invalid"])
    for candidate_id, decision in decision_by_id.items():
        errors = human_review.validate_human_review_decision_record(decision)
        if errors:
            raise PreparationBlocked(
                ["review_predecessor_decision_binding_invalid"],
                f"{candidate_id}: {'; '.join(errors)}",
            )
    receipts_item = (manifest.get("artifacts") or {}).get("review_receipts") or {}
    receipts_path: Path | None = None
    receipts: list[dict[str, Any]] = []
    if receipts_item:
        receipts_path = _bundle_artifact_path(bundle, manifest, "review_receipts")
        receipts = read_jsonl(receipts_path)

    checkpoint = read_json(checkpoint_path)
    declared_rows = checkpoint.get("individual_decision_hashes")
    if not isinstance(declared_rows, list):
        declared_rows = []
    declared_hashes = {
        str(item.get("candidate_id") or ""): str(item.get("decision_sha256") or "")
        for item in declared_rows if isinstance(item, dict)
    }
    classifications = Counter(
        str(item.get("classification") or "")
        for item in declared_rows if isinstance(item, dict)
    )
    receipt_extension_ids: set[str] = set()
    receipt_extension_valid = bool(receipts)
    for receipt in receipts:
        candidate_ids = [str(value) for value in receipt.get("candidate_ids") or []]
        candidate_hashes = [
            str(value) for value in receipt.get("candidate_hashes") or []
        ]
        if (
            not candidate_ids
            or len(candidate_ids) != len(set(candidate_ids))
            or len(candidate_ids) != len(candidate_hashes)
            or receipt_extension_ids.intersection(candidate_ids)
            or any(candidate_id not in decision_by_id for candidate_id in candidate_ids)
            or any(candidate_id not in queue_by_id for candidate_id in candidate_ids)
            or candidate_hashes != [
                human_review._review_candidate_hash(queue_by_id[candidate_id])
                for candidate_id in candidate_ids
            ]
            or receipt.get("decisions_hash") != human_review.semantic_hash([
                human_review.decision_hash(decision_by_id[candidate_id])
                for candidate_id in sorted(candidate_ids)
            ])
            or receipt.get("source_relation_generation_id")
            != manifest.get("relation_generation_id")
        ):
            receipt_extension_valid = False
            break
        receipt_extension_ids.update(candidate_ids)
    declared_total = int(checkpoint.get("total_decisions") or 0)
    total_conserved = declared_total == len(decisions) or (
        receipt_extension_valid
        and all(
            receipt.get("schema_version")
            == "current-single-batch-review-receipt/v1"
            for receipt in receipts
        )
        and declared_total + len(receipt_extension_ids) == len(decisions)
    )
    checkpoint_invalid = (
        checkpoint.get("relation_generation_id")
        != manifest.get("relation_generation_id")
        or checkpoint.get("review_state_id") != manifest.get("review_state_id")
        or checkpoint.get("decisions_file_hash") != sha256_file(decisions_path)
        or not total_conserved
        or len(declared_rows) != len(declared_hashes)
        or "" in declared_hashes
        or set(declared_hashes) != set(decision_by_id)
        or any(
            declared_hashes[candidate_id]
            != human_review.decision_hash(decision).removeprefix("sha256:")
            for candidate_id, decision in decision_by_id.items()
        )
        or any(
            int(checkpoint.get(field) or 0) != classifications[field]
            for field in (
                "current_direct", "preserved_equivalent", "preserved_historical",
            )
        )
        or sum(
            classifications[field]
            for field in (
                "current_direct", "preserved_equivalent", "preserved_historical",
            )
        ) != len(decisions)
    )
    if checkpoint_invalid:
        raise PreparationBlocked(["review_predecessor_decision_hash_mismatch"])
    lineage_descriptor: dict[str, Any] | None = None
    if (manifest.get("artifacts") or {}).get("review_receipt_lineage"):
        lineage_descriptor = read_json(_bundle_artifact_path(
            bundle, manifest, "review_receipt_lineage",
        ))
    return {
        "bundle": bundle,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_hash": manifest_hash,
        "candidates_path": candidates_path,
        "candidate_by_id": candidate_by_id,
        "decisions_path": decisions_path,
        "decision_by_id": decision_by_id,
        "checkpoint_path": checkpoint_path,
        "checkpoint": checkpoint,
        "receipts_path": receipts_path,
        "receipts": receipts,
        "lineage_descriptor": lineage_descriptor,
    }


def _review_batch_surface(record: dict[str, Any]) -> dict[str, Any]:
    manifest = record["manifest"]
    bundle = record["bundle"]
    delta = read_json(_bundle_artifact_path(bundle, manifest, "pending_queue"))
    queue = read_jsonl(_bundle_artifact_path(bundle, manifest, "ready_queue"))
    queue_by_id = {str(row.get("candidate_id") or ""): row for row in queue}
    taxonomy = {
        str(row.get("candidate_id") or ""): row
        for row in delta.get("review_candidates") or []
    }
    pending = [str(value) for value in delta.get("pending_candidate_ids") or []]
    if len(set(pending)) != len(pending) or not set(pending).issubset(queue_by_id):
        raise PreparationBlocked(["review_receipt_lineage_invalid"])
    candidates = [{
        "candidate_id": candidate_id,
        "candidate_hash": human_review._review_candidate_hash(queue_by_id[candidate_id]),
        "reconciliation_class": (taxonomy.get(candidate_id) or {}).get(
            "reconciliation_class"
        ),
        "review_reason": (taxonomy.get(candidate_id) or {}).get("review_reason"),
    } for candidate_id in sorted(pending)]
    return {
        "allowed": True,
        "artifacts": {"effective_decisions": record["decisions_path"]},
        "inventory": {
            "relation_generation_id": manifest.get("relation_generation_id"),
            "review_state_id": manifest.get("review_state_id"),
            "bundle_manifest_hash": record["manifest_hash"],
            "total_pending": len(pending),
            "candidates": candidates,
        },
    }


def _lineage_consumed_candidate_ids(
    receipts: list[dict[str, Any]],
) -> list[str]:
    """Conserve review consumption per relation generation.

    A candidate identity may legitimately be reviewed again after a semantic
    modification in a later relation generation.  Re-consumption inside the
    same generation remains invalid.
    """
    by_relation: dict[str, set[str]] = {}
    all_candidate_ids: set[str] = set()
    for receipt in receipts:
        relation_id = str(receipt.get("source_relation_generation_id") or "")
        candidate_ids = [
            str(value) for value in receipt.get("candidate_ids") or []
        ]
        consumed = by_relation.setdefault(relation_id, set())
        if (
            not relation_id
            or "" in candidate_ids
            or len(candidate_ids) != len(set(candidate_ids))
            or consumed.intersection(candidate_ids)
        ):
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        consumed.update(candidate_ids)
        all_candidate_ids.update(candidate_ids)
    return sorted(all_candidate_ids)


def _validate_review_receipt_lineage(
    paths: Paths, record: dict[str, Any],
) -> dict[str, Any]:
    """Validate the complete review DAG by IDs and hashes, never directory order."""
    receipts = list(record["receipts"])
    if not receipts:
        raise PreparationBlocked(["review_receipt_lineage_missing"])
    receipt_ids = [str(item.get("receipt_id") or "") for item in receipts]
    descriptor = record.get("lineage_descriptor") or {}
    if len(set(receipt_ids)) != len(receipt_ids) or "" in receipt_ids:
        raise PreparationBlocked(["review_receipt_lineage_invalid"])
    try:
        if descriptor:
            segments = human_review._review_receipt_segments(
                descriptor, receipts,
            )
        else:
            relation_ids = {
                str(item.get("source_relation_generation_id") or "")
                for item in receipts
            }
            if "" in relation_ids or len(relation_ids) != 1:
                raise ValueError("receipt relation segment missing")
            segments = [{
                "relation_generation_id": next(iter(relation_ids)),
                "receipt_ids": receipt_ids,
            }]
    except ValueError as error:
        raise PreparationBlocked(
            ["review_receipt_lineage_invalid"], str(error),
        ) from error
    receipt_by_id = {
        str(item.get("receipt_id") or ""): item for item in receipts
    }
    ordered: list[dict[str, Any]] = []
    segment_results: list[dict[str, Any]] = []
    for segment in segments:
        segment_receipts = [
            receipt_by_id[str(receipt_id)]
            for receipt_id in segment.get("receipt_ids") or []
        ]
        sources = [
            str(item.get("source_review_state_id") or "")
            for item in segment_receipts
        ]
        results = [
            str(item.get("result_review_state_id") or "")
            for item in segment_receipts
        ]
        if (
            "" in sources + results
            or len(set(sources)) != len(sources)
        ):
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        roots = set(sources) - set(results)
        tips = set(results) - set(sources)
        if len(roots) != 1 or len(tips) != 1:
            raise PreparationBlocked(["review_receipt_lineage_ambiguous"])
        by_source = {
            str(item["source_review_state_id"]): item
            for item in segment_receipts
        }
        cursor = next(iter(roots))
        segment_ordered: list[dict[str, Any]] = []
        while cursor in by_source:
            receipt = by_source[cursor]
            segment_ordered.append(receipt)
            cursor = str(receipt["result_review_state_id"])
            if len(segment_ordered) > len(segment_receipts):
                raise PreparationBlocked(["review_receipt_lineage_ambiguous"])
        if (
            len(segment_ordered) != len(segment_receipts)
            or cursor != next(iter(tips))
            or (
                segment.get("root_review_state_id")
                and segment.get("root_review_state_id") != next(iter(roots))
            )
            or (
                segment.get("tip_review_state_id")
                and segment.get("tip_review_state_id") != cursor
            )
        ):
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        segment_results.append({
            "relation_generation_id": segment.get("relation_generation_id"),
            "root_review_state_id": next(iter(roots)),
            "tip_review_state_id": cursor,
            "receipt_ids": [str(item["receipt_id"]) for item in segment_ordered],
        })
        ordered.extend(segment_ordered)
    consumed_candidate_ids = _lineage_consumed_candidate_ids(ordered)
    cache: dict[tuple[str, str], dict[str, Any]] = {
        (
            str(record["manifest"].get("relation_generation_id") or ""),
            str(record["manifest"].get("review_state_id") or ""),
        ): record,
    }
    for receipt in ordered:
        relation_id = str(receipt.get("source_relation_generation_id") or "")
        if not relation_id:
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        source_id = str(receipt["source_review_state_id"])
        result_id = str(receipt["result_review_state_id"])
        for review_id in (source_id, result_id):
            cache_key = (relation_id, review_id)
            if cache_key not in cache:
                cache[cache_key] = _load_review_bundle(
                    paths,
                    paths.generations / relation_id / review_id / "human_delta",
                )
        source = cache[(relation_id, source_id)]
        result = cache[(relation_id, result_id)]
        if source["manifest_hash"] != receipt.get("source_bundle_manifest_hash"):
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        receipt_schema = receipt.get("schema_version")
        if receipt_schema not in {
            "current-single-batch-review-receipt/v1",
            "current-single-batch-review-receipt/v2",
        }:
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        identity_schema = "v1" if receipt_schema.endswith("/v1") else "v2"
        batches = human_review.build_current_human_delta_batches(
            _review_batch_surface(source), identity_schema=identity_schema,
        )
        matching = [
            batch for batch in batches
            if batch["batch_id"] == receipt.get("batch_id")
        ]
        if len(matching) != 1:
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        batch = matching[0]
        if (
            identity_schema == "v2"
            and receipt.get("source_review_state_semantic_hash")
            != batch.get("source_review_state_semantic_hash")
        ):
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        for key in ("batch_hash", "candidate_ids", "candidate_hashes"):
            if batch[key] != receipt.get(key):
                raise PreparationBlocked(["review_receipt_lineage_invalid"])
        candidate_ids = [str(value) for value in receipt.get("candidate_ids") or []]
        source_decisions = source["decision_by_id"]
        result_decisions = result["decision_by_id"]
        if (
            set(candidate_ids).intersection(source_decisions)
            or set(result_decisions) != set(source_decisions).union(candidate_ids)
            or any(
                human_review.decision_hash(source_decisions[item])
                != human_review.decision_hash(result_decisions[item])
                for item in source_decisions
            )
        ):
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        proposals = []
        for candidate_id, candidate_hash in zip(
            batch["candidate_ids"], batch["candidate_hashes"], strict=True,
        ):
            decision = result_decisions[candidate_id]
            if (
                decision.get("candidate_hash") != candidate_hash
                or decision.get("batch_hash") != batch["batch_hash"]
                or decision.get("relation_generation_id") != relation_id
                or decision.get("source_review_state_id") != source_id
                or decision.get("result_review_state_id") != result_id
            ):
                raise PreparationBlocked(["review_receipt_lineage_invalid"])
            proposals.append({
                "candidate_id": candidate_id,
                "candidate_hash": candidate_hash,
                "action": decision.get("human_review_decision"),
                "reason_code": decision.get("human_review_reason_code"),
                "note": decision.get("human_review_note") or "",
                "actor": decision.get("human_review_actor"),
                "human_confirmation": decision.get("human_confirmation"),
            })
        expected_result_id, expected_receipt_id = (
            human_review._current_review_semantic_identity(
                {}, batch, proposals, identity_schema=identity_schema,
            )
        )
        if (
            result_id != expected_result_id
            or receipt.get("receipt_id") != expected_receipt_id
            or receipt.get("human_confirmation")
            != human_review.current_batch_confirmation(batch["batch_id"])
            or receipt.get("decisions_hash")
            != human_review.semantic_hash([
                human_review.decision_hash(result_decisions[item])
                for item in sorted(candidate_ids)
            ])
        ):
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
        source_receipt_ids = {
            str(item.get("receipt_id") or "") for item in source["receipts"]
        }
        result_receipts = {
            str(item.get("receipt_id") or ""): item for item in result["receipts"]
        }
        if (
            set(result_receipts) != source_receipt_ids.union({expected_receipt_id})
            or result_receipts.get(expected_receipt_id) != receipt
        ):
            raise PreparationBlocked(["review_receipt_lineage_invalid"])
    result = {
        "root_review_state_id": segment_results[0]["root_review_state_id"],
        "tip_review_state_id": segment_results[-1]["tip_review_state_id"],
        "receipt_count": len(ordered),
        "receipt_ids": [str(item["receipt_id"]) for item in ordered],
        "consumed_candidate_ids": consumed_candidate_ids,
        "integrity_verified": True,
    }
    if len(segment_results) > 1:
        result["segments"] = segment_results
    return result


def _decision_authority_signature(record: dict[str, Any]) -> dict[str, Any]:
    return {
        field: record.get(field)
        for field in human_review.MIGRATION_PRESERVED_FIELDS
        if field != "evidence"
    }


def _resolve_monotonic_review_predecessor(paths: Paths) -> dict[str, Any]:
    """Resolve one predecessor from the pointer and its declared genealogy."""
    pointer = read_json(paths.pointer)
    bundle = Path(str(pointer.get("bundle_path") or ""))
    if not bundle.is_absolute():
        bundle = paths.audit_root / bundle
    current = _load_review_bundle(
        paths, bundle, expected_manifest_hash=str(
            pointer.get("bundle_manifest_hash") or ""
        ),
    )
    for identity in ("relation_generation_id", "review_state_id", "readiness_id"):
        if pointer.get(identity) != current["manifest"].get(identity):
            raise PreparationBlocked(["review_predecessor_identity_mismatch"])
    selected = current
    recovered = False
    raw_previous = str(
        current["checkpoint"].get("previous_checkpoint_or_receipt") or ""
    )
    if raw_previous:
        previous_path = Path(raw_previous)
        if not previous_path.is_absolute():
            previous_path = REPO_ROOT / previous_path
        if previous_path.is_file():
            previous_path = previous_path.parent
        declared_previous_hash = str(
            current["checkpoint"].get("previous_bundle_manifest_hash") or ""
        )
        previous = _load_review_bundle(
            paths,
            previous_path,
            expected_manifest_hash=declared_previous_hash or None,
        )
        same_generation = (
            previous["manifest"].get("relation_generation_id")
            == current["manifest"].get("relation_generation_id")
        )
        same_inventory = sha256_file(previous["candidates_path"]) == sha256_file(
            current["candidates_path"]
        )
        if same_generation and same_inventory:
            current_ids = set(current["decision_by_id"])
            previous_ids = set(previous["decision_by_id"])
            current_receipt_ids = {
                str(item.get("receipt_id") or "") for item in current["receipts"]
            }
            previous_receipt_ids = {
                str(item.get("receipt_id") or "") for item in previous["receipts"]
            }
            if "" in current_receipt_ids.union(previous_receipt_ids):
                raise PreparationBlocked(["review_receipt_lineage_invalid"])
            current_lineage = (
                _validate_review_receipt_lineage(paths, current)
                if current_receipt_ids else None
            )
            previous_lineage = (
                _validate_review_receipt_lineage(paths, previous)
                if previous_receipt_ids else None
            )
            shared = current_ids.intersection(previous_ids)
            if any(
                _decision_authority_signature(current["decision_by_id"][item])
                != _decision_authority_signature(previous["decision_by_id"][item])
                for item in shared
            ):
                raise PreparationBlocked(["review_decision_conflict"])
            if not (
                current_ids.issubset(previous_ids)
                or previous_ids.issubset(current_ids)
            ):
                raise PreparationBlocked(["review_predecessor_ambiguous"])
            if not (
                current_receipt_ids.issubset(previous_receipt_ids)
                or previous_receipt_ids.issubset(current_receipt_ids)
            ):
                raise PreparationBlocked(["review_predecessor_ambiguous"])
            if current_ids < previous_ids:
                if previous_lineage is None:
                    raise PreparationBlocked(["review_receipt_lineage_missing"])
                if not current_receipt_ids.issubset(previous_receipt_ids):
                    raise PreparationBlocked(["review_predecessor_ambiguous"])
                if not (previous_ids - current_ids).issubset(
                    set(previous_lineage["consumed_candidate_ids"])
                ):
                    raise PreparationBlocked(["review_semantic_coverage_regression"])
                previous["receipt_lineage"] = previous_lineage
                selected = previous
                recovered = True
            elif previous_ids < current_ids:
                if current_lineage is None:
                    raise PreparationBlocked(["review_receipt_lineage_missing"])
                if not previous_receipt_ids.issubset(current_receipt_ids):
                    raise PreparationBlocked(["review_predecessor_ambiguous"])
                if not (current_ids - previous_ids).issubset(
                    set(current_lineage["consumed_candidate_ids"])
                ):
                    raise PreparationBlocked(["review_receipt_lineage_invalid"])
                current["receipt_lineage"] = current_lineage
            elif current_receipt_ids < previous_receipt_ids:
                # Coverage alone is insufficient: dropping a certified ledger
                # is a review-state regression even when all decision rows were
                # copied.  Recover the declared receipt-complete ancestor.
                if previous_lineage is None:
                    raise PreparationBlocked(["review_receipt_lineage_missing"])
                previous["receipt_lineage"] = previous_lineage
                selected = previous
                recovered = True
            elif previous_receipt_ids < current_receipt_ids:
                if current_lineage is None:
                    raise PreparationBlocked(["review_receipt_lineage_missing"])
                current["receipt_lineage"] = current_lineage
            elif current["receipts"] != previous["receipts"]:
                raise PreparationBlocked(["review_receipt_lineage_invalid"])
    if selected["receipts"] and "receipt_lineage" not in selected:
        selected["receipt_lineage"] = _validate_review_receipt_lineage(
            paths, selected,
        )
    selected["recovered_from_regression"] = recovered
    selected["pointer_bundle"] = current["bundle"]
    selected["pointer_manifest_hash"] = current["manifest_hash"]
    return selected


def _previous_authority(
    paths: Paths,
) -> tuple[Path | None, Path | None, dict[str, Any] | None, dict[str, Any] | None]:
    if paths.pointer.is_file():
        try:
            predecessor = _resolve_monotonic_review_predecessor(paths)
            manifest = predecessor["manifest"]
            external = (manifest.get("source_bindings") or {}).get(
                "human_decisions"
            ) or {}
            external_path = Path(str(external.get("path") or ""))
            if (
                manifest.get("terminal_state") == TERMINAL_AUTHORIZATION
                and external_path.is_file()
                and sha256_file(external_path) != external.get("sha256")
            ):
                raise PreparationBlocked(
                    ["decision_preservation_failed"],
                    "decision authority changed after READY_FOR_AUTHORIZATION",
                )
            return (
                predecessor["candidates_path"], predecessor["decisions_path"],
                manifest, predecessor,
            )
        except PreparationBlocked:
            # A present operational pointer is never silently replaced by a
            # legacy/S0183 source when its integrity or genealogy is invalid.
            raise
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise PreparationBlocked(
                ["review_predecessor_not_resolved"], str(error),
            ) from error
    decisions = paths.current_dir / "human_review_decisions.jsonl"
    if not decisions.is_file() or not decisions.read_text(encoding="utf-8").strip():
        return None, None, None, None
    candidates, certified_decisions, manifest = _resolve_certified_predecessor(paths)
    return candidates, certified_decisions, manifest, None


def _resolve_certified_predecessor(
    paths: Paths,
) -> tuple[Path | None, Path | None, dict[str, Any] | None]:
    """Gate P: resolve a predecessor only through its certified artifacts."""
    root = paths.local_root / "audit" / "s0183" / "current"
    manifest_path = root / "cross_batch_reconciliation_manifest.json"
    receipt_path = root / "human_decision_preservation_manifest.json"
    if not manifest_path.is_file() or not receipt_path.is_file():
        raise PreparationBlocked(["certified_predecessor_not_resolved"])
    manifest, receipt = read_json(manifest_path), read_json(receipt_path)
    if receipt.get("cross_batch_manifest_hash") != sha256_file(manifest_path):
        raise PreparationBlocked(["predecessor_artifact_hash_mismatch"])
    def artifact(value: Any, expected: Any, missing: str) -> Path:
        path = Path(str(value or ""))
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.is_file():
            raise PreparationBlocked([missing])
        if expected and sha256_file(path) != expected:
            mutable_alias = paths.current_dir in path.resolve().parents or path.resolve() == (
                paths.current_dir / "relation_candidates.jsonl"
            ).resolve()
            raise PreparationBlocked([
                "predecessor_manifest_bound_to_mutable_inventory"
                if mutable_alias else "predecessor_artifact_integrity_violation",
                "certified_predecessor_inventory_unrecoverable",
            ])
        return path
    candidates = artifact(
        manifest.get("current_candidates_path"), manifest.get("current_candidates_hash"),
        "predecessor_candidate_inventory_missing",
    )
    decisions = artifact(
        receipt.get("current_decisions_path"), None,
        "source_decision_candidate_binding_missing",
    )
    certified_ids = {str(row.get("candidate_id") or "") for row in read_jsonl(candidates)}
    for decision in read_jsonl(decisions):
        candidate_id = str(decision.get("candidate_id") or "")
        # The receipt certifies an initial subset; later current_direct rows
        # are classified by Gate C, not rejected at resolution time.
        if not candidate_id:
            raise PreparationBlocked(["source_decision_candidate_binding_missing"])
    predecessor = {
        "relation_generation_id": "rg_s0183_certified_predecessor",
        "certified_predecessor": True,
        "candidate_inventory_hash": sha256_file(candidates),
        "decision_receipt_hash": sha256_file(receipt_path),
        "cross_manifest_hash": sha256_file(manifest_path),
        "certified_candidate_count": len(certified_ids),
    }
    _trace_event(phase="certified_predecessor_resolution", status="completed",
                 output_path=str(candidates), certified_candidate_count=len(certified_ids))
    return candidates, decisions, predecessor


def _predecessor_unrecoverability_manifest(paths: Paths) -> dict[str, Any]:
    """Record the proven discontinuity; it never repairs S0183 evidence."""
    root = paths.local_root / "audit" / "s0183" / "current"
    manifest_path = root / "cross_batch_reconciliation_manifest.json"
    receipt_path = root / "human_decision_preservation_manifest.json"
    manifest = read_json(manifest_path)
    receipt = read_json(receipt_path)
    declared = Path(str(manifest.get("current_candidates_path") or ""))
    if not declared.is_absolute():
        declared = REPO_ROOT / declared
    snapshot = Path(str(manifest.get("historical_candidates_path") or ""))
    if not snapshot.is_absolute():
        snapshot = REPO_ROOT / snapshot
    expected = str(manifest.get("current_candidates_hash") or "")
    observed = sha256_file(declared)
    snapshot_hash = sha256_file(snapshot)
    if not expected or observed == expected:
        raise PreparationBlocked(["governed_review_rebaseline_not_justified"])
    return {
        "schema_version": "current-relational-predecessor-unrecoverability/v1",
        "source_manifest_path": str(manifest_path),
        "source_manifest_hash": sha256_file(manifest_path),
        "source_receipt_path": str(receipt_path),
        "source_receipt_hash": sha256_file(receipt_path),
        "declared_inventory_path": str(declared),
        "declared_inventory_hash": expected,
        "observed_inventory_hash": observed,
        "observed_inventory_bytes": declared.stat().st_size if declared.is_file() else None,
        "mutable_binding_detected": paths.current_dir in declared.resolve().parents,
        "immutable_snapshot_candidates": [{
            "path": str(snapshot), "sha256": snapshot_hash,
            "matches_expected_hash": snapshot_hash == expected,
        }],
        "expected_bytes_recovered": False,
        "git_evidence_checked": True,
        "local_evidence_checked": True,
        "reason_codes": [
            "predecessor_manifest_bound_to_mutable_inventory",
            "certified_predecessor_inventory_unrecoverable",
        ],
        "historical_artifacts_modified": False,
    }


def _stage_governed_review_rebaseline(paths: Paths, staged_current: Path) -> dict[str, Any]:
    """RB0/RB1/RB2 without treating a mutable predecessor as authority.

    The old decisions remain source evidence.  The only derived decisions are
    those independently bound by the immutable S0183 decision snapshot and
    its hash-certified equivalence matrix.
    """
    rb0 = _predecessor_unrecoverability_manifest(paths)
    root = paths.local_root / "audit" / "s0183" / "current"
    manifest_path = root / "cross_batch_reconciliation_manifest.json"
    receipt_path = root / "human_decision_preservation_manifest.json"
    manifest, receipt = read_json(manifest_path), read_json(receipt_path)
    matrix_path = root / "old_to_current_reconciliation.jsonl"
    historical_path = Path(str(receipt.get("historical_decisions_path") or ""))
    if not historical_path.is_absolute():
        historical_path = REPO_ROOT / historical_path
    source_path = paths.current_dir / "human_review_decisions.jsonl"
    if (
        not matrix_path.is_file()
        or sha256_file(matrix_path) != manifest.get("old_to_current_hash")
        or not historical_path.is_file()
        or sha256_file(historical_path) != receipt.get("historical_decisions_hash")
        or not source_path.is_file()
    ):
        raise PreparationBlocked(["source_decision_integrity_blocked"])
    shutil.copyfile(source_path, staged_current / "human_review_decisions.jsonl")
    source_rows = read_jsonl(source_path)
    historical_rows = read_jsonl(historical_path)
    historical = {str(row.get("candidate_id") or ""): row for row in historical_rows}
    mappings = {str(row.get("candidate_id") or ""): row for row in read_jsonl(matrix_path)}
    if len(historical) != len(historical_rows) or len(mappings) != len(read_jsonl(matrix_path)):
        raise PreparationBlocked(["source_decision_integrity_blocked"])
    current_rows = read_jsonl(staged_current / "relation_candidates.jsonl")
    current_by_id = {str(row.get("candidate_id") or ""): row for row in current_rows}
    queue = read_jsonl(staged_current / "ready_for_human_review.jsonl")
    queue_by_id = {str(row.get("candidate_id") or ""): row for row in queue}
    if len(queue_by_id) != len(queue):
        raise PreparationBlocked(["rebaseline_current_candidate_conservation_failed"])
    bindings = human_review.current_bindings(staged_current, paths.local_root)
    items: list[dict[str, Any]] = []
    effective: dict[str, dict[str, Any]] = {}
    for source in source_rows:
        source_id = str(source.get("candidate_id") or "")
        source_hash = human_review.decision_hash(source)
        errors = human_review.validate_human_review_decision_record(source)
        disposition = "provenance_only_due_unrecoverable_predecessor"
        reason = "source_decision_provenance_only"
        current_id: str | None = None
        rebound: dict[str, Any] | None = None
        origin_id = str(source.get("preserved_from_candidate_id") or "")
        mapping = mappings.get(origin_id)
        historical_source = historical.get(origin_id)
        if errors:
            disposition, reason = "integrity_blocked", "source_decision_integrity_blocked"
        elif (
            origin_id and mapping and historical_source
            and mapping.get("classification") == "equivalent"
            and mapping.get("decision_reusable") is True
            and source.get("preserved_from_decision_hash") == human_review.decision_hash(historical_source)
        ):
            target_id = str(mapping.get("counterpart_candidate_id") or "")
            candidate = current_by_id.get(target_id)
            fingerprint = reconciliation._payload_hash(
                reconciliation.candidate_semantic_payload(candidate)
            )
            if (
                candidate is not None
                and target_id in queue_by_id
                and fingerprint == mapping.get("semantic_fingerprint")
            ):
                if target_id in effective:
                    disposition, reason = "conflict_blocked", "source_decision_conflict_blocked"
                else:
                    rebound = dict(source)
                    for key in (
                        "preserved_from_candidate_id", "preserved_from_decision_hash",
                        "preserved_from_bindings", "preservation_classification",
                        "preservation_manifest_hash",
                    ):
                        rebound.pop(key, None)
                    rebound.update({
                        "candidate_id": target_id,
                        "source_canon_id": human_review.candidate_endpoint(candidate, "source"),
                        "target_canon_id": human_review.candidate_endpoint(candidate, "target"),
                        "predicate": str(candidate.get("relation_type") or ""),
                        "relation_schema_version": str(candidate.get("candidate_schema_version") or candidate.get("schema_version") or ""),
                        "evidence": candidate.get("evidence") or {},
                        "rebaseline_preservation": {
                            "source_decision_id": source_id,
                            "source_decision_hash": source_hash,
                            "historical_decision_hash": human_review.decision_hash(historical_source),
                            "matrix_path": str(matrix_path),
                            "matrix_hash": sha256_file(matrix_path),
                            "semantic_fingerprint": fingerprint,
                        },
                        **bindings,
                    })
                    rebound_errors = human_review.validate_human_review_decision_record(rebound)
                    if rebound_errors:
                        disposition, reason = "integrity_blocked", "source_decision_integrity_blocked"
                    else:
                        effective[target_id] = rebound
                        current_id = target_id
                        disposition, reason = "independently_preserved", "source_decision_independently_preserved"
            else:
                reason = "source_decision_provenance_only"
        items.append({
            "source_decision_id": source_id,
            "source_decision_hash": source_hash,
            "source_action": source.get("human_review_decision"),
            "original_review_state_id": "rv_s0183_historical",
            "original_candidate_id": origin_id or source_id,
            "current_candidate_id": current_id,
            "candidate_binding_independent": disposition == "independently_preserved",
            "action_binding_independent": disposition == "independently_preserved",
            "exact_current_binding_verified": disposition == "independently_preserved",
            "disposition": disposition,
            "reason_code": reason,
        })
    blocked = [item for item in items if item["disposition"] in {"integrity_blocked", "conflict_blocked"}]
    if blocked:
        codes = {item["reason_code"] for item in blocked}
        raise PreparationBlocked(codes)
    write_jsonl(staged_current / EFFECTIVE_DECISIONS_FILE, (effective[key] for key in sorted(effective)))
    covered = set(effective)
    coverage = [{
        "candidate_id": candidate_id,
        "candidate_hash": semantic_hash(queue_by_id[candidate_id]),
        "technical_status": str(queue_by_id[candidate_id].get("status") or "reviewable"),
        "preserved_effective_decision_id": candidate_id if candidate_id in covered else None,
        "coverage_status": "independently_preserved" if candidate_id in covered else "pending_human_rebaseline_review",
        "review_required": candidate_id not in covered,
        "reason_code": "source_decision_independently_preserved" if candidate_id in covered else "current_candidate_not_covered_by_certified_decision",
    } for candidate_id in sorted(queue_by_id)]
    source_totals = {
        "source_decisions": len(items),
        "independently_preserved": sum(x["disposition"] == "independently_preserved" for x in items),
        "provenance_only": sum(x["disposition"] == "provenance_only_due_unrecoverable_predecessor" for x in items),
        "integrity_blocked": 0,
        "conflict_blocked": 0,
        "unaccounted": 0,
    }
    candidate_totals = {
        "reviewable_total": len(coverage),
        "independently_covered": sum(x["coverage_status"] == "independently_preserved" for x in coverage),
        "pending_human_review": sum(x["coverage_status"] == "pending_human_rebaseline_review" for x in coverage),
        "conflict_blocked": 0,
        "unaccounted": 0,
        "duplicate_coverage": 0,
    }
    preservation = {
        "schema_version": "current-independent-decision-preservation/v1",
        "source_review_state_id": "rv_s0183_historical",
        "current_relation_generation_id": None,
        "predecessor_certified_inventory_available": False,
        "totals": source_totals,
        "items": items,
    }
    request = {
        "schema_version": "current-governed-review-rebaseline/v1",
        "cause": rb0["reason_codes"],
        "predecessor_unrecoverability_manifest": "predecessor_unrecoverability_manifest.json",
        "source_decision_partition": source_totals | {"conservation_valid": True},
        "current_candidate_partition": candidate_totals | {"conservation_valid": True},
        "current_candidate_coverage": coverage,
        "source_decisions_modified": False,
        "historical_artifacts_modified": False,
    }
    write_json(staged_current / "predecessor_unrecoverability_manifest.json", rb0)
    write_json(staged_current / "independent_decision_preservation_manifest.json", preservation)
    write_json(staged_current / GOVERNED_REBASELINE_REQUEST, request)
    return {
        "schema_version": "current-generational-decision-preservation/v1",
        "mode": "governed_review_rebaseline",
        "historical_decisions": len(items),
        "preserved_equivalent": len(effective),
        "pending_delta": candidate_totals["pending_human_review"],
        "complete": True,
        "reason_codes": ["governed_review_rebaseline_started", "review_rebaseline_completed"],
    }


def _preserve_equivalent_decisions(
    *,
    paths: Paths,
    staged_current: Path,
    previous_candidates: Path | None,
    previous_decisions: Path | None,
    previous_manifest: dict[str, Any] | None,
    previous_record: dict[str, Any] | None = None,
    preserve_source_decisions: bool = False,
    failure_hook: Any = None,
) -> dict[str, Any]:
    current_candidates = read_jsonl(staged_current / "relation_candidates.jsonl")
    historical_candidates = read_jsonl(previous_candidates) if previous_candidates else []
    cross = reconciliation.build_cross_batch_reconciliation(
        historical_candidates,
        current_candidates,
    )
    historical_by_id = {
        str(row.get("candidate_id") or ""): row for row in historical_candidates
    }
    if len(historical_by_id) != len(historical_candidates):
        raise PreparationBlocked(["cross_generation_reconciliation_failed"])
    old_decisions = read_jsonl(previous_decisions) if previous_decisions else []
    decisions_by_id: dict[str, dict[str, Any]] = {}
    for row in old_decisions:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id or candidate_id in decisions_by_id:
            raise PreparationBlocked(["decision_preservation_failed"])
        if candidate_id not in historical_by_id:
            raise PreparationBlocked(
                ["decision_preservation_failed"],
                f"stale decision extension: {candidate_id}",
            )
        if human_review.validate_human_review_decision_record(row):
            raise PreparationBlocked(
                ["decision_preservation_failed"],
                f"invalid predecessor decision: {candidate_id}",
            )
        decisions_by_id[candidate_id] = row
    queue = read_jsonl(staged_current / "ready_for_human_review.jsonl")
    queue_by_id = {str(row.get("candidate_id") or ""): row for row in queue}
    if len(queue_by_id) != len(queue):
        raise PreparationBlocked(["decision_preservation_failed"], "duplicate current queue id")
    bindings = human_review.current_bindings(staged_current, paths.local_root)
    preserved: dict[str, dict[str, Any]] = {}
    provenance: list[dict[str, Any]] = []
    for mapping in cross["old_to_current"]:
        old_id = str(mapping.get("candidate_id") or "")
        old = decisions_by_id.get(old_id)
        if old is None:
            continue
        current_id = str(mapping.get("counterpart_candidate_id") or "")
        classification = str(mapping.get("classification") or "")
        candidate = queue_by_id.get(current_id)
        provenance.append({
            "historical_candidate_id": old_id,
            "current_candidate_id": current_id or None,
            "classification": classification,
            "decision_reused": bool(classification == "equivalent" and candidate),
            "historical_decision_hash": human_review.decision_hash(old),
        })
        if classification != "equivalent" or candidate is None:
            continue
        if current_id in preserved:
            raise PreparationBlocked(
                ["decision_preservation_failed"],
                f"many-to-one equivalent mapping: {current_id}",
            )
        rebound = dict(old)
        historical_chain = {
            key: rebound.pop(key)
            for key in (
                "preserved_from_candidate_id",
                "preserved_from_decision_hash",
                "preserved_from_bindings",
                "preservation_classification",
                "preservation_manifest_hash",
            )
            if key in rebound
        }
        rebound.update({
            "candidate_id": current_id,
            "source_canon_id": human_review.candidate_endpoint(candidate, "source"),
            "target_canon_id": human_review.candidate_endpoint(candidate, "target"),
            "predicate": str(candidate.get("relation_type") or ""),
            "relation_schema_version": str(
                candidate.get("candidate_schema_version")
                or candidate.get("schema_version")
                or ""
            ),
            "evidence": candidate.get("evidence") or {},
            "generational_preservation": {
                "classification": "equivalent",
                "previous_candidate_id": old_id,
                "previous_decision_hash": human_review.decision_hash(old),
                "previous_relation_generation_id": (
                    previous_manifest or {}
                ).get("relation_generation_id"),
                "historical_preservation_chain": historical_chain,
            },
            **bindings,
        })
        errors = human_review.validate_human_review_decision_record(rebound)
        if errors:
            raise PreparationBlocked(
                ["decision_preservation_failed"],
                f"{current_id}: {'; '.join(errors)}",
            )
        preserved[current_id] = rebound
    decision_target = staged_current / (
        EFFECTIVE_DECISIONS_FILE
        if preserve_source_decisions else "human_review_decisions.jsonl"
    )
    write_jsonl(
        decision_target,
        (preserved[key] for key in sorted(preserved)),
    )
    report = {
        "schema_version": "current-generational-decision-preservation/v1",
        "previous_relation_generation_id": (previous_manifest or {}).get(
            "relation_generation_id"
        ),
        "historical_decisions": len(decisions_by_id),
        "preserved_equivalent": len(preserved),
        "pending_delta": len(queue) - len(preserved),
        "disappeared_provenance": sum(
            item["classification"] == "disappeared" for item in provenance
        ),
        "mappings": provenance,
        "complete": True,
    }
    if previous_record and previous_record.get("receipts_path"):
        receipt_source = Path(previous_record["receipts_path"])
        receipt_target = staged_current / REVIEW_RECEIPTS_FILE
        shutil.copyfile(receipt_source, receipt_target)
        lineage = previous_record.get("receipt_lineage") or (
            _validate_review_receipt_lineage(paths, previous_record)
        )
        source_lineage_descriptor = previous_record.get("lineage_descriptor") or {}
        lineage_descriptor = {
            "schema_version": (
                "current-review-receipt-lineage/v2"
                if lineage.get("segments") else "current-review-receipt-lineage/v1"
            ),
            "source_bundle_path": str(previous_record["bundle"]),
            "source_bundle_manifest_hash": previous_record["manifest_hash"],
            "source_relation_generation_id": (
                source_lineage_descriptor.get("source_relation_generation_id")
                or previous_record["manifest"].get("relation_generation_id")
            ),
            "source_review_state_id": (
                source_lineage_descriptor.get("source_review_state_id")
                or previous_record["manifest"].get("review_state_id")
            ),
            "source_effective_decisions_hash": sha256_file(
                previous_record["decisions_path"]
            ),
            "source_review_receipts_path": str(receipt_source),
            "source_review_receipts_hash": sha256_file(receipt_source),
            "carried_review_receipts_hash": sha256_file(receipt_target),
            "receipt_count": lineage["receipt_count"],
            "receipt_ids": lineage["receipt_ids"],
            "receipt_candidate_ids": lineage["consumed_candidate_ids"],
            "root_review_state_id": lineage["root_review_state_id"],
            "tip_review_state_id": lineage["tip_review_state_id"],
            "recovered_from_semantic_regression": bool(
                previous_record.get("recovered_from_regression")
            ),
            "preserved_equivalent": len(preserved),
            "preservation_mapping_hash": semantic_hash(provenance),
            "historical_artifacts_modified": False,
            "integrity_verified": True,
        }
        if lineage.get("segments"):
            lineage_descriptor["segments"] = lineage["segments"]
        write_json(staged_current / REVIEW_LINEAGE_FILE, lineage_descriptor)
        report["review_receipt_lineage"] = {
            "manifest": REVIEW_LINEAGE_FILE,
            "manifest_hash": sha256_file(staged_current / REVIEW_LINEAGE_FILE),
            "receipts": REVIEW_RECEIPTS_FILE,
            "receipts_hash": sha256_file(receipt_target),
            "receipt_count": lineage["receipt_count"],
            "integrity_verified": True,
        }
    write_json(staged_current / "generational_decision_preservation.json", report)
    if failure_hook is not None:
        try:
            failure_hook("decision_preservation")
        except PreparationBlocked:
            raise
        except RuntimeError as error:
            raise PreparationBlocked(["decision_preservation_failed"], str(error)) from error
    return report


def rebuild_source_generation(
    paths: Paths,
    *,
    source_root: Path = REPO_ROOT,
    failure_hook: Any = None,
) -> tuple[Path, Path, dict[str, Any]]:
    canon = canon_snapshot(paths.local_root)
    rebuild_id = "cg_" + semantic_hash({
        key: canon[key] for key in ("hash", "records", "shards")
    })[:24]
    # PID namespaces can reuse the same small PID across invocations.  A
    # publication retry must therefore never collide with a previous staging
    # directory solely because its process identifier was recycled.
    work = paths.current_dir.parent / f".staging-{rebuild_id}-{uuid.uuid4().hex}"
    if work.exists():
        raise PreparationBlocked(["candidate_generation_rebuild_failed"], "staging collision")
    staged_current = work / "current"
    staged_audit = work / "audit"
    staged_current.mkdir(parents=True)
    staged_audit.mkdir(parents=True)
    baseline = paths.local_root / "audit" / "s0180" / "pre_relational_rag_baseline_manifest.json"
    if not baseline.is_file():
        shutil.rmtree(work)
        raise PreparationBlocked(
            ["candidate_generation_rebuild_failed"],
            f"immutable reconciliation baseline missing: {baseline}",
        )
    shutil.copyfile(baseline, staged_audit / baseline.name)
    try:
        _call_rebuild_step(
            [
                sys.executable,
                str(REPO_ROOT / "src/python_scripts/generate_technical_relation_candidates.py"),
                "--repo-root", str(source_root),
                "--canon-root", str(paths.local_root),
                "--out-dir", str(staged_current),
                "--session", "CURRENT",
                "--run-id", rebuild_id,
                "--exclude-prior-dir", str(paths.current_dir),
                "--dry-run",
            ],
            reason_code="candidate_generation_rebuild_failed",
            failpoint="candidate_generation",
            failure_hook=failure_hook,
        )
        _call_rebuild_step(
            [
                sys.executable,
                str(REPO_ROOT / "src/python_scripts/validate_relation_candidates.py"),
                "--candidate-file", str(staged_current / "relation_candidates.jsonl"),
                "--canon-root", str(paths.local_root),
                "--report", str(staged_current / "validation_report.json"),
                "--human-review", str(staged_current / "human_review.md"),
                "--output-dir", str(staged_current),
                "--session-tag", "CURRENT",
                "--dry-run",
            ],
            reason_code="candidate_validation_rebuild_failed",
            failpoint="candidate_validation",
            failure_hook=failure_hook,
        )
        _call_rebuild_step(
            [
                sys.executable,
                str(REPO_ROOT / "src/python_scripts/reconcile_current_relation_candidates.py"),
                "--canon-root", str(paths.local_root),
                "--current-dir", str(staged_current),
                "--audit-dir", str(staged_audit),
            ],
            reason_code="cross_generation_reconciliation_failed",
            failpoint="candidate_reconciliation",
            failure_hook=failure_hook,
        )
        _trace_event(phase="decision_preservation", status="started", output_path=str(staged_current))
        _rebase_staged_candidate_generation(staged_current, paths.current_dir)
        _trace_event(phase="decision_preservation", status="completed", reason_code="staged_generation_rebased")
        try:
            (
                previous_candidates, previous_decisions, previous_manifest,
                previous_record,
            ) = _previous_authority(paths)
        except PreparationBlocked as error:
            if not PREDECESSOR_UNRECOVERABLE_REASONS.issubset(error.reason_codes):
                raise
            _trace_event(
                phase="governed_review_rebaseline", status="started",
                reason_codes=error.reason_codes,
            )
            preservation = _stage_governed_review_rebaseline(paths, staged_current)
            _trace_event(phase="governed_review_rebaseline", status="completed")
        else:
            _trace_event(phase="decision_preservation", status="started", reason_code="preserve_equivalent_decisions")
            preservation = _preserve_equivalent_decisions(
                paths=paths,
                staged_current=staged_current,
                previous_candidates=previous_candidates,
                previous_decisions=previous_decisions,
                previous_manifest=previous_manifest,
                previous_record=previous_record,
                failure_hook=failure_hook,
            )
        _trace_event(phase="decision_preservation", status="completed", output_path=str(staged_current / "human_review_decisions.jsonl"))
        staged_paths = Paths(
            local_root=paths.local_root,
            current_dir=staged_current,
            audit_root=paths.audit_root,
            admission_current=paths.admission_current,
            generations=paths.generations,
            pointer=paths.pointer,
        )
        _trace_event(phase="generator_validation", status="started", output_path=str(staged_current))
        validate_source_generation(staged_paths, canon)
        _trace_event(phase="generator_validation", status="completed", output_path=str(staged_current))
        return work, staged_current, preservation
    except BaseException as error:
        _trace_event(phase="staging_generation", status="failed", reason_code=(error.reason_codes[0] if isinstance(error, PreparationBlocked) and error.reason_codes else "staging_generation_failed"), error_type=type(error).__name__, error_message=str(error))
        if work.exists():
            shutil.rmtree(work)
        raise


def recompose_current_decision_authority(
    paths: Paths, *, failure_hook: Any = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Rebind certified decisions while reusing an already-current technical set."""
    canon = canon_snapshot(paths.local_root)
    validate_source_generation(paths, canon)
    work = paths.current_dir.parent / (
        f".staging-decision-recomposition-{uuid.uuid4().hex}"
    )
    staged_current = work / "current"
    if work.exists():
        raise PreparationBlocked(["decision_recomposition_failed"], "staging collision")
    try:
        shutil.copytree(paths.current_dir, staged_current)
        for filename in (
            EFFECTIVE_DECISIONS_FILE,
            "generational_decision_preservation.json",
            REVIEW_RECEIPTS_FILE,
            REVIEW_LINEAGE_FILE,
            GOVERNED_REBASELINE_REQUEST,
            "predecessor_unrecoverability_manifest.json",
            "independent_decision_preservation_manifest.json",
        ):
            (staged_current / filename).unlink(missing_ok=True)
        (
            previous_candidates, previous_decisions, previous_manifest,
            previous_record,
        ) = _previous_authority(paths)
        if not previous_candidates or not previous_decisions or not previous_record:
            raise PreparationBlocked(["review_predecessor_not_resolved"])
        preservation = _preserve_equivalent_decisions(
            paths=paths,
            staged_current=staged_current,
            previous_candidates=previous_candidates,
            previous_decisions=previous_decisions,
            previous_manifest=previous_manifest,
            previous_record=previous_record,
            preserve_source_decisions=True,
            failure_hook=failure_hook,
        )
        staged_paths = Paths(
            local_root=paths.local_root,
            current_dir=staged_current,
            audit_root=paths.audit_root,
            admission_current=paths.admission_current,
            generations=paths.generations,
            pointer=paths.pointer,
        )
        validate_source_generation(staged_paths, canon)
        return work, staged_current, preservation
    except BaseException:
        if work.exists():
            shutil.rmtree(work)
        raise


def generation_ids(
    canon: dict[str, Any], inputs: dict[str, Path], decisions_semantic_hash: str,
    pending_ids: list[str], gate_report: dict[str, Any],
    taxonomy: dict[str, Any] | None = None,
    review_lineage_semantic_hash: str | None = None,
) -> dict[str, str]:
    canon_generation_id = "cg_" + semantic_hash({
        "hash": canon["hash"], "records": canon["records"], "shards": canon["shards"],
    })[:24]
    candidate_manifest = read_json(inputs["candidate_manifest"])
    validation_report = read_json(inputs["validation_report"])
    reconciliation_manifest = read_json(inputs["reconciliation_manifest"])
    reviewable_manifest = read_json(inputs["reviewable_manifest"])
    candidate_batch = candidate_manifest.get("candidate_batch") or {}
    relation_generation_id = "rg_" + semantic_hash({
        "canon_generation_id": canon_generation_id,
        "candidate_batch": {
            key: candidate_batch.get(key)
            for key in ("hash", "namespace", "record_count")
        },
        "validation_summary": validation_report.get("summary") or {},
        "reconciliation": {
            "matrix_hash": reconciliation_manifest.get("matrix_hash"),
            "total": reconciliation_manifest.get("total"),
            "unclassified": reconciliation_manifest.get("unclassified"),
            "dispositions": reconciliation_manifest.get("dispositions") or {},
        },
        "reviewable": {
            "record_count": reviewable_manifest.get("record_count"),
            "records_hash": reviewable_manifest.get("records_hash"),
        },
        "producer_fingerprints": {
            name: sha256_file(path)
            for name, path in sorted(producer_bindings().items())
            if name in {"candidate_generator", "candidate_validator", "cross_generation_reconciler"}
        },
    })[:24]
    gate_identity = {
        "summary": {
            key: (gate_report.get("summary") or {}).get(key)
            for key in (
                "total_evaluated", "technically_invalid", "awaiting_human_review",
                "human_rejected", "human_deferred", "approved_for_admission",
                "admission_ready_dry_run",
            )
        },
        "items": [
            {
                key: item.get(key)
                for key in (
                    "candidate_id", "gate_status", "decision", "blocking_reasons",
                    "human_review_decision", "human_review_reason_code",
                )
            }
            for item in sorted(
                gate_report.get("items") or [],
                key=lambda row: str(row.get("candidate_id") or ""),
            )
        ],
    }
    review_state_id = "rv_" + semantic_hash({
        "relation_generation_id": relation_generation_id,
        "human_decisions_semantic_hash": decisions_semantic_hash,
        "review_receipt_lineage_semantic_hash": review_lineage_semantic_hash,
        "pending_candidate_ids": pending_ids,
        "review_taxonomy": [
            {
                "candidate_id": item.get("candidate_id"),
                "reconciliation_class": item.get("reconciliation_class"),
                "review_reason": item.get("review_reason"),
            }
            for item in (taxonomy or {}).get("items", [])
        ],
        "admission_gate": gate_identity,
    })[:24]
    return {
        "canon_generation_id": canon_generation_id,
        "relation_generation_id": relation_generation_id,
        "review_state_id": review_state_id,
    }


def previous_generation(paths: Paths) -> tuple[Path | None, str | None, str | None]:
    if paths.pointer.is_file():
        try:
            predecessor = _resolve_monotonic_review_predecessor(paths)
            return (
                predecessor["candidates_path"],
                predecessor["manifest"].get("relation_generation_id"),
                str(predecessor["bundle"]),
            )
        except (OSError, ValueError, json.JSONDecodeError, PreparationBlocked):
            pass
    status = read_current_bundle_status(paths.local_root)
    if status.get("valid") is not True and paths.pointer.is_file():
        try:
            pointer = read_json(paths.pointer)
            bundle = Path(str(pointer.get("bundle_path") or ""))
            manifest_path = bundle / "bundle_manifest.json"
            manifest = read_json(manifest_path)
            if (
                bundle.is_dir()
                and sha256_file(manifest_path) == pointer.get("bundle_manifest_hash")
            ):
                _validate_staged_bundle(bundle, manifest)
                status = {
                    "valid": True,
                    "bundle_path": str(bundle),
                    "manifest": manifest,
                }
        except (OSError, ValueError, json.JSONDecodeError, PreparationBlocked):
            pass
    if status.get("valid") is True:
        bundle = Path(str(status["bundle_path"]))
        manifest = status["manifest"]
        candidate = bundle / "relation_candidates.jsonl"
        if candidate.is_file():
            return candidate, manifest.get("relation_generation_id"), str(bundle)
    legacy = paths.local_root / "audit" / "s0183" / "current" / "cross_batch_reconciliation_manifest.json"
    if legacy.is_file():
        manifest = read_json(legacy)
        candidate = Path(str(manifest.get("historical_candidates_path") or ""))
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        if candidate.is_file():
            return candidate, "rg_s0183_historical", str(legacy)
    return None, None, None


def build_cross_generation(
    historical_path: Path | None, current_path: Path,
) -> dict[str, Any]:
    current = read_jsonl(current_path)
    historical = read_jsonl(historical_path) if historical_path else []
    result = reconciliation.build_cross_batch_reconciliation(historical, current)
    coverage = (
        sum(result["old_counts"].values()) == len(historical)
        and sum(result["current_counts"].values()) == len(current)
    )
    if not coverage:
        raise PreparationBlocked(["cross_generation_reconciliation_incomplete"])
    return result | {
        "historical_count": len(historical),
        "current_count": len(current),
        "coverage_complete": True,
    }


def previous_published_review_taxonomy(
    previous_reference: str | None,
    current_candidates_path: Path,
    pending_candidate_ids: list[str],
) -> dict[str, Any] | None:
    """Reuse an already-published taxonomy only for the exact same review set.

    A second preparation observes the just-published candidates as
    cross-generation ``equivalent``.  That observation must not erase the
    certified reason that placed those candidates in the current review state.
    """
    if not previous_reference:
        return None
    bundle = Path(previous_reference)
    previous_candidates = bundle / "relation_candidates.jsonl"
    delta_path = bundle / "human_delta.json"
    if (
        not bundle.is_dir()
        or not previous_candidates.is_file()
        or not delta_path.is_file()
        or sha256_file(previous_candidates) != sha256_file(current_candidates_path)
    ):
        return None
    delta = read_json(delta_path)
    previous_pending = list(delta.get("pending_candidate_ids") or [])
    rows = list(delta.get("review_candidates") or [])
    if previous_pending != pending_candidate_ids:
        return None
    validation = review_taxonomy.validate_published_review_taxonomy(previous_pending, rows)
    if not validation["valid"]:
        return None
    return {
        "schema_version": review_taxonomy.SCHEMA_REVIEW_TAXONOMY,
        "items": rows,
        "review_reason_counts": validation["review_reason_counts"],
        "missing_review_reason_candidate_ids": [],
        "unsupported_review_reason_candidate_ids": [],
        "duplicate_candidate_ids": [],
        "total_pending": validation["total_pending"],
        "conservation_valid": True,
    }


def previous_published_review_classes(
    previous_reference: str | None,
    current_candidates_path: Path,
    pending_candidate_ids: list[str],
) -> dict[str, str]:
    """Recover certified v1/v2 class partitions from the exact current bundle."""
    if not previous_reference:
        return {}
    bundle = Path(previous_reference)
    previous_candidates = bundle / "relation_candidates.jsonl"
    delta_path = bundle / "human_delta.json"
    if (
        not bundle.is_dir()
        or not previous_candidates.is_file()
        or not delta_path.is_file()
        or sha256_file(previous_candidates) != sha256_file(current_candidates_path)
    ):
        return {}
    delta = read_json(delta_path)
    if list(delta.get("pending_candidate_ids") or []) != pending_candidate_ids:
        return {}
    pending = set(pending_candidate_ids)
    result: dict[str, str] = {}
    for classification in review_taxonomy.RECONCILIATION_CLASS_TO_REVIEW_REASON:
        for raw_candidate_id in delta.get(classification) or []:
            candidate_id = str(raw_candidate_id)
            if candidate_id not in pending or candidate_id in result:
                return {}
            result[candidate_id] = classification
    return result


def load_and_classify_decisions(
    paths: Paths, inputs: dict[str, Path], canon: dict[str, Any],
) -> tuple[human_review.ExistingDecisions, list[dict[str, Any]], dict[str, str]]:
    queue = read_jsonl(inputs["ready_queue"])
    queue_ids = {str(row.get("candidate_id") or "") for row in queue}
    bindings = {
        "canon_hash": canon["hash"],
        "candidate_manifest_hash": str(sha256_file(inputs["candidate_manifest"])),
        "reconciliation_manifest_hash": str(sha256_file(inputs["reconciliation_manifest"])),
    }
    try:
        decisions = human_review.load_existing_decisions(
            inputs["human_decisions"], queue_ids, bindings,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PreparationBlocked(["preserved_decision_integrity_failed"], str(error)) from error
    return decisions, queue, bindings


def _analysis_review_predecessor(paths: Paths) -> dict[str, Any] | None:
    if not paths.pointer.is_file():
        return None
    try:
        return _resolve_monotonic_review_predecessor(paths)
    except PreparationBlocked:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PreparationBlocked(
            ["review_predecessor_not_resolved"], str(error),
        ) from error


def _expected_equivalent_decisions(
    predecessor: dict[str, Any], inputs: dict[str, Path],
) -> dict[str, dict[str, Any]]:
    current_candidates = read_jsonl(inputs["candidate_batch"])
    queue_ids = {
        str(row.get("candidate_id") or "")
        for row in read_jsonl(inputs["ready_queue"])
    }
    cross = reconciliation.build_cross_batch_reconciliation(
        list(predecessor["candidate_by_id"].values()), current_candidates,
    )
    expected: dict[str, dict[str, Any]] = {}
    for mapping in cross["old_to_current"]:
        old_id = str(mapping.get("candidate_id") or "")
        current_id = str(mapping.get("counterpart_candidate_id") or "")
        decision = predecessor["decision_by_id"].get(old_id)
        if (
            decision is None
            or mapping.get("classification") != "equivalent"
            or mapping.get("decision_reusable") is not True
            or current_id not in queue_ids
        ):
            continue
        if current_id in expected:
            raise PreparationBlocked(["review_predecessor_ambiguous"])
        expected[current_id] = decision
    return expected


def _validate_review_semantic_monotonicity(
    predecessor: dict[str, Any], inputs: dict[str, Path],
    decisions: human_review.ExistingDecisions,
) -> dict[str, Any]:
    expected = _expected_equivalent_decisions(predecessor, inputs)
    conflicts = sorted(
        candidate_id for candidate_id in set(expected).intersection(decisions)
        if _decision_authority_signature(expected[candidate_id])
        != _decision_authority_signature(decisions[candidate_id])
    )
    if conflicts:
        raise PreparationBlocked(
            ["review_decision_conflict"], ", ".join(conflicts),
        )
    missing = sorted(set(expected) - set(decisions))
    if missing:
        raise PreparationBlocked(
            [
                "review_decision_recomposition_required",
                "review_semantic_coverage_regression",
            ],
            f"{len(missing)} equivalent reviewed candidates lost coverage",
        )
    return {
        "technical_reviewable": len(read_jsonl(inputs["ready_queue"])),
        "expected_equivalent_covered": len(expected),
        "effective_decision_covered": len(decisions),
        "effective_pending": max(
            0, len(read_jsonl(inputs["ready_queue"])) - len(decisions)
        ),
        "predecessor_review_state_id": predecessor["manifest"].get(
            "review_state_id"
        ),
        "receipt_count": len(predecessor["receipts"]),
        "monotonic": True,
    }


def inspect_review_coverage(paths: Paths) -> dict[str, Any]:
    """Read-only projection of technical queue versus certified human coverage."""
    try:
        canon = canon_snapshot(paths.local_root)
        inputs = validate_source_generation(paths, canon)
        predecessor = _analysis_review_predecessor(paths)
        expected = (
            _expected_equivalent_decisions(predecessor, inputs)
            if predecessor is not None else {}
        )
        queue = read_jsonl(inputs["ready_queue"])
        queue_ids = {str(row.get("candidate_id") or "") for row in queue}
        current: dict[str, dict[str, Any]] = {}
        try:
            decisions, _queue, _bindings = load_and_classify_decisions(
                paths, inputs, canon,
            )
            current = dict(decisions)
        except PreparationBlocked as error:
            if "preserved_decision_integrity_failed" not in error.reason_codes:
                raise
        conflicts = {
            candidate_id for candidate_id in set(expected).intersection(current)
            if _decision_authority_signature(expected[candidate_id])
            != _decision_authority_signature(current[candidate_id])
        }
        if conflicts:
            raise PreparationBlocked(["review_decision_conflict"])
        covered = queue_ids.intersection(set(expected).union(current))
        return {
            "technical_reviewable": len(queue_ids),
            "effective_decision_covered": len(covered),
            "effective_pending": len(queue_ids - covered),
            "expected_equivalent_covered": len(expected),
            "receipt_count": len(predecessor["receipts"])
            if predecessor is not None else 0,
            "coverage_source": (
                "certified_predecessor_preview"
                if predecessor is not None else "current_effective_decisions"
            ),
            "valid": True,
            "reason_codes": [],
        }
    except (OSError, ValueError, json.JSONDecodeError, PreparationBlocked) as error:
        return {
            "technical_reviewable": None,
            "effective_decision_covered": None,
            "effective_pending": None,
            "coverage_source": None,
            "valid": False,
            "reason_codes": getattr(
                error, "reason_codes", ["review_coverage_not_resolved"],
            ),
        }


def effective_current_decisions(
    decisions: dict[str, dict[str, Any]], queue: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    queue_ids = {str(row.get("candidate_id") or "") for row in queue}
    return {candidate_id: row for candidate_id, row in decisions.items() if candidate_id in queue_ids}


def build_gate_report(
    queue: list[dict[str, Any]], effective: dict[str, dict[str, Any]],
    canon: dict[str, Any], candidates_file: Path,
) -> dict[str, Any]:
    canon_index = admission_gate.load_canon_index(canon["glob"])
    candidates = admission_gate.apply_persistent_review_decisions_to_candidates(queue, effective)
    results = [admission_gate.evaluate_gate(candidate, canon_index) for candidate in candidates]
    return admission_gate.build_dry_run_report(
        results,
        session="current",
        candidates_file=candidates_file,
        canon_glob=canon["glob"],
        persistent_human_decisions=effective,
    )


def _decision_checkpoint(
    decisions: human_review.ExistingDecisions, inputs: dict[str, Path], ids: dict[str, str],
    previous_reference: str | None, cross_manifest_name: str,
) -> dict[str, Any]:
    rows = []
    for candidate_id, record in sorted(decisions.items()):
        generational = record.get("generational_preservation") or {}
        classification = (
            "preserved_equivalent"
            if generational.get("classification") == "equivalent"
            else "preserved_historical"
            if candidate_id in decisions.preserved_historical
            else "current_direct"
        )
        rows.append({
            "candidate_id": candidate_id,
            "decision_sha256": semantic_hash(record),
            "classification": classification,
        })
    checkpoint = {
        "schema_version": SCHEMA_CHECKPOINT,
        "relation_generation_id": ids["relation_generation_id"],
        "review_state_id": ids["review_state_id"],
        "previous_checkpoint_or_receipt": previous_reference,
        "decisions_file_path": str(inputs["human_decisions"]),
        "decisions_file_hash": sha256_file(inputs["human_decisions"]),
        "total_decisions": len(decisions),
        "preserved_historical": sum(
            row["classification"] == "preserved_historical" for row in rows
        ),
        "preserved_equivalent": sum(
            row["classification"] == "preserved_equivalent" for row in rows
        ),
        "current_direct": sum(
            row["classification"] == "current_direct" for row in rows
        ),
        "invalid": len(decisions.invalid_or_stale),
        "individual_decision_hashes": rows,
        "mapping_manifest": cross_manifest_name,
        "created_by_process": "prepare_current_relational_generation.py",
    }
    if "review_receipts" in inputs and "review_lineage" in inputs:
        checkpoint["review_receipts_hash"] = sha256_file(
            inputs["review_receipts"]
        )
        checkpoint["review_receipt_lineage_hash"] = sha256_file(
            inputs["review_lineage"]
        )
    return checkpoint


def validate_plan_conservation(plan: dict[str, Any]) -> None:
    approved = list(plan.get("approved_candidate_ids") or [])
    planned = list(plan.get("would_apply_candidate_ids") or [])
    omitted_rows = list(plan.get("omitted_duplicate_representations") or [])
    omitted = [str(row.get("candidate_id") or "") for row in omitted_rows]
    unaccounted = list(plan.get("unaccounted_approved_candidate_ids") or [])
    accounted = planned + omitted + unaccounted
    reasons: list[str] = []
    if len(accounted) != len(set(accounted)):
        reasons.append("approved_representation_accounted_more_than_once")
    if set(accounted) != set(approved):
        reasons.append("approved_partition_conservation_failed")
    if unaccounted:
        reasons.append("approved_representation_unaccounted")
    signatures = [(
        (
            (row.get("evidence") or {}).get("source_id"),
            (row.get("evidence") or {}).get("target_id"),
            (row.get("evidence") or {}).get("relation_type"),
        ),
        row.get("canonical_relation_identity"),
    ) for row in omitted_rows]
    if any(
        not all(signature)
        or identity != hashlib.sha256(
            json.dumps(signature, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        for signature, identity in signatures
    ):
        reasons.append("duplicate_group_identity_conflict")
    if (
        int(plan.get("approved_candidate_representations") or 0)
        != int(plan.get("planned_unique_relations") or 0)
        + int(plan.get("omitted_planned_count") or 0)
        + int(plan.get("unaccounted_approved_representations") or 0)
    ):
        reasons.append("approved_partition_conservation_failed")
    if plan.get("conservation_valid") is not True:
        reasons.append("approved_partition_conservation_failed")
    if reasons:
        raise PreparationBlocked(reasons)


def analyze(paths: Paths) -> dict[str, Any]:
    canon = canon_snapshot(paths.local_root)
    inputs = validate_source_generation(paths, canon)
    predecessor = _analysis_review_predecessor(paths)
    try:
        decisions, queue, bindings = load_and_classify_decisions(
            paths, inputs, canon,
        )
    except PreparationBlocked as error:
        if predecessor is None or "preserved_decision_integrity_failed" not in error.reason_codes:
            raise
        raise PreparationBlocked(
            ["review_decision_recomposition_required"], error.detail,
        ) from error
    coverage = (
        _validate_review_semantic_monotonicity(predecessor, inputs, decisions)
        if predecessor is not None else {
            "technical_reviewable": len(queue),
            "expected_equivalent_covered": 0,
            "effective_decision_covered": len(decisions),
            "effective_pending": max(0, len(queue) - len(decisions)),
            "predecessor_review_state_id": None,
            "receipt_count": 0,
            "monotonic": True,
        }
    )
    effective = effective_current_decisions(decisions, queue)
    gate_report = build_gate_report(queue, effective, canon, inputs["ready_queue"])
    summary = gate_report["summary"]
    pending_ids = sorted(
        str(row.get("candidate_id") or "") for row in queue
        if str(row.get("candidate_id") or "") not in effective
    )
    rebaseline_request_path = paths.current_dir / GOVERNED_REBASELINE_REQUEST
    rebaseline_request = (
        read_json(rebaseline_request_path) if rebaseline_request_path.is_file() else None
    )
    historical_path, previous_relation_id, previous_reference = previous_generation(paths)
    cross = build_cross_generation(historical_path, inputs["candidate_batch"])
    published_classes = previous_published_review_classes(
        previous_reference, inputs["candidate_batch"], pending_ids,
    )
    if published_classes:
        cross["current_to_old"] = [
            {
                **row,
                "classification": published_classes.get(
                    str(row.get("candidate_id") or ""), row.get("classification")
                ),
                "decision_reusable": (
                    False
                    if str(row.get("candidate_id") or "") in published_classes
                    else row.get("decision_reusable")
                ),
                "classification_source": (
                    "published_current_human_delta"
                    if str(row.get("candidate_id") or "") in published_classes
                    else row.get("classification_source")
                ),
            }
            for row in cross["current_to_old"]
        ]
    taxonomy = review_taxonomy.build_review_taxonomy(
        pending_ids, cross["current_to_old"], rebaseline_request,
    )
    if not taxonomy["conservation_valid"]:
        published_taxonomy = previous_published_review_taxonomy(
            previous_reference, inputs["candidate_batch"], pending_ids,
        )
        if published_taxonomy is not None:
            taxonomy = published_taxonomy
    if not taxonomy["conservation_valid"]:
        reasons = ["current_review_taxonomy_conservation_failed"]
        if taxonomy["missing_review_reason_candidate_ids"]:
            reasons.append("current_review_reason_evidence_missing")
        if taxonomy["unsupported_review_reason_candidate_ids"]:
            reasons.append("current_review_reason_unsupported")
        raise PreparationBlocked(reasons)
    ids = generation_ids(
        canon, inputs, _semantic_human_decisions_hash(inputs["human_decisions"]),
        pending_ids,
        gate_report, taxonomy, _review_lineage_semantic_hash(
            inputs.get("review_lineage")
        ),
    )
    terminal = TERMINAL_HUMAN if pending_ids else TERMINAL_AUTHORIZATION
    execution_plan = {
        "reuse": ["canon", "candidate_generation", "validation", "current_reconciliation"],
        "regenerate": [
            "cross_generation_reconciliation", "decision_checkpoint", "pending_queue",
            "admission_gate", "gate_g", "apply_plan", "rollback_snapshot",
            "authorization_request",
        ],
    }
    return {
        "paths": paths,
        "canon": canon,
        "inputs": inputs,
        "decisions": decisions,
        "effective_decisions": effective,
        "queue": queue,
        "bindings": bindings,
        "gate_report": gate_report,
        "gate_summary": summary,
        "pending_ids": pending_ids,
        "review_taxonomy": taxonomy,
        "ids": ids,
        "cross": cross,
        "historical_path": historical_path,
        "previous_relation_generation_id": previous_relation_id,
        "previous_reference": previous_reference,
        "review_predecessor": predecessor,
        "review_coverage": coverage,
        "terminal_state": terminal,
        "execution_plan": execution_plan,
    }


def _plan_for_analysis(analysis: dict[str, Any], gate_path: Path, decision_path: Path) -> dict[str, Any]:
    inputs = analysis["inputs"]
    plan = admission_gate.build_apply_plan(
        candidates=analysis["queue"],
        canon_glob=analysis["canon"]["glob"],
        human_review_decisions=analysis["effective_decisions"],
        dry_run_report=analysis["gate_report"],
        dry_run_report_path=gate_path,
        dry_run_recent=True,
        binding_paths={
            "candidate_manifest": inputs["candidate_manifest"],
            "validation_report": inputs["validation_report"],
            "reconciliation_manifest": inputs["reconciliation_manifest"],
            "reviewable_manifest": inputs["reviewable_manifest"],
            "human_review_decisions": decision_path,
        },
    )
    validate_plan_conservation(plan)
    if plan.get("block_reasons"):
        raise PreparationBlocked(["apply_plan_invalid", *plan["block_reasons"]])
    # Current identity is semantic: publication-local path prefixes do not
    # change the identity of an otherwise identical sealed apply plan.
    plan["apply_plan_id"] = admission_gate.semantic_apply_plan_id(plan)
    return plan


def _readiness_identity(
    ids: dict[str, Any], plan: dict[str, Any], canon: dict[str, Any],
) -> str:
    return "rd_" + semantic_hash({
        "review_state_id": ids["review_state_id"],
        "approved": plan["approved_candidate_representations"],
        "planned": plan["planned_unique_relations"],
        "omitted": plan["omitted_planned_count"],
        "would_apply_candidate_ids": sorted(plan["would_apply_candidate_ids"]),
        "omitted_candidate_ids": sorted(
            str(row.get("candidate_id") or "")
            for row in plan["omitted_duplicate_representations"]
        ),
        "canon_hash": canon["hash"],
    })[:24]


def _artifact(path: Path, bundle: Path, authority: str) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(bundle)),
        "sha256": sha256_file(path),
        "schema_version": (
            read_json(path).get("schema_version") or read_json(path).get("schema")
            if path.suffix == ".json" else "jsonl/v1"
        ),
        "authority": authority,
    }


_RETRY_VOLATILE_FIELDS = {
    "at", "completed_at", "created_at", "generated_at", "prepared_at",
    "published_at", "reviewed_at", "timestamp", "verified_at",
}
_RETRY_DERIVED_PHYSICAL_HASH_FIELDS = {
    "apply_plan_hash", "gate_g_hash", "journal_hash", "receipt_hash",
    "safety_verification_hash", "snapshot_hash", "snapshot_manifest_hash",
}


def _retry_semantic_value(value: Any, *, key: str = "") -> Any:
    """Normalize only publication-local representation for orphan comparison."""
    if isinstance(value, dict):
        return {
            item_key: _retry_semantic_value(item_value, key=item_key)
            for item_key, item_value in sorted(value.items())
            if item_key not in _RETRY_VOLATILE_FIELDS
            and not item_key.endswith("_at")
            and item_key not in _RETRY_DERIVED_PHYSICAL_HASH_FIELDS
        }
    if isinstance(value, list):
        return [_retry_semantic_value(item) for item in value]
    if isinstance(value, str) and (
        key.endswith("_path") or value.startswith("/")
    ):
        # Staging and final directories differ by construction.  Preserve the
        # artifact identity while excluding that publication-local prefix.
        return Path(value).name
    return value


def _bundle_retry_semantics(bundle: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Project every published role before adopting a valid orphan bundle."""
    artifact_projection: dict[str, Any] = {}
    for role, item in sorted((manifest.get("artifacts") or {}).items()):
        if not isinstance(item, dict):
            artifact_projection[role] = item
            continue
        descriptor = {
            key: value for key, value in item.items()
            if key not in {"path", "sha256"}
        }
        if str(item.get("status") or "").startswith("not_applicable"):
            artifact_projection[role] = {"descriptor": descriptor}
            continue
        path = bundle / str(item.get("path") or "")
        if path.suffix == ".json":
            raw_payload = read_json(path)
            if role == "safety_verification":
                payload: Any = {
                    "schema_version": raw_payload.get("schema_version"),
                    "passed": raw_payload.get("passed"),
                    "production_canon_unchanged": raw_payload.get(
                        "production_canon_unchanged"
                    ),
                    "success_copy_restored_exactly": raw_payload.get(
                        "success_copy_restored_exactly"
                    ),
                    "source_canon_hash": raw_payload.get("source_canon_hash"),
                    "source_shards": raw_payload.get("source_shards"),
                    "positive_apply": {
                        key: (raw_payload.get("positive_apply") or {}).get(key)
                        for key in (
                            "applied_count", "approved_count",
                            "omitted_planned_candidate_ids",
                            "omitted_planned_count", "status",
                            "would_apply_count",
                        )
                    },
                    "injected_failure": {
                        key: (raw_payload.get("injected_failure") or {}).get(key)
                        for key in ("restored_exactly", "status")
                    },
                    "rollback": {
                        key: (raw_payload.get("rollback") or {}).get(key)
                        for key in (
                            "byte_exact", "canon_modified", "restored_shards",
                            "status",
                        )
                    },
                    "repeated_rollback": {
                        key: (raw_payload.get("repeated_rollback") or {}).get(key)
                        for key in (
                            "byte_exact", "canon_modified", "restored_shards",
                            "status",
                        )
                    },
                    "second_apply": {
                        key: (raw_payload.get("second_apply") or {}).get(key)
                        for key in (
                            "applied_count", "omitted_existing_count", "status",
                        )
                    },
                }
            else:
                payload = _retry_semantic_value(raw_payload)
        elif path.suffix == ".jsonl" and role == "effective_decisions":
            payload = {
                "semantic_decisions_hash": human_review.semantic_review_decisions_hash(
                    read_jsonl(path)
                )
            }
        else:
            # Candidate inventories, reconciliation matrices and receipt
            # ledgers are already deterministic authority bytes.
            payload = {"sha256": sha256_file(path)}
        artifact_projection[role] = {
            "descriptor": descriptor,
            "payload": payload,
        }
    manifest_projection = {
        key: value for key, value in manifest.items()
        if key not in {
            "artifacts", "created_at", "published_at",
        }
    }
    return {
        "manifest": _retry_semantic_value(manifest_projection),
        "artifacts": artifact_projection,
    }


def _semantic_projection_differences(
    left: Any, right: Any, *, prefix: str = "", limit: int = 12,
) -> list[str]:
    """Return bounded field paths for a fail-closed retry collision report."""
    if left == right:
        return []
    if isinstance(left, dict) and isinstance(right, dict):
        differences: list[str] = []
        for key in sorted(set(left).union(right)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                differences.append(child)
            else:
                differences.extend(_semantic_projection_differences(
                    left[key], right[key], prefix=child,
                    limit=limit - len(differences),
                ))
            if len(differences) >= limit:
                break
        return differences[:limit]
    if isinstance(left, list) and isinstance(right, list):
        differences = []
        for index in range(max(len(left), len(right))):
            child = f"{prefix}[{index}]"
            if index >= len(left) or index >= len(right):
                differences.append(child)
            else:
                differences.extend(_semantic_projection_differences(
                    left[index], right[index], prefix=child,
                    limit=limit - len(differences),
                ))
            if len(differences) >= limit:
                break
        return differences[:limit]
    return [prefix or "<root>"]


def _validate_staged_bundle(bundle: Path, manifest: dict[str, Any]) -> None:
    reasons: list[str] = []
    terminal = str(manifest.get("terminal_state") or "")
    if manifest.get("schema_version") != SCHEMA_BUNDLE:
        reasons.append("bundle_schema_invalid")
    expected_next_action = TERMINAL_NEXT_ACTION.get(terminal)
    if expected_next_action is None:
        reasons.append("bundle_terminal_state_invalid")
    elif manifest.get("next_action") != expected_next_action:
        reasons.append("bundle_next_action_invalid")
    artifact_names = set((manifest.get("artifacts") or {}))
    for name, item in (manifest.get("artifacts") or {}).items():
        if str(item.get("status") or "").startswith("not_applicable"):
            continue
        path = bundle / str(item.get("path") or "")
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            reasons.append(f"bundle_artifact_invalid:{name}")
    if manifest.get("review_lineage_required") is True:
        required_lineage = {"review_receipts", "review_receipt_lineage"}
        if not required_lineage.issubset(artifact_names):
            reasons.append("review_receipt_lineage_incomplete")
        else:
            try:
                descriptor = read_json(_bundle_artifact_path(
                    bundle, manifest, "review_receipt_lineage",
                ))
                receipts_path = _bundle_artifact_path(
                    bundle, manifest, "review_receipts",
                )
                receipts = read_jsonl(receipts_path)
                if (
                    descriptor.get("schema_version")
                    not in {
                        "current-review-receipt-lineage/v1",
                        "current-review-receipt-lineage/v2",
                    }
                    or descriptor.get("integrity_verified") is not True
                    or descriptor.get("carried_review_receipts_hash")
                    != sha256_file(receipts_path)
                    or int(descriptor.get("receipt_count") or 0) != len(receipts)
                ):
                    reasons.append("review_receipt_lineage_invalid")
                if any(
                    receipt.get("schema_version")
                    not in {
                        "current-single-batch-review-receipt/v1",
                        "current-single-batch-review-receipt/v2",
                    }
                    for receipt in receipts
                ):
                    reasons.append("review_receipt_lineage_invalid")
                human_review._review_receipt_segments(descriptor, receipts)
            except (OSError, ValueError, json.JSONDecodeError, PreparationBlocked):
                reasons.append("review_receipt_lineage_invalid")
    if terminal == TERMINAL_AUTHORIZATION:
        required = {"candidate_manifest", "validation_report", "reconciliation_manifest", "reviewable_manifest", "relation_candidates", "ready_queue", "effective_decisions", "decision_checkpoint", "admission_gate", "gate_g", "apply_plan", "rollback_snapshot", "authorization_request"}
        missing = sorted(required - set((manifest.get("artifacts") or {})))
        if missing:
            reasons.extend(f"bundle_missing:{name}" for name in missing)
            reasons.append("bundle_incomplete")
    elif terminal in {
        TERMINAL_HUMAN, TERMINAL_REVIEW_COMPLETE,
    }:
        required = {
            "candidate_manifest", "validation_report", "reconciliation_manifest",
            "reviewable_manifest", "relation_candidates", "ready_queue",
            "effective_decisions", "decision_checkpoint", "admission_gate",
            "pending_queue", "batch_inventory", "current_human_delta",
            "review_rebaseline", "review_rebaseline_checkpoint",
            "independent_decision_preservation", "gate_g", "apply_plan",
            "rollback_snapshot", "authorization_request",
        }
        if terminal == TERMINAL_REVIEW_COMPLETE:
            required.add("review_receipts")
        complete = required.issubset(artifact_names)
        if not complete:
            reasons.append("bundle_incomplete")
        for name in ("gate_g", "apply_plan", "rollback_snapshot", "authorization_request"):
            if (manifest.get("artifacts") or {}).get(name, {}).get("status") != "not_applicable_pending_human_review":
                reasons.append(f"bundle_artifact_state_invalid:{name}")
        if manifest.get("readiness_id") is not None:
            reasons.append("human_delta_readiness_must_be_null")
        if complete:
            artifacts = manifest["artifacts"]
            delta = read_json(bundle / artifacts["pending_queue"]["path"])
            inventory = read_json(bundle / artifacts["batch_inventory"]["path"])
            delta_manifest = read_json(bundle / artifacts["current_human_delta"]["path"])
            delta_schema = delta.get("schema_version")
            if delta_schema not in {
                "current-relational-human-delta/v1",
                "current-relational-human-delta/v2",
            }:
                reasons.append("bundle_review_delta_schema_invalid")
            if (
                inventory.get("schema_version")
                != "current-relational-human-delta-inventory/v2"
            ):
                reasons.append("bundle_review_inventory_schema_invalid")
            if (
                delta_manifest.get("schema_version")
                != "current-governed-review-human-delta/v1"
            ):
                reasons.append("bundle_review_manifest_schema_invalid")
            if delta_schema == "current-relational-human-delta/v2":
                taxonomy_validation = review_taxonomy.validate_published_review_taxonomy(
                    delta.get("pending_candidate_ids") or [],
                    delta.get("review_candidates") or [],
                )
                if not taxonomy_validation["valid"]:
                    reasons.append("bundle_review_taxonomy_invalid")
                if (
                    inventory.get("review_reason_counts")
                    != taxonomy_validation["review_reason_counts"]
                    or delta_manifest.get("review_reason_counts")
                    != taxonomy_validation["review_reason_counts"]
                    or inventory.get("conservation_valid") is not True
                    or delta.get("conservation_valid") is not True
                    or delta_manifest.get("conservation_valid") is not True
                ):
                    reasons.append("bundle_review_taxonomy_conservation_invalid")
            if (
                terminal == TERMINAL_REVIEW_COMPLETE
                and (
                    int(delta.get("pending") or 0) != 0
                    or list(delta.get("pending_candidate_ids") or [])
                )
            ):
                reasons.append("review_complete_pending_must_be_zero")
    if reasons:
        raise PreparationBlocked(["bundle_publication_failed", *reasons])


def _write_cross_and_checkpoint(
    analysis: dict[str, Any], staging: Path, ids: dict[str, Any],
) -> dict[str, Path]:
    cross = analysis["cross"]
    write_jsonl(staging / "old_to_current_reconciliation.jsonl", cross["old_to_current"])
    write_jsonl(staging / "current_to_old_reconciliation.jsonl", cross["current_to_old"])
    cross_manifest = {
        "schema_version": "current-cross-generation-reconciliation/v1",
        "previous_relation_generation_id": analysis["previous_relation_generation_id"],
        "relation_generation_id": ids["relation_generation_id"],
        "historical_candidates_hash": sha256_file(analysis["historical_path"]) if analysis["historical_path"] else None,
        "current_candidates_hash": sha256_file(staging / "relation_candidates.jsonl"),
        "old_to_current_hash": sha256_file(staging / "old_to_current_reconciliation.jsonl"),
        "current_to_old_hash": sha256_file(staging / "current_to_old_reconciliation.jsonl"),
        "old_counts": cross["old_counts"],
        "current_counts": cross["current_counts"],
        "coverage_complete": cross["coverage_complete"],
        "decision_reuse_rule": "equivalent_only",
    }
    write_json(staging / "cross_generation_reconciliation.json", cross_manifest)
    checkpoint = _decision_checkpoint(
        analysis["decisions"], analysis["inputs"], ids,
        analysis["previous_reference"], "cross_generation_reconciliation.json",
    )
    checkpoint["previous_relation_generation_id"] = analysis[
        "previous_relation_generation_id"
    ]
    checkpoint["current_relation_generation_id"] = ids["relation_generation_id"]
    checkpoint["pending_delta"] = len(analysis["pending_ids"])
    checkpoint["disappeared_provenance"] = int(
        cross["old_counts"].get("disappeared", 0)
    )
    write_json(staging / "decision_checkpoint.json", checkpoint)
    return {
        "cross_generation_reconciliation": staging / "cross_generation_reconciliation.json",
        "decision_checkpoint": staging / "decision_checkpoint.json",
    }


def _bundle_source_bindings(analysis: dict[str, Any]) -> dict[str, Any]:
    values = {
        name: {"path": str(path), "sha256": sha256_file(path)}
        for name, path in sorted(analysis["inputs"].items())
    }
    values["human_decisions"]["mutable_for_human_delta_resume"] = True
    # A governed rebaseline publishes a self-contained review authority.  Its
    # mutable pipeline inputs remain provenance for the operator, not a second
    # competing authority that can invalidate the newly published bundle.
    if (analysis["paths"].current_dir / GOVERNED_REBASELINE_REQUEST).is_file():
        for name, item in values.items():
            if name != "human_decisions":
                item["currentness_role"] = "provenance_only"
    values.update({
        name: {
            "path": str(path),
            "sha256": sha256_file(path),
            "currentness_role": "provenance_only",
        }
        for name, path in sorted(producer_bindings().items())
    })
    values["canon"] = analysis["canon"]
    return values


def _materialize_governed_rebaseline(
    analysis: dict[str, Any], staging: Path, ids: dict[str, Any],
) -> dict[str, Path]:
    """Bind staged RB artifacts to the new review state after its ID exists."""
    request_path = analysis["paths"].current_dir / GOVERNED_REBASELINE_REQUEST
    if not request_path.is_file():
        return {}
    request = read_json(request_path)
    rb0_source = analysis["paths"].current_dir / "predecessor_unrecoverability_manifest.json"
    preservation_source = analysis["paths"].current_dir / "independent_decision_preservation_manifest.json"
    if not rb0_source.is_file() or not preservation_source.is_file():
        raise PreparationBlocked(["rebaseline_delta_assembly_failed"])
    shutil.copyfile(rb0_source, staging / rb0_source.name)
    preservation = read_json(preservation_source)
    preservation["current_relation_generation_id"] = ids["relation_generation_id"]
    preservation["new_review_state_id"] = ids["review_state_id"]
    write_json(staging / preservation_source.name, preservation)
    candidate_partition = dict(request["current_candidate_partition"])
    candidate_partition.setdefault("human_reviewed_covered", 0)
    rebaseline = {
        "schema_version": "current-review-rebaseline/v1",
        "canon_generation_id": ids["canon_generation_id"],
        "relation_generation_id": ids["relation_generation_id"],
        "previous_review_state_id": "rv_s0183_historical",
        "new_review_state_id": ids["review_state_id"],
        "cause": request["cause"],
        "current_candidate_partition": candidate_partition,
        "source_decision_partition": request["source_decision_partition"],
        "historical_artifacts_modified": False,
        "source_decisions_modified": False,
    }
    checkpoint = {
        "schema_version": "current-effective-review-rebaseline-checkpoint/v1",
        "relation_generation_id": ids["relation_generation_id"],
        "review_state_id": ids["review_state_id"],
        "historical_receipt_preserved": True,
        "independently_preserved_effective_decisions": request["source_decision_partition"]["independently_preserved"],
        "current_direct_effective_decisions": 0,
        "provenance_only_source_decisions": request["source_decision_partition"]["provenance_only"],
        "pending_human_delta": request["current_candidate_partition"]["pending_human_review"],
        "blocked_conflicts": request["source_decision_partition"]["conflict_blocked"],
        "source_decision_conservation_valid": True,
        "current_candidate_conservation_valid": True,
    }
    write_json(staging / "review_rebaseline_manifest.json", rebaseline)
    write_json(staging / "review_rebaseline_checkpoint.json", checkpoint)
    write_json(staging / "current_human_delta_manifest.json", {
        "schema_version": "current-governed-review-human-delta/v1",
        "relation_generation_id": ids["relation_generation_id"],
        "review_state_id": ids["review_state_id"],
        "pending_candidate_ids": [
            row["candidate_id"] for row in request["current_candidate_coverage"]
            if row["coverage_status"] == "pending_human_rebaseline_review"
        ],
        "reason_code": "current_candidate_queued_for_rebaseline_review",
        "review_taxonomy_schema": analysis["review_taxonomy"]["schema_version"],
        "review_reason_counts": analysis["review_taxonomy"]["review_reason_counts"],
        "review_candidates": analysis["review_taxonomy"]["items"],
        "conservation_valid": analysis["review_taxonomy"]["conservation_valid"],
    })
    return {
        "predecessor_unrecoverability": staging / rb0_source.name,
        "independent_decision_preservation": staging / preservation_source.name,
        "review_rebaseline": staging / "review_rebaseline_manifest.json",
        "review_rebaseline_checkpoint": staging / "review_rebaseline_checkpoint.json",
        "current_human_delta": staging / "current_human_delta_manifest.json",
    }


def _copy_review_lineage_inputs(
    analysis: dict[str, Any], staging: Path,
) -> dict[str, Path]:
    inputs = analysis["inputs"]
    if "review_receipts" not in inputs and "review_lineage" not in inputs:
        return {}
    if "review_receipts" not in inputs or "review_lineage" not in inputs:
        raise PreparationBlocked(["review_receipt_lineage_incomplete"])
    receipts = staging / REVIEW_RECEIPTS_FILE
    lineage = staging / REVIEW_LINEAGE_FILE
    shutil.copyfile(inputs["review_receipts"], receipts)
    shutil.copyfile(inputs["review_lineage"], lineage)
    descriptor = read_json(lineage)
    if (
        descriptor.get("integrity_verified") is not True
        or descriptor.get("carried_review_receipts_hash") != sha256_file(receipts)
    ):
        raise PreparationBlocked(["review_receipt_lineage_invalid"])
    return {
        "review_receipts": receipts,
        "review_receipt_lineage": lineage,
    }


def producer_fingerprints() -> dict[str, str | None]:
    """Declared producer graph.  Values are semantically governing hashes."""
    return {name: sha256_file(path) for name, path in sorted(producer_bindings().items())}


def _execute_human_delta(
    paths: Paths,
    analysis: dict[str, Any],
    *,
    failure_hook: Any = None,
) -> dict[str, Any]:
    ids: dict[str, Any] = dict(analysis["ids"])
    ids["readiness_id"] = None
    current_status = read_current_bundle_status(paths.local_root)
    if (
        current_status.get("valid") is True
        and current_status.get("terminal_state") == TERMINAL_HUMAN
        and (current_status.get("manifest") or {}).get("review_state_id")
        == ids["review_state_id"]
    ):
        return {
            "terminal_state": TERMINAL_HUMAN,
            "next_action": "REVIEW_CURRENT_RELATIONAL_DELTA",
            "idempotent_noop": True,
            "bundle_path": current_status["bundle_path"],
            "ids": ids,
            "planning": current_status.get("planning") or {},
            "writes_performed": False,
            "canon_modified": False,
            "decisions_modified": False,
            "apply_executed": False,
            "reason_codes": ["human_delta_bundle_ready"],
        }
    destination = (
        paths.generations / ids["relation_generation_id"]
        / ids["review_state_id"] / "human_delta"
    )
    staging = paths.generations / f".staging-{ids['review_state_id']}-{os.getpid()}"
    if staging.exists():
        raise PreparationBlocked(["human_delta_bundle_publication_failed"], "staging collision")
    staging.mkdir(parents=True, exist_ok=False)
    canon_before = analysis["canon"]["hash"]
    input_hashes_before = _source_hashes(analysis["inputs"])
    pointer_before = paths.pointer.read_bytes() if paths.pointer.is_file() else None
    pointer_written: bytes | None = None
    pointer_committed = False
    try:
        shutil.copyfile(analysis["inputs"]["candidate_batch"], staging / "relation_candidates.jsonl")
        shutil.copyfile(analysis["inputs"]["ready_queue"], staging / "ready_for_human_review.jsonl")
        for name, filename in (
            ("candidate_manifest", "current_candidate_manifest.json"),
            ("validation_report", "validation_report.json"),
            ("reconciliation_manifest", "reconciliation_manifest.json"),
            ("reviewable_manifest", "reviewable_candidate_manifest.json"),
        ):
            shutil.copyfile(analysis["inputs"][name], staging / filename)
        source_decisions = analysis["paths"].current_dir / "human_review_decisions.jsonl"
        if source_decisions.is_file():
            shutil.copyfile(source_decisions, staging / "source_human_review_decisions.jsonl")
        write_jsonl(
            staging / "effective_human_review_decisions.jsonl",
            analysis["effective_decisions"].values(),
        )
        common = _write_cross_and_checkpoint(analysis, staging, ids)
        lineage_artifacts = _copy_review_lineage_inputs(analysis, staging)
        rebaseline_artifacts = _materialize_governed_rebaseline(analysis, staging, ids)
        taxonomy = analysis["review_taxonomy"]
        taxonomy_by_id = {
            str(row["candidate_id"]): row for row in taxonomy["items"]
        }
        classified = {
            name: [
                candidate_id for candidate_id in analysis["pending_ids"]
                if taxonomy_by_id[candidate_id].get("reconciliation_class") == name
            ]
            for name in ("new", "modified", "ambiguous", "invalid")
        }
        reason_partitions = {
            reason: [
                candidate_id for candidate_id in analysis["pending_ids"]
                if taxonomy_by_id[candidate_id].get("review_reason") == reason
            ]
            for reason in review_taxonomy.ALLOWED_REVIEW_REASONS
        }
        human_delta = {
            "schema_version": "current-relational-human-delta/v2",
            "relation_generation_id": ids["relation_generation_id"],
            "review_state_id": ids["review_state_id"],
            "readiness_id": None,
            "pending": len(analysis["pending_ids"]),
            "pending_candidate_ids": analysis["pending_ids"],
            **classified,
            "review_taxonomy_schema": taxonomy["schema_version"],
            "review_reasons": reason_partitions,
            "review_reason_counts": taxonomy["review_reason_counts"],
            "review_candidates": taxonomy["items"],
            "missing_review_reason_candidate_ids": taxonomy["missing_review_reason_candidate_ids"],
            "unsupported_review_reason_candidate_ids": taxonomy["unsupported_review_reason_candidate_ids"],
            "conservation_valid": taxonomy["conservation_valid"],
            "disappeared_provenance": analysis["cross"]["old_counts"].get(
                "disappeared", 0
            ),
        }
        write_json(staging / "human_delta.json", human_delta)
        inventory = {
            "schema_version": "current-relational-human-delta-inventory/v2",
            "relation_generation_id": ids["relation_generation_id"],
            "review_state_id": ids["review_state_id"],
            "pending": len(analysis["pending_ids"]),
            "pending_candidate_ids": analysis["pending_ids"],
            "pending_queue_hash": sha256_file(staging / "ready_for_human_review.jsonl"),
            "review_taxonomy_schema": taxonomy["schema_version"],
            "review_reason_counts": taxonomy["review_reason_counts"],
            "review_candidates": taxonomy["items"],
            "missing_review_reason": len(taxonomy["missing_review_reason_candidate_ids"]),
            "unsupported_review_reason": len(taxonomy["unsupported_review_reason_candidate_ids"]),
            "duplicated": len(taxonomy["duplicate_candidate_ids"]),
            "conservation_valid": taxonomy["conservation_valid"],
            "authorization_created": False,
        }
        write_json(staging / "human_delta_inventory.json", inventory)
        # Even a first-generation delta needs a self-contained review basis.
        # It is not a historical rebaseline, but uses the same explicit
        # artifacts so the review surface never falls back to pipeline/current.
        if not rebaseline_artifacts:
            write_json(staging / "review_rebaseline_manifest.json", {
                "schema_version": "current-review-rebaseline/v1",
                "mode": "initial_current_review_basis",
                "relation_generation_id": ids["relation_generation_id"],
                "new_review_state_id": ids["review_state_id"],
                "current_candidate_partition": {
                    "reviewable_total": len(analysis["queue"]),
                    "independently_covered": len(analysis["effective_decisions"]),
                    "human_reviewed_covered": 0,
                    "pending_human_review": len(analysis["pending_ids"]),
                },
            })
            write_json(staging / "review_rebaseline_checkpoint.json", {
                "schema_version": "current-effective-review-rebaseline-checkpoint/v1",
                "relation_generation_id": ids["relation_generation_id"],
                "review_state_id": ids["review_state_id"],
                "independently_preserved_effective_decisions": len(
                    analysis["effective_decisions"]
                ),
                "current_direct_effective_decisions": 0,
                "pending_human_delta": len(analysis["pending_ids"]),
            })
            write_json(staging / "current_human_delta_manifest.json", {
                "schema_version": "current-governed-review-human-delta/v1",
                "relation_generation_id": ids["relation_generation_id"],
                "review_state_id": ids["review_state_id"],
                "pending_candidate_ids": analysis["pending_ids"],
                "reason_code": "current_candidate_queued_for_review",
                "review_taxonomy_schema": taxonomy["schema_version"],
                "review_reason_counts": taxonomy["review_reason_counts"],
                "review_candidates": taxonomy["items"],
                "conservation_valid": taxonomy["conservation_valid"],
            })
            write_json(staging / "independent_decision_preservation_manifest.json", {
                "schema_version": "current-independent-decision-preservation/v1",
                "current_relation_generation_id": ids["relation_generation_id"],
                "items": [],
            })
            rebaseline_artifacts = {
                "review_rebaseline": staging / "review_rebaseline_manifest.json",
                "review_rebaseline_checkpoint": staging / "review_rebaseline_checkpoint.json",
                "current_human_delta": staging / "current_human_delta_manifest.json",
                "independent_decision_preservation": staging / "independent_decision_preservation_manifest.json",
            }
        write_json(staging / "admission_gate_dry_run.json", analysis["gate_report"])
        artifact_paths = {
            "candidate_manifest": staging / "current_candidate_manifest.json",
            "validation_report": staging / "validation_report.json",
            "reconciliation_manifest": staging / "reconciliation_manifest.json",
            "reviewable_manifest": staging / "reviewable_candidate_manifest.json",
            "relation_candidates": staging / "relation_candidates.jsonl",
            "ready_queue": staging / "ready_for_human_review.jsonl",
            "effective_decisions": staging / "effective_human_review_decisions.jsonl",
            **common,
            **lineage_artifacts,
            "pending_queue": staging / "human_delta.json",
            "batch_inventory": staging / "human_delta_inventory.json",
            "admission_gate": staging / "admission_gate_dry_run.json",
        }
        if (staging / "source_human_review_decisions.jsonl").is_file():
            artifact_paths["source_decisions"] = staging / "source_human_review_decisions.jsonl"
        artifact_paths.update(rebaseline_artifacts)
        artifacts = {
            name: _artifact(path, staging, "current_relational_generation")
            for name, path in artifact_paths.items()
        }
        artifacts.update({
            name: {
                "status": "not_applicable_pending_human_review",
                "authority": "current_relational_generation",
            }
            for name in (
                "gate_g", "apply_plan", "rollback_snapshot", "authorization_request"
            )
        })
        manifest = {
            "schema_version": SCHEMA_BUNDLE,
            "run_id": "run_" + ids["review_state_id"][3:],
            **ids,
            "previous_relation_generation_id": analysis[
                "previous_relation_generation_id"
            ],
            "source_bindings": _bundle_source_bindings(analysis),
            "artifacts": artifacts,
            "terminal_state": TERMINAL_HUMAN,
            "next_action": "REVIEW_CURRENT_RELATIONAL_DELTA",
            "created_at": utc_now(),
            "authorization_present": False,
            "apply_executed": False,
            "canon_modified": False,
            "human_decisions_modified": False,
            "review_lineage_required": bool(lineage_artifacts),
        }
        if source_decisions.is_file():
            manifest["source_bindings"]["source_human_decisions"] = {
                "path": str(source_decisions),
                "sha256": sha256_file(source_decisions),
                "currentness_role": "provenance_only",
            }
        write_json(staging / "bundle_manifest.json", manifest)
        _validate_staged_bundle(staging, manifest)
        _run_failure_hook(
            failure_hook,
            "bundle_validation",
            "human_delta_bundle_publication_failed",
        )
        _run_failure_hook(
            failure_hook,
            "before_publication",
            "human_delta_bundle_publication_failed",
        )
        _assert_publication_sources_unchanged(
            paths,
            analysis,
            canon_hash=canon_before,
            input_hashes=input_hashes_before,
            pointer_bytes=pointer_before,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing = read_json(destination / "bundle_manifest.json")
            _validate_staged_bundle(destination, existing)
            staged_semantics = _bundle_retry_semantics(staging, manifest)
            existing_semantics = _bundle_retry_semantics(destination, existing)
            semantic_differences = _semantic_projection_differences(
                staged_semantics, existing_semantics,
            )
            if semantic_differences:
                raise PreparationBlocked(
                    ["human_delta_bundle_publication_failed"],
                    "semantic destination collision: "
                    + ", ".join(semantic_differences),
                )
            shutil.rmtree(staging)
        else:
            os.replace(staging, destination)
        _run_failure_hook(
            failure_hook,
            "after_bundle_publication",
            "human_delta_bundle_publication_failed",
        )
        published_manifest = read_json(destination / "bundle_manifest.json")
        _validate_staged_bundle(destination, published_manifest)
        _assert_publication_sources_unchanged(
            paths,
            analysis,
            canon_hash=canon_before,
            input_hashes=input_hashes_before,
            pointer_bytes=pointer_before,
        )
        pointer = {
            "schema_version": SCHEMA_POINTER,
            "bundle_path": str(destination),
            "bundle_manifest_path": str(destination / "bundle_manifest.json"),
            "bundle_manifest_hash": sha256_file(destination / "bundle_manifest.json"),
            **ids,
            "terminal_state": TERMINAL_HUMAN,
            "next_action": TERMINAL_NEXT_ACTION[TERMINAL_HUMAN],
            "published_at": utc_now(),
        }
        _run_failure_hook(
            failure_hook,
            "before_pointer_update",
            "human_delta_bundle_publication_failed",
        )
        _assert_publication_sources_unchanged(
            paths,
            analysis,
            canon_hash=canon_before,
            input_hashes=input_hashes_before,
            pointer_bytes=pointer_before,
        )
        pointer_candidate = _json_bytes(pointer)
        try:
            pointer_installed = current_authority.compare_and_swap_current_pointer(
                paths.pointer,
                expected=pointer_before,
                replacement=pointer_candidate,
            )
        except current_authority.CurrentRelationalAuthorityError as error:
            raise PreparationBlocked(["current_pointer_changed"]) from error
        pointer_committed = True
        if pointer_installed:
            pointer_written = pointer_candidate
        _run_failure_hook(
            failure_hook,
            "pointer_update",
            "human_delta_bundle_publication_failed",
        )
        status = read_current_bundle_status(paths.local_root)
        _assert_published_candidate_is_current(
            status,
            destination=destination,
            ids=ids,
            terminal_state=TERMINAL_HUMAN,
            failure_reason="human_delta_bundle_publication_failed",
        )
        return {
            "terminal_state": TERMINAL_HUMAN,
            "next_action": "REVIEW_CURRENT_RELATIONAL_DELTA",
            "idempotent_noop": False,
            "bundle_path": str(destination),
            "ids": ids,
            "planning": status.get("planning") or {},
            "writes_performed": True,
            "canon_modified": False,
            "decisions_modified": False,
            "apply_executed": False,
            "reason_codes": (
                ["governed_review_rebaseline_required", "review_rebaseline_completed"]
                if rebaseline_artifacts else ["human_delta_bundle_ready"]
            ),
        }
    except Exception as error:
        if staging.exists():
            shutil.rmtree(staging)
        pointer_restored = _restore_pointer_if_owned(
            paths.pointer, before=pointer_before, written=pointer_written,
        )
        # A physically published bundle is immutable and complete.  Preserve
        # it as recoverable evidence: a concurrent descendant may already bind
        # to it even when this writer no longer owns the current pointer.
        if pointer_written is not None and not pointer_restored:
            reasons = (
                list(error.reason_codes)
                if isinstance(error, PreparationBlocked)
                else ["human_delta_bundle_publication_failed"]
            )
            raise PreparationBlocked(
                [*reasons, "current_pointer_descendant_advanced"], str(error),
            ) from error
        if pointer_committed and pointer_written is None:
            reasons = (
                list(error.reason_codes)
                if isinstance(error, PreparationBlocked)
                else ["human_delta_bundle_publication_failed"]
            )
            observed_reason = (
                "current_pointer_equivalent_committed"
                if _path_bytes(paths.pointer) == pointer_candidate
                else "current_pointer_descendant_advanced"
            )
            raise PreparationBlocked(
                [*reasons, observed_reason], str(error),
            ) from error
        raise


def _rebuild_and_execute(
    paths: Paths,
    *,
    keep_safety_work: bool,
    source_root: Path,
    failure_hook: Any,
    recomposition_mode: str = "technical",
) -> dict[str, Any]:
    canon_before = canon_snapshot(paths.local_root)["hash"]
    decisions_path = paths.current_dir / "human_review_decisions.jsonl"
    decisions_before = sha256_file(decisions_path)
    pointer_before = paths.pointer.read_bytes() if paths.pointer.is_file() else None
    current_before = _directory_fingerprint(paths.current_dir)
    if recomposition_mode == "decision_authority":
        work, staged_current, preservation = recompose_current_decision_authority(
            paths, failure_hook=failure_hook,
        )
    else:
        work, staged_current, preservation = rebuild_source_generation(
            paths,
            source_root=source_root,
            failure_hook=failure_hook,
        )
    publish_nonce = uuid.uuid4().hex
    backup = paths.current_dir.with_name(f".previous-current-{publish_nonce}")
    failed_current = paths.current_dir.with_name(f".failed-current-{publish_nonce}")
    publication_lock_path = paths.current_dir.parent / ".current-publication.lock"
    publication_lock_path.parent.mkdir(parents=True, exist_ok=True)
    publication_lock = publication_lock_path.open("a+b")
    fcntl.flock(publication_lock.fileno(), fcntl.LOCK_EX)
    current_moved_to_backup = False
    swapped = False
    swapped_current_fingerprint: str | None = None
    swapped_current_identity: tuple[int, int] | None = None
    publication_committed = False
    secondary_work: Path | None = None
    intermediate_current: Path | None = None
    cascaded_decision_recomposition = False
    try:
        _run_failure_hook(
            failure_hook,
            "before_candidate_publication",
            "human_delta_bundle_publication_failed",
        )
        if canon_snapshot(paths.local_root)["hash"] != canon_before:
            raise PreparationBlocked(["generation_drift_during_rebuild"])
        if sha256_file(decisions_path) != decisions_before:
            raise PreparationBlocked(["decisions_drift_during_rebuild"])
        if _directory_fingerprint(paths.current_dir) != current_before:
            raise PreparationBlocked(["current_relational_source_changed"])
        if _path_bytes(paths.pointer) != pointer_before:
            raise PreparationBlocked(["current_pointer_changed"])
        if backup.exists() or failed_current.exists():
            raise PreparationBlocked(
                ["human_delta_bundle_publication_failed"], "candidate swap collision"
            )
        if paths.current_dir.exists():
            os.replace(paths.current_dir, backup)
            current_moved_to_backup = True
        try:
            os.replace(staged_current, paths.current_dir)
        except Exception:
            if (
                current_moved_to_backup
                and backup.exists()
                and not paths.current_dir.exists()
            ):
                os.replace(backup, paths.current_dir)
                current_moved_to_backup = False
            raise
        swapped = True
        swapped_current_fingerprint = _directory_fingerprint(paths.current_dir)
        swapped_current_identity = _directory_identity(paths.current_dir)
        if _path_bytes(paths.pointer) != pointer_before:
            raise PreparationBlocked(["current_pointer_changed"])
        # A technical rebuild can legitimately expose a second, causally
        # dependent need to rebind certified review authority.  Resolve that
        # transition once, inside this already-held publication transaction,
        # rather than recursively reacquiring the publication lock.
        if recomposition_mode == "technical":
            try:
                analyze(paths)
            except PreparationBlocked as error:
                reason_set = set(error.reason_codes)
                if not (
                    error.reason_codes
                    and reason_set.issubset(DECISION_RECOMPOSITION_REASONS)
                ):
                    raise

                _trace_event(
                    phase="decision_authority_recomposition",
                    status="started",
                    reason_codes=error.reason_codes,
                )

                (
                    secondary_work,
                    secondary_staged_current,
                    secondary_preservation,
                ) = recompose_current_decision_authority(
                    paths,
                    failure_hook=failure_hook,
                )

                # The second phase was derived from the just-published
                # technical generation.  Fail closed if any governing source
                # changed while it was being staged.
                if canon_snapshot(paths.local_root)["hash"] != canon_before:
                    raise PreparationBlocked(["generation_drift_during_rebuild"])
                if _path_bytes(paths.pointer) != pointer_before:
                    raise PreparationBlocked(["current_pointer_changed"])
                if (
                    _directory_identity(paths.current_dir)
                    != swapped_current_identity
                    or _directory_fingerprint(paths.current_dir)
                    != swapped_current_fingerprint
                ):
                    raise PreparationBlocked(["current_relational_source_changed"])

                intermediate_current = paths.current_dir.with_name(
                    f".technical-current-{publish_nonce}"
                )
                if intermediate_current.exists():
                    raise PreparationBlocked(
                        ["human_delta_bundle_publication_failed"],
                        "technical current handoff collision",
                    )

                os.replace(paths.current_dir, intermediate_current)
                try:
                    os.replace(secondary_staged_current, paths.current_dir)
                except BaseException:
                    os.replace(intermediate_current, paths.current_dir)
                    intermediate_current = None
                    raise

                swapped_current_fingerprint = _directory_fingerprint(
                    paths.current_dir
                )
                swapped_current_identity = _directory_identity(
                    paths.current_dir
                )
                preservation = secondary_preservation
                cascaded_decision_recomposition = True

                _trace_event(
                    phase="decision_authority_recomposition",
                    status="completed",
                    output_path=str(paths.current_dir),
                )

        result = execute(
            paths,
            keep_safety_work=keep_safety_work,
            source_root=source_root,
            failure_hook=failure_hook,
            _allow_rebuild=False,
        )
        # ``execute`` owns its exact pointer CAS and rollback.  Once it returns,
        # the publication is committed; never infer ownership by rereading a
        # pointer that a concurrent successor may already have advanced.
        publication_committed = True
        result["detected_changes"] = {
            "canon_changed": recomposition_mode == "technical",
            "candidate_generation_current": recomposition_mode == "decision_authority",
            "current_relational_authority_stale": True,
        }
        result["rebuild_steps"] = (
            [
                "decision_predecessor_resolution", "receipt_lineage_validation",
                "decision_preservation", "decision_checkpoint", "pending_queue",
                "admission_gate",
            ]
            if recomposition_mode == "decision_authority" else [
                "candidates", "validation", "reconciliation",
                "decision_preservation", "decision_checkpoint",
                "pending_queue", "admission_gate",
            ]
        )
        result["decision_preservation"] = preservation
        result.setdefault("reason_codes", []).insert(
            0,
            "review_decision_authority_recomposition_completed"
            if recomposition_mode == "decision_authority"
            else "candidate_generation_stale_rebuild_planned",
        )
        if cascaded_decision_recomposition:
            result.setdefault("reason_codes", []).insert(
                1, "review_decision_authority_recomposition_completed"
            )
        for disposable in (backup, work, secondary_work, intermediate_current):
            if disposable is not None and disposable.exists():
                try:
                    shutil.rmtree(disposable)
                except OSError:
                    # Publication is already committed.  A leftover backup or
                    # work tree is recoverable cleanup debt, not a reason to
                    # roll back a valid current authority.
                    pass
        return result
    except Exception as error:
        if publication_committed:
            # Post-commit reporting/cleanup failures cannot justify reverting
            # an authority that may already have a concurrent descendant.
            raise
        preserve_new_current = (
            isinstance(error, PreparationBlocked)
            and {
                "current_pointer_descendant_advanced",
                "current_pointer_equivalent_committed",
            }.intersection(error.reason_codes)
        )
        foreign_current = (
            swapped
            and (
                _directory_identity(paths.current_dir) != swapped_current_identity
                or _directory_fingerprint(paths.current_dir)
                != swapped_current_fingerprint
            )
        )
        if swapped and not preserve_new_current and not foreign_current:
            if paths.current_dir.exists():
                os.replace(paths.current_dir, failed_current)
            if backup.exists():
                os.replace(backup, paths.current_dir)
            if failed_current.exists():
                shutil.rmtree(failed_current)
        elif (
            current_moved_to_backup
            and not swapped
            and backup.exists()
            and not paths.current_dir.exists()
        ):
            os.replace(backup, paths.current_dir)
        # The inner publication restores only a pointer value it wrote itself.
        # Never overwrite a concurrent pointer advance from this outer swap.
        # Never delete an immutable published bundle here.  A concurrent
        # successor may already reference it as predecessor even when it is no
        # longer the direct current pointer target.
        for disposable in (work, secondary_work, intermediate_current):
            if disposable is not None and disposable.exists():
                shutil.rmtree(disposable)
        if foreign_current:
            reasons = (
                list(error.reason_codes)
                if isinstance(error, PreparationBlocked)
                else ["human_delta_bundle_publication_failed"]
            )
            raise PreparationBlocked(
                [*reasons, "current_pipeline_descendant_advanced"], str(error),
            ) from error
        raise
    finally:
        fcntl.flock(publication_lock.fileno(), fcntl.LOCK_UN)
        publication_lock.close()


def execute(
    paths: Paths,
    *,
    keep_safety_work: bool = False,
    source_root: Path = REPO_ROOT,
    failure_hook: Any = None,
    _allow_rebuild: bool = True,
) -> dict[str, Any]:
    if _allow_rebuild and not os.environ.get(TRACE_ENV):
        trace_path = paths.audit_root / "runtime" / f"recomposition-{uuid.uuid4().hex}.jsonl"
        os.environ[TRACE_ENV] = str(trace_path)
        _trace_event(phase="preflight", status="started", execution_id=trace_path.stem)
    try:
        analysis = analyze(paths)
    except PreparationBlocked as error:
        reason_set = set(error.reason_codes)
        if (
            _allow_rebuild
            and error.reason_codes
            and reason_set.issubset(
                REBUILDABLE_SOURCE_REASONS | {"candidate_generation_failed"}
            )
        ):
            _trace_event(phase="preflight", status="completed", reason_code="candidate_generation_stale")
            return _rebuild_and_execute(
                paths,
                keep_safety_work=keep_safety_work,
                source_root=source_root,
                failure_hook=failure_hook,
            )
        if (
            _allow_rebuild
            and error.reason_codes
            and reason_set.issubset(DECISION_RECOMPOSITION_REASONS)
        ):
            _trace_event(
                phase="preflight", status="completed",
                reason_code="review_decision_recomposition_required",
            )
            return _rebuild_and_execute(
                paths,
                keep_safety_work=keep_safety_work,
                source_root=source_root,
                failure_hook=failure_hook,
                recomposition_mode="decision_authority",
            )
        _trace_event(phase="preflight", status="failed", reason_code=error.reason_codes[0] if error.reason_codes else "preflight_failed", error_message=error.detail)
        raise
    ids = analysis["ids"]
    if analysis["terminal_state"] == TERMINAL_HUMAN:
        return _execute_human_delta(
            paths,
            analysis,
            failure_hook=failure_hook,
        )

    # Precompute deterministic readiness from the semantic plan, before any write.
    prospective_gate = paths.admission_current / "admission_gate_dry_run.json"
    prospective_decisions = analysis["inputs"]["human_decisions"]
    plan = _plan_for_analysis(analysis, prospective_gate, prospective_decisions)
    readiness_id = _readiness_identity(ids, plan, analysis["canon"])
    ids["readiness_id"] = readiness_id
    current_status = read_current_bundle_status(paths.local_root)
    current_manifest = current_status.get("manifest") or {}
    current_source = current_manifest.get("source_bindings") or {}
    current_artifacts = current_manifest.get("artifacts") or {}
    expected_lineage_hashes = {
        role: sha256_file(analysis["inputs"][input_name])
        for role, input_name in (
            ("review_receipts", "review_receipts"),
            ("review_receipt_lineage", "review_lineage"),
        )
        if input_name in analysis["inputs"]
    }
    if (
        current_status.get("valid") is True
        and current_manifest.get("terminal_state") == TERMINAL_AUTHORIZATION
        and all(
            current_manifest.get(name) == expected
            for name, expected in ids.items()
        )
        and (current_source.get("canon") or {}).get("hash") == analysis["canon"]["hash"]
        and (current_source.get("candidate_batch") or {}).get("sha256")
        == sha256_file(analysis["inputs"]["candidate_batch"])
        and (current_source.get("human_decisions") or {}).get("sha256")
        == sha256_file(analysis["inputs"]["human_decisions"])
        and all(
            (current_status.get("planning") or {}).get(name) == expected
            for name, expected in {
                "approved_candidate_representations": plan[
                    "approved_candidate_representations"
                ],
                "planned_unique_relations": plan["planned_unique_relations"],
                "omitted_duplicate_representations": plan[
                    "omitted_planned_count"
                ],
                "unaccounted_approved_representations": plan[
                    "unaccounted_approved_representations"
                ],
                "conservation_valid": plan["conservation_valid"],
            }.items()
        )
        and (current_manifest.get("review_lineage_required") is True)
        == bool(expected_lineage_hashes)
        and all(
            (current_artifacts.get(role) or {}).get("sha256") == expected_hash
            for role, expected_hash in expected_lineage_hashes.items()
        )
    ):
        stable_ids = {
            key: current_manifest.get(key)
            for key in (
                "canon_generation_id", "relation_generation_id",
                "review_state_id", "readiness_id",
            )
        }
        return {
            "terminal_state": TERMINAL_AUTHORIZATION,
            "next_action": "AUTHORIZE_CURRENT_RELATIONAL_APPLY",
            "idempotent_noop": True,
            "bundle_path": current_status["bundle_path"],
            "ids": stable_ids,
            "planning": current_status["planning"],
            "writes_performed": False,
            "canon_modified": False,
            "decisions_modified": False,
            "apply_executed": False,
        }
    semantic_destination = (
        paths.generations / ids["relation_generation_id"]
        / ids["review_state_id"] / readiness_id
    )
    destination = semantic_destination
    # A historical directory can carry the same semantic identifiers while
    # predating the self-contained-bundle contract.  It is evidence, not a
    # valid destination for a new publication.  Preserve it and publish the
    # repaired representation under a deterministic physical variant; the
    # pointer keeps the stable semantic identities as the sole operational
    # authority and a retry resolves the same orphan instead of duplicating it.
    if destination.exists():
        try:
            _validate_staged_bundle(destination, read_json(destination / "bundle_manifest.json"))
        except (OSError, ValueError, json.JSONDecodeError, PreparationBlocked):
            destination = destination.with_name(
                f"{readiness_id}--publication-"
                + semantic_hash({
                    "bundle_schema": SCHEMA_BUNDLE,
                    "representation": "self_contained_current_v1",
                })[:16]
            )
    _trace_event(
        phase="destination_selection", status="completed",
        semantic_destination=str(semantic_destination),
        selected_physical_destination=str(destination),
        historical_destination_preserved=(destination != semantic_destination),
    )
    paths.generations.mkdir(parents=True, exist_ok=True)
    staging = paths.generations / f".staging-{readiness_id}-{uuid.uuid4().hex}"
    if staging.exists():
        raise PreparationBlocked(["bundle_publication_failed"], f"staging collision: {staging}")
    staging.mkdir(parents=True, exist_ok=False)
    safety_work: Path | None = None
    canon_before = analysis["canon"]["hash"]
    input_hashes_before = _source_hashes(analysis["inputs"])
    pointer_before = paths.pointer.read_bytes() if paths.pointer.is_file() else None
    pointer_written: bytes | None = None
    pointer_committed = False
    try:
        _trace_event(phase="bundle_assembly", status="started", output_path=str(staging))
        # Preserve the exact relational source generation inside the immutable bundle.
        shutil.copyfile(analysis["inputs"]["candidate_batch"], staging / "relation_candidates.jsonl")
        shutil.copyfile(analysis["inputs"]["ready_queue"], staging / "ready_for_human_review.jsonl")
        # Apply is never allowed to recover these from mutable pipeline/current.
        for name, filename in (
            ("candidate_manifest", "current_candidate_manifest.json"),
            ("validation_report", "validation_report.json"),
            ("reconciliation_manifest", "reconciliation_manifest.json"),
            ("reviewable_manifest", "reviewable_candidate_manifest.json"),
        ):
            shutil.copyfile(analysis["inputs"][name], staging / filename)
        write_jsonl(staging / "effective_human_review_decisions.jsonl", analysis["effective_decisions"].values())
        lineage_artifacts = _copy_review_lineage_inputs(analysis, staging)

        cross = analysis["cross"]
        write_jsonl(staging / "old_to_current_reconciliation.jsonl", cross["old_to_current"])
        write_jsonl(staging / "current_to_old_reconciliation.jsonl", cross["current_to_old"])
        cross_manifest = {
            "schema_version": "current-cross-generation-reconciliation/v1",
            "previous_relation_generation_id": analysis["previous_relation_generation_id"],
            "relation_generation_id": ids["relation_generation_id"],
            "historical_candidates_hash": sha256_file(analysis["historical_path"]) if analysis["historical_path"] else None,
            "current_candidates_hash": sha256_file(staging / "relation_candidates.jsonl"),
            "old_to_current_hash": sha256_file(staging / "old_to_current_reconciliation.jsonl"),
            "current_to_old_hash": sha256_file(staging / "current_to_old_reconciliation.jsonl"),
            "old_counts": cross["old_counts"],
            "current_counts": cross["current_counts"],
            "coverage_complete": cross["coverage_complete"],
            "decision_reuse_rule": "equivalent_only",
        }
        write_json(staging / "cross_generation_reconciliation.json", cross_manifest)

        checkpoint = _decision_checkpoint(
            analysis["decisions"], analysis["inputs"], ids,
            analysis["previous_reference"], "cross_generation_reconciliation.json",
        )
        write_json(staging / "decision_checkpoint.json", checkpoint)
        human_delta = {
            "schema_version": "current-relational-human-delta/v1",
            "relation_generation_id": ids["relation_generation_id"],
            "review_state_id": ids["review_state_id"],
            "pending": len(analysis["pending_ids"]),
            "pending_candidate_ids": analysis["pending_ids"],
            "new": [], "modified": [], "ambiguous": [], "review_batches": [],
        }
        write_json(staging / "human_delta.json", human_delta)
        write_json(staging / "admission_gate_dry_run.json", analysis["gate_report"])

        # Rebuild the plan against the exact staged gate and effective decision set.
        plan = _plan_for_analysis(
            analysis,
            staging / "admission_gate_dry_run.json",
            staging / "effective_human_review_decisions.jsonl",
        )
        plan["dry_run_report"] = "admission_gate_dry_run.json"
        plan["relation_generation_id"] = ids["relation_generation_id"]
        plan["review_state_id"] = ids["review_state_id"]
        plan["readiness_id"] = readiness_id
        plan["exact_bindings"] = {
            "candidate_manifest": {"path": "current_candidate_manifest.json", "sha256": sha256_file(staging / "current_candidate_manifest.json")},
            "validation_report": {"path": "validation_report.json", "sha256": sha256_file(staging / "validation_report.json")},
            "reconciliation_manifest": {"path": "reconciliation_manifest.json", "sha256": sha256_file(staging / "reconciliation_manifest.json")},
            "reviewable_manifest": {"path": "reviewable_candidate_manifest.json", "sha256": sha256_file(staging / "reviewable_candidate_manifest.json")},
            "human_review_decisions": {"path": "effective_human_review_decisions.jsonl", "sha256": sha256_file(staging / "effective_human_review_decisions.jsonl")},
        }
        plan["payload_candidates_path"] = "ready_for_human_review.jsonl"
        plan["payload_candidates_hash"] = sha256_file(staging / "ready_for_human_review.jsonl")
        write_json(staging / "relation_apply_plan.json", plan)

        safety_work = Path(tempfile.mkdtemp(prefix=f"tdc-{readiness_id}-")) / "verification"
        safety = admission_gate.verify_apply_safety_on_temp_copy(
            source_canon_glob=analysis["canon"]["glob"],
            temp_work_root=safety_work,
            candidates_file=analysis["inputs"]["ready_queue"],
            human_review_decisions_file=staging / "effective_human_review_decisions.jsonl",
            dry_run_report_path=staging / "admission_gate_dry_run.json",
            binding_paths={
                "candidate_manifest": analysis["inputs"]["candidate_manifest"],
                "validation_report": analysis["inputs"]["validation_report"],
                "reconciliation_manifest": analysis["inputs"]["reconciliation_manifest"],
                "reviewable_manifest": analysis["inputs"]["reviewable_manifest"],
            },
            report_path=staging / "apply_safety_verification.json",
        )
        if safety.get("passed") is not True or safety.get("production_canon_unchanged") is not True:
            raise PreparationBlocked(["apply_plan_invalid"])

        snapshot_manifest = admission_gate.create_rollback_snapshot(
            canon_glob=analysis["canon"]["glob"],
            snapshot_root=staging / "rollback_snapshots",
            apply_plan_path=staging / "relation_apply_plan.json",
            apply_plan=plan,
            target_scope="production_preapply_snapshot",
        )
        snapshot = read_json(snapshot_manifest)
        snapshot["relation_generation_id"] = ids["relation_generation_id"]
        snapshot["review_state_id"] = ids["review_state_id"]
        snapshot["readiness_id"] = readiness_id
        snapshot["gate_g_hash"] = None
        snapshot["rollback_available"] = False
        write_json(snapshot_manifest, snapshot)

        final_plan = destination / "relation_apply_plan.json"
        final_snapshot = destination / snapshot_manifest.relative_to(staging)
        gate_g = {
            "schema_version": SCHEMA_GATE_G,
            **ids,
            "canon_hash": analysis["canon"]["hash"],
            "canon_records": analysis["canon"]["records"],
            "approved_candidate_representations": plan["approved_candidate_representations"],
            "planned_unique_relations": plan["planned_unique_relations"],
            "omitted_duplicate_representations": plan["omitted_planned_count"],
            "unaccounted_approved_representations": plan["unaccounted_approved_representations"],
            "conservation_valid": plan["conservation_valid"],
            "apply_plan_path": str(final_plan),
            "apply_plan_hash": sha256_file(staging / "relation_apply_plan.json"),
            "snapshot_path": str(final_snapshot),
            "snapshot_hash": sha256_file(snapshot_manifest),
            "safety_verification_hash": sha256_file(staging / "apply_safety_verification.json"),
            "current": True,
            "ready": True,
            "apply_authorized": False,
            "apply_executed": False,
            "rollback_snapshot_ready": True,
            "rollback_available": False,
        }
        write_json(staging / "gate_g_readiness.json", gate_g)
        authorization_request = {
            "schema_version": SCHEMA_AUTHORIZATION_REQUEST,
            "readiness_id": readiness_id,
            "planned_unique_mutations": plan["planned_unique_relations"],
            "omitted_duplicate_representations": plan["omitted_planned_count"],
            "required_confirmation": f"AUTHORIZE CURRENT RELATIONAL APPLY {readiness_id}",
            "expires_on_state_change": True,
            "authorization_present": False,
            "authorization_created": False,
        }
        write_json(staging / "authorization_request.json", authorization_request)

        artifact_paths = {
            "candidate_manifest": staging / "current_candidate_manifest.json",
            "validation_report": staging / "validation_report.json",
            "reconciliation_manifest": staging / "reconciliation_manifest.json",
            "reviewable_manifest": staging / "reviewable_candidate_manifest.json",
            "relation_candidates": staging / "relation_candidates.jsonl",
            "ready_queue": staging / "ready_for_human_review.jsonl",
            "effective_decisions": staging / "effective_human_review_decisions.jsonl",
            "cross_generation_reconciliation": staging / "cross_generation_reconciliation.json",
            "decision_checkpoint": staging / "decision_checkpoint.json",
            "pending_queue": staging / "human_delta.json",
            "admission_gate": staging / "admission_gate_dry_run.json",
            "apply_plan": staging / "relation_apply_plan.json",
            "safety_verification": staging / "apply_safety_verification.json",
            "rollback_snapshot": snapshot_manifest,
            "gate_g": staging / "gate_g_readiness.json",
            "authorization_request": staging / "authorization_request.json",
            **lineage_artifacts,
        }
        manifest = {
            "schema_version": SCHEMA_BUNDLE,
            "run_id": "run_" + readiness_id[3:],
            **ids,
            "previous_relation_generation_id": analysis["previous_relation_generation_id"],
            "source_bindings": _bundle_source_bindings(analysis),
            "producer_fingerprints": producer_fingerprints(),
            "artifacts": {
                name: _artifact(path, staging, "current_relational_generation")
                for name, path in artifact_paths.items()
            },
            "terminal_state": TERMINAL_AUTHORIZATION,
            "next_action": "AUTHORIZE_CURRENT_RELATIONAL_APPLY",
            "created_at": utc_now(),
            "authorization_present": False,
            "apply_executed": False,
            "canon_modified": False,
            "human_decisions_modified": False,
            "review_lineage_required": bool(lineage_artifacts),
        }
        write_json(staging / "bundle_manifest.json", manifest)
        _validate_staged_bundle(staging, manifest)
        _trace_event(phase="bundle_validation", status="completed", output_path=str(staging),
                     validation_input=str(staging), publication_source=str(staging),
                     publication_destination=str(destination))
        _run_failure_hook(
            failure_hook,
            "bundle_validation",
            "bundle_publication_failed",
        )

        _run_failure_hook(
            failure_hook,
            "before_publication",
            "bundle_publication_failed",
        )
        _assert_publication_sources_unchanged(
            paths,
            analysis,
            canon_hash=canon_before,
            input_hashes=input_hashes_before,
            pointer_bytes=pointer_before,
        )

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing_manifest = read_json(destination / "bundle_manifest.json")
            _validate_staged_bundle(destination, existing_manifest)
            staged_semantics = _bundle_retry_semantics(staging, manifest)
            existing_semantics = _bundle_retry_semantics(
                destination, existing_manifest,
            )
            semantic_differences = _semantic_projection_differences(
                staged_semantics, existing_semantics,
            )
            if semantic_differences:
                raise PreparationBlocked(
                    ["bundle_publication_failed"],
                    "semantic destination collision: "
                    + ", ".join(semantic_differences),
                )
            shutil.rmtree(staging)
        else:
            _trace_event(phase="physical_publication", status="started", output_path=str(destination))
            os.replace(staging, destination)
            _trace_event(phase="physical_publication", status="completed", output_path=str(destination))
        _run_failure_hook(
            failure_hook,
            "after_bundle_publication",
            "bundle_publication_failed",
        )
        published_manifest = read_json(destination / "bundle_manifest.json")
        _validate_staged_bundle(destination, published_manifest)
        _assert_publication_sources_unchanged(
            paths,
            analysis,
            canon_hash=canon_before,
            input_hashes=input_hashes_before,
            pointer_bytes=pointer_before,
        )
        pointer = {
            "schema_version": SCHEMA_POINTER,
            "bundle_path": str(destination),
            "bundle_manifest_path": str(destination / "bundle_manifest.json"),
            "bundle_manifest_hash": sha256_file(destination / "bundle_manifest.json"),
            **ids,
            "terminal_state": TERMINAL_AUTHORIZATION,
            "next_action": TERMINAL_NEXT_ACTION[TERMINAL_AUTHORIZATION],
            "published_at": utc_now(),
        }
        _run_failure_hook(
            failure_hook,
            "before_pointer_update",
            "bundle_publication_failed",
        )
        _assert_publication_sources_unchanged(
            paths,
            analysis,
            canon_hash=canon_before,
            input_hashes=input_hashes_before,
            pointer_bytes=pointer_before,
        )
        _trace_event(phase="current_pointer_update", status="started", output_path=str(paths.pointer))
        pointer_candidate = _json_bytes(pointer)
        try:
            pointer_installed = current_authority.compare_and_swap_current_pointer(
                paths.pointer,
                expected=pointer_before,
                replacement=pointer_candidate,
            )
        except current_authority.CurrentRelationalAuthorityError as error:
            raise PreparationBlocked(["current_pointer_changed"]) from error
        pointer_committed = True
        if pointer_installed:
            pointer_written = pointer_candidate
        _run_failure_hook(
            failure_hook,
            "pointer_update",
            "bundle_publication_failed",
        )
        _trace_event(phase="current_pointer_update", status="completed", output_path=str(paths.pointer))
        status = read_current_bundle_status(paths.local_root)
        _assert_published_candidate_is_current(
            status,
            destination=destination,
            ids=ids,
            terminal_state=TERMINAL_AUTHORIZATION,
            failure_reason="bundle_publication_failed",
        )
        _trace_event(phase="postpublication_resolution", status="completed", output_path=str(destination))
        return {
            "terminal_state": TERMINAL_AUTHORIZATION,
            "next_action": "AUTHORIZE_CURRENT_RELATIONAL_APPLY",
            "idempotent_noop": False,
            "bundle_path": str(destination),
            "ids": ids,
            "planning": status["planning"],
            "writes_performed": True,
            "canon_modified": False,
            "decisions_modified": False,
            "apply_executed": False,
        }
    except Exception as error:
        _trace_event(phase="bundle_publication", status="failed", reason_code=(error.reason_codes[0] if isinstance(error, PreparationBlocked) and error.reason_codes else "bundle_publication_failed"), error_type=type(error).__name__, error_message=str(error))
        if staging.exists():
            shutil.rmtree(staging)
        pointer_restored = _restore_pointer_if_owned(
            paths.pointer, before=pointer_before, written=pointer_written,
        )
        # Preserve every fully validated physical publication as recoverable
        # immutable evidence; cleanup cannot prove absence of future lineage
        # references from concurrent writers.
        if pointer_written is not None and not pointer_restored:
            reasons = (
                list(error.reason_codes)
                if isinstance(error, PreparationBlocked)
                else ["bundle_publication_failed"]
            )
            raise PreparationBlocked(
                [*reasons, "current_pointer_descendant_advanced"], str(error),
            ) from error
        if pointer_committed and pointer_written is None:
            reasons = (
                list(error.reason_codes)
                if isinstance(error, PreparationBlocked)
                else ["bundle_publication_failed"]
            )
            observed_reason = (
                "current_pointer_equivalent_committed"
                if _path_bytes(paths.pointer) == pointer_candidate
                else "current_pointer_descendant_advanced"
            )
            raise PreparationBlocked(
                [*reasons, observed_reason], str(error),
            ) from error
        raise
    finally:
        if safety_work is not None and safety_work.parent.exists() and not keep_safety_work:
            shutil.rmtree(safety_work.parent)


def read_current_bundle_status(local_root: Path) -> dict[str, Any]:
    reasons: list[str] = []
    try:
        authority = current_authority.resolve_current_relational_authority(local_root)
        pointer = authority["pointer"]
        bundle = authority["bundle_path"]
        manifest = authority["manifest"]
        canon = canon_snapshot(local_root)
        source = manifest.get("source_bindings") or {}
        if (source.get("canon") or {}).get("hash") != canon["hash"]:
            reasons.append("current_bundle_canon_stale")
        for name, item in source.items():
            if name == "canon":
                continue
            # A human-delta bundle carries every operational artifact inside
            # the immutable publication.  Its pipeline paths are provenance
            # (and may legitimately be replaced by the next review action),
            # never a second current authority.
            if manifest.get("terminal_state") in {
                TERMINAL_HUMAN, TERMINAL_REVIEW_COMPLETE,
            }:
                continue
            path = Path(str((item or {}).get("path") or ""))
            if name in producer_bindings() or (item or {}).get("currentness_role") == "provenance_only":
                continue
            if (
                name == "human_decisions"
                and manifest.get("terminal_state") == TERMINAL_HUMAN
                and (item or {}).get("mutable_for_human_delta_resume") is True
            ):
                continue
            if sha256_file(path) != (item or {}).get("sha256"):
                reasons.append(f"current_bundle_binding_stale:{name}")
        if manifest.get("authorization_present") is not False or manifest.get("apply_executed") is not False:
            reasons.append("current_bundle_must_remain_unauthorized_and_unexecuted")
        expected_fingerprints = manifest.get("producer_fingerprints") or {}
        for name, expected in expected_fingerprints.items():
            if name in producer_bindings() and expected != sha256_file(producer_bindings()[name]):
                reasons.append("producer_fingerprint_stale")
        authority_artifacts = authority.get("artifacts") or {}
        ready_path = authority_artifacts.get("ready_queue")
        effective_path = authority_artifacts.get("effective_decisions")
        technical_reviewable = (
            len(read_jsonl(ready_path)) if isinstance(ready_path, Path) else 0
        )
        effective_decision_covered = (
            len(read_jsonl(effective_path))
            if isinstance(effective_path, Path) else 0
        )
        if manifest.get("terminal_state") == TERMINAL_AUTHORIZATION:
            plan_item = (manifest.get("artifacts") or {}).get("apply_plan") or {}
            plan = read_json(bundle / str(plan_item.get("path") or ""))
            validate_plan_conservation(plan)
            planning = {
                "approved_candidate_representations": plan.get("approved_candidate_representations", 0),
                "planned_unique_relations": plan.get("planned_unique_relations", 0),
                "omitted_duplicate_representations": plan.get("omitted_planned_count", 0),
                "unaccounted_approved_representations": plan.get("unaccounted_approved_representations", 0),
                "conservation_valid": plan.get("conservation_valid") is True,
                "technical_reviewable": technical_reviewable,
                "effective_decision_covered": effective_decision_covered,
                "effective_pending": 0,
            }
        elif manifest.get("terminal_state") == TERMINAL_HUMAN:
            delta_item = (manifest.get("artifacts") or {}).get("pending_queue") or {}
            delta = read_json(bundle / str(delta_item.get("path") or ""))
            planning = {
                "pending_human_review": int(delta.get("pending") or 0),
                "planned_unique_relations": 0,
                "gate_g_status": "not_applicable_pending_human_review",
                "apply_plan_status": "not_applicable_pending_human_review",
                "rollback_snapshot_status": "not_applicable_pending_human_review",
                "technical_reviewable": technical_reviewable,
                "effective_decision_covered": effective_decision_covered,
                "effective_pending": int(delta.get("pending") or 0),
            }
        elif manifest.get("terminal_state") == TERMINAL_REVIEW_COMPLETE:
            receipts_path = authority_artifacts.get("review_receipts")
            planning = {
                "pending_human_review": 0,
                "technical_reviewable": technical_reviewable,
                "effective_decision_covered": effective_decision_covered,
                "effective_pending": 0,
                "review_receipts": len(read_jsonl(receipts_path))
                if isinstance(receipts_path, Path) else 0,
                "readiness_status": "pending_recomposition",
            }
        else:
            plan_item = (manifest.get("artifacts") or {}).get("apply_plan") or {}
            plan = read_json(bundle / str(plan_item.get("path") or ""))
            validate_plan_conservation(plan)
            planning = {
                "approved_candidate_representations": plan.get("approved_candidate_representations", 0),
                "planned_unique_relations": plan.get("planned_unique_relations", 0),
                "omitted_duplicate_representations": plan.get("omitted_planned_count", 0),
                "unaccounted_approved_representations": plan.get("unaccounted_approved_representations", 0),
                "conservation_valid": plan.get("conservation_valid") is True,
            }
        return {
            "valid": not reasons,
            "reason_codes": sorted(set(reasons)),
            "pointer": pointer,
            "manifest": manifest,
            "bundle_path": str(bundle),
            "planning": planning,
            "ids": {
                key: manifest.get(key)
                for key in (
                    "canon_generation_id", "relation_generation_id",
                    "review_state_id", "readiness_id",
                )
            },
            "terminal_state": manifest.get("terminal_state"),
            "next_action": manifest.get("next_action"),
        }
    except (OSError, ValueError, json.JSONDecodeError, PreparationBlocked, current_authority.CurrentRelationalAuthorityError) as error:
        if not reasons:
            reasons.extend(getattr(error, "reason_codes", ["current_bundle_invalid"]))
        return {"valid": False, "reason_codes": sorted(set(reasons))}


def _preview_decision_recomposition(paths: Paths) -> dict[str, Any]:
    """Build and validate a disposable successor without publishing any path."""
    work: Path | None = None
    try:
        work, staged_current, preservation = recompose_current_decision_authority(
            paths,
        )
        staged_paths = Paths(
            local_root=paths.local_root,
            current_dir=staged_current,
            audit_root=paths.audit_root,
            admission_current=paths.admission_current,
            generations=paths.generations,
            pointer=paths.pointer,
        )
        analysis = analyze(staged_paths)
        status = read_current_bundle_status(paths.local_root)
        reason_codes = ["review_decision_authority_recomposition_planned"]
        reason_codes.extend(status.get("reason_codes") or [])
        planning: dict[str, Any]
        ids = dict(analysis["ids"])
        if analysis["terminal_state"] == TERMINAL_AUTHORIZATION:
            gate_path = work / "preview_admission_gate.json"
            write_json(gate_path, analysis["gate_report"])
            plan = _plan_for_analysis(
                analysis, gate_path, analysis["inputs"]["human_decisions"],
            )
            ids["readiness_id"] = _readiness_identity(
                ids, plan, analysis["canon"],
            )
            planning = {
                "approved_candidate_representations": plan[
                    "approved_candidate_representations"
                ],
                "planned_unique_relations": plan["planned_unique_relations"],
                "omitted_duplicate_representations": plan[
                    "omitted_planned_count"
                ],
                "unaccounted_approved_representations": plan[
                    "unaccounted_approved_representations"
                ],
                "conservation_valid": plan["conservation_valid"],
            }
        else:
            ids["readiness_id"] = None
            planning = {
                "pending_human_review": len(analysis["pending_ids"]),
                "planned_unique_relations": 0,
            }
        return {
            "current_canon": {
                key: analysis["canon"][key] for key in ("hash", "records", "shards")
            },
            "detected_changes": {
                "canon_changed": "current_bundle_canon_stale" in reason_codes,
                "candidate_generation_current": True,
                "reconciliation_current": True,
                "current_relational_authority_stale_or_missing": True,
                "reason_codes": sorted(set(reason_codes)),
            },
            "execution_plan": {
                "reuse": [
                    "current_candidate_generation", "current_validation",
                    "current_reconciliation", "certified_review_receipts",
                ],
                "regenerate": [
                    "effective_decision_bindings", "decision_checkpoint",
                    "cross_generation_reconciliation", "admission_gate",
                    "governed_generation_bundle", "current_pointer",
                ],
            },
            "expected_artifacts": [
                "cross_generation_reconciliation", "decision_checkpoint",
                "review_receipt_lineage", "admission_gate", "gate_g",
                "apply_plan", "rollback_snapshot", "authorization_request",
                "bundle_manifest",
            ],
            "expected_terminal_state": analysis["terminal_state"],
            "next_action": (
                "AUTHORIZE_CURRENT_RELATIONAL_APPLY"
                if analysis["terminal_state"] == TERMINAL_AUTHORIZATION
                else "REVIEW_CURRENT_RELATIONAL_DELTA"
            ),
            "partition": analysis["gate_summary"],
            "review_coverage": analysis["review_coverage"],
            "planning": planning,
            "ids": ids,
            "decision_preservation": preservation,
            "reason_codes": sorted(set(reason_codes)),
            "writes_performed": False,
            "canon_modified": False,
            "decisions_modified": False,
            "authorization_created": False,
            "apply_executed": False,
        }
    finally:
        if work is not None and work.exists():
            shutil.rmtree(work)


def dry_run(paths: Paths) -> dict[str, Any]:
    try:
        analysis = analyze(paths)
    except PreparationBlocked as error:
        if error.reason_codes and set(error.reason_codes).issubset(
            DECISION_RECOMPOSITION_REASONS
        ):
            return _preview_decision_recomposition(paths)
        if error.reason_codes and set(error.reason_codes).issubset(
            REBUILDABLE_SOURCE_REASONS | {"candidate_generation_failed"}
        ):
            canon = canon_snapshot(paths.local_root)
            return {
                "current_canon": {
                    key: canon[key] for key in ("hash", "records", "shards")
                },
                "detected_changes": {
                    "canon_changed": "candidate_generation_stale" in error.reason_codes,
                    "candidate_generation_current": False,
                    "reason_codes": error.reason_codes,
                },
                "execution_plan": {
                    "reuse": [
                        "previous_relation_generation_as_reconciliation_source",
                        "previous_decision_checkpoint",
                        "historical_bundles",
                    ],
                    "regenerate": [
                        "candidates", "validation", "reconciliation",
                        "decision_preservation", "decision_checkpoint",
                        "pending_queue", "admission_gate",
                    ],
                },
                "expected_artifacts": [
                    "candidate_generation", "validation_report",
                    "cross_generation_reconciliation", "decision_checkpoint",
                    "human_delta", "admission_gate", "bundle_manifest",
                ],
                "expected_terminal_state": "RECOMPUTATION_PLANNED",
                "next_action": "EXECUTE_STAGED_RELATIONAL_RECOMPUTATION",
                "reason_codes": ["candidate_generation_stale_rebuild_planned"],
                "writes_performed": False,
                "canon_modified": False,
                "decisions_modified": False,
                "apply_executed": False,
            }
        raise
    if analysis["terminal_state"] == TERMINAL_HUMAN:
        return {
            "current_canon": {
                key: analysis["canon"][key] for key in ("hash", "records", "shards")
            },
            "detected_changes": {
                "canon_changed": False,
                "decisions_changed_only": True,
                "candidate_generation_current": True,
            },
            "execution_plan": analysis["execution_plan"],
            "expected_artifacts": [
                "cross_generation_reconciliation", "decision_checkpoint",
                "human_delta", "human_delta_inventory", "admission_gate",
                "bundle_manifest",
            ],
            "expected_terminal_state": TERMINAL_HUMAN,
            "partition": analysis["gate_summary"],
            "planning": {
                "pending_human_review": len(analysis["pending_ids"]),
                "planned_unique_relations": 0,
            },
            "ids": analysis["ids"] | {"readiness_id": None},
            "writes_performed": False,
            "canon_modified": False,
            "decisions_modified": False,
            "apply_executed": False,
        }
    plan = _plan_for_analysis(
        analysis,
        paths.admission_current / "admission_gate_dry_run.json",
        analysis["inputs"]["human_decisions"],
    )
    return {
        "current_canon": {
            key: analysis["canon"][key] for key in ("hash", "records", "shards")
        },
        "detected_changes": {
            "canon_changed": False,
            "decisions_changed_only": False,
            "historical_operational_bundle_stale": True,
        },
        "execution_plan": analysis["execution_plan"],
        "expected_artifacts": [
            "cross_generation_reconciliation", "decision_checkpoint", "human_delta",
            "admission_gate", "gate_g", "apply_plan", "rollback_snapshot",
            "authorization_request", "bundle_manifest",
        ],
        "expected_terminal_state": analysis["terminal_state"],
        "partition": analysis["gate_summary"],
        "planning": {
            "approved_candidate_representations": plan["approved_candidate_representations"],
            "planned_unique_relations": plan["planned_unique_relations"],
            "omitted_duplicate_representations": plan["omitted_planned_count"],
            "unaccounted_approved_representations": plan["unaccounted_approved_representations"],
            "conservation_valid": plan["conservation_valid"],
        },
        "ids": analysis["ids"],
        "writes_performed": False,
        "canon_modified": False,
        "decisions_modified": False,
        "apply_executed": False,
    }


def compact_output(payload: dict[str, Any]) -> str:
    ids = payload.get("ids") or {}
    plan = payload.get("planning") or {}
    detected = payload.get("detected_changes") or {}
    rebuild_steps = payload.get("rebuild_steps") or []
    reason_codes = payload.get("reason_codes") or []
    coverage = payload.get("review_coverage") or {}
    partition = payload.get("partition") or {}
    technical_reviewable = coverage.get(
        "technical_reviewable", partition.get("total_evaluated", "n/a")
    )
    effective_covered = coverage.get("effective_decision_covered", "n/a")
    effective_pending = coverage.get(
        "effective_pending", partition.get("awaiting_human_review", "n/a")
    )
    blocked = payload.get("terminal_state") == TERMINAL_BLOCKED
    lines = [
        f"Generación canónica: {ids.get('canon_generation_id', 'n/a')}",
        f"Generación relacional: {ids.get('relation_generation_id', 'n/a')}",
        f"Estado de revisión: {ids.get('review_state_id', 'n/a')}",
        "Cambios detectados:",
        (
            "- canon o generación candidata stale"
            if detected.get("candidate_generation_current") is False
            else "- autoridad generacional stale o ausente; recomposición decisional requerida"
            if detected.get("current_relational_authority_stale_or_missing")
            or detected.get("current_relational_authority_stale")
            else "- ninguno; hashes y bindings semánticos vigentes"
        ),
        "Pasos ejecutados:",
        *(
            [f"- {step.replace('_', ' ')}" for step in rebuild_steps]
            if rebuild_steps
            else [
                "- ninguno (noop idempotente)"
                if payload.get("idempotent_noop")
                else "- dry-run/preflight: recomposición staged planificada"
                if payload.get("terminal_state") == "RECOMPUTATION_PLANNED"
                or "review_decision_authority_recomposition_planned" in reason_codes
                else "- no ejecutado: bloqueo causal"
                if blocked
                else "- ninguno (consulta de estado)"
                if payload.get("writes_performed") is not True
                else "- preparación current"
            ]
        ),
        "Decisiones preservadas: sin modificar autoridad productiva",
        f"Cola técnica reviewable: {technical_reviewable}",
        f"Cobertura efectiva de decisiones: {effective_covered}",
        f"Delta humano efectivo pendiente: {effective_pending}",
        f"Gate: {payload.get('terminal_state')}",
        f"Plan: {plan.get('planned_unique_relations', 0)} relaciones únicas",
        f"Snapshot: {'ready' if payload.get('terminal_state') == TERMINAL_AUTHORIZATION else 'no preparado'}",
        f"Estado terminal: {payload.get('terminal_state')}",
        f"Siguiente acción: {payload.get('next_action', 'n/a')}",
        *(["Reason-codes:", *(f"- {reason}" for reason in reason_codes)] if reason_codes else []),
        "Canon modificado: no",
        "Decisiones modificadas: no",
        "Apply ejecutado: no",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare the current relational generation without authorization or apply")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--status", action="store_true")
    parser.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--keep-safety-work", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = Paths.from_local_root(args.local_root)
    try:
        if args.status:
            payload = read_current_bundle_status(paths.local_root)
            code = 0 if payload.get("valid") is True else 2
        elif args.dry_run:
            payload = dry_run(paths)
            payload["terminal_state"] = payload.pop("expected_terminal_state")
            payload.setdefault(
                "next_action",
                "AUTHORIZE_CURRENT_RELATIONAL_APPLY"
                if payload["terminal_state"] == TERMINAL_AUTHORIZATION
                else "REVIEW_CURRENT_RELATIONAL_DELTA",
            )
            code = 0
        else:
            payload = execute(paths, keep_safety_work=args.keep_safety_work)
            code = 0
    except PreparationBlocked as error:
        payload = {
            "terminal_state": TERMINAL_BLOCKED,
            "reason_codes": error.reason_codes,
            "detail": error.detail,
            "writes_performed": False,
            "canon_modified": False,
            "decisions_modified": False,
            "apply_executed": False,
        }
        code = 3
    if args.compact:
        print(compact_output(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
