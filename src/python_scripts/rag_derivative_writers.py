"""Write boundary for the authoritative derivative orchestrator.

This is intentionally a supporting guard, not a second producer.  Only
``derive_layers.py`` may invoke productive writers after this check passes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import shutil
from datetime import datetime, timezone


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
PRODUCTIVE_DERIVATIVE_ROOTS = (
    REPO_ROOT / "data" / "out" / "local" / "enriched",
    REPO_ROOT / "data" / "out" / "local" / "ai",
    REPO_ROOT / "data" / "out" / "local" / "microsoft_copilot",
    REPO_ROOT / "data" / "out" / "local" / "reverse_html",
)
CANON_ROOT = REPO_ROOT / "data" / "out" / "local"
EVIDENCE_ROOTS = (
    CANON_ROOT / "pipeline",
    CANON_ROOT / "audit",
)
PRODUCTIVE_FAMILIES = {
    "enriched": REPO_ROOT / "data" / "out" / "local" / "enriched",
    "ai": REPO_ROOT / "data" / "out" / "local" / "ai",
    "microsoft_copilot": REPO_ROOT / "data" / "out" / "local" / "microsoft_copilot",
}


class ProductiveWriteBlocked(RuntimeError):
    """Raised before any productive derivative write is attempted."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def require_nonproductive_evidence_target(path: Path | str) -> Path:
    """Keep supporting report/profile helpers out of live derivative families."""

    target = Path(path).resolve()
    if any(
        _is_within(target, root) or _is_within(root, target)
        for root in PRODUCTIVE_DERIVATIVE_ROOTS
    ):
        raise ProductiveWriteBlocked(f"supporting evidence target overlaps productive derivatives: {target}")
    if target == CANON_ROOT.resolve() or _is_within(CANON_ROOT, target):
        raise ProductiveWriteBlocked(f"supporting evidence target overlaps canon root: {target}")
    if _is_within(target, REPO_ROOT) and not any(_is_within(target, root) for root in EVIDENCE_ROOTS):
        raise ProductiveWriteBlocked(f"supporting evidence target is outside governed evidence roots: {target}")
    return target


def require_productive_write_permission(preflight: dict[str, Any]) -> None:
    if preflight.get("productive_write_allowed") is True:
        return
    reasons = preflight.get("blocking_reasons") or ["productive_write_not_authorized"]
    raise ProductiveWriteBlocked("productive derivative write blocked: " + ", ".join(map(str, reasons)))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _family_roots(productive_families: Mapping[str, Path | str] | None = None) -> dict[str, Path]:
    """Resolve an explicit target map without changing the production default."""

    source = productive_families or PRODUCTIVE_FAMILIES
    return {str(name): Path(path).resolve() for name, path in source.items()}


def _tree_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    return [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(path for path in root.rglob("*") if path.is_file())
    ]


