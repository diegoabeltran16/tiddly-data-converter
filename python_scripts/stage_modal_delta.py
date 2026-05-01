#!/usr/bin/env python3
"""Stage a controlled modal delta between live canon and a normalized copy."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_governance import (
    DEFAULT_CANON_DIR,
    DEFAULT_INPUT_HTML,
    REPO_ROOT,
    as_display_path,
    resolve_repo_path,
    sorted_canon_shards,
)


SESSION_ID = "m04-s77-canonical-staging-and-controlled-modal-admission-v0"
DEFAULT_NORMALIZED_JSONL = REPO_ROOT / "data" / "tmp" / "s76-modal-export" / "local-normalized-modal.jsonl"
DEFAULT_REPORT_ROOT = REPO_ROOT / "data" / "tmp" / "s77-modal-admission"


@dataclass
class JsonlRecord:
    source_path: Path
    shard: str
    line_no: int
    record: dict[str, Any]


@dataclass
class CommandResult:
    args: list[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str

    def to_report(self) -> dict[str, Any]:
        return {
            "command": " ".join(self.args),
            "cwd": as_display_path(self.cwd),
            "exit_code": self.returncode,
            "stdout_tail": self.stdout[-4000:],
            "stderr_tail": self.stderr[-4000:],
        }


def stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canon_tree_manifest(canon_dir: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    shards = sorted_canon_shards(canon_dir)
    shard_reports: list[dict[str, Any]] = []
    for shard in shards:
        data = shard.read_bytes()
        digest.update(shard.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
        line_count = sum(1 for line in data.decode("utf-8").splitlines() if line.strip())
        shard_reports.append(
            {
                "path": as_display_path(shard),
                "name": shard.name,
                "line_count": line_count,
                "byte_count": len(data),
                "sha256": f"sha256:{hashlib.sha256(data).hexdigest()}",
            }
        )
    return {
        "root": as_display_path(canon_dir),
        "hash": f"sha256:{digest.hexdigest()}",
        "shard_count": len(shards),
        "line_count": sum(item["line_count"] for item in shard_reports),
        "byte_count": sum(item["byte_count"] for item in shard_reports),
        "shards": shard_reports,
    }


def read_jsonl_file(path: Path, shard_name: str | None = None) -> list[JsonlRecord]:
    records: list[JsonlRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{as_display_path(path)}:{line_no} is not a JSON object")
            records.append(JsonlRecord(path, shard_name or path.name, line_no, payload))
    return records


def read_canon_dir(canon_dir: Path) -> list[JsonlRecord]:
    shards = sorted_canon_shards(canon_dir)
    if not shards:
        raise ValueError(f"no tiddlers_*.jsonl files under {as_display_path(canon_dir)}")
    records: list[JsonlRecord] = []
    for shard in shards:
        records.extend(read_jsonl_file(shard, shard.name))
    return records


def index_by_id(records: list[JsonlRecord], label: str) -> dict[str, JsonlRecord]:
    indexed: dict[str, JsonlRecord] = {}
    for item in records:
        record_id = str(item.record.get("id") or "")
        if not record_id:
            raise ValueError(f"{label} has a record without id at {as_display_path(item.source_path)}:{item.line_no}")
        if record_id in indexed:
            first = indexed[record_id]
            raise ValueError(
                f"{label} repeats id {record_id} at "
                f"{as_display_path(first.source_path)}:{first.line_no} and "
                f"{as_display_path(item.source_path)}:{item.line_no}"
            )
        indexed[record_id] = item
    return indexed


def content_asset_present(record: dict[str, Any]) -> bool:
    content = record.get("content")
    return isinstance(content, dict) and isinstance(content.get("asset"), dict)


def select_asset_content_delta(live: dict[str, Any], normalized: dict[str, Any]) -> bool:
    if live.get("role_primary") != "asset":
        return False
    if content_asset_present(live):
        return False
    if not content_asset_present(normalized):
        return False
    return live.get("content") != normalized.get("content")


def compare_and_stage(
    canon_dir: Path,
    normalized_jsonl: Path,
    out_dir: Path,
    *,
    scope: str,
) -> dict[str, Any]:
    live_records = read_canon_dir(canon_dir)
    normalized_records = read_jsonl_file(normalized_jsonl)
    live_by_id = index_by_id(live_records, "canon")
    normalized_by_id = index_by_id(normalized_records, "normalized")

    missing_in_normalized = sorted(set(live_by_id) - set(normalized_by_id))
    extra_in_normalized = sorted(set(normalized_by_id) - set(live_by_id))
    if missing_in_normalized or extra_in_normalized:
        raise ValueError(
            "canon and normalized copy do not have the same id set "
            f"(missing={len(missing_in_normalized)}, extra={len(extra_in_normalized)})"
        )

    field_change_counts: Counter[str] = Counter()
    role_change_counts: Counter[str] = Counter()
    diffset_counts: Counter[tuple[str, ...]] = Counter()
    normalized_tags_changes = 0
    changed_line_count = 0
    selected_by_id: dict[str, dict[str, Any]] = {}
    patch_records: list[dict[str, Any]] = []

    for live_item in live_records:
        record_id = str(live_item.record["id"])
        normalized_item = normalized_by_id[record_id]
        live = live_item.record
        normalized = normalized_item.record
        changed_fields = tuple(sorted(field for field in set(live) | set(normalized) if live.get(field) != normalized.get(field)))
        if not changed_fields:
            continue
        changed_line_count += 1
        field_change_counts.update(changed_fields)
        role_change_counts.update([str(live.get("role_primary") or "")])
        diffset_counts.update([changed_fields])
        if "normalized_tags" in changed_fields:
            normalized_tags_changes += 1

        if scope == "asset-content" and select_asset_content_delta(live, normalized):
            staged = copy.deepcopy(live)
            staged["content"] = copy.deepcopy(normalized.get("content"))
            selected_by_id[record_id] = staged
            patch_records.append(
                {
                    "op": "replace_content",
                    "scope": scope,
                    "id": record_id,
                    "title": live.get("title"),
                    "role_primary": live.get("role_primary"),
                    "shard": live_item.shard,
                    "line": live_item.line_no,
                    "changed_fields": ["content"],
                    "before": {"content": live.get("content")},
                    "after": {"content": staged.get("content")},
                    "source_normalized": {
                        "path": as_display_path(normalized_jsonl),
                        "line": normalized_item.line_no,
                    },
                }
            )

    staged_canon_dir = out_dir / "staged-canon"
    if staged_canon_dir.exists():
        shutil.rmtree(staged_canon_dir)
    staged_canon_dir.mkdir(parents=True, exist_ok=True)

    for shard in sorted_canon_shards(canon_dir):
        staged_lines: list[str] = []
        for item in read_jsonl_file(shard, shard.name):
            record_id = str(item.record["id"])
            staged = selected_by_id.get(record_id, item.record)
            staged_lines.append(json.dumps(staged, ensure_ascii=False, separators=(",", ":")))
        (staged_canon_dir / shard.name).write_text("\n".join(staged_lines) + "\n", encoding="utf-8")

    patch_path = out_dir / "modal-assets.patch.jsonl"
    write_jsonl(patch_path, patch_records)

    comparison = {
        "canon_line_count": len(live_records),
        "normalized_line_count": len(normalized_records),
        "matched_line_count": len(live_records),
        "changed_line_count": changed_line_count,
        "field_change_counts": dict(sorted(field_change_counts.items())),
        "role_change_counts": dict(sorted(role_change_counts.items())),
        "diffset_counts": [
            {"fields": list(fields), "count": count}
            for fields, count in sorted(diffset_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "normalized_tags_changed_lines": normalized_tags_changes,
    }

    return {
        "report_kind": "canonical_modal_delta_staging",
        "session_id": SESSION_ID,
        "timestamp": iso_now(),
        "scope": scope,
        "canon_modified": False,
        "selection_criteria": [
            "role_primary == asset",
            "live content.asset absent",
            "normalized content.asset present",
            "only the top-level content field is staged",
        ],
        "inputs": {
            "canon_dir": as_display_path(canon_dir),
            "normalized_jsonl": as_display_path(normalized_jsonl),
            "normalized_jsonl_sha256": file_hash(normalized_jsonl),
        },
        "outputs": {
            "out_dir": as_display_path(out_dir),
            "staged_canon_dir": as_display_path(staged_canon_dir),
            "patch_jsonl": as_display_path(patch_path),
            "comparison_report": as_display_path(out_dir / "comparison-report.json"),
        },
        "before": canon_tree_manifest(canon_dir),
        "after": canon_tree_manifest(staged_canon_dir),
        "comparison": comparison,
        "delta": {
            "selected_count": len(patch_records),
            "updated_fields": ["content"] if patch_records else [],
            "ignored_changed_lines": changed_line_count - len(patch_records),
            "candidate_apply_status": "staging_only_not_applied",
            "examples": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "shard": item["shard"],
                    "line": item["line"],
                    "after_content_keys": sorted((item["after"]["content"] or {}).keys()),
                }
                for item in patch_records[:8]
            ],
        },
        "gates": {
            "strict": "not_run",
            "reverse_preflight": "not_run",
            "reverse_authoritative": "not_run",
        },
        "commands_run": [],
    }


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GOCACHE", "/tmp/tdc-go-build")
    return env


def run_command(args: list[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(args, cwd=cwd, env=command_env(), check=False, capture_output=True, text=True)
    return CommandResult(args=args, cwd=cwd, returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def parse_stdout_json(stdout: str) -> Any:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def run_gates(report: dict[str, Any], html_path: Path) -> None:
    staged_canon_dir = REPO_ROOT / report["outputs"]["staged_canon_dir"]
    reverse_html = Path("/tmp") / f"{Path(report['outputs']['out_dir']).name}.reverse.html"
    reverse_report = Path("/tmp") / f"{Path(report['outputs']['out_dir']).name}.reverse-report.json"

    strict = run_command(
        ["go", "run", "./cmd/canon_preflight", "--mode", "strict", "--input", str(staged_canon_dir)],
        cwd=REPO_ROOT / "go" / "canon",
    )
    reverse_preflight = run_command(
        ["go", "run", "./cmd/canon_preflight", "--mode", "reverse-preflight", "--input", str(staged_canon_dir)],
        cwd=REPO_ROOT / "go" / "canon",
    )
    reverse = run_command(
        [
            "go",
            "run",
            "./cmd/reverse_tiddlers",
            "--html",
            str(html_path),
            "--canon",
            str(staged_canon_dir),
            "--out-html",
            str(reverse_html),
            "--report",
            str(reverse_report),
            "--mode",
            "authoritative-upsert",
        ],
        cwd=REPO_ROOT / "go" / "bridge",
    )

    reverse_payload: dict[str, Any] | None = None
    if reverse_report.exists():
        with reverse_report.open("r", encoding="utf-8") as handle:
            reverse_payload = json.load(handle)
    reverse_rejected = None
    if isinstance(reverse_payload, dict):
        raw_rejected = reverse_payload.get("rejected_count", reverse_payload.get("rejected"))
        try:
            reverse_rejected = int(raw_rejected)
        except (TypeError, ValueError):
            reverse_rejected = None

    report["gates"] = {
        "strict": "passed" if strict.returncode == 0 else "failed",
        "reverse_preflight": "passed" if reverse_preflight.returncode == 0 else "failed",
        "reverse_authoritative": "passed" if reverse.returncode == 0 and reverse_rejected == 0 else "failed",
        "reverse_rejected": reverse_rejected,
        "reverse_report": str(reverse_report),
        "reverse_html": str(reverse_html),
    }
    report["commands_run"].extend([strict.to_report(), reverse_preflight.to_report(), reverse.to_report()])
    report["gate_reports"] = {
        "strict": parse_stdout_json(strict.stdout),
        "reverse_preflight": parse_stdout_json(reverse_preflight.stdout),
        "reverse_authoritative": reverse_payload,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canon-dir", default=str(DEFAULT_CANON_DIR), help="live canon shard directory")
    parser.add_argument("--normalized-jsonl", default=str(DEFAULT_NORMALIZED_JSONL), help="normalized JSONL copy to compare")
    parser.add_argument("--out-dir", default="", help="output run directory; defaults under data/tmp/s77-modal-admission")
    parser.add_argument("--run-id", default="", help="run id when --out-dir is not provided")
    parser.add_argument("--scope", choices=["asset-content"], default="asset-content")
    parser.add_argument("--run-gates", action="store_true", help="run strict, reverse-preflight and reverse against staged canon")
    parser.add_argument("--html", default=str(DEFAULT_INPUT_HTML), help="HTML source for reverse gate")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    canon_dir = resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR)
    normalized_jsonl = resolve_repo_path(args.normalized_jsonl, DEFAULT_NORMALIZED_JSONL)
    html_path = resolve_repo_path(args.html, DEFAULT_INPUT_HTML)
    run_id = args.run_id or f"s77-modal-assets-{stamp_now()}"
    out_dir = resolve_repo_path(args.out_dir, DEFAULT_REPORT_ROOT / run_id) if args.out_dir else DEFAULT_REPORT_ROOT / run_id

    out_dir.mkdir(parents=True, exist_ok=True)
    report = compare_and_stage(canon_dir, normalized_jsonl, out_dir, scope=args.scope)
    if args.run_gates:
        run_gates(report, html_path)
    report_path = out_dir / "comparison-report.json"
    write_json(report_path, report)
    summary = {
        "status": "ok",
        "report": as_display_path(report_path),
        "patch_jsonl": report["outputs"]["patch_jsonl"],
        "staged_canon_dir": report["outputs"]["staged_canon_dir"],
        "changed_line_count": report["comparison"]["changed_line_count"],
        "selected_count": report["delta"]["selected_count"],
        "canon_modified": False,
        "gates": report["gates"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if args.run_gates and any(report["gates"].get(name) != "passed" for name in ("strict", "reverse_preflight", "reverse_authoritative")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
