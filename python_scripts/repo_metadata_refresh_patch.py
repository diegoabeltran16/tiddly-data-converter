#!/usr/bin/env python3
"""Refresh S0147 repo metadata patch preview against the current canon.

S0150 uses this script to resolve stale canon hashes without applying metadata.
It reads the S0147 patch preview, verifies each target against the live canon,
recomputes preview/batch hashes, and writes refreshed dry-run artifacts.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_S0147_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_review" / "s0147"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_admission" / "s0150"
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
SESSION_TITLE_RE = re.compile(
    r"^#### .*?(sesión|sesion|diagnóstico|diagnostico|hipótesis|hipotesis|procedencia|balance|propuesta|contrato)",
    re.IGNORECASE,
)


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tree_sha256(glob_pattern: str) -> str:
    digest = hashlib.sha256()
    for path_str in sorted(glob.glob(glob_pattern)):
        path = Path(path_str)
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                value = json.loads(raw)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(stable_json(row) + "\n" for row in rows), encoding="utf-8")


def subset_sha(rows: list[dict[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda row: stable_json(row))
    return hashlib.sha256("".join(stable_json(row) + "\n" for row in ordered).encode("utf-8")).hexdigest()


def refreshed_paths(out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Path]:
    return {
        "report": out_dir / "s0150_metadata_refresh_report.json",
        "summary": out_dir / "s0150_metadata_refresh_summary.md",
        "patch_preview": out_dir / "s0150_metadata_patch_preview_refreshed.jsonl",
        "review_batches": out_dir / "s0150_metadata_review_batches_refreshed.json",
        "patch_hashes": out_dir / "s0150_metadata_patch_hashes_refreshed.json",
        "blocked": out_dir / "s0150_metadata_refresh_blocked.jsonl",
        "review": out_dir / "s0150_metadata_refresh_review.csv",
    }


def load_canon_index(canon_glob: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for path_str in sorted(glob.glob(canon_glob)):
        for row in read_jsonl(Path(path_str)):
            row_id = str(row.get("id") or "")
            if row_id:
                index[row_id] = row
    return index


def source_fields(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("source_fields")
    return value if isinstance(value, dict) else {}


def current_family(record: dict[str, Any]) -> str:
    fields = source_fields(record)
    value = fields.get("artifact_family") or record.get("artifact_family") or record.get("family") or ""
    return str(value or "unknown")


def block_reasons_for_row(row: dict[str, Any], canon_index: dict[str, dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    target_id = str(row.get("target_id") or "")
    current = canon_index.get(target_id)
    fields_preview = row.get("fields_preview") if isinstance(row.get("fields_preview"), dict) else {}
    if not current:
        return ["target_missing"]
    current_title = str(current.get("title") or "")
    expected_title = str(row.get("target_title") or "")
    if expected_title and current_title and expected_title != current_title:
        reasons.append("target_title_changed")
    current_key = str(current.get("key") or "")
    expected_key = str(row.get("target_key") or "")
    if expected_key and current_key and expected_key != current_key:
        reasons.append("target_key_changed")
    if str(row.get("source_risk_level") or row.get("risk_level") or "") == "critical":
        reasons.append("critical_risk")
    proposed_family = fields_preview.get("artifact_family")
    if proposed_family:
        family = current_family(current)
        if SESSION_TITLE_RE.search(current_title):
            reasons.append("artifact_family_session_preserved")
        elif family not in {"", "unknown", str(proposed_family)}:
            reasons.append("artifact_family_conflict")
        if row.get("batch_id") != "batch_current_verified":
            reasons.append("artifact_family_only_allowed_for_current_verified")
    if "relations" in row or "candidate_relations" in row:
        reasons.append("relation_field_present")
    if "relations" in fields_preview or "candidate_relations" in fields_preview:
        reasons.append("relation_field_present_in_fields_preview")
    return sorted(set(reasons))


def refreshed_row(row: dict[str, Any], *, session: str, canon_before_sha256: str) -> dict[str, Any]:
    payload = dict(row)
    payload["session"] = session
    payload["source_session"] = "S0147"
    payload["refresh_session"] = session
    payload["canon_before_sha256_refreshed"] = canon_before_sha256
    payload["dry_run"] = True
    payload["applied_to_canon"] = False
    payload["canon_modified"] = False
    payload["relations_generated"] = False
    payload["candidate_relations_generated"] = False
    return payload


def blocked_row(row: dict[str, Any], reasons: list[str], *, session: str) -> dict[str, Any]:
    return {
        "session": session,
        "source_session": "S0147",
        "op_id": row.get("op_id", ""),
        "target_id": row.get("target_id", ""),
        "target_title": row.get("target_title", ""),
        "batch_id": row.get("batch_id", ""),
        "patch_lane": row.get("patch_lane", ""),
        "risk_level": row.get("source_risk_level", row.get("risk_level", "")),
        "block_reasons": reasons,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
    }


def build_refreshed_batches(original_batches: dict[str, Any], ready_rows: list[dict[str, Any]], *, canon_before_sha256: str, session: str) -> dict[str, Any]:
    rows_by_batch: dict[str, list[dict[str, Any]]] = {}
    for row in ready_rows:
        rows_by_batch.setdefault(str(row.get("batch_id") or ""), []).append(row)
    refreshed: dict[str, Any] = {}
    all_batch_ids = sorted(set(original_batches) | set(rows_by_batch))
    for batch_id in all_batch_ids:
        original = original_batches.get(batch_id, {})
        rows = rows_by_batch.get(batch_id, [])
        risks = Counter(str(row.get("source_risk_level") or row.get("risk_level") or "") for row in rows)
        batch = dict(original)
        batch.update(
            {
                "session": session,
                "source_session": "S0147",
                "batch_id": batch_id,
                "record_count": len(rows),
                "patch_sha256": subset_sha(rows),
                "canon_before_sha256": canon_before_sha256,
                "risk_profile": dict(sorted((risk, count) for risk, count in risks.items() if risk)),
                "dry_run": True,
                "applied_to_canon": False,
                "human_approved": False,
            }
        )
        refreshed[batch_id] = batch
    return {
        "schema": "repo-metadata-review-batches/v1",
        "session": session,
        "source_session": "S0147",
        "dry_run": True,
        "applied_to_canon": False,
        "human_approved": False,
        "batches": refreshed,
    }


def write_review_csv(path: Path, ready_rows: list[dict[str, Any]], blocked_rows: list[dict[str, Any]]) -> None:
    fieldnames = ["status", "op_id", "target_id", "target_title", "batch_id", "patch_lane", "risk_level", "block_reasons"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in ready_rows:
            writer.writerow(
                {
                    "status": "preserved",
                    "op_id": row.get("op_id", ""),
                    "target_id": row.get("target_id", ""),
                    "target_title": row.get("target_title", ""),
                    "batch_id": row.get("batch_id", ""),
                    "patch_lane": row.get("patch_lane", ""),
                    "risk_level": row.get("source_risk_level", row.get("risk_level", "")),
                    "block_reasons": "",
                }
            )
        for row in blocked_rows:
            writer.writerow(
                {
                    "status": "blocked",
                    "op_id": row.get("op_id", ""),
                    "target_id": row.get("target_id", ""),
                    "target_title": row.get("target_title", ""),
                    "batch_id": row.get("batch_id", ""),
                    "patch_lane": row.get("patch_lane", ""),
                    "risk_level": row.get("risk_level", ""),
                    "block_reasons": "|".join(row.get("block_reasons") or []),
                }
            )


def summary_md(report: dict[str, Any]) -> str:
    lines = [
        "# S0150 metadata refresh summary",
        "",
        f"- source_patch_operations: {report['source_patch_operations']}",
        f"- operations_preserved: {report['operations_preserved']}",
        f"- operations_blocked: {report['operations_blocked']}",
        f"- canon_before_sha256_old: `{report['canon_before_sha256_old']}`",
        f"- canon_before_sha256_refreshed: `{report['canon_before_sha256_refreshed']}`",
        f"- block_reason_counts: {report['block_reason_counts']}",
        "- dry_run: true",
        "- applied_to_canon: false",
        "- canon_modified: false",
        "- relations_generated: false",
        "- candidate_relations_generated: false",
        "",
        "## Batches",
    ]
    for batch_id, count in report["preserved_by_batch"].items():
        lines.append(f"- {batch_id}: {count}")
    lines.append("")
    return "\n".join(lines)


def refresh_metadata_patch(
    *,
    patch_preview: Path,
    review_batches: Path,
    patch_hashes: Path,
    canon_glob: str,
    out_dir: Path,
    session: str = "S0150",
    dry_run: bool = True,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("S0150 metadata refresh is dry-run only")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = refreshed_paths(out_dir)
    source_rows = read_jsonl(patch_preview)
    source_batches_doc = read_json(review_batches)
    source_hashes = read_json(patch_hashes)
    canon_index = load_canon_index(canon_glob)
    current_canon_sha = tree_sha256(canon_glob)
    ready_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    reason_counter: Counter[str] = Counter()

    for row in source_rows:
        reasons = block_reasons_for_row(row, canon_index)
        if reasons:
            blocked = blocked_row(row, reasons, session=session)
            blocked_rows.append(blocked)
            reason_counter.update(reasons)
        else:
            ready_rows.append(refreshed_row(row, session=session, canon_before_sha256=current_canon_sha))

    refreshed_batches = build_refreshed_batches(
        source_batches_doc.get("batches") or {},
        ready_rows,
        canon_before_sha256=current_canon_sha,
        session=session,
    )
    write_jsonl(paths["patch_preview"], ready_rows)
    write_jsonl(paths["blocked"], blocked_rows)
    write_json(paths["review_batches"], refreshed_batches)
    write_review_csv(paths["review"], ready_rows, blocked_rows)

    refreshed_hashes = {
        "schema": "repo-metadata-patch-hashes/v1",
        "session": session,
        "source_session": "S0147",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "canon_before_sha256_old": source_hashes.get("canon_before_sha256", ""),
        "canon_before_sha256": current_canon_sha,
        "patch_preview_sha256": file_sha256(paths["patch_preview"]),
        "review_batches_sha256": file_sha256(paths["review_batches"]),
        "source_patch_preview_sha256": source_hashes.get("patch_preview_sha256", ""),
        "source_review_batches_sha256": source_hashes.get("review_batches_sha256", ""),
        "relations_generated": False,
        "candidate_relations_generated": False,
    }
    write_json(paths["patch_hashes"], refreshed_hashes)

    report = {
        "schema": "repo-metadata-s0150-refresh-report/v1",
        "session": session,
        "source_session": "S0147",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "source_patch_operations": len(source_rows),
        "operations_preserved": len(ready_rows),
        "operations_blocked": len(blocked_rows),
        "canon_before_sha256_old": source_hashes.get("canon_before_sha256", ""),
        "canon_before_sha256_refreshed": current_canon_sha,
        "patch_preview_sha256_refreshed": refreshed_hashes["patch_preview_sha256"],
        "review_batches_sha256_refreshed": refreshed_hashes["review_batches_sha256"],
        "preserved_by_batch": dict(sorted(Counter(str(row.get("batch_id") or "") for row in ready_rows).items())),
        "blocked_by_batch": dict(sorted(Counter(str(row.get("batch_id") or "") for row in blocked_rows).items())),
        "block_reason_counts": dict(sorted(reason_counter.items())),
        "relations_generated": False,
        "formal_relation_candidates_generated": False,
        "candidate_relations_generated": False,
        "metadata_applied": False,
    }
    write_json(paths["report"], report)
    paths["summary"].write_text(summary_md(report), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh S0147 repo metadata patch against current canon")
    parser.add_argument("--patch-preview", default=str(DEFAULT_S0147_DIR / "s0147_repo_metadata_patch_preview.jsonl"))
    parser.add_argument("--review-batches", default=str(DEFAULT_S0147_DIR / "s0147_repo_metadata_review_batches.json"))
    parser.add_argument("--patch-hashes", default=str(DEFAULT_S0147_DIR / "s0147_repo_metadata_patch_hashes.json"))
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--session", default="S0150")
    parser.add_argument("--dry-run", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = refresh_metadata_patch(
        patch_preview=Path(args.patch_preview),
        review_batches=Path(args.review_batches),
        patch_hashes=Path(args.patch_hashes),
        canon_glob=args.canon_glob,
        out_dir=Path(args.out_dir),
        session=str(args.session).upper(),
        dry_run=args.dry_run,
    )
    print(stable_json(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
