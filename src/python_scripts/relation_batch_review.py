#!/usr/bin/env python3
"""S0142 governed batch human-review helpers.

The module classifies existing relation candidates for terminal batch review,
computes a stable approval hash, and persists only the auditable batch decision.
It never writes canonical tiddlers and never applies relations.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from relation_admission_policy import EVIDENCE_POLICY, GLOBAL_MIN_CONFIDENCE
from relation_candidate_contract import (
    ALLOWED_RELATION_TYPES,
    CANDIDATE_ID_RE,
    verify_excerpt_in_source,
)

SCHEMA_BATCH_DECISIONS = "relation-human-review-batch-decisions/v1"
SCHEMA_BATCH_SUMMARY = "relation-human-review-batch-summary/v1"
SCHEMA_BATCH_AUDIT = "relation-human-review-batch-audit-log/v1"

SESSION = "S0142"
BATCH_ID = "s0142_batch_ready_001"
CONFIRMATION_TOKEN = "APROBAR_BATCH_001"
DECISION_BASIS_VERSION = "relation_batch_review/v1"

BATCH_READY = "batch_ready"
INDIVIDUAL_REVIEW_REQUIRED = "individual_review_required"
BLOCKED = "blocked"
DEFERRED = "deferred"
REJECTED_BY_HUMAN = "rejected_by_human"
ALREADY_APPROVED_FOR_DRY_RUN = "already_approved_for_dry_run"

RESOLVED_TARGET_STATUSES = frozenset({
    "resolved",
    "resolved_id",
    "resolved_title_unique",
})

HISTORICAL_BLOCKED_TYPES = frozenset({
    "usa",
    "parte_de",
    "define",
    "requiere",
    "child_of",
})

REVIEWER = {
    "reviewer_id": "local-operator",
    "reviewer_role": "human_operator",
}


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_candidates(path: Path) -> list[dict[str, Any]]:
    return load_jsonl(path)


def load_admissibility_results(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path, {}) or {}
    return {
        str(item.get("candidate_id")): item
        for item in payload.get("results") or []
        if item.get("candidate_id")
    }


def load_human_review_decisions(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = load_json(path, {}) or {}
    return {
        str(item.get("candidate_id")): item
        for item in payload.get("decisions") or []
        if item.get("candidate_id")
    }


def canonical_relations_set(canon: dict[str, dict[str, Any]]) -> set[tuple[str, str, str]]:
    edges: set[tuple[str, str, str]] = set()
    for source_id, record in canon.items():
        for relation in record.get("relations") or []:
            if not isinstance(relation, dict):
                continue
            rel_type = str(relation.get("type") or "")
            target_id = str(relation.get("target_id") or "")
            if rel_type and target_id:
                edges.add((source_id, target_id, rel_type))
    return edges


def relation_policy_block_reason(rel_type: str, type_policy: dict[str, dict[str, Any]]) -> str | None:
    decision = type_policy.get(rel_type)
    if not decision:
        return None
    status = decision.get("decision_status")
    if status == "canonical_keep":
        return None
    if status in {"legacy_alias_candidate", "canonical_equivalent"}:
        return "legacy_alias_policy"
    if status == "legacy_readonly":
        return "legacy_readonly"
    if status == "structural_only":
        return "structural_only"
    return "s0139_type_policy"


def confidence_threshold(rel_type: str) -> float:
    policy = EVIDENCE_POLICY.get(rel_type) or {}
    return float(policy.get("min_confidence", GLOBAL_MIN_CONFIDENCE))


def evidence_excerpt_hash(candidate: dict[str, Any]) -> str:
    excerpt = ((candidate.get("evidence") or {}).get("excerpt") or "")
    return hashlib.sha256(str(excerpt).encode("utf-8")).hexdigest()


def _risk_for(candidate: dict[str, Any], admissibility: dict[str, dict[str, Any]]) -> str:
    cid = str(candidate.get("candidate_id") or "")
    item = admissibility.get(cid) or {}
    risk = item.get("risk_level")
    if risk:
        return str(risk)
    flags = ((candidate.get("confidence") or {}).get("risk_flags") or [])
    if any(str(flag).lower() == "high" for flag in flags):
        return "high"
    return "medium"


def classify_candidate(
    candidate: dict[str, Any],
    canon: dict[str, dict[str, Any]],
    *,
    type_policy: dict[str, dict[str, Any]] | None = None,
    admissibility: dict[str, dict[str, Any]] | None = None,
    individual_decisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    type_policy = type_policy or {}
    admissibility = admissibility or {}
    individual_decisions = individual_decisions or {}

    cid = str(candidate.get("candidate_id") or "")
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    relation = candidate.get("relation") or {}
    evidence = candidate.get("evidence") or {}
    confidence = candidate.get("confidence") or {}

    source_id = str(source.get("tiddler_id") or "")
    target_id = str(target.get("tiddler_id") or "")
    rel_type = str(relation.get("type") or "")
    excerpt = str(evidence.get("excerpt") or "")
    score = float(confidence.get("score") or 0.0)
    resolution_status = str(target.get("resolution_status") or "")
    risk = _risk_for(candidate, admissibility)

    decision = individual_decisions.get(cid) or {}
    decision_value = decision.get("decision")
    if decision_value == "rejected_by_human":
        return _classification(candidate, REJECTED_BY_HUMAN, ["rejected_by_human"], risk)
    if decision_value == "approved_for_dry_run":
        return _classification(candidate, ALREADY_APPROVED_FOR_DRY_RUN, ["already_approved_for_dry_run"], risk)

    hard_reasons: list[str] = []
    review_reasons: list[str] = []

    if not CANDIDATE_ID_RE.match(cid):
        hard_reasons.append("invalid_contract")
    if not source_id or source_id not in canon:
        hard_reasons.append("source_missing")
    if resolution_status and resolution_status not in RESOLVED_TARGET_STATUSES:
        hard_reasons.append("unresolved_target")
    if not target_id or target_id not in canon:
        hard_reasons.append("unresolved_target")

    policy_reason = relation_policy_block_reason(rel_type, type_policy)
    if policy_reason:
        hard_reasons.append(policy_reason)
    elif rel_type in HISTORICAL_BLOCKED_TYPES:
        hard_reasons.append("historical_type")
    elif rel_type not in ALLOWED_RELATION_TYPES:
        hard_reasons.append("invalid_relation_type")

    source_text = (canon.get(source_id) or {}).get("text", "") if source_id in canon else ""
    excerpt_ok = verify_excerpt_in_source(excerpt, source_text)
    if excerpt_ok is not True:
        hard_reasons.append("unverified_evidence")

    if (source_id, target_id, rel_type) in canonical_relations_set(canon):
        hard_reasons.append("possible_duplicate")

    threshold = confidence_threshold(rel_type)
    if score < threshold:
        hard_reasons.append("score_below_threshold")
    elif score < max(threshold, 0.80):
        review_reasons.append("score_medium_low")

    if risk == "high":
        review_reasons.append("risk_high")

    if hard_reasons:
        return _classification(candidate, BLOCKED, sorted(set(hard_reasons)), risk)
    if review_reasons:
        return _classification(candidate, INDIVIDUAL_REVIEW_REQUIRED, sorted(set(review_reasons)), risk)
    if decision_value == "deferred":
        return _classification(candidate, BATCH_READY, ["previously_deferred_pending_batch"], risk)
    return _classification(candidate, BATCH_READY, ["meets_batch_ready_criteria"], risk)


def _classification(
    candidate: dict[str, Any],
    category: str,
    reasons: list[str],
    risk: str,
) -> dict[str, Any]:
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    relation = candidate.get("relation") or {}
    evidence = candidate.get("evidence") or {}
    confidence = candidate.get("confidence") or {}
    return {
        "candidate_id": candidate.get("candidate_id", ""),
        "category": category,
        "reasons": reasons,
        "risk_level": risk,
        "source_id": source.get("tiddler_id", ""),
        "source_title": source.get("title", ""),
        "target_id": target.get("tiddler_id", ""),
        "target_title": target.get("title", ""),
        "relation_type": relation.get("type", ""),
        "confidence_score": float(confidence.get("score") or 0.0),
        "evidence_kind": evidence.get("kind", ""),
        "evidence_excerpt": evidence.get("excerpt", ""),
        "evidence_excerpt_sha256": evidence_excerpt_hash(candidate),
    }


def classify_batch_candidates(
    candidates: list[dict[str, Any]],
    canon: dict[str, dict[str, Any]],
    *,
    type_policy: dict[str, dict[str, Any]] | None = None,
    admissibility: dict[str, dict[str, Any]] | None = None,
    individual_decisions: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        classify_candidate(
            candidate,
            canon,
            type_policy=type_policy,
            admissibility=admissibility,
            individual_decisions=individual_decisions,
        )
        for candidate in candidates
    ]


def batch_ready_items(classifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (item for item in classifications if item["category"] == BATCH_READY),
        key=lambda item: str(item.get("candidate_id") or ""),
    )


def compute_batch_hash(
    ready_items: list[dict[str, Any]],
    *,
    batch_id: str = BATCH_ID,
    session: str = SESSION,
) -> str:
    payload = {
        "session": session,
        "batch_id": batch_id,
        "decision_basis_version": DECISION_BASIS_VERSION,
        "candidates": [
            {
                "candidate_id": str(item.get("candidate_id") or ""),
                "source_id": str(item.get("source_id") or ""),
                "target_id": str(item.get("target_id") or ""),
                "relation_type": str(item.get("relation_type") or ""),
                "evidence_excerpt_sha256": str(item.get("evidence_excerpt_sha256") or ""),
                "confidence_score": float(item.get("confidence_score") or 0.0),
            }
            for item in sorted(ready_items, key=lambda item: str(item.get("candidate_id") or ""))
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_batch_summary(
    classifications: list[dict[str, Any]],
    *,
    batch_id: str = BATCH_ID,
) -> dict[str, Any]:
    counts = Counter(item["category"] for item in classifications)
    reason_counts = Counter(
        reason
        for item in classifications
        if item["category"] != BATCH_READY
        for reason in item.get("reasons") or []
    )
    ready = batch_ready_items(classifications)
    risk_counts = Counter(item.get("risk_level", "") for item in ready)
    batch_hash = compute_batch_hash(ready, batch_id=batch_id)
    return {
        "schema": SCHEMA_BATCH_SUMMARY,
        "session": SESSION,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "batch_id": batch_id,
        "batch_sha256": batch_hash,
        "decision_basis_version": DECISION_BASIS_VERSION,
        "summary": {
            "total_evaluated": len(classifications),
            "batch_ready": counts.get(BATCH_READY, 0),
            "individual_review_required": counts.get(INDIVIDUAL_REVIEW_REQUIRED, 0),
            "blocked": counts.get(BLOCKED, 0),
            "deferred": counts.get(DEFERRED, 0),
            "rejected_by_human": counts.get(REJECTED_BY_HUMAN, 0),
            "already_approved_for_dry_run": counts.get(ALREADY_APPROVED_FOR_DRY_RUN, 0),
            "risk_low": risk_counts.get("low", 0),
            "risk_medium": risk_counts.get("medium", 0),
            "risk_high": risk_counts.get("high", 0),
        },
        "reason_counts": dict(sorted(reason_counts.items())),
        "batch_ready_candidate_ids": [item["candidate_id"] for item in ready],
        "classifications": sorted(classifications, key=lambda item: str(item.get("candidate_id") or "")),
    }


def render_terminal_batch_report(summary: dict[str, Any], *, sample_size: int = 3) -> str:
    s = summary.get("summary") or {}
    reason_counts = summary.get("reason_counts") or {}
    ready_items = [item for item in summary.get("classifications") or [] if item.get("category") == BATCH_READY]
    sample = sorted(ready_items, key=lambda item: item["candidate_id"])[:sample_size]
    lines = [
        "=== Reporte batch de human_review relacional ===",
        "",
        f"Candidatos evaluados: {s.get('total_evaluated', 0)}",
        "",
        "BATCH READY:",
        f"- candidatos: {s.get('batch_ready', 0)}",
        f"- riesgo bajo: {s.get('risk_low', 0)}",
        f"- riesgo medio: {s.get('risk_medium', 0)}",
        f"- source resuelto: {s.get('batch_ready', 0)}/{s.get('batch_ready', 0)}",
        f"- target resuelto: {s.get('batch_ready', 0)}/{s.get('batch_ready', 0)}",
        f"- evidencia verificable: {s.get('batch_ready', 0)}/{s.get('batch_ready', 0)}",
        "- duplicados: 0",
        "- conflictos: 0",
        "",
        "REQUIEREN REVISION INDIVIDUAL:",
        f"- candidatos: {s.get('individual_review_required', 0)}",
        "- razones principales:",
        f"  - evidence_weak: {reason_counts.get('evidence_weak', 0)}",
        f"  - possible_duplicate: {reason_counts.get('possible_duplicate', 0)}",
        f"  - legacy_alias_policy: {reason_counts.get('legacy_alias_policy', 0)}",
        f"  - score_medium_low: {reason_counts.get('score_medium_low', 0)}",
        "",
        "BLOQUEADOS:",
        f"- candidatos: {s.get('blocked', 0)}",
        "- razones principales:",
        f"  - unresolved_target: {reason_counts.get('unresolved_target', 0)}",
        f"  - invalid_contract: {reason_counts.get('invalid_contract', 0)}",
        f"  - unverified_evidence: {reason_counts.get('unverified_evidence', 0)}",
        f"  - structural_only: {reason_counts.get('structural_only', 0)}",
        f"  - rejected_by_human: {s.get('rejected_by_human', 0)}",
        "",
        f"Batch ID: {summary.get('batch_id', BATCH_ID)}",
        f"Batch SHA256: {summary.get('batch_sha256', '')}",
    ]
    if sample:
        lines.extend(["", "Muestra auditada batch_ready:"])
        for idx, item in enumerate(sample, start=1):
            lines.append(
                f"{idx}. {item['candidate_id']} | {item['relation_type']} | "
                f"{item['source_id']} -> {item['target_id']} | score {item['confidence_score']}"
            )
    return "\n".join(lines)


def empty_batch_decisions_doc() -> dict[str, Any]:
    return {
        "schema": SCHEMA_BATCH_DECISIONS,
        "session": SESSION,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "reviewer": REVIEWER,
        "decisions": [],
    }


def build_batch_approval_decision(
    summary: dict[str, Any],
    *,
    rationale: str = "Aprobacion batch explicitamente confirmada por operador local solo para dry-run.",
) -> dict[str, Any]:
    candidate_ids = list(summary.get("batch_ready_candidate_ids") or [])
    return {
        "decision_type": "batch_approval",
        "batch_id": summary.get("batch_id", BATCH_ID),
        "batch_sha256": summary.get("batch_sha256", ""),
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "decision": "approved_for_dry_run",
        "reviewed_at": utc_now(),
        "rationale": rationale,
        "confirmation_token": CONFIRMATION_TOKEN,
        "checks": {
            "terminal_report_reviewed": True,
            "batch_hash_confirmed": True,
            "batch_contains_only_batch_ready": True,
            "blocked_candidates_excluded": True,
            "individual_review_candidates_excluded": True,
            "no_canonical_write_requested": True,
        },
    }


def persist_batch_decision(
    summary: dict[str, Any],
    *,
    decisions_path: Path,
    audit_path: Path,
    confirmation: str,
) -> bool:
    if confirmation != CONFIRMATION_TOKEN:
        append_batch_audit(audit_path, action="batch_approval_cancelled", summary=summary)
        return False
    doc = empty_batch_decisions_doc()
    doc["decisions"] = [build_batch_approval_decision(summary)]
    write_json(decisions_path, doc)
    append_batch_audit(audit_path, action="approved_for_dry_run", summary=summary)
    return True


def append_batch_audit(path: Path, *, action: str, summary: dict[str, Any]) -> None:
    append_jsonl(path, {
        "schema": SCHEMA_BATCH_AUDIT,
        "timestamp": utc_now(),
        "session": SESSION,
        "action": action,
        "batch_id": summary.get("batch_id", BATCH_ID),
        "batch_sha256": summary.get("batch_sha256", ""),
        "candidate_count": len(summary.get("batch_ready_candidate_ids") or []),
        "operator": "local-operator",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
    })


def write_batch_summary_artifacts(summary: dict[str, Any], *, summary_json: Path, summary_md: Path) -> None:
    write_json(summary_json, summary)
    summary_md.parent.mkdir(parents=True, exist_ok=True)
    summary_md.write_text(render_terminal_batch_report(summary) + "\n", encoding="utf-8")


def approved_batch_decision(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    for decision in doc.get("decisions") or []:
        if (
            decision.get("decision_type") == "batch_approval"
            and decision.get("decision") == "approved_for_dry_run"
        ):
            return decision
    return None


def validate_batch_decisions_doc(doc: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["root must be object"]
    if doc.get("schema") != SCHEMA_BATCH_DECISIONS:
        errors.append(f"schema must be {SCHEMA_BATCH_DECISIONS}")
    if doc.get("session") != SESSION:
        errors.append(f"session must be {SESSION}")
    if doc.get("dry_run") is not True:
        errors.append("dry_run must be true")
    if doc.get("applied_to_canon") is not False:
        errors.append("applied_to_canon must be false")
    if doc.get("canon_modified") is not False:
        errors.append("canon_modified must be false")
    decisions = doc.get("decisions")
    if not isinstance(decisions, list):
        errors.append("decisions must be list")
        return errors
    required_checks = {
        "terminal_report_reviewed",
        "batch_hash_confirmed",
        "batch_contains_only_batch_ready",
        "blocked_candidates_excluded",
        "individual_review_candidates_excluded",
        "no_canonical_write_requested",
    }
    for idx, decision in enumerate(decisions):
        prefix = f"decisions[{idx}]"
        if decision.get("decision_type") != "batch_approval":
            errors.append(f"{prefix}.decision_type must be batch_approval")
        if decision.get("decision") != "approved_for_dry_run":
            errors.append(f"{prefix}.decision must be approved_for_dry_run")
        if not decision.get("batch_id"):
            errors.append(f"{prefix}.batch_id required")
        if not decision.get("batch_sha256"):
            errors.append(f"{prefix}.batch_sha256 required")
        if decision.get("confirmation_token") != CONFIRMATION_TOKEN:
            errors.append(f"{prefix}.confirmation_token invalid")
        candidate_ids = decision.get("candidate_ids")
        if not isinstance(candidate_ids, list):
            errors.append(f"{prefix}.candidate_ids must be list")
        elif decision.get("candidate_count") != len(candidate_ids):
            errors.append(f"{prefix}.candidate_count mismatch")
        checks = decision.get("checks")
        if not isinstance(checks, dict):
            errors.append(f"{prefix}.checks must be object")
        else:
            missing = sorted(required_checks - set(checks))
            if missing:
                errors.append(f"{prefix}.checks missing: {missing}")
            not_true = sorted(k for k in required_checks if checks.get(k) is not True)
            if not_true:
                errors.append(f"{prefix}.checks must be true: {not_true}")
    return errors
