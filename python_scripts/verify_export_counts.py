#!/usr/bin/env python3
"""Verify a JSONL export file against schema and manifest.

Checks:
  1. Every non-empty line is valid JSON
  2. Every line has required schema v0 fields: schema_version, key, title
  3. No duplicate keys
  4. Non-empty line count matches manifest exported_count (if manifest provided)
  5. SHA-256 matches manifest sha256 field (if manifest provided)

Exit codes:
  0 — all checks pass
  1 — one or more checks failed

Usage:
  python3 python_scripts/verify_export_counts.py --jsonl <file> [--manifest <file>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _check_valid_json(jsonl_path: Path) -> tuple[int, int]:
    """Return (line_count, invalid_count) counting only non-empty lines."""
    line_count = 0
    invalid_count = 0
    with jsonl_path.open(encoding="utf-8") as fh:
        for i, raw in enumerate(fh, 1):
            stripped = raw.strip()
            if not stripped:
                continue
            line_count += 1
            try:
                json.loads(stripped)
            except json.JSONDecodeError as exc:
                print(f"  Line {i}: {exc}", file=sys.stderr)
                invalid_count += 1
    return line_count, invalid_count


def _check_required_fields(jsonl_path: Path) -> int:
    """Return count of field violations (missing or empty required fields)."""
    count = 0
    with jsonl_path.open(encoding="utf-8") as fh:
        for i, raw in enumerate(fh, 1):
            stripped = raw.strip()
            if not stripped:
                continue
            obj = json.loads(stripped)
            for field in ("schema_version", "key", "title"):
                if field not in obj or not obj[field]:
                    print(f"  Line {i}: missing or empty {field}", file=sys.stderr)
                    count += 1
    return count


def _check_duplicates(jsonl_path: Path) -> int:
    """Return count of duplicate keys."""
    keys: list[str] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            obj = json.loads(stripped)
            keys.append(obj.get("key", ""))
    return len(keys) - len(set(keys))


def _check_manifest(jsonl_path: Path, manifest_path: Path, line_count: int) -> int:
    """Verify line count and SHA-256 against manifest. Return failure count (0-2)."""
    failures = 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest_count = manifest.get("exported_count", -1)
    if line_count != manifest_count:
        print(f"[s33-verify] FAIL: line count ({line_count}) != manifest exported_count ({manifest_count})")
        failures += 1
    else:
        print(f"[s33-verify] ✓ Line count ({line_count}) matches manifest")

    manifest_sha = manifest.get("sha256", "")
    actual_sha = "sha256:" + hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
    if actual_sha != manifest_sha:
        print("[s33-verify] FAIL: SHA-256 mismatch")
        print(f"[s33-verify]   manifest: {manifest_sha}")
        print(f"[s33-verify]   actual:   {actual_sha}")
        failures += 1
    else:
        print("[s33-verify] ✓ SHA-256 matches manifest")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a JSONL export file against schema and optional manifest.",
    )
    parser.add_argument("--jsonl", required=True, help="Path to the JSONL file to verify")
    parser.add_argument("--manifest", default="", help="Path to the manifest JSON file (optional)")
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl)
    if not jsonl_path.is_file():
        print(f"[s33-verify] FAIL: {jsonl_path} does not exist", file=sys.stderr)
        return 1

    failures = 0

    line_count, invalid_count = _check_valid_json(jsonl_path)
    if invalid_count:
        print(f"[s33-verify] FAIL: {invalid_count} lines are not valid JSON")
        failures += 1
    else:
        print(f"[s33-verify] ✓ All {line_count} lines are valid JSON")

    missing_count = _check_required_fields(jsonl_path)
    if missing_count:
        print(f"[s33-verify] FAIL: {missing_count} missing required fields")
        failures += 1
    else:
        print("[s33-verify] ✓ All lines have required schema v0 fields")

    dup_count = _check_duplicates(jsonl_path)
    if dup_count:
        print(f"[s33-verify] FAIL: {dup_count} duplicate keys found")
        failures += 1
    else:
        print("[s33-verify] ✓ No duplicate keys")

    manifest_path = Path(args.manifest) if args.manifest else None
    if manifest_path and manifest_path.is_file():
        failures += _check_manifest(jsonl_path, manifest_path, line_count)
    else:
        print("[s33-verify] WARN: manifest not found, skipping checks 5-6")

    print()
    if failures:
        print(f"[s33-verify] FAILED: {failures} check(s) failed")
        return 1

    print("[s33-verify] ============================================")
    print("[s33-verify] All checks passed ✓")
    print(f"[s33-verify] Lines: {line_count}")
    print("[s33-verify] ============================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
