#!/usr/bin/env python3
"""Validate governed derivative equivalence against a living local canon.

The validator is deliberately a gate, never a derivative producer.  Version
two retains a historical baseline to expose removals and unexpected changes,
but resolves every candidate record against the canon that is current when the
comparison runs.  A new or changed record is therefore non-blocking only when
its stable canonical identity and canonical ``version_id`` both resolve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from rag_derivation_plan import canonical_snapshot
from rag_derivation_profile import stable_json
from rag_derivative_writers import require_nonproductive_evidence_target


CONTRACT_SCHEMA_VERSION = "productive-equivalence-contract/v2"
REPORT_SCHEMA_VERSION = "productive-equivalence-report/v2"
FAMILY_PATTERNS = {
    "enriched": ("enriched", "tiddlers_enriched_*.jsonl"),
    "ai": ("ai", "tiddlers_ai_*.jsonl"),
    "chunks_ai": ("ai", "chunks_ai_*.jsonl"),
    "semantic_text": ("semantic_text", "*_semantic_text_records.jsonl"),
}
DEFAULT_FAMILIES = ("enriched", "ai", "chunks_ai", "semantic_text", "microsoft_copilot")
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
VERSION_IN_SEMANTIC_TEXT = re.compile(r"^version_id:\s*(\S+)", re.MULTILINE)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_file(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.exists() else None


def _iter_jsonl_records(paths: list[Path]):
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number} invalid JSON: {error.msg}") from error
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number} is not a JSON object")
                yield value, path, line_number


def _copilot_records(root: Path) -> list[dict[str, Any]]:
    path = root / "microsoft_copilot" / "entities.json"
    if not path.exists():
        return []
    value = _load_json(path)
    if isinstance(value, dict) and isinstance(value.get("entities"), list):
        return [record for record in value["entities"] if isinstance(record, dict)]
    if isinstance(value, list):
        return [record for record in value if isinstance(record, dict)]
    raise ValueError(f"{path} must contain an entities list")


def _record_id(record: dict[str, Any], family: str) -> str | None:
    key = record.get("chunk_id") if family == "chunks_ai" else (record.get("id") or record.get("node_id") or record.get("tiddler_id"))
    return str(key).strip() if key is not None and str(key).strip() else None


def _source_id(record: dict[str, Any], family: str) -> str | None:
    if family == "chunks_ai":
        key = record.get("source_id") or (record.get("source_anchor") or {}).get("canon_id")
    elif family == "microsoft_copilot":
        key = record.get("id") or (record.get("canon_ref") or {}).get("id")
    else:
        key = record.get("id") or (record.get("source_anchor") or {}).get("canon_id")
    return str(key).strip() if key is not None and str(key).strip() else None


def _legacy_semantic_version(record: dict[str, Any]) -> str | None:
    match = VERSION_IN_SEMANTIC_TEXT.search(str(record.get("semantic_text") or ""))
    return match.group(1) if match else None


def _source_version(record: dict[str, Any], family: str) -> tuple[str | None, str]:
    """Return the source revision and how it was represented by this layer.

    ``semantic_text`` is consulted only for a historical AI baseline whose
    producer predates the explicit field.  New projections expose the version
    directly; this compatibility path is never used as authority over canon.
    """

    candidates: list[tuple[Any, str]] = []
    if family == "chunks_ai":
        candidates.append((record.get("source_version_id"), "source_version_id"))
    elif family == "microsoft_copilot":
        candidates.extend(
            (
                (record.get("version_id"), "version_id"),
                (record.get("content_hash"), "content_hash"),
                ((record.get("canon_ref") or {}).get("content_hash"), "canon_ref.content_hash"),
            )
        )
    else:
        candidates.extend(((record.get("version_id"), "version_id"), (record.get("source_version_id"), "source_version_id")))
    for value, source in candidates:
        if value is not None and str(value).strip():
            return str(value).strip(), source
    legacy = _legacy_semantic_version(record)
    return (legacy, "legacy_semantic_text") if legacy else (None, "missing")


def _normalize(value: Any, baseline_root: Path, staging_root: Path, *, key: str | None = None) -> Any:
    if key in OPERATIONAL_KEYS:
        return None
    if isinstance(value, dict):
        return {
            child_key: _normalize(child_value, baseline_root, staging_root, key=child_key)
            for child_key, child_value in value.items()
            if child_key not in OPERATIONAL_KEYS
        }
    if isinstance(value, list):
        return [_normalize(item, baseline_root, staging_root, key=key) for item in value]
    if isinstance(value, str):
        result = value
        for root in (baseline_root.resolve(), staging_root.resolve()):
            result = result.replace(str(root), "<DERIVATION_ROOT>")
        if key and key.endswith("_path"):
            result = result.replace("/preview/", "/<DERIVATION_ROOT>/").replace("/staging/", "/<DERIVATION_ROOT>/")
        return result
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def _signature(record: dict[str, Any], family: str, root: Path) -> dict[str, Any]:
    """Create a compact, version-aware projection for one derivative record."""

    semantic = _normalize(record.get("semantic_text"), root, root, key="semantic_text")
    metadata = _normalize(record.get("promoted_metadata") or record.get("embedding_metadata"), root, root, key="metadata")
    rag_filter = _normalize(record.get("rag_filters") or record.get("rag_allowed_tags") or record.get("rag_safe_tags"), root, root, key="rag_filter")
    source_anchor = record.get("source_anchor") or {}
    # Shard and line move when canon is compacted; canonical identity does not.
    compact_anchor = {"canon_id": source_anchor.get("canon_id")} if isinstance(source_anchor, dict) else None
    chunk_fields = {
        key: _normalize(record.get(key), root, root, key=key)
        for key in ("text", "chunk_index", "chunk_total", "source_id", "within_hard_max")
    }
    chunk_fields["source_anchor"] = compact_anchor
    retrieval_hints = _normalize(record.get("retrieval_hints") or record.get("retrieval_terms"), root, root, key="retrieval_hints")
    source_version, version_representation = _source_version(record, family)
    return {
        "id": _record_id(record, family),
        "source_id": _source_id(record, family),
        "version_id": source_version,
        "version_representation": version_representation,
        "title": record.get("title"),
        "canonical_slug": record.get("canonical_slug") or record.get("source_canonical_slug"),
        "artifact_family": record.get("artifact_family"),
        "semantic_text_hash": hashlib.sha256(str(semantic).encode("utf-8")).hexdigest(),
        "retrieval_hints_hash": _digest(retrieval_hints),
        "metadata_hash": _digest(metadata),
        "rag_filter_hash": _digest(rag_filter),
        "chunk_fields_hash": _digest(chunk_fields),
        "schema_version": record.get("schema_version"),
        "within_hard_max": record.get("within_hard_max"),
        "logical_hash": _digest(
            {
                "semantic_text": semantic,
                "retrieval_hints": retrieval_hints,
                "metadata": metadata,
                "rag_filter": rag_filter,
                "chunk_fields": chunk_fields,
                "schema_version": record.get("schema_version"),
            }
        ),
    }


def _logical_records(root: Path, *, families: tuple[str, ...]) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, list[str]]]]:
    surfaces: dict[str, dict[str, dict[str, Any]]] = {}
    issues: dict[str, dict[str, list[str]]] = {}
    for family in families:
        indexed: dict[str, dict[str, Any]] = {}
        family_issues = {"duplicate_record": [], "identity_mismatch": [], "family_mismatch": [], "chunk_hard_max": []}
        if family == "microsoft_copilot":
            rows = ((record, root / "microsoft_copilot" / "entities.json", number) for number, record in enumerate(_copilot_records(root), start=1))
        else:
            relative, pattern = FAMILY_PATTERNS[family]
            rows = _iter_jsonl_records(sorted((root / relative).glob(pattern)))
        for record, path, line_number in rows:
            record_id = _record_id(record, family) or f"<missing-id>:{path.name}:{line_number}"
            if record_id in indexed:
                family_issues["duplicate_record"].append(record_id)
                continue
            signature = _signature(record, family, root)
            indexed[record_id] = signature
            if signature["id"] is None or signature["source_id"] is None or (family != "chunks_ai" and signature["id"] != signature["source_id"]):
                family_issues["identity_mismatch"].append(record_id)
            explicit_family = signature.get("artifact_family")
            if explicit_family and explicit_family != family:
                family_issues["family_mismatch"].append(record_id)
            if family == "chunks_ai" and signature.get("within_hard_max") is not True:
                family_issues["chunk_hard_max"].append(record_id)
        surfaces[family] = indexed
        issues[family] = family_issues
    return surfaces, issues


def build_canonical_index(canon_dir: Path | str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read the current canon once and report invalid authority conditions."""

    root = Path(canon_dir).resolve()
    files = sorted(root.glob("tiddlers_*.jsonl"), key=lambda item: item.name)
    if not files:
        raise FileNotFoundError(f"no canon shards found in {root}")
    index: dict[str, dict[str, Any]] = {}
    issues: dict[str, list[str]] = {"parse_errors": [], "empty_ids": [], "duplicate_ids": [], "empty_versions": [], "invalid_records": []}
    records = 0
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                records += 1
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    issues["parse_errors"].append(f"{path.name}:{line_number}:{error.msg}")
                    continue
                if not isinstance(value, dict):
                    issues["invalid_records"].append(f"{path.name}:{line_number}")
                    continue
                record_id = str(value.get("id") or "").strip()
                if not record_id:
                    issues["empty_ids"].append(f"{path.name}:{line_number}")
                    continue
                if record_id in index:
                    issues["duplicate_ids"].append(record_id)
                    continue
                version_id = str(value.get("version_id") or "").strip()
                if not version_id:
                    issues["empty_versions"].append(record_id)
                index[record_id] = {
                    "version_id": version_id or None,
                    "title": value.get("title"),
                    "canonical_slug": value.get("canonical_slug"),
                    "artifact_family": value.get("artifact_family") or (value.get("source_fields") or {}).get("artifact_family"),
                    "present": True,
                }
    snapshot = canonical_snapshot(root)
    counts = {name: len(values) for name, values in issues.items()}
    return index, {
        "canon_dir": str(root),
        "canon_hash": snapshot["source_canon_hash"],
        "shards": len(files),
        "records_seen": records,
        "records_indexed": len(index),
        "valid": not any(counts.values()),
        "issue_counts": counts,
    }


