#!/usr/bin/env python3
"""Build a persistent source-tag inventory for S0169.

Reads live canon shards and writes inventory artifacts under
data/out/local/pipeline/tag_sanitation/s0169 by default. It never mutates canon.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tag_sanitation_policy import (
    DEFAULT_POLICY_PATH,
    REPO_ROOT,
    classify_tag,
    load_policy,
    parse_tags,
    stable_json,
)


DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "tag_sanitation" / "s0169"
INVENTORY_COLUMNS = [
    "tag",
    "count",
    "sample_tiddlers",
    "has_emoji",
    "looks_like_path",
    "looks_like_markdown_header",
    "looks_like_code_marker",
    "looks_like_metadata_prefix",
    "classification",
    "rag_policy",
    "recommended_action",
]


def read_canon_records(canon_glob: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for shard in sorted(glob.glob(canon_glob)):
        path = Path(shard)
        with path.open(encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                record = json.loads(raw)
                if isinstance(record, dict):
                    record["_source_shard"] = str(path)
                    record["_source_line"] = line_no
                    records.append(record)
    return records


def source_tags_for_record(record: dict[str, Any]) -> list[str]:
    return parse_tags(record.get("tags"))


def tiddler_ref(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "title": record.get("title") or record.get("key"),
        "shard": record.get("_source_shard"),
        "line": record.get("_source_line"),
    }


def build_inventory(records: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    emoji_appearances = 0

    for record in records:
        tags = source_tags_for_record(record)
        for tag in tags:
            counts[tag] += 1
            decision = classify_tag(tag, policy)
            if decision["has_emoji"]:
                emoji_appearances += 1
            if len(samples[tag]) < 5:
                samples[tag].append(tiddler_ref(record))

    rows: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    rag_counts: Counter[str] = Counter()
    for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold())):
        decision = classify_tag(tag, policy)
        row = {
            "tag": tag,
            "count": count,
            "sample_tiddlers": samples[tag],
            **decision,
        }
        rows.append(row)
        class_counts[decision["classification"]] += 1
        rag_counts[decision["rag_policy"]] += 1

    summary = {
        "schema": "tag-inventory/v1",
        "session": "S0169",
        "canon_modified": False,
        "dry_run": True,
        "total_tiddlers": len(records),
        "unique_tags": len(counts),
        "tag_appearances": sum(counts.values()),
        "tags_with_emoji": sum(1 for row in rows if row["has_emoji"]),
        "tag_appearances_with_emoji": emoji_appearances,
        "classification_counts": dict(sorted(class_counts.items())),
        "rag_policy_counts": dict(sorted(rag_counts.items())),
    }
    return {
        "summary": summary,
        "tags": rows,
    }


def write_inventory_outputs(inventory: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "tag_inventory.json"
    csv_path = out_dir / "tag_inventory.csv"
    summary_path = out_dir / "tag_inventory_summary.md"

    json_path.write_text(stable_json(inventory, indent=2) + "\n", encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_COLUMNS)
        writer.writeheader()
        for row in inventory["tags"]:
            writer.writerow(
                {
                    key: stable_json(row.get(key)) if key == "sample_tiddlers" else row.get(key)
                    for key in INVENTORY_COLUMNS
                }
            )

    summary = inventory["summary"]
    lines = [
        "# S0169 tag inventory summary",
        "",
        f"- canon_modified: {str(summary['canon_modified']).lower()}",
        f"- dry_run: {str(summary['dry_run']).lower()}",
        f"- total_tiddlers: {summary['total_tiddlers']}",
        f"- unique_tags: {summary['unique_tags']}",
        f"- tag_appearances: {summary['tag_appearances']}",
        f"- tags_with_emoji: {summary['tags_with_emoji']}",
        f"- tag_appearances_with_emoji: {summary['tag_appearances_with_emoji']}",
        "",
        "## Classification counts",
        "",
    ]
    for key, value in summary["classification_counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## RAG policy counts", ""])
    for key, value in summary["rag_policy_counts"].items():
        lines.append(f"- {key}: {value}")
    summary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    return {
        "json": str(json_path),
        "csv": str(csv_path),
        "summary": str(summary_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit live canon source tags for S0169.")
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    policy = load_policy(args.policy)
    records = read_canon_records(args.canon_glob)
    inventory = build_inventory(records, policy)
    paths = write_inventory_outputs(inventory, Path(args.out_dir))
    print(stable_json({"summary": inventory["summary"], "paths": paths}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
