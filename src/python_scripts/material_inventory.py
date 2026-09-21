#!/usr/bin/env python3
"""S0187 Unit C — consolidated material inventory capability.

Observes the repository's material state (what files exist, their content
hash, size, git status) into a replaceable/rebuildable current inventory,
and compares successive observations to produce durable transition receipts
only when the material state actually changed.

Governing principles (see the S0187 Unit C session directive):
  LOCATION != IDENTITY, HASH != IDENTITY, GIT TRACKED != MATERIAL RELEVANCE,
  INVENTORY != CANON, CURRENT INVENTORY = REPLACEABLE + REBUILDABLE,
  MATERIAL TRANSITION EVIDENCE = DURABLE, OBSERVATION FREQUENCY != HISTORY SIZE.

This module never reads Canon (`data/out/local/tiddlers_*.jsonl`) content and
never writes to it; Canon files are merely observed and classified like any
other artifact. Nothing here admits observations to Canon.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
import sys  # noqa: E402
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
# S0187 Unit D finding: INVENTORY_DIR and TMP_ROOT were hardcoded
# REPO_ROOT-relative literals -- update_inventory() is called from
# operator_menu.py's option 3 (Inventario material / repositorio) with no
# override, so this was a confirmed active writer to the old root. The scan
# ROOT itself (root_locator, the repo checkout) is intentionally unchanged --
# only where the resulting inventory.jsonl/manifest/tmp state materialize.
# Note: moving these off REPO_ROOT means the "data/out/local/inventory" etc.
# self-exclusion patterns below (used while walking the scan root) become
# structurally unreachable rather than load-bearing, since the new
# destination no longer sits inside the tree being scanned -- not a semantic
# change to what gets scanned or how change events are classified.
from path_governance import DEFAULT_LOCAL_OUT_DIR, DEFAULT_TMP_DIR, WORKSPACE_ROOT  # noqa: E402

# S0187 D22: INVENTORY SCOPE != INVENTORY PHYSICAL LOCATION. Two scopes are
# supported by this single engine -- REPOSITORY (root=REPO_ROOT, "what makes
# up the TDC checkout") and WORKSPACE_DATA (root=WORKSPACE_ROOT, "what makes
# up this workspace's out/refs/tmp"). Classification, exclusions and current-
# inventory storage are all scope-parameterized rather than duplicated into a
# second engine.
INVENTORY_SCOPE_REPOSITORY = "repository"
INVENTORY_SCOPE_WORKSPACE_DATA = "workspace_data"

SCHEMA_VERSION = "material-inventory/v1"
SCANNER_COMPONENT = "material_inventory.py"
SCANNER_VERSION = "s0187-unit-c-v1"
CURRENTNESS_SCOPE = "LAST_PERSISTED_OBSERVATION_QUALITY"
INCREMENTAL_VERIFICATION_MODE = "INCREMENTAL_STAT_REUSE"
FULL_VERIFICATION_MODE = "FULL_CONTENT_HASHED_DURING_SCAN"

DEFAULT_ROOT_ID = "repo-main"

INVENTORY_DIR = DEFAULT_LOCAL_OUT_DIR / "inventory"
CURRENT_INVENTORY_PATH = INVENTORY_DIR / "current_inventory.jsonl"
CURRENT_MANIFEST_PATH = INVENTORY_DIR / "current_inventory_manifest.json"
VIEWS_DIR = INVENTORY_DIR / "views"
ASCII_VIEW_PATH = VIEWS_DIR / "estructura.txt"
LOCK_PATH = INVENTORY_DIR / ".inventory.lock"

TRANSITIONS_DIR = DEFAULT_LOCAL_OUT_DIR / "audit" / "material_inventory" / "transitions"

TMP_ROOT = DEFAULT_TMP_DIR / "material_inventory"

# WORKSPACE_DATA scope storage -- a sibling surface, never sharing a path
# with the REPOSITORY scope's storage above, so running one scope can never
# silently clobber the other's current inventory (S0187 D22).
WORKSPACE_DATA_INVENTORY_DIR = DEFAULT_LOCAL_OUT_DIR / "inventory_workspace_data"
WORKSPACE_DATA_CURRENT_INVENTORY_PATH = WORKSPACE_DATA_INVENTORY_DIR / "current_inventory.jsonl"
WORKSPACE_DATA_CURRENT_MANIFEST_PATH = WORKSPACE_DATA_INVENTORY_DIR / "current_inventory_manifest.json"
WORKSPACE_DATA_LOCK_PATH = WORKSPACE_DATA_INVENTORY_DIR / ".inventory.lock"
WORKSPACE_DATA_TRANSITIONS_DIR = DEFAULT_LOCAL_OUT_DIR / "audit" / "material_inventory_workspace_data" / "transitions"
WORKSPACE_DATA_TMP_ROOT = DEFAULT_TMP_DIR / "material_inventory_workspace_data"

# Self-observation exclusions (relative-to-root prefixes, POSIX), keyed by
# scope. Each MUST stay in sync with that scope's own storage constants above
# so the inventory never observes its own receipts (Fase C-06) -- the prefix
# shape differs by scope because it is relative to a different root.
_SELF_OBSERVATION_PREFIXES_BY_SCOPE: dict[str, tuple[str, ...]] = {
    INVENTORY_SCOPE_REPOSITORY: (
        "data/out/local/inventory",
        "data/out/local/audit/material_inventory",
        "data/tmp/material_inventory",
    ),
    INVENTORY_SCOPE_WORKSPACE_DATA: (
        "out/local/inventory",
        "out/local/inventory_workspace_data",
        "out/local/audit/material_inventory",
        "out/local/audit/material_inventory_workspace_data",
        "tmp/material_inventory",
        "tmp/material_inventory_workspace_data",
    ),
}
# Backward-compatible alias: existing callers/tests reading this name get the
# repository-scope tuple unchanged.
_SELF_OBSERVATION_PREFIXES = _SELF_OBSERVATION_PREFIXES_BY_SCOPE[INVENTORY_SCOPE_REPOSITORY]

CHANGE_ADDED = "ADDED"
CHANGE_REMOVED = "REMOVED"
CHANGE_UNCHANGED = "UNCHANGED"
CHANGE_CONTENT_CHANGED = "CONTENT_CHANGED"
CHANGE_METADATA_CHANGED = "METADATA_CHANGED"
CHANGE_POSSIBLE_MOVE = "POSSIBLE_MOVE_OR_RENAME"
CHANGE_POSSIBLE_COPY = "POSSIBLE_COPY"
CHANGE_DUPLICATED_CONTENT = "DUPLICATED_CONTENT"
CHANGE_UNKNOWN = "UNKNOWN_CHANGE"


class MaterialInventoryError(RuntimeError):
    """Raised for fail-closed conditions (inconsistent pair, staging failure)."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


