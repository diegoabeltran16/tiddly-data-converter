#!/usr/bin/env python3
"""Inventory data/sessions artifacts and prepare safe canon candidates.

This helper does not modify the canon. It reads session artifacts, derives
canonical identity through the existing canon_preflight normalize command, and
writes an inventory plus a temporary candidate file for records missing by id.
"""

from __future__ import annotations

import argparse
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
    _load_canon_index,
    _project_candidate_record_as_admitted,
    _run_normalize,
    _safe_str,
    _write_jsonl,
)
from path_governance import (  # noqa: E402
    DEFAULT_CANON_DIR,
    REPO_ROOT,
    as_display_path,
    resolve_repo_path,
)


DEFAULT_SESSION_SYNC_DIR = REPO_ROOT / "data" / "tmp" / "session_sync"
SESSION_RE = re.compile(r"^(m\d+)-s([0-9]+[a-z]?)-(.+)$")

FAMILY_BY_RELATIVE_ROOT: dict[tuple[str, ...], dict[str, Any]] = {
    ("00_contratos",): {
        "family": "contrato_de_sesion",
        "role_primary": "policy",
        "source_role": "policy",
        "order": 1,
    },
    ("01_procedencia",): {
        "family": "procedencia_de_sesion",
        "role_primary": "evidence",
        "source_role": "procedencia",
        "order": 2,
    },
    ("02_detalles_de_sesion",): {
        "family": "detalles_de_sesion",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 3,
    },
    ("03_hipotesis",): {
        "family": "hipotesis_de_sesion",
        "role_primary": "procedure",
        "source_role": "hipotesis",
        "order": 4,
    },
    ("04_balance_de_sesion",): {
        "family": "balance_de_sesion",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 5,
    },
    ("05_propuesta_de_sesion",): {
        "family": "propuesta_de_sesion",
        "role_primary": "procedure",
        "source_role": "procedure",
        "order": 6,
    },
    ("06_diagnoses", "sesion"): {
        "family": "diagnostico_de_sesion",
        "role_primary": "log",
        "source_role": "reporte",
        "order": 7,
    },
}


@dataclass
class SessionArtifactCandidate:
    source_path: Path
    session_id: str
    artifact_family: str
    record: dict[str, Any]


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


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


def _session_id_from_path(path: Path) -> str:
    name = path.name
    if name.endswith(".md.json"):
        return name[: -len(".md.json")]
    return path.stem


def _session_parts(session_id: str) -> tuple[str, str, str]:
    match = SESSION_RE.match(session_id)
    if not match:
        return "", "", session_id
    milestone, number, slug = match.groups()
    if slug.startswith("session-"):
        slug = slug[len("session-") :]
    return milestone, number, slug


def _family_spec(path: Path, sessions_dir: Path) -> dict[str, Any] | None:
    rel = path.relative_to(sessions_dir)
    parts = rel.parts
    for prefix, spec in FAMILY_BY_RELATIVE_ROOT.items():
        if parts[: len(prefix)] == prefix:
            return spec
    return None


def _artifact_text(payload: dict[str, Any]) -> str:
    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _session_tags(session_id: str, artifact_family: str) -> list[str]:
    milestone, number, _slug = _session_parts(session_id)
    tags = []
    if milestone and number:
        tags.append(f"session:{milestone}-s{number}")
        tags.append(f"milestone:{milestone}")
    else:
        tags.append(f"session:{session_id}")
    tags.extend([f"artifact:{artifact_family}", "status:candidate", "layer:session"])

    deduped: list[str] = []
    seen = set()
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped


def _provenance_ref(session_id: str, source_path: Path, sessions_dir: Path) -> str:
    provenance_path = sessions_dir / "01_procedencia" / f"{session_id}.md.json"
    if provenance_path.exists():
        return as_display_path(provenance_path)
    return as_display_path(source_path)


