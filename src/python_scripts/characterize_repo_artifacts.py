#!/usr/bin/env python3
"""S0146 governed repo-artifact characterization.

Read-only with respect to canon shards. The script joins S0145 technical
candidate signals with observable canon/code-like evidence and the current
worktree inventory, then writes dry-run review artifacts under
data/out/local/pipeline/repo_artifacts/s0146/.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

SCHEMA = "repo-artifact-characterization/v1"
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_S0145_CANDIDATES = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "unknown_artifact_family"
    / "s0145"
    / "s0145_unknown_classification_candidates.jsonl"
)
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_artifacts" / "s0146"

REVIEW_COLUMNS = [
    "id",
    "title",
    "tags",
    "diagnostic_category",
    "candidate_artifact_family",
    "candidate_repo_path",
    "repo_path_exists_in_git",
    "repo_path_exists_in_worktree",
    "candidate_repo_artifact_kind",
    "candidate_repo_lifecycle_state",
    "candidate_is_current_repo_artifact",
    "candidate_authority_level",
    "content_comparison",
    "moved_to_candidate",
    "confidence",
    "risk_level",
    "reason",
    "recommended_action",
]

DIAGNOSTIC_CATEGORIES = [
    "repo_snapshot_current",
    "repo_snapshot_drifted",
    "repo_snapshot_missing",
    "moved_candidate",
    "deleted_historical_candidate",
    "generated_output",
    "narrative_code_reference",
    "embedded_code_block",
    "documentation_with_code_example",
    "session_or_diagnostic_narrative",
    "external_technical_reference",
    "unknown_repo_artifact",
    "review_required",
]

REPO_ARTIFACT_KINDS = [
    "source_code",
    "test_code",
    "shell_script",
    "config",
    "schema",
    "documentation",
    "ci_workflow",
    "generated_output",
    "data_fixture",
    "external_reference",
    "unknown_repo_artifact",
]

LIFECYCLE_STATES = [
    "current_repo_artifact",
    "historical_snapshot",
    "missing_from_repo",
    "moved_candidate",
    "deleted_historical",
    "generated_output",
    "external_reference",
    "unknown_lifecycle",
    "review_required",
]

AUTHORITY_LEVELS = [
    "current_verified",
    "historical_snapshot",
    "narrative_reference",
    "generated_derivative",
    "external_reference",
    "unknown",
]

RELATION_OPPORTUNITY_TYPES = [
    "possible_tested_by",
    "possible_tests",
    "possible_imports",
    "possible_imported_by",
    "possible_reads_from",
    "possible_writes_to",
    "possible_generates",
    "possible_validates",
    "possible_configured_by",
    "possible_belongs_to_directory",
    "possible_related_session",
    "possible_documents",
    "possible_implements",
    "possible_superseded_by",
    "possible_moved_to",
]

RECOMMENDED_ACTIONS = [
    "accept_as_repo_artifact_later",
    "apply_metadata_preview_later",
    "review_manually",
    "keep_as_narrative",
    "keep_as_historical",
    "mark_generated_derivative_later",
    "exclude_from_repo_artifact",
    "needs_new_rule",
    "needs_relation_review_later",
]

CODE_EXTENSIONS = {
    ".py",
    ".go",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".rs",
    ".java",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".sql",
}
CONFIG_EXTENSIONS = {
    ".json",
    ".jsonl",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".lock",
}
DOC_EXTENSIONS = {".md", ".txt", ".rst"}
TECH_PATH_PREFIXES = (
    ".github/",
    "src/python_scripts/",
    "src/shell_scripts/",
    "tests/",
    "src/go/",
    "src/rust/",
    "docs/",
    "esquemas/",
    "data/",
    "ux/",
)
SPECIAL_REPO_NAMES = {
    "README.md",
    "LICENSE",
    ".gitignore",
    ".gitattributes",
    "go.work",
    "go.work.sum",
    "estructura.txt",
    "tdc.sh",
}
GENERATED_PREFIXES = (
    "data/out/",
    "data/tmp/",
    ".venv/",
)
GENERATED_PARTS = (
    "/__pycache__/",
    "/.pytest_cache/",
    "/repository_export.egg-info/",
    "/tiddlers-export/",
)
SESSION_TITLE_RE = re.compile(
    r"^#### .*?(?:sesion|sesión|hipótesis|procedencia|balance|propuesta|diagnóstico)",
    re.IGNORECASE,
)
PATH_TOKEN_RE = re.compile(
    r"(?:(?:python_scripts|shell_scripts|tests|\.github|go|docs|data|esquemas|ux)/"
    r"[A-Za-z0-9._/() -]+\.[A-Za-z0-9]+|"
    r"(?:README\.md|LICENSE|go\.work(?:\.sum)?|estructura\.txt|\.gitignore|\.gitattributes))"
)
FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*\n(.*?)\n```", re.DOTALL)


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def clean_repo_path(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if value.startswith("./"):
        return value[2:]
    return value


def comparable_text(text: str) -> str:
    return normalize_newlines(text).rstrip("\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(comparable_text(text).encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            record = json.loads(raw)
            if isinstance(record, dict):
                record["_jsonl_source_path"] = str(path)
                record["_jsonl_source_line"] = line_no
                records.append(record)
    return records


def load_canon(canon_glob: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for shard in sorted(glob.glob(canon_glob)):
        shard_path = Path(shard)
        for record in read_jsonl(shard_path):
            record["_canon_shard"] = shard_path.name
            records.append(record)
    return records


def load_path_set(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    values: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = clean_repo_path(raw)
        if value:
            values.add(value)
    return values


def collect_tags(record: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("tags", "source_tags", "normalized_tags"):
        raw = record.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
        elif isinstance(raw, str):
            values.extend(raw.split())
    source_fields = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    raw_tags = source_fields.get("tags") or source_fields.get("source_tags")
    if isinstance(raw_tags, str):
        values.extend(raw_tags.split())
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def record_text(record: dict[str, Any]) -> str:
    text = record.get("text")
    if isinstance(text, str) and text:
        return text
    content = record.get("content")
    if isinstance(content, dict):
        plain = content.get("plain")
        if isinstance(plain, str):
            return plain
    return ""


def first_code_block(record: dict[str, Any]) -> str:
    content = record.get("content")
    if isinstance(content, dict):
        blocks = content.get("code_blocks")
        if isinstance(blocks, list) and blocks:
            first = blocks[0]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                return first["text"]
    text = record_text(record)
    match = FENCE_RE.search(text)
    if match:
        return match.group(1)
    return ""


def looks_like_repo_path(value: str) -> bool:
    value = clean_repo_path(value)
    if not value:
        return False
    if value in SPECIAL_REPO_NAMES:
        return True
    return value.startswith(TECH_PATH_PREFIXES) and bool(Path(value).suffix)


def path_tokens(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in PATH_TOKEN_RE.finditer(text):
        token = clean_repo_path(match.group(0).strip().strip("`'\",;:()[]{}"))
        if token and token not in seen:
            seen.add(token)
            found.append(token)
    return found


def candidate_repo_path(record: dict[str, Any], git_files: set[str], worktree_files: set[str]) -> str:
    candidates: list[str] = []
    for key in ("title", "key"):
        raw = record.get(key)
        if isinstance(raw, str):
            normalized = raw.strip().replace("\\", "/").lstrip("./")
            normalized = clean_repo_path(raw)
            if looks_like_repo_path(normalized):
                candidates.append(normalized)
    for token in path_tokens(record_text(record)):
        candidates.append(token)
    for candidate in candidates:
        if candidate in git_files or candidate in worktree_files:
            return candidate
    for candidate in candidates:
        if looks_like_repo_path(candidate):
            return candidate
    return ""


def title_declares_repo_path(record: dict[str, Any]) -> bool:
    for key in ("title", "key"):
        raw = record.get(key)
        if isinstance(raw, str) and looks_like_repo_path(clean_repo_path(raw)):
            return True
    return False


def is_generated_path(path: str) -> bool:
    clean = clean_repo_path(path)
    wrapped = f"/{clean}/"
    return clean.startswith(GENERATED_PREFIXES) or any(part in wrapped for part in GENERATED_PARTS)


def is_session_or_diagnostic(record: dict[str, Any]) -> bool:
    title = str(record.get("title") or "")
    if SESSION_TITLE_RE.search(title):
        return True
    source_fields = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    family = str(source_fields.get("artifact_family") or record.get("artifact_family") or "")
    return family.endswith("_de_sesion") or family.startswith("diagnostico_")


def is_external_reference(text: str) -> bool:
    return bool(re.search(r"\bhttps?://", text))


def is_code_like(record: dict[str, Any]) -> bool:
    text = record_text(record)
    tags = " ".join(collect_tags(record)).casefold()
    title = str(record.get("title") or "")
    return (
        record.get("role_primary") == "code"
        or bool(first_code_block(record))
        or "--- codigo" in tags
        or "--- código" in tags
        or looks_like_repo_path(title)
        or bool(path_tokens(text))
        or any(prefix in text for prefix in ("src/python_scripts/", "src/shell_scripts/", "python_scripts/", "shell_scripts/", "tests/", ".github/workflows/"))
    )


def classify_repo_artifact_kind(path: str, *, external: bool = False) -> str:
    if external:
        return "external_reference"
    clean = clean_repo_path(path)
    suffix = Path(clean).suffix.lower()
    name = Path(clean).name
    if not clean:
        return "unknown_repo_artifact"
    if is_generated_path(clean):
        return "generated_output"
    if clean.startswith(".github/workflows/") and suffix in {".yml", ".yaml"}:
        return "ci_workflow"
    if clean.startswith("esquemas/"):
        return "schema"
    if clean.startswith("tests/fixtures/") and not name.startswith("test_"):
        return "data_fixture"
    if clean.startswith("tests/") or name.startswith("test_") or name.endswith("_test.go"):
        return "test_code"
    if clean.startswith("src/shell_scripts/") or clean.startswith("shell_scripts/") or suffix == ".sh" or name == "tdc.sh":
        return "shell_script"
    if suffix in DOC_EXTENSIONS or name.upper() == "README.MD":
        return "documentation"
    if suffix in CONFIG_EXTENSIONS or name in {".gitignore", ".gitattributes", "go.work", "go.work.sum"}:
        return "config"
    if suffix in CODE_EXTENSIONS:
        return "source_code"
    return "unknown_repo_artifact"


def compare_content(record: dict[str, Any], repo_path: str) -> tuple[str, str, str]:
    if not repo_path:
        return "not_applicable", "", ""
    path = REPO_ROOT / repo_path
    if not path.exists() or not path.is_file():
        return "not_applicable", "", ""
    canon_code = first_code_block(record)
    if not canon_code:
        return "no_comparable_code_block", "", sha256_text(path.read_text(encoding="utf-8", errors="replace"))
    worktree_text = path.read_text(encoding="utf-8", errors="replace")
    canon_hash = sha256_text(canon_code)
    worktree_hash = sha256_text(worktree_text)
    if canon_code == worktree_text:
        comparison = "exact_match"
    elif comparable_text(canon_code) == comparable_text(worktree_text):
        comparison = "normalized_newline_match"
    else:
        comparison = "substantive_diff"
    return comparison, canon_hash, worktree_hash


def moved_candidate_for(path: str, git_files: set[str], worktree_files: set[str]) -> str:
    if not path:
        return ""
    basename = Path(path).name
    if not basename:
        return ""
    alternatives = sorted(
        candidate
        for candidate in (git_files | worktree_files)
        if Path(candidate).name == basename and candidate != path
    )
    return alternatives[0] if alternatives else ""


def s0145_technical_candidates(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for item in read_jsonl(path):
        if item.get("candidate_artifact_family") == "tiddler_tecnico":
            records[str(item.get("id") or "")] = item
    return records


def input_source_for(*, in_s0145: bool, code_like: bool, repo_path: bool) -> str:
    active = [in_s0145, code_like, repo_path]
    if sum(1 for flag in active if flag) > 1:
        return "mixed"
    if in_s0145:
        return "s0145_candidate"
    if repo_path:
        return "repo_path_like"
    return "canon_code_like"


def classify_record(
    record: dict[str, Any],
    *,
    s0145_candidate: dict[str, Any] | None,
    git_files: set[str],
    worktree_files: set[str],
) -> dict[str, Any]:
    title = str(record.get("title") or "")
    text = record_text(record)
    tags = collect_tags(record)
    repo_path = candidate_repo_path(record, git_files, worktree_files)
    session_shape = is_session_or_diagnostic(record)
    if session_shape and not title_declares_repo_path(record):
        repo_path = ""
    exists_git = repo_path in git_files if repo_path else False
    exists_worktree = repo_path in worktree_files or (bool(repo_path) and (REPO_ROOT / repo_path).exists())
    path_exists = exists_git or exists_worktree
    signals: list[str] = []
    if s0145_candidate:
        signals.extend(str(item) for item in s0145_candidate.get("signals", []))
        signals.append("s0145_tiddler_tecnico")
    if repo_path:
        signals.append("repo_path_detected")
    if exists_git:
        signals.append("git_path_exact")
    if exists_worktree:
        signals.append("worktree_path_exact")
    if first_code_block(record):
        signals.append("code_block_detected")
    if session_shape:
        signals.append("session_or_diagnostic_shape")

    external = not repo_path and is_external_reference(text)
    kind = classify_repo_artifact_kind(repo_path, external=external)
    comparison, canon_hash, worktree_hash = compare_content(record, repo_path)
    moved_to = "" if path_exists else moved_candidate_for(repo_path, git_files, worktree_files)
    if moved_to:
        signals.append("moved_basename_candidate")

    diagnostic_category = "unknown_repo_artifact"
    lifecycle = "unknown_lifecycle"
    authority = "unknown"
    current = "unknown"
    confidence = "low"
    risk = "medium"
    action = "review_manually"
    family = ""
    reason = "Insufficient evidence for governed repo-artifact classification."

    if repo_path and is_generated_path(repo_path):
        diagnostic_category = "generated_output"
        lifecycle = "generated_output"
        authority = "generated_derivative"
        current = "false"
        confidence = "high"
        risk = "critical"
        action = "mark_generated_derivative_later"
        family = "artefacto_repositorio"
        reason = "Path is under generated/runtime output and must not be treated as repo source truth."
    elif repo_path and path_exists:
        family = "artefacto_repositorio"
        if comparison in {"exact_match", "normalized_newline_match"}:
            diagnostic_category = "repo_snapshot_current"
            lifecycle = "current_repo_artifact"
            authority = "current_verified"
            current = "true"
            confidence = "high"
            risk = "low"
            action = "accept_as_repo_artifact_later"
            reason = "Repo path exists and canonized content matches current worktree content."
        elif comparison == "substantive_diff":
            diagnostic_category = "repo_snapshot_drifted"
            lifecycle = "historical_snapshot"
            authority = "historical_snapshot"
            current = "false"
            confidence = "high"
            risk = "critical"
            action = "review_manually"
            reason = "Repo path exists but canonized content differs substantively from current worktree content."
        else:
            diagnostic_category = "review_required"
            lifecycle = "review_required"
            authority = "unknown"
            current = "unknown"
            confidence = "requires_human_review"
            risk = "high"
            action = "review_manually"
            reason = "Repo path exists, but content cannot be compared; current authority is not proven."
    elif repo_path and moved_to:
        family = "artefacto_repositorio"
        diagnostic_category = "moved_candidate"
        lifecycle = "moved_candidate"
        authority = "historical_snapshot"
        current = "false"
        confidence = "medium"
        risk = "high"
        action = "review_manually"
        reason = "Original repo path is missing, but another worktree path has the same basename."
    elif repo_path:
        family = "artefacto_repositorio"
        diagnostic_category = "repo_snapshot_missing"
        lifecycle = "missing_from_repo"
        authority = "historical_snapshot"
        current = "false"
        confidence = "medium"
        risk = "critical"
        action = "keep_as_historical"
        reason = "Title or text indicates a repo path, but the path is absent from git/worktree."
    elif is_session_or_diagnostic(record) and path_tokens(text):
        diagnostic_category = "session_or_diagnostic_narrative"
        lifecycle = "unknown_lifecycle"
        authority = "narrative_reference"
        current = "false"
        confidence = "high"
        risk = "high"
        action = "keep_as_narrative"
        reason = "Session or diagnostic narrative mentions code paths but does not represent a repo file snapshot."
    elif first_code_block(record) and (title.endswith(".md") or "README" in title):
        diagnostic_category = "documentation_with_code_example"
        lifecycle = "unknown_lifecycle"
        authority = "narrative_reference"
        current = "false"
        confidence = "medium"
        risk = "high"
        action = "keep_as_narrative"
        reason = "Documentation-like tiddler contains code examples, not a verified repo file snapshot."
    elif first_code_block(record):
        diagnostic_category = "embedded_code_block"
        lifecycle = "unknown_lifecycle"
        authority = "narrative_reference"
        current = "false"
        confidence = "medium"
        risk = "high"
        action = "keep_as_narrative"
        reason = "Tiddler contains embedded code without a verifiable repo path."
    elif path_tokens(text):
        diagnostic_category = "narrative_code_reference"
        lifecycle = "unknown_lifecycle"
        authority = "narrative_reference"
        current = "false"
        confidence = "medium"
        risk = "medium"
        action = "keep_as_narrative"
        reason = "Tiddler mentions code paths or commands without representing a file snapshot."
    elif external:
        diagnostic_category = "external_technical_reference"
        lifecycle = "external_reference"
        authority = "external_reference"
        current = "false"
        confidence = "medium"
        risk = "medium"
        action = "exclude_from_repo_artifact"
        reason = "Technical reference appears external to the repository."

    if family == "artefacto_repositorio" and not repo_path:
        confidence = "requires_human_review"
        risk = "critical"
        action = "review_manually"

    return {
        "id": str(record.get("id") or ""),
        "title": title,
        "tags": tags,
        "input_source": input_source_for(
            in_s0145=s0145_candidate is not None,
            code_like=is_code_like(record),
            repo_path=bool(repo_path),
        ),
        "s0145_candidate_artifact_family": str((s0145_candidate or {}).get("candidate_artifact_family") or ""),
        "diagnostic_category": diagnostic_category,
        "candidate_artifact_family": family,
        "candidate_repo_path": repo_path,
        "repo_path_exists_in_git": bool(exists_git),
        "repo_path_exists_in_worktree": bool(exists_worktree),
        "candidate_repo_directory": str(Path(repo_path).parent) if repo_path and str(Path(repo_path).parent) != "." else "",
        "candidate_repo_extension": Path(repo_path).suffix.lower() if repo_path else "",
        "candidate_repo_artifact_kind": kind,
        "candidate_content_sha256": canon_hash,
        "candidate_first_seen_at": str((record.get("source_fields") or {}).get("created") or record.get("created") or ""),
        "candidate_last_seen_at": "S0146",
        "candidate_repo_lifecycle_state": lifecycle,
        "candidate_is_current_repo_artifact": current,
        "candidate_source_export_session": "S0146",
        "candidate_related_sessions": [],
        "candidate_authority_level": authority,
        "canon_content_sha256": canon_hash,
        "worktree_content_sha256": worktree_hash,
        "content_comparison": comparison,
        "moved_to_candidate": moved_to,
        "confidence": confidence,
        "risk_level": risk,
        "signals": sorted(set(signals)),
        "reason": reason,
        "recommended_action": action,
        "applied_to_canon": False,
        "dry_run": True,
    }


def build_relation_opportunities(classifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_path = {item["candidate_repo_path"]: item for item in classifications if item.get("candidate_repo_path")}
    opportunities: list[dict[str, Any]] = []
    for item in classifications:
        path = item.get("candidate_repo_path") or ""
        if not path:
            continue
        directory = item.get("candidate_repo_directory") or ""
        if directory:
            opportunities.append(
                relation_opportunity(
                    item,
                    target_id="",
                    target_title=directory,
                    relation_type="possible_belongs_to_directory",
                    evidence_strength="weak",
                    evidence=f"repo_path directory is {directory}",
                    risk_level="low",
                )
            )
        moved_to = item.get("moved_to_candidate") or ""
        if moved_to:
            target = by_path.get(moved_to, {})
            opportunities.append(
                relation_opportunity(
                    item,
                    target_id=str(target.get("id") or ""),
                    target_title=str(target.get("title") or moved_to),
                    relation_type="possible_moved_to",
                    evidence_strength="weak",
                    evidence=f"missing path shares basename with {moved_to}",
                    risk_level="high",
                )
            )
        if item.get("candidate_repo_artifact_kind") == "test_code":
            basename = Path(path).name
            stem = basename.removeprefix("test_").removesuffix("_test.go")
            possible_targets = [
                f"src/python_scripts/{stem.removesuffix('.py')}.py",
                f"src/go/{stem}.go",
            ]
            for target_path in possible_targets:
                target = by_path.get(target_path)
                if target:
                    opportunities.append(
                        relation_opportunity(
                            item,
                            target_id=str(target.get("id") or ""),
                            target_title=str(target.get("title") or target_path),
                            relation_type="possible_tests",
                            evidence_strength="weak",
                            evidence=f"test filename resembles {target_path}",
                            risk_level="high",
                        )
                    )
    return sorted(opportunities, key=lambda row: (row["source_title"], row["possible_relation_type"], row["target_title"]))


def relation_opportunity(
    source: dict[str, Any],
    *,
    target_id: str,
    target_title: str,
    relation_type: str,
    evidence_strength: str,
    evidence: str,
    risk_level: str,
) -> dict[str, Any]:
    return {
        "source_id": source.get("id", ""),
        "source_title": source.get("title", ""),
        "target_id": target_id,
        "target_title": target_title,
        "possible_relation_type": relation_type,
        "evidence_strength": evidence_strength,
        "evidence": evidence,
        "risk_level": risk_level,
        "requires_human_review": True,
        "formal_relation_candidate": False,
        "admissible_in_s0146": False,
    }


def select_universe(
    canon_records: list[dict[str, Any]],
    s0145_candidates: dict[str, dict[str, Any]],
    git_files: set[str],
    worktree_files: set[str],
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    selected: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for record in canon_records:
        tid = str(record.get("id") or "")
        s0145 = s0145_candidates.get(tid)
        repo_path = candidate_repo_path(record, git_files, worktree_files)
        if s0145 or is_code_like(record) or repo_path:
            selected.append((record, s0145))
    return sorted(selected, key=lambda pair: (str(pair[0].get("title") or ""), str(pair[0].get("id") or "")))


def counter_for(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key) or "") for row in rows).items()))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(stable_json(row) + "\n" for row in rows), encoding="utf-8")


def write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    column: "|".join(row.get(column, [])) if isinstance(row.get(column), list) else row.get(column, "")
                    for column in REVIEW_COLUMNS
                }
            )


def display_path(path: Path) -> str:
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_summary(classifications: list[dict[str, Any]], *, s0145_total: int, additional_code_like: int) -> dict[str, Any]:
    by_category = counter_for(classifications, "diagnostic_category")
    return {
        "schema": "repo-artifact-grouped-summary/v1",
        "session": "S0146",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "total_evaluated": len(classifications),
        "from_s0145": s0145_total,
        "additional_code_like": additional_code_like,
        "with_candidate_repo_path": sum(1 for row in classifications if row.get("candidate_repo_path")),
        "with_git_path": sum(1 for row in classifications if row.get("repo_path_exists_in_git")),
        "with_worktree_path": sum(1 for row in classifications if row.get("repo_path_exists_in_worktree")),
        "by_diagnostic_category": by_category,
        "by_candidate_repo_artifact_kind": counter_for(classifications, "candidate_repo_artifact_kind"),
        "by_candidate_repo_lifecycle_state": counter_for(classifications, "candidate_repo_lifecycle_state"),
        "by_candidate_authority_level": counter_for(classifications, "candidate_authority_level"),
        "by_content_comparison": counter_for(classifications, "content_comparison"),
        "by_risk_level": counter_for(classifications, "risk_level"),
        "by_recommended_action": counter_for(classifications, "recommended_action"),
        "s0147_strong_candidates": sum(
            1
            for row in classifications
            if row.get("candidate_artifact_family") == "artefacto_repositorio"
            and row.get("candidate_repo_path")
            and row.get("candidate_authority_level") not in {"", "unknown"}
            and row.get("candidate_repo_lifecycle_state") not in {"", "unknown_lifecycle"}
            and row.get("content_comparison") not in {"no_comparable_code_block", "not_applicable"}
            and row.get("risk_level") != "critical"
        ),
        "requires_human_review": sum(1 for row in classifications if row.get("confidence") == "requires_human_review" or row.get("risk_level") in {"high", "critical"}),
    }


def grouped_summary_md(summary: dict[str, Any], relation_count: int) -> str:
    cat = summary["by_diagnostic_category"]
    kind = summary["by_candidate_repo_artifact_kind"]
    lifecycle = summary["by_candidate_repo_lifecycle_state"]
    authority = summary["by_candidate_authority_level"]
    dominant_kind = max(kind.items(), key=lambda item: item[1])[0] if kind else ""
    dominant_lifecycle = max(lifecycle.items(), key=lambda item: item[1])[0] if lifecycle else ""
    dominant_authority = max(authority.items(), key=lambda item: item[1])[0] if authority else ""
    lines = [
        "# S0146 repo_artifact grouped summary",
        "",
        f"- Total de tiddlers evaluados: {summary['total_evaluated']}",
        f"- Total provenientes de S0145: {summary['from_s0145']}",
        f"- Total code-like adicional detectado en canon: {summary['additional_code_like']}",
        f"- Total con repo_path candidato: {summary['with_candidate_repo_path']}",
        f"- Total con ruta en git: {summary['with_git_path']}",
        f"- Total con ruta en worktree: {summary['with_worktree_path']}",
        f"- Total current_repo_artifact: {lifecycle.get('current_repo_artifact', 0)}",
        f"- Total repo_snapshot_current: {cat.get('repo_snapshot_current', 0)}",
        f"- Total repo_snapshot_drifted: {cat.get('repo_snapshot_drifted', 0)}",
        f"- Total repo_snapshot_missing: {cat.get('repo_snapshot_missing', 0)}",
        f"- Total missing_from_repo: {lifecycle.get('missing_from_repo', 0)}",
        f"- Total moved_candidate: {cat.get('moved_candidate', 0)}",
        f"- Total deleted_historical_candidate: {cat.get('deleted_historical_candidate', 0)}",
        f"- Total generated_output: {cat.get('generated_output', 0)}",
        f"- Total narrative_code_reference: {cat.get('narrative_code_reference', 0)}",
        f"- Total embedded_code_block: {cat.get('embedded_code_block', 0)}",
        f"- Total documentation_with_code_example: {cat.get('documentation_with_code_example', 0)}",
        f"- Total session_or_diagnostic_narrative: {cat.get('session_or_diagnostic_narrative', 0)}",
        f"- Total external_technical_reference: {cat.get('external_technical_reference', 0)}",
        f"- Total unknown_repo_artifact: {cat.get('unknown_repo_artifact', 0)}",
        f"- Total review_required: {cat.get('review_required', 0)}",
        f"- Total que podrian recibir artefacto_repositorio en S0147: {summary['s0147_strong_candidates']}",
        f"- Total que requieren revision humana o exclusion antes de metadata: {summary['requires_human_review']}",
        f"- Tipo repo_artifact_kind dominante: {dominant_kind}",
        f"- Estado repo_lifecycle_state dominante: {dominant_lifecycle}",
        f"- authority_level dominante: {dominant_authority}",
        f"- Oportunidades relacionales detectadas: {relation_count}",
        "",
        "## Riesgos principales",
        "- Authority falsa por rutas vigentes con contenido divergente.",
        "- Sesiones narrativas que mencionan codigo y parecen snapshots.",
        "- Outputs generados bajo data/out o data/tmp tratados como fuente de verdad.",
        "- Bloques markdown de ejemplo confundidos con archivos ejecutables.",
        "",
        "## Reglas que funcionaron",
        "- Ruta exacta en git/worktree mas comparacion de contenido para current_verified.",
        "- Separacion entre snapshot, narrativa, output generado y referencia externa.",
        "- Bloqueo de relaciones formales: solo oportunidades con formal_relation_candidate=false.",
        "",
        "## Reglas insuficientes",
        "- Basename compartido solo permite moved_candidate debil, no rename confirmado.",
        "- Nombres de tests parecidos no prueban relacion tests/tested_by.",
        "- Markdown con codigo requiere revision antes de authority_level operativo.",
        "",
        "## Decision recomendada para S0147",
        "Avanzar solo a patch preview reversible de metadata para registros con repo_path, authority_level y lifecycle definidos, content_comparison no ambiguo y risk_level distinto de critical.",
        "",
        "## Familia artefacto_repositorio",
        "Conviene usar `artefacto_repositorio` como familia canonica futura solo para snapshots de archivos con metadata de path, hash, ciclo de vida y autoridad. No conviene promover en masa `tiddler_tecnico`.",
    ]
    return "\n".join(lines) + "\n"


def metadata_contract_md() -> str:
    return """# S0146 repo_artifact metadata contract

