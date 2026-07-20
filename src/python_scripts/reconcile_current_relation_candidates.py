#!/usr/bin/env python3
"""Freeze S0180's pre-relational baseline and reconcile current candidates.

This utility is deliberately read-only with respect to canon and productive
derivatives.  It consumes the already-generated ``relation_candidates/current``
batch and emits an auditable technical disposition for every candidate.  A
technical disposition is not a human decision and never grants canonical
authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from relation_candidate_contract import ALLOWED_RELATION_TYPES
from repair_relation_resolution_post_src import (
    CanonNode,
    build_indexes,
    canonicalize_observed_path,
    load_canon,
    resolve_endpoint,
    resolution_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANON_ROOT = REPO_ROOT / "data" / "out" / "local"
DEFAULT_CURRENT_DIR = DEFAULT_CANON_ROOT / "pipeline" / "relation_candidates" / "current"
DEFAULT_OUT_DIR = DEFAULT_CANON_ROOT / "audit" / "s0180"
DEFAULT_PRODUCTIVE_MANIFEST = DEFAULT_CANON_ROOT / "audit" / "rag_admission" / "productive_rag_manifest.json"

SESSION = "S0180"
SCHEMA = "s0180-candidate-reconciliation/v1"
DISPOSITIONS = (
    "ready_for_review",
    "exact_duplicate",
    "already_canonically_admitted",
    "invalid_source",
    "invalid_target",
    "unresolved_target",
    "not_canonicalizable",
    "unsupported_predicate",
    "self_reference",
    "insufficient_evidence",
    "out_of_scope",
    "malformed",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canon_snapshot(canon_root: Path) -> dict[str, Any]:
    shards = sorted(canon_root.glob("tiddlers_*.jsonl"))
    aggregate = hashlib.sha256()
    records = 0
    files = []
    for path in shards:
        payload = path.read_bytes()
        aggregate.update(payload)
        count = sum(1 for line in payload.splitlines() if line.strip())
        records += count
        files.append({"path": repo_path(path), "sha256": hashlib.sha256(payload).hexdigest(), "records": count})
    return {
        "canon_hash": aggregate.hexdigest(),
        "canon_records": records,
        "canon_shards": len(shards),
        "canon_files": files,
    }


def repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    return payload


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            malformed.append({"line_number": line_no, "raw": raw, "error": str(exc)})
            continue
        if not isinstance(row, dict):
            malformed.append({"line_number": line_no, "raw": raw, "error": "record is not an object"})
            continue
        records.append(row)
    return records, malformed


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def relation_schema(relation: dict[str, Any]) -> str:
    return str(relation.get("schema_version") or relation.get("relation_schema") or "legacy/pre-v1")


def canonical_relation_inventory(canon_root: Path) -> dict[str, Any]:
    canonical_v1 = 0
    legacy = 0
    canonical_v1_signatures: set[tuple[str, str, str]] = set()
    legacy_signatures: set[tuple[str, str, str]] = set()
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            source_id = str(row.get("id") or "")
            for relation in row.get("relations") or []:
                if not isinstance(relation, dict):
                    continue
                target_id = str(relation.get("target_id") or "")
                predicate = str(relation.get("type") or "")
                if not source_id or not target_id or not predicate:
                    continue
                if relation_schema(relation) == "canonical-relation/v1":
                    canonical_v1 += 1
                    canonical_v1_signatures.add((source_id, target_id, predicate))
                else:
                    legacy += 1
                    legacy_signatures.add((source_id, target_id, predicate))
    return {
        "canonical_relation_v1": canonical_v1,
        "legacy_explicit_relations": legacy,
        "canonical_v1_signatures": canonical_v1_signatures,
        "legacy_signatures": legacy_signatures,
    }


def lineage_relation_counts(local_root: Path) -> dict[str, int]:
    """Read the already-audited S0179 counts without treating them as authority."""
    report = local_root / "audit" / "s0179" / "current_derivative_relation_lineage.json"
    if not report.exists():
        return {"content_embedded_occurrences": 0, "projected_relation_targets": 0, "chunk_propagated_targets": 0, "copilot_edges": 0}
    payload = read_json(report)
    counts = payload.get("observed_counts") or payload.get("counts") or {}
    def count(*names: str) -> int:
        for name in names:
            value = counts.get(name)
            if isinstance(value, int):
                return value
            if isinstance(value, dict) and isinstance(value.get("count"), int):
                return value["count"]
        return 0
    return {
        "content_embedded_occurrences": count("embedded_relations", "content_embedded_occurrences"),
        "projected_relation_targets": count("relation_targets_content_embedded", "projected_relation_targets"),
        "chunk_propagated_targets": count("chunk_relation_targets", "chunk_propagated_targets"),
        "copilot_edges": count("copilot_edges"),
    }


def evidence_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    evidence = candidate.get("evidence") or {}
    return (evidence.get("evidence_kind"), evidence.get("file"), evidence.get("line"), evidence.get("raw_observation"))


def candidate_signature(candidate: dict[str, Any], source_id: str | None, target_id: str | None) -> tuple[str, str, str] | None:
    predicate = candidate.get("relation_type")
    if not source_id or not target_id or not isinstance(predicate, str) or not predicate:
        return None
    return source_id, target_id, predicate


def endpoint_resolution(endpoint: dict[str, Any], indexes: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    resolution = resolve_endpoint(endpoint, indexes, candidate_id=candidate_id)
    return resolution_payload(resolution)


def resolution_is_valid(resolution: dict[str, Any]) -> bool:
    return resolution.get("status") == "resolved" and bool(resolution.get("canonical_id"))


def disposition_for(
    candidate: dict[str, Any],
    indexes: dict[str, Any],
    canonical_v1_signatures: set[tuple[str, str, str]],
    seen_current: dict[tuple[str, str, str], tuple[str, tuple[Any, ...]]],
    historical_occurrences: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or "")
    source = candidate.get("source")
    target = candidate.get("target")
    predicate = candidate.get("relation_type")
    base = {
        "candidate_id": candidate_id or None,
        "source_canon_id": None,
        "source_version_id": None,
        "target_raw": None,
        "target_canon_id": None,
        "target_version_id": None,
        "predicate": predicate,
        "direction": "source_to_target",
        "evidence": candidate.get("evidence") or {},
        "origin": candidate.get("session_origin"),
        "candidate_authority": "candidate",
        "canonical_authority_granted": False,
        "human_reviewed": False,
        "canon_admitted": False,
        "historical_occurrence": {
            "observed": False,
            "matching_batches": [],
            "prior_human_decision": {"observed": False},
            "prior_canonical_admission": {"observed": False},
            "authority": "provenance_only",
        },
    }
    if not candidate_id or not isinstance(source, dict) or not isinstance(target, dict) or not isinstance(predicate, str):
        return base | {"disposition": "malformed", "reason": "candidate_id, source, target, or predicate is missing or malformed"}
    source_result = endpoint_resolution(source, indexes, candidate_id)
    target_result = endpoint_resolution(target, indexes, candidate_id)
    base.update({
        "source_resolution": source_result,
        "target_resolution": target_result,
        "source_canon_id": source_result.get("canonical_id"),
        "target_canon_id": target_result.get("canonical_id"),
        "source_version_id": source.get("sha256"),
        "target_version_id": target.get("sha256"),
        "target_raw": target.get("repo_path") or target.get("canonical_title"),
    })
    signature = candidate_signature(candidate, source_result.get("canonical_id"), target_result.get("canonical_id"))
    if signature:
        matches = historical_occurrences.get(signature, [])
        base["historical_occurrence"] = {
            "observed": bool(matches),
            "matching_batches": matches,
            "prior_human_decision": {"observed": False},
            "prior_canonical_admission": {"observed": False},
            "authority": "provenance_only",
        }
    if signature and signature in canonical_v1_signatures:
        base["canon_admitted"] = True
        return base | {
            "disposition": "already_canonically_admitted",
            "reason": "same source-target-predicate is present under canonical-relation/v1 in the runtime canon",
        }
    if signature and signature[0] == signature[1]:
        return base | {"disposition": "self_reference", "reason": "resolved source and target are the same canonical node"}
    if source_result["status"] == "missing_canonical_node":
        return base | {"disposition": "invalid_source", "reason": source_result["reason"]}
    if source_result["status"] != "resolved":
        return base | {"disposition": "not_canonicalizable", "reason": source_result["reason"], "source_mapping_class": "mapping_rule_absent_or_ambiguous"}
    if target_result["status"] == "missing_canonical_node":
        return base | {"disposition": "invalid_target", "reason": target_result["reason"]}
    if target_result["status"] != "resolved":
        return base | {"disposition": "unresolved_target", "reason": target_result["reason"], "target_class": target_result["status"]}
    if predicate not in ALLOWED_RELATION_TYPES:
        return base | {"disposition": "unsupported_predicate", "reason": "predicate is outside relation_candidate_contract.py"}
    signature = candidate_signature(candidate, source_result["canonical_id"], target_result["canonical_id"])
    assert signature is not None
    evidence = candidate.get("evidence") or {}
    if not evidence.get("evidence_kind") or not evidence.get("raw_observation"):
        return base | {"disposition": "insufficient_evidence", "reason": "missing evidence_kind or raw_observation"}
    if signature in seen_current:
        previous_id, previous_evidence = seen_current[signature]
        if previous_evidence == evidence_key(candidate):
            return base | {"disposition": "exact_duplicate", "reason": "exact duplicate edge and evidence inside current batch", "duplicate_of": previous_id}
    seen_current[signature] = (candidate_id, evidence_key(candidate))
    return base | {
        "disposition": "ready_for_review",
        "reason": "runtime source and target resolve uniquely; predicate and evidence satisfy the current contract",
        "relation_schema": "technical-candidate/v1",
    }


def historical_signatures(
    pipeline_root: Path,
    current_dir: Path,
    indexes: dict[str, Any],
) -> tuple[dict[tuple[str, str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    signatures: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    batches: list[dict[str, Any]] = []
    for child in sorted(pipeline_root.iterdir() if pipeline_root.exists() else []):
        if not child.is_dir() or child.resolve() == current_dir.resolve():
            continue
        candidates_file = child / "relation_candidates.jsonl"
        if not candidates_file.exists():
            candidates_file = child / "candidates.jsonl"
        classification = "historical"
        record: dict[str, Any] = {
            "batch_id": child.name,
            "path": repo_path(child),
            "classification": classification,
            "authority_for_current_operation": False,
            "candidate_file": repo_path(candidates_file) if candidates_file.exists() else None,
        }
        if not candidates_file.exists():
            record["reason"] = "no primary candidate JSONL found"
            batches.append(record)
            continue
        rows, malformed = read_jsonl(candidates_file)
        candidate_hash = sha256_file(candidates_file)
        record["manifest_hash"] = candidate_hash
        record["record_count"] = len(rows)
        record["malformed_count"] = len(malformed)
        for candidate in rows:
            candidate_id = str(candidate.get("candidate_id") or "")
            source = candidate.get("source") or {}
            target = candidate.get("target") or {}
            if not candidate_id or not isinstance(source, dict) or not isinstance(target, dict):
                continue
            src = endpoint_resolution(source, indexes, candidate_id).get("canonical_id")
            tgt = endpoint_resolution(target, indexes, candidate_id).get("canonical_id")
            signature = candidate_signature(candidate, src, tgt)
            if signature:
                signatures[signature].append({
                    "batch_id": child.name,
                    "manifest_hash": candidate_hash,
                    "candidate_id": candidate_id,
                    "signature_match": True,
                })
        batches.append(record)
    return signatures, batches


def preserved_pre_refresh_batches(out_dir: Path) -> list[dict[str, Any]]:
    """Classify S0180's audit snapshots without reintroducing them as inputs."""
    batches: list[dict[str, Any]] = []
    for child in sorted(out_dir.glob("*_current_candidate_batch")):
        candidates_file = child / "relation_candidates.jsonl"
        if not candidates_file.exists():
            continue
        rows, malformed = read_jsonl(candidates_file)
        batches.append({
            "path": repo_path(child),
            "classification": "stale",
            "reason": "preserved before S0180 authoritative current refresh",
            "candidate_file": repo_path(candidates_file),
            "candidate_hash": sha256_file(candidates_file),
            "record_count": len(rows),
            "malformed_count": len(malformed),
        })
    return batches


