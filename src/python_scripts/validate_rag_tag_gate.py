#!/usr/bin/env python3
"""Dry-run anti-noise gate for P0 tags in RAG-facing artifacts.

The gate reports P0 propagation into semantic_text, retrieval_hints, embedding
metadata, AI chunks, and Microsoft Copilot exports. It never regenerates or
modifies derived layers.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from audit_tags_inventory import DEFAULT_CANON_GLOB, DEFAULT_OUT_DIR, build_inventory, read_canon_records
from tag_sanitation_policy import (
    DEFAULT_POLICY_PATH,
    REPO_ROOT,
    classify_tag,
    load_policy,
    p0_tags_from_inventory,
    parse_tags,
    stable_json,
)


DEFAULT_INVENTORY = DEFAULT_OUT_DIR / "tag_inventory.json"
DEFAULT_REPORT = DEFAULT_OUT_DIR / "rag_tag_gate_report.json"
DEFAULT_REPORT_MD = DEFAULT_OUT_DIR / "rag_tag_gate_report.md"
DEFAULT_SCAN_ROOTS = [
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "semantic_text",
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "semantic_text_authority",
    REPO_ROOT / "data" / "out" / "local" / "enriched",
    REPO_ROOT / "data" / "out" / "local" / "ai",
    REPO_ROOT / "data" / "out" / "local" / "microsoft_copilot",
]
TEXT_EXTENSIONS = {".md", ".txt", ".csv"}
JSON_EXTENSIONS = {".json", ".jsonl"}
SEMANTIC_FIELDS = {"semantic_text"}
RETRIEVAL_FIELDS = {"retrieval_hints", "retrieval_terms", "retrieval_aliases"}
EMBEDDING_METADATA_FIELDS = {"tags", "source_tags", "normalized_tags", "metadata", "embedding_metadata"}


def load_inventory(path: Path, policy: dict[str, Any], canon_glob: str) -> dict[str, Any]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    records = read_canon_records(canon_glob)
    return build_inventory(records, policy)


def field_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(field_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(field_values(item))
        return values
    return [str(value)]


def detect_tags_in_values(values: list[str], p0_tags: set[str]) -> list[str]:
    hits: set[str] = set()
    for value in values:
        text = str(value)
        parsed = set(parse_tags(text))
        for tag in p0_tags:
            if tag in parsed or tag == text or (tag and tag in text):
                hits.add(tag)
    return sorted(hits, key=lambda item: item.casefold())


def iter_json_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                value = json.loads(raw)
                if isinstance(value, dict):
                    value["_gate_line"] = line_no
                    rows.append(value)
        return rows
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def scan_json_file(path: Path, p0_tags: set[str], unknown_tags: set[str] | None = None) -> tuple[int, list[dict[str, Any]]]:
    unknown_tags = unknown_tags or set()
    findings: list[dict[str, Any]] = []
    checked = 0
    for record in iter_json_records(path):
        checked += 1
        record_id = record.get("id") or record.get("tiddler_id") or record.get("title") or ""
        title = record.get("title") or record.get("key") or ""
        for field_name, value in record.items():
            if field_name.startswith("_"):
                continue
            field_kind = ""
            if field_name in SEMANTIC_FIELDS:
                field_kind = "semantic_text"
            elif field_name in RETRIEVAL_FIELDS:
                field_kind = "retrieval_hints"
            elif field_name in EMBEDDING_METADATA_FIELDS:
                field_kind = "embedding_metadata"
            else:
                continue
            values = field_values(value)
            hits = detect_tags_in_values(values, p0_tags)
            for tag in hits:
                findings.append(
                    {
                        "path": str(path),
                        "line": record.get("_gate_line"),
                        "record_id": record_id,
                        "title": title,
                        "field": field_name,
                        "field_kind": field_kind,
                        "tag": tag,
                        "tag_kind": "p0",
                    }
                )
            unknown_hits = detect_tags_in_values(values, unknown_tags)
            for tag in unknown_hits:
                findings.append(
                    {
                        "path": str(path),
                        "line": record.get("_gate_line"),
                        "record_id": record_id,
                        "title": title,
                        "field": field_name,
                        "field_kind": field_kind,
                        "tag": tag,
                        "tag_kind": "unknown",
                    }
                )
    return checked, findings


def scan_text_file(path: Path, p0_tags: set[str], unknown_tags: set[str] | None = None) -> tuple[int, list[dict[str, Any]]]:
    unknown_tags = unknown_tags or set()
    findings: list[dict[str, Any]] = []
    checked = 0
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for line_no, row in enumerate(reader, start=2):
                checked += 1
                for field_name in ("tags", "retrieval_hints", "retrieval_terms", "retrieval_aliases"):
                    if field_name not in row:
                        continue
                    values = [row.get(field_name) or ""]
                    hits = detect_tags_in_values(values, p0_tags)
                    for tag in hits:
                        findings.append(
                            {
                                "path": str(path),
                                "line": line_no,
                                "record_id": row.get("id") or "",
                                "title": row.get("title") or "",
                                "field": field_name,
                                "field_kind": "embedding_metadata" if field_name == "tags" else "retrieval_hints",
                                "tag": tag,
                                "tag_kind": "p0",
                            }
                        )
                    unknown_hits = detect_tags_in_values(values, unknown_tags)
                    for tag in unknown_hits:
                        findings.append(
                            {
                                "path": str(path),
                                "line": line_no,
                                "record_id": row.get("id") or "",
                                "title": row.get("title") or "",
                                "field": field_name,
                                "field_kind": "embedding_metadata" if field_name == "tags" else "retrieval_hints",
                                "tag": tag,
                                "tag_kind": "unknown",
                            }
                        )
        return checked, findings

    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.startswith(("TAGS:", "RETRIEVAL_HINTS:", "RETRIEVAL_TERMS:", "RETRIEVAL_ALIASES:")):
            continue
        checked += 1
        field_kind = "embedding_metadata" if line.startswith("TAGS:") else "retrieval_hints"
        values = [line]
        hits = detect_tags_in_values(values, p0_tags)
        for tag in hits:
            findings.append(
                {
                    "path": str(path),
                    "line": line_no,
                    "record_id": "",
                    "title": "",
                    "field": line.split(":", 1)[0].lower(),
                    "field_kind": field_kind,
                    "tag": tag,
                    "tag_kind": "p0",
                }
            )
        unknown_hits = detect_tags_in_values(values, unknown_tags)
        for tag in unknown_hits:
            findings.append(
                {
                    "path": str(path),
                    "line": line_no,
                    "record_id": "",
                    "title": "",
                    "field": line.split(":", 1)[0].lower(),
                    "field_kind": field_kind,
                    "tag": tag,
                    "tag_kind": "unknown",
                }
            )
    return checked, findings


def scan_roots(roots: list[Path], p0_tags: set[str], unknown_tags: set[str] | None = None) -> tuple[int, list[dict[str, Any]], list[str]]:
    unknown_tags = unknown_tags or set()
    checked = 0
    findings: list[dict[str, Any]] = []
    warnings: list[str] = []
    for root in roots:
        if not root.exists():
            warnings.append(f"scan_root_missing: {root}")
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.suffix in JSON_EXTENSIONS:
                try:
                    count, file_findings = scan_json_file(path, p0_tags, unknown_tags)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    warnings.append(f"scan_skipped_invalid_json: {path}: {exc}")
                    continue
            elif path.suffix in TEXT_EXTENSIONS:
                count, file_findings = scan_text_file(path, p0_tags, unknown_tags)
            else:
                continue
            checked += count
            findings.extend(file_findings)
    return checked, findings, warnings


def projected_tag_risks(inventory: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for item in inventory.get("tags", []):
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag") or "")
        decision = classify_tag(tag, policy)
        if decision["classification"] == "p3_projectable" and item.get("count", 0):
            risks.append(
                {
                    "tag": tag,
                    "count": item.get("count", 0),
                    "risk": "tdc:* appears in source_tags; it must not be used as primary metadata or relation source",
                }
            )
    return risks


def unknown_tags_from_inventory(inventory: dict[str, Any]) -> set[str]:
    tags = inventory.get("tags", inventory)
    if not isinstance(tags, list):
        return set()
    return {
        str(item.get("tag"))
        for item in tags
        if isinstance(item, dict) and item.get("classification") == "unknown" and item.get("tag")
    }


def build_gate_report(
    *,
    policy: dict[str, Any],
    inventory: dict[str, Any],
    roots: list[Path],
    session: str = "S0169",
    run_id: str = "",
) -> dict[str, Any]:
    p0_tags = p0_tags_from_inventory(inventory)
    p0_tags.update(str(tag) for tag in policy.get("rag_blocklist", []) if tag)
    unknown_tags = unknown_tags_from_inventory(inventory)
    checked, findings, warnings = scan_roots(roots, p0_tags, unknown_tags)

    p0_findings = [item for item in findings if item.get("tag_kind") == "p0"]
    unknown_findings = [item for item in findings if item.get("tag_kind") == "unknown"]
    semantic_findings = [item for item in p0_findings if item["field_kind"] == "semantic_text"]
    retrieval_findings = [item for item in p0_findings if item["field_kind"] == "retrieval_hints"]
    metadata_findings = [item for item in p0_findings if item["field_kind"] == "embedding_metadata"]
    unknown_semantic_findings = [item for item in unknown_findings if item["field_kind"] == "semantic_text"]
    unknown_retrieval_findings = [item for item in unknown_findings if item["field_kind"] == "retrieval_hints"]
    unknown_metadata_findings = [item for item in unknown_findings if item["field_kind"] == "embedding_metadata"]
    tdc_risks = projected_tag_risks(inventory, policy)
    if tdc_risks:
        warnings.append("tdc_projected_tags_present_in_source_tags")
    if not p0_tags:
        warnings.append("no_p0_tags_detected_in_inventory")
    if not checked:
        warnings.append("no_rag_artifacts_checked")

    status = "pass"
    if (
        semantic_findings
        or retrieval_findings
        or metadata_findings
        or unknown_semantic_findings
        or unknown_retrieval_findings
        or unknown_metadata_findings
    ):
        status = "blocked"
    elif findings or warnings:
        status = "warning"

    return {
        "schema": "rag-tag-gate/v1",
        "session": session,
        "run_id": run_id,
        "canon_modified": False,
        "derivatives_modified": False,
        "dry_run": True,
        "policy_version": policy.get("policy_version"),
        "scan_roots": [str(root) for root in roots],
        "total_records_checked": checked,
        "p0_tags_detected": len(p0_tags),
        "p0_tag_values": sorted(p0_tags, key=lambda item: item.casefold()),
        "unknown_tags_detected": len(unknown_tags),
        "unknown_tag_values": sorted(unknown_tags, key=lambda item: item.casefold()),
        "p0_tags_in_semantic_text": len(semantic_findings),
        "p0_tags_in_retrieval_hints": len(retrieval_findings),
        "p0_tags_in_embedding_metadata": len(metadata_findings),
        "unknown_tags_in_semantic_text": len(unknown_semantic_findings),
        "unknown_tags_in_retrieval_hints": len(unknown_retrieval_findings),
        "unknown_tags_in_embedding_metadata": len(unknown_metadata_findings),
        "tdc_projected_tag_risks": tdc_risks,
        "blocked_records": findings,
        "warnings": sorted(set(warnings)),
        "status": status,
    }


def write_report(path: Path, md_path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# S0169 RAG tag gate report",
        "",
        f"- status: {report['status']}",
        f"- canon_modified: {str(report['canon_modified']).lower()}",
        f"- derivatives_modified: {str(report['derivatives_modified']).lower()}",
        f"- total_records_checked: {report['total_records_checked']}",
        f"- p0_tags_detected: {report['p0_tags_detected']}",
        f"- p0_tags_in_semantic_text: {report['p0_tags_in_semantic_text']}",
        f"- p0_tags_in_retrieval_hints: {report['p0_tags_in_retrieval_hints']}",
        f"- p0_tags_in_embedding_metadata: {report['p0_tags_in_embedding_metadata']}",
        f"- unknown_tags_in_semantic_text: {report['unknown_tags_in_semantic_text']}",
        f"- unknown_tags_in_retrieval_hints: {report['unknown_tags_in_retrieval_hints']}",
        f"- unknown_tags_in_embedding_metadata: {report['unknown_tags_in_embedding_metadata']}",
        f"- blocked_records: {len(report['blocked_records'])}",
        "",
        "## Warnings",
        "",
    ]
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- none")
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RAG anti-noise tag gate in dry-run mode.")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--canon-dir", help="Canon dir; converted to <dir>/tiddlers_*.jsonl when inventory must be rebuilt.")
    parser.add_argument("--input-dir", help="Scan only this RAG output directory.")
    parser.add_argument("--out-dir", help="Write reports into this directory.")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--session", default="S0170")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--report-md", default=str(DEFAULT_REPORT_MD))
    parser.add_argument("--scan-root", action="append", default=[], help="Additional or replacement scan root.")
    args = parser.parse_args()

    canon_glob = str(Path(args.canon_dir) / "tiddlers_*.jsonl") if args.canon_dir else args.canon_glob
    report = Path(args.report)
    report_md = Path(args.report_md)
    if args.out_dir:
        out_dir = Path(args.out_dir)
        report = out_dir / "rag_tag_gate_report.json"
        report_md = out_dir / "rag_tag_gate_report.md"
    policy = load_policy(args.policy)
    inventory = load_inventory(Path(args.inventory), policy, canon_glob)
    if args.input_dir:
        roots = [Path(args.input_dir)]
    else:
        roots = [Path(root) for root in args.scan_root] if args.scan_root else DEFAULT_SCAN_ROOTS
    payload = build_gate_report(
        policy=policy,
        inventory=inventory,
        roots=roots,
        session=args.session,
        run_id=args.run_id,
    )
    write_report(report, report_md, payload)
    print(stable_json(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
