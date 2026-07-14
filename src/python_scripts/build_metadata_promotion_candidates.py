#!/usr/bin/env python3
"""Build S0171 metadata promotion candidates and reports in dry-run mode."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from audit_tags_inventory import DEFAULT_CANON_GLOB, read_canon_records, source_tags_for_record
from metadata_promotion_policy import (
    DEFAULT_POLICY_PATH,
    FORMAL_RELATION_VOCAB,
    MULTI_VALUE_FIELDS,
    POLICY_VERSION,
    classify_promotion,
    load_policy as load_promotion_policy,
)
from tag_sanitation_policy import (
    DEFAULT_POLICY_PATH as DEFAULT_TAG_POLICY_PATH,
    classify_tag_for_rag,
    load_policy as load_tag_policy,
    stable_json,
)
from template_set_classifier import classify_template_record, template_mapping_report


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "metadata_promotion" / "s0171"


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canon_snapshot(canon_glob: str) -> dict[str, Any]:
    files = []
    total_lines = 0
    for raw_path in sorted(glob.glob(canon_glob)):
        path = Path(raw_path)
        line_count = sum(1 for line in path.open(encoding="utf-8") if line.strip())
        total_lines += line_count
        files.append({"path": str(path), "sha256": _sha256_bytes(path), "line_count": line_count})
    return {"shard_count": len(files), "line_count": total_lines, "files": files}


def _stable_candidate_id(seed: dict[str, Any]) -> str:
    digest = hashlib.sha256(stable_json(seed).encode("utf-8")).hexdigest()[:24]
    return f"s0171:{digest}"


def _candidate_common(
    record: dict[str, Any],
    *,
    source_value: str,
    source_kind: str,
    target_field: str | None,
    proposed_value: Any,
) -> dict[str, Any]:
    seed = {
        "policy_version": POLICY_VERSION,
        "tiddler_id": record.get("id"),
        "source_kind": source_kind,
        "source_value": source_value,
        "target_field": target_field,
        "proposed_value": proposed_value,
    }
    return {
        "schema_version": "metadata-promotion-candidate/v1",
        "candidate_id": _stable_candidate_id(seed),
        "tiddler_id": record.get("id"),
        "title": record.get("title") or record.get("key"),
        "source_tag": source_value,
        "source_kind": source_kind,
        "target_field": target_field,
        "proposed_value": proposed_value,
        "source_policy": "tag-sanitation/v1",
        "promotion_policy": POLICY_VERSION,
        "dry_run": True,
        "canon_modified": False,
    }


def _tag_candidate(
    record: dict[str, Any],
    tag: str,
    *,
    tag_policy: dict[str, Any],
    promotion_policy: dict[str, Any],
) -> dict[str, Any] | None:
    upstream = classify_tag_for_rag(tag, tag_policy)
    decision = classify_promotion(
        tag,
        upstream_rag_class=upstream["rag_class"],
        policy=promotion_policy,
    )
    if decision is None:
        return None
    candidate = _candidate_common(
        record,
        source_value=tag,
        source_kind="canonical_tags_projection",
        target_field=decision.get("target_field"),
        proposed_value=decision.get("proposed_value"),
    )
    candidate.update(decision)
    candidate["upstream_source_tag_classification"] = upstream["rag_class"]
    candidate.setdefault("source_tag_classification", upstream["rag_class"])
    return candidate


def _template_candidate(record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    title = str(record.get("title") or record.get("key") or "")
    secondary = {
        key: metadata[key]
        for key in ("template_node", "structural_role", "governance_axis", "formal_relation_vocab")
        if key in metadata
    }
    candidate = _candidate_common(
        record,
        source_value=title,
        source_kind="canonical_title_template_catalog",
        target_field="template_set",
        proposed_value=metadata["template_set"],
    )
    candidate.update(
        {
            "source_tag_classification": "p2_human_navigation",
            "upstream_source_tag_classification": "canonical_title",
            "secondary_fields": secondary,
            "normalization_applied": True,
            "confidence": "high",
            "promotion_status": "candidate",
            "authority_level": "proposed",
            "requires_human_review": False,
            "promotion_basis": "exact_template_title_catalog",
            "reason": (
                f"Known base tiddler maps to {metadata['template_set']} under "
                "T=R∪A∪C∪N∪D∪Q"
            ),
        }
    )
    return candidate


def _apply_conflict_rules(candidates: list[dict[str, Any]]) -> None:
    by_scalar: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        if candidate.get("promotion_status") != "candidate":
            continue
        field = candidate.get("target_field")
        if field and field not in MULTI_VALUE_FIELDS:
            by_scalar[(str(candidate.get("tiddler_id")), str(field))].append(candidate)
    for rows in by_scalar.values():
        values = {stable_json(row.get("proposed_value")) for row in rows}
        if len(values) <= 1:
            continue
        for row in rows:
            row.update(
                {
                    "promotion_status": "blocked",
                    "requires_human_review": True,
                    "confidence": "low",
                    "block_reason": "multiple_conflicting_values",
                    "reason": "Multiple distinct scalar values require human review",
                }
            )


def _apply_template_topic_collision_rules(candidates: list[dict[str, Any]]) -> None:
    template_nodes: dict[str, str] = {}
    for candidate in candidates:
        if candidate.get("target_field") == "template_set":
            node = (candidate.get("secondary_fields") or {}).get("template_node")
            if node:
                template_nodes[str(candidate.get("tiddler_id"))] = str(node)
    for candidate in candidates:
        node = template_nodes.get(str(candidate.get("tiddler_id")))
        if not node or candidate.get("target_field") != "topics":
            continue
        if candidate.get("proposed_value") != node:
            continue
        candidate.update(
            {
                "promotion_status": "blocked",
                "requires_human_review": True,
                "confidence": "low",
                "block_reason": "template_node_topic_collision",
                "reason": "A base template node cannot become the same topic automatically",
            }
        )


def build_candidates(
    records: list[dict[str, Any]],
    *,
    tag_policy: dict[str, Any],
    promotion_policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    observations = Counter()
    p1_unique: set[str] = set()
    override_unique: set[str] = set()
    skipped_classes = Counter()

    for record in records:
        for tag in source_tags_for_record(record):
            upstream = classify_tag_for_rag(tag, tag_policy)["rag_class"]
            observations[f"source_{upstream}"] += 1
            if upstream == "p1_metadata_only":
                observations["p1_tags_seen"] += 1
                p1_unique.add(tag)
            candidate = _tag_candidate(
                record,
                tag,
                tag_policy=tag_policy,
                promotion_policy=promotion_policy,
            )
            if candidate is None:
                skipped_classes[upstream] += 1
                continue
            if candidate.get("promotion_basis") == "policy_curated_exact_mapping":
                observations["curated_exact_override_occurrences"] += 1
                override_unique.add(tag)
            candidates.append(candidate)

        template_metadata = classify_template_record(record)
        if template_metadata:
            candidates.append(_template_candidate(record, template_metadata))
            observations["template_records_seen"] += 1

    _apply_conflict_rules(candidates)
    _apply_template_topic_collision_rules(candidates)
    candidates.sort(key=lambda row: row["candidate_id"])
    return candidates, {
        **dict(observations),
        "p1_unique_tags_seen": len(p1_unique),
        "curated_exact_override_unique": len(override_unique),
        "skipped_source_occurrences_by_class": dict(sorted(skipped_classes.items())),
    }


def _field_distribution(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter()
    for candidate in candidates:
        if candidate.get("promotion_status") != "candidate":
            continue
        if candidate.get("target_field"):
            counts[str(candidate["target_field"])] += 1
        for field in (candidate.get("secondary_fields") or {}):
            counts[field] += 1
    return {
        "schema": "metadata-promotion-field-distribution/v1",
        "session": "S0171",
        "candidate_field_occurrences": dict(sorted(counts.items())),
        "fields_generated": len(counts),
    }


def _template_reports(records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    coverage = template_mapping_report(records)
    coverage.pop("unclassified_titles", None)
    node_rows = []
    for row in coverage["classifications"]:
        metadata = row["metadata"]
        node_rows.append(
            {
                "title": row["title"],
                "template_set": metadata["template_set"],
                "template_node": metadata["template_node"],
                "structural_role": metadata["structural_role"],
                "governance_axis": metadata.get("governance_axis", []),
            }
        )
    node_rows.sort(key=lambda row: (row["template_set"], row["template_node"], row["title"]))
    node_report = {
        "schema": "template-node-mapping-report/v1",
        "session": "S0171",
        "mapping_count": len(node_rows),
        "mappings": node_rows,
        "template_nodes_as_topics": 0,
    }
    relation_report = {
        "schema": "template-relation-vocab-report/v1",
        "session": "S0171",
        "formal_relation_vocab": list(FORMAL_RELATION_VOCAB),
        "handling": "formal_relation_reference_only",
        "canonical_relation_schema_emitted": False,
        "relation_candidates_emitted": False,
        "formal_relation_edges_emitted": 0,
    }
    return coverage, node_report, relation_report


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(stable_json(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _summary_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# S0171 metadata promotion summary",
            "",
            f"- policy_version: {summary['policy_version']}",
            f"- dry_run: {str(summary['dry_run']).lower()}",
            f"- p1_tags_seen: {summary['p1_tags_seen']}",
            f"- promotion_candidates: {summary['promotion_candidates']}",
            f"- promotion_blocked: {summary['promotion_blocked']}",
            f"- requires_human_review: {summary['requires_human_review']}",
            f"- template_set_candidates: {summary['template_set_candidates']}",
            f"- formal_relation_edges_emitted: {summary['formal_relation_edges_emitted']}",
            f"- canon_modified: {str(summary['canon_modified']).lower()}",
            f"- productive_derivatives_modified: {str(summary['productive_derivatives_modified']).lower()}",
            "",
            "The curated tech-stack override is exact-match only and preserves the upstream S0169 unknown_review classification as disclosure.",
            "",
        ]
    )


def write_outputs(
    *,
    out_dir: Path,
    candidates: list[dict[str, Any]],
    observations: dict[str, Any],
    records: list[dict[str, Any]],
    canon_state: dict[str, Any],
    promotion_policy_path: str,
    run_id: str,
) -> dict[str, Any]:
    blocked = [row for row in candidates if row.get("promotion_status") == "blocked"]
    review = [row for row in candidates if row.get("requires_human_review")]
    safe = [row for row in candidates if row.get("promotion_status") == "candidate"]
    distribution = _field_distribution(candidates)
    template_report, node_report, relation_report = _template_reports(records)
    summary = {
        "schema": "metadata-promotion-summary/v1",
        "session": "S0171",
        "run_id": run_id,
        "policy_version": POLICY_VERSION,
        "promotion_policy_path": promotion_policy_path,
        "dry_run": True,
        "canon_modified": False,
        "productive_derivatives_modified": False,
        "total_tiddlers": len(records),
        **observations,
        "promotion_candidates": len(safe),
        "promotion_blocked": len(blocked),
        "requires_human_review": len(review),
        "candidate_records": len({row.get("tiddler_id") for row in safe}),
        "fields_generated": distribution["fields_generated"],
        "template_set_candidates": sum(
            1 for row in safe if row.get("target_field") == "template_set"
        ),
        "template_node_topic_collisions": sum(
            1 for row in blocked if row.get("block_reason") == "template_node_topic_collision"
        ),
        "formal_relation_edges_emitted": 0,
        "canon_snapshot_before": canon_state,
    }
    paths = {
        "candidates": _write_jsonl(out_dir / "metadata_promotion_candidates.jsonl", candidates),
        "blocked": _write_jsonl(out_dir / "metadata_promotion_blocked.jsonl", blocked),
        "review": _write_jsonl(out_dir / "metadata_promotion_requires_review.jsonl", review),
        "summary": _write_json(out_dir / "metadata_promotion_summary.json", summary),
        "distribution": _write_json(out_dir / "metadata_promotion_field_distribution.json", distribution),
        "template_set": _write_json(out_dir / "template_set_classification_report.json", template_report),
        "template_nodes": _write_json(out_dir / "template_node_mapping_report.json", node_report),
        "relation_vocab": _write_json(out_dir / "template_relation_vocab_report.json", relation_report),
    }
    (out_dir / "metadata_promotion_summary.md").write_text(
        _summary_markdown(summary), encoding="utf-8"
    )
    return {"summary": summary, "paths": {key: str(path) for key, path in paths.items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build S0171 metadata promotion candidates (dry-run only).")
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--canon-dir", help="Canon dir; converted to <dir>/tiddlers_*.jsonl.")
    parser.add_argument("--tag-policy", default=str(DEFAULT_TAG_POLICY_PATH))
    parser.add_argument("--promotion-policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--run-id", default="s0171-metadata-promotion")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()
    if not args.dry_run:
        raise SystemExit("S0171 metadata promotion is always dry-run")

    canon_glob = str(Path(args.canon_dir) / "tiddlers_*.jsonl") if args.canon_dir else args.canon_glob
    tag_policy = load_tag_policy(args.tag_policy)
    promotion_policy = load_promotion_policy(args.promotion_policy)
    records = read_canon_records(canon_glob)
    candidates, observations = build_candidates(
        records,
        tag_policy=tag_policy,
        promotion_policy=promotion_policy,
    )
    result = write_outputs(
        out_dir=Path(args.out_dir),
        candidates=candidates,
        observations=observations,
        records=records,
        canon_state=canon_snapshot(canon_glob),
        promotion_policy_path=args.promotion_policy,
        run_id=args.run_id,
    )
    print(stable_json(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
