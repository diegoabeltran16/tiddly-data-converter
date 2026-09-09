#!/usr/bin/env python3
"""audit_repo_lifecycle_authority.py — S0186 Unit H (GATE-020 remediation)

Read-only diagnostic: which Canon records that represent real repository
files are missing ``source_fields.repo_lifecycle_state``, and for how many
of them can ``current_repo_artifact`` be demonstrated deterministically
right now (no human judgment, no ad hoc inference)?

Ownership finding (see the accompanying evidence under
data/out/local/audit/s0186/unit_h_repository_relational_full_hd/):

  repo_lifecycle_state is CANON_DERIVED. The established producer/contract
  is characterize_repo_artifacts.py (S0146): a record may carry
  repo_lifecycle_state=current_repo_artifact only when its resolved
  repo_path exists in the worktree AND the record's own canonized content
  (the fenced code block already embedded in its ``text``) matches that
  worktree file's current content exactly, or up to newline normalization.
  "The file exists" alone is NOT sufficient evidence (Canon can be stale
  relative to an edited worktree file -- demonstrated live, see below) and
  is deliberately never treated as sufficient by this module.

  Materialization into Canon (if the human decides to proceed) belongs to
  the EXISTING governed repo-metadata pipeline (characterize_repo_artifacts
  .py -> build_repo_metadata_patch_preview.py -> repo_metadata_admission_gate
  .py / repo_metadata_review_menu.py), reachable from
  "7) Revisión/admisión gobernada -> 1) Metadata técnica". This module does
  not replace or bypass that governance -- it independently re-verifies the
  SAME evidentiary rule those scripts are supposed to implement, because
  characterize_repo_artifacts.py's own content-comparison/authority-level
  logic has a separate, already-documented, pre-existing defect
  (test_repo_artifact_characterization.py: test_requires_positive_
  comparison_for_current_verified and related) that makes its automated
  output currently unreliable for this exact decision. Until that is
  repaired, this module is the trustworthy source for the classification.

This module never writes Canon, never writes metadata, never runs
admission/Apply. It is pure read + report.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_LOCAL_ROOT = REPO_ROOT / "data" / "out" / "local"
DEFAULT_GATE_REPORT = (
    DEFAULT_LOCAL_ROOT / "audit" / "relation_admission" / "current" / "admission_gate_dry_run.json"
)

CONTENT_BLOCK_RE = re.compile(r"```(?:\w+)?\n(.*?)\n```", re.S)

ROOT_LEVEL_KNOWN_FILES = ("LICENSE", "README.md", "estructura.txt")


def _load_canon(local_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for shard in sorted(local_root.glob("tiddlers_*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _is_repo_like(record: dict[str, Any]) -> bool:
    source_fields = record.get("source_fields") or {}
    title = str(record.get("title") or "")
    return bool(
        source_fields.get("repo_path")
        or title.startswith("src/")
        or title.startswith("tests/")
        or title in ROOT_LEVEL_KNOWN_FILES
    )


def _resolve_real_path(record: dict[str, Any]) -> str:
    source_fields = record.get("source_fields") or {}
    return str(source_fields.get("repo_path") or record.get("key") or record.get("title") or "")


def classify_content_authority(record: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """Deterministic, content-verified classification for one canon record.

    Never infers current_repo_artifact from path existence alone.
    """
    real_path = _resolve_real_path(record)
    result: dict[str, Any] = {
        "id": record.get("id"),
        "title": record.get("title"),
        "repo_path": real_path,
    }
    if not real_path:
        result["classification"] = "NO_RESOLVABLE_PATH"
        return result
    absolute = repo_root / real_path
    if not absolute.is_file():
        result["classification"] = "NO_REAL_FILE"
        return result
    match = CONTENT_BLOCK_RE.search(record.get("text") or "")
    if match is None:
        result["classification"] = "NO_CODE_BLOCK"
        return result
    canon_code = match.group(1)
    try:
        worktree_code = absolute.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        result["classification"] = "WORKTREE_UNREADABLE"
        return result
    if canon_code == worktree_code:
        result["classification"] = "CONTENT_EXACT_MATCH"
    elif canon_code.replace("\r", "") == worktree_code.replace("\r", ""):
        result["classification"] = "CONTENT_NORMALIZED_MATCH"
    else:
        result["classification"] = "CONTENT_MISMATCH"
    return result


DETERMINISTIC_CURRENT_REPO_ARTIFACT = frozenset({"CONTENT_EXACT_MATCH", "CONTENT_NORMALIZED_MATCH"})
REQUIRES_HUMAN_REVIEW = frozenset({"CONTENT_MISMATCH", "NO_CODE_BLOCK", "WORKTREE_UNREADABLE"})


def build_lifecycle_authority_report(
    local_root: Path = DEFAULT_LOCAL_ROOT, repo_root: Path = REPO_ROOT,
    gate_report_path: Path = DEFAULT_GATE_REPORT,
) -> dict[str, Any]:
    canon_rows = _load_canon(local_root)
    repo_like = [row for row in canon_rows if _is_repo_like(row)]
    has_lifecycle = [row for row in repo_like if (row.get("source_fields") or {}).get("repo_lifecycle_state")]
    missing_lifecycle = [row for row in repo_like if not (row.get("source_fields") or {}).get("repo_lifecycle_state")]

    classifications = [classify_content_authority(row, repo_root) for row in missing_lifecycle]
    by_classification = Counter(item["classification"] for item in classifications)
    deterministic_ids = {
        item["id"] for item in classifications if item["classification"] in DETERMINISTIC_CURRENT_REPO_ARTIFACT
    }
    review_ids = {
        item["id"] for item in classifications if item["classification"] in REQUIRES_HUMAN_REVIEW
    }

    gate_cross_reference: dict[str, Any] = {"gate_report_found": False}
    if gate_report_path.is_file():
        gate = json.loads(gate_report_path.read_text(encoding="utf-8"))
        items = gate.get("items") or []
        candidates_path = local_root / "pipeline" / "relation_candidates" / "current" / "ready_for_human_review.jsonl"
        candidates_by_id: dict[str, Any] = {}
        if candidates_path.is_file():
            for line in candidates_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    candidates_by_id[str(row.get("candidate_id") or "")] = row
        blocked_by_lifecycle = [
            item for item in items
            if isinstance(item, dict)
            and item.get("human_review_decision") == "approved_for_admission"
            and any("GATE-020" in str(reason) for reason in (item.get("all_block_reasons") or []))
        ]
        would_resolve = 0
        still_needs_review = 0
        for item in blocked_by_lifecycle:
            candidate = candidates_by_id.get(str(item.get("candidate_id") or ""))
            if not candidate:
                continue
            endpoint_ids = {
                (candidate.get("source") or {}).get("canonical_id"),
                (candidate.get("target") or {}).get("canonical_id"),
            }
            if endpoint_ids & review_ids:
                still_needs_review += 1
            elif endpoint_ids & deterministic_ids:
                would_resolve += 1
        gate_cross_reference = {
            "gate_report_found": True,
            "gate_report_path": str(gate_report_path),
            "approved_but_blocked_by_gate_020": len(blocked_by_lifecycle),
            "would_resolve_via_deterministic_content_match": would_resolve,
            "still_requires_human_review": still_needs_review,
        }

    return {
        "schema_version": "s0186-unit-h-repo-lifecycle-authority/v1",
        "repo_like_records_total": len(repo_like),
        "already_have_lifecycle": len(has_lifecycle),
        "missing_lifecycle_total": len(missing_lifecycle),
        "missing_lifecycle_by_classification": dict(sorted(by_classification.items())),
        "deterministic_current_repo_artifact_count": len(deterministic_ids),
        "requires_human_review_count": len(review_ids),
        "sample_mismatches": [
            item for item in classifications if item["classification"] == "CONTENT_MISMATCH"
        ][:20],
        "gate_020_cross_reference": gate_cross_reference,
        "ownership_finding": {
            "repo_lifecycle_state": "CANON_DERIVED",
            "producer_contract": "src/python_scripts/characterize_repo_artifacts.py",
            "deterministic_rule": (
                "repo_path resolved AND file exists in worktree AND canonized "
                "fenced code block content matches (exact or newline-normalized) "
                "the current worktree file content"
            ),
            "materialization_owner": (
                "governed repo-metadata pipeline: characterize_repo_artifacts.py "
                "-> build_repo_metadata_patch_preview.py -> "
                "repo_metadata_admission_gate.py / repo_metadata_review_menu.py"
            ),
            "blocking_precondition": (
                "characterize_repo_artifacts.py's own content-comparison/"
                "authority-level logic has a pre-existing, already-documented "
                "defect (see tests/test_repo_artifact_characterization.py) that "
                "makes its automated current_verified/current_repo_artifact "
                "classification currently unreliable; this module independently "
                "re-verifies the same rule until that is repaired"
            ),
        },
    }


def render_compact(report: dict[str, Any]) -> str:
    lines = [
        "AUDITORÍA DE AUTORIDAD DE repo_lifecycle_state (solo lectura)",
        "",
        f"Registros repo-like en Canon: {report['repo_like_records_total']}",
        f"  Ya tienen repo_lifecycle_state: {report['already_have_lifecycle']}",
        f"  Sin repo_lifecycle_state: {report['missing_lifecycle_total']}",
        "",
        "De los que faltan, por clasificación determinista:",
    ]
    for classification, count in report["missing_lifecycle_by_classification"].items():
        lines.append(f"  {classification:<28} {count:>6}")
    lines += [
        "",
        f"current_repo_artifact demostrable ahora (contenido verificado): {report['deterministic_current_repo_artifact_count']}",
        f"Requieren revisión humana (drift o sin bloque de código): {report['requires_human_review_count']}",
    ]
    gate = report["gate_020_cross_reference"]
    if gate.get("gate_report_found"):
        lines += [
            "",
            "Cruce contra el admission gate CURRENT vigente:",
            f"  approved_for_admission bloqueados por GATE-020: {gate['approved_but_blocked_by_gate_020']}",
            f"  se resolverían con la regla determinista: {gate['would_resolve_via_deterministic_content_match']}",
            f"  seguirían requiriendo revisión humana: {gate['still_requires_human_review']}",
        ]
    lines += [
        "",
        f"Ownership: repo_lifecycle_state = {report['ownership_finding']['repo_lifecycle_state']}",
        f"Owner de materialización: {report['ownership_finding']['materialization_owner']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--gate-report", type=Path, default=DEFAULT_GATE_REPORT)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)

    report = build_lifecycle_authority_report(args.local_root, args.repo_root, args.gate_report)
    if args.compact:
        print(render_compact(report))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