def build_candidate_from_artifact(path: Path, sessions_dir: Path) -> SessionArtifactCandidate:
    spec = _family_spec(path, sessions_dir)
    if spec is None:
        raise ValueError("unsupported session artifact family")

    payload = _load_session_tiddler(path)
    title = _safe_str(payload.get("title"))
    if not title:
        raise ValueError("session artifact has no title")

    session_id = _session_id_from_path(path)
    artifact_family = _safe_str(spec["family"])
    source_type = _safe_str(payload.get("type")) or "text/markdown"
    text = _artifact_text(payload)
    created = _safe_str(payload.get("created")) or "19700101000000000"
    modified = _safe_str(payload.get("modified")) or created
    source_path = as_display_path(path)
    tags = _session_tags(session_id, artifact_family)

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
        "role_primary": spec["role_primary"],
        "tags": tags,
        "taxonomy_path": ["sessions", artifact_family],
        "semantic_text": None,
        "content": {"plain": text},
        "raw_payload_ref": "",
        "mime_type": source_type,
        "document_id": f"sessions-{session_id}",
        "section_path": ["sessions", artifact_family, session_id],
        "order_in_document": spec["order"],
        "relations": [],
        "source_tags": list(tags),
        "normalized_tags": list(tags),
        "source_fields": {
            "artifact_family": artifact_family,
            "canonical_status": CANON_STATUS_CANDIDATE,
            "document_key": f"data/sessions/{session_id}",
            "provenance_ref": _provenance_ref(session_id, path, sessions_dir),
            "session_origin": session_id,
            "source_path": source_path,
        },
        "source_role": spec["source_role"],
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
        "source_path": _safe_str(source_fields.get("source_path")) or as_display_path(candidate.source_path),
    }


def scan_session_sync(
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
    canon_dir: Path = DEFAULT_CANON_DIR,
    out_dir: Path = DEFAULT_SESSION_SYNC_DIR,
    run_id: str | None = None,
) -> dict[str, Any]:
    sessions_dir = sessions_dir.resolve()
    canon_dir = canon_dir.resolve()
    run_id = run_id or f"sync-{_stamp_now()}"
    run_dir = out_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

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
    same_id_different_content: list[dict[str, Any]] = []

    seen_ids: dict[str, str] = {}
    missing_records: list[dict[str, Any]] = []

    for candidate in normalized:
        rec_id = _safe_str(candidate.record.get("id"))
        summary = _summary_record(candidate)
        previous_source = seen_ids.get(rec_id)
        if previous_source and previous_source != summary["source_path"]:
            same_id_different_content.append(
                {
                    **summary,
                    "classification": "same_id_different_content",
                    "message": f"id also derived from {previous_source}",
                }
            )
            continue
        seen_ids[rec_id] = summary["source_path"]

        existing = canon_index.by_id.get(rec_id)
        if existing is None:
            missing_by_id.append({**summary, "classification": "missing_by_id"})
            missing_records.append(candidate.record)
            continue

        projected = _project_candidate_record_as_admitted(candidate.record)
        if existing.serialized == _canonical_json(candidate.record) or existing.serialized == _canonical_json(projected):
            existing_by_id.append(
                {
                    **summary,
                    "classification": "existing_by_id",
                    "shard": existing.shard,
                    "line_no": existing.line_no,
                }
            )
        else:
            same_id_different_content.append(
                {
                    **summary,
                    "classification": "same_id_different_content",
                    "shard": existing.shard,
                    "line_no": existing.line_no,
                    "message": "id exists in canon but normalized session artifact differs",
                }
            )

    generated_candidate_file = None
    if missing_records:
        generated_candidate_file = run_dir / "missing-candidates.canon-candidates.jsonl"
        _write_jsonl(generated_candidate_file, missing_records)

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
        "invalid": invalid,
        "unsupported": unsupported,
        "generated_candidate_file": as_display_path(generated_candidate_file) if generated_candidate_file else None,
        "inventory_path": as_display_path(inventory_path),
    }
    _write_json(inventory_path, inventory)
    return inventory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan data/sessions by canonical id and generate missing session candidates."
    )
    parser.add_argument("command", choices=["scan"], help="Operation to run")
    parser.add_argument("--sessions-dir", default=as_display_path(DEFAULT_SESSIONS_DIR))
    parser.add_argument("--canon-dir", default=as_display_path(DEFAULT_CANON_DIR))
    parser.add_argument("--out-dir", default=as_display_path(DEFAULT_SESSION_SYNC_DIR))
    parser.add_argument("--run-id", default=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        inventory = scan_session_sync(
            sessions_dir=resolve_repo_path(args.sessions_dir, DEFAULT_SESSIONS_DIR),
            canon_dir=resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR),
            out_dir=resolve_repo_path(args.out_dir, DEFAULT_SESSION_SYNC_DIR),
            run_id=args.run_id,
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
                "total_session_records": inventory["total_session_records"],
                "existing_by_id": len(inventory["existing_by_id"]),
                "missing_by_id": len(inventory["missing_by_id"]),
                "same_id_different_content": len(inventory["same_id_different_content"]),
                "invalid": len(inventory["invalid"]),
                "unsupported": len(inventory["unsupported"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