# ---------------------------------------------------------------------------
# Inventory profile (Fase C-02 / P-C-01..P-C-12)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExclusionRule:
    pattern: str
    reason: str
    owner: str
    traversal_policy: str = "PRUNE"


@dataclass(frozen=True)
class InventoryProfile:
    profile_id: str
    root_id: str
    root_locator: str
    exclusions: tuple[ExclusionRule, ...]
    follow_symlinks: bool = False
    scope: str = INVENTORY_SCOPE_REPOSITORY


def default_exclusions(scope: str = INVENTORY_SCOPE_REPOSITORY) -> tuple[ExclusionRule, ...]:
    self_obs = _SELF_OBSERVATION_PREFIXES_BY_SCOPE[scope]
    reason_by_suffix = {
        "inventory": "CONTROL_PLANE_SELF_OBSERVATION_EXCLUSION: inventory's own current state",
        "material_inventory": "CONTROL_PLANE_SELF_OBSERVATION_EXCLUSION: inventory's own transition receipts",
    }
    common = (
        ExclusionRule(".git", "VCS internal metadata, not TDC material", "repo-hygiene"),
        ExclusionRule(
            ".venv",
            "Vendored/installed Python virtualenv, not TDC material "
            "(explicit profile rule -- NOT because it is gitignored, per P-C-03)",
            "repo-hygiene",
        ),
        ExclusionRule("node_modules", "Vendored JS dependency tree, not TDC material", "repo-hygiene"),
    )
    self_rules = tuple(
        ExclusionRule(
            pattern,
            "CONTROL_PLANE_SELF_OBSERVATION_EXCLUSION: inventory's own current state or "
            "working/transition receipts (scope=" + scope + ")",
            "unit-c",
        )
        for pattern in self_obs
    )
    return common + self_rules


def default_profile(root_locator: Path | str | None = None) -> InventoryProfile:
    return InventoryProfile(
        profile_id="default-repo-main-v1",
        root_id=DEFAULT_ROOT_ID,
        root_locator=str(Path(root_locator or REPO_ROOT).resolve()),
        exclusions=default_exclusions(INVENTORY_SCOPE_REPOSITORY),
        scope=INVENTORY_SCOPE_REPOSITORY,
    )


def workspace_data_profile(root_locator: Path | str | None = None) -> InventoryProfile:
    """S0187 D22 -- the WORKSPACE_DATA scope: 'what constitutes this
    workspace materially' (out/refs/tmp), independent of where the
    repository checkout happens to live. Defaults to WORKSPACE_ROOT, the
    same single owner every other workspace-scoped path already uses."""
    return InventoryProfile(
        profile_id="default-workspace-data-v1",
        root_id="workspace-data-main",
        root_locator=str(Path(root_locator or WORKSPACE_ROOT).resolve()),
        exclusions=default_exclusions(INVENTORY_SCOPE_WORKSPACE_DATA),
        scope=INVENTORY_SCOPE_WORKSPACE_DATA,
    )


