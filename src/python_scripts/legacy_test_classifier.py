#!/usr/bin/env python3
"""Classify legacy pytest failures for governed S0150 test saneamiento."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_OUT_DIR = Path("data/out/local/pipeline/test_saneamiento/s0150")
FAILED_RE = re.compile(r"^FAILED\s+([^\s]+)(?:\s+-\s+(.+))?$")
SUMMARY_RE = re.compile(r"(?P<failed>\d+) failed, (?P<passed>\d+) passed(?:, (?P<skipped>\d+) skipped)?")
PROTECTED_KEYWORDS = {
    "canon",
    "rollback",
    "human_review",
    "human review",
    "apply",
    "dry_run",
    "dry-run",
    "candidate",
    "hash",
    "mcp",
    "mirror",
    "exporter",
}


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def classify_failure(nodeid: str, message: str) -> dict[str, Any]:
    lower = f"{nodeid} {message}".lower()
    categories: list[str] = []
    if "classification_characterization" in nodeid or "derive_layers_characterization" in nodeid:
        categories.extend(["baseline_freeze_obsolete", "needs_test_update"])
    elif "readme" in lower:
        categories.extend(["readme_expectation_obsolete", "needs_test_update"])
    elif "legacy" in lower:
        categories.append("legacy_flow_obsolete")
    else:
        categories.append("requires_human_review")

    protected = sorted(keyword for keyword in PROTECTED_KEYWORDS if keyword in lower)
    if protected and "requires_human_review" not in categories:
        categories.append("requires_human_review")

    removable = not protected and any(category in categories for category in {"legacy_flow_obsolete", "readme_expectation_obsolete"})
    recommendation = "update_expected_baseline_with_human_review" if protected else "update_or_move_to_legacy"
    if removable:
        recommendation = "may_move_to_legacy_after_replacement"
    return {
        "nodeid": nodeid,
        "message": message,
        "classification": categories,
        "protected_keywords": protected,
        "removal_allowed": removable,
        "recommendation": recommendation,
    }


def parse_pytest_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    failures = []
    for line in text.splitlines():
        match = FAILED_RE.match(line.strip())
        if match:
            failures.append(classify_failure(match.group(1), match.group(2) or ""))
    summary = {
        "failed": len(failures),
        "passed": None,
        "skipped": None,
    }
    for match in SUMMARY_RE.finditer(text):
        summary = {
            "failed": int(match.group("failed")),
            "passed": int(match.group("passed")),
            "skipped": int(match.group("skipped") or 0),
        }
    return {
        "summary": summary,
        "failures": failures,
    }


def paths(out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Path]:
    return {
        "classification_json": out_dir / "s0150_legacy_test_classification.json",
        "classification_md": out_dir / "s0150_legacy_test_classification.md",
        "update_plan": out_dir / "s0150_test_update_plan.md",
        "pytest_log": out_dir / "s0150_pytest_full.log",
    }


def classification_markdown(payload: dict[str, Any]) -> str:
    counts = Counter(category for failure in payload["failures"] for category in failure["classification"])
    lines = [
        "# S0150 legacy test classification",
        "",
        f"- pytest_failed_total: {payload['summary']['failed']}",
        f"- pytest_passed_total: {payload['summary']['passed']}",
        f"- pytest_skipped_total: {payload['summary']['skipped']}",
        f"- classified_failures: {len(payload['failures'])}",
        f"- classification_counts: {dict(sorted(counts.items()))}",
        "",
        "| nodeid | classification | removal_allowed | recommendation |",
        "|---|---|---:|---|",
    ]
    for failure in payload["failures"]:
        lines.append(
            "| {nodeid} | {classes} | {removal} | {recommendation} |".format(
                nodeid=failure["nodeid"],
                classes=", ".join(failure["classification"]),
                removal=str(failure["removal_allowed"]).lower(),
                recommendation=failure["recommendation"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def update_plan_markdown(payload: dict[str, Any]) -> str:
    protected = [failure for failure in payload["failures"] if failure["protected_keywords"]]
    lines = [
        "# S0150 test update plan",
        "",
        "## Policy",
        "- Do not remove tests protecting canon, hashes, rollback, dry-run/apply separation, candidates, MCP/mirror, or repository exporter without explicit human review.",
        "- Prefer updating stale baselines or moving obsolete flows to legacy with replacement tests.",
        "",
        "## Current recommendation",
        "- Update frozen canon/derive/classification baselines only after human confirmation that 1597 records and 16 shards are the accepted current baseline.",
        "- No tests were removed in S0150.",
        f"- Protected failures requiring review: {len(protected)}.",
        "",
    ]
    return "\n".join(lines)


def classify_pytest_log(*, pytest_log: Path, out_dir: Path = DEFAULT_OUT_DIR, session: str = "S0150") -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = paths(out_dir)
    payload = parse_pytest_log(pytest_log)
    payload.update(
        {
            "schema": "legacy-test-classification/v1",
            "session": session,
            "pytest_log": str(pytest_log),
            "tests_updated": 0,
            "tests_moved_to_legacy": 0,
            "tests_removed": 0,
            "critical_test_removal_permitted": False,
        }
    )
    p["pytest_log"].write_text(pytest_log.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    p["classification_json"].write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")
    p["classification_md"].write_text(classification_markdown(payload), encoding="utf-8")
    p["update_plan"].write_text(update_plan_markdown(payload), encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify legacy pytest failures")
    parser.add_argument("--pytest-log", required=True)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--session", default="S0150")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = classify_pytest_log(
        pytest_log=Path(args.pytest_log),
        out_dir=Path(args.out_dir),
        session=str(args.session).upper(),
    )
    print(stable_json({"status": "ok", "summary": payload["summary"], "classified_failures": len(payload["failures"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
