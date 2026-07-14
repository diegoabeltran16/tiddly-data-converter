#!/usr/bin/env python3
"""Build an isolated S0170 RAG-safe semantic_text preview.

This wrapper only writes under data/out/local/pipeline/rag_sanitation/s0170 by
default. It never writes canon shards or productive derived directories.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from audit_tags_inventory import DEFAULT_CANON_GLOB, read_canon_records
from build_rag_filter_preview import build_promoted_metadata_index, read_jsonl
from metadata_promotion_policy import load_policy as load_metadata_promotion_policy
from semantic_text_builder import build_semantic_text_outputs
from tag_sanitation_policy import DEFAULT_POLICY_PATH, filter_tags_for_rag, load_policy, stable_json


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "rag_sanitation" / "s0170"
DEFAULT_PREVIEW_DIR = DEFAULT_OUT_DIR / "preview"


def collect_tag_review(records: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    blocked: dict[str, dict[str, Any]] = {}
    unknown: dict[str, dict[str, Any]] = {}
    totals = Counter()

    for record in records:
        tags = record.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split()
        filtered = filter_tags_for_rag([str(tag) for tag in tags], policy)
        for bucket_name, target in (("blocked_tags", blocked), ("unknown_tags", unknown)):
            for tag in filtered[bucket_name]:
                entry = target.setdefault(
                    tag,
                    {
                        "tag": tag,
                        "occurrences": 0,
                        "sample_tiddlers": [],
                        "recommended_review": (
                            "block_from_rag_or_canon_sanitation"
                            if bucket_name == "blocked_tags"
                            else "human_review_before_rag"
                        ),
                    },
                )
                entry["occurrences"] += 1
                totals[bucket_name] += 1
                if len(entry["sample_tiddlers"]) < 5:
                    entry["sample_tiddlers"].append(
                        {
                            "id": record.get("id"),
                            "title": record.get("title") or record.get("key"),
                        }
                    )

    return {
        "blocked": sorted(blocked.values(), key=lambda item: (-item["occurrences"], item["tag"].casefold())),
        "unknown": sorted(unknown.values(), key=lambda item: (-item["occurrences"], item["tag"].casefold())),
        "summary": {
            "blocked_tags_unique": len(blocked),
            "blocked_tags_occurrences": totals["blocked_tags"],
            "unknown_tags_unique": len(unknown),
            "unknown_tags_occurrences": totals["unknown_tags"],
        },
    }


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build S0170 isolated RAG-safe semantic_text preview.")
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--canon-dir", help="Canon dir; converted to <dir>/tiddlers_*.jsonl.")
    parser.add_argument("--tag-policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--preview-dir")
    parser.add_argument("--run-id", default="s0170-rag-safe-preview")
    parser.add_argument("--session", default="S0170")
    parser.add_argument("--metadata-promotion-policy")
    parser.add_argument("--metadata-candidates")
    parser.add_argument("--strict-tag-gate", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args()

    if not args.dry_run:
        raise SystemExit("S0170 preview is always dry-run")

    canon_glob = str(Path(args.canon_dir) / "tiddlers_*.jsonl") if args.canon_dir else args.canon_glob
    out_dir = Path(args.out_dir)
    if args.preview_dir:
        preview_dir = Path(args.preview_dir)
    elif args.metadata_candidates or args.metadata_promotion_policy or args.session.upper() == "S0171":
        preview_dir = out_dir / "preview"
    else:
        preview_dir = DEFAULT_PREVIEW_DIR
    policy = load_policy(args.tag_policy)
    records = read_canon_records(canon_glob)
    review = collect_tag_review(records, policy)
    promoted_metadata = None
    promotion_policy_version = None
    if args.metadata_candidates:
        promotion_policy = load_metadata_promotion_policy(
            args.metadata_promotion_policy
            or "data/out/local/pipeline/metadata_promotion/s0171/metadata_promotion_policy.json"
        )
        promoted_metadata = build_promoted_metadata_index(
            read_jsonl(args.metadata_candidates),
            allowed_fields=set(promotion_policy["allowed_fields"]),
        )
        promotion_policy_version = promotion_policy.get("policy_version")

    result = build_semantic_text_outputs(
        canon_glob=canon_glob,
        out_dir=preview_dir,
        session=args.run_id,
        tag_policy=Path(args.tag_policy),
        strict_tag_gate=args.strict_tag_gate,
        promoted_metadata_by_id=promoted_metadata,
    )

    manifest = {
        "schema": "rag-safe-preview-manifest/v1",
        "session": args.session.upper(),
        "run_id": args.run_id,
        "dry_run": True,
        "canon_modified": False,
        "productive_derivatives_modified": False,
        "tag_policy": str(args.tag_policy),
        "metadata_promotion_policy": args.metadata_promotion_policy,
        "metadata_candidates": args.metadata_candidates,
        "metadata_promotion_policy_version": promotion_policy_version,
        "preview_dir": str(preview_dir),
        "semantic_text_result": result,
        "tag_review_summary": review["summary"],
    }
    policy_report = {
        "schema": "semantic-text-builder-policy-report/v1",
        "session": args.session.upper(),
        "run_id": args.run_id,
        "policy_version": policy.get("policy_version"),
        "strict_tag_gate": args.strict_tag_gate,
        "flow": (
            "source_tags -> tag_sanitation_policy -> metadata-promotion/v1 -> "
            "normalized promoted metadata -> semantic_text/retrieval_hints/embedding_metadata"
            if promoted_metadata is not None
            else "source_tags -> tag_sanitation_policy -> classified_tags -> rag_allowed_tags/metadata_only/human_navigation/blocked/unknown -> semantic_text/retrieval_hints/embedding_metadata"
        ),
        "canon_modified": False,
        "productive_derivatives_modified": False,
        "builder_summary": result["summary"],
    }
    unknown_queue = {
        "schema": "unknown-tag-review-queue/v1",
        "session": args.session.upper(),
        "unknown_tags_unique": review["summary"]["unknown_tags_unique"],
        "unknown_tags_occurrences": review["summary"]["unknown_tags_occurrences"],
        "recommended_review": "unknown tags are excluded from RAG by default until human review",
        "items": review["unknown"],
    }
    blocked_samples = {
        "schema": "blocked-tag-samples/v1",
        "session": args.session.upper(),
        "blocked_tags_unique": review["summary"]["blocked_tags_unique"],
        "blocked_tags_occurrences": review["summary"]["blocked_tags_occurrences"],
        "items": review["blocked"][:200],
    }

    paths = {
        "manifest": write_json(out_dir / "rag_safe_preview_manifest.json", manifest),
        "policy_report": write_json(out_dir / "semantic_text_builder_policy_report.json", policy_report),
        "unknown_queue": write_json(out_dir / "unknown_tag_review_queue.json", unknown_queue),
        "blocked_samples": write_json(out_dir / "blocked_tag_samples.json", blocked_samples),
    }
    print(stable_json({name: str(path) for name, path in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
