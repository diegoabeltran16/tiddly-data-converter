#!/usr/bin/env python3
"""Build the S0169 dry-run tag sanitation plan.

The plan is advisory and reversible by construction: canon_modified=false,
dry_run=true, and P0 defaults to exclude_from_rag rather than remove_from_tags.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from audit_tags_inventory import DEFAULT_CANON_GLOB, DEFAULT_OUT_DIR, read_canon_records, source_tags_for_record
from tag_sanitation_policy import DEFAULT_POLICY_PATH, classify_tag, load_policy, stable_json


DEFAULT_PLAN_PATH = DEFAULT_OUT_DIR / "tag_sanitation_plan.dry_run.json"
ACTION_BY_CLASSIFICATION = {
    "p0_blocked": "exclude_from_rag",
    "p1_promote": "promote_to_metadata",
    "p2_human_nav": "keep_human_visible",
    "p3_projectable": "requires_human_review",
    "unknown": "requires_human_review",
}
REASON_BY_CLASSIFICATION = {
    "p0_blocked": "technical or structural tag must not enter RAG before human-approved canon cleanup",
    "p1_promote": "metadata-like tag should be reviewed for structured metadata promotion",
    "p2_human_nav": "human navigation tag remains visible and is not treated as relation or primary metadata",
    "p3_projectable": "projected tdc tag namespace is derived and requires anti-cycle review",
    "unknown": "tag requires human review before promotion, blocking, or projection",
}


def build_plan(records: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    summary: Counter[str] = Counter()

    for record in records:
        for tag in source_tags_for_record(record):
            decision = classify_tag(tag, policy)
            action = ACTION_BY_CLASSIFICATION.get(decision["classification"], "requires_human_review")
            summary[f"{action}_count"] += 1
            actions.append(
                {
                    "tiddler_id": record.get("id"),
                    "title": record.get("title") or record.get("key"),
                    "tag": tag,
                    "classification": decision["classification"],
                    "rag_policy": decision["rag_policy"],
                    "recommended_action": action,
                    "destructive_action_required": False,
                    "reason": REASON_BY_CLASSIFICATION.get(decision["classification"], "review required"),
                }
            )

    for key in (
        "remove_from_tags_count",
        "exclude_from_rag_count",
        "promote_to_metadata_count",
        "keep_human_visible_count",
        "requires_human_review_count",
    ):
        summary.setdefault(key, 0)

    return {
        "schema": "tag-sanitation-plan/v1",
        "plan_id": "s0169-tag-sanitation-dry-run",
        "canon_modified": False,
        "derivatives_modified": False,
        "dry_run": True,
        "default_p0_action": "exclude_from_rag",
        "actions": actions,
        "summary": dict(sorted(summary.items())),
    }


def write_plan(path: Path, plan: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(plan, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build S0169 tag sanitation dry-run plan.")
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--out", default=str(DEFAULT_PLAN_PATH))
    args = parser.parse_args()

    records = read_canon_records(args.canon_glob)
    policy = load_policy(args.policy)
    plan = build_plan(records, policy)
    path = write_plan(Path(args.out), plan)
    print(stable_json({"path": str(path), "summary": plan["summary"], "canon_modified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
