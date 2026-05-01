#!/usr/bin/env python3
"""Create and validate legacy proposal JSONL files for extraordinary canon batches."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from path_governance import (
    DEFAULT_CANON_DIR,
    DEFAULT_PROPOSALS_FILE,
    as_display_path,
    ensure_runtime_directories,
    proposals_path,
    resolve_repo_path,
    sorted_canon_shards,
)


REQUIRED_CANON_LINE_FIELDS = (
    "schema_version",
    "id",
    "key",
    "title",
    "canonical_slug",
    "version_id",
)

REQUIRED_SESSION_PROPOSAL_FIELDS = (
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

REPO_ROOT = Path(__file__).resolve().parents[1]
CANON_GO_DIR = REPO_ROOT / "go" / "canon"


def _load_json_objects(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path} is empty")
    if path.suffix == ".jsonl":
        records = []
        for lineno, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{lineno} is not a JSON object")
            records.append(record)
        if not records:
            raise ValueError(f"{path} does not contain JSONL objects")
        return records
    record = json.loads(text)
    if not isinstance(record, dict):
        raise ValueError(f"{path} is not a JSON object")
    return [record]


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _run_canon_preflight(mode: str, input_path: Path, output_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GOCACHE", str(Path(tempfile.gettempdir()) / "go-build-canon-proposal"))
    cmd = [
        "go",
        "run",
        "./cmd/canon_preflight",
        "--mode",
        mode,
        "--input",
        str(input_path),
    ]
    if output_path is not None:
        cmd.extend(["--output", str(output_path)])
    return subprocess.run(
        cmd,
        cwd=CANON_GO_DIR,
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def _normalize_lines(lines: list[dict]) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="canon_proposal_normalize_") as tmp_dir:
        input_path = Path(tmp_dir) / "input.jsonl"
        output_path = Path(tmp_dir) / "output.jsonl"
        _write_jsonl(input_path, lines)
        result = _run_canon_preflight("normalize", input_path, output_path)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"canon_preflight normalize failed: {detail}")
        return _load_json_objects(output_path)


def _strict_validate_jsonl(path: Path) -> list[str]:
    result = _run_canon_preflight("strict", path)
    if result.returncode == 0:
        return []

    detail = (result.stderr or result.stdout).strip()
    errors = [f"canon_preflight strict failed for {as_display_path(path)}"]
    if detail:
        errors.append(detail)
    return errors


def _load_canon_index(canon_dir: Path) -> tuple[set[str], set[str], set[str]]:
    ids: set[str] = set()
    keys: set[str] = set()
    titles: set[str] = set()
    for shard_path in sorted_canon_shards(canon_dir):
        for raw_line in shard_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                if record.get("id"):
                    ids.add(record["id"])
                if record.get("key"):
                    keys.add(record["key"])
                if record.get("title"):
                    titles.add(record["title"])
    return ids, keys, titles


def validate_lines(lines: list[dict], canon_dir: Path | None, allow_existing: bool) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    seen_titles: set[str] = set()

    canon_ids: set[str] = set()
    canon_keys: set[str] = set()
    canon_titles: set[str] = set()
    if canon_dir is not None and canon_dir.exists():
        canon_ids, canon_keys, canon_titles = _load_canon_index(canon_dir)

    try:
        normalized_lines = _normalize_lines(lines)
    except RuntimeError as exc:
        return [str(exc)]

    if normalized_lines != lines:
        errors.append(
            "proposal file is not canonized; normalize it first or create it via python_scripts/canon_proposal.py"
        )

    for idx, line in enumerate(lines, start=1):
        if not isinstance(line, dict):
            errors.append(f"line {idx}: proposal entry must be a JSON object")
            continue

        for field in REQUIRED_SESSION_PROPOSAL_FIELDS:
            if field not in line:
                errors.append(f"line {idx}: missing canonical proposal field {field}")

        for field in REQUIRED_CANON_LINE_FIELDS:
            if field not in line:
                errors.append(f"line {idx}: missing field {field}")

        if line.get("schema_version") != "v0":
            errors.append(f"line {idx}: schema_version must be 'v0'")

        record_id = line.get("id")
        record_key = line.get("key")
        record_title = line.get("title")

        if record_id and line.get("raw_payload_ref") not in {"", None, f"node:{record_id}"}:
            errors.append(
                f"line {idx}: raw_payload_ref must match node:<id> for canonized proposals"
            )

        order_in_document = line.get("order_in_document")
        if not isinstance(order_in_document, int) or order_in_document < 1:
            errors.append(f"line {idx}: order_in_document must be a positive integer")

        section_path = line.get("section_path")
        if not isinstance(section_path, list) or not section_path:
            errors.append(f"line {idx}: section_path must be a non-empty array")

        tags = line.get("tags")
        if not isinstance(tags, list) or not tags:
            errors.append(f"line {idx}: tags must be a non-empty array")

        taxonomy_path = line.get("taxonomy_path")
        if not isinstance(taxonomy_path, list) or not taxonomy_path:
            errors.append(f"line {idx}: taxonomy_path must be a non-empty array")

        source_tags = line.get("source_tags")
        if not isinstance(source_tags, list) or not source_tags:
            errors.append(f"line {idx}: source_tags must be a non-empty array")

        normalized_tags = line.get("normalized_tags")
        if not isinstance(normalized_tags, list) or not normalized_tags:
            errors.append(f"line {idx}: normalized_tags must be a non-empty array")

        source_fields = line.get("source_fields")
        if not isinstance(source_fields, dict) or not source_fields:
            errors.append(f"line {idx}: source_fields must be a non-empty object")

        content = line.get("content")
        if not isinstance(content, dict) or "plain" not in content:
            errors.append(f"line {idx}: content.plain must be present in canonized proposals")

        if record_id:
            if record_id in seen_ids:
                errors.append(f"line {idx}: duplicate id inside proposal file: {record_id}")
            seen_ids.add(record_id)
            if record_id in canon_ids and not allow_existing:
                errors.append(f"line {idx}: id already exists in canon: {record_id}")

        if record_key:
            if record_key in seen_keys:
                errors.append(f"line {idx}: duplicate key inside proposal file: {record_key}")
            seen_keys.add(record_key)
            if record_key in canon_keys and not allow_existing:
                errors.append(f"line {idx}: key already exists in canon: {record_key}")

        if record_title:
            if record_title in seen_titles:
                errors.append(
                    f"line {idx}: duplicate title inside proposal file: {record_title}"
                )
            seen_titles.add(record_title)
            if record_title in canon_titles and not allow_existing:
                errors.append(
                    f"line {idx}: title already exists in canon: {record_title}"
                )

    return errors


def cmd_create(args: argparse.Namespace) -> int:
    ensure_runtime_directories()
    canon_dir = resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR)
    output_path = resolve_repo_path(args.output, proposals_path())

    raw_lines: list[dict] = []
    for payload_file in args.payload_file:
        payload_path = resolve_repo_path(payload_file, DEFAULT_CANON_DIR)
        raw_lines.extend(_load_json_objects(payload_path))

    try:
        lines = _normalize_lines(raw_lines)
    except RuntimeError as exc:
        print(f"[canon_proposal] ERROR: {exc}", file=sys.stderr)
        return 2

    existing_lines: list[dict] = []
    if output_path.exists():
        existing_lines = _load_json_objects(output_path)

    combined_lines = existing_lines + lines
    errors = validate_lines(combined_lines, canon_dir, args.allow_existing)
    if errors:
        for error in errors:
            print(f"[canon_proposal] ERROR: {error}", file=sys.stderr)
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_path, combined_lines)

    strict_errors = _strict_validate_jsonl(output_path)
    if strict_errors:
        for error in strict_errors:
            print(f"[canon_proposal] ERROR: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "session": args.session,
                "appended_line_count": len(lines),
                "total_line_count": len(combined_lines),
                "output": as_display_path(output_path),
                "allow_existing": args.allow_existing,
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    proposal_path = resolve_repo_path(args.proposal_file, DEFAULT_CANON_DIR)
    canon_dir = resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR)
    lines = _load_json_objects(proposal_path)
    errors = validate_lines(lines, canon_dir, args.allow_existing)
    errors.extend(_strict_validate_jsonl(proposal_path))
    if errors:
        for error in errors:
            print(f"[canon_proposal] ERROR: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "proposal_file": as_display_path(proposal_path),
                "line_count": len(lines),
                "canon_dir": as_display_path(canon_dir),
                "status": "ok",
                "allow_existing": args.allow_existing,
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and validate legacy proposal JSONL files for extraordinary canon batches."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create",
        help="Append canonized proposal lines into a legacy proposal JSONL file.",
    )
    create_parser.add_argument("--session", help="Session id for reporting context.")
    create_parser.add_argument(
        "--payload-file",
        required=True,
        action="append",
        help="JSON or JSONL file containing proposal line objects. Repeatable.",
    )
    create_parser.add_argument(
        "--canon-dir",
        default=as_display_path(DEFAULT_CANON_DIR),
        help="Canon shard directory used to detect collisions (default: data/out/local)",
    )
    create_parser.add_argument(
        "--output",
        default=as_display_path(DEFAULT_PROPOSALS_FILE),
        help="Legacy proposal JSONL file to append into (default: data/out/local/proposals.jsonl)",
    )
    create_parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="Allow ids/keys/titles that already exist in canon.",
    )
    create_parser.set_defaults(func=cmd_create)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a session proposal JSONL file against the canon.",
    )
    validate_parser.add_argument("--proposal-file", required=True, help="JSONL file to validate.")
    validate_parser.add_argument(
        "--canon-dir",
        default=as_display_path(DEFAULT_CANON_DIR),
        help="Canon shard directory used to detect collisions (default: data/out/local)",
    )
    validate_parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="Allow ids/keys/titles that already exist in canon.",
    )
    validate_parser.set_defaults(func=cmd_validate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[canon_proposal] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
