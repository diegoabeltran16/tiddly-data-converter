#!/usr/bin/env python3
"""S0148 dry-run admission gate for approved repo metadata batches.

This module verifies terminal decisions, S0147 hashes, batch risk, and patch
invariants. It never applies metadata to canon shards.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

S0147_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_review" / "s0147"
DEFAULT_PATCH_PREVIEW = S0147_DIR / "s0147_repo_metadata_patch_preview.jsonl"
DEFAULT_REVIEW_BATCHES = S0147_DIR / "s0147_repo_metadata_review_batches.json"
DEFAULT_PATCH_HASHES = S0147_DIR / "s0147_repo_metadata_patch_hashes.json"
DEFAULT_DRY_RUN_REPORT = S0147_DIR / "s0147_repo_metadata_dry_run_report.json"
DEFAULT_CLASSIFICATION = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "repo_artifacts"
    / "s0146"
    / "s0146_repo_artifact_classification.jsonl"
)
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_review" / "s0148"
DEFAULT_HUMAN_DECISIONS = DEFAULT_OUT_DIR / "s0148_repo_metadata_human_decisions.json"
DEFAULT_S0149_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_admission" / "s0149"
DEFAULT_S0149_SELECTED_BATCHES = DEFAULT_S0149_OUT_DIR / "s0149_selected_batches.json"

CURRENT_BATCH = "batch_current_verified"
EXCLUDED_BATCH = "batch_excluded_review_required"
S0149_RECOMMENDED_BATCHES = {
    "batch_current_verified",
    "batch_embedded_code",
    "batch_narrative_reference",
}
S0149_NOT_RECOMMENDED_BATCHES = {
    "batch_historical_review",
    "batch_generated_derivative",
}
S0149_BLOCKED_BATCHES = {
    EXCLUDED_BATCH,
}
S0149_BATCH_CHOICES = {
    "1": "batch_current_verified",
    "2": "batch_embedded_code",
    "3": "batch_narrative_reference",
    "4": "batch_historical_review",
    "5": "batch_generated_derivative",
    "6": EXCLUDED_BATCH,
}
S0149_DRY_RUN_TOKEN = "DRY RUN METADATA"
S0149_APPLY_TOKEN = "APPLY METADATA S0149"
ALLOWED_DECISIONS = {"approved", "rejected", "deferred"}
SESSION_TITLE_RE = re.compile(
    r"^#### .*?(sesión|sesion|diagnóstico|diagnostico|hipótesis|hipotesis|procedencia|balance|propuesta|contrato)",
    re.IGNORECASE,
)


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
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


def append_audit(path: Path, action: str, *, batch_id: str = "", result: str = "", timestamp: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": timestamp or utc_now(),
        "action": action,
        "batch_id": batch_id,
        "result": result,
        "decision_source": "terminal",
        "dry_run": True,
        "applied_to_canon": False,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(stable_json(payload) + "\n")


def s0148_paths(out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Path]:
    return {
        "human_decisions": out_dir / "s0148_repo_metadata_human_decisions.json",
        "batch_approvals": out_dir / "s0148_repo_metadata_batch_approvals.json",
        "gate_report": out_dir / "s0148_repo_metadata_gate_report.json",
        "admission_ready": out_dir / "s0148_repo_metadata_admission_ready_dry_run.jsonl",
        "blocked_records": out_dir / "s0148_repo_metadata_blocked_records.jsonl",
        "rejected_or_deferred": out_dir / "s0148_repo_metadata_rejected_or_deferred_batches.json",
        "terminal_audit": out_dir / "s0148_repo_metadata_terminal_audit.jsonl",
        "hash_verification": out_dir / "s0148_repo_metadata_hash_verification.json",
        "risk_verification": out_dir / "s0148_repo_metadata_risk_verification.json",
        "operator_summary": out_dir / "s0148_repo_metadata_operator_summary.md",
        "next_apply_plan": out_dir / "s0148_repo_metadata_next_apply_plan.md",
    }


def s0149_paths(out_dir: Path = DEFAULT_S0149_OUT_DIR) -> dict[str, Path]:
    return {
        "selected_batches": out_dir / "s0149_selected_batches.json",
        "dry_run_report": out_dir / "s0149_metadata_admission_dry_run_report.json",
        "ready": out_dir / "s0149_metadata_admission_ready.jsonl",
        "blocked": out_dir / "s0149_metadata_admission_blocked.jsonl",
        "patch_preview": out_dir / "s0149_metadata_admission_patch_preview.jsonl",
        "review": out_dir / "s0149_metadata_admission_review.csv",
        "summary": out_dir / "s0149_metadata_admission_summary.md",
        "audit": out_dir / "s0149_metadata_admission_audit_log.jsonl",
        "operator_flow": out_dir / "s0149_metadata_operator_flow_report.md",
        "apply_report": out_dir / "s0149_metadata_apply_report.json",
        "apply_log": out_dir / "s0149_metadata_apply_log.jsonl",
        "applied_records": out_dir / "s0149_metadata_applied_records.jsonl",
        "before_after_hashes": out_dir / "s0149_metadata_before_after_hashes.json",
        "apply_summary": out_dir / "s0149_metadata_apply_summary.md",
        "rollback_report": out_dir / "s0149_metadata_rollback_report.json",
        "rollback_log": out_dir / "s0149_metadata_rollback_log.jsonl",
        "backups": out_dir / "backups",
    }


def empty_decisions_doc() -> dict[str, Any]:
    return {
        "schema": "repo-metadata-human-decisions/v1",
        "session": "S0148",
        "decision_source": "terminal",
        "created_by_agent": False,
        "dry_run": True,
        "applied_to_canon": False,
        "human_approval_found": False,
        "decisions": [],
    }


def ensure_decisions_file(path: Path) -> dict[str, Any]:
    if path.exists():
        data = read_json(path)
        if isinstance(data, dict):
            return data
    data = empty_decisions_doc()
    write_json(path, data)
    return data


def expected_token(batch_id: str, decision: str) -> str:
    if batch_id == CURRENT_BATCH and decision == "approved":
        return "APROBAR_METADATA_BATCH_CURRENT_VERIFIED"
    if batch_id == CURRENT_BATCH and decision == "rejected":
        return "RECHAZAR_METADATA_BATCH_CURRENT_VERIFIED"
    if batch_id == CURRENT_BATCH and decision == "deferred":
        return "DIFERIR_METADATA_BATCH_CURRENT_VERIFIED"
    stem = batch_id.upper()
    if stem.startswith("BATCH_"):
        stem = stem.removeprefix("BATCH_")
    verb = {"approved": "APROBAR", "rejected": "RECHAZAR", "deferred": "DIFERIR"}[decision]
    return f"{verb}_METADATA_{stem}"


def token_name(decision: str) -> str:
    return {
        "approved": "approve",
        "rejected": "reject",
        "deferred": "defer",
    }[decision]


def batch_rows(patch_rows: list[dict[str, Any]], batch_id: str) -> list[dict[str, Any]]:
    return [row for row in patch_rows if row.get("batch_id") == batch_id]


def subset_sha(rows: list[dict[str, Any]]) -> str:
    ordered = sorted(rows, key=lambda row: stable_json(row))
    return hashlib.sha256("".join(stable_json(row) + "\n" for row in ordered).encode("utf-8")).hexdigest()


def record_terminal_decision(
    *,
    batch_id: str,
    decision: str,
    token: str,
    patch_preview: Path = DEFAULT_PATCH_PREVIEW,
    review_batches: Path = DEFAULT_REVIEW_BATCHES,
    patch_hashes: Path = DEFAULT_PATCH_HASHES,
    human_decisions: Path = DEFAULT_HUMAN_DECISIONS,
    out_dir: Path = DEFAULT_OUT_DIR,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"invalid decision: {decision}")
    paths = s0148_paths(out_dir)
    doc = ensure_decisions_file(human_decisions)
    batches_doc = read_json(review_batches)
    batches = batches_doc.get("batches") or {}
    hashes = read_json(patch_hashes)
    rows = read_jsonl(patch_preview)

    if batch_id not in batches:
        append_audit(paths["terminal_audit"], f"{decision}_batch", batch_id=batch_id, result="batch_not_found", timestamp=timestamp)
        return {"status": "blocked", "batch_id": batch_id, "decision": decision, "reason": "batch_not_found"}
    if decision == "approved" and batch_id == EXCLUDED_BATCH:
        append_audit(paths["terminal_audit"], "approve_batch", batch_id=batch_id, result="batch_not_approvable", timestamp=timestamp)
        return {"status": "blocked", "batch_id": batch_id, "decision": decision, "reason": "batch_not_approvable"}

    expected = expected_token(batch_id, decision)
    if token != expected:
        append_audit(paths["terminal_audit"], f"{decision}_batch", batch_id=batch_id, result="invalid_token", timestamp=timestamp)
        return {"status": "blocked", "batch_id": batch_id, "decision": decision, "reason": "invalid_token"}

    batch = batches[batch_id]
    matching_rows = batch_rows(rows, batch_id)
    batch_sha = batch.get("patch_sha256") or subset_sha(matching_rows)
    decision_payload = {
        "batch_id": batch_id,
        "decision": decision,
        "human_approved": decision == "approved",
        "token_verified": True,
        "token_name": expected,
        "decision_timestamp": timestamp or utc_now(),
        "patch_sha256": hashes.get("patch_preview_sha256", ""),
        "batch_sha256": batch_sha,
        "canon_before_sha256": hashes.get("canon_before_sha256", ""),
        "s0146_classification_sha256": hashes.get("s0146_classification_sha256", ""),
        "source_session": "S0147",
        "decision_source": "terminal",
    }

    decisions = [item for item in doc.get("decisions", []) if item.get("batch_id") != batch_id]
    decisions.append(decision_payload)
    decisions = sorted(decisions, key=lambda item: str(item.get("batch_id", "")))
    doc = {
        "schema": "repo-metadata-human-decisions/v1",
        "session": "S0148",
        "decision_source": "terminal",
        "created_by_agent": False,
        "dry_run": True,
        "applied_to_canon": False,
        "human_approval_found": any(item.get("decision") == "approved" and item.get("human_approved") is True for item in decisions),
        "decisions": decisions,
    }
    write_json(human_decisions, doc)
    append_audit(paths["terminal_audit"], f"{decision}_batch", batch_id=batch_id, result="recorded", timestamp=timestamp)
    return {"status": "ok", "batch_id": batch_id, "decision": decision, "token_verified": True}


def hash_verification(
    *,
    patch_preview: Path,
    review_batches: Path,
    patch_hashes: Path,
    dry_run_report: Path,
    s0146_classification: Path,
    canon_glob: str,
) -> dict[str, Any]:
    hashes = read_json(patch_hashes)
    checks = [
        {
            "name": "patch_preview_sha256",
            "expected": hashes.get("patch_preview_sha256", ""),
            "actual": file_sha256(patch_preview),
        },
        {
            "name": "review_batches_sha256",
            "expected": hashes.get("review_batches_sha256", ""),
            "actual": file_sha256(review_batches),
        },
        {
            "name": "dry_run_report_sha256",
            "expected": hashes.get("dry_run_report_sha256", ""),
            "actual": file_sha256(dry_run_report),
        },
        {
            "name": "s0146_classification_sha256",
            "expected": hashes.get("s0146_classification_sha256", ""),
            "actual": file_sha256(s0146_classification),
        },
        {
            "name": "canon_before_sha256",
            "expected": hashes.get("canon_before_sha256", ""),
            "actual": tree_sha256(canon_glob),
        },
    ]
    for check in checks:
        check["match"] = check["expected"] == check["actual"]
    return {
        "schema": "repo-metadata-hash-verification/v1",
        "session": "S0148",
        "all_hashes_match": all(check["match"] for check in checks),
        "checks": checks,
    }


def verify_patch_invariants(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for row in rows:
        op_id = str(row.get("op_id", ""))
        if row.get("dry_run") is not True:
            violations.append({"op_id": op_id, "reason": "patch_record_not_dry_run"})
        if row.get("applied_to_canon") is not False:
            violations.append({"op_id": op_id, "reason": "patch_record_applied_to_canon"})
        if row.get("human_approved") is not False:
            violations.append({"op_id": op_id, "reason": "s0147_patch_human_approved_true"})
        if "relations" in row or "candidate_relations" in row:
            violations.append({"op_id": op_id, "reason": "relation_field_present"})
        fields = row.get("fields_preview") if isinstance(row.get("fields_preview"), dict) else {}
        if "relations" in fields or "candidate_relations" in fields:
            violations.append({"op_id": op_id, "reason": "relation_field_present_in_fields_preview"})
        title = str(row.get("target_title") or "")
        if "artifact_family" in fields and SESSION_TITLE_RE.search(title):
            violations.append({"op_id": op_id, "reason": "artifact_family_change_on_session_or_diagnostic"})
    return violations


def risk_verification_for_batches(approved_batches: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    approved_rows = [row for row in rows if row.get("batch_id") in set(approved_batches)]
    risk_counts = Counter(str(row.get("source_risk_level") or row.get("risk_level") or "") for row in approved_rows)
    critical_count = risk_counts.get("critical", 0)
    return {
        "schema": "repo-metadata-risk-verification/v1",
        "session": "S0148",
        "approved_batches": approved_batches,
        "records_by_risk_level": dict(sorted(risk_counts.items())),
        "critical_count": critical_count,
        "high_count": risk_counts.get("high", 0),
        "medium_count": risk_counts.get("medium", 0),
        "low_count": risk_counts.get("low", 0),
        "blocked_due_to_risk": critical_count > 0,
    }


def rejected_or_deferred_doc(decisions: list[dict[str, Any]], batches: dict[str, Any]) -> dict[str, Any]:
    by_decision: dict[str, list[str]] = {key: [] for key in ("rejected", "deferred", "approved")}
    for decision in decisions:
        value = str(decision.get("decision") or "")
        if value in by_decision:
            by_decision[value].append(str(decision.get("batch_id") or ""))
    reviewed = set(by_decision["rejected"] + by_decision["deferred"] + by_decision["approved"])
    return {
        "schema": "repo-metadata-rejected-or-deferred-batches/v1",
        "session": "S0148",
        "rejected_batches": sorted(by_decision["rejected"]),
        "deferred_batches": sorted(by_decision["deferred"]),
        "not_reviewed_batches": sorted(set(batches) - reviewed),
        "blocked_by_policy": [EXCLUDED_BATCH] if EXCLUDED_BATCH in batches else [],
        "dry_run": True,
        "applied_to_canon": False,
    }


def approval_summary(decisions: list[dict[str, Any]], batches: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "repo-metadata-batch-approvals/v1",
        "session": "S0148",
        "dry_run": True,
        "applied_to_canon": False,
        "approved_batches": sorted(
            str(item.get("batch_id")) for item in decisions if item.get("decision") == "approved" and item.get("human_approved") is True
        ),
        "rejected_batches": sorted(str(item.get("batch_id")) for item in decisions if item.get("decision") == "rejected"),
        "deferred_batches": sorted(str(item.get("batch_id")) for item in decisions if item.get("decision") == "deferred"),
        "available_batches": sorted(batches),
        "recommended_batch": CURRENT_BATCH,
    }


def ready_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "op_id": row.get("op_id", ""),
        "target_id": row.get("target_id", ""),
        "target_title": row.get("target_title", ""),
        "batch_id": row.get("batch_id", ""),
        "fields_preview": row.get("fields_preview", {}),
        "human_approved": True,
        "gate_status": "admission_ready_dry_run",
        "dry_run": True,
        "applied_to_canon": False,
    }


def blocked_record(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "op_id": row.get("op_id", ""),
        "target_id": row.get("target_id", ""),
        "target_title": row.get("target_title", ""),
        "batch_id": row.get("batch_id", ""),
        "block_reason": reason,
        "risk_level": row.get("source_risk_level", row.get("risk_level", "")),
        "dry_run": True,
        "applied_to_canon": False,
    }


def operator_summary_md(report: dict[str, Any], hashes: dict[str, Any], risks: dict[str, Any]) -> str:
    lines = [
        "# S0148 repo metadata operator summary",
        "",
        f"- Approved batches: {report['approved_batches']}",
        f"- Rejected batches: {report['rejected_batches']}",
        f"- Deferred batches: {report['deferred_batches']}",
        f"- Human approval found: {report['human_approval_found']}",
        f"- Gate blocked: {report['blocked']}",
        f"- Admission ready dry-run records: {report['admission_ready_dry_run']}",
        f"- Blocked records: {report['blocked_records']}",
        f"- Block reasons: {report['block_reasons']}",
        f"- Hashes match: {hashes['all_hashes_match']}",
        f"- Critical approved records: {risks['critical_count']}",
        "",
        "## Not applied",
        "- Metadata was not applied to canon.",
        "- No formal relations or candidate_relations were generated.",
        "- semantic_text, embeddings, enriched, AI and chunks were not regenerated.",
        "",
        "## S0149",
        "S0149 can consume the approved dry-run artifacts only if hashes still match and human approval remains valid.",
    ]
    return "\n".join(lines) + "\n"


def next_apply_plan_md(report: dict[str, Any], hashes: dict[str, Any]) -> str:
    approved = report["approved_batches"]
    lines = [
        "# S0148 next apply plan for S0149",
        "",
        "S0149 is the candidate session for governed admission of approved repo metadata.",
        "",
        "## Inputs",
        "- `data/out/local/pipeline/repo_metadata_review/s0148/s0148_repo_metadata_human_decisions.json`",
        "- `data/out/local/pipeline/repo_metadata_review/s0148/s0148_repo_metadata_gate_report.json`",
        "- `data/out/local/pipeline/repo_metadata_review/s0148/s0148_repo_metadata_admission_ready_dry_run.jsonl`",
        "- `data/out/local/pipeline/repo_metadata_review/s0148/s0148_repo_metadata_hash_verification.json`",
        "",
        "## Approved batch",
        f"- {approved if approved else 'None'}",
        "",
        "## Hashes S0149 must verify",
    ]
    for check in hashes["checks"]:
        lines.append(f"- {check['name']}: `{check['expected']}`")
    lines.extend(
        [
            "",
            "## Dry-run records",
            f"- admission_ready_dry_run: {report['admission_ready_dry_run']}",
            f"- blocked_records: {report['blocked_records']}",
            "",
            "S0149 must not apply if hashes change, approval is missing, the approved batch differs, or any critical risk appears.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_gate(
    *,
    patch_preview: Path = DEFAULT_PATCH_PREVIEW,
    review_batches: Path = DEFAULT_REVIEW_BATCHES,
    patch_hashes: Path = DEFAULT_PATCH_HASHES,
    dry_run_report: Path = DEFAULT_DRY_RUN_REPORT,
    human_decisions: Path = DEFAULT_HUMAN_DECISIONS,
    canon_glob: str = DEFAULT_CANON_GLOB,
    s0146_classification: Path = DEFAULT_CLASSIFICATION,
    out_dir: Path = DEFAULT_OUT_DIR,
    session: str = "S0148",
    dry_run: bool = True,
) -> dict[str, Any]:
    if session != "S0148":
        raise ValueError("this gate is scoped to S0148")
    if not dry_run:
        raise ValueError("S0148 only supports dry_run=true")

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = s0148_paths(out_dir)
    decisions_doc = ensure_decisions_file(human_decisions)
    patch_rows = read_jsonl(patch_preview)
    batches_doc = read_json(review_batches)
    batches = batches_doc.get("batches") or {}
    decisions = decisions_doc.get("decisions") if isinstance(decisions_doc.get("decisions"), list) else []

    approved_decisions = [
        item
        for item in decisions
        if item.get("decision") == "approved"
        and item.get("human_approved") is True
        and item.get("token_verified") is True
        and item.get("decision_source") == "terminal"
    ]
    rejected_batches = sorted(str(item.get("batch_id")) for item in decisions if item.get("decision") == "rejected")
    deferred_batches = sorted(str(item.get("batch_id")) for item in decisions if item.get("decision") == "deferred")
    approved_batches = sorted(str(item.get("batch_id")) for item in approved_decisions)

    hash_doc = hash_verification(
        patch_preview=patch_preview,
        review_batches=review_batches,
        patch_hashes=patch_hashes,
        dry_run_report=dry_run_report,
        s0146_classification=s0146_classification,
        canon_glob=canon_glob,
    )
    risk_doc = risk_verification_for_batches(approved_batches, patch_rows)

    block_reasons: list[str] = []
    blocked_rows: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []

    if not approved_decisions:
        block_reasons.append("no_human_approval")
    if decisions_doc.get("created_by_agent") is not False:
        block_reasons.append("human_decisions_created_by_agent_not_false")
    if not hash_doc["all_hashes_match"]:
        block_reasons.extend(f"hash_mismatch:{check['name']}" for check in hash_doc["checks"] if not check["match"])

    invariant_violations = verify_patch_invariants(patch_rows)
    for violation in invariant_violations:
        block_reasons.append(violation["reason"])
    if risk_doc["blocked_due_to_risk"]:
        block_reasons.append("critical_risk_in_approved_batch")

    for batch_id in approved_batches:
        if batch_id not in batches:
            block_reasons.append(f"batch_not_found:{batch_id}")
            continue
        if batch_id == EXCLUDED_BATCH:
            block_reasons.append("excluded_batch_not_approvable")
        batch = batches[batch_id]
        decision = next(item for item in approved_decisions if item.get("batch_id") == batch_id)
        rows = batch_rows(patch_rows, batch_id)
        computed_batch_sha = subset_sha(rows)
        if decision.get("batch_sha256") != batch.get("patch_sha256"):
            block_reasons.append(f"decision_batch_sha_mismatch:{batch_id}")
        if batch.get("patch_sha256") != computed_batch_sha:
            block_reasons.append(f"computed_batch_sha_mismatch:{batch_id}")
        if decision.get("patch_sha256") != read_json(patch_hashes).get("patch_preview_sha256"):
            block_reasons.append(f"decision_patch_sha_mismatch:{batch_id}")
        if decision.get("canon_before_sha256") != read_json(patch_hashes).get("canon_before_sha256"):
            block_reasons.append(f"decision_canon_sha_mismatch:{batch_id}")
        if decision.get("s0146_classification_sha256") != read_json(patch_hashes).get("s0146_classification_sha256"):
            block_reasons.append(f"decision_classification_sha_mismatch:{batch_id}")
        if any(row.get("patch_lane") == "lane_f_excluded_review_required" for row in rows):
            block_reasons.append(f"lane_f_in_approved_batch:{batch_id}")
        if any(row.get("source_risk_level") == "critical" for row in rows):
            block_reasons.append(f"critical_risk_in_batch:{batch_id}")
        if any(row.get("applied_to_canon") is not False for row in rows):
            block_reasons.append(f"applied_record_in_batch:{batch_id}")
        if any(row.get("dry_run") is not True for row in rows):
            block_reasons.append(f"non_dry_run_record_in_batch:{batch_id}")
        if any("relations" in row or "candidate_relations" in row for row in rows):
            block_reasons.append(f"relation_field_in_batch:{batch_id}")

    block_reasons = sorted(set(block_reasons))
    blocked = bool(block_reasons)

    if not blocked:
        for row in patch_rows:
            if row.get("batch_id") in set(approved_batches):
                ready_rows.append(ready_record(row))
    elif approved_batches:
        reason = ";".join(block_reasons)
        for row in patch_rows:
            if row.get("batch_id") in set(approved_batches):
                blocked_rows.append(blocked_record(row, reason))

    rejected_doc = rejected_or_deferred_doc(decisions, batches)
    approvals_doc = approval_summary(decisions, batches)
    report = {
        "schema": "repo-metadata-admission-gate-report/v1",
        "session": "S0148",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "human_approval_found": bool(approved_decisions),
        "approved_batches": approved_batches,
        "rejected_batches": rejected_batches,
        "deferred_batches": deferred_batches,
        "admission_ready_dry_run": len(ready_rows),
        "blocked_records": len(blocked_rows),
        "blocked": blocked,
        "block_reasons": block_reasons,
        "hash_verification": hash_doc,
        "risk_verification": risk_doc,
        "relations_generated": False,
        "candidate_relations_generated": False,
        "formal_relation_candidates_generated": False,
        "semantic_text_modified": False,
    }

    write_json(paths["batch_approvals"], approvals_doc)
    write_json(paths["hash_verification"], hash_doc)
    write_json(paths["risk_verification"], risk_doc)
    write_json(paths["rejected_or_deferred"], rejected_doc)
    write_json(paths["gate_report"], report)
    write_jsonl(paths["admission_ready"], ready_rows)
    write_jsonl(paths["blocked_records"], blocked_rows)
    if not paths["terminal_audit"].exists():
        paths["terminal_audit"].write_text("", encoding="utf-8")
    paths["operator_summary"].write_text(operator_summary_md(report, hash_doc, risk_doc), encoding="utf-8")
    paths["next_apply_plan"].write_text(next_apply_plan_md(report, hash_doc), encoding="utf-8")
    append_audit(paths["terminal_audit"], "run_gate_dry_run", result="blocked" if blocked else "ready")
    return report


def s0149_audit_event(
    path: Path,
    action: str,
    *,
    result: str,
    details: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": timestamp or utc_now(),
        "session": "S0149",
        "action": action,
        "result": result,
        "dry_run_default": True,
        "apply_requires_token": S0149_APPLY_TOKEN,
        "applied_to_canon": False,
        "details": details or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(stable_json(payload) + "\n")


def s0149_batch_catalog(review_batches: Path = DEFAULT_REVIEW_BATCHES) -> dict[str, dict[str, Any]]:
    batches = read_json(review_batches).get("batches") or {}
    catalog: dict[str, dict[str, Any]] = {}
    reverse_choices = {batch_id: number for number, batch_id in S0149_BATCH_CHOICES.items()}
    for batch_id, batch in sorted(batches.items()):
        catalog[batch_id] = {
            "batch_id": batch_id,
            "choice": reverse_choices.get(batch_id, ""),
            "batch_label": batch.get("batch_label", ""),
            "record_count": int(batch.get("record_count") or 0),
            "patch_lane": batch.get("patch_lane", ""),
            "risk_profile": batch.get("risk_profile") or {},
            "recommended": batch_id in S0149_RECOMMENDED_BATCHES,
            "recommended_by_default": batch_id in S0149_RECOMMENDED_BATCHES,
            "not_recommended_by_default": batch_id in S0149_NOT_RECOMMENDED_BATCHES,
            "blocked": batch_id in S0149_BLOCKED_BATCHES,
            "block_reason": "excluded_review_required" if batch_id in S0149_BLOCKED_BATCHES else "",
        }
    return catalog


def normalize_s0149_batch_token(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value in S0149_BATCH_CHOICES:
        return S0149_BATCH_CHOICES[value]
    if value.startswith("batch_"):
        return value
    aliases = {
        "current_verified": "batch_current_verified",
        "embedded_code": "batch_embedded_code",
        "narrative_reference": "batch_narrative_reference",
        "historical_review": "batch_historical_review",
        "generated_derivative": "batch_generated_derivative",
        "excluded": EXCLUDED_BATCH,
        "excluded_review_required": EXCLUDED_BATCH,
        "review_required": EXCLUDED_BATCH,
    }
    return aliases.get(value, value)


def parse_s0149_batch_selection(selection: str | list[str] | tuple[str, ...]) -> dict[str, Any]:
    if isinstance(selection, str):
        raw_items = [item.strip() for item in selection.split(",")]
    else:
        raw_items = [str(item).strip() for item in selection]
    selected: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        batch_id = normalize_s0149_batch_token(item)
        if not batch_id:
            continue
        if batch_id in seen:
            duplicates.append(batch_id)
            continue
        seen.add(batch_id)
        selected.append(batch_id)
    return {
        "selected_batch_ids": selected,
        "duplicates": sorted(set(duplicates)),
        "empty_selection": not selected,
    }


def select_s0149_batches(
    selection: str | list[str] | tuple[str, ...],
    *,
    review_batches: Path = DEFAULT_REVIEW_BATCHES,
    out_dir: Path = DEFAULT_S0149_OUT_DIR,
    timestamp: str | None = None,
) -> dict[str, Any]:
    paths = s0149_paths(out_dir)
    catalog = s0149_batch_catalog(review_batches)
    parsed = parse_s0149_batch_selection(selection)
    selected_ids = parsed["selected_batch_ids"]
    invalid = [batch_id for batch_id in selected_ids if batch_id not in catalog]
    blocked = [batch_id for batch_id in selected_ids if batch_id in S0149_BLOCKED_BATCHES]
    selected_batches = [
        catalog[batch_id]
        for batch_id in selected_ids
        if batch_id in catalog
    ]
    valid = not parsed["empty_selection"] and not invalid and not blocked
    doc = {
        "schema": "repo-metadata-s0149-selected-batches/v1",
        "session": "S0149",
        "source_session": "S0147",
        "created_at": timestamp or utc_now(),
        "selection_source": "terminal_or_cli",
        "dry_run_token_required_for_interactive_menu": S0149_DRY_RUN_TOKEN,
        "apply_token_required": S0149_APPLY_TOKEN,
        "human_approval_simulated": False,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "valid": valid,
        "empty_selection": parsed["empty_selection"],
        "selected_batch_ids": selected_ids,
        "selected_batches": selected_batches,
        "selected_operation_count": sum(int(item.get("record_count") or 0) for item in selected_batches),
        "invalid_batch_ids": invalid,
        "blocked_batch_ids": blocked,
        "duplicate_batch_ids": parsed["duplicates"],
        "recommended_batch_ids": sorted(S0149_RECOMMENDED_BATCHES),
        "not_recommended_by_default_batch_ids": sorted(S0149_NOT_RECOMMENDED_BATCHES),
        "blocked_batch_policy": sorted(S0149_BLOCKED_BATCHES),
        "available_batches": list(catalog.values()),
        "relations_generated": False,
        "formal_relation_candidates_generated": False,
        "candidate_relations_generated": False,
    }
    write_json(paths["selected_batches"], doc)
    s0149_audit_event(
        paths["audit"],
        "select_batches",
        result="valid" if valid else "blocked",
        details={
            "selected_batch_ids": selected_ids,
            "invalid_batch_ids": invalid,
            "blocked_batch_ids": blocked,
            "empty_selection": parsed["empty_selection"],
        },
        timestamp=timestamp,
    )
    return doc


def s0149_selected_batch_ids(selected_batches: Path) -> list[str]:
    doc = read_json(selected_batches)
    values = doc.get("selected_batch_ids")
    if isinstance(values, list):
        return [str(item) for item in values]
    selected = doc.get("selected_batches")
    if isinstance(selected, list):
        ids: list[str] = []
        for item in selected:
            if isinstance(item, dict) and item.get("batch_id"):
                ids.append(str(item["batch_id"]))
            elif isinstance(item, str):
                ids.append(item)
        return ids
    return []


def s0149_ready_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "op_id": row.get("op_id", ""),
        "target_id": row.get("target_id", ""),
        "target_title": row.get("target_title", ""),
        "batch_id": row.get("batch_id", ""),
        "patch_lane": row.get("patch_lane", ""),
        "risk_level": row.get("source_risk_level", row.get("risk_level", "")),
        "fields_preview": row.get("fields_preview", {}),
        "selected_for_admission": True,
        "human_approved": False,
        "requires_apply_confirmation": True,
        "gate_status": "metadata_admission_ready_dry_run",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
    }


def s0149_blocked_record(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "op_id": row.get("op_id", ""),
        "target_id": row.get("target_id", ""),
        "target_title": row.get("target_title", ""),
        "batch_id": row.get("batch_id", ""),
        "patch_lane": row.get("patch_lane", ""),
        "risk_level": row.get("source_risk_level", row.get("risk_level", "")),
        "block_reason": reason,
        "selected_for_admission": True,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
    }


def s0149_preview_record(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    payload["session"] = "S0149"
    payload["source_session"] = "S0147"
    payload["selected_for_admission"] = True
    payload["dry_run"] = True
    payload["human_approved"] = False
    payload["applied_to_canon"] = False
    payload["canon_modified"] = False
    return payload


def write_s0149_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "op_id",
        "target_id",
        "target_title",
        "batch_id",
        "patch_lane",
        "risk_level",
        "fields_preview_keys",
        "gate_status",
        "block_reason",
        "applied_to_canon",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            fields_preview = row.get("fields_preview") if isinstance(row.get("fields_preview"), dict) else {}
            writer.writerow(
                {
                    "op_id": row.get("op_id", ""),
                    "target_id": row.get("target_id", ""),
                    "target_title": row.get("target_title", ""),
                    "batch_id": row.get("batch_id", ""),
                    "patch_lane": row.get("patch_lane", ""),
                    "risk_level": row.get("risk_level", row.get("source_risk_level", "")),
                    "fields_preview_keys": "|".join(sorted(fields_preview)),
                    "gate_status": row.get("gate_status", ""),
                    "block_reason": row.get("block_reason", ""),
                    "applied_to_canon": str(row.get("applied_to_canon") is True).lower(),
                }
            )


def s0149_summary_md(report: dict[str, Any]) -> str:
    lines = [
        "# S0149 metadata admission summary",
        "",
        f"- Selected batches: {report['selected_batch_ids']}",
        f"- Selected operations: {report['selected_operation_count']}",
        f"- Ready operations: {report['admission_ready']}",
        f"- Blocked operations: {report['blocked_records']}",
        f"- Gate blocked: {report['blocked']}",
        f"- Block reasons: {report['block_reasons']}",
        f"- Hashes match: {report['hash_verification']['all_hashes_match']}",
        "- Apply executed: false",
        "- Canon modified: false",
        "- Relations generated: false",
        "- Candidate relations generated: false",
        "- Semantic_text modified in metadata step: false",
        "",
        "## Apply policy",
        f"- Apply requires a successful dry-run and exact token `{S0149_APPLY_TOKEN}`.",
        "- Apply is not executed by dry-run.",
    ]
    return "\n".join(lines) + "\n"


def s0149_operator_flow_md(report: dict[str, Any]) -> str:
    lines = [
        "# S0149 metadata operator flow",
        "",
        "## Estado",
        f"- seleccion_actual: {report['selected_batch_ids']}",
        f"- dry_run_status: {'blocked' if report['blocked'] else 'ready'}",
        f"- admission_ready: {report['admission_ready']}",
        f"- blocked_records: {report['blocked_records']}",
        "- apply_status: not_executed",
        "- canon_modified: false",
        "",
        "## Tokens",
        f"- dry_run_menu_token: `{S0149_DRY_RUN_TOKEN}`",
        f"- apply_token: `{S0149_APPLY_TOKEN}`",
        "",
        "## Separacion",
        "- Este flujo no genera relaciones.",
        "- Este flujo no genera candidate_relations.",
        "- semantic_text authority-aware se ejecuta en ruta separada.",
    ]
    return "\n".join(lines) + "\n"


def s0149_apply_not_executed_report(reason: str, *, dry_run_report: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": "repo-metadata-s0149-apply-report/v1",
        "session": "S0149",
        "apply_executed": False,
        "apply_blocked": True,
        "block_reasons": [reason],
        "records_modified": 0,
        "dry_run_report_ready": bool(dry_run_report and dry_run_report.get("blocked") is False),
        "applied_to_canon": False,
        "canon_modified": False,
        "relations_generated": False,
        "formal_relation_candidates_generated": False,
        "candidate_relations_generated": False,
        "semantic_text_modified": False,
    }


def run_s0149_dry_run(
    *,
    patch_preview: Path = DEFAULT_PATCH_PREVIEW,
    review_batches: Path = DEFAULT_REVIEW_BATCHES,
    patch_hashes: Path = DEFAULT_PATCH_HASHES,
    dry_run_report: Path = DEFAULT_DRY_RUN_REPORT,
    selected_batches: Path = DEFAULT_S0149_SELECTED_BATCHES,
    canon_glob: str = DEFAULT_CANON_GLOB,
    s0146_classification: Path = DEFAULT_CLASSIFICATION,
    out_dir: Path = DEFAULT_S0149_OUT_DIR,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = s0149_paths(out_dir)
    patch_rows = read_jsonl(patch_preview)
    batches_doc = read_json(review_batches)
    batches = batches_doc.get("batches") or {}
    selected_doc = read_json(selected_batches)
    selected_ids = s0149_selected_batch_ids(selected_batches)
    selected_set = set(selected_ids)
    selected_rows = [row for row in patch_rows if row.get("batch_id") in selected_set]

    hash_doc = hash_verification(
        patch_preview=patch_preview,
        review_batches=review_batches,
        patch_hashes=patch_hashes,
        dry_run_report=dry_run_report,
        s0146_classification=s0146_classification,
        canon_glob=canon_glob,
    )
    hash_doc["session"] = "S0149"
    risk_doc = risk_verification_for_batches(selected_ids, patch_rows)
    risk_doc["session"] = "S0149"

    block_reasons: list[str] = []
    if selected_doc.get("valid") is not True:
        block_reasons.append("selected_batches_invalid")
    if not selected_ids:
        block_reasons.append("empty_selection")
    missing = [batch_id for batch_id in selected_ids if batch_id not in batches]
    block_reasons.extend(f"batch_not_found:{batch_id}" for batch_id in missing)
    if EXCLUDED_BATCH in selected_set:
        block_reasons.append("excluded_batch_not_approvable")
    if selected_doc.get("blocked_batch_ids"):
        block_reasons.extend(f"blocked_batch_selected:{batch_id}" for batch_id in selected_doc["blocked_batch_ids"])
    if selected_doc.get("invalid_batch_ids"):
        block_reasons.extend(f"invalid_batch_selected:{batch_id}" for batch_id in selected_doc["invalid_batch_ids"])
    if not hash_doc["all_hashes_match"]:
        block_reasons.extend(f"hash_mismatch:{check['name']}" for check in hash_doc["checks"] if not check["match"])
    invariant_violations = verify_patch_invariants(selected_rows)
    block_reasons.extend(violation["reason"] for violation in invariant_violations)
    if risk_doc["critical_count"] > 0:
        block_reasons.append("critical_risk_in_selected_batches")

    for batch_id in selected_ids:
        if batch_id not in batches:
            continue
        rows = batch_rows(patch_rows, batch_id)
        computed_batch_sha = subset_sha(rows)
        if batches[batch_id].get("patch_sha256") != computed_batch_sha:
            block_reasons.append(f"computed_batch_sha_mismatch:{batch_id}")
        if any(row.get("patch_lane") == "lane_f_excluded_review_required" for row in rows):
            block_reasons.append(f"lane_f_in_selected_batch:{batch_id}")
        if any(row.get("applied_to_canon") is not False for row in rows):
            block_reasons.append(f"applied_record_in_selected_batch:{batch_id}")
        if any(row.get("dry_run") is not True for row in rows):
            block_reasons.append(f"non_dry_run_record_in_selected_batch:{batch_id}")
        if any("relations" in row or "candidate_relations" in row for row in rows):
            block_reasons.append(f"relation_field_in_selected_batch:{batch_id}")

    block_reasons = sorted(set(block_reasons))
    blocked = bool(block_reasons)
    ready_rows = [s0149_ready_record(row) for row in selected_rows] if not blocked else []
    blocked_rows = [s0149_blocked_record(row, ";".join(block_reasons)) for row in selected_rows] if blocked else []
    preview_rows = [s0149_preview_record(row) for row in selected_rows]

    report = {
        "schema": "repo-metadata-s0149-admission-dry-run-report/v1",
        "session": "S0149",
        "source_session": "S0147",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "selected_batches_path": str(selected_batches),
        "selected_batch_ids": selected_ids,
        "selected_operation_count": len(selected_rows),
        "admission_ready": len(ready_rows),
        "blocked_records": len(blocked_rows),
        "blocked": blocked,
        "block_reasons": block_reasons,
        "hash_verification": hash_doc,
        "risk_verification": risk_doc,
        "invariant_violations": invariant_violations,
        "relations_generated": False,
        "formal_relation_candidates_generated": False,
        "candidate_relations_generated": False,
        "semantic_text_modified": False,
        "apply_requires_human_token": S0149_APPLY_TOKEN,
    }

    write_json(paths["dry_run_report"], report)
    write_jsonl(paths["ready"], ready_rows)
    write_jsonl(paths["blocked"], blocked_rows)
    write_jsonl(paths["patch_preview"], preview_rows)
    write_s0149_review_csv(paths["review"], [*ready_rows, *blocked_rows])
    paths["summary"].write_text(s0149_summary_md(report), encoding="utf-8")
    paths["operator_flow"].write_text(s0149_operator_flow_md(report), encoding="utf-8")
    write_json(paths["apply_report"], s0149_apply_not_executed_report("apply_not_requested", dry_run_report=report))
    s0149_audit_event(
        paths["audit"],
        "run_dry_run",
        result="blocked" if blocked else "ready",
        details={
            "selected_batch_ids": selected_ids,
            "admission_ready": len(ready_rows),
            "blocked_records": len(blocked_rows),
            "block_reasons": block_reasons,
        },
    )
    return report


def canon_sha256_lines(canon_glob: str) -> str:
    lines = []
    for path_str in sorted(glob.glob(canon_glob)):
        path = Path(path_str)
        lines.append(f"{file_sha256(path)}  {path.name}")
    return "\n".join(lines) + ("\n" if lines else "")


def backup_s0149_canon(canon_glob: str, out_dir: Path) -> Path:
    paths = s0149_paths(out_dir)
    backup_root = paths["backups"]
    backup_dir = backup_root / "canon_before_apply"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    shards = [Path(path_str) for path_str in sorted(glob.glob(canon_glob))]
    for shard in shards:
        shutil.copy2(shard, backup_dir / shard.name)
    (backup_root / "tiddlers_before_apply.sha256").write_text(canon_sha256_lines(canon_glob), encoding="utf-8")
    manifest = {
        "schema": "repo-metadata-s0149-rollback-manifest/v1",
        "session": "S0149",
        "created_at": utc_now(),
        "backup_dir": str(backup_dir),
        "shards": [
            {
                "source": str(shard),
                "backup": str(backup_dir / shard.name),
                "sha256": file_sha256(shard),
            }
            for shard in shards
        ],
    }
    write_json(backup_root / "rollback_manifest.json", manifest)
    return backup_dir


def title_is_session_or_diagnostic(title: Any) -> bool:
    return bool(SESSION_TITLE_RE.search(str(title or "")))


def applyable_fields_for_row(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    fields = row.get("fields_preview") if isinstance(row.get("fields_preview"), dict) else {}
    applied: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    for key, value in fields.items():
        if key in {"relations", "candidate_relations"}:
            skipped[key] = "relation_fields_forbidden"
            continue
        if key == "artifact_family":
            if row.get("batch_id") != CURRENT_BATCH:
                skipped[key] = "artifact_family_only_allowed_for_current_verified"
                continue
            if value != "artefacto_repositorio":
                skipped[key] = "artifact_family_value_not_allowed"
                continue
            if title_is_session_or_diagnostic(row.get("target_title")):
                skipped[key] = "artifact_family_preserved_for_session_or_diagnostic"
                continue
        applied[key] = value
    return applied, skipped


def apply_s0149_metadata(
    *,
    patch_preview: Path = DEFAULT_PATCH_PREVIEW,
    review_batches: Path = DEFAULT_REVIEW_BATCHES,
    patch_hashes: Path = DEFAULT_PATCH_HASHES,
    s0147_dry_run_report: Path = DEFAULT_DRY_RUN_REPORT,
    dry_run_report_path: Path | None = None,
    selected_batches: Path = DEFAULT_S0149_SELECTED_BATCHES,
    canon_glob: str = DEFAULT_CANON_GLOB,
    s0146_classification: Path = DEFAULT_CLASSIFICATION,
    out_dir: Path = DEFAULT_S0149_OUT_DIR,
    apply_token: str | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = s0149_paths(out_dir)
    dry_path = dry_run_report_path or paths["dry_run_report"]

    def block(reason: str) -> dict[str, Any]:
        report = s0149_apply_not_executed_report(reason)
        write_json(paths["apply_report"], report)
        s0149_audit_event(paths["apply_log"], "apply", result="blocked", details={"reason": reason})
        return report

    if apply_token != S0149_APPLY_TOKEN:
        return block("invalid_or_missing_apply_token")
    if not dry_path.exists():
        return block("missing_successful_dry_run")
    dry_report = read_json(dry_path)
    if dry_report.get("session") != "S0149" or dry_report.get("blocked") is not False:
        return block("dry_run_not_successful")
    selected_ids = s0149_selected_batch_ids(selected_batches)
    if selected_ids != dry_report.get("selected_batch_ids"):
        return block("selected_batches_changed_since_dry_run")

    hash_doc = hash_verification(
        patch_preview=patch_preview,
        review_batches=review_batches,
        patch_hashes=patch_hashes,
        dry_run_report=s0147_dry_run_report,
        s0146_classification=s0146_classification,
        canon_glob=canon_glob,
    )
    hash_doc["session"] = "S0149"
    if not hash_doc["all_hashes_match"]:
        write_json(paths["apply_report"], s0149_apply_not_executed_report("hash_mismatch_before_apply", dry_run_report=dry_report))
        s0149_audit_event(paths["apply_log"], "apply", result="blocked", details={"reason": "hash_mismatch_before_apply", "hash_verification": hash_doc})
        return read_json(paths["apply_report"])

    patch_rows = read_jsonl(patch_preview)
    selected_rows = [row for row in patch_rows if row.get("batch_id") in set(selected_ids)]
    risk_doc = risk_verification_for_batches(selected_ids, patch_rows)
    if risk_doc["critical_count"] > 0:
        return block("critical_risk_in_selected_batches")
    if EXCLUDED_BATCH in selected_ids:
        return block("excluded_batch_not_approvable")
    if verify_patch_invariants(selected_rows):
        return block("patch_invariant_violation")

    before_tree = tree_sha256(canon_glob)
    backup_s0149_canon(canon_glob, out_dir)
    operations_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in selected_rows:
        operations_by_id.setdefault(str(row.get("target_id") or ""), []).append(row)

    applied_records: list[dict[str, Any]] = []
    modified_ids: set[str] = set()
    for shard_str in sorted(glob.glob(canon_glob)):
        shard = Path(shard_str)
        new_lines: list[str] = []
        changed = False
        with shard.open(encoding="utf-8") as handle:
            for raw in handle:
                if not raw.strip():
                    new_lines.append(raw)
                    continue
                record = json.loads(raw)
                record_id = str(record.get("id") or "")
                ops = operations_by_id.get(record_id, [])
                if not ops:
                    new_lines.append(raw if raw.endswith("\n") else raw + "\n")
                    continue
                original = stable_json(record)
                source_fields = record.get("source_fields")
                if not isinstance(source_fields, dict):
                    source_fields = {}
                    record["source_fields"] = source_fields
                applied_fields: dict[str, Any] = {}
                skipped_fields: dict[str, str] = {}
                for op in ops:
                    applyable, skipped = applyable_fields_for_row(op)
                    source_fields.update(applyable)
                    applied_fields.update(applyable)
                    skipped_fields.update(skipped)
                if stable_json(record) != original:
                    changed = True
                    modified_ids.add(record_id)
                applied_records.append(
                    {
                        "target_id": record_id,
                        "target_title": record.get("title", ""),
                        "source_shard": str(shard),
                        "operation_count": len(ops),
                        "applied_fields": applied_fields,
                        "skipped_fields": skipped_fields,
                        "relations_generated": False,
                        "candidate_relations_generated": False,
                    }
                )
                new_lines.append(stable_json(record) + "\n")
        if changed:
            shard.write_text("".join(new_lines), encoding="utf-8")

    after_tree = tree_sha256(canon_glob)
    canon_modified = before_tree != after_tree
    write_jsonl(paths["applied_records"], applied_records)
    before_after = {
        "schema": "repo-metadata-s0149-before-after-hashes/v1",
        "session": "S0149",
        "before_tree_sha256": before_tree,
        "after_tree_sha256": after_tree,
        "canon_modified": canon_modified,
        "before_files": read_json(paths["backups"] / "rollback_manifest.json").get("shards", []),
    }
    write_json(paths["before_after_hashes"], before_after)
    report = {
        "schema": "repo-metadata-s0149-apply-report/v1",
        "session": "S0149",
        "apply_executed": True,
        "apply_blocked": False,
        "block_reasons": [],
        "selected_batch_ids": selected_ids,
        "records_modified": len(modified_ids),
        "applied_records": len(applied_records),
        "applied_to_canon": True,
        "canon_modified": canon_modified,
        "relations_generated": False,
        "formal_relation_candidates_generated": False,
        "candidate_relations_generated": False,
        "semantic_text_modified": False,
        "rollback_available": True,
        "hashes": before_after,
    }
    write_json(paths["apply_report"], report)
    paths["apply_summary"].write_text(
        "\n".join(
            [
                "# S0149 metadata apply summary",
                "",
                f"- apply_executed: {str(report['apply_executed']).lower()}",
                f"- records_modified: {report['records_modified']}",
                f"- canon_modified: {str(canon_modified).lower()}",
                "- relations_generated: false",
                "- candidate_relations_generated: false",
                f"- rollback_manifest: {paths['backups'] / 'rollback_manifest.json'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    s0149_audit_event(
        paths["apply_log"],
        "apply",
        result="applied",
        details={"records_modified": len(modified_ids), "canon_modified": canon_modified},
    )
    return report


def rollback_s0149_metadata(*, out_dir: Path = DEFAULT_S0149_OUT_DIR) -> dict[str, Any]:
    paths = s0149_paths(out_dir)
    manifest_path = paths["backups"] / "rollback_manifest.json"
    if not manifest_path.exists():
        report = {
            "schema": "repo-metadata-s0149-rollback-report/v1",
            "session": "S0149",
            "rollback_executed": False,
            "rollback_blocked": True,
            "block_reasons": ["missing_rollback_manifest"],
            "canon_modified": False,
        }
        write_json(paths["rollback_report"], report)
        s0149_audit_event(paths["rollback_log"], "rollback", result="blocked", details={"reason": "missing_rollback_manifest"})
        return report
    manifest = read_json(manifest_path)
    restored: list[str] = []
    for item in manifest.get("shards") or []:
        source = Path(str(item.get("source") or ""))
        backup = Path(str(item.get("backup") or ""))
        if not backup.exists() or not source.parent.exists():
            continue
        shutil.copy2(backup, source)
        restored.append(str(source))
    report = {
        "schema": "repo-metadata-s0149-rollback-report/v1",
        "session": "S0149",
        "rollback_executed": bool(restored),
        "rollback_blocked": not bool(restored),
        "block_reasons": [] if restored else ["no_shards_restored"],
        "restored_shards": restored,
        "canon_modified": bool(restored),
    }
    write_json(paths["rollback_report"], report)
    s0149_audit_event(paths["rollback_log"], "rollback", result="restored" if restored else "blocked", details={"restored_shards": restored})
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run governed repo metadata admission gates")
    parser.add_argument("--patch-preview", default=str(DEFAULT_PATCH_PREVIEW))
    parser.add_argument("--review-batches", default=str(DEFAULT_REVIEW_BATCHES))
    parser.add_argument("--patch-hashes", default=str(DEFAULT_PATCH_HASHES))
    parser.add_argument("--dry-run-report", default=str(DEFAULT_DRY_RUN_REPORT))
    parser.add_argument("--human-decisions", default=str(DEFAULT_HUMAN_DECISIONS))
    parser.add_argument("--selected-batches", default=str(DEFAULT_S0149_SELECTED_BATCHES))
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--s0146-classification", default=str(DEFAULT_CLASSIFICATION))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--session", default="S0148")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-token", default=None)
    parser.add_argument("--rollback", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session = str(args.session).upper()
    if session == "S0149":
        modes = [args.dry_run, args.apply, args.rollback]
        if sum(bool(item) for item in modes) != 1:
            raise SystemExit("S0149 requires exactly one mode: --dry-run, --apply, or --rollback")
        if args.rollback:
            report = rollback_s0149_metadata(out_dir=Path(args.out_dir))
        elif args.apply:
            report = apply_s0149_metadata(
                patch_preview=Path(args.patch_preview),
                review_batches=Path(args.review_batches),
                patch_hashes=Path(args.patch_hashes),
                s0147_dry_run_report=Path(args.dry_run_report),
                dry_run_report_path=Path(args.out_dir) / "s0149_metadata_admission_dry_run_report.json",
                selected_batches=Path(args.selected_batches),
                canon_glob=args.canon_glob,
                s0146_classification=Path(args.s0146_classification),
                out_dir=Path(args.out_dir),
                apply_token=args.apply_token,
            )
        else:
            report = run_s0149_dry_run(
                patch_preview=Path(args.patch_preview),
                review_batches=Path(args.review_batches),
                patch_hashes=Path(args.patch_hashes),
                dry_run_report=Path(args.dry_run_report),
                selected_batches=Path(args.selected_batches),
                canon_glob=args.canon_glob,
                s0146_classification=Path(args.s0146_classification),
                out_dir=Path(args.out_dir),
            )
        print(stable_json(report))
        return 0

    if not args.dry_run:
        raise SystemExit("S0148 only supports --dry-run")
    report = run_gate(
        patch_preview=Path(args.patch_preview),
        review_batches=Path(args.review_batches),
        patch_hashes=Path(args.patch_hashes),
        dry_run_report=Path(args.dry_run_report),
        human_decisions=Path(args.human_decisions),
        canon_glob=args.canon_glob,
        s0146_classification=Path(args.s0146_classification),
        out_dir=Path(args.out_dir),
        session=args.session,
        dry_run=args.dry_run,
    )
    print(stable_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