def compute_profile_hash(profile: InventoryProfile) -> str:
    payload = {
        "profile_id": profile.profile_id,
        "root_id": profile.root_id,
        "follow_symlinks": profile.follow_symlinks,
        "exclusions": [
            {
                "pattern": rule.pattern,
                "reason": rule.reason,
                "owner": rule.owner,
                "traversal_policy": rule.traversal_policy,
            }
            for rule in profile.exclusions
        ],
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _is_excluded(rel_posix: str, exclusions: Sequence[ExclusionRule]) -> ExclusionRule | None:
    for rule in exclusions:
        if rel_posix == rule.pattern or rel_posix.startswith(rule.pattern + "/"):
            return rule
    return None


# ---------------------------------------------------------------------------
# Classification (observed vs interpreted -- Fase C-02 / material classes)
# ---------------------------------------------------------------------------

# S0187 D22: classification prefixes are relative-to-scan-root, so they
# necessarily differ by scope -- REPOSITORY scans from REPO_ROOT (paths look
# like "data/refs/..."), WORKSPACE_DATA scans from WORKSPACE_ROOT (paths look
# like "refs/..."). Same material semantics, different relative shape.
_MATERIAL_CLASS_PREFIXES_BY_SCOPE: dict[str, tuple[tuple[str, dict[str, str]], ...]] = {
    INVENTORY_SCOPE_REPOSITORY: (
        (
            "data/refs/",
            {
                "material_class": "EXTERNAL_REFERENCE",
                "material_owner": "external-source-material",
                "authority_relation": "NONE",
                "reconstructibility": "NOT_REBUILDABLE_BY_TDC",
            },
        ),
        (
            "data/out/local/sessions/",
            {
                "material_class": "SESSION_STATE",
                "material_owner": "session-governance",
                "authority_relation": "NONE",
                "reconstructibility": "DURABLE",
            },
        ),
        (
            "data/out/local/audit/",
            {
                "material_class": "AUDIT_EVIDENCE",
                "material_owner": "audit-governance",
                "authority_relation": "NONE",
                "reconstructibility": "DURABLE",
            },
        ),
        (
            "data/out/local/backups/",
            {
                "material_class": "BACKUP",
                "material_owner": "rollback-governance",
                "authority_relation": "NONE",
                "reconstructibility": "DURABLE",
            },
        ),
        (
            "data/tmp/",
            {
                "material_class": "TEMPORARY",
                "material_owner": "working-state",
                "authority_relation": "NONE",
                "reconstructibility": "REPLACEABLE",
            },
        ),
        (
            "data/out/local/",  # catch-all for remaining derivative families (enriched/ai/pipeline/...)
            {
                "material_class": "DERIVED",
                "material_owner": "rag-derivative-pipeline",
                "authority_relation": "NONE",
                "reconstructibility": "REBUILDABLE_FROM_CANON",
            },
        ),
        (
            "src/",
            {
                "material_class": "SOURCE",
                "material_owner": "engineering",
                "authority_relation": "NONE",
                "reconstructibility": "DURABLE",
            },
        ),
        (
            "tests/",
            {
                "material_class": "SOURCE",
                "material_owner": "engineering",
                "authority_relation": "NONE",
                "reconstructibility": "DURABLE",
            },
        ),
    ),
    INVENTORY_SCOPE_WORKSPACE_DATA: (
        (
            "refs/",
            {
                "material_class": "EXTERNAL_REFERENCE",
                "material_owner": "external-source-material",
                "authority_relation": "NONE",
                "reconstructibility": "NOT_REBUILDABLE_BY_TDC",
            },
        ),
        (
            "out/local/sessions/",
            {
                "material_class": "SESSION_STATE",
                "material_owner": "session-governance",
                "authority_relation": "NONE",
                "reconstructibility": "DURABLE",
            },
        ),
        (
            "out/local/audit/",
            {
                "material_class": "AUDIT_EVIDENCE",
                "material_owner": "audit-governance",
                "authority_relation": "NONE",
                "reconstructibility": "DURABLE",
            },
        ),
        (
            "out/local/backups/",
            {
                "material_class": "BACKUP",
                "material_owner": "rollback-governance",
                "authority_relation": "NONE",
                "reconstructibility": "DURABLE",
            },
        ),
        (
            "tmp/",
            {
                "material_class": "TEMPORARY",
                "material_owner": "working-state",
                "authority_relation": "NONE",
                "reconstructibility": "REPLACEABLE",
            },
        ),
        (
            "out/local/",  # catch-all for remaining derivative families (enriched/ai/pipeline/...)
            {
                "material_class": "DERIVED",
                "material_owner": "rag-derivative-pipeline",
                "authority_relation": "NONE",
                "reconstructibility": "REBUILDABLE_FROM_CANON",
            },
        ),
    ),
}
# Backward-compatible alias for any existing consumer/test reading this name
# directly -- resolves to the repository-scope table, unchanged shape.
_MATERIAL_CLASS_PREFIXES = _MATERIAL_CLASS_PREFIXES_BY_SCOPE[INVENTORY_SCOPE_REPOSITORY]

_CANON_PREFIX_BY_SCOPE: dict[str, str] = {
    INVENTORY_SCOPE_REPOSITORY: "data/out/local/tiddlers_",
    INVENTORY_SCOPE_WORKSPACE_DATA: "out/local/tiddlers_",
}


def classify_material(rel_posix: str, scope: str = INVENTORY_SCOPE_REPOSITORY) -> dict[str, Any]:
    canon_prefix = _CANON_PREFIX_BY_SCOPE[scope]
    if rel_posix.startswith(canon_prefix) and rel_posix.endswith(".jsonl"):
        return {
            "material_class": "CANON",
            "material_owner": "canon-admission-pipeline",
            "authority_relation": "CANONICAL_AUTHORITY",
            "reconstructibility": "DURABLE_NOT_REBUILDABLE_FROM_INVENTORY",
            "classification_basis": "EXPLICIT_GOVERNED_RULE",
            "classification_confidence": "HIGH",
        }
    for prefix, base in _MATERIAL_CLASS_PREFIXES_BY_SCOPE[scope]:
        if rel_posix.startswith(prefix):
            result = dict(base)
            result["classification_basis"] = "EXPLICIT_GOVERNED_RULE"
            result["classification_confidence"] = "HIGH"
            return result
    if rel_posix == ".gitignore" or rel_posix.startswith(".github/"):
        return {
            "material_class": "SOURCE",
            "material_owner": "engineering",
            "authority_relation": "NONE",
            "reconstructibility": "DURABLE",
            "classification_basis": "KNOWN_SURFACE_CONTRACT",
            "classification_confidence": "HIGH",
        }
    if rel_posix == ".env" or rel_posix.endswith("/.env"):
        # S0187 Unit E: previously fell through to UNKNOWN and was hashed
        # (content_hash only, never raw content) with no governing rule.
        # This makes the sensitivity of the material explicit rather than
        # accidental, per S0187 Unit E's "SKIPPED_SENSITIVE_POLICY" handoff.
        return {
            "material_class": "SENSITIVE_MATERIAL",
            "material_owner": "secrets-governance",
            "authority_relation": "NONE",
            "reconstructibility": "NOT_REBUILDABLE_BY_TDC",
            "classification_basis": "EXPLICIT_GOVERNED_RULE",
            "classification_confidence": "HIGH",
        }
    if rel_posix.endswith(".md") or rel_posix.startswith("ux/"):
        return {
            "material_class": "SOURCE",
            "material_owner": "engineering",
            "authority_relation": "NONE",
            "reconstructibility": "DURABLE",
            "classification_basis": "PATH_HEURISTIC",
            "classification_confidence": "MEDIUM",
        }
    return {
        "material_class": "UNKNOWN",
        "material_owner": None,
        "authority_relation": "NONE",
        "reconstructibility": "UNKNOWN",
        "classification_basis": "UNKNOWN",
        "classification_confidence": "LOW",
    }


# ---------------------------------------------------------------------------
# Git boundary (Fase C-09): git_tracked / git_ignored are metadata, never a
# scan filter (P-C-03).
# ---------------------------------------------------------------------------


def _run_git_ls_files_z(root: Path, *extra_args: str) -> set[str]:
    # -z (NUL-delimited, unquoted paths) is required: git's default output
    # quotes/escapes any path containing non-ASCII bytes (accents, etc.),
    # which would silently break exact relative_path membership checks for
    # e.g. many real filenames under data/refs/.
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", *extra_args],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return set()
    if out.returncode != 0:
        return set()
    raw = out.stdout.split(b"\x00")
    return {chunk.decode("utf-8", errors="surrogateescape") for chunk in raw if chunk}


def _git_tracked_set(root: Path) -> set[str]:
    return _run_git_ls_files_z(root)


def _git_ignored_paths(root: Path, candidate_rel_paths: Sequence[str]) -> set[str]:
    # `git ls-files --others --ignored` refuses to descend into a directory
    # that itself contains a nested `.git` (an embedded/foreign repo, as seen
    # under several data/refs/<n>. <project>/ subtrees) -- it treats that as
    # a repository boundary and silently omits everything inside, regardless
    # of .gitignore. `check-ignore` has no such blind spot: it is pure
    # pattern matching against the path, so a single batched call over every
    # candidate path (fed via -z/stdin to dodge quoting) is both correct
    # across those boundaries and O(1) subprocess calls rather than O(N).
    if not candidate_rel_paths:
        return set()
    payload = b"\x00".join(p.encode("utf-8", errors="surrogateescape") for p in candidate_rel_paths) + b"\x00"
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--stdin", "-z", "--no-index"],
            input=payload,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return set()
    # exit 0 = at least one match, 1 = none matched (both are normal
    # outcomes for us); >1 signals a real invocation error.
    if proc.returncode not in (0, 1):
        return set()
    raw = proc.stdout.split(b"\x00")
    return {chunk.decode("utf-8", errors="surrogateescape") for chunk in raw if chunk}


# ---------------------------------------------------------------------------
# Hashing (Fase C-03): streaming, SHA-256, hash is never identity.
# ---------------------------------------------------------------------------


def sha256_stream(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class ScanStats:
    artifact_count: int = 0
    total_size_bytes: int = 0
    hashed_count: int = 0
    hash_reused_count: int = 0
    hash_error_count: int = 0
    classification_counts: dict[str, int] = field(default_factory=dict)


def _build_record(
    full_path: Path,
    rel_posix: str,
    tracked: set[str],
    ignored: set[str],
    previous: Mapping[str, Any] | None,
    full_verify: bool,
    scope: str = INVENTORY_SCOPE_REPOSITORY,
) -> dict[str, Any]:
    classification = classify_material(rel_posix, scope)
    # S0187 Unit E (D-handoff, human decision ENV_POLICY_DECISION=CLASSIFY_AND_SKIP_HASH):
    # sensitivity is known here, BEFORE any content read is attempted, so the
    # sensitive branch below never calls sha256_stream()/os.readlink() -- the
    # required property is "sensitive file content is not read for hashing",
    # not merely "content_hash is nulled out after having read the file".
    is_sensitive = classification["material_class"] == "SENSITIVE_MATERIAL"
    observation_error: str | None = None
    content_hash: str | None = None
    hash_status = "UNKNOWN"
    size_bytes: int | None = None
    mtime_ns: int | None = None
    mode: int | None = None
    symlink_target: str | None = None
    is_symlink = full_path.is_symlink()
    object_type = "symlink" if is_symlink else ("directory" if full_path.is_dir() else "file")

    try:
        st = full_path.lstat()
        mtime_ns = st.st_mtime_ns
        mode = st.st_mode & 0o777
        size_bytes = st.st_size
        if is_sensitive:
            content_hash = None
            hash_status = "SKIPPED_SENSITIVE_POLICY"
        elif is_symlink:
            symlink_target = os.readlink(full_path)
            content_hash = hashlib.sha256(symlink_target.encode("utf-8")).hexdigest()
            hash_status = "COMPUTED"
        else:
            reuse_ok = (
                not full_verify
                and previous is not None
                and previous.get("content_hash")
                and previous.get("object_type") == object_type
                and previous.get("size_bytes") == size_bytes
                and previous.get("mtime_ns") == mtime_ns
            )
            if reuse_ok:
                content_hash = previous["content_hash"]
                hash_status = "REUSED_FROM_PREVIOUS_OBSERVATION"
            else:
                content_hash = sha256_stream(full_path)
                hash_status = "COMPUTED"
    except OSError as exc:
        observation_error = str(exc)
        hash_status = "ERROR"

    return {
        "schema_version": SCHEMA_VERSION,
        "root_id": DEFAULT_ROOT_ID,
        "relative_path": rel_posix,
        "object_type": object_type,
        "size_bytes": size_bytes,
        "content_hash": content_hash,
        "hash_algorithm": "sha256" if content_hash else None,
        "hash_status": hash_status,
        "mtime_ns": mtime_ns,
        "mode": mode,
        "git_tracked": rel_posix in tracked,
        "git_ignored": rel_posix in ignored,
        "symlink_target": symlink_target,
        "material_class": classification["material_class"],
        "material_owner": classification["material_owner"],
        "authority_relation": classification["authority_relation"],
        "reconstructibility": classification["reconstructibility"],
        "classification_basis": classification["classification_basis"],
        "classification_confidence": classification["classification_confidence"],
        "observation_error": observation_error,
    }


def _accumulate(record: dict[str, Any], records: list[dict[str, Any]], stats: ScanStats) -> None:
    records.append(record)
    stats.artifact_count += 1
    if record["size_bytes"]:
        stats.total_size_bytes += record["size_bytes"]
    if record["hash_status"] == "COMPUTED":
        stats.hashed_count += 1
    elif record["hash_status"] == "REUSED_FROM_PREVIOUS_OBSERVATION":
        stats.hash_reused_count += 1
    if record["observation_error"]:
        stats.hash_error_count += 1
    cls = record["material_class"]
    stats.classification_counts[cls] = stats.classification_counts.get(cls, 0) + 1


def _collect_candidates(root: Path, exclusions: Sequence[ExclusionRule]) -> list[tuple[str, Path]]:
    """First pass: walk the tree, apply PRUNE exclusions, and return every
    in-scope (relative_path, full_path) pair (files + symlinked dirs) without
    touching content -- cheap enough to precede the git-ignore batch query
    and the hashing pass without meaningfully affecting scan wall time.
    """

    candidates: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dir_rel = Path(dirpath).relative_to(root).as_posix()
        if dir_rel == ".":
            dir_rel = ""
        pruned = []
        for dname in list(dirnames):
            child_rel = f"{dir_rel}/{dname}" if dir_rel else dname
            rule = _is_excluded(child_rel, exclusions)
            if rule is not None and rule.traversal_policy == "PRUNE":
                pruned.append(dname)
                continue
            child_path = Path(dirpath) / dname
            if child_path.is_symlink():
                # os.walk(followlinks=False) lists a symlinked dir in
                # dirnames but never descends into it -- record it as the
                # symlink object it is, then keep it out of dirnames so it
                # is not silently dropped nor mistaken for a real dir.
                candidates.append((child_rel, child_path))
                pruned.append(dname)
        for dname in pruned:
            dirnames.remove(dname)

        for name in sorted(filenames):
            rel_posix = f"{dir_rel}/{name}" if dir_rel else name
            if _is_excluded(rel_posix, exclusions) is not None:
                continue
            candidates.append((rel_posix, Path(dirpath) / name))
    return candidates


def scan_material(
    profile: InventoryProfile,
    *,
    previous_records_by_path: Mapping[str, Mapping[str, Any]] | None = None,
    full_verify: bool = False,
) -> tuple[list[dict[str, Any]], ScanStats]:
    root = Path(profile.root_locator)
    previous_records_by_path = previous_records_by_path or {}

    candidates = _collect_candidates(root, profile.exclusions)
    tracked = _git_tracked_set(root)
    ignored = _git_ignored_paths(root, [rel for rel, _path in candidates])

    records: list[dict[str, Any]] = []
    stats = ScanStats()
    for rel_posix, full_path in candidates:
        record = _build_record(
            full_path,
            rel_posix,
            tracked,
            ignored,
            previous_records_by_path.get(rel_posix),
            full_verify,
            profile.scope,
        )
        _accumulate(record, records, stats)

    records.sort(key=lambda r: (r["root_id"], r["relative_path"]))
    return records, stats


# ---------------------------------------------------------------------------
# Snapshot identity (material_state_hash / snapshot_id). observed_at NEVER
# participates (P-C-... / two no-op scans must share a snapshot_id).
# ---------------------------------------------------------------------------

_HASHED_RECORD_FIELDS = (
    "root_id",
    "relative_path",
    "object_type",
    "size_bytes",
    "content_hash",
    "hash_algorithm",
    "mtime_ns",
    "mode",
    "git_tracked",
    "git_ignored",
)


def _canonical_record_for_hash(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in _HASHED_RECORD_FIELDS}


def compute_material_state_hash(records: Sequence[Mapping[str, Any]]) -> str:
    canonical = [_canonical_record_for_hash(r) for r in records]
    return hashlib.sha256(_canonical_json(canonical)).hexdigest()


def compute_snapshot_id(material_state_hash: str, profile_hash: str) -> str:
    return hashlib.sha256(f"{material_state_hash}:{profile_hash}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Change detection (Fase C-04)
# ---------------------------------------------------------------------------


def detect_changes(
    previous_records: Sequence[Mapping[str, Any]],
    current_records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    prev_by_path = {r["relative_path"]: r for r in previous_records}
    curr_by_path = {r["relative_path"]: r for r in current_records}
    prev_paths = set(prev_by_path)
    curr_paths = set(curr_by_path)

    events: list[dict[str, Any]] = []
    counts = {
        "added_count": 0,
        "removed_count": 0,
        "content_changed_count": 0,
        "metadata_changed_count": 0,
        "unchanged_count": 0,
        "possible_move_count": 0,
        "possible_copy_count": 0,
        "duplicate_content_count": 0,
        "unknown_count": 0,
    }

    for path in sorted(prev_paths & curr_paths):
        before, after = prev_by_path[path], curr_by_path[path]
        if after.get("observation_error"):
            events.append(
                {
                    "change_type": CHANGE_UNKNOWN,
                    "relative_path": path,
                    "before": before,
                    "after": after,
                    "changed_fields": ["observation_error"],
                }
            )
            counts["unknown_count"] += 1
        elif before.get("content_hash") != after.get("content_hash"):
            events.append(
                {
                    "change_type": CHANGE_CONTENT_CHANGED,
                    "relative_path": path,
                    "before": before,
                    "after": after,
                    "changed_fields": ["content_hash"],
                }
            )
            counts["content_changed_count"] += 1
        else:
            # Every same-path field that participates in material_state_hash
            # must have a causal representation in the full diff.  Otherwise
            # check_status could report CHANGES_DETECTED while returning no
            # event that explains the changed snapshot.
            metadata_fields = tuple(
                field for field in _HASHED_RECORD_FIELDS if field not in {"relative_path", "content_hash"}
            )
            changed_fields = [field for field in metadata_fields if before.get(field) != after.get(field)]
            if not changed_fields:
                counts["unchanged_count"] += 1
                continue
            events.append(
                {
                    "change_type": CHANGE_METADATA_CHANGED,
                    "relative_path": path,
                    "before": before,
                    "after": after,
                    "changed_fields": changed_fields,
                }
            )
            counts["metadata_changed_count"] += 1

    removed_only = sorted(prev_paths - curr_paths)
    added_only = sorted(curr_paths - prev_paths)

    # Hashes that still survive somewhere in the current tree under an
    # unchanged/renamed-in-place path -- these disqualify a move inference
    # (content still exists at a known path => any new appearance is a copy,
    # not a move) per P-C-11 / "no inferir move automáticamente" ambiguity rule.
    surviving_hashes: dict[str, list[str]] = {}
    for path in sorted(prev_paths & curr_paths):
        h = curr_by_path[path].get("content_hash")
        if h:
            surviving_hashes.setdefault(h, []).append(path)

    removed_by_hash: dict[str, list[str]] = {}
    for path in removed_only:
        h = prev_by_path[path].get("content_hash")
        if h:
            removed_by_hash.setdefault(h, []).append(path)
    added_by_hash: dict[str, list[str]] = {}
    for path in added_only:
        h = curr_by_path[path].get("content_hash")
        if h:
            added_by_hash.setdefault(h, []).append(path)

    matched_removed: set[str] = set()
    matched_added: set[str] = set()

    move_events: list[dict[str, Any]] = []
    for h, removed_paths in sorted(removed_by_hash.items()):
        added_paths = added_by_hash.get(h, [])
        if h in surviving_hashes:
            continue  # content still exists elsewhere -> copy territory, not a move
        if len(removed_paths) == 1 and len(added_paths) == 1:
            old_path, new_path = removed_paths[0], added_paths[0]
            old_rec, new_rec = prev_by_path[old_path], curr_by_path[new_path]
            if old_rec.get("size_bytes") == new_rec.get("size_bytes") and old_rec.get(
                "object_type"
            ) == new_rec.get("object_type"):
                move_events.append(
                    {
                        "change_type": CHANGE_POSSIBLE_MOVE,
                        "old_relative_path": old_path,
                        "new_relative_path": new_path,
                        "confidence": "HIGH",
                        "evidence": (
                            "unique matching content_hash, size_bytes and object_type between "
                            "exactly one removed path and one added path; hash does not survive "
                            "at any other current path (inference, not proven identity)"
                        ),
                        "before": old_rec,
                        "after": new_rec,
                    }
                )
                matched_removed.add(old_path)
                matched_added.add(new_path)

    copy_events: list[dict[str, Any]] = []
    for path in added_only:
        if path in matched_added:
            continue
        h = curr_by_path[path].get("content_hash")
        sources = surviving_hashes.get(h, []) if h else []
        if sources:
            copy_events.append(
                {
                    "change_type": CHANGE_POSSIBLE_COPY,
                    "source_candidate_paths": sources,
                    "new_relative_path": path,
                    "confidence": "MEDIUM",
                    "evidence": (
                        f"new path shares content_hash with {len(sources)} still-present "
                        "path(s); source continues to exist, so this is a copy inference, "
                        "not a proven identity relation"
                    ),
                    "after": curr_by_path[path],
                }
            )
            matched_added.add(path)

    for path in removed_only:
        if path not in matched_removed:
            events.append({"change_type": CHANGE_REMOVED, "relative_path": path, "before": prev_by_path[path]})
            counts["removed_count"] += 1
    for path in added_only:
        if path not in matched_added:
            events.append({"change_type": CHANGE_ADDED, "relative_path": path, "after": curr_by_path[path]})
            counts["added_count"] += 1

    for ev in move_events:
        events.append(ev)
        counts["possible_move_count"] += 1
    for ev in copy_events:
        events.append(ev)
        counts["possible_copy_count"] += 1

    # DUPLICATED_CONTENT: informational, additive -- same hash at 2+ current
    # paths. Does not replace any of the events already emitted above.
    hash_to_current_paths: dict[str, list[str]] = {}
    for r in current_records:
        h = r.get("content_hash")
        if h:
            hash_to_current_paths.setdefault(h, []).append(r["relative_path"])
    for h, paths in sorted(hash_to_current_paths.items()):
        if len(paths) > 1:
            events.append(
                {
                    "change_type": CHANGE_DUPLICATED_CONTENT,
                    "content_hash": h,
                    "relative_paths": sorted(paths),
                }
            )
            counts["duplicate_content_count"] += 1

    events.sort(key=lambda e: (e["change_type"], e.get("relative_path") or e.get("new_relative_path") or ""))
    return events, counts


def _receipt_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    # Durable receipts never carry UNCHANGED rows (P-C-06/P-C-08: no inflation).
    return [ev for ev in events if ev["change_type"] != CHANGE_UNCHANGED]


# ---------------------------------------------------------------------------
# Manifest + transition receipts (Fase C-05)
# ---------------------------------------------------------------------------


def build_manifest(
    *,
    profile: InventoryProfile,
    profile_hash: str,
    stats: ScanStats,
    snapshot_id: str,
    material_state_hash: str,
    previous_snapshot_id: str | None,
    latest_transition_id: str | None,
    currentness_level: str,
) -> dict[str, Any]:
    observed_at = _utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory_profile_id": profile.profile_id,
        "inventory_profile_hash": profile_hash,
        "snapshot_id": snapshot_id,
        "material_state_hash": material_state_hash,
        "observed_at": observed_at,
        "last_observed_at": observed_at,
        "root_id": profile.root_id,
        "root_locator": profile.root_locator,
        "inventory_scope": profile.scope,
        "artifact_count": stats.artifact_count,
        "total_size_bytes": stats.total_size_bytes,
        "hashed_count": stats.hashed_count,
        "hash_reused_count": stats.hash_reused_count,
        "hash_error_count": stats.hash_error_count,
        "classification_counts": dict(sorted(stats.classification_counts.items())),
        "scanner_component": SCANNER_COMPONENT,
        "scanner_version_or_code_fingerprint": SCANNER_VERSION,
        "previous_snapshot_id": previous_snapshot_id,
        "latest_transition_id": latest_transition_id,
        "currentness_level": currentness_level,
        "currentness_scope": CURRENTNESS_SCOPE,
        "verification_mode": (
            FULL_VERIFICATION_MODE
            if currentness_level == "CURRENT_FULLY_VERIFIED"
            else INCREMENTAL_VERIFICATION_MODE
            if currentness_level == "CURRENT_INCREMENTAL"
            else "INCOMPLETE_OR_UNKNOWN"
        ),
        "exclusions_applied": [
            {
                "pattern": rule.pattern,
                "reason": rule.reason,
                "owner": rule.owner,
                "traversal_policy": rule.traversal_policy,
            }
            for rule in profile.exclusions
        ],
    }


def _compute_transition_id(previous_snapshot_id: str, current_snapshot_id: str) -> str:
    return hashlib.sha256(f"{previous_snapshot_id}:{current_snapshot_id}".encode("utf-8")).hexdigest()


def _write_transition_receipt(
    *,
    transition_id: str,
    previous_snapshot_id: str,
    current_snapshot_id: str,
    previous_material_state_hash: str | None,
    current_material_state_hash: str,
    profile: InventoryProfile,
    profile_hash: str,
    events: Sequence[Mapping[str, Any]],
    counts: Mapping[str, int],
    transitions_dir: Path = TRANSITIONS_DIR,
) -> dict[str, Any]:
    tr_dir = transitions_dir / transition_id
    tr_dir.mkdir(parents=True, exist_ok=True)
    receipt_events = _receipt_events(events)
    events_path = tr_dir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as handle:
        for ev in receipt_events:
            handle.write(json.dumps(ev, sort_keys=True, ensure_ascii=False) + "\n")
    events_hash = hashlib.sha256(events_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "transition_id": transition_id,
        "previous_snapshot_id": previous_snapshot_id,
        "current_snapshot_id": current_snapshot_id,
        "previous_material_state_hash": previous_material_state_hash,
        "current_material_state_hash": current_material_state_hash,
        "inventory_profile_id": profile.profile_id,
        "inventory_profile_hash": profile_hash,
        "created_at": _utc_now(),
        "event_count": len(receipt_events),
        "added_count": counts.get("added_count", 0),
        "removed_count": counts.get("removed_count", 0),
        "content_changed_count": counts.get("content_changed_count", 0),
        "metadata_changed_count": counts.get("metadata_changed_count", 0),
        "possible_move_count": counts.get("possible_move_count", 0),
        "possible_copy_count": counts.get("possible_copy_count", 0),
        "duplicate_content_count": counts.get("duplicate_content_count", 0),
        "unknown_count": counts.get("unknown_count", 0),
        "events_hash": events_hash,
    }
    (tr_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


# ---------------------------------------------------------------------------
# Current inventory I/O (Fase C-07/C-08 atomicity + fail-closed consistency)
# ---------------------------------------------------------------------------


def load_current_inventory(
    *,
    inventory_path: Path = CURRENT_INVENTORY_PATH,
    manifest_path: Path = CURRENT_MANIFEST_PATH,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    inv_exists = inventory_path.exists()
    manifest_exists = manifest_path.exists()
    if inv_exists != manifest_exists:
        raise MaterialInventoryError("CURRENT_INVENTORY_PAIR_INCONSISTENT")
    if not inv_exists:
        return None, None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = [
        json.loads(line) for line in inventory_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    recomputed = compute_material_state_hash(records)
    if recomputed != manifest.get("material_state_hash"):
        raise MaterialInventoryError("CURRENT_INVENTORY_PAIR_INCONSISTENT")
    return records, manifest


@contextmanager
def _inventory_lock(lock_path: Path = LOCK_PATH) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_promote(
    staging_inventory: Path,
    staging_manifest: Path,
    *,
    inventory_path: Path = CURRENT_INVENTORY_PATH,
    manifest_path: Path = CURRENT_MANIFEST_PATH,
) -> None:
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_inventory = inventory_path.with_suffix(inventory_path.suffix + ".tmp")
    tmp_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    shutil.copyfile(staging_inventory, tmp_inventory)
    shutil.copyfile(staging_manifest, tmp_manifest)
    os.replace(tmp_inventory, inventory_path)
    os.replace(tmp_manifest, manifest_path)


def _validate_staging(records: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> dict[str, Any]:
    problems: list[str] = []
    if manifest.get("artifact_count") != len(records):
        problems.append("artifact_count mismatch")
    recomputed = compute_material_state_hash(records)
    if recomputed != manifest.get("material_state_hash"):
        problems.append("material_state_hash mismatch")
    paths = [r["relative_path"] for r in records]
    if paths != sorted(paths):
        problems.append("records not in deterministic order")
    if len(set(paths)) != len(paths):
        problems.append("duplicate relative_path in inventory")
    return {"valid": not problems, "problems": problems}


# ---------------------------------------------------------------------------
# Top-level operations (option 1/2/3 of the reoriented menu)
# ---------------------------------------------------------------------------


def update_inventory(
    *,
    profile: InventoryProfile | None = None,
    run_id: str | None = None,
    full_verify: bool = False,
    tmp_root: Path = TMP_ROOT,
    transitions_dir: Path = TRANSITIONS_DIR,
    inventory_path: Path = CURRENT_INVENTORY_PATH,
    manifest_path: Path = CURRENT_MANIFEST_PATH,
    lock_path: Path = LOCK_PATH,
) -> dict[str, Any]:
    profile = profile or default_profile()
    run_id = run_id or f"run-{int(time.time() * 1000)}"
    work_dir = tmp_root / run_id

    previous_records, previous_manifest = load_current_inventory(
        inventory_path=inventory_path, manifest_path=manifest_path
    )
    previous_by_path = {r["relative_path"]: r for r in (previous_records or [])}

    started = time.monotonic()
    records, stats = scan_material(profile, previous_records_by_path=previous_by_path, full_verify=full_verify)
    scan_seconds = time.monotonic() - started
    if stats.hash_error_count:
        raise MaterialInventoryError(
            f"OBSERVATION_INCOMPLETE: {stats.hash_error_count} artifact(s) could not be hashed"
        )

    material_state_hash = compute_material_state_hash(records)
    profile_hash = compute_profile_hash(profile)
    snapshot_id = compute_snapshot_id(material_state_hash, profile_hash)

    work_dir.mkdir(parents=True, exist_ok=True)
    staging_inventory = work_dir / "current_inventory.jsonl"
    with staging_inventory.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")

    transition_id: str | None = None
    if previous_manifest is None:
        currentness_level = "CURRENT_FULLY_VERIFIED" if full_verify else "CURRENT_INCREMENTAL"
        change_summary: dict[str, Any] = {"result": "INITIAL_CURRENT_INVENTORY"}
    elif previous_manifest.get("inventory_profile_hash") != profile_hash:
        currentness_level = "UNKNOWN"
        change_summary = {"result": "INVENTORY_PROFILE_CHANGED_REBASELINE_REQUIRED"}
    elif snapshot_id == previous_manifest.get("snapshot_id"):
        currentness_level = "CURRENT_FULLY_VERIFIED" if full_verify else "CURRENT_INCREMENTAL"
        change_summary = {"result": "NO_CHANGE"}
    else:
        events, counts = detect_changes(previous_records or [], records)
        transition_id = _compute_transition_id(previous_manifest["snapshot_id"], snapshot_id)
        _write_transition_receipt(
            transition_id=transition_id,
            previous_snapshot_id=previous_manifest["snapshot_id"],
            current_snapshot_id=snapshot_id,
            previous_material_state_hash=previous_manifest.get("material_state_hash"),
            current_material_state_hash=material_state_hash,
            profile=profile,
            profile_hash=profile_hash,
            events=events,
            counts=counts,
            transitions_dir=transitions_dir,
        )
        currentness_level = "CURRENT_FULLY_VERIFIED" if full_verify else "CURRENT_INCREMENTAL"
        change_summary = {"result": "MATERIAL_TRANSITION", "transition_id": transition_id, "counts": counts}

    manifest = build_manifest(
        profile=profile,
        profile_hash=profile_hash,
        stats=stats,
        snapshot_id=snapshot_id,
        material_state_hash=material_state_hash,
        previous_snapshot_id=(previous_manifest or {}).get("snapshot_id"),
        latest_transition_id=transition_id or (previous_manifest or {}).get("latest_transition_id"),
        currentness_level=currentness_level,
    )
    staging_manifest = work_dir / "current_inventory_manifest.json"
    staging_manifest.write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    validation_report = _validate_staging(records, manifest)
    (work_dir / "validation_report.json").write_text(
        json.dumps(validation_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if not validation_report["valid"]:
        raise MaterialInventoryError(f"staging validation failed: {validation_report['problems']}")

    with _inventory_lock(lock_path):
        _atomic_promote(
            staging_inventory, staging_manifest, inventory_path=inventory_path, manifest_path=manifest_path
        )

    return {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "material_state_hash": material_state_hash,
        "scan_seconds": scan_seconds,
        "change_summary": change_summary,
        "manifest": manifest,
        "work_dir": str(work_dir),
    }


def check_status(
    *,
    profile: InventoryProfile | None = None,
    full_verify: bool = False,
    inventory_path: Path = CURRENT_INVENTORY_PATH,
    manifest_path: Path = CURRENT_MANIFEST_PATH,
) -> dict[str, Any]:
    profile = profile or default_profile()
    previous_records, previous_manifest = load_current_inventory(
        inventory_path=inventory_path, manifest_path=manifest_path
    )
    if previous_manifest is None:
        return {"status": "NO_CURRENT_INVENTORY"}

    previous_by_path = {r["relative_path"]: r for r in previous_records}
    started = time.monotonic()
    records, stats = scan_material(profile, previous_records_by_path=previous_by_path, full_verify=full_verify)
    scan_seconds = time.monotonic() - started
    material_state_hash = compute_material_state_hash(records)
    profile_hash = compute_profile_hash(profile)
    snapshot_id = compute_snapshot_id(material_state_hash, profile_hash)

    if previous_manifest.get("inventory_profile_hash") != profile_hash:
        return {
            "status": "PROFILE_MISMATCH",
            "checked_at": _utc_now(),
            "last_observed_at": previous_manifest.get("last_observed_at")
            or previous_manifest.get("observed_at"),
            "previous_profile_hash": previous_manifest.get("inventory_profile_hash"),
            "current_profile_hash": profile_hash,
        }

    events, counts = detect_changes(previous_records, records)
    common = {
        "checked_at": _utc_now(),
        "scan_seconds": scan_seconds,
        "verification_mode": FULL_VERIFICATION_MODE if full_verify else INCREMENTAL_VERIFICATION_MODE,
        "persisted_snapshot_id": previous_manifest.get("snapshot_id"),
        "last_observed_at": previous_manifest.get("last_observed_at")
        or previous_manifest.get("observed_at"),
        "persisted_currentness_level": previous_manifest.get("currentness_level"),
        "persisted_currentness_scope": previous_manifest.get("currentness_scope") or CURRENTNESS_SCOPE,
        "persisted_artifact_count": previous_manifest.get("artifact_count"),
        "live_artifact_count": stats.artifact_count,
        "live_hash_error_count": stats.hash_error_count,
    }
    if stats.hash_error_count:
        return {
            "status": "OBSERVATION_INCOMPLETE",
            "snapshot_id": snapshot_id,
            "counts": counts,
            "events": _receipt_events(events),
            **common,
        }
    if snapshot_id == previous_manifest.get("snapshot_id"):
        return {"status": "CURRENT", "snapshot_id": snapshot_id, "counts": counts, **common}
    return {
        "status": "CHANGES_DETECTED",
        "snapshot_id": snapshot_id,
        "counts": counts,
        "events": _receipt_events(events),
        **common,
    }


def _tree_lines(records: Sequence[Mapping[str, Any]]) -> str:
    root: dict[str, Any] = {}
    for record in records:
        parts = record["relative_path"].split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault("__files__", []).append(parts[-1])

    lines: list[str] = ["."]

    def walk(node: dict[str, Any], prefix: str) -> None:
        dirs = sorted(k for k in node if k != "__files__")
        files = sorted(node.get("__files__", []))
        entries = [(d, True) for d in dirs] + [(f, False) for f in files]
        for idx, (name, is_dir) in enumerate(entries):
            last = idx == len(entries) - 1
            connector = "`-- " if last else "|-- "
            lines.append(f"{prefix}{connector}{name}")
            if is_dir:
                walk(node[name], prefix + ("    " if last else "|   "))

    walk(root, "")
    return "\n".join(lines) + "\n"


def render_ascii_structure(
    *,
    output_path: Path = ASCII_VIEW_PATH,
    inventory_path: Path = CURRENT_INVENTORY_PATH,
    manifest_path: Path = CURRENT_MANIFEST_PATH,
) -> dict[str, Any]:
    records, manifest = load_current_inventory(inventory_path=inventory_path, manifest_path=manifest_path)
    if manifest is None:
        return {"status": "NO_CURRENT_INVENTORY"}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree_text = _tree_lines(records)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(tree_text, encoding="utf-8")
    os.replace(tmp_path, output_path)
    return {
        "status": "OK",
        "output_path": str(output_path),
        "artifact_count": len(records),
        "snapshot_id": manifest["snapshot_id"],
    }
