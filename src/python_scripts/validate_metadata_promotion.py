#!/usr/bin/env python3
"""Validate S0171 metadata candidates and RAG-filter previews without apply."""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from build_metadata_promotion_candidates import canon_snapshot
from build_rag_filter_preview import read_jsonl
from metadata_promotion_policy import DEFAULT_POLICY_PATH, FORMAL_RELATION_VOCAB, load_policy
from tag_sanitation_policy import stable_json


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_PROMOTION_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "metadata_promotion" / "s0171"
DEFAULT_FILTER_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_filters" / "s0171"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "audit" / "metadata_promotion" / "s0171"


def _read_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _snapshot_equal(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before_map = {item["path"]: item["sha256"] for item in before.get("files", [])}
    after_map = {item["path"]: item["sha256"] for item in after.get("files", [])}
    return before_map == after_map


def validate_candidates(
    candidates: list[dict[str, Any]],
    *,
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ids = Counter(str(row.get("candidate_id") or "") for row in candidates)
    allowed_fields = set(policy.get("allowed_fields") or [])
    required = {
        "schema_version",
        "candidate_id",
        "tiddler_id",
        "title",
        "source_tag",
        "source_tag_classification",
        "target_field",
        "promotion_status",
        "authority_level",
        "requires_human_review",
        "source_policy",
        "promotion_policy",
    }
    for row in candidates:
        candidate_id = row.get("candidate_id")
        missing = sorted(required - set(row))
        if missing:
            findings.append({"candidate_id": candidate_id, "code": "missing_required_fields", "fields": missing})
        if ids[str(candidate_id)] > 1:
            findings.append({"candidate_id": candidate_id, "code": "duplicate_candidate_id"})
        if row.get("schema_version") != "metadata-promotion-candidate/v1":
            findings.append({"candidate_id": candidate_id, "code": "invalid_schema_version"})
        if row.get("target_field") not in allowed_fields:
            findings.append({"candidate_id": candidate_id, "code": "target_field_not_allowed"})
        if row.get("authority_level") != "proposed":
            findings.append({"candidate_id": candidate_id, "code": "authority_not_proposed"})
        if row.get("promotion_status") not in {"candidate", "blocked"}:
            findings.append({"candidate_id": candidate_id, "code": "invalid_promotion_status"})
        if row.get("canon_modified") is not False or row.get("dry_run") is not True:
            findings.append({"candidate_id": candidate_id, "code": "dry_run_invariant_failed"})
        if any(key in row for key in ("relations", "edges", "canonical_relation", "relation_candidates")):
            findings.append({"candidate_id": candidate_id, "code": "relation_emission_forbidden"})
        if row.get("target_field") == "tech_stack":
            value = str(row.get("proposed_value") or "")
            if "/" in value or "\\" in value or "." in value:
                findings.append({"candidate_id": candidate_id, "code": "path_like_tech_stack"})
        secondary = row.get("secondary_fields") or {}
        if set(secondary) - allowed_fields:
            findings.append(
                {
                    "candidate_id": candidate_id,
                    "code": "secondary_field_not_allowed",
                    "fields": sorted(set(secondary) - allowed_fields),
                }
            )
        vocab = secondary.get("formal_relation_vocab")
        if vocab is not None and vocab != list(FORMAL_RELATION_VOCAB):
            findings.append({"candidate_id": candidate_id, "code": "formal_relation_vocab_mismatch"})
    metrics = {
        "candidate_lines": len(candidates),
        "safe_candidates": sum(row.get("promotion_status") == "candidate" for row in candidates),
        "blocked_candidates": sum(row.get("promotion_status") == "blocked" for row in candidates),
        "requires_human_review": sum(bool(row.get("requires_human_review")) for row in candidates),
        "unique_candidate_ids": len(ids),
        "formal_relation_edges_emitted": sum(
            any(key in row for key in ("relations", "edges", "canonical_relation", "relation_candidates"))
            for row in candidates
        ),
    }
    return findings, metrics


def normalization_collisions(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        if row.get("promotion_status") != "candidate":
            continue
        key = (
            str(row.get("tiddler_id")),
            str(row.get("target_field")),
            stable_json(row.get("proposed_value")),
        )
        groups[key].append(row)
    collisions = []
    for (tiddler_id, field, proposed), rows in sorted(groups.items()):
        source_values = sorted({str(row.get("source_tag")) for row in rows})
        if len(source_values) > 1:
            collisions.append(
                {
                    "tiddler_id": tiddler_id,
                    "target_field": field,
                    "proposed_value": json.loads(proposed),
                    "source_values": source_values,
                    "candidate_ids": sorted(str(row.get("candidate_id")) for row in rows),
                }
            )
    return collisions


def validate_preview(
    preview: list[dict[str, Any]],
    *,
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []
    allowed = set(policy.get("allowed_fields") or [])
    fields = Counter()
    for row in preview:
        filters = row.get("rag_filters")
        if not isinstance(filters, dict) or not filters:
            findings.append({"tiddler_id": row.get("tiddler_id"), "code": "missing_rag_filters"})
            continue
        fields.update(filters.keys())
        extra = set(filters) - allowed
        if extra:
            findings.append(
                {"tiddler_id": row.get("tiddler_id"), "code": "rag_filter_field_not_allowed", "fields": sorted(extra)}
            )
        node = filters.get("template_node")
        topics = filters.get("topics") or []
        if node and node in topics:
            collision = {
                "tiddler_id": row.get("tiddler_id"),
                "title": row.get("title"),
                "template_node": node,
                "block_reason": "template_node_topic_collision",
            }
            collisions.append(collision)
            findings.append({**collision, "code": "template_node_as_topic"})
        serialized = stable_json(
            {
                "retrieval_hints": row.get("retrieval_hints"),
                "embedding_metadata": row.get("embedding_metadata"),
            }
        )
        for marker in ("source_tags", "metadata_only_tags", "projectable_tags"):
            if marker in serialized:
                findings.append({"tiddler_id": row.get("tiddler_id"), "code": "raw_tag_channel_present", "marker": marker})
    metrics = {
        "rag_filters_generated": len(preview),
        "promoted_metadata_fields_present": bool(fields),
        "promoted_metadata_field_count": len(fields),
        "field_distribution": dict(sorted(fields.items())),
        "template_nodes_as_topics": len(collisions),
    }
    return findings, metrics, collisions


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate S0171 metadata promotion and RAG preview.")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--candidates", default=str(DEFAULT_PROMOTION_DIR / "metadata_promotion_candidates.jsonl"))
    parser.add_argument("--summary", default=str(DEFAULT_PROMOTION_DIR / "metadata_promotion_summary.json"))
    parser.add_argument("--rag-filter-preview", default=str(DEFAULT_FILTER_DIR / "rag_filter_preview.jsonl"))
    parser.add_argument("--rag-gate-report")
    parser.add_argument("--canon-glob", default=str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"))
    parser.add_argument("--canon-dir", help="Canon dir; converted to <dir>/tiddlers_*.jsonl.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--run-id", default="s0171-metadata-promotion-validation")
    args = parser.parse_args()

    policy = load_policy(args.policy)
    candidates = read_jsonl(args.candidates)
    preview = read_jsonl(args.rag_filter_preview)
    candidate_findings, candidate_metrics = validate_candidates(candidates, policy=policy)
    preview_findings, preview_metrics, template_collisions = validate_preview(preview, policy=policy)
    findings = candidate_findings + preview_findings
    blocked = [row for row in candidates if row.get("promotion_status") == "blocked"]
    ambiguous = [
        {
            "candidate_id": row.get("candidate_id"),
            "tiddler_id": row.get("tiddler_id"),
            "title": row.get("title"),
            "source_tag": row.get("source_tag"),
            "target_field": row.get("target_field"),
            "block_reason": row.get("block_reason"),
        }
        for row in blocked
    ]

    canon_glob = str(Path(args.canon_dir) / "tiddlers_*.jsonl") if args.canon_dir else args.canon_glob
    summary = _read_json(args.summary)
    before = summary.get("canon_snapshot_before") or {}
    after = canon_snapshot(canon_glob)
    canon_unchanged = _snapshot_equal(before, after)
    canon_diff = {
        "schema": "canon-diff-report/v1",
        "session": "S0171",
        "comparison": "sha256_by_canon_shard",
        "canon_modified": not canon_unchanged,
        "before": before,
        "after": after,
    }
    if not canon_unchanged:
        findings.append({"code": "canon_modified"})

    gate = _read_json(args.rag_gate_report) if args.rag_gate_report else {}
    if gate and gate.get("status") != "pass":
        findings.append({"code": "rag_gate_not_pass", "status": gate.get("status")})
    validation = {
        "schema": "metadata-promotion-validation/v1",
        "session": "S0171",
        "run_id": args.run_id,
        "policy_version": policy.get("policy_version"),
        "status": "pass" if not findings else "blocked",
        "dry_run": True,
        "canon_modified": not canon_unchanged,
        "productive_derivatives_modified": False,
        "candidate_metrics": candidate_metrics,
        "preview_metrics": preview_metrics,
        "rag_gate": {
            key: gate.get(key)
            for key in (
                "status",
                "p0_tags_in_semantic_text",
                "p0_tags_in_retrieval_hints",
                "p0_tags_in_embedding_metadata",
                "unknown_tags_in_semantic_text",
                "unknown_tags_in_retrieval_hints",
                "unknown_tags_in_embedding_metadata",
                "p1_raw_tags_in_semantic_text",
                "p1_raw_tags_in_retrieval_hints",
                "p1_raw_tags_in_embedding_metadata",
            )
            if key in gate
        },
        "formal_relation_vocab_is_metadata_only": candidate_metrics["formal_relation_edges_emitted"] == 0,
        "findings": findings,
    }
    collisions = normalization_collisions(candidates)
    out_dir = Path(args.out_dir)
    paths = {
        "validation": _write_json(out_dir / "validation_report.json", validation),
        "collisions": _write_json(
            out_dir / "normalization_collisions.json",
            {"schema": "normalization-collisions/v1", "count": len(collisions), "items": collisions},
        ),
        "ambiguous": _write_json(
            out_dir / "ambiguous_values_report.json",
            {"schema": "ambiguous-values-report/v1", "count": len(ambiguous), "items": ambiguous},
        ),
        "template_collisions": _write_json(
            out_dir / "template_node_topic_collision_report.json",
            {"schema": "template-node-topic-collision-report/v1", "count": len(template_collisions), "items": template_collisions},
        ),
        "canon_diff": _write_json(out_dir / "canon_diff_report.json", canon_diff),
    }
    print(stable_json({"validation": validation, "paths": {key: str(path) for key, path in paths.items()}}, indent=2))
    return 0 if validation["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
