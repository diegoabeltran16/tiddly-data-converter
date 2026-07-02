#!/usr/bin/env python3
"""Generate technical relation candidates from repository evidence.

S0157 dry-run generator. It reads repository files and local canon shards,
emits reviewable candidates, and never writes canonical relations or derived
layers.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANON_ROOT = REPO_ROOT / "data" / "out" / "local"
DEFAULT_OUT_DIR = DEFAULT_CANON_ROOT / "pipeline" / "relation_candidates" / "s0157"

SCHEMA = "technical-relation-candidates/v1"
SESSION = "S0157"

READY = "candidate_ready_for_review"
BLOCKED_UNRESOLVED = "blocked_unresolved_target"
BLOCKED_DUPLICATE = "blocked_possible_duplicate"
BLOCKED_UNKNOWN_MAPPING = "blocked_unknown_canonical_mapping"
BLOCKED_UNVERIFIED = "blocked_unverified_evidence"

TECHNICAL_RELATION_TYPES: dict[str, str] = {
    "python_ast_import": "depende_de",
    "test_imports_subject": "valida",
    "script_references_path": "references",
    "script_reads_path": "references",
    "script_writes_artifact": "produce_artefacto",
}

SCAN_DIRS = (Path("python_scripts"), Path("tests"))
SKIP_DIR_PARTS = {".git", "__pycache__", ".pytest_cache", "data/out/local", "data/tmp"}


@dataclass(frozen=True)
class CanonArtifact:
    repo_path: str
    canonical_id: str
    canonical_title: str
    artifact_family: str | None
    authority_level: str | None
    repo_lifecycle_state: str | None
    canonical_status: str | None
    sha256: str | None


@dataclass(frozen=True)
class Observation:
    technical_relation_kind: str
    source_repo_path: str
    target_repo_path: str | None
    evidence_kind: str
    line: int
    raw_observation: str
    confidence: str = "high"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_canon_artifacts(canon_root: Path) -> tuple[dict[str, CanonArtifact], set[tuple[str, str, str]]]:
    by_repo_path: dict[str, CanonArtifact] = {}
    canonical_relations: set[tuple[str, str, str]] = set()

    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        with shard.open(encoding="utf-8") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                rec = json.loads(raw)
                tid = str(rec.get("id") or "")
                if not tid:
                    continue
                for rel in rec.get("relations") or []:
                    if isinstance(rel, dict) and rel.get("target_id") and rel.get("type"):
                        canonical_relations.add((tid, str(rel["target_id"]), str(rel["type"])))
                source_fields = rec.get("source_fields") or {}
                repo_path = source_fields.get("repo_path")
                if not repo_path:
                    continue
                by_repo_path[str(repo_path)] = CanonArtifact(
                    repo_path=str(repo_path),
                    canonical_id=tid,
                    canonical_title=str(rec.get("title") or ""),
                    artifact_family=source_fields.get("artifact_family"),
                    authority_level=source_fields.get("authority_level"),
                    repo_lifecycle_state=source_fields.get("repo_lifecycle_state"),
                    canonical_status=source_fields.get("canonical_status"),
                    sha256=source_fields.get("content_sha256") or rec.get("version_id"),
                )
    return by_repo_path, canonical_relations


def repo_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root)
            rel_s = rel.as_posix()
            if any(part in rel_s for part in SKIP_DIR_PARTS):
                continue
            files.append(path)
    return files


def module_to_repo_path(module: str, source_path: Path, root: Path) -> str | None:
    if not module:
        return None
    parts = module.split(".")
    module_path = Path(*parts)
    candidates = [
        root / module_path.with_suffix(".py"),
        root / module_path / "__init__.py",
    ]
    if len(parts) == 1:
        candidates.extend([
            source_path.parent / f"{parts[0]}.py",
            source_path.parent / parts[0] / "__init__.py",
        ])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.relative_to(root).as_posix()
    return None


def repo_file_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for base in SCAN_DIRS + (Path("."),):
        scan_root = root / base
        if not scan_root.exists():
            continue
        iterator = scan_root.rglob("*") if base != Path(".") else scan_root.iterdir()
        for path in iterator:
            if path.is_dir():
                continue
            rel = path.relative_to(root).as_posix()
            if any(part in rel for part in SKIP_DIR_PARTS):
                continue
            paths.add(rel)
    return paths


def _line_text(path: Path, line: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return ""
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()
    return ""


def ast_import_observations(path: Path, root: Path) -> list[Observation]:
    rel_source = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    observations: list[Observation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = module_to_repo_path(alias.name, path, root)
                if not target:
                    continue
                kind = "test_imports_subject" if rel_source.startswith("tests/") and target.startswith("python_scripts/") else "python_ast_import"
                observations.append(Observation(
                    technical_relation_kind=kind,
                    source_repo_path=rel_source,
                    target_repo_path=target,
                    evidence_kind="ast_import",
                    line=node.lineno,
                    raw_observation=_line_text(path, node.lineno),
                ))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            modules = [node.module or ""]
            modules.extend(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if node.module and alias.name != "*"
            )
            for module in modules:
                target = module_to_repo_path(module, path, root)
                if not target:
                    continue
                kind = "test_imports_subject" if rel_source.startswith("tests/") and target.startswith("python_scripts/") else "python_ast_import"
                observations.append(Observation(
                    technical_relation_kind=kind,
                    source_repo_path=rel_source,
                    target_repo_path=target,
                    evidence_kind="ast_import",
                    line=node.lineno,
                    raw_observation=_line_text(path, node.lineno),
                ))
    return observations


def path_literal_observations(path: Path, root: Path, known_paths: set[str]) -> list[Observation]:
    rel_source = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    observations: list[Observation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value.strip()
        if not value or len(value) > 240:
            continue
        normalized = value.replace("\\", "/").lstrip("./")
        if normalized not in known_paths:
            continue
        evidence_line = _line_text(path, getattr(node, "lineno", 1))
        lowered = evidence_line.lower()
        if ".write" in lowered or "write_text" in lowered or "open(" in lowered and "'w" in lowered:
            kind = "script_writes_artifact"
        elif ".read" in lowered or "read_text" in lowered or "open(" in lowered:
            kind = "script_reads_path"
        else:
            kind = "script_references_path"
        observations.append(Observation(
            technical_relation_kind=kind,
            source_repo_path=rel_source,
            target_repo_path=normalized,
            evidence_kind="path_literal",
            line=getattr(node, "lineno", 1),
            raw_observation=evidence_line,
        ))
    return observations


def discover_observations(root: Path, canon_paths: set[str]) -> list[Observation]:
    observations: list[Observation] = []
    observable_paths = set(canon_paths) | repo_file_paths(root)
    for path in repo_python_files(root):
        observations.extend(ast_import_observations(path, root))
        observations.extend(path_literal_observations(path, root, observable_paths))
    return observations


def load_prior_signatures(pipeline_root: Path) -> dict[tuple[str | None, str | None, str | None], str]:
    signatures: dict[tuple[str | None, str | None, str | None], str] = {}
    for path in sorted(pipeline_root.rglob("*.jsonl")):
        if "s0157" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for raw in lines:
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            source = rec.get("source") or {}
            target = rec.get("target") or {}
            relation = rec.get("relation") or {}
            sig = (
                source.get("canonical_id") or source.get("tiddler_id"),
                target.get("canonical_id") or target.get("tiddler_id"),
                rec.get("relation_type") or relation.get("type"),
            )
            if all(sig):
                signatures.setdefault(sig, rec.get("candidate_id") or path.as_posix())
    return signatures


def artifact_payload(artifact: CanonArtifact | None, repo_path: str | None, root: Path) -> dict[str, Any]:
    path = root / repo_path if repo_path else None
    file_hash = sha256_file(path) if path and path.exists() and path.is_file() else None
    return {
        "repo_path": repo_path,
        "canonical_id": artifact.canonical_id if artifact else None,
        "canonical_title": artifact.canonical_title if artifact else None,
        "artifact_family": artifact.artifact_family if artifact else None,
        "authority_level": artifact.authority_level if artifact else None,
        "repo_lifecycle_state": artifact.repo_lifecycle_state if artifact else None,
        "canonical_status": artifact.canonical_status if artifact else None,
        "sha256": file_hash or (artifact.sha256 if artifact else None),
    }


def build_candidate(
    observation: Observation,
    artifacts: dict[str, CanonArtifact],
    canonical_relations: set[tuple[str, str, str]],
    prior_signatures: dict[tuple[str | None, str | None, str | None], str],
    root: Path,
) -> dict[str, Any]:
    source_artifact = artifacts.get(observation.source_repo_path)
    target_artifact = artifacts.get(observation.target_repo_path or "")
    relation_type = TECHNICAL_RELATION_TYPES.get(observation.technical_relation_kind)

    reasons: list[str] = []
    duplicate_of: str | None = None
    status = READY
    if not relation_type:
        status = "blocked_unknown_relation_type_policy"
        reasons.append("technical_relation_kind has no governed relation_type mapping")
    elif not source_artifact:
        status = BLOCKED_UNKNOWN_MAPPING
        reasons.append("source repo_path has no canonical artifact mapping")
    elif not target_artifact:
        status = BLOCKED_UNRESOLVED
        reasons.append("target repo_path has no canonical artifact mapping")
    elif not observation.raw_observation:
        status = BLOCKED_UNVERIFIED
        reasons.append("evidence line could not be read from source file")
    else:
        sig = (source_artifact.canonical_id, target_artifact.canonical_id, relation_type)
        if sig in canonical_relations:
            status = BLOCKED_DUPLICATE
            duplicate_of = "canonical_relation"
            reasons.append("same source/target/relation_type already exists in canon")
        elif sig in prior_signatures:
            status = BLOCKED_DUPLICATE
            duplicate_of = prior_signatures[sig]
            reasons.append("same source/target/relation_type appears in prior relation candidates")

    seed = json.dumps({
        "source": observation.source_repo_path,
        "target": observation.target_repo_path,
        "kind": observation.technical_relation_kind,
        "line": observation.line,
        "raw": observation.raw_observation,
    }, sort_keys=True, ensure_ascii=False)
    candidate_id = "rc_s0157_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]

    candidate = {
        "candidate_id": candidate_id,
        "session_origin": SESSION,
        "candidate_schema_version": SCHEMA,
        "status": status,
        "relation_type": relation_type,
        "technical_relation_kind": observation.technical_relation_kind,
        "source": artifact_payload(source_artifact, observation.source_repo_path, root),
        "target": artifact_payload(target_artifact, observation.target_repo_path, root),
        "evidence": {
            "evidence_kind": observation.evidence_kind,
            "parser": "python_ast",
            "file": observation.source_repo_path,
            "line": observation.line,
            "span": f"line {observation.line}",
            "raw_observation": observation.raw_observation,
            "confidence": observation.confidence,
        },
        "policy": {
            "human_review_required": True,
            "canonical_admission_allowed": False,
            "derivation_allowed": False,
            "reasons": reasons,
        },
        "duplicate_of": duplicate_of,
    }
    return candidate


def build_candidates(root: Path, canon_root: Path) -> list[dict[str, Any]]:
    artifacts, canonical_relations = load_canon_artifacts(canon_root)
    observations = discover_observations(root, set(artifacts))
    prior = load_prior_signatures(canon_root / "pipeline")
    seen_observations: set[tuple[str, str | None, str, int]] = set()
    candidates: list[dict[str, Any]] = []
    for obs in observations:
        key = (obs.source_repo_path, obs.target_repo_path, obs.technical_relation_kind, obs.line)
        if key in seen_observations:
            continue
        seen_observations.add(key)
        candidates.append(build_candidate(obs, artifacts, canonical_relations, prior, root))
    return sorted(candidates, key=lambda c: c["candidate_id"])


def validate_candidates(candidates: Iterable[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for idx, candidate in enumerate(candidates, start=1):
        cid = candidate.get("candidate_id")
        if not isinstance(cid, str) or not cid.startswith("rc_s0157_"):
            errors.append(f"line {idx}: invalid candidate_id")
        if cid in seen:
            errors.append(f"line {idx}: duplicate candidate_id {cid}")
        seen.add(cid)
        if candidate.get("session_origin") != SESSION:
            errors.append(f"line {idx}: wrong session_origin")
        if candidate.get("policy", {}).get("canonical_admission_allowed") is not False:
            errors.append(f"line {idx}: canonical_admission_allowed must be false")
        if candidate.get("policy", {}).get("derivation_allowed") is not False:
            errors.append(f"line {idx}: derivation_allowed must be false")
        if candidate.get("status") == READY:
            if not candidate.get("source", {}).get("canonical_id"):
                errors.append(f"line {idx}: ready candidate without source canonical_id")
            if not candidate.get("target", {}).get("canonical_id"):
                errors.append(f"line {idx}: ready candidate without target canonical_id")
    return errors


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    rows = list(records)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return len(rows)


def write_outputs(candidates: list[dict[str, Any]], out_dir: Path, canon_root: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status_counts = Counter(c["status"] for c in candidates)
    kind_counts = Counter(c["technical_relation_kind"] for c in candidates)

    paths = {
        "jsonl": out_dir / "relation_candidates.jsonl",
        "report": out_dir / "relation_candidates_report.json",
        "summary": out_dir / "relation_candidates_summary.md",
        "review": out_dir / "relation_candidates_review.csv",
        "blocked": out_dir / "relation_candidates_blocked.json",
        "ready": out_dir / "relation_candidates_ready_for_review.json",
        "audit": out_dir / "relation_candidates_audit_log.jsonl",
    }

    ready = [c for c in candidates if c["status"] == READY]
    blocked = [c for c in candidates if c["status"] != READY]

    write_jsonl(paths["jsonl"], candidates)
    paths["ready"].write_text(json.dumps(ready, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["blocked"].write_text(json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "schema": "technical-relation-candidates-report/v1",
        "session": SESSION,
        "generated_at": now,
        "dry_run": True,
        "canon_root": str(canon_root),
        "output_dir": str(out_dir),
        "candidate_count": len(candidates),
        "ready_for_review_count": len(ready),
        "blocked_count": len(blocked),
        "status_counts": dict(sorted(status_counts.items())),
        "technical_relation_kind_counts": dict(sorted(kind_counts.items())),
        "policy": {
            "canonical_admission_allowed": False,
            "derivation_allowed": False,
            "human_review_required": True,
        },
        "validation_errors": validate_candidates(candidates),
    }
    paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = [
        "# S0157 relation candidates dry-run",
        "",
        f"Generated: `{now}`",
        f"Candidates: `{len(candidates)}`",
        f"Ready for review: `{len(ready)}`",
        f"Blocked: `{len(blocked)}`",
        "",
        "## Status counts",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        summary.append(f"- `{status}`: {count}")
    summary += ["", "## Technical relation kinds", ""]
    for kind, count in sorted(kind_counts.items()):
        summary.append(f"- `{kind}`: {count}")
    summary += [
        "",
        "## Boundary",
        "",
        "No canonical relation was admitted. No derived layer was regenerated. "
        "All candidates have `canonical_admission_allowed=false` and `derivation_allowed=false`.",
        "",
    ]
    paths["summary"].write_text("\n".join(summary), encoding="utf-8")

    with paths["review"].open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "candidate_id", "status", "relation_type", "technical_relation_kind",
            "source_repo_path", "source_canonical_id", "target_repo_path",
            "target_canonical_id", "evidence_kind", "line_or_span", "confidence",
            "human_review_required", "blocked_reason", "duplicate_of",
            "review_decision", "review_notes",
        ])
        writer.writeheader()
        for c in candidates:
            writer.writerow({
                "candidate_id": c["candidate_id"],
                "status": c["status"],
                "relation_type": c["relation_type"],
                "technical_relation_kind": c["technical_relation_kind"],
                "source_repo_path": c["source"]["repo_path"],
                "source_canonical_id": c["source"]["canonical_id"],
                "target_repo_path": c["target"]["repo_path"],
                "target_canonical_id": c["target"]["canonical_id"],
                "evidence_kind": c["evidence"]["evidence_kind"],
                "line_or_span": c["evidence"]["span"],
                "confidence": c["evidence"]["confidence"],
                "human_review_required": c["policy"]["human_review_required"],
                "blocked_reason": "; ".join(c["policy"]["reasons"]),
                "duplicate_of": c.get("duplicate_of") or "",
                "review_decision": "",
                "review_notes": "",
            })

    audit_rows = [
        {"event": "candidate_emitted", "session": SESSION, "candidate_id": c["candidate_id"], "status": c["status"]}
        for c in candidates
    ]
    write_jsonl(paths["audit"], audit_rows)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate S0157 technical relation candidates in dry-run mode.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--canon-root", type=Path, default=DEFAULT_CANON_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.apply:
        raise SystemExit("--apply is forbidden for S0157; this generator is dry-run only")
    candidates = build_candidates(args.repo_root.resolve(), args.canon_root)
    report = write_outputs(candidates, args.out_dir, args.canon_root)
    if report["validation_errors"]:
        print(json.dumps(report["validation_errors"], ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "session": SESSION,
        "candidate_count": report["candidate_count"],
        "ready_for_review_count": report["ready_for_review_count"],
        "blocked_count": report["blocked_count"],
        "out_dir": str(args.out_dir),
        "dry_run": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