## Familia
`artifact_family = artefacto_repositorio` identifica snapshots o representaciones gobernadas de artefactos del repositorio. No reemplaza Git y no convierte el canon en fuente viva de codigo.

## Campos obligatorios futuros
- `repo_path`
- `repo_artifact_kind`
- `content_sha256`
- `last_seen_at`
- `repo_lifecycle_state`
- `is_current_repo_artifact`
- `authority_level`

## Campos derivados
- `repo_directory`
- `repo_extension`
- `is_current_repo_artifact`

## Campos opcionales
- `first_seen_at`
- `source_export_session`
- `related_sessions`

## Valores permitidos
- `repo_artifact_kind`: source_code, test_code, shell_script, config, schema, documentation, ci_workflow, generated_output, data_fixture, external_reference, unknown_repo_artifact.
- `repo_lifecycle_state`: current_repo_artifact, historical_snapshot, missing_from_repo, moved_candidate, deleted_historical, generated_output, external_reference, unknown_lifecycle, review_required.
- `authority_level`: current_verified, historical_snapshot, narrative_reference, generated_derivative, external_reference, unknown.

## Reglas de validacion
- `current_verified` requiere `repo_path` actual y `content_sha256`/comparacion positiva.
- Una ruta coincidente sin bloque comparable no basta para vigencia.
- `generated_output` nunca debe tratarse como source_code vigente.
- Sin `repo_path` verificable no hay `artefacto_repositorio` de confianza alta.

