#!/usr/bin/env python3
"""CLI for the S0144 deterministic semantic_text sidecar build."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from semantic_text_builder import (
    DEFAULT_CANON_GLOB,
    DEFAULT_MAX_CONTENT_CHARS,
    DEFAULT_OUT_DIR,
    DEFAULT_PATCH_PREVIEW_GLOB,
    DEFAULT_DRY_RUN_READY_GLOB,
    DEFAULT_SESSION,
    DEFAULT_TYPE_POLICY,
    build_semantic_text_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build deterministic semantic_text records as a dry-run derived sidecar.",
    )
    parser.add_argument(
        "--canon-glob",
        default=DEFAULT_CANON_GLOB,
        help="Glob for canon shards. Defaults to data/out/local/tiddlers_*.jsonl.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="Output directory for S0144 semantic_text artifacts.",
    )
    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help="Session label used in output filenames. Default: s0144.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Accepted for explicitness. This command is always dry-run and has no apply mode.",
    )
    parser.add_argument(
        "--type-policy",
        default=str(DEFAULT_TYPE_POLICY),
        help="S0139 relation type policy JSON.",
    )
    parser.add_argument(
        "--dry-run-ready-glob",
        default=DEFAULT_DRY_RUN_READY_GLOB,
        help="Glob for admission_ready_dry_run reports to count as excluded previews.",
    )
    parser.add_argument(
        "--patch-preview-glob",
        default=DEFAULT_PATCH_PREVIEW_GLOB,
        help="Glob for admission_patch_preview reports to count as excluded previews.",
    )
    parser.add_argument(
        "--max-content-chars-per-section",
        type=int,
        default=DEFAULT_MAX_CONTENT_CHARS,
        help="Deterministic truncation limit for long text/source_fields sections.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("semantic_text build is always dry-run")

    result = build_semantic_text_outputs(
        canon_glob=args.canon_glob,
        out_dir=Path(args.out_dir),
        session=args.session,
        type_policy=Path(args.type_policy),
        dry_run_ready_glob=args.dry_run_ready_glob,
        patch_preview_glob=args.patch_preview_glob,
        max_content_chars=args.max_content_chars_per_section,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
