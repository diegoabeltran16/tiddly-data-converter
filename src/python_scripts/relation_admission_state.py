#!/usr/bin/env python3
"""Read-only assembler for the live relational admission state.

The assembler owns no generation, reconciliation, review, gate, apply, or
rollback behavior.  It validates bindings between their durable artifacts and
the runtime canon, then emits one operator-facing state and next action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
LOCAL_ROOT = REPO_ROOT / "data" / "out" / "local"
CURRENT_DIR = LOCAL_ROOT / "pipeline" / "relation_candidates" / "current"
AUDIT_DIR = LOCAL_ROOT / "audit" / "relation_admission" / "current"
S0180_AUDIT = LOCAL_ROOT / "audit" / "s0180"
BASELINE = S0180_AUDIT / "pre_relational_rag_baseline_manifest.json"
STATE_REPORT = AUDIT_DIR / "relational_operational_state.json"
AUDIT_INDEX = AUDIT_DIR / "relational_audit_index.json"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, "missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, f"invalid:{error}"
    return (value, None) if isinstance(value, dict) else ({}, "invalid:object_required")


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not path.exists():
        return [], "missing"
    rows: list[dict[str, Any]] = []
    try:
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                return [], f"invalid:line_{line_no}_object_required"
            rows.append(value)
    except (OSError, json.JSONDecodeError) as error:
        return [], f"invalid:{error}"
    return rows, None


def write_json(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def display(path: Path, repo_root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def canon_snapshot(local_root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    records = 0
    shards = sorted(local_root.glob("tiddlers_*.jsonl"))
    for shard in shards:
        data = shard.read_bytes()
        digest.update(data)
        records += sum(1 for line in data.splitlines() if line.strip())
    return {"hash": digest.hexdigest(), "records": records, "shards": len(shards), "current": True}


def count_decisions(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("human_review_decision") or row.get("decision") or "unknown") for row in rows)
    return {
        "total": len(rows),
        "approved": counts.get("approved_for_admission", 0),
        "rejected": counts.get("rejected", 0),
        "deferred": counts.get("deferred", 0),
    }


def canonical_relation_v1_count(local_root: Path) -> int:
    total = 0
    for shard in sorted(local_root.glob("tiddlers_*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            for relation in row.get("relations") or []:
                if isinstance(relation, dict) and (relation.get("schema_version") or relation.get("relation_schema")) == "canonical-relation/v1":
                    total += 1
    return total


def build_state(
    local_root: Path = LOCAL_ROOT,
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    audit_dir = local_root / "audit" / "relation_admission" / "current"
    s0180_audit = local_root / "audit" / "s0180"
    baseline_path = s0180_audit / "pre_relational_rag_baseline_manifest.json"
    candidate_manifest_path = current_dir / "current_candidate_manifest.json"
    validation_path = current_dir / "validation_report.json"
    reconciliation_path = current_dir / "reconciliation_manifest.json"
    reviewable_path = current_dir / "reviewable_candidate_manifest.json"
    decisions_path = current_dir / "human_review_decisions.jsonl"
    gate_path = audit_dir / "admission_gate_dry_run.json"
    run_manifest_path = audit_dir / "current_run_manifest.json"
    apply_path = audit_dir / "relation_apply_report.json"

    canon = canon_snapshot(local_root)
    baseline, baseline_error = read_json(baseline_path)
    candidate, candidate_error = read_json(candidate_manifest_path)
    validation, validation_error = read_json(validation_path)
    reconciliation, reconciliation_error = read_json(reconciliation_path)
    reviewable, reviewable_error = read_json(reviewable_path)
    decisions, decisions_error = read_jsonl(decisions_path)
    gate, gate_error = read_json(gate_path)
    run_manifest, run_manifest_error = read_json(run_manifest_path)
    apply_report, apply_error = read_json(apply_path)

    generator = REPO_ROOT / "src" / "python_scripts" / "generate_technical_relation_candidates.py"
    contract = REPO_ROOT / "src" / "python_scripts" / "relation_candidate_contract.py"
    policy = REPO_ROOT / "src" / "python_scripts" / "relation_admission_policy.py"
    reconciler = REPO_ROOT / "src" / "python_scripts" / "reconcile_current_relation_candidates.py"
    candidate_manifest_hash = sha256_file(candidate_manifest_path)
    reconciliation_hash = sha256_file(reconciliation_path)
    reviewable_hash = sha256_file(reviewable_path)

    candidate_reasons: list[str] = []
    if candidate_error:
        candidate_reasons.append(f"candidate_manifest_{candidate_error}")
    else:
        binding = candidate.get("canon_binding") or {}
        producer = candidate.get("producer") or {}
        if binding.get("canon_hash") != canon["hash"]:
            candidate_reasons.append("stale_canon_changed")
        if producer.get("hash") != sha256_file(generator):
            candidate_reasons.append("stale_candidate_generator_changed")
        if producer.get("contract_hash") != sha256_file(contract):
            candidate_reasons.append("stale_candidate_contract_changed")
        batch = candidate.get("candidate_batch") or {}
        batch_path = current_dir / "relation_candidates.jsonl"
        if batch.get("hash") != sha256_file(batch_path):
            candidate_reasons.append("stale_candidate_batch_changed")

    reconciliation_reasons: list[str] = []
    if reconciliation_error:
        reconciliation_reasons.append(f"reconciliation_manifest_{reconciliation_error}")
    else:
        if reconciliation.get("candidate_manifest_hash") != candidate_manifest_hash:
            reconciliation_reasons.append("stale_candidate_manifest_changed")
        if reconciliation.get("canon_hash") != canon["hash"]:
            reconciliation_reasons.append("stale_canon_changed")
        if reconciliation.get("predicate_policy_hash") != sha256_file(policy):
            reconciliation_reasons.append("stale_predicate_policy_changed")
        if reconciliation.get("candidate_contract_hash") != sha256_file(contract):
            reconciliation_reasons.append("stale_candidate_contract_changed")
        if reconciliation.get("reconciler_hash") != sha256_file(reconciler):
            reconciliation_reasons.append("stale_reconciler_changed")

    reviewable_reasons: list[str] = []
    if reviewable_error:
        reviewable_reasons.append(f"reviewable_manifest_{reviewable_error}")
    else:
        if reviewable.get("canon_hash") != canon["hash"]:
            reviewable_reasons.append("stale_canon_changed")
        if reviewable.get("candidate_manifest_hash") != candidate_manifest_hash:
            reviewable_reasons.append("stale_candidate_manifest_changed")
        if reviewable.get("reconciliation_manifest_hash") != reconciliation_hash:
            reviewable_reasons.append("stale_reconciliation_manifest_changed")
        if reviewable.get("predicate_policy_hash") != sha256_file(policy):
            reviewable_reasons.append("stale_predicate_policy_changed")

    validation_summary = validation.get("summary") or {}
    reconciliation_counts = reconciliation.get("dispositions") or {}
    ready_count = int(reconciliation_counts.get("ready_for_review") or 0)
    blocked_count = max(0, int(reconciliation.get("total") or 0) - ready_count)
    decision_counts = count_decisions(decisions)
    decision_stale = bool(decisions and (candidate_reasons or reconciliation_reasons or reviewable_reasons))
    gate_summary = gate.get("summary") or {}
    gate_items = gate.get("items") or []
    gate_decisions = Counter(str(item.get("decision") or "unknown") for item in gate_items if isinstance(item, dict))
    gate_reasons: list[str] = []
    if gate_error:
        gate_reasons.append(f"admission_gate_report_{gate_error}")
    if run_manifest_error:
        gate_reasons.append(f"current_run_manifest_{run_manifest_error}")
    log_path = audit_dir / "current_relation_admission_log.jsonl"
    if not gate_error and run_manifest.get("report_hash") != sha256_file(gate_path):
        gate_reasons.append("current_run_manifest_report_hash_mismatch")
    if not run_manifest_error and run_manifest.get("log_hash") != sha256_file(log_path):
        gate_reasons.append("current_run_manifest_log_hash_mismatch")
    gate_current = bool(
        not gate_reasons
        and run_manifest.get("canon_hash") == canon["hash"]
        and run_manifest.get("candidate_manifest_hash") == candidate_manifest_hash
        and run_manifest.get("reviewable_manifest_hash") == reviewable_hash
    )

    blocking_reasons = candidate_reasons + reconciliation_reasons + reviewable_reasons
    if candidate_error == "missing":
        verdict = "NO_CURRENT_RELATION_CANDIDATE_MANIFEST"
        next_action = "GENERATE_CURRENT_RELATION_CANDIDATES"
    elif candidate_reasons:
        verdict = "CURRENT_RELATION_CANDIDATES_STALE"
        next_action = "REFRESH_CURRENT_RELATION_CANDIDATES"
    elif reconciliation_reasons or reviewable_reasons:
        verdict = "CURRENT_RELATION_CANDIDATES_REQUIRE_RECONCILIATION"
        next_action = "VALIDATE_AND_RECONCILE_CURRENT_CANDIDATES"
    elif not gate_current:
        verdict = "RELATIONAL_ADMISSION_CURRENT_RUN_INCOMPLETE"
        next_action = "RUN_RELATIONAL_ADMISSION_GATE_DRY_RUN"
    elif ready_count > 0 and decision_counts["total"] == 0:
        verdict = "READY_FOR_HUMAN_RELATIONAL_REVIEW"
        next_action = "OPEN_S0181_HUMAN_RELATIONAL_REVIEW"
    elif decision_counts["total"] and decision_counts["approved"] < ready_count:
        verdict = "HUMAN_RELATIONAL_REVIEW_INCOMPLETE"
        next_action = "CONTINUE_HUMAN_RELATIONAL_REVIEW"
    elif gate_summary.get("admission_ready_dry_run", 0):
        verdict = "READY_FOR_RELATIONAL_ADMISSION"
        next_action = "APPLY_REQUIRES_EXPLICIT_CONFIRMATION"
    else:
        verdict = "RELATIONAL_ADMISSION_BLOCKED"
        next_action = "RUN_RELATIONAL_ADMISSION_GATE_DRY_RUN"

    state = {
        "schema_version": "relational-operational-state/v1",
        "checked_at": checked_at or now(),
        "canon": canon,
        "baseline": {
            "path": display(baseline_path),
            "hash": sha256_file(baseline_path),
            "canon_hash": baseline.get("canon_hash"),
            "immutable": True,
            "authority_for_current_operation": False,
            "error": baseline_error,
        },
        "candidate_generation": {
            "manifest_path": display(candidate_manifest_path),
            "manifest_hash": candidate_manifest_hash,
            "bound_canon_hash": (candidate.get("canon_binding") or {}).get("canon_hash"),
            "total": (candidate.get("candidate_batch") or {}).get("record_count", 0),
            "current": not candidate_reasons,
            "stale_reasons": candidate_reasons,
        },
        "validation": {
            "report_path": display(validation_path),
            "total": validation_summary.get("total", 0),
            "valid": validation_summary.get("valid", 0),
            "invalid": validation_summary.get("invalid", 0),
            "unresolved": validation_summary.get("unresolved_target", 0),
            "duplicates": validation_summary.get("duplicate", 0),
            "current": not validation_error and int(validation_summary.get("total") or 0) == int((candidate.get("candidate_batch") or {}).get("record_count") or 0),
        },
        "reconciliation": {
            "manifest_path": display(reconciliation_path),
            "total": reconciliation.get("total", 0),
            "unclassified": reconciliation.get("unclassified", 0),
            "ready_for_review": ready_count,
            "blocked": blocked_count,
            "dispositions": reconciliation_counts,
            "historical_occurrences": reconciliation.get("historical_occurrences") or {},
            "current": not reconciliation_reasons,
            "stale_reasons": reconciliation_reasons,
        },
        "human_review": {
            "decisions_path": display(decisions_path),
            **decision_counts,
            "stale": len(decisions) if decision_stale else 0,
            "current": not decisions_error and not decision_stale,
        },
        "admission_gate": {
            "report_path": display(gate_path),
            "evaluated": gate_summary.get("total_evaluated", 0),
            "technically_invalid": gate_summary.get("technically_invalid", 0),
            "awaiting_human_review": gate_summary.get("awaiting_human_review", gate_decisions.get("blocked_missing_human_review", 0)),
            "human_rejected": gate_summary.get("human_rejected", gate_decisions.get("rejected_by_human", 0)),
            "human_deferred": gate_summary.get("human_deferred", 0),
            "approved_for_admission": gate_summary.get("approved_for_admission", 0),
            "admission_ready": gate_summary.get("admission_ready_dry_run", 0),
            "current": gate_current,
            "stale_reasons": gate_reasons,
        },
        "apply": {
            "executed": bool(apply_report.get("status") == "applied"),
            "applied_count": apply_report.get("applied_count", 0),
            "receipt_path": display(apply_path) if not apply_error else None,
            "canon_modified": bool(apply_report.get("canon_modified") is True),
            "current": bool(not apply_error and gate_current),
        },
        "rollback": {
            "available": bool(apply_report.get("canon_modified") is True and apply_report.get("rollback_snapshot")),
            "receipt_bound": False,
            "snapshot_path": apply_report.get("rollback_snapshot"),
            "current": False,
        },
        "canonical_relation_v1": canonical_relation_v1_count(local_root),
        "verdict": verdict,
        "next_action": next_action,
        "blocking_reasons": sorted(set(blocking_reasons)),
        "warnings": [
            warning for warning in (
                "baseline_is_historical_not_operational" if baseline else None,
                "admission_gate_current_run_missing_or_stale" if not gate_current else None,
                "data_tmp_is_not_an_operational_dependency",
            ) if warning
        ],
    }
    return state


def build_audit_index(local_root: Path = LOCAL_ROOT, *, checked_at: str | None = None) -> dict[str, Any]:
    state = build_state(local_root, checked_at=checked_at)
    current_dir = local_root / "pipeline" / "relation_candidates" / "current"
    audit_dir = local_root / "audit" / "relation_admission" / "current"
    paths = [
        current_dir / "current_candidate_manifest.json",
        current_dir / "validation_report.json",
        current_dir / "reconciliation_manifest.json",
        current_dir / "reviewable_candidate_manifest.json",
        current_dir / "human_review_decisions.jsonl",
        audit_dir / "current_run_manifest.json",
        audit_dir / "admission_gate_dry_run.json",
        audit_dir / "relation_apply_report.json",
    ]
    return {
        "schema_version": "relational-audit-index/v1",
        "checked_at": checked_at or now(),
        "state": state,
        "artifacts": [
            {"path": display(path), "exists": path.exists(), "sha256": sha256_file(path)}
            for path in paths
        ],
        "history_path": display(local_root / "audit" / "relation_admission" / "history"),
        "tmp_dependency": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble live relational admission state")
    parser.add_argument("command", choices=("state", "audit", "validate-currentness"))
    parser.add_argument("--local-root", type=Path, default=LOCAL_ROOT)
    args = parser.parse_args(argv)
    audit_dir = args.local_root / "audit" / "relation_admission" / "current"
    if args.command == "audit":
        payload = build_audit_index(args.local_root)
        write_json(audit_dir / "relational_operational_state.json", payload["state"])
        write_json(audit_dir / "relational_audit_index.json", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    state = build_state(args.local_root)
    if args.command == "state":
        write_json(audit_dir / "relational_operational_state.json", state)
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    if any(reason.startswith("invalid") for reason in state["blocking_reasons"]):
        return 1
    return 0 if state["candidate_generation"]["current"] and state["reconciliation"]["current"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
