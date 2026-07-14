#!/usr/bin/env python3
"""Build an isolated RAG-filter preview from proposed S0171 metadata."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from audit_tags_inventory import DEFAULT_CANON_GLOB, read_canon_records, source_tags_for_record
from metadata_promotion_policy import DEFAULT_POLICY_PATH, MULTI_VALUE_FIELDS, load_policy
from tag_sanitation_policy import (
    DEFAULT_POLICY_PATH as DEFAULT_TAG_POLICY_PATH,
    filter_tags_for_rag,
    load_policy as load_tag_policy,
    stable_json,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_CANDIDATES = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "metadata_promotion"
    / "s0171"
    / "metadata_promotion_candidates.jsonl"
)
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_filters" / "s0171"


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"candidate line {line_no} must be an object: {path}")
            rows.append(value)
    return rows


def build_promoted_metadata_index(
    candidates: list[dict[str, Any]],
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Aggregate safe proposed candidates into normalized metadata by tiddler."""

    allowed_fields = allowed_fields or set(load_policy()["allowed_fields"])
    raw: dict[str, dict[str, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for candidate in candidates:
        if (
            candidate.get("promotion_status") != "candidate"
            or candidate.get("authority_level") != "proposed"
            or candidate.get("requires_human_review")
        ):
            continue
        tiddler_id = str(candidate.get("tiddler_id") or "")
        field = candidate.get("target_field")
        if not tiddler_id or field not in allowed_fields:
            continue
        raw[tiddler_id][str(field)].append(candidate.get("proposed_value"))
        for secondary_field, secondary_value in (candidate.get("secondary_fields") or {}).items():
            if secondary_field in allowed_fields:
                raw[tiddler_id][secondary_field].append(secondary_value)

    result: dict[str, dict[str, Any]] = {}
    for tiddler_id, fields in raw.items():
        metadata: dict[str, Any] = {}
        for field, values in sorted(fields.items()):
            flattened: list[Any] = []
            for value in values:
                if isinstance(value, list):
                    flattened.extend(value)
                elif value is not None:
                    flattened.append(value)
            deduped: list[Any] = []
            seen: set[str] = set()
            for value in flattened:
                key = stable_json(value)
                if key not in seen:
                    seen.add(key)
                    deduped.append(value)
            deduped.sort(key=lambda item: stable_json(item))
            if field in MULTI_VALUE_FIELDS:
                metadata[field] = deduped
            elif deduped:
                metadata[field] = deduped[0]
        if metadata:
            result[tiddler_id] = metadata
    return result


def _retrieval_hints(metadata: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    hint_fields = (
        "topics",
        "tech_stack",
        "language",
        "artifact_family",
        "status",
        "session_id",
        "milestones",
        "layer",
        "module",
        "source_kind",
        "workflow_stage",
        "template_set",
        "template_node",
        "structural_role",
        "governance_axis",
    )
    label_alias = {"topics": "topic", "milestones": "milestone"}
    for field in hint_fields:
        value = metadata.get(field)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item is not None and str(item).strip():
                hints.append(f"{label_alias.get(field, field)}: {item}")
    return sorted(set(hints), key=lambda item: item.casefold())


def build_preview_records(
    canon_records: list[dict[str, Any]],
    *,
    promoted_metadata: dict[str, dict[str, Any]],
    tag_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for record in canon_records:
        tiddler_id = str(record.get("id") or "")
        metadata = promoted_metadata.get(tiddler_id)
        if not metadata:
            continue
        filtered = filter_tags_for_rag(source_tags_for_record(record), tag_policy)
        preview.append(
            {
                "schema": "rag-filter-preview/v1",
                "tiddler_id": tiddler_id,
                "title": record.get("title") or record.get("key"),
                "rag_filters": metadata,
                "retrieval_hints": _retrieval_hints(metadata),
                "embedding_metadata": {
                    "promoted_metadata": metadata,
                    "source_tag_projection_mode": "normalized_promoted_metadata_only",
                },
                "blocked_tags_count": len(filtered["blocked_tags"]),
                "metadata_only_source_tags_count": len(filtered["metadata_only_tags"]),
                "human_navigation_tags_count": len(filtered["human_navigation_tags"]),
                "unknown_tags_count": len(filtered["unknown_tags"]),
                "dry_run": True,
                "canon_modified": False,
                "productive_derivatives_modified": False,
            }
        )
    preview.sort(key=lambda row: (str(row["tiddler_id"]), str(row["title"])))
    return preview


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(stable_json(row) + "\n" for row in rows), encoding="utf-8")
    return path


def write_preview_outputs(
    *,
    out_dir: Path,
    records: list[dict[str, Any]],
    candidates_path: str,
    promotion_policy_path: str,
    run_id: str,
) -> dict[str, Any]:
    field_counts = Counter(
        field
        for record in records
        for field in (record.get("rag_filters") or {})
    )
    template_collisions = []
    for record in records:
        filters = record.get("rag_filters") or {}
        node = filters.get("template_node")
        topics = filters.get("topics") or []
        if node and node in topics:
            template_collisions.append(
                {"tiddler_id": record["tiddler_id"], "title": record["title"], "template_node": node}
            )
    summary = {
        "schema": "rag-filter-preview-summary/v1",
        "session": "S0171",
        "run_id": run_id,
        "dry_run": True,
        "canon_modified": False,
        "productive_derivatives_modified": False,
        "rag_filters_generated": len(records),
        "records_with_retrieval_hints": sum(bool(row["retrieval_hints"]) for row in records),
        "promoted_metadata_fields_present": bool(field_counts),
        "field_distribution": dict(sorted(field_counts.items())),
        "template_nodes_as_topics": len(template_collisions),
        "formal_relation_edges_emitted": 0,
    }
    policy_report = {
        "schema": "rag-filter-policy-report/v1",
        "session": "S0171",
        "run_id": run_id,
        "promotion_policy": promotion_policy_path,
        "metadata_candidates": candidates_path,
        "source_tags_raw_in_retrieval_hints": False,
        "source_tags_raw_in_embedding_metadata": False,
        "unknown_source_tags_projected": False,
        "p0_source_tags_projected": False,
        "template_node_topic_collisions": template_collisions,
        "relation_safety": "metadata_only_no_edges",
    }
    paths = {
        "preview": _write_jsonl(out_dir / "rag_filter_preview.jsonl", records),
        "summary": _write_json(out_dir / "rag_filter_preview_summary.json", summary),
        "policy_report": _write_json(out_dir / "rag_filter_policy_report.json", policy_report),
    }
    return {"summary": summary, "paths": {key: str(path) for key, path in paths.items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build S0171 RAG filter preview (dry-run only).")
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--canon-dir", help="Canon dir; converted to <dir>/tiddlers_*.jsonl.")
    parser.add_argument("--tag-policy", default=str(DEFAULT_TAG_POLICY_PATH))
    parser.add_argument("--metadata-promotion-policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--metadata-candidates", default=str(DEFAULT_CANDIDATES))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--run-id", default="s0171-rag-filter-preview")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()
    if not args.dry_run:
        raise SystemExit("S0171 RAG filter preview is always dry-run")

    canon_glob = str(Path(args.canon_dir) / "tiddlers_*.jsonl") if args.canon_dir else args.canon_glob
    promotion_policy = load_policy(args.metadata_promotion_policy)
    candidates = read_jsonl(args.metadata_candidates)
    promoted = build_promoted_metadata_index(
        candidates,
        allowed_fields=set(promotion_policy["allowed_fields"]),
    )
    records = build_preview_records(
        read_canon_records(canon_glob),
        promoted_metadata=promoted,
        tag_policy=load_tag_policy(args.tag_policy),
    )
    result = write_preview_outputs(
        out_dir=Path(args.out_dir),
        records=records,
        candidates_path=args.metadata_candidates,
        promotion_policy_path=args.metadata_promotion_policy,
        run_id=args.run_id,
    )
    print(stable_json(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
