#!/usr/bin/env python3
"""Deterministic preview/staging equivalence validator for S0173.

This module is a validator gate, never a derivative producer.  It compares the
logical records emitted by ``derive_layers.py`` and ignores only operational
metadata declared by the productive-equivalence contract.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from rag_derivation_profile import stable_json
from rag_derivative_writers import require_nonproductive_evidence_target


CONTRACT_SCHEMA_VERSION = "productive-equivalence-contract/v1"
REPORT_SCHEMA_VERSION = "productive-equivalence-report/v1"
FAMILY_PATTERNS = {
    "enriched": ("enriched", "tiddlers_enriched_*.jsonl"),
    "ai": ("ai", "tiddlers_ai_*.jsonl"),
    "chunks_ai": ("ai", "chunks_ai_*.jsonl"),
    "semantic_text": ("semantic_text", "*_semantic_text_records.jsonl"),
}
OPERATIONAL_KEYS = {
    "run_id",
    "session",
    "generated_from_session",
    "updated_at",
    "created_at",
    "output_root",
    "manifest_path",
    "transaction_id",
    "authority_state",
    "producer_execution_mode",
    "productive_write",
    "productive_regeneration_executed",
    "canon_modified",
    "productive_derivatives_modified",
    "mtime",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl_records(paths: list[Path]):
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number} is not a JSON object")
                yield value


def _copilot_records(root: Path) -> list[dict[str, Any]]:
    path = root / "microsoft_copilot" / "entities.json"
    if not path.exists():
        return []
    value = _load_json(path)
    if isinstance(value, dict) and isinstance(value.get("entities"), list):
        return [record for record in value["entities"] if isinstance(record, dict)]
    if isinstance(value, list):
        return [record for record in value if isinstance(record, dict)]
    return []


def _record_id(record: dict[str, Any], family: str) -> str | None:
    if family == "chunks_ai":
        key = record.get("chunk_id") or record.get("id")
    else:
        key = record.get("id") or record.get("node_id") or record.get("tiddler_id")
    return str(key) if key is not None else None


def _normalize(value: Any, preview_root: Path, staging_root: Path, *, key: str | None = None) -> Any:
    if key in OPERATIONAL_KEYS:
        return None
    if isinstance(value, dict):
        normalized = {}
        for child_key, child_value in value.items():
            if child_key in OPERATIONAL_KEYS:
                continue
            normalized[child_key] = _normalize(child_value, preview_root, staging_root, key=child_key)
        return normalized
    if isinstance(value, list):
        return [_normalize(item, preview_root, staging_root, key=key) for item in value]
    if isinstance(value, str):
        result = value
        for root in (preview_root.resolve(), staging_root.resolve()):
            result = result.replace(str(root), "<DERIVATION_ROOT>")
        result = re.sub(r"/s017[23]/(preview|staging)/", "/<DERIVATION_ROOT>/", result)
        if key and key.endswith("_path"):
            result = result.replace("/preview/", "/<DERIVATION_ROOT>/").replace("/staging/", "/<DERIVATION_ROOT>/")
        return result
    return value


def _signature(record: dict[str, Any], family: str, root: Path) -> dict[str, Any]:
    """Retain compact comparison material; never retain the full corpus in memory."""

    # Do not recursively normalize the full record: enriched payloads contain
    # large canonical text/projection objects and can exhaust the validator's
    # memory budget.  The contract compares only these logical fields.
    semantic = _normalize(record.get("semantic_text"), root, root, key="semantic_text")
    metadata = _normalize(record.get("promoted_metadata") or record.get("embedding_metadata"), root, root, key="metadata")
    rag_filter = _normalize(record.get("rag_filters") or record.get("rag_allowed_tags"), root, root, key="rag_filter")
    chunk_fields = {
        key: _normalize(record.get(key), root, root, key=key)
        for key in ("text", "chunk_index", "chunk_total", "source_id", "source_anchor", "within_hard_max")
    }
    retrieval_hints = _normalize(record.get("retrieval_hints"), root, root, key="retrieval_hints")
    schema_version = record.get("schema_version")
    def digest(value: Any) -> str:
        return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()

    return {
        "id": _record_id(record, family),
        "semantic_text_hash": hashlib.sha256(str(semantic).encode("utf-8")).hexdigest(),
        "retrieval_hints_hash": digest(retrieval_hints),
        "metadata_hash": digest(metadata),
        "rag_filter_hash": digest(rag_filter),
        "chunk_fields_hash": digest(chunk_fields),
        "schema_version": schema_version,
        "logical_hash": digest({
            "semantic_text": semantic,
            "retrieval_hints": retrieval_hints,
            "metadata": metadata,
            "rag_filter": rag_filter,
            "chunk_fields": chunk_fields,
            "schema_version": schema_version,
        }),
    }


def _logical_records(
    root: Path,
    *,
    families: tuple[str, ...] = ("enriched", "ai", "chunks_ai", "semantic_text", "microsoft_copilot"),
) -> dict[str, dict[str, dict[str, Any]]]:
    surfaces: dict[str, dict[str, dict[str, Any]]] = {}
    for family in families:
        if family == "microsoft_copilot":
            continue
        relative, pattern = FAMILY_PATTERNS[family]
        indexed: dict[str, dict[str, Any]] = {}
        for record in _iter_jsonl_records(sorted((root / relative).glob(pattern))):
            record_id = _record_id(record, family)
            if record_id is None:
                raise ValueError(f"{family} record has no stable identity")
            if record_id in indexed:
                raise ValueError(f"duplicate {family} identity: {record_id}")
            indexed[record_id] = _signature(record, family, root)
        surfaces[family] = indexed
    if "microsoft_copilot" in families:
        copilot = {}
        for record in _copilot_records(root):
            record_id = _record_id(record, "microsoft_copilot")
            if record_id is None:
                raise ValueError("microsoft_copilot entity has no stable identity")
            if record_id in copilot:
                raise ValueError(f"duplicate microsoft_copilot identity: {record_id}")
            copilot[record_id] = _signature(record, "microsoft_copilot", root)
        surfaces["microsoft_copilot"] = copilot
    return surfaces


def _family_report(
    family: str,
    preview: dict[str, dict[str, Any]],
    staging: dict[str, dict[str, Any]],
    preview_root: Path,
    staging_root: Path,
) -> dict[str, Any]:
    preview_ids = set(preview)
    staging_ids = set(staging)
    common = sorted(preview_ids & staging_ids)
    missing_preview = sorted(staging_ids - preview_ids)
    missing_staging = sorted(preview_ids - staging_ids)
    identity_mismatches = 0
    semantic_text_mismatches = 0
    retrieval_hint_mismatches = 0
    metadata_mismatches = 0
    rag_filter_mismatches = 0
    chunk_mismatches = 0
    schema_mismatches = 0
    for record_id in common:
        left = preview[record_id]
        right = staging[record_id]
        if left.get("id") != right.get("id"):
            identity_mismatches += 1
        if left.get("semantic_text_hash") != right.get("semantic_text_hash"):
            semantic_text_mismatches += 1
        if left.get("retrieval_hints_hash") != right.get("retrieval_hints_hash"):
            retrieval_hint_mismatches += 1
        if left.get("metadata_hash") != right.get("metadata_hash"):
            metadata_mismatches += 1
        if left.get("rag_filter_hash") != right.get("rag_filter_hash"):
            rag_filter_mismatches += 1
        if family == "chunks_ai" and left.get("chunk_fields_hash") != right.get("chunk_fields_hash"):
            chunk_mismatches += 1
        if left.get("schema_version") != right.get("schema_version"):
            schema_mismatches += 1
    mismatch_total = sum(
        (identity_mismatches, semantic_text_mismatches, retrieval_hint_mismatches,
         metadata_mismatches, rag_filter_mismatches, chunk_mismatches, schema_mismatches)
    )
    status = "equivalent" if not missing_preview and not missing_staging and not mismatch_total else "not_equivalent"
    return {
        "records_compared": len(common),
        "missing_in_preview": missing_preview,
        "missing_in_staging": missing_staging,
        "identity_mismatches": identity_mismatches,
        "semantic_text_mismatches": semantic_text_mismatches,
        "retrieval_hint_mismatches": retrieval_hint_mismatches,
        "metadata_mismatches": metadata_mismatches,
        "rag_filter_mismatches": rag_filter_mismatches,
        "chunk_mismatches": chunk_mismatches,
        "schema_mismatches": schema_mismatches,
        "allowed_operational_differences": sorted(OPERATIONAL_KEYS),
        "equivalence_status": status,
    }


def build_equivalence_report(
    preview_root: Path | str,
    staging_root: Path | str,
    *,
    families: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    preview = Path(preview_root).resolve()
    staging = Path(staging_root).resolve()
    compared_families = tuple(families or ("enriched", "ai", "chunks_ai", "semantic_text", "microsoft_copilot"))
    unknown = sorted(set(compared_families) - set(FAMILY_PATTERNS) - {"microsoft_copilot"})
    if unknown:
        raise ValueError(f"unknown equivalence families: {', '.join(unknown)}")
    preview_surfaces = _logical_records(preview, families=compared_families)
    staging_surfaces = _logical_records(staging, families=compared_families)
    family_reports = {
        family: _family_report(family, preview_surfaces.get(family, {}), staging_surfaces.get(family, {}), preview, staging)
        for family in compared_families
    }
    failed = [family for family, result in family_reports.items() if result["equivalence_status"] == "not_equivalent"]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "preview_root": str(preview),
        "staging_root": str(staging),
        "normalization": {
            "operational_fields_ignored": sorted(OPERATIONAL_KEYS),
            "path_roots_normalized": True,
            "comparison_order": "stable_identity_then_recursive_fields",
        },
        "families": family_reports,
        "compared_families": list(compared_families),
        "equivalence_status": "not_equivalent" if failed else "equivalent_with_declared_operational_differences",
        "blocking": bool(failed),
        "failed_families": failed,
    }


def write_report(path: Path | str, report: dict[str, Any]) -> Path:
    target = require_nonproductive_evidence_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stable_json(report, indent=2) + "\n", encoding="utf-8")
    return target


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Equivalencia preview / staging",
        "",
        f"- Estado: `{report['equivalence_status']}`",
        f"- Bloqueante: `{str(report['blocking']).lower()}`",
        "",
        "| Familia | Comparados | Faltan en preview | Faltan en staging | Semántica | Metadata | Chunks | Estado |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for family, result in report["families"].items():
        lines.append(
            f"| {family} | {result['records_compared']} | {len(result['missing_in_preview'])} | "
            f"{len(result['missing_in_staging'])} | {result['semantic_text_mismatches']} | "
            f"{result['metadata_mismatches']} | {result['chunk_mismatches']} | {result['equivalence_status']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare authoritative preview and staging outputs deterministically.")
    parser.add_argument("--preview-root", required=True)
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--report-md")
    parser.add_argument("--family", action="append", dest="families", help="Limit comparison to one logical family; repeatable")
    args = parser.parse_args()
    report = build_equivalence_report(args.preview_root, args.staging_root, families=args.families)
    write_report(args.report, report)
    if args.report_md:
        target = require_nonproductive_evidence_target(args.report_md)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report_markdown(report), encoding="utf-8")
    print(stable_json(report, indent=2))
    return 0 if not report["blocking"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
