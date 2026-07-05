#!/usr/bin/env python3
"""S0149 authority-aware semantic_text sidecar builder.

This wrapper reuses the deterministic S0144 semantic_text builder, adds an
authority-level header, and writes experimental outputs under
data/out/local/pipeline/semantic_text_authority/s0149. It never writes canon
shards and does not overwrite the S0144 sidecar path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import semantic_text_builder as base


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_SESSION = "S0149"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "semantic_text_authority" / "s0149"
SCHEMA = "semantic-text-authority-aware-build/v1"
SEMANTIC_TEXT_VERSION = "semantic-text-authority-aware/v1"

AUTHORITY_HEADERS = {
    "current_verified": "Este tiddler representa un artefacto actual verificado del repositorio.",
    "historical_snapshot": "Este tiddler representa o describe un artefacto histórico, divergente o no vigente del repositorio.",
    "narrative_reference": "Este tiddler documenta o menciona contenido técnico, pero no debe tratarse como archivo vigente del repositorio.",
    "generated_derivative": "Este tiddler corresponde a una salida derivada o generada por pipeline.",
    "external_reference": "Este tiddler corresponde a una referencia técnica externa al repositorio local.",
    "unknown": "La autoridad técnica de este tiddler no está determinada.",
}

REVIEW_COLUMNS = [
    "id",
    "title",
    "artifact_family",
    "authority_level",
    "mode",
    "semantic_text_chars",
    "semantic_text_sha256",
    "warnings",
]


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authority_level_for(record: dict[str, Any]) -> str:
    source_fields = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    raw = (
        source_fields.get("authority_level")
        or record.get("authority_level")
        or source_fields.get("candidate_authority_level")
        or record.get("candidate_authority_level")
        or "unknown"
    )
    value = base.normalize_text(raw)
    return value if value in AUTHORITY_HEADERS else "unknown"


def output_paths(out_dir: Path, session: str) -> dict[str, Path]:
    prefix = session.lower()
    return {
        "records": out_dir / f"{prefix}_semantic_text_authority_records.jsonl",
        "index": out_dir / f"{prefix}_semantic_text_authority_index.json",
        "coverage_report": out_dir / f"{prefix}_semantic_text_authority_coverage_report.json",
        "summary": out_dir / f"{prefix}_semantic_text_authority_summary.md",
        "review": out_dir / f"{prefix}_semantic_text_authority_review.csv",
        "hashes": out_dir / f"{prefix}_semantic_text_authority_hashes.json",
    }


def authority_record(canon_record: dict[str, Any], semantic_record: dict[str, Any], *, mode: str, source_session: str) -> dict[str, Any]:
    authority = authority_level_for(canon_record)
    header = AUTHORITY_HEADERS[authority]
    semantic_text = (
        "# Autoridad técnica\n"
        f"authority_level: {authority}\n"
        f"{header}\n\n"
        + semantic_record["semantic_text"]
    )
    semantic_hash = sha256_text(semantic_text)
    warnings = sorted(set([*semantic_record.get("warnings", []), f"authority:{authority}"]))
    return {
        "id": semantic_record["id"],
        "title": semantic_record["title"],
        "artifact_family": semantic_record["artifact_family"],
        "authority_level": authority,
        "authority_statement": header,
        "semantic_text": semantic_text,
        "semantic_text_version": SEMANTIC_TEXT_VERSION,
        "semantic_text_sha256": semantic_hash,
        "source_record_sha256": semantic_record["source_record_sha256"],
        "source_semantic_text_sha256": semantic_record["semantic_text_sha256"],
        "sections_included": ["authority_header", *semantic_record["sections_included"]],
        "mode": mode,
        "preview": mode == "preview",
        "generate": mode == "generate",
        "authority_aware": True,
        "source_session": source_session,
        "dry_run": mode == "preview",
        "modified_canon": False,
        "canon_modified": False,
        "relations_generated": False,
        "candidate_relations_generated": False,
        "warnings": warnings,
    }


def build_index(records: list[dict[str, Any]], *, mode: str, source_session: str) -> dict[str, Any]:
    by_authority = Counter(record["authority_level"] for record in records)
    by_family = Counter(record["artifact_family"] for record in records)
    return {
        "schema": "semantic-text-authority-index/v1",
        "session": source_session,
        "source_session": source_session,
        "mode": mode,
        "authority_aware": True,
        "modified_canon": False,
        "record_count": len(records),
        "by_authority_level": dict(sorted(by_authority.items())),
        "by_artifact_family": dict(sorted(by_family.items())),
        "records": {
            record["id"]: {
                "title": record["title"],
                "artifact_family": record["artifact_family"],
                "authority_level": record["authority_level"],
                "semantic_text_sha256": record["semantic_text_sha256"],
            }
            for record in sorted(records, key=lambda item: (item["id"], item["title"]))
        },
    }


def build_coverage_report(records: list[dict[str, Any]], *, mode: str, source_session: str) -> dict[str, Any]:
    by_authority: dict[str, dict[str, int]] = {}
    for record in records:
        bucket = by_authority.setdefault(
            record["authority_level"],
            {
                "total_records": 0,
                "records_with_semantic_text": 0,
            },
        )
        bucket["total_records"] += 1
        bucket["records_with_semantic_text"] += int(bool(record["semantic_text"]))
    return {
        "schema": "semantic-text-authority-coverage-report/v1",
        "session": source_session,
        "source_session": source_session,
        "mode": mode,
        "authority_aware": True,
        "modified_canon": False,
        "canon_modified": False,
        "semantic_text_version": SEMANTIC_TEXT_VERSION,
        "total_records": len(records),
        "records_with_semantic_text": sum(1 for record in records if record["semantic_text"]),
        "authority_levels_detected": sorted(by_authority),
        "by_authority_level": dict(sorted(by_authority.items())),
        "relations_generated": False,
        "candidate_relations_generated": False,
        "embeddings_executed": False,
    }


def summary_md(report: dict[str, Any]) -> str:
    lines = [
        "# S0149 semantic_text authority-aware summary",
        "",
        f"- mode: {report['mode']}",
        "- authority_aware: true",
        f"- total_records: {report['total_records']}",
        f"- records_with_semantic_text: {report['records_with_semantic_text']}",
        f"- authority_levels_detected: {report['authority_levels_detected']}",
        "- modified_canon: false",
        "- relations_generated: false",
        "- candidate_relations_generated: false",
        "- embeddings_executed: false",
        "",
        "| authority_level | total | semantic_text |",
        "|---|---:|---:|",
    ]
    for authority, bucket in report["by_authority_level"].items():
        lines.append(
            f"| {authority} | {bucket['total_records']} | {bucket['records_with_semantic_text']} |"
        )
    lines.append("")
    return "\n".join(lines)


def review_rows(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "id": record["id"],
            "title": record["title"],
            "artifact_family": record["artifact_family"],
            "authority_level": record["authority_level"],
            "mode": record["mode"],
            "semantic_text_chars": str(len(record["semantic_text"])),
            "semantic_text_sha256": record["semantic_text_sha256"],
            "warnings": "|".join(record["warnings"]),
        }
        for record in records
    ]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(stable_json(record) + "\n" for record in records), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_hashes(paths: dict[str, Path], records: list[dict[str, Any]], *, mode: str, source_session: str) -> dict[str, Any]:
    payload = {
        "schema": "semantic-text-authority-hashes/v1",
        "session": source_session,
        "source_session": source_session,
        "mode": mode,
        "authority_aware": True,
        "modified_canon": False,
        "file_sha256": {
            name: file_sha256(path)
            for name, path in sorted(paths.items())
            if name != "hashes" and path.exists()
        },
        "record_semantic_text_sha256": {
            record["id"]: record["semantic_text_sha256"]
            for record in sorted(records, key=lambda item: (item["id"], item["title"]))
        },
        "hashes_file_self_hash_included": False,
    }
    write_json(paths["hashes"], payload)
    return payload


def build_authority_outputs(
    *,
    canon_glob: str = base.DEFAULT_CANON_GLOB,
    out_dir: Path = DEFAULT_OUT_DIR,
    session: str = DEFAULT_SESSION,
    mode: str = "preview",
    type_policy: Path = base.DEFAULT_TYPE_POLICY,
    max_content_chars: int = base.DEFAULT_MAX_CONTENT_CHARS,
) -> dict[str, Any]:
    session = session.upper()
    if (out_dir / "s0144_semantic_text_records.jsonl").exists() or "semantic_text/s0144" in str(out_dir):
        raise ValueError("S0149 authority-aware builder must not overwrite S0144 outputs")
    canon_records = base.read_canon_records(canon_glob)
    profiles = base.build_profiles({base.artifact_family_for(record) for record in canon_records}, max_content_chars)
    policy = base.load_relation_policy(type_policy)
    base_records = base.build_records(
        canon_records,
        policy=policy,
        profiles=profiles,
        preview_index=base.load_dry_run_preview_index(),
        max_content_chars=max_content_chars,
    )
    records = [
        authority_record(canon_record, semantic_record, mode=mode, source_session=session)
        for canon_record, semantic_record in zip(canon_records, base_records, strict=True)
    ]
    paths = output_paths(out_dir, session)
    coverage = build_coverage_report(records, mode=mode, source_session=session)
    write_jsonl(paths["records"], records)
    write_json(paths["index"], build_index(records, mode=mode, source_session=session))
    write_json(paths["coverage_report"], coverage)
    paths["summary"].parent.mkdir(parents=True, exist_ok=True)
    paths["summary"].write_text(summary_md(coverage), encoding="utf-8")
    write_csv(paths["review"], review_rows(records))
    hashes = write_hashes(paths, records, mode=mode, source_session=session)
    return {
        "schema": SCHEMA,
        "session": session,
        "source_session": session,
        "mode": mode,
        "authority_aware": True,
        "modified_canon": False,
        "canon_modified": False,
        "paths": {name: str(path) for name, path in paths.items()},
        "summary": {
            "record_count": len(records),
            "authority_levels_detected": coverage["authority_levels_detected"],
            "records_with_semantic_text": coverage["records_with_semantic_text"],
            "hashes_sha256": file_sha256(paths["hashes"]),
            "records_sha256": hashes["file_sha256"].get("records", ""),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build S0149 authority-aware semantic_text sidecar")
    parser.add_argument("--canon-glob", default=base.DEFAULT_CANON_GLOB)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--session", default=DEFAULT_SESSION)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--generate", action="store_true")
    parser.add_argument("--type-policy", default=str(base.DEFAULT_TYPE_POLICY))
    parser.add_argument("--max-content-chars-per-section", type=int, default=base.DEFAULT_MAX_CONTENT_CHARS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = "generate" if args.generate else "preview"
    result = build_authority_outputs(
        canon_glob=args.canon_glob,
        out_dir=Path(args.out_dir),
        session=args.session,
        mode=mode,
        type_policy=Path(args.type_policy),
        max_content_chars=args.max_content_chars_per_section,
    )
    print(stable_json(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