def snapshot_productive_derivatives(
    snapshot_root: Path | str,
    *,
    productive_families: Mapping[str, Path | str] | None = None,
    session_id: str = "S0173",
) -> dict[str, Any]:
    """Create a persistent, hash-addressed rollback snapshot of live families."""

    target = require_nonproductive_evidence_target(snapshot_root)
    if target.exists() and any(target.iterdir()):
        raise ProductiveWriteBlocked(f"rollback snapshot is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    family_roots = _family_roots(productive_families)
    for family, source in family_roots.items():
        destination = target / family
        if source.exists():
            shutil.copytree(source, destination)
            for path in sorted(p for p in destination.rglob("*") if p.is_file()):
                files.append(
                    {
                        "artifact_family": family,
                        "relative_path": path.relative_to(destination).as_posix(),
                        "sha256": _sha256_file(path),
                        "size_bytes": path.stat().st_size,
                    }
                )
        else:
            destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "rollback-manifest/v1",
        "created_at": _utc_now(),
        "snapshot_root": str(target),
        "producer": "derive_layers.py",
        "session_id": session_id,
        "families": sorted(family_roots),
        "files": files,
        "restorable": True,
    }
    (target / "rollback_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_rollback_snapshot(
    snapshot_root: Path | str,
    manifest: dict[str, Any],
    *,
    productive_families: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    target = Path(snapshot_root).resolve()
    mismatches: list[str] = []
    expected_by_family: dict[str, set[str]] = {}
    for entry in manifest.get("files", []):
        family = entry["artifact_family"]
        relative_path = entry["relative_path"]
        expected_by_family.setdefault(family, set()).add(relative_path)
        path = target / family / relative_path
        if not path.exists() or _sha256_file(path) != entry.get("sha256"):
            mismatches.append(str(path))
    for family in manifest.get("families", []):
        family_root = target / family
        observed = {
            path.relative_to(family_root).as_posix()
            for path in family_root.rglob("*")
            if path.is_file()
        } if family_root.exists() else set()
        unexpected = observed - expected_by_family.get(family, set())
        mismatches.extend(str(family_root / relative) for relative in sorted(unexpected))
    return {
        "schema_version": "rollback-verification-report/v1",
        "snapshot_root": str(target),
        "files_checked": len(manifest.get("files", [])),
        "mismatches": mismatches,
        "restored_manifest_matches": not mismatches,
    }


def verify_productive_state_matches_snapshot(
    snapshot_root: Path | str,
    *,
    productive_families: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    """Compare live family trees with their pre-write snapshot hashes."""

    snapshot = Path(snapshot_root).resolve()
    manifest_path = snapshot / "rollback_manifest.json"
    if not manifest_path.exists():
        return {"matches": False, "reason": "rollback_manifest_missing", "mismatches": []}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    family_roots = _family_roots(productive_families)
    expected = {
        (entry.get("artifact_family"), entry.get("relative_path")): entry.get("sha256")
        for entry in manifest.get("files", [])
    }
    observed: dict[tuple[str, str], str] = {}
    for family, root in family_roots.items():
        for entry in _tree_manifest(root):
            observed[(family, entry["relative_path"])] = entry["sha256"]
    mismatches = sorted(
        f"{family}/{relative}"
        for family, relative in set(expected) | set(observed)
        if expected.get((family, relative)) != observed.get((family, relative))
    )
    return {"matches": not mismatches, "reason": None if not mismatches else "live_state_changed", "mismatches": mismatches}


def _write_tree_to_target(source: Path, target: Path, transaction_root: Path) -> dict[str, Any]:
    if not source.is_dir():
        raise ProductiveWriteBlocked(f"staging family is missing: {source.name}")
    temporary = transaction_root / source.name
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(source, temporary)
    before_exists = target.exists()
    before_files = _tree_manifest(target) if before_exists else []
    if target.exists():
        shutil.rmtree(target)
    temporary.replace(target)
    return {
        "family": source.name,
        "operation": "replace" if before_exists else "create",
        "before_files": before_files,
        "after_files": _tree_manifest(target),
    }


def _restore_family_from_snapshot(target: Path, snapshot: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    if snapshot.exists():
        shutil.copytree(snapshot, target)


def promote_staging_transaction(
    *,
    staging_root: Path | str,
    rollback_root: Path | str,
    authorization: dict[str, Any],
    planned_families: list[str],
    transaction_journal: Path | str,
    receipt_path: Path | str,
    expected_session_id: str = "S0173",
    required_authorization_phrase: str | None = "REGENERATE RAG SAFE S0173",
    staging_manifest_path: Path | str | None = None,
    staging_manifest_hash: str | None = None,
    productive_families: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    """Promote only authorized families; never callable without exact human auth.

    The caller must have already validated plan, staging, gate and equivalence
    hashes.  This function performs the final filesystem transaction and rolls
    back from the persistent snapshot on any partial failure.
    """

    if authorization.get("session_id") not in {None, expected_session_id}:
        raise ProductiveWriteBlocked(f"authorization is not scoped to {expected_session_id}")
    if not authorization.get("authorization_phrase"):
        if required_authorization_phrase is not None:
            raise ProductiveWriteBlocked(f"exact {expected_session_id} authorization phrase is required")
        raise ProductiveWriteBlocked("an explicit authorization phrase is required")
    if required_authorization_phrase is not None and authorization.get("authorization_phrase") != required_authorization_phrase:
        raise ProductiveWriteBlocked(f"exact {expected_session_id} authorization phrase is required")
    if authorization.get("authorized_by") != "human_operator":
        raise ProductiveWriteBlocked("productive authorization must come from human_operator")
    family_roots = _family_roots(productive_families)
    invalid = sorted(set(planned_families) - set(family_roots))
    if invalid:
        raise ProductiveWriteBlocked("authorization contains unplanned productive families: " + ", ".join(invalid))
    staging = Path(staging_root).resolve()
    rollback = Path(rollback_root).resolve()
    journal = require_nonproductive_evidence_target(transaction_journal)
    receipt = require_nonproductive_evidence_target(receipt_path)
    rollback_manifest_path = rollback / "rollback_manifest.json"
    if not rollback_manifest_path.exists():
        raise ProductiveWriteBlocked("rollback manifest is required before promotion")
    rollback_manifest = json.loads(rollback_manifest_path.read_text(encoding="utf-8"))
    rollback_check = verify_rollback_snapshot(rollback, rollback_manifest, productive_families=family_roots)
    if not rollback_check["restored_manifest_matches"]:
        raise ProductiveWriteBlocked("rollback snapshot failed verification")
    manifest_hash_observed = None
    if staging_manifest_path is not None:
        manifest_path = Path(staging_manifest_path).resolve()
        if not manifest_path.exists():
            raise ProductiveWriteBlocked("staging manifest is required before promotion")
        manifest_hash_observed = _sha256_file(manifest_path)
        if staging_manifest_hash and manifest_hash_observed != staging_manifest_hash:
            raise ProductiveWriteBlocked("staging manifest hash changed before promotion")
        authorized_manifest_hash = authorization.get("staging_manifest_hash")
        if authorized_manifest_hash and authorized_manifest_hash != manifest_hash_observed:
            raise ProductiveWriteBlocked("authorization is not bound to the current staging manifest")
    planned = list(dict.fromkeys(planned_families))
    scope = authorization.get("planned_families")
    if scope is not None and sorted(scope) != sorted(planned):
        raise ProductiveWriteBlocked("authorization scope does not match planned productive families")
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("", encoding="utf-8")
    transaction_root = staging.parent / f".{staging.name}.transaction"
    if transaction_root.exists():
        shutil.rmtree(transaction_root)
    transaction_root.mkdir(parents=True, exist_ok=True)
    completed: list[str] = []
    operations: list[dict[str, Any]] = []
    try:
        with journal.open("a", encoding="utf-8") as handle:
            for family in planned:
                source = staging / family
                target = family_roots[family]
                if not source.exists():
                    raise ProductiveWriteBlocked(f"staging family is missing: {family}")
                target.parent.mkdir(parents=True, exist_ok=True)
                # Mark the family before the replace so a failure after target
                # removal still restores the exact pre-write snapshot.
                completed.append(family)
                operation = _write_tree_to_target(source, target, transaction_root)
                operations.append(operation)
                handle.write(json.dumps({"at": _utc_now(), "event": "family_promoted", "family": family, "operation": operation["operation"]}) + "\n")
        write_manifest = {
            "schema_version": "productive-write-manifest/v1",
            "session_id": expected_session_id,
            "producer": "derive_layers.py",
            "writer": "rag_derivative_writers.py",
            "staging_root": str(staging),
            "staging_manifest_hash": manifest_hash_observed,
            "families": completed,
            "operations": operations,
            "deletion_policy": "none",
            "canon_modified": False,
            "reverse_html_modified": False,
        }
        receipt_payload = {
            "schema_version": "productive-regeneration-receipt/v1",
            "status": "promotion_completed",
            "session_id": expected_session_id,
            "productive_regeneration_executed": True,
            "productive_promotion_executed": True,
            "transaction_journal": str(journal),
            "rollback_snapshot": str(rollback),
            "families": completed,
            "write_manifest": write_manifest,
        }
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(receipt_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(transaction_root, ignore_errors=True)
        return receipt_payload
    except Exception:
        for family in reversed(completed):
            target = family_roots[family]
            snapshot = rollback / family
            _restore_family_from_snapshot(target, snapshot)
        shutil.rmtree(transaction_root, ignore_errors=True)
        raise


def rollback_productive_transaction(
    *,
    rollback_root: Path | str,
    planned_families: list[str],
    transaction_journal: Path | str,
    verification_report_path: Path | str,
    productive_families: Mapping[str, Path | str] | None = None,
    expected_session_id: str = "S0174",
) -> dict[str, Any]:
    """Restore the manifest-scoped productive families and verify them from disk."""

    family_roots = _family_roots(productive_families)
    invalid = sorted(set(planned_families) - set(family_roots))
    if invalid:
        raise ProductiveWriteBlocked("rollback contains unplanned productive families: " + ", ".join(invalid))
    rollback = Path(rollback_root).resolve()
    manifest_path = rollback / "rollback_manifest.json"
    if not manifest_path.exists():
        raise ProductiveWriteBlocked("rollback manifest is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("session_id") not in {None, expected_session_id}:
        raise ProductiveWriteBlocked("rollback snapshot is not scoped to this session")
    before_check = verify_rollback_snapshot(rollback, manifest, productive_families=family_roots)
    if not before_check["restored_manifest_matches"]:
        raise ProductiveWriteBlocked("rollback snapshot failed verification")
    journal = require_nonproductive_evidence_target(transaction_journal)
    report_path = require_nonproductive_evidence_target(verification_report_path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    restored: list[dict[str, Any]] = []
    with journal.open("a", encoding="utf-8") as handle:
        for family in planned_families:
            target = family_roots[family]
            snapshot = rollback / family
            _restore_family_from_snapshot(target, snapshot)
            observed = _tree_manifest(target)
            expected = sorted(
                {
                    "relative_path": entry.get("relative_path"),
                    "sha256": entry.get("sha256"),
                    "size_bytes": entry.get("size_bytes"),
                }
                for entry in manifest.get("files", [])
                if entry.get("artifact_family") == family
            )
            restored.append({
                "family": family,
                "expected_files": expected,
                "observed_files": observed,
                "matches": expected == observed,
            })
            handle.write(json.dumps({"at": _utc_now(), "event": "family_restored", "family": family}) + "\n")
    report = {
        "schema_version": "productive-rollback-report/v1",
        "session_id": expected_session_id,
        "status": "pass" if all(item["matches"] for item in restored) else "blocked",
        "blocking": not all(item["matches"] for item in restored),
        "rollback_execution": "pass",
        "rollback_verification": "pass" if all(item["matches"] for item in restored) else "blocked",
        "families": restored,
        "canon_modified": False,
        "reverse_html_modified": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report