def _new_family_report(family: str, baseline_count: int, current_count: int) -> tuple[dict[str, Any], dict[str, list[str]]]:
    report = {
        "family": family,
        "baseline_records": baseline_count,
        "current_records": current_count,
        "records_compared": 0,
        "unchanged_shared_records": 0,
        "added_from_current_canon": 0,
        "canonical_updates": 0,
        "removed_historical_records": 0,
        "unexpected_semantic_regressions": 0,
        "invalid_version_transitions": 0,
        "invalid_canonical_membership": 0,
        "identity_mismatches": 0,
        "schema_mismatches": 0,
        "family_mismatches": 0,
        "duplicate_records": 0,
        "chunk_mismatches": 0,
        "chunks_above_hard_max": 0,
        "equivalence_status": "equivalent",
        "blocking": False,
    }
    evidence = {key: [] for key in (
        "unchanged_shared_records", "added_from_current_canon", "canonical_updates", "removed_historical_records",
        "unexpected_semantic_regressions", "invalid_version_transitions", "invalid_canonical_membership", "identity_mismatches",
        "schema_mismatches", "family_mismatches", "duplicate_records", "chunk_mismatches", "chunks_above_hard_max",
    )}
    return report, evidence


def _evidence_id(signature: dict[str, Any], fallback: str) -> str:
    return str(signature.get("source_id") or signature.get("id") or fallback)


