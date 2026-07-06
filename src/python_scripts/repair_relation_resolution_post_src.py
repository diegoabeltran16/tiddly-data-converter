#!/usr/bin/env python3
"""Repair S0161 technical relation resolution after the manual src/ migration.

Dry-run only. Reads the current local canon plus S0161 candidate evidence,
builds an audited post-src path equivalence table, and reclassifies every
candidate into reviewable, still blocked, or duplicate buckets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from relation_candidate_contract import ALLOWED_RELATION_TYPES

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANON_ROOT = REPO_ROOT / "data" / "out" / "local"
DEFAULT_INPUT_CANDIDATES = (
    DEFAULT_CANON_ROOT / "pipeline" / "relation_candidates" / "s0161" / "candidates.jsonl"
)
DEFAULT_INPUT_BLOCKED = (
    DEFAULT_CANON_ROOT / "pipeline" / "relation_candidates" / "s0161" / "blocked_candidates.jsonl"
)
DEFAULT_OUT_DIR = DEFAULT_CANON_ROOT / "pipeline" / "relation_resolution" / "s0162"
DEFAULT_SESSION = "S0162"
DEFAULT_RUN_ID = "s0162-post-src-resolution"

SCHEMA_MANIFEST = "s0162-post-src-mapping-manifest/v1"
SCHEMA_EQUIVALENCE = "s0162-path-equivalence/v1"
SCHEMA_INDEX = "s0162-canonical-resolution-index/v1"
SCHEMA_SUMMARY = "s0162-resolution-summary/v1"
SCHEMA_VALIDATION = "s0162-resolution-validation-report/v1"
SCHEMA_OPERATOR_REVIEW = "s0162-operator-review-manifest/v1"

RESOLVED = "resolved_for_human_review"
STILL_UNKNOWN = "still_blocked_unknown_canonical_mapping"
STILL_UNRESOLVED = "still_blocked_unresolved_target"
STILL_AMBIGUOUS = "still_blocked_ambiguous_mapping"
STILL_MISSING_NODE = "still_blocked_missing_canonical_node"
POSSIBLE_DUPLICATE = "possible_duplicate"
CONFIRMED_DUPLICATE = "confirmed_duplicate"
ALREADY_REPRESENTED = "already_represented"
OUT_OF_SCOPE_HISTORICAL = "out_of_scope_historical"
SCHEMA_INCOMPATIBLE = "schema_incompatible"
NEEDS_MANUAL_REVIEW = "needs_manual_review"

CLASSIFICATIONS = {
    RESOLVED,
    STILL_UNKNOWN,
    STILL_UNRESOLVED,
    STILL_AMBIGUOUS,
    STILL_MISSING_NODE,
    POSSIBLE_DUPLICATE,
    CONFIRMED_DUPLICATE,
    ALREADY_REPRESENTED,
    OUT_OF_SCOPE_HISTORICAL,
    SCHEMA_INCOMPATIBLE,
    NEEDS_MANUAL_REVIEW,
}

POST_SRC_PREFIXES: tuple[tuple[str, str], ...] = (
    ("go/", "src/go/"),
    ("python_scripts/", "src/python_scripts/"),
    ("rust/", "src/rust/"),
    ("shell_scripts/", "src/shell_scripts/"),
)


@dataclass(frozen=True)
class CanonNode:
    canonical_id: str
    title: str
    key: str
    canonical_slug: str
    version_id: str
    repo_path: str | None
    source_path: str | None
    artifact_family: str | None
    authority_level: str | None
    repo_lifecycle_state: str | None
    canonical_status: str | None
    shard_path: str
    line_no: int

    def payload(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "title": self.title,
            "key": self.key,
            "canonical_slug": self.canonical_slug,
            "version_id": self.version_id,
            "repo_path": self.repo_path,
            "source_path": self.source_path,
            "artifact_family": self.artifact_family,
            "authority_level": self.authority_level,
            "repo_lifecycle_state": self.repo_lifecycle_state,
            "canonical_status": self.canonical_status,
            "shard_path": self.shard_path,
            "line_no": self.line_no,
        }


@dataclass(frozen=True)
class Resolution:
    status: str
    node: CanonNode | None
    observed_path: str | None
    normalized_path: str | None
    method: str
    reason: str
    candidate_ids: tuple[str, ...]

    @property
    def canonical_id(self) -> str | None:
        return self.node.canonical_id if self.node else None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def run_readonly(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def canonicalize_observed_path(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return value or None


def normalize_post_src(raw: str | None) -> tuple[str | None, str]:
    value = canonicalize_observed_path(raw)
    if value is None:
        return None, "missing"
    for old, new in POST_SRC_PREFIXES:
        if value.startswith(old):
            return new + value[len(old):], "old_to_src_prefix"
    return value, "identity"


def old_alias_for_src(raw: str | None) -> str | None:
    value = canonicalize_observed_path(raw)
    if value is None:
        return None
    for old, new in POST_SRC_PREFIXES:
        if value.startswith(new):
            return old + value[len(new):]
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canon_snapshot(canon_root: Path) -> dict[str, Any]:
    files = []
    aggregate = hashlib.sha256()
    total_lines = 0
    for path in sorted(canon_root.glob("tiddlers_*.jsonl")):
        data = path.read_bytes()
        aggregate.update(data)
        line_count = data.count(b"\n")
        total_lines += line_count
        files.append({
            "path": repo_display(path),
            "line_count": line_count,
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return {
        "canon_input_path": repo_display(canon_root / "tiddlers_*.jsonl"),
        "canon_input_file_count": len(files),
        "canon_input_line_count": total_lines,
        "canon_input_sha256": aggregate.hexdigest(),
        "canon_input_files": files,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            rec = json.loads(raw)
            if not isinstance(rec, dict):
                raise ValueError(f"{path}:{line_no}: JSONL record must be object")
            records.append(rec)
    return records


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    rows = list(records)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return len(rows)


def load_canon(canon_root: Path) -> tuple[list[CanonNode], set[tuple[str, str, str]]]:
    nodes: list[CanonNode] = []
    relations: set[tuple[str, str, str]] = set()
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        with shard.open(encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                if not raw.strip():
                    continue
                rec = json.loads(raw)
                cid = str(rec.get("id") or "")
                if not cid:
                    continue
                for rel in rec.get("relations") or []:
                    if not isinstance(rel, dict):
                        continue
                    target_id = str(rel.get("target_id") or "")
                    rel_type = str(rel.get("type") or "")
                    if target_id and rel_type:
                        relations.add((cid, target_id, rel_type))
                sf = rec.get("source_fields") or {}
                nodes.append(CanonNode(
                    canonical_id=cid,
                    title=str(rec.get("title") or ""),
                    key=str(rec.get("key") or ""),
                    canonical_slug=str(rec.get("canonical_slug") or ""),
                    version_id=str(rec.get("version_id") or ""),
                    repo_path=canonicalize_observed_path(sf.get("repo_path")),
                    source_path=canonicalize_observed_path(sf.get("source_path")),
                    artifact_family=sf.get("artifact_family"),
                    authority_level=sf.get("authority_level"),
                    repo_lifecycle_state=sf.get("repo_lifecycle_state"),
                    canonical_status=sf.get("canonical_status"),
                    shard_path=repo_display(shard),
                    line_no=line_no,
                ))
    return nodes, relations


def add_index(index: dict[str, list[CanonNode]], key: str | None, node: CanonNode) -> None:
    if key:
        index[key].append(node)


def build_indexes(nodes: list[CanonNode]) -> dict[str, Any]:
    by_id = {node.canonical_id: node for node in nodes}
    by_title: dict[str, list[CanonNode]] = defaultdict(list)
    by_key: dict[str, list[CanonNode]] = defaultdict(list)
    by_slug: dict[str, list[CanonNode]] = defaultdict(list)
    by_path: dict[str, list[CanonNode]] = defaultdict(list)
    aliases_by_canonical_id: dict[str, set[str]] = defaultdict(set)

    for node in nodes:
        add_index(by_title, node.title, node)
        add_index(by_key, node.key, node)
        add_index(by_slug, node.canonical_slug, node)
        for raw_path in (node.repo_path, node.source_path):
            value = canonicalize_observed_path(raw_path)
            if not value:
                continue
            add_index(by_path, value, node)
            aliases_by_canonical_id[node.canonical_id].add(value)
            normalized, method = normalize_post_src(value)
            if normalized and method == "old_to_src_prefix":
                add_index(by_path, normalized, node)
                aliases_by_canonical_id[node.canonical_id].add(normalized)
            historical = old_alias_for_src(value)
            if historical:
                add_index(by_path, historical, node)
                aliases_by_canonical_id[node.canonical_id].add(historical)

    return {
        "by_id": by_id,
        "by_title": by_title,
        "by_key": by_key,
        "by_slug": by_slug,
        "by_path": by_path,
        "aliases_by_canonical_id": aliases_by_canonical_id,
    }


def unique_node(nodes: list[CanonNode]) -> CanonNode | None:
    unique = {node.canonical_id: node for node in nodes}
    if len(unique) == 1:
        return next(iter(unique.values()))
    return None


def resolve_endpoint(
    endpoint: dict[str, Any],
    indexes: dict[str, Any],
    *,
    candidate_id: str,
) -> Resolution:
    by_id: dict[str, CanonNode] = indexes["by_id"]
    by_path: dict[str, list[CanonNode]] = indexes["by_path"]
    canonical_id = endpoint.get("canonical_id")
    observed = canonicalize_observed_path(endpoint.get("repo_path"))
    normalized, method = normalize_post_src(observed)

    if canonical_id:
        node = by_id.get(str(canonical_id))
        if not node:
            return Resolution("missing_canonical_node", None, observed, normalized, "candidate_canonical_id", "candidate canonical_id not found in current canon", (candidate_id,))
        return Resolution("resolved", node, observed, normalized, "candidate_canonical_id", "candidate canonical_id verified against current canon", (candidate_id,))

    candidates = by_path.get(normalized or "", [])
    node = unique_node(candidates)
    if node:
        return Resolution("resolved", node, observed, normalized, f"path:{method}", "unique canonical node matched by normalized repo_path", (candidate_id,))
    if candidates:
        return Resolution("ambiguous", None, observed, normalized, f"path:{method}", "normalized path maps to multiple canonical nodes", (candidate_id,))

    historical = old_alias_for_src(observed)
    if historical:
        historical_candidates = by_path.get(historical, [])
        node = unique_node(historical_candidates)
        if node:
            return Resolution("resolved", node, observed, normalized, "src_to_old_alias", "unique canonical node matched by historical alias", (candidate_id,))
        if historical_candidates:
            return Resolution("ambiguous", None, observed, normalized, "src_to_old_alias", "historical alias maps to multiple canonical nodes", (candidate_id,))

    return Resolution("unresolved", None, observed, normalized, f"path:{method}", "no canonical node matched path", (candidate_id,))


def relation_signature(candidate: dict[str, Any], source_id: str | None, target_id: str | None) -> tuple[str | None, str | None, str | None]:
    return (source_id, target_id, candidate.get("relation_type"))


def candidate_key(candidate: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None, int | None, str | None]:
    evidence = candidate.get("evidence") or {}
    return (
        (candidate.get("source") or {}).get("repo_path"),
        (candidate.get("target") or {}).get("repo_path"),
        candidate.get("relation_type"),
        candidate.get("technical_relation_kind"),
        evidence.get("line"),
        evidence.get("raw_observation"),
    )


def classify_candidate(
    candidate: dict[str, Any],
    indexes: dict[str, Any],
    canonical_relations: set[tuple[str, str, str]],
    seen_signatures: dict[tuple[str, str, str], str],
) -> dict[str, Any]:
    cid = str(candidate.get("candidate_id") or "")
    rel_type = candidate.get("relation_type")
    source = candidate.get("source")
    target = candidate.get("target")
    if not cid or not isinstance(source, dict) or not isinstance(target, dict):
        classification = SCHEMA_INCOMPATIBLE
        source_resolution = Resolution("schema_incompatible", None, None, None, "schema", "candidate missing required source/target/candidate_id", (cid,))
        target_resolution = Resolution("schema_incompatible", None, None, None, "schema", "candidate missing required source/target/candidate_id", (cid,))
    else:
        source_resolution = resolve_endpoint(source, indexes, candidate_id=cid)
        target_resolution = resolve_endpoint(target, indexes, candidate_id=cid)
        classification = RESOLVED

        if rel_type not in ALLOWED_RELATION_TYPES:
            classification = SCHEMA_INCOMPATIBLE
        elif source_resolution.status == "missing_canonical_node" or target_resolution.status == "missing_canonical_node":
            classification = STILL_MISSING_NODE
        elif source_resolution.status == "ambiguous" or target_resolution.status == "ambiguous":
            classification = STILL_AMBIGUOUS
        elif source_resolution.status != "resolved":
            classification = STILL_UNKNOWN
        elif target_resolution.status != "resolved":
            classification = STILL_UNRESOLVED
        else:
            sig = relation_signature(candidate, source_resolution.canonical_id, target_resolution.canonical_id)
            resolved_sig = (str(sig[0]), str(sig[1]), str(sig[2]))
            if source_resolution.canonical_id == target_resolution.canonical_id:
                classification = NEEDS_MANUAL_REVIEW
            elif resolved_sig in canonical_relations:
                classification = ALREADY_REPRESENTED
            elif resolved_sig in seen_signatures:
                classification = CONFIRMED_DUPLICATE
            elif candidate.get("status") == "blocked_possible_duplicate" or candidate.get("duplicate_of"):
                classification = POSSIBLE_DUPLICATE
            else:
                classification = RESOLVED
                seen_signatures[resolved_sig] = cid

    enriched = dict(candidate)
    enriched["session_resolution"] = {
        "session": "S0162",
        "classification": classification,
        "source_resolution": resolution_payload(source_resolution),
        "target_resolution": resolution_payload(target_resolution),
        "canonical_admission_allowed": False,
        "derivation_allowed": False,
        "human_review_required": classification == RESOLVED,
        "provenance": {
            "input_session": candidate.get("session_origin"),
            "input_candidate_id": candidate.get("candidate_id"),
            "resolution_session": "S0162",
        },
    }
    if classification == RESOLVED:
        enriched["status"] = RESOLVED
        enriched["source"] = merge_endpoint(source, source_resolution)
        enriched["target"] = merge_endpoint(target, target_resolution)
        enriched.setdefault("policy", {})
        enriched["policy"]["human_review_required"] = True
        enriched["policy"]["canonical_admission_allowed"] = False
        enriched["policy"]["derivation_allowed"] = False
        enriched["policy"]["reasons"] = ["resolved deterministically by S0162; requires human review before any future admission"]
    else:
        enriched["status"] = classification
    return enriched


def merge_endpoint(endpoint: dict[str, Any], resolution: Resolution) -> dict[str, Any]:
    merged = dict(endpoint)
    if resolution.node:
        merged.update({
            "canonical_id": resolution.node.canonical_id,
            "canonical_title": resolution.node.title,
            "artifact_family": resolution.node.artifact_family,
            "authority_level": resolution.node.authority_level,
            "repo_lifecycle_state": resolution.node.repo_lifecycle_state,
            "canonical_status": resolution.node.canonical_status,
        })
    merged["observed_repo_path"] = resolution.observed_path
    merged["normalized_repo_path"] = resolution.normalized_path
    merged["resolution_method"] = resolution.method
    return merged


def resolution_payload(resolution: Resolution) -> dict[str, Any]:
    return {
        "status": resolution.status,
        "observed_path": resolution.observed_path,
        "normalized_path": resolution.normalized_path,
        "method": resolution.method,
        "reason": resolution.reason,
        "canonical_id": resolution.canonical_id,
        "canonical_title": resolution.node.title if resolution.node else None,
    }


def build_equivalence_rows(candidates: list[dict[str, Any]], indexes: dict[str, Any]) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str | None, str | None, str, str | None], dict[str, Any]] = {}
    by_path: dict[str, list[CanonNode]] = indexes["by_path"]
    for candidate in candidates:
        cid = str(candidate.get("candidate_id") or "")
        for endpoint_name in ("source", "target"):
            endpoint = candidate.get(endpoint_name) or {}
            observed = canonicalize_observed_path(endpoint.get("repo_path"))
            normalized, method = normalize_post_src(observed)
            canonical_candidates = by_path.get(normalized or "", [])
            node = unique_node(canonical_candidates)
            status = "resolved_unique" if node else ("ambiguous" if canonical_candidates else "unresolved")
            if endpoint.get("canonical_id") and str(endpoint["canonical_id"]) in indexes["by_id"]:
                node = indexes["by_id"][str(endpoint["canonical_id"])]
                status = "resolved_by_candidate_id"
            exists = bool(normalized and (REPO_ROOT / normalized).exists())
            key = (observed, normalized, endpoint_name, node.canonical_id if node else None)
            row = rows_by_key.setdefault(key, {
                "schema": SCHEMA_EQUIVALENCE,
                "session": "S0162",
                "observed_path": observed,
                "normalized_path": normalized,
                "normalization_method": method,
                "endpoint": endpoint_name,
                "normalized_path_exists_in_repo": exists,
                "resolution_status": status,
                "canonical_id": node.canonical_id if node else None,
                "canonical_title": node.title if node else None,
                "candidate_ids": [],
            })
            row["candidate_ids"].append(cid)
    for row in rows_by_key.values():
        row["candidate_ids"] = sorted(set(row["candidate_ids"]))
    return sorted(rows_by_key.values(), key=lambda r: (str(r["observed_path"]), str(r["endpoint"]), str(r["canonical_id"])))


def build_resolution_index(nodes: list[CanonNode], indexes: dict[str, Any]) -> dict[str, Any]:
    aliases = indexes["aliases_by_canonical_id"]
    path_entries = []
    for path, path_nodes in sorted(indexes["by_path"].items()):
        ids = sorted({node.canonical_id for node in path_nodes})
        path_entries.append({
            "path": path,
            "canonical_ids": ids,
            "resolution_status": "unique" if len(ids) == 1 else "ambiguous",
        })
    return {
        "schema": SCHEMA_INDEX,
        "session": "S0162",
        "generated_at": utc_now(),
        "node_count": len(nodes),
        "path_index_count": len(path_entries),
        "title_index_count": len(indexes["by_title"]),
        "key_index_count": len(indexes["by_key"]),
        "canonical_slug_index_count": len(indexes["by_slug"]),
        "nodes": [node.payload() | {"path_aliases": sorted(aliases.get(node.canonical_id, set()))} for node in nodes],
        "path_resolution_index": path_entries,
    }


def admission_gate_candidate(candidate: dict[str, Any], generated_at: str) -> dict[str, Any]:
    """Project a resolved S0162 technical candidate into the S0137 gate schema.

    This is still pre-review: it intentionally omits ``human_review`` so the
    admission gate blocks the record until an operator decision exists.
    """
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    evidence = candidate.get("evidence") or {}
    original_id = str(candidate.get("candidate_id") or "")
    seed = json.dumps(
        {
            "session": "S0162",
            "original_candidate_id": original_id,
            "source": source.get("canonical_id"),
            "target": target.get("canonical_id"),
            "relation_type": candidate.get("relation_type"),
            "raw_observation": evidence.get("raw_observation"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "candidate_id": "rc1_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32],
        "schema_version": "relations-candidate/v1",
        "status": "candidate",
        "source": {
            "tiddler_id": source.get("canonical_id"),
            "title": source.get("canonical_title"),
            "field_path": "text",
        },
        "target": {
            "tiddler_id": target.get("canonical_id"),
            "title": target.get("canonical_title"),
            "resolution_status": "resolved",
        },
        "relation": {
            "type": candidate.get("relation_type"),
            "direction": "source_to_target",
            "label": candidate.get("technical_relation_kind"),
        },
        "evidence": {
            "kind": "content_embedded",
            "excerpt": evidence.get("raw_observation") or "",
            "location": f"{evidence.get('file')}:{evidence.get('line')}",
            "strength": "E1",
        },
        "confidence": {
            "score": 0.92 if evidence.get("confidence") == "high" else 0.70,
            "method": "s0162_deterministic_resolution",
            "risk_flags": ["requires_human_review_before_admission"],
        },
        "provenance": {
            "generated_by": "src/python_scripts/repair_relation_resolution_post_src.py",
            "generated_at": generated_at,
            "source_path": "data/out/local/pipeline/relation_resolution/s0162/review_queue.jsonl",
            "source_session": candidate.get("session_origin"),
            "source_candidate_id": original_id,
            "resolution_session": "S0162",
        },
        "review": {
            "required": True,
            "review_status": "pending_operator_review",
        },
        "created_at": generated_at,
    }


def mirror_relation_candidates_s0162(out_dir: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, str]:
    mirror_dir = out_dir.parents[1] / "relation_candidates" / "s0162"
    mirror_dir.mkdir(parents=True, exist_ok=True)
    review_queue = [r for r in records if r.get("status") == RESOLVED]
    non_review_queue = [r for r in records if r.get("status") != RESOLVED]
    still_blocked = [
        r for r in records
        if (r.get("session_resolution") or {}).get("classification") not in {
            RESOLVED,
            POSSIBLE_DUPLICATE,
            CONFIRMED_DUPLICATE,
            ALREADY_REPRESENTED,
        }
    ]
    duplicates = [
        r for r in records
        if (r.get("session_resolution") or {}).get("classification") in {
            POSSIBLE_DUPLICATE,
            CONFIRMED_DUPLICATE,
            ALREADY_REPRESENTED,
        }
    ]
    paths = {
        "candidates": mirror_dir / "candidates.jsonl",
        "review_queue": mirror_dir / "review_queue.jsonl",
        "blocked": mirror_dir / "blocked_candidates.jsonl",
        "summary": mirror_dir / "candidates_summary.json",
        "generation_manifest": mirror_dir / "generation_manifest.json",
    }
    write_jsonl(paths["candidates"], records)
    write_jsonl(paths["review_queue"], review_queue)
    write_jsonl(paths["blocked"], non_review_queue)
    write_json(paths["summary"], {
        "schema": "s0162-repaired-relation-candidates-summary/v1",
        "session": "S0162",
        "source_relation_resolution_dir": repo_display(out_dir),
        "candidate_count": summary["candidate_count"],
        "review_queue_count": summary["review_queue_count"],
        "blocked_candidates_file_count": len(non_review_queue),
        "still_blocked_count": len(still_blocked),
        "duplicate_or_already_represented_count": len(duplicates),
        "classification_counts": summary["classification_counts"],
        "relations_admitted": False,
        "canon_modified": False,
        "derivatives_regenerated": False,
    })
    write_json(paths["generation_manifest"], {
        "schema": "s0162-repaired-relation-candidates-manifest/v1",
        "session": "S0162",
        "source_relation_resolution_dir": repo_display(out_dir),
        "equivalence": "relation_resolution/s0162 = evidencia de reparación; relation_candidates/s0162 = superficie candidata vigente posterior a reparación",
        "blocked_candidates_semantics": "blocked_candidates.jsonl contains every non-review-queue candidate: still blocked plus duplicates/already represented; use classification_counts for exact categories.",
        "dry_run": True,
        "relations_admitted": False,
        "canon_modified": False,
    })
    return {name: repo_display(path) for name, path in paths.items()}


def validate_outputs(paths: dict[str, Path], expected_jsonl: list[str]) -> dict[str, Any]:
    checks = []
    errors = []
    for name, path in paths.items():
        if not path.exists():
            errors.append(f"missing output: {repo_display(path)}")
            checks.append({"path": repo_display(path), "exists": False})
            continue
        check = {"path": repo_display(path), "exists": True, "sha256": sha256_file(path)}
        try:
            if name in expected_jsonl:
                count = 0
                with path.open(encoding="utf-8") as fh:
                    for line_no, raw in enumerate(fh, start=1):
                        if not raw.strip():
                            continue
                        json.loads(raw)
                        count += 1
                check["jsonl_records"] = count
            else:
                json.loads(path.read_text(encoding="utf-8"))
                check["json_valid"] = True
        except json.JSONDecodeError as exc:
            errors.append(f"{repo_display(path)}: invalid JSON at line {exc.lineno}: {exc.msg}")
            check["json_valid"] = False
        checks.append(check)
    return {"status": "ok" if not errors else "error", "errors": errors, "checks": checks}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair post-src relation resolution for S0161 candidates in dry-run mode.")
    parser.add_argument("--canon-root", type=Path, default=DEFAULT_CANON_ROOT)
    parser.add_argument("--input-candidates", type=Path, default=DEFAULT_INPUT_CANDIDATES)
    parser.add_argument("--input-blocked", type=Path, default=DEFAULT_INPUT_BLOCKED)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--dry-run", action="store_true", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = str(args.session).upper()
    if session != "S0162":
        raise SystemExit("this repair script is governed for --session S0162")

    started_at = utc_now()
    canon_before = canon_snapshot(args.canon_root)
    git_branch = run_readonly(["git", "branch", "--show-current"])
    git_head = run_readonly(["git", "rev-parse", "--short", "HEAD"])
    git_status = run_readonly(["git", "status", "--short"])

    candidates = load_jsonl(args.input_candidates)
    blocked = load_jsonl(args.input_blocked)
    blocked_ids = {record.get("candidate_id") for record in blocked}
    candidate_ids = {record.get("candidate_id") for record in candidates}
    nodes, canonical_relations = load_canon(args.canon_root)
    indexes = build_indexes(nodes)

    seen_signatures: dict[tuple[str, str, str], str] = {}
    repaired = [classify_candidate(candidate, indexes, canonical_relations, seen_signatures) for candidate in candidates]
    classification_counts = Counter(record["session_resolution"]["classification"] for record in repaired)

    resolved = [record for record in repaired if record["session_resolution"]["classification"] == RESOLVED]
    duplicates = [
        record for record in repaired
        if record["session_resolution"]["classification"] in {POSSIBLE_DUPLICATE, CONFIRMED_DUPLICATE, ALREADY_REPRESENTED}
    ]
    still_blocked = [record for record in repaired if record["session_resolution"]["classification"] not in {RESOLVED, POSSIBLE_DUPLICATE, CONFIRMED_DUPLICATE, ALREADY_REPRESENTED}]

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    output_paths = {
        "post_src_mapping_manifest": out_dir / "post_src_mapping_manifest.json",
        "path_equivalence_table": out_dir / "path_equivalence_table.jsonl",
        "canonical_resolution_index": out_dir / "canonical_resolution_index.json",
        "resolved_candidates": out_dir / "resolved_candidates.jsonl",
        "review_queue": out_dir / "review_queue.jsonl",
        "still_blocked_candidates": out_dir / "still_blocked_candidates.jsonl",
        "possible_duplicates": out_dir / "possible_duplicates.jsonl",
        "admission_gate_candidates": out_dir / "admission_gate_candidates.jsonl",
        "resolution_summary": out_dir / "resolution_summary.json",
        "validation_report": out_dir / "validation_report.json",
        "operator_review_manifest": out_dir / "operator_review_manifest.json",
    }

    equivalence_rows = build_equivalence_rows(candidates, indexes)
    write_jsonl(output_paths["path_equivalence_table"], equivalence_rows)
    write_json(output_paths["canonical_resolution_index"], build_resolution_index(nodes, indexes))
    write_jsonl(output_paths["resolved_candidates"], resolved)
    write_jsonl(output_paths["review_queue"], resolved)
    write_jsonl(output_paths["still_blocked_candidates"], still_blocked)
    write_jsonl(output_paths["possible_duplicates"], duplicates)
    write_jsonl(
        output_paths["admission_gate_candidates"],
        [admission_gate_candidate(record, started_at) for record in resolved],
    )

    summary = {
        "schema": SCHEMA_SUMMARY,
        "session": "S0162",
        "run_id": args.run_id,
        "generated_at": utc_now(),
        "candidate_count": len(candidates),
        "s0161_blocked_input_count": len(blocked),
        "s0161_blocked_ids_all_present": blocked_ids.issubset(candidate_ids),
        "review_queue_count": len(resolved),
        "resolved_count": len(resolved),
        "still_blocked_count": len(still_blocked),
        "possible_duplicate_count": classification_counts.get(POSSIBLE_DUPLICATE, 0),
        "confirmed_duplicate_count": classification_counts.get(CONFIRMED_DUPLICATE, 0),
        "already_represented_count": classification_counts.get(ALREADY_REPRESENTED, 0),
        "classification_counts": {key: classification_counts.get(key, 0) for key in sorted(CLASSIFICATIONS)},
        "relation_type_counts": dict(sorted(Counter(record.get("relation_type") for record in repaired).items())),
        "technical_relation_kind_counts": dict(sorted(Counter(record.get("technical_relation_kind") for record in repaired).items())),
        "relations_admitted": False,
        "canon_modified": False,
        "derivatives_regenerated": False,
        "reverse_authoritative_run": False,
        "dry_run": True,
        "output_paths": {name: repo_display(path) for name, path in output_paths.items()},
    }
    write_json(output_paths["resolution_summary"], summary)

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "session": "S0162",
        "run_id": args.run_id,
        "generated_at": started_at,
        "branch": git_branch["stdout"],
        "head": git_head["stdout"],
        "git_status_initial": git_status["stdout"].splitlines(),
        **canon_before,
        "s0161_input_paths": {
            "candidates": repo_display(args.input_candidates),
            "blocked": repo_display(args.input_blocked),
        },
        "mapping_rules": [
            {"old_prefix": old, "new_prefix": new}
            for old, new in POST_SRC_PREFIXES
        ],
        "formal_model": {
            "C": "current canonical nodes loaded from data/out/local/tiddlers_*.jsonl",
            "P": "observable paths in S0161 source/target endpoints and canon source_fields",
            "P_old": "historical pre-src path prefixes go/, python_scripts/, rust/, shell_scripts/",
            "P_new": "current src/ path prefixes src/go/, src/python_scripts/, src/rust/, src/shell_scripts/",
            "mu_base": "P_old -> P_new prefix mapping, only deterministic prefix rewrites",
            "E_path": "audited path equivalence index over P_old union P_new; includes src_to_old_alias only for lookup against historical canon paths",
            "kappa": "E_path/path alias -> unique current canonical node",
            "rho": "S0161 candidates x E_path x kappa -> review queue, blocked, duplicate",
        },
        "resolution_algorithm": [
            "verify candidate canonical_id against current canon when present",
            "normalize observed repo_path with post-src prefix mapping",
            "resolve normalized path against canonical path index including audited old/src aliases",
            "keep ambiguous or missing mappings blocked",
            "keep self-relations out of the admission review queue as needs_manual_review",
            "classify canonical relation matches and repeated signatures as duplicates",
            "send only unique source and target resolutions with allowed candidate relation types to review_queue",
        ],
        "data_tmp_usage": {
            "used": False,
            "used_as_decisory_source": False,
        },
        "relations_admitted": False,
        "canon_modified": False,
        "derivatives_regenerated": False,
        "reverse_authoritative_run": False,
    }
    write_json(output_paths["post_src_mapping_manifest"], manifest)

    mirror_paths = mirror_relation_candidates_s0162(out_dir, repaired, summary)
    operator_manifest = {
        "schema": SCHEMA_OPERATOR_REVIEW,
        "session": "S0162",
        "run_id": args.run_id,
        "generated_at": utc_now(),
        "operator_required": True,
        "next_session_candidate": "S0164" if len(resolved) > 0 else None,
        "review_queue_path": repo_display(output_paths["review_queue"]),
        "review_queue_count": len(resolved),
        "blocking_summary": summary["classification_counts"],
        "commands": [
            "cat data/out/local/pipeline/relation_resolution/s0162/resolution_summary.json",
            "cat data/out/local/pipeline/relation_resolution/s0162/post_src_mapping_manifest.json",
            "less data/out/local/pipeline/relation_resolution/s0162/review_queue.jsonl",
            "less data/out/local/pipeline/relation_resolution/s0162/admission_gate_candidates.jsonl",
            "less data/out/local/pipeline/relation_resolution/s0162/still_blocked_candidates.jsonl",
            "less data/out/local/pipeline/relation_resolution/s0162/possible_duplicates.jsonl",
            "cat data/out/local/pipeline/relation_resolution/s0162/admission_gate_validation_projection_clean/s0162_relation_admission_dry_run_report.json",
        ],
        "admission_gate_candidate_path": repo_display(output_paths["admission_gate_candidates"]),
        "admission_gate_validation_expected_path": "data/out/local/pipeline/relation_resolution/s0162/admission_gate_validation_projection_clean/s0162_relation_admission_dry_run_report.json",
        "relation_candidates_s0162_mirror": mirror_paths,
        "admission_allowed_in_s0162": False,
    }
    write_json(output_paths["operator_review_manifest"], operator_manifest)

    validation_output_paths = {
        name: path for name, path in output_paths.items()
        if name != "validation_report"
    }
    validation = validate_outputs(
        validation_output_paths,
        [
            "path_equivalence_table",
            "resolved_candidates",
            "review_queue",
            "still_blocked_candidates",
            "possible_duplicates",
            "admission_gate_candidates",
        ],
    )
    canon_after = canon_snapshot(args.canon_root)
    validation.update({
        "schema": SCHEMA_VALIDATION,
        "session": "S0162",
        "run_id": args.run_id,
        "generated_at": utc_now(),
        "canon_before_sha256": canon_before["canon_input_sha256"],
        "canon_after_sha256": canon_after["canon_input_sha256"],
        "canon_modified": canon_before["canon_input_sha256"] != canon_after["canon_input_sha256"],
        "derivatives_regenerated": False,
        "relations_admitted": False,
        "all_candidates_classified": sum(classification_counts.values()) == len(candidates),
        "known_classifications_only": set(classification_counts).issubset(CLASSIFICATIONS),
    })
    validation["status"] = "ok" if validation["status"] == "ok" and not validation["canon_modified"] and validation["all_candidates_classified"] and validation["known_classifications_only"] else "error"
    write_json(output_paths["validation_report"], validation)

    print(json.dumps({
        "session": "S0162",
        "run_id": args.run_id,
        "candidate_count": len(candidates),
        "review_queue_count": len(resolved),
        "still_blocked_count": len(still_blocked),
        "possible_duplicate_count": len(duplicates),
        "out_dir": repo_display(out_dir),
        "dry_run": True,
        "canon_modified": validation["canon_modified"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if validation["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
