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

from relation_candidate_contract import ALLOWED_RELATION_TYPES, CANDIDATE_ID_RE
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
S0183_RECONCILIATION_CLASSES = (
    "equivalent",
    "modified",
    "disappeared",
    "new",
    "ambiguous",
    "invalid",
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


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _endpoint_semantic_identity(endpoint: Any) -> str:
    if not isinstance(endpoint, dict):
        return ""
    return _normalized_text(
        endpoint.get("canonical_id")
        or endpoint.get("tiddler_id")
        or endpoint.get("repo_path")
        or endpoint.get("canonical_title")
    )


def candidate_semantic_payload(candidate: Any, *, include_evidence: bool = True) -> dict[str, Any] | None:
    """Return decision-relevant semantics, deliberately excluding volatile IDs.

    Candidate IDs, line numbers, timestamps, file hashes, and current-manifest
    bindings are regeneration details.  Reusing a human decision is allowed
    only when the resolved endpoints, predicate, evidence kind, observed text,
    and lifecycle semantics remain equal.
    """
    if not isinstance(candidate, dict):
        return None
    candidate_id = str(candidate.get("candidate_id") or "")
    source = candidate.get("source")
    target = candidate.get("target")
    predicate = _normalized_text(
        candidate.get("relation_type") or (candidate.get("relation") or {}).get("type")
    )
    source_id = _endpoint_semantic_identity(source)
    target_id = _endpoint_semantic_identity(target)
    if (
        not candidate_id
        or CANDIDATE_ID_RE.fullmatch(candidate_id) is None
        or not isinstance(source, dict)
        or not isinstance(target, dict)
        or not source_id
        or not target_id
        or not predicate
    ):
        return None
    payload: dict[str, Any] = {
        "source": source_id,
        "target": target_id,
        "predicate": predicate,
        "source_lifecycle": _normalized_text(source.get("repo_lifecycle_state") or source.get("lifecycle_state")),
        "target_lifecycle": _normalized_text(target.get("repo_lifecycle_state") or target.get("lifecycle_state")),
    }
    if include_evidence:
        evidence = candidate.get("evidence")
        if not isinstance(evidence, dict):
            return None
        evidence_kind = _normalized_text(evidence.get("evidence_kind"))
        raw_observation = _normalized_text(evidence.get("raw_observation"))
        if not evidence_kind or not raw_observation:
            return None
        payload["evidence"] = {
            "kind": evidence_kind,
            "parser": _normalized_text(evidence.get("parser")),
            "technical_kind": _normalized_text(
                evidence.get("technical_evidence_kind") or evidence.get("technical_kind")
            ),
            "raw_observation": raw_observation,
        }
    return payload


def _payload_hash(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_cross_batch_reconciliation(
    historical_candidates: list[dict[str, Any]],
    current_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify every old and current candidate under S0183's closed taxonomy."""
    sides = {"historical": historical_candidates, "current": current_candidates}
    prepared: dict[str, list[dict[str, Any]]] = {}
    duplicate_ids: dict[str, set[str]] = {}
    for side, candidates in sides.items():
        id_counts = Counter(str(row.get("candidate_id") or "") for row in candidates if isinstance(row, dict))
        duplicate_ids[side] = {candidate_id for candidate_id, count in id_counts.items() if candidate_id and count > 1}
        prepared[side] = []
        for row in candidates:
            candidate_id = str(row.get("candidate_id") or "") if isinstance(row, dict) else ""
            semantic = candidate_semantic_payload(row)
            base = candidate_semantic_payload(row, include_evidence=False)
            prepared[side].append({
                "candidate_id": candidate_id or None,
                "semantic": semantic,
                "semantic_fingerprint": _payload_hash(semantic),
                "base_fingerprint": _payload_hash(base),
                "invalid": semantic is None or candidate_id in duplicate_ids[side],
            })

    semantic_index: dict[str, dict[str, list[int]]] = {
        side: defaultdict(list) for side in sides
    }
    base_index: dict[str, dict[str, list[int]]] = {
        side: defaultdict(list) for side in sides
    }
    for side, rows in prepared.items():
        for index, row in enumerate(rows):
            if row["invalid"]:
                continue
            semantic_index[side][str(row["semantic_fingerprint"])].append(index)
            base_index[side][str(row["base_fingerprint"])].append(index)

    pairings: dict[tuple[str, int], tuple[str, int, str, str]] = {}
    used_current: set[int] = set()
    current_by_id = {
        str(row["candidate_id"]): index
        for index, row in enumerate(prepared["current"])
        if not row["invalid"]
    }
    for old_index, old in enumerate(prepared["historical"]):
        current_index = current_by_id.get(str(old["candidate_id"]))
        if (
            not old["invalid"]
            and current_index is not None
            and old["semantic_fingerprint"] == prepared["current"][current_index]["semantic_fingerprint"]
        ):
            pairings[("historical", old_index)] = (
                "current", current_index, "equivalent",
                "stable candidate_id and decision-relevant semantics are equal",
            )
            pairings[("current", current_index)] = (
                "historical", old_index, "equivalent",
                "stable candidate_id and decision-relevant semantics are equal",
            )
            used_current.add(current_index)

    for old_index, old in enumerate(prepared["historical"]):
        if old["invalid"] or ("historical", old_index) in pairings:
            continue
        semantic_matches = [
            index for index in semantic_index["current"].get(str(old["semantic_fingerprint"]), [])
            if index not in used_current
        ]
        reverse_semantic = [
            index for index in semantic_index["historical"].get(str(old["semantic_fingerprint"]), [])
            if ("historical", index) not in pairings
        ]
        if len(semantic_matches) == 1 and len(reverse_semantic) == 1:
            current_index = semantic_matches[0]
            pairings[("historical", old_index)] = ("current", current_index, "equivalent", "decision-relevant semantics are equal")
            pairings[("current", current_index)] = ("historical", old_index, "equivalent", "decision-relevant semantics are equal")
            used_current.add(current_index)

    for old_index, old in enumerate(prepared["historical"]):
        if old["invalid"] or ("historical", old_index) in pairings:
            continue
        base_matches = [
            index for index in base_index["current"].get(str(old["base_fingerprint"]), [])
            if index not in used_current
        ]
        reverse_base = base_index["historical"].get(str(old["base_fingerprint"]), [])
        if len(base_matches) == 1 and len(reverse_base) == 1:
            current_index = base_matches[0]
            pairings[("historical", old_index)] = ("current", current_index, "modified", "same endpoints and predicate but evidence semantics changed")
            pairings[("current", current_index)] = ("historical", old_index, "modified", "same endpoints and predicate but evidence semantics changed")
            used_current.add(current_index)

    def classify(side: str, index: int, row: dict[str, Any]) -> dict[str, Any]:
        other = "current" if side == "historical" else "historical"
        if row["invalid"]:
            classification, reason, counterpart = "invalid", "candidate is malformed or has a duplicate candidate_id", None
        elif (side, index) in pairings:
            _other, other_index, classification, reason = pairings[(side, index)]
            counterpart = prepared[other][other_index]["candidate_id"]
        else:
            semantic_matches = semantic_index[other].get(str(row["semantic_fingerprint"]), [])
            base_matches = base_index[other].get(str(row["base_fingerprint"]), [])
            if semantic_matches or base_matches:
                classification, reason, counterpart = "ambiguous", "multiple or non-bijective semantic matches", None
            elif side == "historical":
                classification, reason, counterpart = "disappeared", "no current candidate shares the semantic or endpoint-predicate identity", None
            else:
                classification, reason, counterpart = "new", "no historical candidate shares the semantic or endpoint-predicate identity", None
        return {
            "candidate_id": row["candidate_id"],
            "counterpart_candidate_id": counterpart,
            "classification": classification,
            "reason": reason,
            "semantic_fingerprint": row["semantic_fingerprint"],
            "base_fingerprint": row["base_fingerprint"],
            "decision_reusable": classification == "equivalent",
        }

    old_rows = [classify("historical", index, row) for index, row in enumerate(prepared["historical"])]
    current_rows = [classify("current", index, row) for index, row in enumerate(prepared["current"])]
    old_rows.sort(key=lambda row: str(row.get("candidate_id") or ""))
    current_rows.sort(key=lambda row: str(row.get("candidate_id") or ""))
    old_counts = Counter(str(row["classification"]) for row in old_rows)
    current_counts = Counter(str(row["classification"]) for row in current_rows)
    return {
        "old_to_current": old_rows,
        "current_to_old": current_rows,
        "old_counts": {name: old_counts.get(name, 0) for name in S0183_RECONCILIATION_CLASSES},
        "current_counts": {name: current_counts.get(name, 0) for name in S0183_RECONCILIATION_CLASSES},
    }


def write_cross_batch_reconciliation(
    *,
    historical_candidates_file: Path,
    current_candidates_file: Path,
    out_dir: Path,
) -> Path:
    historical, historical_malformed = read_jsonl(historical_candidates_file)
    current, current_malformed = read_jsonl(current_candidates_file)
    if historical_malformed or current_malformed:
        raise ValueError("cross-batch reconciliation requires valid JSONL candidate batches")
    result = build_cross_batch_reconciliation(historical, current)
    out_dir.mkdir(parents=True, exist_ok=True)
    old_path = out_dir / "old_to_current_reconciliation.jsonl"
    current_path = out_dir / "current_to_old_reconciliation.jsonl"
    write_jsonl(old_path, result["old_to_current"])
    write_jsonl(current_path, result["current_to_old"])
    manifest = {
        "schema_version": "s0183-cross-batch-reconciliation/v1",
        "session_id": "m04-s0183",
        "taxonomy": list(S0183_RECONCILIATION_CLASSES),
        "historical_candidates_path": repo_path(historical_candidates_file),
        "historical_candidates_hash": sha256_file(historical_candidates_file),
        "current_candidates_path": repo_path(current_candidates_file),
        "current_candidates_hash": sha256_file(current_candidates_file),
        "old_to_current_path": repo_path(old_path),
        "old_to_current_hash": sha256_file(old_path),
        "current_to_old_path": repo_path(current_path),
        "current_to_old_hash": sha256_file(current_path),
        "old_counts": result["old_counts"],
        "current_counts": result["current_counts"],
        "coverage_complete": (
            sum(result["old_counts"].values()) == len(historical)
            and sum(result["current_counts"].values()) == len(current)
        ),
        "decision_reuse_rule": "equivalent_only",
        "human_authority_created": False,
        "canon_modified": False,
    }
    path = out_dir / "cross_batch_reconciliation_manifest.json"
    write_json(path, manifest)
    return path


def write_s0183_entry_baseline(
    *,
    canon_root: Path,
    preservation_dir: Path,
    output_path: Path,
    contract_path: Path,
    git_branch: str,
    git_head: str,
) -> Path:
    """Bind S0183's entry state and its byte-preserved historical authority."""
    if not preservation_dir.is_dir():
        raise ValueError(f"entry preservation directory does not exist: {preservation_dir}")
    files = []
    for path in sorted(item for item in preservation_dir.rglob("*") if item.is_file()):
        files.append({
            "path": repo_path(path),
            "relative_path": path.relative_to(preservation_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    historical_candidates = preservation_dir / "pipeline_current" / "relation_candidates.jsonl"
    historical_decisions = preservation_dir / "pipeline_current" / "human_review_decisions.jsonl"
    candidates, candidate_errors = read_jsonl(historical_candidates)
    decisions, decision_errors = read_jsonl(historical_decisions)
    if candidate_errors or decision_errors:
        raise ValueError("preserved candidate or decision JSONL is malformed")
    snapshot = canon_snapshot(canon_root)
    manifest = {
        "schema_version": "s0183-impact-entry-baseline/v1",
        "session_id": "m04-s0183",
        "git": {"branch": git_branch, "head": git_head},
        "canon": snapshot,
        "contract_path": repo_path(contract_path),
        "contract_hash": sha256_file(contract_path),
        "preservation_dir": repo_path(preservation_dir),
        "preserved_file_count": len(files),
        "preserved_files": files,
        "historical_candidates": {
            "path": repo_path(historical_candidates),
            "sha256": sha256_file(historical_candidates),
            "records": len(candidates),
        },
        "historical_decisions": {
            "path": repo_path(historical_decisions),
            "sha256": sha256_file(historical_decisions),
            "records": len(decisions),
            "counts": dict(sorted(Counter(
                str(row.get("human_review_decision") or "unknown") for row in decisions
            ).items())),
            "byte_preservation_required": True,
        },
        "entry_currentness": "stale_expected",
        "production_apply_authorized": False,
        "canon_modified": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, manifest)
    return output_path


def write_isolated_run_determinism_report(
    *,
    run_a: Path,
    run_b: Path,
    output_path: Path,
) -> Path:
    """Compare isolated runs while excluding timestamps, paths, and run labels."""
    exact_relative_paths = (
        "current/relation_candidates.jsonl",
        "current/valid_candidates.jsonl",
        "current/invalid_candidates.jsonl",
        "current/unresolved_candidates.jsonl",
        "current/duplicate_candidates.jsonl",
        "current/candidate_reconciliation_matrix.jsonl",
        "current/ready_for_human_review.jsonl",
        "audit/old_to_current_reconciliation.jsonl",
        "audit/current_to_old_reconciliation.jsonl",
    )
    exact = []
    for relative in exact_relative_paths:
        left, right = run_a / relative, run_b / relative
        exact.append({
            "relative_path": relative,
            "run_a_hash": sha256_file(left),
            "run_b_hash": sha256_file(right),
            "equal": left.read_bytes() == right.read_bytes(),
        })

    generation_keys = ("session", "candidate_count", "ready_for_review_count", "blocked_count", "dry_run")
    generation_a = read_json(run_a / "current" / "relation_candidates_report.json")
    generation_b = read_json(run_b / "current" / "relation_candidates_report.json")
    validation_a = read_json(run_a / "current" / "validation_report.json")
    validation_b = read_json(run_b / "current" / "validation_report.json")
    reconciliation_a = read_json(run_a / "current" / "reconciliation_manifest.json")
    reconciliation_b = read_json(run_b / "current" / "reconciliation_manifest.json")
    cross_a = read_json(run_a / "audit" / "cross_batch_reconciliation_manifest.json")
    cross_b = read_json(run_b / "audit" / "cross_batch_reconciliation_manifest.json")
    semantic = {
        "generation": {
            "run_a": {key: generation_a.get(key) for key in generation_keys},
            "run_b": {key: generation_b.get(key) for key in generation_keys},
        },
        "validation": {
            "run_a": validation_a.get("summary") or {},
            "run_b": validation_b.get("summary") or {},
        },
        "reconciliation": {
            "run_a": {
                key: reconciliation_a.get(key)
                for key in ("canon_hash", "total", "unclassified", "dispositions")
            },
            "run_b": {
                key: reconciliation_b.get(key)
                for key in ("canon_hash", "total", "unclassified", "dispositions")
            },
        },
        "cross_batch": {
            "run_a": {
                key: cross_a.get(key)
                for key in ("taxonomy", "old_counts", "current_counts", "coverage_complete")
            },
            "run_b": {
                key: cross_b.get(key)
                for key in ("taxonomy", "old_counts", "current_counts", "coverage_complete")
            },
        },
    }
    semantic_equal = all(
        values["run_a"] == values["run_b"] for values in semantic.values()
    )
    report = {
        "schema_version": "s0183-isolated-run-determinism/v1",
        "session_id": "m04-s0183",
        "run_a": repo_path(run_a),
        "run_b": repo_path(run_b),
        "exact_artifacts": exact,
        "exact_artifacts_equal": all(item["equal"] for item in exact),
        "semantic_summaries": semantic,
        "semantic_summaries_equal": semantic_equal,
        "equivalent": semantic_equal and all(item["equal"] for item in exact),
        "excluded_volatile_fields": ["generated_at", "run_id", "out_dir", "artifact_paths"],
        "canon_modified": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, report)
    return output_path


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
    parser.add_argument("--historical-candidates", type=Path)
    parser.add_argument("--cross-batch-out-dir", type=Path)
    parser.add_argument("--write-entry-baseline-only", action="store_true")
    parser.add_argument("--entry-preservation-dir", type=Path)
    parser.add_argument("--entry-baseline-output", type=Path)
    parser.add_argument("--preimpact-contract", type=Path)
    parser.add_argument("--git-branch", default="")
    parser.add_argument("--git-head", default="")
    parser.add_argument("--compare-runs-a", type=Path)
    parser.add_argument("--compare-runs-b", type=Path)
    parser.add_argument("--determinism-output", type=Path)
    args = parser.parse_args()
    if args.compare_runs_a or args.compare_runs_b:
        if not args.compare_runs_a or not args.compare_runs_b or not args.determinism_output:
            raise SystemExit("--compare-runs-a, --compare-runs-b, and --determinism-output are required")
        path = write_isolated_run_determinism_report(
            run_a=args.compare_runs_a,
            run_b=args.compare_runs_b,
            output_path=args.determinism_output,
        )
        report = read_json(path)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["equivalent"] else 3
    if args.write_entry_baseline_only:
        if not args.entry_preservation_dir or not args.entry_baseline_output or not args.preimpact_contract:
            raise SystemExit(
                "--entry-preservation-dir, --entry-baseline-output, and --preimpact-contract are required"
            )
        path = write_s0183_entry_baseline(
            canon_root=args.canon_root,
            preservation_dir=args.entry_preservation_dir,
            output_path=args.entry_baseline_output,
            contract_path=args.preimpact_contract,
            git_branch=args.git_branch,
            git_head=args.git_head,
        )
        print(json.dumps({"entry_baseline": repo_path(path), "canon_modified": False}, indent=2))
        return 0

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
    cross_batch_path = None
    if args.historical_candidates:
        cross_batch_path = write_cross_batch_reconciliation(
            historical_candidates_file=args.historical_candidates,
            current_candidates_file=current_file,
            out_dir=args.cross_batch_out_dir or args.audit_dir,
        )
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
        "cross_batch_reconciliation": repo_path(cross_batch_path) if cross_batch_path else None,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