def _family_report(
    family: str,
    baseline: dict[str, dict[str, Any]],
    staging: dict[str, dict[str, Any]],
    baseline_issues: dict[str, list[str]],
    staging_issues: dict[str, list[str]],
    canon: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    report, evidence = _new_family_report(family, len(baseline), len(staging))
    for key in ("duplicate_record", "identity_mismatch", "family_mismatch", "chunk_hard_max"):
        destination = {
            "duplicate_record": "duplicate_records",
            "identity_mismatch": "identity_mismatches",
            "family_mismatch": "family_mismatches",
            "chunk_hard_max": "chunks_above_hard_max",
        }[key]
        values = sorted(set(baseline_issues.get(key, []) + staging_issues.get(key, [])))
        report[destination] += len(values)
        evidence[destination].extend(values)

    for record_id in sorted(set(baseline) - set(staging)):
        report["removed_historical_records"] += 1
        evidence["removed_historical_records"].append(_evidence_id(baseline[record_id], record_id))

    for record_id in sorted(staging):
        current = staging[record_id]
        current_id = _evidence_id(current, record_id)
        source_id = current.get("source_id")
        canon_record = canon.get(str(source_id)) if source_id else None
        if canon_record is None:
            report["invalid_canonical_membership"] += 1
            evidence["invalid_canonical_membership"].append(current_id)
            continue
        if not current.get("version_id") or current.get("version_id") != canon_record.get("version_id"):
            report["invalid_version_transitions"] += 1
            evidence["invalid_version_transitions"].append(current_id)
            continue

        previous = baseline.get(record_id)
        if previous is None:
            report["added_from_current_canon"] += 1
            evidence["added_from_current_canon"].append(current_id)
            continue

        report["records_compared"] += 1
        if previous.get("schema_version") != current.get("schema_version"):
            report["schema_mismatches"] += 1
            evidence["schema_mismatches"].append(current_id)
            continue
        if previous.get("version_id") == current.get("version_id"):
            logical_changed = previous.get("logical_hash") != current.get("logical_hash")
            if family == "chunks_ai" and previous.get("chunk_fields_hash") != current.get("chunk_fields_hash"):
                report["chunk_mismatches"] += 1
                evidence["chunk_mismatches"].append(current_id)
                logical_changed = True
            if logical_changed:
                report["unexpected_semantic_regressions"] += 1
                evidence["unexpected_semantic_regressions"].append(current_id)
            else:
                report["unchanged_shared_records"] += 1
                evidence["unchanged_shared_records"].append(current_id)
            continue

        # The historical baseline differs, but the staging revision is exactly
        # the current canonical revision.  Structural violations were checked
        # above, so the permitted content projection matrix applies.
        report["canonical_updates"] += 1
        evidence["canonical_updates"].append(current_id)

    blocking_fields = (
        "removed_historical_records", "unexpected_semantic_regressions", "invalid_version_transitions",
        "invalid_canonical_membership", "identity_mismatches", "schema_mismatches", "family_mismatches",
        "duplicate_records", "chunk_mismatches", "chunks_above_hard_max",
    )
    report["blocking"] = any(report[field] for field in blocking_fields)
    report["equivalence_status"] = "not_equivalent" if report["blocking"] else "equivalent"
    for values in evidence.values():
        values.sort()
    return report, evidence


def _record_counts(surfaces: dict[str, dict[str, dict[str, Any]]]) -> dict[str, int]:
    return {family: len(records) for family, records in surfaces.items()}


def _union_evolution_ids(evidence: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for family_values in evidence.values():
        for classification, values in family_values.items():
            result.setdefault(classification, set()).update(values)
    return {classification: sorted(values) for classification, values in result.items()}


def build_equivalence_report(
    baseline_root: Path | str,
    staging_root: Path | str,
    *,
    canon_dir: Path | str | None = None,
    staging_manifest_path: Path | str | None = None,
    baseline_manifest_path: Path | str | None = None,
    baseline_source_type: str | None = None,
    families: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    baseline = Path(baseline_root).resolve()
    staging = Path(staging_root).resolve()
    canon_root = Path(canon_dir).resolve() if canon_dir else (Path(__file__).resolve().parents[2] / "data" / "out" / "local")
    compared_families = tuple(families or DEFAULT_FAMILIES)
    unknown = sorted(set(compared_families) - set(FAMILY_PATTERNS) - {"microsoft_copilot"})
    if unknown:
        raise ValueError(f"unknown equivalence families: {', '.join(unknown)}")
    canon_index, canon_summary = build_canonical_index(canon_root)
    baseline_surfaces, baseline_issues = _logical_records(baseline, families=compared_families)
    staging_surfaces, staging_issues = _logical_records(staging, families=compared_families)
    family_reports: dict[str, dict[str, Any]] = {}
    family_evidence: dict[str, dict[str, list[str]]] = {}
    for family in compared_families:
        report, evidence = _family_report(
            family,
            baseline_surfaces.get(family, {}),
            staging_surfaces.get(family, {}),
            baseline_issues.get(family, {}),
            staging_issues.get(family, {}),
            canon_index,
        )
        family_reports[family] = report
        family_evidence[family] = evidence
    evolution_ids = _union_evolution_ids(family_evidence)
    evolution = {
        "additions": len(evolution_ids.get("added_from_current_canon", [])),
        "updates": len(evolution_ids.get("canonical_updates", [])),
        "removals": len(evolution_ids.get("removed_historical_records", [])),
        "regressions": len(evolution_ids.get("unexpected_semantic_regressions", [])),
    }
    failed = [family for family, result in family_reports.items() if result["blocking"]]
    canonical_invalid = canon_summary["valid"] is not True
    blocking = bool(failed or canonical_invalid)
    if blocking:
        status = "not_equivalent"
    elif evolution["additions"] or evolution["updates"]:
        status = "equivalent_with_expected_canonical_evolution"
    else:
        status = "equivalent"
    baseline_manifest = Path(baseline_manifest_path).resolve() if baseline_manifest_path else None
    staging_manifest = Path(staging_manifest_path).resolve() if staging_manifest_path else None
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "baseline": {
            "source_type": baseline_source_type or "historical_derivative_staging",
            "staging_root": str(baseline),
            "manifest_hash": _hash_file(baseline_manifest),
            "record_counts": _record_counts(baseline_surfaces),
        },
        "current": {
            "staging_root": str(staging),
            "canon_dir": str(canon_root),
            "canon_hash": canon_summary["canon_hash"],
            "staging_manifest_hash": _hash_file(staging_manifest),
            "record_counts": _record_counts(staging_surfaces),
        },
        "canonical_index": canon_summary,
        "normalization": {
            "operational_fields_ignored": sorted(OPERATIONAL_KEYS),
            "path_roots_normalized": True,
            "chunk_source_anchor": "canon_id_only",
            "version_resolution": {
                "current": ["version_id", "source_version_id", "content_hash"],
                "historical_compatibility": "semantic_text version_id only when no explicit field exists",
            },
        },
        "families": family_reports,
        "compared_families": list(compared_families),
        "evolution": evolution,
        "equivalence_status": status,
        "blocking": blocking,
        "failed_families": failed + (["canonical_index"] if canonical_invalid else []),
        "_evolution_ids": {"families": family_evidence, "global": evolution_ids},
    }
    return report


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if not key.startswith("_")}


def write_report(path: Path | str, report: dict[str, Any]) -> Path:
    target = require_nonproductive_evidence_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stable_json(_public_report(report), indent=2) + "\n", encoding="utf-8")
    return target