## Bloqueos de admision futura
- `risk_level=critical`.
- `content_comparison` en `substantive_diff`, `no_comparable_code_block` o `not_applicable` para authority current.
- `repo_lifecycle_state=unknown_lifecycle`.
- `candidate_authority_level=unknown`.

## Compatibilidad con source_fields
Si estos campos se almacenan en `source_fields`, deben ser planos string -> string. Listas como `related_sessions` deben serializarse como JSON string. No se deben guardar relaciones ni markdown completo dentro de `source_fields`.

## Compatibilidad con semantic_text
- `current_verified`: puede presentarse como codigo vigente.
- `historical_snapshot`: debe marcarse como historico.
- `narrative_reference`: debe tratarse como explicacion, no archivo.
- `generated_derivative`: debe marcarse como output derivado.
- `unknown`: debe evitar lenguaje de autoridad.

## Compatibilidad con relaciones tecnicas futuras
Las relaciones tecnicas solo pueden generarse despues de separar evidencia fuerte y debil. S0146 produce oportunidades, no candidatos formales.
"""


def lifecycle_report(classifications: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in classifications:
        rows_by_state[str(row.get("candidate_repo_lifecycle_state") or "")].append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "candidate_repo_path": row.get("candidate_repo_path"),
                "diagnostic_category": row.get("diagnostic_category"),
                "authority_level": row.get("candidate_authority_level"),
                "content_comparison": row.get("content_comparison"),
                "risk_level": row.get("risk_level"),
            }
        )
    return {
        "schema": "repo-artifact-lifecycle-report/v1",
        "session": "S0146",
        "dry_run": True,
        "applied_to_canon": False,
        "by_state": {key: value for key, value in sorted(rows_by_state.items())},
    }


def lifecycle_report_md(report: dict[str, Any]) -> str:
    lines = ["# S0146 repo lifecycle report", ""]
    for state, rows in report["by_state"].items():
        lines.append(f"## {state or 'empty'}")
        lines.append(f"- count: {len(rows)}")
        for row in rows[:10]:
            lines.append(f"- {row['title']} | {row.get('candidate_repo_path') or 'no-path'} | {row.get('content_comparison')}")
        lines.append("")
    return "\n".join(lines)


def path_mismatch_report(classifications: list[dict[str, Any]]) -> dict[str, Any]:
    mismatches = [
        row
        for row in classifications
        if row.get("content_comparison") in {"substantive_diff", "no_comparable_code_block"}
        or row.get("candidate_repo_lifecycle_state") in {"missing_from_repo", "moved_candidate"}
    ]
    return {
        "schema": "repo-artifact-path-mismatch-report/v1",
        "session": "S0146",
        "dry_run": True,
        "applied_to_canon": False,
        "count": len(mismatches),
        "items": [
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "candidate_repo_path": row.get("candidate_repo_path"),
                "moved_to_candidate": row.get("moved_to_candidate"),
                "content_comparison": row.get("content_comparison"),
                "diagnostic_category": row.get("diagnostic_category"),
                "risk_level": row.get("risk_level"),
                "reason": row.get("reason"),
            }
            for row in mismatches
        ],
    }


def rules_payload() -> dict[str, Any]:
    return {
        "schema": "repo-artifact-rules/v1",
        "session": "S0146",
        "dry_run": True,
        "diagnostic_categories": DIAGNOSTIC_CATEGORIES,
        "repo_artifact_kinds": REPO_ARTIFACT_KINDS,
        "repo_lifecycle_states": LIFECYCLE_STATES,
        "authority_levels": AUTHORITY_LEVELS,
        "relation_opportunity_types": RELATION_OPPORTUNITY_TYPES,
        "recommended_actions": RECOMMENDED_ACTIONS,
        "current_verified_requires": ["repo_path", "path_exists", "content_match"],
        "weak_evidence_never_allows": ["current_verified", "formal_relation_candidate"],
    }


def samples_md(classifications: list[dict[str, Any]]) -> str:
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in classifications:
        by_category[str(row.get("diagnostic_category"))].append(row)
    lines = ["# S0146 repo artifact samples", ""]
    for category in DIAGNOSTIC_CATEGORIES:
        rows = by_category.get(category, [])
        if not rows:
            continue
        lines.append(f"## {category}")
        for row in rows[:5]:
            lines.append(
                f"- {row.get('title')} | path={row.get('candidate_repo_path') or 'no-path'} | "
                f"comparison={row.get('content_comparison')} | risk={row.get('risk_level')}"
            )
        lines.append("")
    return "\n".join(lines)


def build_repo_artifact_outputs(
    *,
    canon_glob: str = DEFAULT_CANON_GLOB,
    s0145_candidates: Path | None = DEFAULT_S0145_CANDIDATES,
    git_files: Path | None = None,
    worktree_files: Path | None = None,
    out_dir: Path = DEFAULT_OUT_DIR,
    session: str = "S0146",
    dry_run: bool = True,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("S0146 only supports dry_run=true")
    canon_records = load_canon(canon_glob)
    s0145 = s0145_technical_candidates(s0145_candidates)
    git_set = load_path_set(git_files)
    worktree_set = load_path_set(worktree_files)
    if not git_set:
        git_set = {path.as_posix() for path in REPO_ROOT.rglob("*") if path.is_file()}
    if not worktree_set:
        worktree_set = set(git_set)

    universe = select_universe(canon_records, s0145, git_set, worktree_set)
    classifications = [
        classify_record(record, s0145_candidate=s0145_candidate, git_files=git_set, worktree_files=worktree_set)
        for record, s0145_candidate in universe
    ]
    classifications = sorted(classifications, key=lambda row: (row["title"], row["id"]))
    relation_opportunities = build_relation_opportunities(classifications)

    s0145_in_universe = sum(1 for _record, s0145_candidate in universe if s0145_candidate is not None)
    additional_code_like = len(classifications) - s0145_in_universe
    summary = build_summary(classifications, s0145_total=s0145_in_universe, additional_code_like=additional_code_like)

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "inventory": out_dir / "s0146_technical_tiddler_inventory.json",
        "classification": out_dir / "s0146_repo_artifact_classification.jsonl",
        "grouped_summary_json": out_dir / "s0146_repo_artifact_grouped_summary.json",
        "grouped_summary_md": out_dir / "s0146_repo_artifact_grouped_summary.md",
        "review": out_dir / "s0146_repo_artifact_review.csv",
        "metadata_contract": out_dir / "s0146_repo_artifact_metadata_contract.md",
        "mapping_preview": out_dir / "s0146_repo_artifact_mapping_preview.json",
        "lifecycle_json": out_dir / "s0146_repo_lifecycle_report.json",
        "lifecycle_md": out_dir / "s0146_repo_lifecycle_report.md",
        "path_mismatch": out_dir / "s0146_repo_path_mismatch_report.json",
        "moved_candidates": out_dir / "s0146_moved_candidates.jsonl",
        "generated_output_candidates": out_dir / "s0146_generated_output_candidates.jsonl",
        "narrative_code_reference_candidates": out_dir / "s0146_narrative_code_reference_candidates.jsonl",
        "relation_opportunities": out_dir / "s0146_repo_artifact_relation_opportunities.jsonl",
        "rules": out_dir / "s0146_repo_artifact_rules.json",
        "samples": out_dir / "s0146_repo_artifact_samples.md",
    }

    inventory = {
        "schema": SCHEMA,
        "session": session,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "canon_records": len(canon_records),
        "s0145_technical_candidates_available": len(s0145),
        "evaluated_records": len(classifications),
        "git_files": len(git_set),
        "worktree_files": len(worktree_set),
        "input_sources": counter_for(classifications, "input_source"),
        "outputs": {key: display_path(path) for key, path in paths.items()},
    }
    mapping_preview = {
        "schema": "repo-artifact-mapping-preview/v1",
        "session": session,
        "dry_run": True,
        "mapping_allowed_in_s0146": False,
        "applied_to_canon": False,
        "canon_modified": False,
        "relations_generated": False,
        "formal_relation_candidates_generated": False,
        "counts": {
            "diagnostic_category": summary["by_diagnostic_category"],
            "candidate_repo_artifact_kind": summary["by_candidate_repo_artifact_kind"],
            "candidate_repo_lifecycle_state": summary["by_candidate_repo_lifecycle_state"],
            "candidate_authority_level": summary["by_candidate_authority_level"],
            "content_comparison": summary["by_content_comparison"],
            "risk_level": summary["by_risk_level"],
            "recommended_action": summary["by_recommended_action"],
        },
    }

    write_json(paths["inventory"], inventory)
    write_jsonl(paths["classification"], classifications)
    write_json(paths["grouped_summary_json"], summary)
    paths["grouped_summary_md"].write_text(grouped_summary_md(summary, len(relation_opportunities)), encoding="utf-8")
    write_review_csv(paths["review"], classifications)
    paths["metadata_contract"].write_text(metadata_contract_md(), encoding="utf-8")
    write_json(paths["mapping_preview"], mapping_preview)
    lifecycle = lifecycle_report(classifications)
    write_json(paths["lifecycle_json"], lifecycle)
    paths["lifecycle_md"].write_text(lifecycle_report_md(lifecycle), encoding="utf-8")
    write_json(paths["path_mismatch"], path_mismatch_report(classifications))
    write_jsonl(paths["moved_candidates"], [row for row in classifications if row["diagnostic_category"] == "moved_candidate"])
    write_jsonl(paths["generated_output_candidates"], [row for row in classifications if row["diagnostic_category"] == "generated_output"])
    write_jsonl(
        paths["narrative_code_reference_candidates"],
        [
            row
            for row in classifications
            if row["diagnostic_category"] in {"narrative_code_reference", "session_or_diagnostic_narrative"}
        ],
    )
    write_jsonl(paths["relation_opportunities"], relation_opportunities)
    write_json(paths["rules"], rules_payload())
    paths["samples"].write_text(samples_md(classifications), encoding="utf-8")

    return {
        "summary": summary,
        "inventory": inventory,
        "relation_opportunities": len(relation_opportunities),
        "paths": {key: str(path) for key, path in paths.items()},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S0146 dry-run repo artifact characterization")
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--s0145-candidates", default=str(DEFAULT_S0145_CANDIDATES))
    parser.add_argument("--git-files", default="")
    parser.add_argument("--worktree-files", default="")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--session", default="S0146")
    parser.add_argument("--dry-run", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    s0145_path = Path(args.s0145_candidates) if args.s0145_candidates else None
    result = build_repo_artifact_outputs(
        canon_glob=args.canon_glob,
        s0145_candidates=s0145_path,
        git_files=Path(args.git_files) if args.git_files else None,
        worktree_files=Path(args.worktree_files) if args.worktree_files else None,
        out_dir=Path(args.out_dir),
        session=args.session,
        dry_run=args.dry_run,
    )
    print(stable_json({"status": "ok", **result["summary"], "relation_opportunities": result["relation_opportunities"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
