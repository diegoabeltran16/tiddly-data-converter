#!/usr/bin/env python3
"""Validate machine-readable corpus governance against the local repository."""

from __future__ import annotations

import argparse
import json
import sys

from corpus_governance import (
    load_canon_policy_bundle,
    load_layer_registry,
    validate_repository_alignment,
)
from path_governance import DEFAULT_AI_DIR, DEFAULT_CANON_DIR, as_display_path, resolve_repo_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate corpus_state governance, layer authority and lineage."
    )
    parser.add_argument(
        "--canon-dir",
        default=as_display_path(DEFAULT_CANON_DIR),
        help="Directory containing canon shards (default: data/out/local)",
    )
    parser.add_argument(
        "--ai-dir",
        default=as_display_path(DEFAULT_AI_DIR),
        help="Directory containing AI layer shards (default: data/out/local/ai)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    canon_dir = resolve_repo_path(args.canon_dir, DEFAULT_CANON_DIR)
    ai_dir = resolve_repo_path(args.ai_dir, DEFAULT_AI_DIR)
    report = validate_repository_alignment(
        canon_dir=canon_dir,
        ai_dir=ai_dir,
        bundle=load_canon_policy_bundle(),
        registry=load_layer_registry(),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())