def build_baseline(
    canon_root: Path,
    productive_manifest: Path,
    current_file: Path,
    candidate_count: int,
    relation_inventory: dict[str, Any],
) -> dict[str, Any]:
    snapshot = canon_snapshot(canon_root)
    productive = read_json(productive_manifest)
    producer = REPO_ROOT / "src" / "python_scripts" / "derive_layers.py"
    writer = REPO_ROOT / "src" / "python_scripts" / "rag_derivative_writers.py"
    lineage = lineage_relation_counts(canon_root)
    query_paths = sorted(REPO_ROOT.glob("data/out/local/**/*query*set*"))
    query_path = next((path for path in query_paths if path.is_file()), None)
    return {
        "schema_version": "pre-relational-rag-baseline/v1",
        "created_at": "omitted_for_determinism",
        **snapshot,
        "productive_manifest_path": repo_path(productive_manifest),
        "productive_manifest_hash": sha256_file(productive_manifest),
        "producer_hash": sha256_file(producer),
        "writer_hash": sha256_file(writer),
        "equivalence_status": {"technical_gate": productive.get("technical_gate"), "governance_gate": productive.get("governance_gate")},
        "governance_status": productive.get("governance_gate"),
        "relation_authority_state": "DERIVATIVE_RELATION_AUTHORITY_AMBIGUOUS",
        "relations": {
            "canonical_relation_v1": relation_inventory["canonical_relation_v1"],
            "legacy_explicit_relations": relation_inventory["legacy_explicit_relations"],
            **lineage,
            "authority_verdict": "DERIVATIVE_RELATION_AUTHORITY_AMBIGUOUS",
        },
        "candidates": {
            "manifest_path": repo_path(current_file),
            "manifest_hash": sha256_file(current_file),
            "canon_hash": snapshot["canon_hash"],
            "total": candidate_count,
            "current": True,
        },
        "retrieval_control": {
            "query_set_path": repo_path(query_path) if query_path else None,
            "query_set_hash": sha256_file(query_path) if query_path else None,
            "corpus_manifest_hash": sha256_file(productive_manifest),
            "retrieval_config": None,
            "ranking_config": None,
            "top_k": None,
            "execution_status": "not_executed_no_stable_runner",
            "raw_results_path": None,
        },
        "immutability": {"comparison_target": "S0184/DT070", "input_surfaces_hashed_before_reconciliation": True},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile the permanent current relation-candidate batch")
    parser.add_argument("--canon-root", type=Path, default=DEFAULT_CANON_ROOT)
    parser.add_argument("--current-dir", type=Path, default=DEFAULT_CURRENT_DIR)
    parser.add_argument("--out-dir", "--audit-dir", dest="audit_dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--productive-manifest", type=Path, default=DEFAULT_PRODUCTIVE_MANIFEST)
    args = parser.parse_args()

    current_file = args.current_dir / "relation_candidates.jsonl"
    baseline_path = args.audit_dir / "pre_relational_rag_baseline_manifest.json"
    if not current_file.exists():
        raise SystemExit(f"current candidate batch missing: {current_file}")
    if not baseline_path.exists():
        raise SystemExit(f"immutable S0180 baseline missing: {baseline_path}")
    baseline_hash_before = sha256_file(baseline_path)
    args.current_dir.mkdir(parents=True, exist_ok=True)
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    candidates, malformed_rows = read_jsonl(current_file)
    nodes, _all_canonical_signatures = load_canon(args.canon_root)
    indexes = build_indexes(nodes)
    historical, historical_batches = historical_signatures(args.current_dir.parent, args.current_dir, indexes)
    relation_inventory = canonical_relation_inventory(args.canon_root)
    seen_current: dict[tuple[str, str, str], tuple[str, tuple[Any, ...]]] = {}
    matrix = [
        disposition_for(
            candidate,
            indexes,
            relation_inventory["canonical_v1_signatures"],
            seen_current,
            historical,
        )
        for candidate in candidates
    ]
    for bad in malformed_rows:
        matrix.append({
            "candidate_id": None,
            "disposition": "malformed",
            "reason": bad["error"],
            "line_number": bad["line_number"],
            "candidate_authority": "candidate",
            "canonical_authority_granted": False,
            "human_reviewed": False,
            "canon_admitted": False,
        })
    matrix.sort(key=lambda row: (str(row.get("candidate_id") or ""), int(row.get("line_number") or 0)))
    counts = Counter(row["disposition"] for row in matrix)
    if any(name not in DISPOSITIONS for name in counts) or sum(counts.values()) != len(matrix):
        raise SystemExit("reconciliation did not produce one allowed disposition per record")

    snapshot = canon_snapshot(args.canon_root)
    generator_path = REPO_ROOT / "src" / "python_scripts" / "generate_technical_relation_candidates.py"
    validator_path = REPO_ROOT / "src" / "python_scripts" / "validate_relation_candidates.py"
    contract_path = REPO_ROOT / "src" / "python_scripts" / "relation_candidate_contract.py"
    policy_path = REPO_ROOT / "src" / "python_scripts" / "relation_admission_policy.py"
    reconciler_path = Path(__file__).resolve()
    generation_report_path = args.current_dir / "relation_candidates_report.json"
    generation_report = read_json(generation_report_path) if generation_report_path.exists() else {}
    generated_at = str(generation_report.get("generated_at") or "omitted_for_determinism")
    namespace = "rc_current"
    ids = [str(candidate.get("candidate_id") or "") for candidate in candidates]
    if ids:
        prefixes = {"_".join(candidate_id.split("_")[:2]) for candidate_id in ids if "_" in candidate_id}
        if len(prefixes) == 1:
            namespace = next(iter(prefixes))
    configuration_hash = hashlib.sha256(json.dumps({
        "canon_root": repo_path(args.canon_root),
        "namespace": namespace,
        "dry_run": True,
    }, sort_keys=True).encode()).hexdigest()
    current_manifest = {
        "schema_version": "current-relation-candidate-manifest/v1",
        "candidate_batch": {
            "path": repo_path(current_file),
            "hash": sha256_file(current_file),
            "record_count": len(candidates),
            "namespace": namespace,
        },
        "canon_binding": {
            "canon_hash": snapshot["canon_hash"],
            "record_count": snapshot["canon_records"],
            "shards": snapshot["canon_shards"],
        },
        "producer": {
            "path": repo_path(generator_path),
            "hash": sha256_file(generator_path),
            "contract_hash": sha256_file(contract_path),
            "configuration_hash": configuration_hash,
        },
        "generated_at": generated_at,
        "authority": "technical_candidate_batch",
        "human_reviewed": False,
        "canon_admitted": False,
        "current": True,
        "provenance": {"generated_during_session": SESSION},
    }
    current_manifest_path = args.current_dir / "current_candidate_manifest.json"
    write_json(current_manifest_path, current_manifest)
    candidate_manifest_hash = sha256_file(current_manifest_path)
    mapping_summary = Counter()
    target_summary = Counter()
    for row in matrix:
        mapping_summary[str((row.get("source_resolution") or {}).get("status") or "malformed")] += 1
        target_summary[str((row.get("target_resolution") or {}).get("status") or "malformed")] += 1
    mapping_report = {
        "schema_version": "s0180-canonical-mapping-resolution/v1",
        "canon_hash": snapshot["canon_hash"],
        "source_resolution_counts": dict(sorted(mapping_summary.items())),
        "target_resolution_counts": dict(sorted(target_summary.items())),
        "deterministic_resolution_only": True,
        "ambiguous_mappings_forced": False,
    }
    duplicate_rows = [row for row in matrix if row["disposition"] in {"exact_duplicate", "already_canonically_admitted"}]
    duplicate_report = {
        "schema_version": "s0180-duplicate-resolution/v1",
        "counts": {name: counts.get(name, 0) for name in ("exact_duplicate", "already_canonically_admitted")},
        "historical_occurrences": sum(1 for row in matrix if (row.get("historical_occurrence") or {}).get("observed")),
        "historical_occurrence_is_primary_disposition": False,
        "legacy_is_canonical_v1": False,
        "legacy_promoted": False,
        "records": duplicate_rows,
    }
    unresolved_rows = [row for row in matrix if row["disposition"] in {"unresolved_target", "invalid_target"}]
    unresolved_report = {
        "schema_version": "s0180-unresolved-target-resolution/v1",
        "counts": {name: counts.get(name, 0) for name in ("unresolved_target", "invalid_target")},
        "deterministic_resolutions_only": True,
        "records": unresolved_rows,
    }
    historical_report = {
        "schema_version": "s0180-historical-candidate-classification/v1",
        "current_authority_path": repo_path(current_manifest_path),
        "single_current_manifest": True,
        "historical_batches": historical_batches + preserved_pre_refresh_batches(args.audit_dir),
    }
    ready = [row for row in matrix if row["disposition"] == "ready_for_review"]
    by_id = {str(candidate.get("candidate_id")): candidate for candidate in candidates}
    ready_rows = [
        by_id[str(row["candidate_id"])] | {
            "status": "ready_for_review",
            "authority": "technical_review_queue",
            "human_reviewed": False,
            "canon_admitted": False,
            "canonical_authority_granted": False,
            "reconciliation": row,
        }
        for row in ready
    ]
    matrix_current_path = args.current_dir / "candidate_reconciliation_matrix.jsonl"
    write_jsonl(matrix_current_path, matrix)
    ready_path = args.current_dir / "ready_for_human_review.jsonl"
    write_jsonl(ready_path, ready_rows)
    reconciliation_manifest = {
        "schema_version": "relation-candidate-reconciliation-manifest/v1",
        "candidate_manifest_hash": candidate_manifest_hash,
        "canon_hash": snapshot["canon_hash"],
        "predicate_policy_hash": sha256_file(policy_path),
        "candidate_contract_hash": sha256_file(contract_path),
        "reconciler_path": repo_path(reconciler_path),
        "reconciler_hash": sha256_file(reconciler_path),
        "matrix_path": repo_path(matrix_current_path),
        "matrix_hash": sha256_file(matrix_current_path),
        "total": len(matrix),
        "unclassified": 0,
        "dispositions": {name: counts.get(name, 0) for name in DISPOSITIONS},
        "historical_occurrences": {
            "observed": any((row.get("historical_occurrence") or {}).get("observed") for row in matrix),
            "candidates_with_history": sum(1 for row in matrix if (row.get("historical_occurrence") or {}).get("observed")),
            "authority": "provenance_only",
        },
        "generated_at": generated_at,
        "current": True,
    }
    reconciliation_manifest_path = args.current_dir / "reconciliation_manifest.json"
    write_json(reconciliation_manifest_path, reconciliation_manifest)
    review_manifest = {
        "schema_version": "reviewable-relation-candidate-manifest/v1",
        "canon_hash": snapshot["canon_hash"],
        "candidate_manifest_hash": candidate_manifest_hash,
        "reconciliation_manifest_hash": sha256_file(reconciliation_manifest_path),
        "predicate_policy_hash": sha256_file(policy_path),
        "candidate_contract_hash": sha256_file(contract_path),
        "record_count": len(ready_rows),
        "records_hash": sha256_file(ready_path),
        "generated_at": generated_at,
        "authority": "technical_review_queue",
        "human_reviewed": False,
        "canon_admitted": False,
        "current": True,
    }
    review_manifest_path = args.current_dir / "reviewable_candidate_manifest.json"
    write_json(review_manifest_path, review_manifest)

    initial_matrix_path = args.audit_dir / "history" / "initial_closure" / "candidate_reconciliation_matrix.jsonl"
    initial_matrix, _ = read_jsonl(initial_matrix_path) if initial_matrix_path.exists() else ([], [])
    valid_path = args.current_dir / "valid_candidates.jsonl"
    invalid_path = args.current_dir / "invalid_candidates.jsonl"
    valid_rows, _ = read_jsonl(valid_path) if valid_path.exists() else ([], [])
    invalid_rows, _ = read_jsonl(invalid_path) if invalid_path.exists() else ([], [])
    valid_ids = {str(row.get("candidate_id")) for row in valid_rows}
    historical_ids = {str(row.get("candidate_id")) for row in initial_matrix if row.get("disposition") == "historical_duplicate"}
    decisions_path = args.current_dir / "human_review_decisions.jsonl"
    current_decisions, _ = read_jsonl(decisions_path) if decisions_path.exists() else ([], [])
    root_cause_report = {
        "schema_version": "historical-occurrence-reclassification-report/v1",
        "candidate_manifest_hash": candidate_manifest_hash,
        "canon_hash": snapshot["canon_hash"],
        "validator": {"total": len(valid_rows) + len(invalid_rows), "valid": len(valid_rows), "invalid": len(invalid_rows)},
        "initial_reconciliation": dict(sorted(Counter(str(row.get("disposition")) for row in initial_matrix).items())),
        "set_comparison": {
            "valid_ids_count": len(valid_ids),
            "historical_duplicate_ids_count": len(historical_ids),
            "intersection_count": len(valid_ids & historical_ids),
            "valid_not_historical_count": len(valid_ids - historical_ids),
            "historical_not_valid_count": len(historical_ids - valid_ids),
            "sets_equal": valid_ids == historical_ids,
            "valid_not_historical_ids": sorted(valid_ids - historical_ids),
            "historical_not_valid_ids": sorted(historical_ids - valid_ids),
        },
        "decision_evidence": {
            "current_human_review_decisions": len(current_decisions),
            "historical_human_review_decisions": 0,
            "successful_apply_observed": False,
            "canon_modified_by_relational_apply": False,
        },
        "root_cause": {
            "proven": valid_ids == historical_ids and not current_decisions,
            "classification": "historical_occurrence_used_as_terminal_disposition",
            "explanation": "Historical batch appearance was treated as a veto although current validation passed and no human decision or canonical v1 admission existed.",
        },
    }
    summary = [
        "# S0180 — Cierre correctivo de reconciliación técnica",
        "",
        f"- Runtime canon: `{snapshot['canon_hash']}` ({snapshot['canon_records']} records / {snapshot['canon_shards']} shards).",
        f"- Immutable baseline hash: `{baseline_hash_before}`.",
        f"- Permanent current manifest: `{candidate_manifest_hash}` ({len(candidates)} candidates).",
        f"- Disposiciones: `{json.dumps(dict(sorted(counts.items())), ensure_ascii=False, sort_keys=True)}`.",
        f"- Ready for human review: `{len(ready_rows)}`; human_reviewed=false; canon_admitted=false.",
        f"- Historical occurrences: `{reconciliation_manifest['historical_occurrences']['candidates_with_history']}` (provenance only).",
        "- No candidate was marked approved, accepted, canonical, or admitted.",
        "- No legacy relation was promoted to canonical-relation/v1.",
        "",
        "## Autoridad y límites",
        "",
        "La salida conserva autoridad `candidate`. `ready_for_review` es una disposición técnica y no una decisión humana ni una instrucción de apply.",
        "",
    ]
    write_jsonl(args.audit_dir / "candidate_reconciliation_matrix.jsonl", matrix)
    write_json(args.audit_dir / "canonical_mapping_resolution.json", mapping_report)
    write_json(args.audit_dir / "duplicate_resolution_report.json", duplicate_report)
    write_json(args.audit_dir / "unresolved_target_resolution.json", unresolved_report)
    write_json(args.audit_dir / "historical_candidate_classification.json", historical_report)
    write_json(args.audit_dir / "historical_occurrence_reclassification_report.json", root_cause_report)
    write_json(args.audit_dir / "current_candidate_manifest.json", {
        "schema_version": "s0180-current-candidate-manifest-evidence/v1",
        "operational_manifest_path": repo_path(current_manifest_path),
        "operational_manifest_hash": candidate_manifest_hash,
        "authority_for_current_operation": False,
        "captured_payload": current_manifest,
    })
    (args.audit_dir / "candidate_reconciliation_summary.md").write_text("\n".join(summary), encoding="utf-8")
    if sha256_file(baseline_path) != baseline_hash_before:
        raise SystemExit("immutable S0180 baseline changed during reconciliation")
    print(json.dumps({
        "candidate_count": len(matrix),
        "unclassified": 0,
        "ready_for_review": len(ready_rows),
        "dispositions": dict(sorted(counts.items())),
        "canon_modified": False,
        "derivatives_modified": False,
        "historical_occurrences": reconciliation_manifest["historical_occurrences"]["candidates_with_history"],
        "current_dir": repo_path(args.current_dir),
        "audit_dir": repo_path(args.audit_dir),
        "baseline_unchanged": True,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
