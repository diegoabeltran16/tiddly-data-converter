#!/usr/bin/env python3
"""Local orchestrator for admitting session candidate lines into the canon."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from path_governance import (
    DEFAULT_CANON_DIR,
    DEFAULT_INPUT_HTML,
    REPO_ROOT,
    as_display_path,
    resolve_repo_path,
)


CANON_STATUS_CANDIDATE = "candidate_not_admitted"
CANON_STATUS_ADMITTED = "local_admitted"

DEFAULT_SESSIONS_DIR = REPO_ROOT / "data" / "sessions"
DEFAULT_TMP_DIR = REPO_ROOT / "data" / "tmp" / "session_admission"
DEFAULT_REPORT_DIR = REPO_ROOT / "data" / "tmp" / "admissions"
SESSION_ID_RE = re.compile(r"^(m\d+)-s([0-9]+[a-z]?)-(.+)$")

REQUIRED_CANON_FIELDS = (
    "schema_version",
    "id",
    "key",
    "title",
    "canonical_slug",
    "version_id",
    "content_type",
    "modality",
    "encoding",
    "is_binary",
    "is_reference_only",
    "role_primary",
    "tags",
    "taxonomy_path",
    "semantic_text",
    "content",
    "raw_payload_ref",
    "mime_type",
    "document_id",
    "section_path",
    "order_in_document",
    "relations",
    "source_tags",
    "normalized_tags",
    "source_fields",
    "text",
    "source_type",
    "source_position",
    "created",
    "modified",
)

REQUIRED_SOURCE_FIELDS = (
    "session_origin",
    "artifact_family",
    "source_path",
    "provenance_ref",
    "canonical_status",
)


@dataclass
class CommandResult:
    command: list[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str

    def to_report(self) -> dict[str, Any]:
        return {
            "command": " ".join(self.command),
            "cwd": as_display_path(self.cwd),
            "exit_code": self.returncode,
            "stdout_tail": _tail(self.stdout),
            "stderr_tail": _tail(self.stderr),
        }


@dataclass
class CandidateEntry:
    line_no: int
    record: dict[str, Any]
    serialized: str
    source_path: str
    session_origin: str
    artifact_family: str
    replacement: "CanonRecord | None" = None


@dataclass
class CanonRecord:
    record: dict[str, Any]
    serialized: str
    shard: str
    line_no: int


@dataclass
class CanonIndex:
    by_id: dict[str, CanonRecord]
    by_key: dict[str, CanonRecord]
    by_slug: dict[str, CanonRecord]
    by_source_path: dict[str, CanonRecord]
    by_session_family: dict[str, CanonRecord]
    by_hash: dict[str, list[CanonRecord]]
    by_title: dict[str, list[CanonRecord]]


@dataclass
class CandidateValidation:
    entries: list[CandidateEntry]
    rejected: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    invalid_jsonl: bool


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp_now() -> str:
    return _now_utc().strftime("%Y%m%d%H%M%S")


def _tail(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _safe_str(value: Any) -> str:
    return "" if value is None else str(value)


def _canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _run_command(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(
        command=command,
        cwd=cwd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _go_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GOCACHE", "/tmp/tdc-go-build")
    return env


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_jsonl(path: Path, lines: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                rejects.append(
                    {
                        "line": line_no,
                        "classification": "reject_invalid_jsonl",
                        "message": f"invalid JSONL: {exc}",
                    }
                )
                continue
            if not isinstance(obj, dict):
                rejects.append(
                    {
                        "line": line_no,
                        "classification": "reject_invalid_jsonl",
                        "message": "line is not a JSON object",
                    }
                )
                continue
            records.append(obj)
    return records, rejects


def _canon_hash(canon_dir: Path) -> str:
    digest = hashlib.sha256()
    shard_paths = sorted(canon_dir.glob("tiddlers_*.jsonl"))
    for shard in shard_paths:
        digest.update(shard.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(shard.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _session_family_key(session_origin: str, artifact_family: str) -> str:
    return f"{session_origin}::{artifact_family}"


def _session_number_and_slug(session_id: str) -> tuple[str, str, str]:
    match = SESSION_ID_RE.match(session_id)
    if not match:
        return "", session_id, session_id
    milestone, number, slug = match.groups()
    if slug.startswith("session-"):
        slug = slug[len("session-") :]
    return milestone, number, slug


def _session_title_for_family(session_id: str, artifact_family: str) -> str:
    _, number, slug = _session_number_and_slug(session_id)
    labels = {
        "contrato_de_sesion": "#### 🌀 Contrato de sesión",
        "procedencia_de_sesion": "#### 🌀🧾 Procedencia de sesión",
        "detalles_de_sesion": "#### 🌀 Sesión",
        "hipotesis_de_sesion": "#### 🌀🧪 Hipótesis de sesión",
        "balance_de_sesion": "#### 🌀 Balance de sesión",
        "propuesta_de_sesion": "#### 🌀 Propuesta de sesión",
        "diagnostico_de_sesion": "#### 🌀 Diagnóstico de sesión",
    }
    label = labels.get(artifact_family, "#### 🌀 Sesión")
    if number:
        return f"{label} {number} = {slug}"
    return f"{label} = {slug}"


def _load_session_artifact(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if isinstance(payload, list):
        if not payload or not isinstance(payload[0], dict):
            raise ValueError(f"{as_display_path(path)} does not contain a tiddler object")
        return payload[0]
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"{as_display_path(path)} is not a JSON object or tiddler array")


def _session_id_from_artifact_path(path: Path) -> str:
    name = path.name
    if name.endswith(".md.json"):
        return name[: -len(".md.json")]
    return path.stem


def _artifact_text(payload: dict[str, Any]) -> str:
    text = payload.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _contract_candidate_from_artifact(path: Path, sessions_dir: Path) -> dict[str, Any]:
    payload = _load_session_artifact(path)
    session_id = _session_id_from_artifact_path(path)
    milestone, number, _ = _session_number_and_slug(session_id)
    if not milestone:
        milestone = session_id.split("-", 1)[0] if "-" in session_id else "session"
    session_tag = f"session:{milestone}-s{number}" if number else f"session:{session_id}"
    title = _session_title_for_family(session_id, "contrato_de_sesion")
    source_path = as_display_path(path)
    source_type = _safe_str(payload.get("type")) or "text/markdown"
    text = _artifact_text(payload)
    created = _safe_str(payload.get("created")) or "19700101000000000"
    modified = _safe_str(payload.get("modified")) or created
    tags = [
        session_tag,
        f"milestone:{milestone}",
        "artifact:contrato_de_sesion",
        "status:candidate",
        "layer:session",
    ]
    content_type = "application/json" if source_type == "application/json" else "text/markdown"
    modality = "metadata" if content_type == "application/json" else "text"

    return {
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
        "role_primary": "policy",
        "tags": tags,
        "taxonomy_path": ["sessions", "contrato_de_sesion"],
        "semantic_text": None,
        "content": {"plain": text},
        "raw_payload_ref": "",
        "mime_type": source_type,
        "document_id": f"sessions-{session_id}",
        "section_path": ["sessions", "contrato_de_sesion", session_id],
        "order_in_document": 1,
        "relations": [],
        "source_tags": list(tags),
        "normalized_tags": list(tags),
        "source_fields": {
            "artifact_family": "contrato_de_sesion",
            "canonical_status": CANON_STATUS_CANDIDATE,
            "document_key": f"data/sessions/{session_id}",
            "provenance_ref": source_path,
            "session_origin": session_id,
            "source_path": source_path,
        },
        "source_role": "policy",
        "text": text,
        "source_type": source_type,
        "source_position": source_path,
        "created": created,
        "modified": modified,
    }


def _generate_contract_candidate_file(sessions_dir: Path, report_dir: Path) -> Path:
    contracts_dir = sessions_dir / "00_contratos"
    contract_paths = sorted(contracts_dir.glob("*.md.json"))
    if not contract_paths:
        raise ValueError(f"no contract artifacts found under {as_display_path(contracts_dir)}")

    raw_lines = [_contract_candidate_from_artifact(path, sessions_dir) for path in contract_paths]
    generated_dir = report_dir / "generated"
    run_dir = generated_dir / f"all-contracts-{_stamp_now()}"
    normalized, _normalize_result = _run_normalize(raw_lines, run_dir)
    for line in normalized:
        rec_id = _safe_str(line.get("id"))
        line["raw_payload_ref"] = f"node:{rec_id}" if rec_id else ""

    output_path = generated_dir / f"all-contracts-{_stamp_now()}.canon-candidates.jsonl"
    _write_jsonl(output_path, normalized)
    return output_path


def _validate_source_path(raw_path: str, sessions_dir: Path) -> tuple[bool, str]:
    if not raw_path:
        return False, "source_path is empty"
    resolved = resolve_repo_path(raw_path, sessions_dir)
    try:
        resolved.relative_to(sessions_dir.resolve())
    except ValueError:
        return False, f"source_path must stay under {as_display_path(sessions_dir)}"
    if not resolved.exists():
        return False, f"source_path does not exist: {raw_path}"
    return True, ""


def _validate_provenance_path(raw_path: str, sessions_dir: Path) -> tuple[bool, str]:
    if not raw_path:
        return False, "provenance_ref is empty"
    resolved = resolve_repo_path(raw_path, sessions_dir)
    try:
        resolved.relative_to(sessions_dir.resolve())
    except ValueError:
        return False, f"provenance_ref must stay under {as_display_path(sessions_dir)}"
    if not resolved.exists():
        return False, f"provenance_ref does not exist: {raw_path}"
    return True, ""


def _build_candidate_validation(candidate_file: Path, sessions_dir: Path) -> CandidateValidation:
    if not candidate_file.exists():
        return CandidateValidation(
            entries=[],
            rejected=[
                {
                    "line": 0,
                    "classification": "reject_invalid_jsonl",
                    "message": f"candidate file does not exist: {as_display_path(candidate_file)}",
                }
            ],
            warnings=[],
            invalid_jsonl=True,
        )

    parsed_lines, parse_rejects = _read_jsonl(candidate_file)
    rejected: list[dict[str, Any]] = list(parse_rejects)
    warnings: list[dict[str, Any]] = []
    entries: list[CandidateEntry] = []

    for line_no, record in enumerate(parsed_lines, start=1):
        missing_fields = [field for field in REQUIRED_CANON_FIELDS if field not in record]
        if missing_fields:
            rejected.append(
                {
                    "line": line_no,
                    "id": _safe_str(record.get("id")),
                    "title": _safe_str(record.get("title")),
                    "classification": "reject_missing_required_fields",
                    "message": f"missing required fields: {', '.join(missing_fields)}",
                }
            )
            continue

        source_fields = record.get("source_fields")
        if not isinstance(source_fields, dict):
            rejected.append(
                {
                    "line": line_no,
                    "id": _safe_str(record.get("id")),
                    "title": _safe_str(record.get("title")),
                    "classification": "reject_missing_required_fields",
                    "message": "source_fields must be a non-empty object",
                }
            )
            continue

        missing_source_fields = [field for field in REQUIRED_SOURCE_FIELDS if not _safe_str(source_fields.get(field))]
        if missing_source_fields:
            rejected.append(
                {
                    "line": line_no,
                    "id": _safe_str(record.get("id")),
                    "title": _safe_str(record.get("title")),
                    "classification": "reject_missing_required_fields",
                    "message": f"missing source_fields: {', '.join(missing_source_fields)}",
                }
            )
            continue

        source_path = _safe_str(source_fields.get("source_path"))
        source_ok, source_error = _validate_source_path(source_path, sessions_dir)
        if not source_ok:
            rejected.append(
                {
                    "line": line_no,
                    "id": _safe_str(record.get("id")),
                    "title": _safe_str(record.get("title")),
                    "classification": "reject_missing_source_artifact",
                    "message": source_error,
                }
            )
            continue

        provenance_ref = _safe_str(source_fields.get("provenance_ref"))
        provenance_ok, provenance_error = _validate_provenance_path(provenance_ref, sessions_dir)
        if not provenance_ok:
            rejected.append(
                {
                    "line": line_no,
                    "id": _safe_str(record.get("id")),
                    "title": _safe_str(record.get("title")),
                    "classification": "reject_missing_required_fields",
                    "message": provenance_error,
                }
            )
            continue

        canonical_status = _safe_str(source_fields.get("canonical_status"))
        if canonical_status != CANON_STATUS_CANDIDATE:
            rejected.append(
                {
                    "line": line_no,
                    "id": _safe_str(record.get("id")),
                    "title": _safe_str(record.get("title")),
                    "classification": "reject_missing_required_fields",
                    "message": (
                        "canonical_status must remain candidate_not_admitted in candidate files; "
                        f"found {canonical_status!r}"
                    ),
                }
            )
            continue

        raw_id = _safe_str(record.get("id"))
        raw_payload_ref = _safe_str(record.get("raw_payload_ref"))
        if raw_id and raw_payload_ref != f"node:{raw_id}":
            warnings.append(
                {
                    "line": line_no,
                    "id": raw_id,
                    "title": _safe_str(record.get("title")),
                    "classification": "warning_inconsistent_raw_payload_ref",
                    "message": "raw_payload_ref does not match node:<id>; normalize may correct id but strict can fail",
                }
            )

        entries.append(
            CandidateEntry(
                line_no=line_no,
                record=record,
                serialized=_canonical_json(record),
                source_path=source_path,
                session_origin=_safe_str(source_fields.get("session_origin")),
                artifact_family=_safe_str(source_fields.get("artifact_family")),
            )
        )

    return CandidateValidation(
        entries=entries,
        rejected=rejected,
        warnings=warnings,
        invalid_jsonl=bool(parse_rejects),
    )


def _load_canon_index(canon_dir: Path) -> CanonIndex:
    by_id: dict[str, CanonRecord] = {}
    by_key: dict[str, CanonRecord] = {}
    by_slug: dict[str, CanonRecord] = {}
    by_source_path: dict[str, CanonRecord] = {}
    by_session_family: dict[str, CanonRecord] = {}
    by_hash: dict[str, list[CanonRecord]] = {}
    by_title: dict[str, list[CanonRecord]] = {}

    for shard_path in sorted(canon_dir.glob("tiddlers_*.jsonl")):
        with shard_path.open("r", encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue

                canon_record = CanonRecord(
                    record=record,
                    serialized=_canonical_json(record),
                    shard=shard_path.name,
                    line_no=line_no,
                )

                record_id = _safe_str(record.get("id"))
                record_key = _safe_str(record.get("key"))
                record_title = _safe_str(record.get("title"))
                record_slug = _safe_str(record.get("canonical_slug"))

                source_fields = record.get("source_fields") or {}
                source_path = _safe_str(source_fields.get("source_path"))
                session_origin = _safe_str(source_fields.get("session_origin"))
                artifact_family = _safe_str(source_fields.get("artifact_family"))

                if record_id and record_id not in by_id:
                    by_id[record_id] = canon_record
                if record_key and record_key not in by_key:
                    by_key[record_key] = canon_record
                if record_slug and record_slug not in by_slug:
                    by_slug[record_slug] = canon_record
                if source_path and source_path not in by_source_path:
                    by_source_path[source_path] = canon_record
                if session_origin and artifact_family:
                    sf_key = _session_family_key(session_origin, artifact_family)
                    if sf_key not in by_session_family:
                        by_session_family[sf_key] = canon_record

                if record_title:
                    by_title.setdefault(record_title, []).append(canon_record)

                by_hash.setdefault(canon_record.serialized, []).append(canon_record)

    return CanonIndex(
        by_id=by_id,
        by_key=by_key,
        by_slug=by_slug,
        by_source_path=by_source_path,
        by_session_family=by_session_family,
        by_hash=by_hash,
        by_title=by_title,
    )


def _classify_against_index(
    entries: list[CandidateEntry],
    canon_index: CanonIndex | None,
    allow_replacements: bool = False,
) -> tuple[list[CandidateEntry], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    eligible: list[CandidateEntry] = []
    skipped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    stats = {
        "new_candidate": 0,
        "already_admitted_skip": 0,
        "duplicate_identical": 0,
        "conflict_same_id_different_content": 0,
        "conflict_same_source_path_different_id": 0,
        "conflict_same_session_family_already_admitted": 0,
        "replace_existing_by_source_path": 0,
        "warning_same_title_different_id": 0,
    }

    seen_ids: dict[str, CandidateEntry] = {}
    seen_source_paths: dict[str, CandidateEntry] = {}
    seen_session_family: dict[str, CandidateEntry] = {}
    seen_titles: dict[str, CandidateEntry] = {}

    for entry in entries:
        record = entry.record
        rec_id = _safe_str(record.get("id"))
        rec_title = _safe_str(record.get("title"))
        rec_key = _safe_str(record.get("key"))
        rec_slug = _safe_str(record.get("canonical_slug"))
        sf_key = _session_family_key(entry.session_origin, entry.artifact_family)

        if rec_id in seen_ids:
            prev = seen_ids[rec_id]
            if prev.serialized == entry.serialized:
                skipped.append(
                    {
                        "line": entry.line_no,
                        "id": rec_id,
                        "title": rec_title,
                        "classification": "duplicate_identical",
                        "message": f"duplicate identical candidate line for id {rec_id}",
                    }
                )
                stats["duplicate_identical"] += 1
            else:
                rejected.append(
                    {
                        "line": entry.line_no,
                        "id": rec_id,
                        "title": rec_title,
                        "classification": "conflict_same_id_different_content",
                        "message": f"candidate id {rec_id} repeats with different content inside the same file",
                    }
                )
                stats["conflict_same_id_different_content"] += 1
            continue

        if entry.source_path in seen_source_paths and seen_source_paths[entry.source_path].record.get("id") != rec_id:
            rejected.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "conflict_same_source_path_different_id",
                    "message": f"source_path {entry.source_path} already appears with a different id inside candidate file",
                }
            )
            stats["conflict_same_source_path_different_id"] += 1
            continue

        if sf_key in seen_session_family and seen_session_family[sf_key].record.get("id") != rec_id:
            rejected.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "conflict_same_session_family_already_admitted",
                    "message": "same session_origin + artifact_family repeats with a different id in candidate file",
                }
            )
            stats["conflict_same_session_family_already_admitted"] += 1
            continue

        if rec_title in seen_titles and seen_titles[rec_title].record.get("id") != rec_id:
            warnings.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "warning_same_title_different_id",
                    "message": "same title repeats with a different id in candidate file",
                }
            )
            stats["warning_same_title_different_id"] += 1
            rejected.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "warning_same_title_different_id",
                    "message": "title collision inside candidate batch is rejected to preserve reverse safety",
                }
            )
            continue

        seen_ids[rec_id] = entry
        seen_source_paths[entry.source_path] = entry
        seen_session_family[sf_key] = entry
        seen_titles[rec_title] = entry

        if canon_index is None:
            eligible.append(entry)
            stats["new_candidate"] += 1
            continue

        canon_same_id = canon_index.by_id.get(rec_id)
        if canon_same_id is not None:
            if canon_same_id.serialized == entry.serialized:
                skipped.append(
                    {
                        "line": entry.line_no,
                        "id": rec_id,
                        "title": rec_title,
                        "classification": "already_admitted_skip",
                        "message": f"id {rec_id} already exists with identical content in {canon_same_id.shard}",
                    }
                )
                stats["already_admitted_skip"] += 1
            elif _canonical_json(_project_candidate_record_as_admitted(entry.record)) == canon_same_id.serialized:
                skipped.append(
                    {
                        "line": entry.line_no,
                        "id": rec_id,
                        "title": rec_title,
                        "classification": "already_admitted_skip",
                        "message": (
                            f"id {rec_id} is already admitted in {canon_same_id.shard}; "
                            "candidate differs only by admission status projection"
                        ),
                    }
                )
                stats["already_admitted_skip"] += 1
            elif allow_replacements and _safe_str((canon_same_id.record.get("source_fields") or {}).get("source_path")) == entry.source_path:
                entry.replacement = canon_same_id
                warnings.append(
                    {
                        "line": entry.line_no,
                        "id": rec_id,
                        "title": rec_title,
                        "classification": "replace_existing_by_source_path",
                        "message": (
                            f"id {rec_id} already exists with different content in {canon_same_id.shard}; "
                            "will replace it because source_path is identical"
                        ),
                    }
                )
                eligible.append(entry)
                stats["replace_existing_by_source_path"] += 1
            else:
                rejected.append(
                    {
                        "line": entry.line_no,
                        "id": rec_id,
                        "title": rec_title,
                        "classification": "conflict_same_id_different_content",
                        "message": f"id {rec_id} already exists with different content in {canon_same_id.shard}",
                    }
                )
                stats["conflict_same_id_different_content"] += 1
            continue

        same_hash = canon_index.by_hash.get(entry.serialized)
        if same_hash:
            first = same_hash[0]
            skipped.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "duplicate_identical",
                    "message": (
                        "candidate content is already present in canon with a different identity; "
                        f"first seen in {first.shard}:{first.line_no}"
                    ),
                }
            )
            stats["duplicate_identical"] += 1
            continue

        source_match = canon_index.by_source_path.get(entry.source_path)
        if source_match is not None and _safe_str(source_match.record.get("id")) != rec_id:
            if allow_replacements:
                entry.replacement = source_match
                warnings.append(
                    {
                        "line": entry.line_no,
                        "id": rec_id,
                        "title": rec_title,
                        "classification": "replace_existing_by_source_path",
                        "message": (
                            f"source_path {entry.source_path} already exists with id "
                            f"{_safe_str(source_match.record.get('id'))}; will replace it"
                        ),
                    }
                )
                eligible.append(entry)
                stats["replace_existing_by_source_path"] += 1
                continue
            rejected.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "conflict_same_source_path_different_id",
                    "message": (
                        f"source_path {entry.source_path} already exists with id "
                        f"{_safe_str(source_match.record.get('id'))}"
                    ),
                }
            )
            stats["conflict_same_source_path_different_id"] += 1
            continue

        sf_existing = canon_index.by_session_family.get(sf_key)
        if sf_existing is not None and _safe_str(sf_existing.record.get("id")) != rec_id:
            if allow_replacements and _safe_str((sf_existing.record.get("source_fields") or {}).get("source_path")) == entry.source_path:
                entry.replacement = sf_existing
                warnings.append(
                    {
                        "line": entry.line_no,
                        "id": rec_id,
                        "title": rec_title,
                        "classification": "replace_existing_by_source_path",
                        "message": (
                            "session_origin + artifact_family already admitted with a different id; "
                            "will replace it because source_path is identical"
                        ),
                    }
                )
                eligible.append(entry)
                stats["replace_existing_by_source_path"] += 1
                continue
            rejected.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "conflict_same_session_family_already_admitted",
                    "message": (
                        "session_origin + artifact_family already admitted with different id "
                        f"{_safe_str(sf_existing.record.get('id'))}"
                    ),
                }
            )
            stats["conflict_same_session_family_already_admitted"] += 1
            continue

        title_matches = canon_index.by_title.get(rec_title, [])
        if any(_safe_str(match.record.get("id")) != rec_id for match in title_matches):
            warnings.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "warning_same_title_different_id",
                    "message": "title already exists in canon with different id; candidate is rejected",
                }
            )
            stats["warning_same_title_different_id"] += 1
            rejected.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "warning_same_title_different_id",
                    "message": "reverse requires unique title set; rejecting this candidate",
                }
            )
            continue

        key_match = canon_index.by_key.get(rec_key)
        if key_match is not None and _safe_str(key_match.record.get("id")) != rec_id:
            rejected.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "warning_same_title_different_id",
                    "message": "key already exists in canon with different id; rejecting candidate",
                }
            )
            stats["warning_same_title_different_id"] += 1
            continue

        slug_match = canon_index.by_slug.get(rec_slug)
        if slug_match is not None and _safe_str(slug_match.record.get("id")) != rec_id:
            rejected.append(
                {
                    "line": entry.line_no,
                    "id": rec_id,
                    "title": rec_title,
                    "classification": "warning_same_title_different_id",
                    "message": "canonical_slug already exists with different id; rejecting candidate",
                }
            )
            stats["warning_same_title_different_id"] += 1
            continue

        eligible.append(entry)
        stats["new_candidate"] += 1

    return eligible, skipped, rejected, warnings, stats


def _replace_status_tags(tags: Any, new_status: str) -> Any:
    if not isinstance(tags, list):
        return tags

    replaced = []
    seen = set()
    replacement_done = False
    for item in tags:
        tag = _safe_str(item)
        if tag == "status:candidate":
            tag = new_status
            replacement_done = True
        if tag not in seen:
            seen.add(tag)
            replaced.append(tag)

    if replacement_done and new_status not in seen:
        replaced.append(new_status)
    return replaced


def _project_candidate_record_as_admitted(record: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(record)
    source_fields = projected.setdefault("source_fields", {})
    source_fields["canonical_status"] = CANON_STATUS_ADMITTED
    for field in ("tags", "source_tags", "normalized_tags"):
        projected[field] = _replace_status_tags(projected.get(field), "status:local_admitted")
    return projected


def _run_normalize(lines: list[dict[str, Any]], work_dir: Path) -> tuple[list[dict[str, Any]], CommandResult]:
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_path = work_dir / "admission_lines.raw.jsonl"
    normalized_path = work_dir / "admission_lines.normalized.jsonl"
    _write_jsonl(raw_path, lines)

    cmd = [
        "go",
        "run",
        "./cmd/canon_preflight",
        "--mode",
        "normalize",
        "--input",
        str(raw_path),
        "--output",
        str(normalized_path),
    ]
    result = _run_command(cmd, cwd=REPO_ROOT / "go" / "canon", env=_go_env())
    if result.returncode != 0:
        raise RuntimeError("canon_preflight normalize failed")

    normalized, rejects = _read_jsonl(normalized_path)
    if rejects:
        raise RuntimeError("normalized output is invalid JSONL")
    return normalized, result


def _prepare_admitted_lines(entries: list[CandidateEntry], work_dir: Path) -> tuple[list[dict[str, Any]], list[CommandResult]]:
    if not entries:
        return [], []

    transformed: list[dict[str, Any]] = []
    for entry in entries:
        record = _project_candidate_record_as_admitted(entry.record)
        transformed.append(record)

    normalized, normalize_result = _run_normalize(transformed, work_dir)

    for line in normalized:
        rec_id = _safe_str(line.get("id"))
        line["raw_payload_ref"] = f"node:{rec_id}" if rec_id else ""

    return normalized, [normalize_result]


def _copy_canon_shards(canon_dir: Path, target_dir: Path) -> list[Path]:
    shard_paths = sorted(canon_dir.glob("tiddlers_*.jsonl"))
    if not shard_paths:
        raise RuntimeError(f"no canon shard files found under {as_display_path(canon_dir)}")

    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for shard_path in shard_paths:
        dst = target_dir / shard_path.name
        shutil.copy2(shard_path, dst)
        copied.append(dst)
    return copied


def _append_lines_to_shard(shard_path: Path, lines: list[dict[str, Any]]) -> None:
    with shard_path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _run_canon_preflight(mode: str, input_path: Path) -> CommandResult:
    return _run_command(
        [
            "go",
            "run",
            "./cmd/canon_preflight",
            "--mode",
            mode,
            "--input",
            str(input_path),
        ],
        cwd=REPO_ROOT / "go" / "canon",
        env=_go_env(),
    )


def _run_reverse_authoritative(
    canon_dir: Path,
    input_html: Path,
    out_html: Path,
    report_path: Path,
) -> CommandResult:
    out_html.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    return _run_command(
        [
            "go",
            "run",
            "./cmd/reverse_tiddlers",
            "--html",
            str(input_html),
            "--canon",
            str(canon_dir),
            "--out-html",
            str(out_html),
            "--report",
            str(report_path),
            "--mode",
            "authoritative-upsert",
        ],
        cwd=REPO_ROOT / "go" / "bridge",
        env=_go_env(),
    )


def _run_test_gates(skip_tests: bool) -> tuple[dict[str, str], list[CommandResult]]:
    if skip_tests:
        return {"go_canon": "skipped", "go_bridge": "skipped", "canon_proposal_fixture": "skipped"}, []

    results: list[CommandResult] = []

    go_canon = _run_command(["go", "test", "./...", "-count=1"], cwd=REPO_ROOT / "go" / "canon", env=_go_env())
    results.append(go_canon)

    go_bridge = _run_command(["go", "test", "./...", "-count=1"], cwd=REPO_ROOT / "go" / "bridge", env=_go_env())
    results.append(go_bridge)

    proposal_fixture = _run_command(
        ["bash", "tests/fixtures/s49/run_canon_proposal_test.sh"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
    )
    results.append(proposal_fixture)

    status = {
        "go_canon": "passed" if go_canon.returncode == 0 else "failed",
        "go_bridge": "passed" if go_bridge.returncode == 0 else "failed",
        "canon_proposal_fixture": "passed" if proposal_fixture.returncode == 0 else "failed",
    }
    return status, results


def _parse_reverse_report(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"inserted": 0, "updated": 0, "already_present": 0, "rejected": 0}

    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {"inserted": 0, "updated": 0, "already_present": 0, "rejected": 0}

    return {
        "inserted": int(payload.get("inserted_count") or 0),
        "updated": int(payload.get("updated_count") or 0),
        "already_present": int(payload.get("already_present_count") or 0),
        "rejected": int(payload.get("rejected_count") or 0),
    }


def _detect_session_id(entries: list[CandidateEntry], candidate_file: Path) -> str:
    sessions = sorted({entry.session_origin for entry in entries if entry.session_origin})
    if len(sessions) == 1:
        return sessions[0]
    if len(sessions) > 1:
        return "multi-session"
    return candidate_file.stem


def _resolve_candidate_file_arg(args: argparse.Namespace, sessions_dir: Path, report_dir: Path | None = None) -> Path:
    candidate_file_arg = getattr(args, "candidate_file", None)
    session_id_arg = getattr(args, "session_id", None)
    all_contracts_arg = bool(getattr(args, "all_contracts", False))

    if all_contracts_arg:
        target_report_dir = report_dir or DEFAULT_REPORT_DIR
        return _generate_contract_candidate_file(sessions_dir, target_report_dir)

    if candidate_file_arg:
        candidate_file = resolve_repo_path(candidate_file_arg, sessions_dir)
        if candidate_file.is_dir():
            raise ValueError(
                "--candidate-file must point to a .canon-candidates.jsonl file, "
                f"not a directory: {as_display_path(candidate_file)}"
            )
        return candidate_file

    if session_id_arg:
        session_id = _safe_str(session_id_arg)
        matches = sorted(sessions_dir.rglob(f"{session_id}.canon-candidates.jsonl"))
        if not matches:
            raise ValueError(
                f"no candidate file found for --session-id {session_id!r} under {as_display_path(sessions_dir)}"
            )
        if len(matches) > 1:
            display_matches = ", ".join(as_display_path(match) for match in matches)
            raise ValueError(
                f"multiple candidate files found for --session-id {session_id!r}; "
                f"use --candidate-file explicitly: {display_matches}"
            )
        return matches[0]

    raise ValueError("provide --all-contracts, --session-id, or --candidate-file")


def _run_canon_proposal_validate(candidate_file: Path, canon_dir: Path) -> CommandResult:
    return _run_command(
        [
            sys.executable,
            "python_scripts/canon_proposal.py",
            "validate",
            "--proposal-file",
            str(candidate_file),
            "--canon-dir",
            str(canon_dir),
            "--allow-existing",
        ],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
    )


def _replace_canon_from_tmp(canon_dir: Path, tmp_canon_dir: Path) -> None:
    target_shards = sorted(tmp_canon_dir.glob("tiddlers_*.jsonl"))
    if not target_shards:
        raise RuntimeError("temporary canon has no shard files")

    for old in canon_dir.glob("tiddlers_*.jsonl"):
        old.unlink()
    for shard in target_shards:
        shutil.copy2(shard, canon_dir / shard.name)


def _build_report_skeleton(
    mode: str,
    run_id: str,
    session_id: str,
    candidate_file: Path | None,
    sessions_dir: Path | None,
    canon_dir: Path,
    tmp_canon_dir: Path | None,
) -> dict[str, Any]:
    return {
        "admission_run_id": run_id,
        "mode": mode,
        "timestamp": _iso_now(),
        "session_id": session_id,
        "candidate_file": as_display_path(candidate_file) if candidate_file else None,
        "sessions_dir": as_display_path(sessions_dir) if sessions_dir else None,
        "canon_dir": as_display_path(canon_dir),
        "tmp_canon_dir": as_display_path(tmp_canon_dir) if tmp_canon_dir else None,
        "canon_before_hash": "",
        "canon_after_hash": "",
        "candidate_count": 0,
        "eligible_count": 0,
        "admitted_count": 0,
        "skipped_duplicates": [],
        "rejected_candidates": [],
        "warnings": [],
        "admitted_ids": [],
        "replaced_ids": [],
        "replacement_count": 0,
        "replacement_records": [],
        "commands_run": [],
        "validation_results": {
            "jsonl": "not_run",
            "proposal": "not_run",
            "strict": "not_run",
            "reverse_preflight": "not_run",
            "reverse_authoritative": "not_run",
            "tests": "not_run",
        },
        "test_results": {},
        "classification_counts": {},
        "reverse_result": {
            "inserted": 0,
            "updated": 0,
            "already_present": 0,
            "rejected": 0,
        },
        "rollback_ready": False,
        "canon_modified": False,
        "status": "fail",
    }


def _write_report(report: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{report['admission_run_id']}.json"
    _write_json(report_path, report)
    return report_path


def _handle_validate(args: argparse.Namespace) -> int:
    sessions_dir = resolve_repo_path(args.sessions_dir, DEFAULT_SESSIONS_DIR)
    canon_dir = resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR)
    report_dir = resolve_repo_path(args.report_dir, DEFAULT_REPORT_DIR)
    candidate_file = _resolve_candidate_file_arg(args, sessions_dir, report_dir)

    validation = _build_candidate_validation(candidate_file, sessions_dir)
    session_id = _detect_session_id(validation.entries, candidate_file)
    run_id = f"validate-{_stamp_now()}-{session_id}"

    report = _build_report_skeleton(
        mode="validate",
        run_id=run_id,
        session_id=session_id,
        candidate_file=candidate_file,
        sessions_dir=sessions_dir,
        canon_dir=canon_dir,
        tmp_canon_dir=None,
    )
    report["canon_before_hash"] = _canon_hash(canon_dir)
    report["canon_after_hash"] = report["canon_before_hash"]
    report["candidate_count"] = len(validation.entries) + len([r for r in validation.rejected if r.get("classification") == "reject_invalid_jsonl"])

    proposal_validate_result = _run_canon_proposal_validate(candidate_file, canon_dir)
    report["commands_run"].append(proposal_validate_result.to_report())

    report["validation_results"]["proposal"] = "passed" if proposal_validate_result.returncode == 0 else "failed"
    report["rejected_candidates"].extend(validation.rejected)
    report["warnings"].extend(validation.warnings)

    eligible, skipped, rejected, extra_warnings, stats = _classify_against_index(validation.entries, canon_index=None)
    report["classification_counts"] = stats
    report["skipped_duplicates"] = skipped
    report["rejected_candidates"].extend(rejected)
    report["warnings"].extend(extra_warnings)
    report["eligible_count"] = len(eligible)

    if validation.invalid_jsonl or validation.rejected or rejected:
        report["validation_results"]["jsonl"] = "failed"
    else:
        report["validation_results"]["jsonl"] = "passed"

    if report["validation_results"]["jsonl"] == "passed" and report["validation_results"]["proposal"] == "passed":
        report["status"] = "ok"

    report_path = _write_report(report, report_dir)

    print(
        json.dumps(
            {
                "mode": "validate",
                "status": report["status"],
                "session_id": session_id,
                "candidate_file": as_display_path(candidate_file),
                "report": as_display_path(report_path),
                "candidate_count": report["candidate_count"],
                "eligible_count": report["eligible_count"],
                "rejected_count": len(report["rejected_candidates"]),
                "canon_modified": False,
            },
            ensure_ascii=False,
        )
    )

    return 0 if report["status"] == "ok" else 2


def _run_dry_pipeline(args: argparse.Namespace, mode: str) -> tuple[int, dict[str, Any], Path]:
    sessions_dir = resolve_repo_path(args.sessions_dir, DEFAULT_SESSIONS_DIR)
    canon_dir = resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR)
    tmp_dir = resolve_repo_path(args.tmp_dir, DEFAULT_TMP_DIR)
    report_dir = resolve_repo_path(args.report_dir, DEFAULT_REPORT_DIR)
    input_html = resolve_repo_path(args.input_html, DEFAULT_INPUT_HTML)
    candidate_file = _resolve_candidate_file_arg(args, sessions_dir, report_dir)

    validation = _build_candidate_validation(candidate_file, sessions_dir)
    session_id = _detect_session_id(validation.entries, candidate_file)
    run_id = f"admit-{_stamp_now()}-{session_id}"

    tmp_run_dir = tmp_dir / run_id
    tmp_canon_dir = tmp_run_dir / "canon"

    report = _build_report_skeleton(
        mode=mode,
        run_id=run_id,
        session_id=session_id,
        candidate_file=candidate_file,
        sessions_dir=sessions_dir,
        canon_dir=canon_dir,
        tmp_canon_dir=tmp_canon_dir,
    )
    report["canon_before_hash"] = _canon_hash(canon_dir)
    report["candidate_count"] = len(validation.entries) + len([r for r in validation.rejected if r.get("classification") == "reject_invalid_jsonl"])
    report["rejected_candidates"].extend(validation.rejected)
    report["warnings"].extend(validation.warnings)

    if mode == "apply" and not args.confirm_apply:
        report["canon_after_hash"] = report["canon_before_hash"]
        report["rejected_candidates"].append(
            {
                "line": 0,
                "classification": "reject_apply_without_confirmation",
                "message": "apply requires explicit --confirm-apply before admission gates are run",
            }
        )
        report_path = _write_report(report, report_dir)
        return 2, report, report_path

    proposal_validate_result = _run_canon_proposal_validate(candidate_file, canon_dir)
    report["commands_run"].append(proposal_validate_result.to_report())
    report["validation_results"]["proposal"] = "passed" if proposal_validate_result.returncode == 0 else "failed"

    canon_index = _load_canon_index(canon_dir)
    allow_replacements = bool(getattr(args, "allow_replacements", False) or getattr(args, "all_contracts", False))
    eligible, skipped, rejected, extra_warnings, stats = _classify_against_index(
        validation.entries,
        canon_index,
        allow_replacements=allow_replacements,
    )
    report["classification_counts"] = stats
    report["eligible_count"] = len(eligible)
    report["skipped_duplicates"] = skipped
    report["rejected_candidates"].extend(rejected)
    report["warnings"].extend(extra_warnings)
    replacement_entries = [entry for entry in eligible if entry.replacement is not None]
    replacement_records = [entry.replacement.record for entry in replacement_entries if entry.replacement is not None]
    replaced_ids = sorted(
        {
            _safe_str(entry.replacement.record.get("id"))
            for entry in replacement_entries
            if entry.replacement is not None and _safe_str(entry.replacement.record.get("id"))
        }
    )
    report["replacement_count"] = len(replaced_ids)
    report["replaced_ids"] = replaced_ids
    report["replacement_records"] = replacement_records

    if validation.invalid_jsonl or validation.rejected:
        report["validation_results"]["jsonl"] = "failed"
    else:
        report["validation_results"]["jsonl"] = "passed"

    if report["validation_results"]["jsonl"] != "passed" or report["validation_results"]["proposal"] != "passed":
        report_path = _write_report(report, report_dir)
        return 2, report, report_path

    if report["rejected_candidates"]:
        report_path = _write_report(report, report_dir)
        return 2, report, report_path

    try:
        normalized_lines, normalize_commands = _prepare_admitted_lines(eligible, tmp_run_dir)
    except RuntimeError as exc:
        report["validation_results"]["strict"] = "failed"
        report["rejected_candidates"].append(
            {
                "line": 0,
                "classification": "reject_missing_required_fields",
                "message": str(exc),
            }
        )
        report_path = _write_report(report, report_dir)
        return 2, report, report_path

    for command in normalize_commands:
        report["commands_run"].append(command.to_report())

    admitted_ids = [_safe_str(line.get("id")) for line in normalized_lines if _safe_str(line.get("id"))]
    report["admitted_ids"] = admitted_ids
    report["admitted_count"] = len(admitted_ids)

    try:
        copied_shards = _copy_canon_shards(canon_dir, tmp_canon_dir)
    except RuntimeError as exc:
        report["rejected_candidates"].append(
            {
                "line": 0,
                "classification": "reject_missing_required_fields",
                "message": str(exc),
            }
        )
        report_path = _write_report(report, report_dir)
        return 2, report, report_path

    target_shard = copied_shards[-1]
    if replaced_ids:
        removed_count, removed_ids = _remove_ids_from_canon(tmp_canon_dir, set(replaced_ids))
        if removed_count != len(replaced_ids):
            report["rejected_candidates"].append(
                {
                    "line": 0,
                    "classification": "reject_replacement_mismatch",
                    "message": (
                        f"expected to remove {len(replaced_ids)} replaced id(s), "
                        f"removed {removed_count}: {removed_ids}"
                    ),
                }
            )
            report_path = _write_report(report, report_dir)
            return 2, report, report_path

    if normalized_lines:
        _append_lines_to_shard(target_shard, normalized_lines)

    strict_result = _run_canon_preflight("strict", tmp_canon_dir)
    report["commands_run"].append(strict_result.to_report())
    report["validation_results"]["strict"] = "passed" if strict_result.returncode == 0 else "failed"
    if strict_result.returncode != 0:
        report_path = _write_report(report, report_dir)
        return 2, report, report_path

    reverse_preflight_result = _run_canon_preflight("reverse-preflight", tmp_canon_dir)
    report["commands_run"].append(reverse_preflight_result.to_report())
    report["validation_results"]["reverse_preflight"] = (
        "passed" if reverse_preflight_result.returncode == 0 else "failed"
    )
    if reverse_preflight_result.returncode != 0:
        report_path = _write_report(report, report_dir)
        return 2, report, report_path

    reverse_html = tmp_run_dir / "reverse_html" / f"{run_id}.derived.html"
    reverse_report_path = tmp_run_dir / "reverse_html" / f"{run_id}.reverse-report.json"
    reverse_result = _run_reverse_authoritative(
        canon_dir=tmp_canon_dir,
        input_html=input_html,
        out_html=reverse_html,
        report_path=reverse_report_path,
    )
    report["commands_run"].append(reverse_result.to_report())
    report["validation_results"]["reverse_authoritative"] = "passed" if reverse_result.returncode == 0 else "failed"
    report["reverse_result"] = _parse_reverse_report(reverse_report_path)

    if reverse_result.returncode != 0 or report["reverse_result"]["rejected"] > 0:
        report["validation_results"]["reverse_authoritative"] = "failed"
        report_path = _write_report(report, report_dir)
        return 2, report, report_path

    test_results, test_commands = _run_test_gates(skip_tests=args.skip_tests)
    for command in test_commands:
        report["commands_run"].append(command.to_report())
    report["test_results"] = test_results

    if any(status == "failed" for status in test_results.values()):
        report["validation_results"]["tests"] = "failed"
        report_path = _write_report(report, report_dir)
        return 2, report, report_path
    report["validation_results"]["tests"] = "skipped" if args.skip_tests else "passed"

    if mode == "dry-run":
        report["canon_after_hash"] = _canon_hash(tmp_canon_dir)
        report["rollback_ready"] = False
        report["canon_modified"] = False
        report["status"] = "ok"
        report_path = _write_report(report, report_dir)
        return 0, report, report_path

    if mode == "apply":
        backup_dir = report_dir / "backups" / run_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        for shard in sorted(canon_dir.glob("tiddlers_*.jsonl")):
            shutil.copy2(shard, backup_dir / shard.name)

        if normalized_lines:
            _replace_canon_from_tmp(canon_dir, tmp_canon_dir)
            report["canon_modified"] = True

        report["backup_dir"] = as_display_path(backup_dir)
        report["canon_after_hash"] = _canon_hash(canon_dir)
        report["rollback_ready"] = bool(normalized_lines)
        report["status"] = "ok"
        report_path = _write_report(report, report_dir)
        return 0, report, report_path

    report_path = _write_report(report, report_dir)
    return 2, report, report_path


def _handle_dry_run(args: argparse.Namespace) -> int:
    code, report, report_path = _run_dry_pipeline(args, mode="dry-run")
    print(
        json.dumps(
            {
                "mode": "dry-run",
                "status": report["status"],
                "session_id": report["session_id"],
                "report": as_display_path(report_path),
                "candidate_count": report["candidate_count"],
                "eligible_count": report["eligible_count"],
                "admitted_count": report["admitted_count"],
                "replacement_count": report["replacement_count"],
                "rejected_count": len(report["rejected_candidates"]),
                "reverse_rejected": report["reverse_result"]["rejected"],
                "canon_modified": report["canon_modified"],
            },
            ensure_ascii=False,
        )
    )
    return code


def _handle_apply(args: argparse.Namespace) -> int:
    code, report, report_path = _run_dry_pipeline(args, mode="apply")
    print(
        json.dumps(
            {
                "mode": "apply",
                "status": report["status"],
                "session_id": report["session_id"],
                "report": as_display_path(report_path),
                "candidate_count": report["candidate_count"],
                "eligible_count": report["eligible_count"],
                "admitted_count": report["admitted_count"],
                "replacement_count": report["replacement_count"],
                "rejected_count": len(report["rejected_candidates"]),
                "reverse_rejected": report["reverse_result"]["rejected"],
                "canon_modified": report["canon_modified"],
                "rollback_ready": report["rollback_ready"],
            },
            ensure_ascii=False,
        )
    )
    return code


def _remove_ids_from_canon(canon_dir: Path, ids_to_remove: set[str]) -> tuple[int, list[str]]:
    removed_ids: list[str] = []
    for shard_path in sorted(canon_dir.glob("tiddlers_*.jsonl")):
        kept_lines: list[str] = []
        with shard_path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                stripped = raw.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    kept_lines.append(raw)
                    continue
                rec_id = _safe_str(record.get("id"))
                if rec_id in ids_to_remove:
                    removed_ids.append(rec_id)
                    continue
                kept_lines.append(raw)

        with shard_path.open("w", encoding="utf-8") as handle:
            for line in kept_lines:
                handle.write(line.rstrip("\n"))
                handle.write("\n")

    return len(removed_ids), sorted(set(removed_ids))


def _handle_rollback(args: argparse.Namespace) -> int:
    canon_dir = resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR)
    report_dir = resolve_repo_path(args.report_dir, DEFAULT_REPORT_DIR)
    tmp_dir = resolve_repo_path(args.tmp_dir, DEFAULT_TMP_DIR)
    input_html = resolve_repo_path(args.input_html, DEFAULT_INPUT_HTML)
    admission_report_path = resolve_repo_path(args.admission_report, DEFAULT_REPORT_DIR)

    if not admission_report_path.exists():
        print(
            json.dumps(
                {
                    "mode": "rollback",
                    "status": "fail",
                    "message": f"admission report does not exist: {as_display_path(admission_report_path)}",
                },
                ensure_ascii=False,
            )
        )
        return 2

    admission_report = _load_json(admission_report_path)
    if not isinstance(admission_report, dict):
        print(json.dumps({"mode": "rollback", "status": "fail", "message": "invalid admission report JSON"}, ensure_ascii=False))
        return 2

    admitted_ids = sorted({_safe_str(item) for item in admission_report.get("admitted_ids") or [] if _safe_str(item)})
    replacement_records = [
        item for item in admission_report.get("replacement_records") or [] if isinstance(item, dict)
    ]
    session_id = _safe_str(admission_report.get("session_id")) or "unknown-session"
    run_id = f"rollback-{_stamp_now()}-{session_id}"

    report = {
        "admission_run_id": run_id,
        "mode": "rollback",
        "timestamp": _iso_now(),
        "session_id": session_id,
        "admission_report": as_display_path(admission_report_path),
        "canon_dir": as_display_path(canon_dir),
        "canon_before_hash": _canon_hash(canon_dir),
        "canon_after_hash": "",
        "requested_ids": admitted_ids,
        "replacement_records_requested": len(replacement_records),
        "removed_ids": [],
        "removed_count": 0,
        "restored_replacement_count": 0,
        "commands_run": [],
        "validation_results": {
            "strict": "not_run",
            "reverse_preflight": "not_run",
            "reverse_authoritative": "not_run",
        },
        "reverse_result": {
            "inserted": 0,
            "updated": 0,
            "already_present": 0,
            "rejected": 0,
        },
        "dry_run": bool(args.dry_run),
        "status": "fail",
        "warnings": [],
    }

    if not admitted_ids:
        report["warnings"].append("admission report has no admitted_ids; nothing to rollback")
        report["canon_after_hash"] = report["canon_before_hash"]
        rollback_report_path = _write_report(report, report_dir)
        print(
            json.dumps(
                {
                    "mode": "rollback",
                    "status": report["status"],
                    "report": as_display_path(rollback_report_path),
                    "removed_count": 0,
                    "canon_modified": False,
                },
                ensure_ascii=False,
            )
        )
        return 2

    expected_hash = _safe_str(admission_report.get("canon_after_hash"))
    if expected_hash and expected_hash != report["canon_before_hash"] and not args.force:
        report["warnings"].append(
            "current canon hash differs from admission_report canon_after_hash; use --force to continue"
        )
        report["canon_after_hash"] = report["canon_before_hash"]
        rollback_report_path = _write_report(report, report_dir)
        print(
            json.dumps(
                {
                    "mode": "rollback",
                    "status": report["status"],
                    "report": as_display_path(rollback_report_path),
                    "removed_count": 0,
                    "canon_modified": False,
                },
                ensure_ascii=False,
            )
        )
        return 2

    tmp_run_dir = tmp_dir / run_id
    tmp_canon_dir = tmp_run_dir / "canon"

    try:
        _copy_canon_shards(canon_dir, tmp_canon_dir)
    except RuntimeError as exc:
        report["warnings"].append(str(exc))
        report["canon_after_hash"] = report["canon_before_hash"]
        rollback_report_path = _write_report(report, report_dir)
        print(
            json.dumps(
                {
                    "mode": "rollback",
                    "status": report["status"],
                    "report": as_display_path(rollback_report_path),
                    "removed_count": 0,
                    "canon_modified": False,
                },
                ensure_ascii=False,
            )
        )
        return 2

    removed_count, removed_ids = _remove_ids_from_canon(tmp_canon_dir, set(admitted_ids))
    report["removed_count"] = removed_count
    report["removed_ids"] = removed_ids
    if replacement_records:
        target_shards = sorted(tmp_canon_dir.glob("tiddlers_*.jsonl"))
        if not target_shards:
            report["warnings"].append("temporary canon has no shard files for replacement restore")
            report["canon_after_hash"] = report["canon_before_hash"]
            rollback_report_path = _write_report(report, report_dir)
            print(
                json.dumps(
                    {
                        "mode": "rollback",
                        "status": report["status"],
                        "report": as_display_path(rollback_report_path),
                        "removed_count": 0,
                        "canon_modified": False,
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        _append_lines_to_shard(target_shards[-1], replacement_records)
        report["restored_replacement_count"] = len(replacement_records)

    strict_result = _run_canon_preflight("strict", tmp_canon_dir)
    report["commands_run"].append(strict_result.to_report())
    report["validation_results"]["strict"] = "passed" if strict_result.returncode == 0 else "failed"
    if strict_result.returncode != 0:
        report["canon_after_hash"] = report["canon_before_hash"]
        rollback_report_path = _write_report(report, report_dir)
        print(
            json.dumps(
                {
                    "mode": "rollback",
                    "status": report["status"],
                    "report": as_display_path(rollback_report_path),
                    "removed_count": 0,
                    "canon_modified": False,
                },
                ensure_ascii=False,
            )
        )
        return 2

    reverse_preflight_result = _run_canon_preflight("reverse-preflight", tmp_canon_dir)
    report["commands_run"].append(reverse_preflight_result.to_report())
    report["validation_results"]["reverse_preflight"] = (
        "passed" if reverse_preflight_result.returncode == 0 else "failed"
    )
    if reverse_preflight_result.returncode != 0:
        report["canon_after_hash"] = report["canon_before_hash"]
        rollback_report_path = _write_report(report, report_dir)
        print(
            json.dumps(
                {
                    "mode": "rollback",
                    "status": report["status"],
                    "report": as_display_path(rollback_report_path),
                    "removed_count": 0,
                    "canon_modified": False,
                },
                ensure_ascii=False,
            )
        )
        return 2

    reverse_html = tmp_run_dir / "reverse_html" / f"{run_id}.derived.html"
    reverse_report = tmp_run_dir / "reverse_html" / f"{run_id}.reverse-report.json"
    reverse_result = _run_reverse_authoritative(tmp_canon_dir, input_html, reverse_html, reverse_report)
    report["commands_run"].append(reverse_result.to_report())
    report["validation_results"]["reverse_authoritative"] = "passed" if reverse_result.returncode == 0 else "failed"
    report["reverse_result"] = _parse_reverse_report(reverse_report)

    if reverse_result.returncode != 0 or report["reverse_result"]["rejected"] > 0:
        report["validation_results"]["reverse_authoritative"] = "failed"
        report["canon_after_hash"] = report["canon_before_hash"]
        rollback_report_path = _write_report(report, report_dir)
        print(
            json.dumps(
                {
                    "mode": "rollback",
                    "status": report["status"],
                    "report": as_display_path(rollback_report_path),
                    "removed_count": 0,
                    "canon_modified": False,
                },
                ensure_ascii=False,
            )
        )
        return 2

    if not args.dry_run:
        backup_dir = report_dir / "backups" / f"{run_id}-pre"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for shard in sorted(canon_dir.glob("tiddlers_*.jsonl")):
            shutil.copy2(shard, backup_dir / shard.name)
        _replace_canon_from_tmp(canon_dir, tmp_canon_dir)
        report["backup_dir"] = as_display_path(backup_dir)

    report["canon_after_hash"] = report["canon_before_hash"] if args.dry_run else _canon_hash(canon_dir)
    report["status"] = "ok"

    rollback_report_path = _write_report(report, report_dir)
    print(
        json.dumps(
                {
                    "mode": "rollback",
                    "status": report["status"],
                    "report": as_display_path(rollback_report_path),
                    "removed_count": report["removed_count"],
                    "restored_replacement_count": report["restored_replacement_count"],
                    "canon_modified": not args.dry_run,
                },
            ensure_ascii=False,
        )
    )
    return 0


def _shared_mode_arguments(subparser: argparse.ArgumentParser) -> None:
    candidate_source = subparser.add_mutually_exclusive_group(required=True)
    candidate_source.add_argument(
        "--all-contracts",
        action="store_true",
        help=(
            "Generate candidates for every data/sessions/00_contratos/*.md.json "
            "and admit missing contract artifacts"
        ),
    )
    candidate_source.add_argument(
        "--session-id",
        help=(
            "Session id to admit; resolves SESSION_ID.canon-candidates.jsonl "
            "anywhere under --sessions-dir"
        ),
    )
    candidate_source.add_argument(
        "--candidate-file",
        help="Advanced: explicit JSONL file with session candidate lines",
    )
    subparser.add_argument(
        "--canon-dir",
        default=as_display_path(DEFAULT_CANON_DIR),
        help="Canon shard directory (default: data/out/local)",
    )
    subparser.add_argument(
        "--sessions-dir",
        default=as_display_path(DEFAULT_SESSIONS_DIR),
        help="Session artifacts root (default: data/sessions)",
    )
    subparser.add_argument(
        "--tmp-dir",
        default=as_display_path(DEFAULT_TMP_DIR),
        help="Temporary admission working dir (default: data/tmp/session_admission)",
    )
    subparser.add_argument(
        "--report-dir",
        default=as_display_path(DEFAULT_REPORT_DIR),
        help="Admission report output dir (default: data/tmp/admissions)",
    )
    subparser.add_argument(
        "--input-html",
        default=as_display_path(DEFAULT_INPUT_HTML),
        help="Base HTML used by reverse gates (default: data/in/tiddly-data-converter (Saved).html)",
    )
    subparser.add_argument(
        "--allow-replacements",
        action="store_true",
        help=(
            "Allow controlled replacement when the same source_path is already in canon "
            "with an older id/content; rollback stores the replaced records"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate, dry-run, apply, and rollback admission of session candidate canon lines "
            "without blind append."
        )
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate candidate JSONL without modifying canon")
    _shared_mode_arguments(validate_parser)
    validate_parser.set_defaults(func=_handle_validate)

    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Run full admission gates on a temporary canon copy and emit a report",
    )
    _shared_mode_arguments(dry_run_parser)
    dry_run_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip go test and fixture test gates (not recommended)",
    )
    dry_run_parser.set_defaults(func=_handle_dry_run)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Run full gates and apply to canon only with explicit confirmation",
    )
    _shared_mode_arguments(apply_parser)
    apply_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip go test and fixture test gates (not recommended)",
    )
    apply_parser.add_argument(
        "--confirm-apply",
        action="store_true",
        help="Required explicit confirmation before admission gates can write data/out/local/tiddlers_*.jsonl",
    )
    apply_parser.set_defaults(func=_handle_apply)

    rollback_parser = subparsers.add_parser(
        "rollback",
        help="Rollback a previous apply run using its admission report",
    )
    rollback_parser.add_argument(
        "--admission-report",
        required=True,
        help="Path to a previous apply report under data/tmp/admissions",
    )
    rollback_parser.add_argument(
        "--canon-dir",
        default=as_display_path(DEFAULT_CANON_DIR),
        help="Canon shard directory (default: data/out/local)",
    )
    rollback_parser.add_argument(
        "--tmp-dir",
        default=as_display_path(DEFAULT_TMP_DIR),
        help="Temporary rollback working dir (default: data/tmp/session_admission)",
    )
    rollback_parser.add_argument(
        "--report-dir",
        default=as_display_path(DEFAULT_REPORT_DIR),
        help="Rollback report output dir (default: data/tmp/admissions)",
    )
    rollback_parser.add_argument(
        "--input-html",
        default=as_display_path(DEFAULT_INPUT_HTML),
        help="Base HTML used by reverse gates (default: data/in/tiddly-data-converter (Saved).html)",
    )
    rollback_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate rollback effects without modifying canon",
    )
    rollback_parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if current canon hash differs from admission report canon_after_hash",
    )
    rollback_parser.set_defaults(func=_handle_rollback)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
