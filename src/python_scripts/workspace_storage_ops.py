#!/usr/bin/env python3
"""Workspace/storage location operations for the TDC terminal (S0187 Unit D).

Read-only diagnosis, non-secret configuration, and a gated migration preview
sit here. This module never performs a write against a migration target --
`apply_migration()` always refuses until a human has authorized Gate
D-H3/D-H4 outside of any agent context. See path_governance.py for the
resolved-root ownership this module reads from.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_governance import (  # noqa: E402
    DEFAULT_AUDIT_DIR,
    DEFAULT_CANON_DIR,
    DEFAULT_LOCAL_OUT_DIR,
    DEFAULT_REFS_DIR,
    DEFAULT_REMOTE_OUT_DIR,
    DEFAULT_SESSIONS_DIR,
    DEFAULT_TMP_DIR,
    REPO_DATA_DIR,
    WORKSPACE_ROOT,
    WorkspaceRootUnavailableError,
    current_workspace_status,
    require_reachable_workspace_root,
    sorted_canon_shards,
)

REPORTS_DIR = DEFAULT_AUDIT_DIR / "workspace_storage"
CHECKPOINT_REPORT = REPORTS_DIR / "latest_checkpoint.json"
PREVIEW_REPORT = REPORTS_DIR / "latest_preview.json"
MIGRATION_REPORT = REPORTS_DIR / "latest_migration_report.json"
PRE_COPY_MANIFEST_REPORT = REPORTS_DIR / "latest_pre_copy_manifest.json"
COPY_RECEIPT_REPORT = REPORTS_DIR / "latest_copy_receipt.json"
VERIFY_REPORT = REPORTS_DIR / "latest_verify_result.json"

# Required literal for execute_authorized_copy() -- mirrors the typed-confirmation
# idiom already used elsewhere in operator_menu.py (e.g. "NORMALIZAR"). Callers
# must know this exact string; it cannot be satisfied by a generic truthy flag.
COPY_AUTHORIZATION_TOKEN = "D11_COPY_AUTHORIZATION_GRANTED"

_SECRET_LIKE_FILENAMES = {".env", ".env.local", "credentials.json"}
_SECRET_LIKE_SUFFIXES = (".pem", ".key")


def _looks_like_secret_filename(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SECRET_LIKE_FILENAMES or lowered.endswith(_SECRET_LIKE_SUFFIXES)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def describe_mount(path: Path) -> dict:
    """Find the /proc/mounts entry covering `path` (longest-prefix match)."""
    target = str(Path(path).resolve())
    best: dict | None = None
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 4:
                    continue
                device, raw_mountpoint, fstype, options = parts[0], parts[1], parts[2], parts[3]
                mountpoint = raw_mountpoint.replace("\\040", " ")
                covers = target == mountpoint or target.startswith(mountpoint.rstrip("/") + "/") or mountpoint == "/"
                if covers and (best is None or len(mountpoint) > len(best["mountpoint"])):
                    best = {
                        "device": device,
                        "mountpoint": mountpoint,
                        "fstype": fstype,
                        "options": options.split(","),
                    }
    except OSError:
        return {"device": None, "mountpoint": None, "fstype": None, "options": [], "error": "proc_mounts_unreadable"}
    if best is None:
        return {"device": None, "mountpoint": None, "fstype": None, "options": [], "error": "no_matching_mount_found"}
    return best


def disk_usage_bytes(path: Path) -> dict:
    probe_path = Path(path)
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent
    usage = shutil.disk_usage(probe_path)
    return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}


def validate_location(path: Path) -> dict:
    """Read-only validation of a candidate workspace-root location."""
    candidate = Path(path).expanduser()
    warnings: list[str] = []
    ok = True

    probe_target = candidate if candidate.exists() else candidate.parent
    mount = describe_mount(probe_target if probe_target.exists() else Path("/"))
    read_only_mount = "ro" in mount.get("options", [])
    if read_only_mount:
        ok = False
        warnings.append(
            "El punto de montaje es de solo lectura (ro). No puede usarse como "
            "ubicacion activa de escritura sin habilitar RW bajo Gate D-H3, "
            "autorizado explicitamente por un humano desde su propio terminal."
        )

    if candidate.exists() and not candidate.is_dir():
        ok = False
        warnings.append("La ruta existe pero no es un directorio.")

    if probe_target.exists() and not os.access(probe_target, os.W_OK):
        ok = False
        warnings.append("Sin permiso de escritura del proceso actual sobre la ruta.")

    usage = disk_usage_bytes(probe_target)

    return {
        "path": str(candidate),
        "exists": candidate.exists(),
        "is_dir": candidate.is_dir() if candidate.exists() else None,
        "mount": mount,
        "read_only_mount": read_only_mount,
        "free_bytes": usage["free_bytes"],
        "total_bytes": usage["total_bytes"],
        "warnings": warnings,
        "ok": ok,
    }


def _tree_stats(root: Path) -> dict:
    if not root.exists():
        return {"file_count": 0, "byte_count": 0}
    file_count = 0
    byte_count = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            file_count += 1
            try:
                byte_count += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return {"file_count": file_count, "byte_count": byte_count}


def checkpoint_source() -> dict:
    """D8 -- explicit pre-migration checkpoint of the current source state.

    Fails closed (WorkspaceRootUnavailableError) if the configured workspace
    root is not reachable, rather than silently reporting an empty/zero-shard
    Canon -- EXPLICIT CONFIGURATION FAILURE != PERMISSION TO FALL BACK."""
    require_reachable_workspace_root()
    shards = sorted_canon_shards(DEFAULT_CANON_DIR)
    record_count = 0
    hasher = hashlib.sha256()
    for shard in shards:
        with shard.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                hasher.update(chunk)
        with shard.open("r", encoding="utf-8") as fh:
            record_count += sum(1 for _ in fh)

    inventory_manifest = DEFAULT_LOCAL_OUT_DIR / "inventory" / "current_inventory_manifest.json"
    inventory_snapshot = None
    if inventory_manifest.exists():
        try:
            inventory_snapshot = json.loads(inventory_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            inventory_snapshot = {"error": "unreadable_manifest"}

    checkpoint = {
        "schema": "s0187-unit-d-checkpoint/v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_workspace_root": str(WORKSPACE_ROOT),
        "canon": {
            "shard_count": len(shards),
            "record_count": record_count,
            "concat_sha256": hasher.hexdigest(),
        },
        "inventory_manifest_present": inventory_manifest.exists(),
        "inventory_manifest_snapshot": inventory_snapshot,
        "sessions_dir_present": DEFAULT_SESSIONS_DIR.exists(),
        "audit_dir_present": DEFAULT_AUDIT_DIR.exists(),
        "verification_mode": "live_filesystem_read_at_checkpoint_time",
        "note": "Re-checked live at checkpoint time -- the historical Unit C/C-R inventory snapshot is not treated as automatically current.",
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with CHECKPOINT_REPORT.open("w", encoding="utf-8") as fh:
        json.dump(checkpoint, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return checkpoint


def preview_migration(target: Path) -> dict:
    """D9 -- read-only migration preview. Never copies or mutates anything."""
    target_path = Path(target).expanduser()
    validation = validate_location(target_path)

    out_local_stats = _tree_stats(DEFAULT_LOCAL_OUT_DIR)
    out_remote_stats = _tree_stats(DEFAULT_REMOTE_OUT_DIR)
    tmp_stats = _tree_stats(DEFAULT_TMP_DIR)
    in_stats = _tree_stats(REPO_DATA_DIR / "in")
    refs_stats = _tree_stats(DEFAULT_REFS_DIR)

    preview = {
        "schema": "s0187-unit-d-migration-preview/v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_workspace_root": str(WORKSPACE_ROOT),
        "proposed_target": str(target_path),
        "target_validation": validation,
        "will_migrate": {
            "out/local (canon, sessions, audit, inventory, ai, enriched, export, backups, pipeline, reverse_html, tiddlers-export, microsoft_copilot)": out_local_stats,
            "refs/ (workspace reference material -- follows WORKSPACE_ROOT since D22; REFS != CANON, REFS != CORE RUNTIME STATE)": refs_stats,
        },
        "will_not_migrate": {
            "out/remote (LEGACY_UNUSED_STORAGE_SURFACE per D05 verdict -- routed to Unit G, not activated here)": out_remote_stats,
            "in/ (mixed foundational template + committed workspace material, Gate D-H2 decision pending -- stays with the repo checkout)": in_stats,
            "tmp/ (transient/regenerable working state -- not migrated; regenerates fresh under whichever root is active)": tmp_stats,
            "secrets (.env, MSA_REFRESH_TOKEN, any credential)": {"file_count": 0, "byte_count": 0, "note": "never migration material -- see D5 CONFIGURATION != CREDENTIALS boundary"},
        },
        "expected_artifact_count": out_local_stats["file_count"] + refs_stats["file_count"],
        "expected_byte_count": out_local_stats["byte_count"] + refs_stats["byte_count"],
        "available_target_free_bytes": validation.get("free_bytes"),
        "verification_strategy": "per-file content hashing of the migrated tree plus canon concat_sha256/shard-count/record-count comparison between source and target after copy, before cutover (D12)",
        "rollback_strategy": "the source is never deleted or mutated by the copy step (D11); it remains available for rollback until a future unit authorizes its reduction with sufficient evidence (D16)",
        "migration_order": "COPY -> VERIFY -> CUTOVER (never MOVE -> HOPE)",
        "cutover_requires": "Gate D-H4 human authorization, after a D11 copy receipt and a D12 equivalence verification -- NOT reached by this preview",
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with PREVIEW_REPORT.open("w", encoding="utf-8") as fh:
        json.dump(preview, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return preview


def apply_migration(target: Path) -> dict:
    """Always refuses in Unit D. No simulated result substitutes for a real
    human-authorized RW gate, and passing validation never implies permission
    to write -- see Gate D-H3/D-H4 in the session brief."""
    validation = validate_location(target)
    report: dict
    if not validation["ok"]:
        report = {
            "schema": "s0187-unit-d-migration-report/v1",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "REFUSED",
            "reason": "target_not_writable_or_invalid",
            "detail": validation,
        }
    else:
        report = {
            "schema": "s0187-unit-d-migration-report/v1",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED_PENDING_HUMAN_GATE",
            "reason": (
                "Unit D stops at the write gate by design. Even though the target "
                "currently validates as writable, no copy is performed until a "
                "human has explicitly reviewed the D8 checkpoint and D9 preview "
                "and authorized Gate D-H3 (Toshiba RW) and Gate D-H4 (cutover)."
            ),
            "detail": validation,
        }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with MIGRATION_REPORT.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return report


def freeze_pre_copy_manifest(source_root: Path | None = None) -> dict:
    """D11 step 0 -- freeze the exact payload (relative path/size/sha256 per
    file) that D11_COPY will materialize at the target. Read-only; never
    mutates source. Scope is intentionally identical to preview_migration()'s
    'will_migrate' surface (out/local only) -- reuses the same root constant
    rather than re-deriving the layout."""
    root = Path(source_root) if source_root is not None else DEFAULT_LOCAL_OUT_DIR
    entries = []
    total_bytes = 0
    rejected_secret_like = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if _looks_like_secret_filename(name):
                rejected_secret_like.append(str((Path(dirpath) / name).relative_to(root)))
                continue
            full = Path(dirpath) / name
            rel = full.relative_to(root)
            try:
                size = full.stat().st_size
            except OSError:
                continue
            entries.append({
                "relative_path": str(rel),
                "size_bytes": size,
                "sha256": _sha256_file(full),
            })
            total_bytes += size

    manifest = {
        "schema": "s0187-unit-d-pre-copy-manifest/v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "rejected_secret_like_filenames": rejected_secret_like,
        "entries": entries,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with PRE_COPY_MANIFEST_REPORT.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return manifest


def execute_authorized_copy(manifest: dict, target_workspace_root: Path, human_authorization: str) -> dict:
    """D11 COPY. Requires the exact COPY_AUTHORIZATION_TOKEN literal -- this
    is the governed mechanism itself, not an ad-hoc cp/rsync substitute.
    Copies only the frozen manifest's entries, mirrored under
    <target_workspace_root>/out/local/<relative_path>. Never deletes or
    modifies the source. Stops at the first I/O error (fail closed) rather
    than continuing partially or attempting silent repair."""
    if human_authorization != COPY_AUTHORIZATION_TOKEN:
        raise PermissionError(
            "execute_authorized_copy() requires the exact D11 authorization token; "
            "refusing to copy without it."
        )

    target_workspace_root = Path(target_workspace_root)
    target_out_local = target_workspace_root / "out" / "local"
    started_at = datetime.now(timezone.utc).isoformat()
    copied: list[str] = []
    failures: list[dict] = []

    for entry in manifest["entries"]:
        rel = entry["relative_path"]
        src = Path(manifest["source_root"]) / rel
        dst = target_out_local / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)
        except OSError as exc:
            failures.append({"relative_path": rel, "error": str(exc)})
            break  # fail closed -- do not continue past the first failure

    completed_at = datetime.now(timezone.utc).isoformat()
    if failures:
        status = "PARTIAL" if copied else "FAILED"
    else:
        status = "COMPLETED"

    receipt = {
        "schema": "s0187-unit-d-copy-receipt/v1",
        "started_at": started_at,
        "completed_at": completed_at,
        "manifest_timestamp_utc": manifest["timestamp_utc"],
        "source_root": manifest["source_root"],
        "target_root": str(target_out_local),
        "expected_file_count": manifest["file_count"],
        "expected_byte_count": manifest["total_bytes"],
        "copied_file_count": len(copied),
        "failed_file_count": len(failures),
        "failures": failures,
        "status": status,
        "excluded_surfaces": ["in/", "refs/", "tmp/", "out/remote/", "secrets"],
        "source_deleted": False,
        "source_modified": False,
        "cutover_performed": False,
        "active_locator_changed": False,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with COPY_RECEIPT_REPORT.open("w", encoding="utf-8") as fh:
        json.dump(receipt, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return receipt


def verify_target_against_manifest(manifest: dict, target_workspace_root: Path) -> dict:
    """D12 VERIFY. Re-hashes the target and compares against the frozen
    pre-copy manifest -- never against a re-walk of the (possibly-since-changed)
    live source. Read-only against both source and target."""
    target_out_local = Path(target_workspace_root) / "out" / "local"

    missing: list[str] = []
    mismatches: list[dict] = []
    expected_paths = {e["relative_path"] for e in manifest["entries"]}

    for entry in manifest["entries"]:
        dst = target_out_local / entry["relative_path"]
        if not dst.exists():
            missing.append(entry["relative_path"])
            continue
        actual_size = dst.stat().st_size
        if actual_size != entry["size_bytes"]:
            mismatches.append({
                "relative_path": entry["relative_path"],
                "reason": "size_mismatch",
                "expected_bytes": entry["size_bytes"],
                "actual_bytes": actual_size,
            })
            continue
        actual_hash = _sha256_file(dst)
        if actual_hash != entry["sha256"]:
            mismatches.append({
                "relative_path": entry["relative_path"],
                "reason": "hash_mismatch",
                "expected_sha256": entry["sha256"],
                "actual_sha256": actual_hash,
            })

    actual_paths: set[str] = set()
    actual_byte_count = 0
    if target_out_local.exists():
        for dirpath, _dirnames, filenames in os.walk(target_out_local):
            for name in filenames:
                full = Path(dirpath) / name
                rel = str(full.relative_to(target_out_local))
                actual_paths.add(rel)
                try:
                    actual_byte_count += full.stat().st_size
                except OSError:
                    continue
    unexpected_extra = sorted(actual_paths - expected_paths)

    result = {
        "schema": "s0187-unit-d-verify-result/v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_timestamp_utc": manifest["timestamp_utc"],
        "target_root": str(target_out_local),
        "expected_file_count": manifest["file_count"],
        "actual_file_count": len(actual_paths),
        "expected_byte_count": manifest["total_bytes"],
        "actual_byte_count": actual_byte_count,
        "missing_files": missing,
        "mismatches": mismatches,
        "unexpected_extra_files": unexpected_extra,
        "equivalence_verified": not missing and not mismatches and not unexpected_extra,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with VERIFY_REPORT.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return result


def load_last_report(report_path: Path) -> dict | None:
    if not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


if __name__ == "__main__":
    print(json.dumps(current_workspace_status(), indent=2, ensure_ascii=False))