def write_evolution_evidence(summary_path: Path | str, ids_path: Path | str, report: dict[str, Any]) -> tuple[Path, Path]:
    summary_target = require_nonproductive_evidence_target(summary_path)
    ids_target = require_nonproductive_evidence_target(ids_path)
    summary_target.parent.mkdir(parents=True, exist_ok=True)
    ids_target.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "canonical-evolution-summary/v1",
        "contract_schema_version": report["contract_schema_version"],
        "report_schema_version": report["schema_version"],
        "current": report["current"],
        "canonical_index": report["canonical_index"],
        "evolution": report["evolution"],
        "equivalence_status": report["equivalence_status"],
        "blocking": report["blocking"],
        "families": {
            family: {
                key: value
                for key, value in result.items()
                if key not in {"family", "equivalence_status", "blocking"}
            }
            for family, result in report["families"].items()
        },
    }
    identifiers = {
        "schema_version": "canonical-evolution-identifiers/v1",
        "contract_schema_version": report["contract_schema_version"],
        "report_schema_version": report["schema_version"],
        "global": report["_evolution_ids"]["global"],
        "families": report["_evolution_ids"]["families"],
    }
    summary_target.write_text(stable_json(summary, indent=2) + "\n", encoding="utf-8")
    ids_target.write_text(stable_json(identifiers, indent=2) + "\n", encoding="utf-8")
    return summary_target, ids_target


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Equivalencia productiva gobernada",
        "",
        f"- Contrato: `{report['contract_schema_version']}`",
        f"- Estado: `{report['equivalence_status']}`",
        f"- Bloqueante: `{str(report['blocking']).lower()}`",
        f"- Altas canónicas válidas: `{report['evolution']['additions']}`",
        f"- Actualizaciones canónicas válidas: `{report['evolution']['updates']}`",
        f"- Pérdidas históricas: `{report['evolution']['removals']}`",
        f"- Regresiones inesperadas: `{report['evolution']['regressions']}`",
        "",
        "| Familia | Base | Actual | Sin cambio | Altas | Actualizaciones | Pérdidas | Regresiones | Estado |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in report["families"].values():
        lines.append(
            f"| {result['family']} | {result['baseline_records']} | {result['current_records']} | "
            f"{result['unchanged_shared_records']} | {result['added_from_current_canon']} | "
            f"{result['canonical_updates']} | {result['removed_historical_records']} | "
            f"{result['unexpected_semantic_regressions']} | {result['equivalence_status']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate derivative equivalence against a historical baseline and current canon.")
    parser.add_argument("--preview-root", "--baseline-root", dest="baseline_root", required=True)
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--canon-dir", default="data/out/local")
    parser.add_argument("--staging-manifest")
    parser.add_argument("--baseline-manifest")
    parser.add_argument("--baseline-source-type")
    parser.add_argument("--report", required=True)
    parser.add_argument("--report-md")
    parser.add_argument("--evolution-summary")
    parser.add_argument("--evolution-ids")
    parser.add_argument("--family", action="append", dest="families", help="Limit comparison to one logical family; repeatable")
    args = parser.parse_args()
    report = build_equivalence_report(
        args.baseline_root,
        args.staging_root,
        canon_dir=args.canon_dir,
        staging_manifest_path=args.staging_manifest,
        baseline_manifest_path=args.baseline_manifest,
        baseline_source_type=args.baseline_source_type,
        families=args.families,
    )
    report_path = write_report(args.report, report)
    summary_path = args.evolution_summary or str(report_path.with_name("canonical_evolution_summary.json"))
    ids_path = args.evolution_ids or str(report_path.with_name("canonical_evolution_ids.json"))
    write_evolution_evidence(summary_path, ids_path, report)
    if args.report_md:
        target = require_nonproductive_evidence_target(args.report_md)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report_markdown(report), encoding="utf-8")
    print(stable_json(_public_report(report), indent=2))
    return 0 if not report["blocking"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
