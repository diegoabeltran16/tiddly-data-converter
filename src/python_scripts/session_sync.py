#!/usr/bin/env python3
"""Inventory data/out/local/sessions artifacts and prepare safe canon candidates.

This helper does not modify the canon. It reads session artifacts, derives
canonical identity through the existing canon_preflight normalize command, and
writes an inventory plus temporary candidate files for records missing by id
and same-source replacements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from admit_session_candidates import (  # noqa: E402
    CANON_STATUS_CANDIDATE,
    DEFAULT_SESSIONS_DIR,
    _canonical_json,
    _canon_hash,
    _load_canon_index,
    _project_candidate_record_as_admitted,
    _run_normalize,
    _safe_str,
    _validated_source_type,
    _write_jsonl,
)
from path_governance import (  # noqa: E402
    DEFAULT_CANON_DIR,
    REPO_ROOT,
    as_display_path,
    resolve_repo_path,
)
from session_artifact_governance import (  # noqa: E402
    FAMILY_BY_RELATIVE_ROOT,
    SESSION_RE,
    classify_artifact_family,
    extract_session_id,
    parse_session_parts,
    build_session_tags,
)
from session_title_policy import needs_normalization  # noqa: E402
from generate_session_deliverables import validate_deliverable_file  # noqa: E402


DEFAULT_SESSION_SYNC_DIR = REPO_ROOT / "data" / "tmp" / "session_sync"
DEFAULT_SESSION_SYNC_EVIDENCE_DIR = REPO_ROOT / "data" / "out" / "local" / "audit" / "session_sync"


@dataclass
class SessionArtifactCandidate:
    source_path: Path
    session_id: str
    artifact_family: str
    record: dict[str, Any]
    contract_session_id: str
    contract_module: str
    contract_session: str


SESSION_DELIVERABLE_FAMILIES = {
    "contrato_de_sesion",
    "procedencia_de_sesion",
    "detalles_de_sesion",
    "hipotesis_de_sesion",
    "balance_de_sesion",
    "propuesta_de_sesion",
    "diagnostico_de_sesion",
}

SYNC_SCOPES = ("missing", "replacement", "combined", "identity-drift")
SYNC_FILTER_TYPES = ("all", "session_id", "module", "family")


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_persistent_summary(inventory: dict[str, Any], evidence_dir: Path) -> Path:
    summary_dir = evidence_dir.resolve() / inventory["run_id"]
    summary_path = summary_dir / "summary.json"
    generated_files = [
        value
        for value in (
            inventory.get("generated_missing_candidate_file"),
            inventory.get("generated_replacement_candidate_file"),
            inventory.get("generated_candidate_file"),
        )
        if value
    ]
    summary = {
        "schema": "session-sync-persistent-summary/v1",
        "run_id": inventory["run_id"],
        "timestamp": inventory["timestamp"],
        "tmp_inventory_path": inventory["inventory_path"],
        "canon_dir": inventory["canon_dir"],
        "sessions_dir": inventory["sessions_dir"],
        "counts": {
            "total_files_scanned": inventory["total_files_scanned"],
            "total_session_records": inventory["total_session_records"],
            "existing_by_id": len(inventory["existing_by_id"]),
            "missing_by_id": len(inventory["missing_by_id"]),
            "replaceable_same_id_different_content": len(inventory["replaceable_same_id_different_content"]),
            "blocked_same_id_different_content": len(inventory["blocked_same_id_different_content"]),
            "invalid": len(inventory["invalid"]),
            "unsupported": len(inventory["unsupported"]),
            "source_path_identity_drift": len(inventory["source_path_identity_drift"]),
            "excluded_non_session": len(inventory["excluded_non_session"]),
            "selected_candidates": inventory["candidate_count"],
        },
        "selection": inventory["selection"],
        "source_canon_hash": inventory["source_canon_hash"],
        "candidate_sha256": inventory["candidate_sha256"],
        "generated_candidate_files": generated_files,
        "policy": {
            "data_tmp_role": "temporary_cleanable_workspace",
            "persistent_summary": True,
            "candidate_files_remain_temporary": bool(generated_files),
            "required_action_before_closure_or_admission": (
                "Promote candidate files or cite this persistent summary plus validation evidence "
                "under data/out/local/ before using session_sync output as closure evidence."
            ),
        },
    }
    _write_json(summary_path, summary)
    return summary_path


def _load_session_tiddler(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict):
            return payload[0]
        raise ValueError("JSON array does not contain a tiddler object")
    if isinstance(payload, dict):
        return payload
    raise ValueError("JSON payload is not an object or tiddler array")


def _artifact_text(payload: dict[str, Any]) -> str:
    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


_MIGRATION_PATH_PREFIXES: tuple[tuple[str, str], ...] = (
    ("data/sessions/", "data/out/local/sessions/"),
    ("data/out/sessions/", "data/out/local/sessions/"),
    ("data\\sessions\\", "data\\out\\local\\sessions\\"),
    ("data\\out\\sessions\\", "data\\out\\local\\sessions\\"),
)


def _is_migration_equivalent_path(old_path: str, new_path: str) -> bool:
    """Return True when old_path and new_path differ only by the sessions-dir
    migration prefix (data/sessions/ → data/out/local/sessions/), confirming that
    the artifact was relocated but not semantically changed."""
    old_path = old_path.replace("\\", "/").strip()
    new_path = new_path.replace("\\", "/").strip()
    for old_prefix, new_prefix in _MIGRATION_PATH_PREFIXES:
        old_p = old_prefix.replace("\\", "/")
        new_p = new_prefix.replace("\\", "/")
        if old_path.startswith(old_p) and new_path.startswith(new_p):
            if old_path[len(old_p):] == new_path[len(new_p):]:
                return True
    return False


def _provenance_ref(session_id: str, source_path: Path, sessions_dir: Path) -> str:
    provenance_path = sessions_dir / "01_procedencia" / f"{session_id}.md.json"
    if provenance_path.exists():
        return as_display_path(provenance_path)
    return as_display_path(source_path)


def build_candidate_from_artifact(path: Path, sessions_dir: Path) -> SessionArtifactCandidate:
    family_spec = classify_artifact_family(path, sessions_dir)
    if family_spec is None:
        raise ValueError("unsupported session artifact family")

    payload = _load_session_tiddler(path)
    title = _safe_str(payload.get("title"))
    if not title:
        raise ValueError("session artifact has no title")

    session_id = extract_session_id(path)
    artifact_family = family_spec.family
    source_type = _validated_source_type(_safe_str(payload.get("type")), path)
    text = _artifact_text(payload)
    created = _safe_str(payload.get("created")) or "19700101000000000"
    modified = _safe_str(payload.get("modified")) or created
    source_path = as_display_path(path)
    tags = build_session_tags(session_id, artifact_family)

    content_type = "application/json" if source_type == "application/json" else "text/markdown"
    modality = "metadata" if content_type == "application/json" else "text"

    record = {
        "schema_version": "v0",
        "id": "",
        "key": title,
        "title": title,
        "canonical_slug": "",
        "version_id": "",
        "content_type": content_type,
        "modality": modality,
        "encoding": "utf-8",
        "is_binary": False,
        "is_reference_only": False,
        "role_primary": family_spec.role_primary,
        "tags": tags,
        "taxonomy_path": ["sessions", artifact_family],
        "semantic_text": None,
        "content": {"plain": text},
        "raw_payload_ref": "",
        "mime_type": source_type,
        "document_id": f"sessions-{session_id}",
        "section_path": ["sessions", artifact_family, session_id],
        "order_in_document": family_spec.order,
        "relations": [],
        "source_tags": list(tags),
        "normalized_tags": list(tags),
        "source_fields": {
            "artifact_family": artifact_family,
            "canonical_status": CANON_STATUS_CANDIDATE,
            "document_key": f"data/out/local/sessions/{session_id}",
            "provenance_ref": _provenance_ref(session_id, path, sessions_dir),
            "session_origin": session_id,
            "source_path": source_path,
            # S0124: title normalisation gate — "true"/"false" string (source_fields is map[string]string in Go)
            "needs_title_normalization": "true" if needs_normalization(title, artifact_family) else "false",
        },
        "source_role": family_spec.source_role,
        "text": text,
        "source_type": source_type,
        "source_position": source_path,
        "created": created,
        "modified": modified,
    }
    return SessionArtifactCandidate(
        source_path=path,
        session_id=session_id,
        artifact_family=artifact_family,
        record=record,
        contract_session_id=_safe_str(payload.get("session_id")),
        contract_module=_safe_str(payload.get("module")),
        contract_session=_safe_str(payload.get("session")),
    )


def _normalize_candidates(
    candidates: list[SessionArtifactCandidate],
    run_dir: Path,
) -> tuple[list[SessionArtifactCandidate], list[dict[str, Any]]]:
    if not candidates:
        return [], []

    raw_records = [candidate.record for candidate in candidates]
    try:
        normalized_records, _result = _run_normalize(raw_records, run_dir / "normalize")
    except RuntimeError as exc:
        invalid = [
            {
                "path": as_display_path(candidate.source_path),
                "classification": "invalid",
                "message": f"normalize failed in batch: {exc}",
            }
            for candidate in candidates
        ]
        return [], invalid

    normalized_candidates: list[SessionArtifactCandidate] = []
    invalid: list[dict[str, Any]] = []
    for candidate, record in zip(candidates, normalized_records):
        rec_id = _safe_str(record.get("id"))
        if not rec_id:
            invalid.append(
                {
                    "path": as_display_path(candidate.source_path),
                    "classification": "invalid",
                    "message": "canon_preflight normalize did not derive id",
                }
            )
            continue
        record["raw_payload_ref"] = f"node:{rec_id}"
        normalized_candidates.append(
            SessionArtifactCandidate(
                source_path=candidate.source_path,
                session_id=candidate.session_id,
                artifact_family=candidate.artifact_family,
                record=record,
                contract_session_id=candidate.contract_session_id,
                contract_module=candidate.contract_module,
                contract_session=candidate.contract_session,
            )
        )
    return normalized_candidates, invalid


def _summary_record(candidate: SessionArtifactCandidate) -> dict[str, Any]:
    record = candidate.record
    source_fields = record.get("source_fields") or {}
    return {
        "id": _safe_str(record.get("id")),
        "title": _safe_str(record.get("title")),
        "session_origin": candidate.session_id,
        "artifact_family": candidate.artifact_family,
        "session_id": candidate.contract_session_id,
        "module": candidate.contract_module,
        "session": candidate.contract_session,
        "source_path": _safe_str(source_fields.get("source_path")) or as_display_path(candidate.source_path),
        "canonical_slug": _safe_str(record.get("canonical_slug")),
    }


def _record_hash(record: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


def _replacement_diff(candidate: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    candidate_fields = set(candidate)
    current_fields = set(current)
    changed_fields = sorted(
        field for field in candidate_fields | current_fields if candidate.get(field) != current.get(field)
    )
    candidate_source = candidate.get("source_fields") or {}
    current_source = current.get("source_fields") or {}
    identity_fields = {"id", "key", "title", "canonical_slug"}
    volatile_fields = {"modified"}
    return {
        "id": _safe_str(candidate.get("id")),
        "source_path": _safe_str(candidate_source.get("source_path")),
        "canonical_slug": _safe_str(candidate.get("canonical_slug")),
        "changed_fields": changed_fields,
        "text_changed": candidate.get("text") != current.get("text"),
        "metadata_changed": bool(set(changed_fields) - {"text", "content"}),
        "identity_changed": bool(set(changed_fields) & identity_fields),
        "volatile_only": bool(changed_fields) and set(changed_fields) <= volatile_fields,
        "current_record_hash": _record_hash(current),
        "candidate_record_hash": _record_hash(candidate),
    }


def _matches_filter(candidate: SessionArtifactCandidate, filter_type: str, filter_value: str | None) -> bool:
    if filter_type == "all":
        return True
    if not filter_value:
        return False
    if filter_type == "session_id":
        return candidate.contract_session_id == filter_value
    if filter_type == "module":
        return candidate.contract_module == filter_value
    if filter_type == "family":
        return candidate.artifact_family == filter_value
    raise ValueError(f"unsupported session sync filter: {filter_type}")


def _candidate_filename(scope: str, filter_type: str, filter_value: str | None) -> str:
    raw_filter = "all" if filter_type == "all" else f"{filter_type}-{filter_value or 'empty'}"
    safe_filter = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw_filter).strip("-")
    return f"{scope}-{safe_filter}.canon-candidates.jsonl"


def scan_session_sync(
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
    canon_dir: Path = DEFAULT_CANON_DIR,
    out_dir: Path = DEFAULT_SESSION_SYNC_DIR,
    run_id: str | None = None,
    evidence_dir: Path | None = None,
    scope: str = "combined",
    filter_type: str = "all",
    filter_value: str | None = None,
) -> dict[str, Any]:
    sessions_dir = sessions_dir.resolve()
    canon_dir = canon_dir.resolve()
    run_id = run_id or f"sync-{_stamp_now()}"
    run_dir = out_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if scope not in SYNC_SCOPES:
        raise ValueError(f"unsupported sync scope: {scope}")
    if filter_type not in SYNC_FILTER_TYPES:
        raise ValueError(f"unsupported sync filter type: {filter_type}")
    if filter_type != "all" and not filter_value:
        raise ValueError(f"filter {filter_type} requires a value")

    md_paths = sorted(sessions_dir.rglob("*.md.json"))
    candidate_paths = sorted(sessions_dir.rglob("*.canon-candidates.jsonl"))
    unsupported_paths = [
        path
        for path in sorted(sessions_dir.rglob("*"))
        if path.is_file() and not path.name.endswith(".md.json") and not path.name.endswith(".canon-candidates.jsonl")
    ]

    prepared: list[SessionArtifactCandidate] = []
    invalid: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    for path in md_paths:
        # Step 1: JSON parse check — preserve "invalid" classification for
        # unreadable/malformed files (preserves pre-S0128 contract).
        try:
            path.read_text(encoding="utf-8")
            # validate_deliverable_file will re-parse; this is just for early detection
            json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            invalid.append(
                {
                    "path": as_display_path(path),
                    "classification": "invalid",
                    "message": str(exc),
                }
            )
            continue

        # Step 2: S0128 schema validation — fail-fast on authoring errors
        # (wrong 'type', 'created_at', S-prefix titles, list-format root, etc.)
        schema_errors = validate_deliverable_file(path)
        if schema_errors:
            invalid.append(
                {
                    "path": as_display_path(path),
                    "classification": "schema_invalid",
                    "message": "; ".join(str(e) for e in schema_errors),
                    "schema_errors": [
                        {"field": e.field, "message": e.message}
                        for e in schema_errors
                    ],
                }
            )
            continue

        # Step 3: build candidate (existing behavior)
        try:
            prepared.append(build_candidate_from_artifact(path, sessions_dir))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            invalid.append(
                {
                    "path": as_display_path(path),
                    "classification": "invalid",
                    "message": str(exc),
                }
            )

    for path in unsupported_paths:
        unsupported.append(
            {
                "path": as_display_path(path),
                "classification": "unsupported",
                "message": "not a .md.json session artifact or .canon-candidates.jsonl support file",
            }
        )

    normalized, normalize_invalid = _normalize_candidates(prepared, run_dir)
    invalid.extend(normalize_invalid)

    canon_index = _load_canon_index(canon_dir)
    existing_by_id: list[dict[str, Any]] = []
    missing_by_id: list[dict[str, Any]] = []
    replaceable_same_id_different_content: list[dict[str, Any]] = []
    blocked_same_id_different_content: list[dict[str, Any]] = []
    source_path_identity_drift: list[dict[str, Any]] = []
    excluded_non_session: list[dict[str, Any]] = []

    seen_ids: dict[str, str] = {}
    missing_records: list[dict[str, Any]] = []
    replacement_records: list[dict[str, Any]] = []

    for candidate in normalized:
        rec_id = _safe_str(candidate.record.get("id"))
        summary = _summary_record(candidate)
        previous_source = seen_ids.get(rec_id)
        if previous_source and previous_source != summary["source_path"]:
            blocked_same_id_different_content.append(
                {
                    **summary,
                    "classification": "blocking_conflict",
                    "message": f"id also derived from {previous_source}",
                }
            )
            continue
        seen_ids[rec_id] = summary["source_path"]

        if candidate.artifact_family not in SESSION_DELIVERABLE_FAMILIES:
            excluded_non_session.append(
                {**summary, "classification": "excluded_non_session", "message": "artifact family is outside the seven session deliverables"}
            )
            continue

        existing = canon_index.by_id.get(rec_id)
        if existing is None:
            source_match = canon_index.by_source_path.get(summary["source_path"])
            if source_match is not None:
                source_path_identity_drift.append(
                    {
                        **summary,
                        "classification": "source_path_identity_drift",
                        "canonical_id": _safe_str(source_match.record.get("id")),
                        "canonical_slug_current": _safe_str(source_match.record.get("canonical_slug")),
                        "message": "source_path exists in canon under a different id; separate human identity review required",
                    }
                )
                continue
            missing_by_id.append({**summary, "classification": "missing_by_id"})
            if _matches_filter(candidate, filter_type, filter_value):
                missing_records.append(candidate.record)
            continue

        projected = _project_candidate_record_as_admitted(candidate.record)
        if existing.serialized == _canonical_json(candidate.record) or existing.serialized == _canonical_json(projected):
            existing_by_id.append(
                {
                    **summary,
                    "classification": "equal_by_id",
                    "shard": existing.shard,
                    "line_no": existing.line_no,
                }
            )
        else:
            existing_source_fields = existing.record.get("source_fields") or {}
            existing_source_path = _safe_str(existing_source_fields.get("source_path"))
            item = {
                **summary,
                "shard": existing.shard,
                "line_no": existing.line_no,
            }
            replaceable_same_id_different_content.append(
                {
                    **item,
                    "classification": "replacement_by_same_id",
                    "existing_source_path": existing_source_path,
                    "source_path_changed": existing_source_path != summary["source_path"],
                    "source_path_migrated": _is_migration_equivalent_path(
                        existing_source_path, summary["source_path"]
                    ),
                    "message": "id exists in canon with different content; eligible for controlled same-id replacement",
                    "replacement_diff": _replacement_diff(candidate.record, existing.record),
                }
            )
            if _matches_filter(candidate, filter_type, filter_value):
                replacement_records.append(candidate.record)

    if scope == "missing":
        selected_records = missing_records
    elif scope == "replacement":
        selected_records = replacement_records
    elif scope == "combined":
        selected_records = [*missing_records, *replacement_records]
    else:
        selected_records = []

    generated_missing_candidate_file = None
    if missing_records:
        generated_missing_candidate_file = run_dir / "missing-candidates.canon-candidates.jsonl"
        _write_jsonl(generated_missing_candidate_file, missing_records)

    generated_replacement_candidate_file = None
    if replacement_records:
        generated_replacement_candidate_file = run_dir / "replacement-candidates.canon-candidates.jsonl"
        _write_jsonl(generated_replacement_candidate_file, replacement_records)

    generated_candidate_file = None
    if selected_records:
        generated_candidate_file = run_dir / _candidate_filename(scope, filter_type, filter_value)
        _write_jsonl(generated_candidate_file, selected_records)

    same_id_different_content = [
        *replaceable_same_id_different_content,
        *blocked_same_id_different_content,
    ]

    inventory_path = run_dir / "inventory.json"
    inventory = {
        "run_id": run_id,
        "timestamp": _iso_now(),
        "canon_dir": as_display_path(canon_dir),
        "sessions_dir": as_display_path(sessions_dir),
        "total_files_scanned": len(md_paths) + len(candidate_paths),
        "total_session_records": len(normalized),
        "candidate_support_files": [as_display_path(path) for path in candidate_paths],
        "existing_by_id": existing_by_id,
        "missing_by_id": missing_by_id,
        "same_id_different_content": same_id_different_content,
        "equal_by_id": existing_by_id,
        "replaceable_same_id_different_content": replaceable_same_id_different_content,
        "replacement_by_same_id": replaceable_same_id_different_content,
        "blocked_same_id_different_content": blocked_same_id_different_content,
        "blocking_conflict": blocked_same_id_different_content,
        "source_path_identity_drift": source_path_identity_drift,
        "excluded_non_session": excluded_non_session,
        "unsupported_auxiliary": unsupported,
        "invalid_session_deliverable": invalid,
        "selection": {
            "scope": scope,
            "filter": {"type": filter_type, "value": filter_value},
            "replacement_policy": "same_id_only" if scope in {"replacement", "combined"} else "none",
        },
        "source_canon_hash": _canon_hash(canon_dir),
        "invalid": invalid,
        "unsupported": unsupported,
        "generated_missing_candidate_file": (
            as_display_path(generated_missing_candidate_file) if generated_missing_candidate_file else None
        ),
        "generated_replacement_candidate_file": (
            as_display_path(generated_replacement_candidate_file) if generated_replacement_candidate_file else None
        ),
        "generated_candidate_file": as_display_path(generated_candidate_file) if generated_candidate_file else None,
        "candidate_sha256": _sha256_file(generated_candidate_file) if generated_candidate_file else None,
        "candidate_count": len(selected_records),
        "inventory_path": as_display_path(inventory_path),
        "persistent_summary_path": None,
    }
    _write_json(inventory_path, inventory)
    if evidence_dir is not None:
        summary_path = _write_persistent_summary(inventory, evidence_dir)
        inventory["persistent_summary_path"] = as_display_path(summary_path)
        _write_json(inventory_path, inventory)
    return inventory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan data/out/local/sessions by canonical id and generate missing plus "
            "controlled replacement session candidates."
        )
    )
    parser.add_argument("command", choices=["scan"], help="Operation to run")
    parser.add_argument("--sessions-dir", default=as_display_path(DEFAULT_SESSIONS_DIR))  # default: data/out/local/sessions
    parser.add_argument("--canon-dir", default=as_display_path(DEFAULT_CANON_DIR))
    parser.add_argument("--out-dir", default=as_display_path(DEFAULT_SESSION_SYNC_DIR))
    parser.add_argument(
        "--evidence-dir",
        default=as_display_path(DEFAULT_SESSION_SYNC_EVIDENCE_DIR),
        help="Persistent session_sync evidence summary dir (default: data/out/local/audit/session_sync)",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--scope", choices=SYNC_SCOPES, required=True)
    parser.add_argument("--filter-type", choices=SYNC_FILTER_TYPES, default="all")
    parser.add_argument("--filter-value", default=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        inventory = scan_session_sync(
            sessions_dir=resolve_repo_path(args.sessions_dir, DEFAULT_SESSIONS_DIR),
            canon_dir=resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR),
            out_dir=resolve_repo_path(args.out_dir, DEFAULT_SESSION_SYNC_DIR),
            evidence_dir=resolve_repo_path(args.evidence_dir, DEFAULT_SESSION_SYNC_EVIDENCE_DIR),
            run_id=args.run_id,
            scope=args.scope,
            filter_type=args.filter_type,
            filter_value=args.filter_value,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": inventory["run_id"],
                "inventory": inventory["inventory_path"],
                "generated_candidate_file": inventory["generated_candidate_file"],
                "generated_missing_candidate_file": inventory["generated_missing_candidate_file"],
                "generated_replacement_candidate_file": inventory["generated_replacement_candidate_file"],
                "persistent_summary_path": inventory["persistent_summary_path"],
                "total_session_records": inventory["total_session_records"],
                "existing_by_id": len(inventory["existing_by_id"]),
                "missing_by_id": len(inventory["missing_by_id"]),
                "same_id_different_content": len(inventory["same_id_different_content"]),
                "replaceable_same_id_different_content": len(inventory["replaceable_same_id_different_content"]),
                "blocked_same_id_different_content": len(inventory["blocked_same_id_different_content"]),
                "invalid": len(inventory["invalid"]),
                "unsupported": len(inventory["unsupported"]),
                "source_path_identity_drift": len(inventory["source_path_identity_drift"]),
                "excluded_non_session": len(inventory["excluded_non_session"]),
                "scope": inventory["selection"]["scope"],
                "filter": inventory["selection"]["filter"],
                "candidate_sha256": inventory["candidate_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
