#!/usr/bin/env python3
"""Mirror data/out/local/ to data/out/remote/ for remote agent consumption.

Replicates LOCAL_SYNC_SOURCE (default: data/out/local/) into
data/out/remote/, preserving the directory tree. The remote directory is
never the live canon; it is a prepared read-only projection.

Env vars honored:
  LOCAL_SYNC_SOURCE   override source root (default: data/out/local/)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_governance import (  # noqa: E402
    DEFAULT_LOCAL_OUT_DIR,
    DEFAULT_REMOTE_OUT_DIR,
    as_display_path,
    resolve_repo_path,
)

# Subdirectory names that are always excluded from mirroring.
# These contain ephemeral build artefacts or temp state not useful remotely.
_DEFAULT_EXCLUDE: frozenset[str] = frozenset()


@dataclass
class MirrorStats:
    copied: int = 0
    skipped_unchanged: int = 0
    deleted: int = 0
    errors: list[str] = field(default_factory=list)


def _file_digest(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _needs_sync(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    if src.stat().st_size != dst.stat().st_size:
        return True
    return _file_digest(src) != _file_digest(dst)


def mirror(
    src_root: Path,
    dst_root: Path,
    *,
    dry_run: bool,
    exclude_dirs: frozenset[str],
    prune_orphans: bool,
    verbose: bool,
) -> MirrorStats:
    stats = MirrorStats()
    if not dry_run:
        dst_root.mkdir(parents=True, exist_ok=True)

    seen_dst: set[Path] = set()

    for src_file in sorted(src_root.rglob("*")):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src_root)
        if any(part in exclude_dirs for part in rel.parts):
            continue

        dst_file = dst_root / rel
        seen_dst.add(dst_file)

        if _needs_sync(src_file, dst_file):
            if verbose or dry_run:
                label = "[dry-run] " if dry_run else ""
                print(f"  {label}copy  {as_display_path(src_file)}")
            if not dry_run:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(src_file, dst_file)
                    stats.copied += 1
                except OSError as exc:
                    stats.errors.append(f"{src_file}: {exc}")
            else:
                stats.copied += 1
        else:
            stats.skipped_unchanged += 1

    if prune_orphans:
        for dst_file in sorted(dst_root.rglob("*")):
            if dst_file.is_file() and dst_file not in seen_dst:
                if verbose or dry_run:
                    label = "[dry-run] " if dry_run else ""
                    print(f"  {label}prune {as_display_path(dst_file)}")
                if not dry_run:
                    dst_file.unlink()
                stats.deleted += 1

    return stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mirror data/out/local/ → data/out/remote/ for remote agent consumption."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be copied without writing anything.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Source root to mirror (default: LOCAL_SYNC_SOURCE env or data/out/local/).",
    )
    parser.add_argument(
        "--dest",
        default=None,
        help="Destination root (default: data/out/remote/).",
    )
    parser.add_argument(
        "--exclude",
        metavar="DIR",
        action="append",
        default=[],
        help="Subdirectory name to exclude (repeatable, matches at any depth).",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove files in dest that no longer exist in source.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="Emit a JSON summary instead of human-readable output.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print each file action (implied by --dry-run).",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    src_env = os.environ.get("LOCAL_SYNC_SOURCE")
    src_root = resolve_repo_path(args.source or src_env, DEFAULT_LOCAL_OUT_DIR)
    dst_root = resolve_repo_path(args.dest, DEFAULT_REMOTE_OUT_DIR)

    if not src_root.exists():
        print(f"error: source does not exist: {src_root}", file=sys.stderr)
        return 1

    exclude = _DEFAULT_EXCLUDE | frozenset(args.exclude)

    if args.dry_run or args.verbose:
        print(f"source : {as_display_path(src_root)}")
        print(f"dest   : {as_display_path(dst_root)}")
        if args.dry_run:
            print("mode   : dry-run (no files written)")
        print()

    stats = mirror(
        src_root,
        dst_root,
        dry_run=args.dry_run,
        exclude_dirs=exclude,
        prune_orphans=args.prune,
        verbose=args.verbose,
    )

    summary = {
        "source": as_display_path(src_root),
        "dest": as_display_path(dst_root),
        "dry_run": args.dry_run,
        "copied": stats.copied,
        "skipped_unchanged": stats.skipped_unchanged,
        "deleted": stats.deleted,
        "errors": stats.errors,
    }

    if args.json_out:
        print(json.dumps(summary, indent=2))
    else:
        action = "would copy" if args.dry_run else "copied"
        parts = [f"{action}: {stats.copied}", f"unchanged: {stats.skipped_unchanged}"]
        if args.prune:
            parts.append(f"pruned: {stats.deleted}")
        if stats.errors:
            parts.append(f"errors: {len(stats.errors)}")
        print("\n" + "  ".join(parts))
        for err in stats.errors:
            print(f"  error: {err}", file=sys.stderr)

    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(main())
