#!/usr/bin/env python3
"""relation_admission_gate.py — S0137 / S0165

Compuerta humana mínima de admisión relacional y motor apply protegido.

Evalúa relaciones candidatas y determina si podrían avanzar a admisión real,
exigiendo aprobación humana explícita + compatibilidad de tipo relacional.

Por defecto opera en dry-run y no modifica tiddlers_*.jsonl. El modo --apply
existe como capacidad técnica protegida: requiere revisión humana persistente,
dry-run reciente, plan previo, ausencia de bloqueos P0 y confirmación externa
exacta. El operador humano, no el agente, decide ejecutarlo.

Uso
---
  # Evaluar candidatos y generar log + reporte dry-run
  python3 relation_admission_gate.py \\
    --candidates-file data/out/local/pipeline/relations_candidates/s0129/valid_candidates.jsonl \\
    --canon-glob "data/out/local/tiddlers_*.jsonl" \\
    --out-dir data/out/local/pipeline/relation_admission/s0137/

  # Evaluar con fixture de prueba
  python3 relation_admission_gate.py \\
    --candidates-file tests/fixtures/gate_test_candidates.jsonl \\
    --out-dir /tmp/gate_test/

Estados de salida de un candidato:
  admission_ready_dry_run — pasa todos los controles; listo para compuerta real
  blocked                 — no pasa uno o más controles
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_CANDIDATES_FILE = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline"
    / "relations_candidates" / "s0129" / "valid_candidates.jsonl"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admission" / "s0137"
)

sys.path.insert(0, str(SCRIPT_DIR))

from relation_candidate_contract import (  # noqa: E402
    ADMISSION_HUMAN_REVIEW_DECISION,
    ALLOWED_RELATION_TYPES,
    BUILD_ARTIFACT_PATH_PARTS,
    BUILD_ARTIFACT_PREFIXES,
    CANDIDATE_ID_RE,
    HISTORICAL_REPO_LIFECYCLE_STATES,
    VALID_HUMAN_REVIEW_DECISIONS,
    verify_excerpt_in_source,
)
from relation_admission_policy import EVIDENCE_POLICY, GLOBAL_MIN_CONFIDENCE  # noqa: E402
from relation_batch_review import (  # noqa: E402
    SESSION as BATCH_SESSION,
    approved_batch_decision,
    build_batch_summary,
    classify_batch_candidates,
    empty_batch_decisions_doc,
    validate_batch_decisions_doc,
)

SCHEMA_LOG = "relation-admission-log/v1"
SCHEMA_REPORT = "relation-admission-dry-run-report/v1"
SCHEMA_HUMAN_DECISIONS = "relation-human-review-decisions/v1"
SCHEMA_HUMAN_DECISION_LINE_LEGACY = "relation-human-review-decision/v1"
SCHEMA_HUMAN_DECISION_LINE = "relation-human-review-decision/v2"
SCHEMA_HUMAN_QUEUE = "relation-human-review-queue/v1"
SCHEMA_PATCH_PREVIEW = "relation-admission-patch-preview/v1"
SCHEMA_APPLY_PLAN = "relation-admission-apply-plan/v1"
SCHEMA_APPLY_REPORT = "relation-admission-apply-report/v1"
SCHEMA_SNAPSHOT = "relation-admission-rollback-snapshot/v1"
SCHEMA_RECEIPT = "relation-admission-apply-receipt/v1"
SCHEMA_CANDIDATE_JOURNAL = "relation-apply-candidate-journal/v1"
SCHEMA_ROLLBACK = "relation-admission-rollback-report/v1"
SCHEMA_CANONICAL_RELATION = "canonical-relation/v1"

# Types blocked for new candidates (historical types from S0136/S0137 analysis)
HISTORICAL_BLOCKED_TYPES: frozenset[str] = frozenset({
    "usa",
    "parte_de",
    "define",
    "requiere",
    "child_of",
})

ADMISSION_READY = "admission_ready_dry_run"
BLOCKED = "blocked"

VALID_HUMAN_DECISIONS: frozenset[str] = frozenset({
    "approved_for_dry_run",
    "approved_for_admission",
    "rejected_by_human",
    "rejected",
    "needs_changes",
    "deferred",
})

S0165_APPLY_HUMAN_DECISIONS: frozenset[str] = frozenset({
    "approved_for_admission",
    "rejected",
    "deferred",
})

DECISION_REASON_CODES: dict[str, frozenset[str]] = {
    "approved_for_admission": frozenset({
        "DIRECT_CODE_DEPENDENCY_CONFIRMED",
        "TEST_VALIDATES_TARGET_CONFIRMED",
        "EXPLICIT_REFERENCE_CONFIRMED",
        "ARCHITECTURAL_RELATION_CONFIRMED",
        "EVIDENCE_AND_ENDPOINTS_VERIFIED",
    }),
    "rejected": frozenset({
        "INCIDENTAL_REFERENCE",
        "TEST_FIXTURE_ONLY",
        "PATH_LITERAL_NOT_SEMANTIC",
        "DUPLICATE_RELATION",
        "WRONG_PREDICATE",
        "WRONG_SOURCE_OR_TARGET",
        "OUT_OF_SCOPE",
    }),
    "deferred": frozenset({
        "STALE_TARGET_PATH",
        "INSUFFICIENT_CONTEXT",
        "LIFECYCLE_UNRESOLVED",
        "REQUIRES_CANON_RECONCILIATION",
        "POLICY_UNCLEAR",
        "MANUAL_TECHNICAL_REVIEW_REQUIRED",
    }),
}
EXCEPTION_REASON_CODES = frozenset({"OTHER", "POLICY_EXCEPTION", "MANUAL_OVERRIDE"})
NOTE_REQUIRED_REASON_CODES = EXCEPTION_REASON_CODES

APPLY_CONFIRMATION = "APPLY RELATIONS"

RESOLVED_TARGET_STATUSES: frozenset[str] = frozenset({
    "resolved",
    "resolved_id",
    "resolved_title_unique",
})

REVIEW_QUEUE_FAMILIES: frozenset[str] = frozenset({
    "review_queue",
    "relation_review_queue",
})

ADMITTED_RELATION_FAMILIES: frozenset[str] = frozenset({
    "admitted_relation",
    "canonical_relation",
})

S0140_REVIEW_DIR = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_review" / "s0140"
)
S0140_TYPE_POLICY_DIR = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_type_governance" / "s0139"
)
S0140_ADMISSIBILITY_REPORT = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "relation_admissibility"
    / "s0132" / "s0132_relation_admissibility_report.json"
)


# ── Canon loader ──────────────────────────────────────────────────────────────

def load_canon_index(canon_glob: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for fpath in sorted(glob.glob(canon_glob)):
        with open(fpath, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("id"):
                    index[rec["id"]] = rec
    return index


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def count_canon_records(canon_glob: str) -> int:
    total = 0
    for fpath in sorted(glob.glob(canon_glob)):
        with open(fpath, encoding="utf-8") as fh:
            total += sum(1 for line in fh if line.strip())
    return total


def validate_human_review_decision_record(
    record: Any, *, allow_legacy: bool = False,
) -> list[str]:
    """Validate one authoritative v2 decision or an explicit migration-only v1 record."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be object"]
    schema = record.get("schema_version")
    if schema == SCHEMA_HUMAN_DECISION_LINE_LEGACY:
        if not allow_legacy:
            errors.append("legacy v1 decision is audit/migration only")
    elif schema != SCHEMA_HUMAN_DECISION_LINE:
        errors.append(f"schema_version must be {SCHEMA_HUMAN_DECISION_LINE}")
    cid = str(record.get("candidate_id") or "")
    if not cid:
        errors.append("candidate_id required")
    elif not CANDIDATE_ID_RE.match(cid):
        errors.append(f"candidate_id invalid: {cid!r}")
    decision = record.get("human_review_decision")
    if decision not in S0165_APPLY_HUMAN_DECISIONS:
        errors.append(
            "human_review_decision invalid: "
            f"{decision!r}; allowed={sorted(S0165_APPLY_HUMAN_DECISIONS)}"
        )
    if not str(record.get("human_review_actor") or "").strip():
        errors.append("human_review_actor required")
    if not str(record.get("human_review_timestamp") or "").strip():
        errors.append("human_review_timestamp required")
    if schema == SCHEMA_HUMAN_DECISION_LINE_LEGACY and allow_legacy:
        if decision == ADMISSION_HUMAN_REVIEW_DECISION and not str(record.get("human_review_rationale") or "").strip():
            errors.append("human_review_rationale required for legacy approval")
    else:
        reason_code = str(record.get("human_review_reason_code") or "").strip()
        allowed_reasons = DECISION_REASON_CODES.get(str(decision), frozenset()) | EXCEPTION_REASON_CODES
        if reason_code not in allowed_reasons:
            errors.append(
                f"human_review_reason_code invalid for {decision!r}: {reason_code!r}"
            )
        note = record.get("human_review_note")
        if note is not None and not isinstance(note, str):
            errors.append("human_review_note must be string or null")
        if reason_code in NOTE_REQUIRED_REASON_CODES and not str(note or "").strip():
            errors.append(f"human_review_note required for {reason_code}")
        mode = record.get("decision_mode")
        if mode not in {"individual", "batch"}:
            errors.append("decision_mode must be individual or batch")
        if mode == "batch" and not str(record.get("decision_batch_id") or "").strip():
            errors.append("decision_batch_id required for batch decision")
        multi_operation = record.get("multi_review_operation_id")
        if multi_operation is not None and not re.fullmatch(r"hrm_[a-f0-9]{24}", str(multi_operation)):
            errors.append("multi_review_operation_id must match hrm_<24 hex>")
        if record.get("supersedes_decision_hash") is not None:
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", str(record.get("supersedes_decision_hash"))):
                errors.append("supersedes_decision_hash must be sha256:<64 hex>")
            if not str(note or "").strip():
                errors.append("human_review_note required for manual supersession")
        for binding in ("canon_hash", "candidate_manifest_hash", "reconciliation_manifest_hash"):
            if not re.fullmatch(r"[a-f0-9]{64}", str(record.get(binding) or "")):
                errors.append(f"{binding} must be 64 lowercase hex")
    if decision == ADMISSION_HUMAN_REVIEW_DECISION:
        if record.get("approval_scope") != "canonical_admission":
            errors.append("approval_scope must be canonical_admission for approval")
    evidence_paths = record.get("reviewed_evidence_paths")
    if evidence_paths is not None and not isinstance(evidence_paths, list):
        errors.append("reviewed_evidence_paths must be list")
    session_id = str(record.get("session_id") or "")
    if session_id and not re.fullmatch(r"S\d{4}", session_id):
        errors.append("session_id must match SNNNN")
    return errors


def load_human_review_decisions_jsonl(
    path: Path, *, allow_legacy: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load S0165 JSONL decisions keyed by candidate_id."""
    decisions: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if not path.exists():
        return decisions, [f"human_review_decisions file does not exist: {path}"]
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_no}: invalid JSON: {exc}")
                continue
            record_errors = validate_human_review_decision_record(record, allow_legacy=allow_legacy)
            if record_errors:
                errors.extend(f"line {line_no}: {err}" for err in record_errors)
                continue
            decisions[str(record["candidate_id"])] = record
    return decisions, errors


def human_review_decision_lines_from_legacy_doc(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Translate older review docs to S0165 line-shaped records where possible."""
    reviewer = doc.get("reviewer") or {}
    out: dict[str, dict[str, Any]] = {}
    for decision in doc.get("decisions") or []:
        cid = str(decision.get("candidate_id") or "")
        if not cid:
            continue
        value = decision.get("decision")
        if value == "rejected_by_human":
            value = "rejected"
        record = {
            "candidate_id": cid,
            "human_review_decision": value,
            "human_review_actor": reviewer.get("reviewer_id") or "operator",
            "human_review_timestamp": decision.get("reviewed_at") or "",
            "human_review_rationale": decision.get("rationale") or "",
            "approval_scope": "canonical_admission"
            if value == ADMISSION_HUMAN_REVIEW_DECISION
            else "review_queue",
            "reviewed_evidence_paths": decision.get("reviewed_evidence_paths") or [],
            "session_id": doc.get("session") or "",
        }
        out[cid] = record
    return out


def load_persistent_human_review_decisions(path: Path | None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load persistent human review from S0165 JSONL or legacy JSON docs."""
    if path is None:
        return {}, ["human_review_decisions file is required"]
    if not path.exists():
        return {}, [f"human_review_decisions file does not exist: {path}"]
    if path.suffix == ".jsonl":
        return load_human_review_decisions_jsonl(path)
    doc = load_json(path, default={}) or {}
    translated = human_review_decision_lines_from_legacy_doc(doc)
    errors: list[str] = []
    for cid, record in translated.items():
        record_errors = validate_human_review_decision_record(record, allow_legacy=True)
        if not record_errors:
            record_errors.append("legacy decision documents are audit/migration only")
        if record_errors:
            errors.extend(f"{cid}: {err}" for err in record_errors)
    return translated, errors


def apply_persistent_review_decisions_to_candidates(
    candidates: list[dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay S0165 persistent decisions onto candidates without mutating inputs."""
    updated: list[dict[str, Any]] = []
    for candidate in candidates:
        merged = json.loads(json.dumps(candidate))
        decision = decisions.get(str(merged.get("candidate_id") or ""))
        if decision:
            merged["human_review_decision"] = decision.get("human_review_decision")
            merged["human_review_actor"] = decision.get("human_review_actor")
            merged["human_review_timestamp"] = decision.get("human_review_timestamp")
            merged["human_review_rationale"] = decision.get("human_review_rationale")
            merged["human_review_reason_code"] = decision.get("human_review_reason_code")
            merged["human_review_note"] = decision.get("human_review_note")
            merged["decision_batch_id"] = decision.get("decision_batch_id")
            merged["multi_review_operation_id"] = decision.get("multi_review_operation_id")
            merged["review_policy_id"] = decision.get("review_policy_id")
            merged["human_review_schema_version"] = decision.get("schema_version")
            merged["approval_scope"] = decision.get("approval_scope")
            merged["reviewed_evidence_paths"] = decision.get("reviewed_evidence_paths") or []
        updated.append(merged)
    return updated


def load_s0139_type_policy(type_policy_dir: Path) -> dict[str, dict[str, Any]]:
    """Load S0139 decisions keyed by relation type."""
    path = type_policy_dir / "s0139_historical_relation_type_decisions.json"
    payload = load_json(path, default={}) or {}
    return payload.get("decisions_by_type") or {}


def canonical_relations_set(canon: dict[str, dict[str, Any]]) -> set[tuple[str, str, str]]:
    edges: set[tuple[str, str, str]] = set()
    for src_id, rec in canon.items():
        for rel in rec.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            rel_type = str(rel.get("type") or "")
            target_id = str(rel.get("target_id") or "")
            if rel_type and target_id:
                edges.add((src_id, target_id, rel_type))
    return edges


def is_technical_candidate(candidate: dict[str, Any]) -> bool:
    return (
        candidate.get("candidate_schema_version") == "technical-relation-candidates/v1"
        or "relation_type" in candidate
    )


def endpoint_id(endpoint: dict[str, Any]) -> str:
    return str(endpoint.get("canonical_id") or endpoint.get("tiddler_id") or "")


def endpoint_title(endpoint: dict[str, Any], canon_record: dict[str, Any] | None = None) -> str:
    return str(
        endpoint.get("canonical_title")
        or endpoint.get("title")
        or (canon_record or {}).get("title")
        or ""
    )


def endpoint_lifecycle(endpoint: dict[str, Any], canon_record: dict[str, Any] | None = None) -> str:
    canon_record = canon_record or {}
    source_fields = canon_record.get("source_fields") or {}
    return str(
        endpoint.get("lifecycle_state")
        or endpoint.get("repo_lifecycle_state")
        or canon_record.get("lifecycle_state")
        or canon_record.get("repo_lifecycle_state")
        or source_fields.get("lifecycle_state")
        or source_fields.get("repo_lifecycle_state")
        or ""
    )


def endpoint_repo_path(endpoint: dict[str, Any], canon_record: dict[str, Any] | None = None) -> str:
    canon_record = canon_record or {}
    source_fields = canon_record.get("source_fields") or {}
    return str(
        endpoint.get("repo_path")
        or endpoint.get("normalized_repo_path")
        or endpoint.get("observed_repo_path")
        or canon_record.get("repo_path")
        or source_fields.get("repo_path")
        or source_fields.get("source_path")
        or ""
    )


def relation_type_for(candidate: dict[str, Any]) -> str:
    relation = candidate.get("relation") or {}
    return str(candidate.get("relation_type") or relation.get("type") or "")


def evidence_kind_for(candidate: dict[str, Any]) -> str:
    evidence = candidate.get("evidence") or {}
    return str(evidence.get("evidence_kind") or evidence.get("kind") or "")


def evidence_excerpt_for(candidate: dict[str, Any]) -> str:
    evidence = candidate.get("evidence") or {}
    return str(evidence.get("excerpt") or evidence.get("raw_observation") or "")


def confidence_score_for(candidate: dict[str, Any]) -> float:
    confidence = candidate.get("confidence") or {}
    if "score" in confidence:
        return float(confidence.get("score") or 0.0)
    evidence_confidence = str((candidate.get("evidence") or {}).get("confidence") or "").lower()
    return {
        "high": 0.90,
        "medium": 0.70,
        "low": 0.50,
    }.get(evidence_confidence, 0.0)


def is_build_artifact_path(repo_path: str) -> bool:
    normalized = repo_path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    if normalized.startswith(BUILD_ARTIFACT_PREFIXES):
        return True
    return any(part in BUILD_ARTIFACT_PATH_PARTS for part in normalized.split("/"))


def repo_path_status(repo_path: str, lifecycle: str) -> str:
    normalized = repo_path.replace("\\", "/").lstrip("./")
    if not normalized:
        return "not_applicable"
    if is_build_artifact_path(normalized):
        return "build_artifact"
    if lifecycle in HISTORICAL_REPO_LIFECYCLE_STATES:
        return "historical"
    if Path(normalized).exists():
        return "current"
    return "stale"


def candidate_artifact_family(candidate: dict[str, Any]) -> str:
    source_fields = candidate.get("source_fields") or {}
    return str(candidate.get("artifact_family") or source_fields.get("artifact_family") or "")


def relation_policy_block_reason(rel_type: str, type_policy: dict[str, dict[str, Any]]) -> str | None:
    """Return a S0139 blocking reason when a type is not allowed for S0140."""
    decision = type_policy.get(rel_type)
    if not decision:
        return None
    status = decision.get("decision_status")
    if status == "canonical_keep":
        return None
    if status in {"legacy_alias_candidate", "canonical_equivalent"}:
        return (
            f"blocked_legacy_alias_policy: relation.type='{rel_type}' depende de "
            "alias/equivalencia S0139 no aplicada."
        )
    if status == "legacy_readonly":
        return f"blocked_s0139_legacy_readonly: relation.type='{rel_type}' es solo lectura historica."
    if status == "structural_only":
        return f"blocked_s0139_structural_only: relation.type='{rel_type}' es estructural, no semantico."
    return f"blocked_s0139_type_policy: relation.type='{rel_type}' tiene decision S0139 '{status}'."


def confidence_threshold(rel_type: str) -> float:
    policy = EVIDENCE_POLICY.get(rel_type) or {}
    return float(policy.get("min_confidence", GLOBAL_MIN_CONFIDENCE))


def human_decisions_by_candidate(decisions_doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not decisions_doc:
        return {}
    decisions = decisions_doc.get("decisions") or []
    return {
        str(decision.get("candidate_id")): decision
        for decision in decisions
        if decision.get("candidate_id")
    }


def validate_human_review_decisions_doc(
    doc: Any,
    *,
    expected_session: str | None = "S0140",
) -> list[str]:
    """Validate persisted human-review decisions without external deps."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["root must be object"]
    if doc.get("schema") != SCHEMA_HUMAN_DECISIONS:
        errors.append(f"schema must be {SCHEMA_HUMAN_DECISIONS}")
    session = str(doc.get("session") or "")
    if expected_session is not None:
        if session != expected_session:
            errors.append(f"session must be {expected_session}")
    elif not re.fullmatch(r"S\d{4}", session):
        errors.append("session must match SNNNN")
    if doc.get("dry_run") is not True:
        errors.append("dry_run must be true")
    if doc.get("applied_to_canon") is not False:
        errors.append("applied_to_canon must be false")
    reviewer = doc.get("reviewer")
    if not isinstance(reviewer, dict):
        errors.append("reviewer must be object")
    elif not reviewer.get("reviewer_id") or not reviewer.get("reviewer_role"):
        errors.append("reviewer_id and reviewer_role are required")
    decisions = doc.get("decisions")
    if not isinstance(decisions, list):
        errors.append("decisions must be list")
        return errors
    seen: set[str] = set()
    required_checks = {
        "source_verified",
        "target_verified",
        "evidence_excerpt_verified",
        "relation_type_checked_against_s0139",
        "not_duplicate_of_existing_relation",
        "no_canonical_write_requested",
    }
    for idx, decision in enumerate(decisions):
        prefix = f"decisions[{idx}]"
        if not isinstance(decision, dict):
            errors.append(f"{prefix} must be object")
            continue
        cid = decision.get("candidate_id")
        if not cid:
            errors.append(f"{prefix}.candidate_id required")
        elif cid in seen:
            errors.append(f"{prefix}.candidate_id duplicate: {cid}")
        else:
            seen.add(cid)
        value = decision.get("decision")
        if value not in VALID_HUMAN_DECISIONS:
            errors.append(f"{prefix}.decision invalid: {value!r}")
        if not isinstance(decision.get("rationale"), str):
            errors.append(f"{prefix}.rationale must be string")
        checks = decision.get("checks")
        if not isinstance(checks, dict):
            errors.append(f"{prefix}.checks must be object")
        elif value in {"approved_for_dry_run", "approved_for_admission"}:
            missing = sorted(required_checks - set(checks))
            if missing:
                errors.append(f"{prefix}.checks missing: {missing}")
            not_true = sorted(k for k in required_checks if checks.get(k) is not True)
            if not_true:
                errors.append(f"{prefix}.checks must be true for approval: {not_true}")
            if not decision.get("reviewed_at"):
                errors.append(f"{prefix}.reviewed_at required for approval")
            if not decision.get("rationale"):
                errors.append(f"{prefix}.rationale required for approval")
    return errors


def human_review_block(candidate_id: str, decisions_doc: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Return legacy embedded human_review block and blocking notes from persisted decisions."""
    decisions = human_decisions_by_candidate(decisions_doc)
    decision = decisions.get(candidate_id)
    if not decision:
        return None, ["blocked_missing_human_review: no persisted human_review decision for candidate."]

    value = decision.get("decision")
    if value in {"rejected_by_human", "rejected"}:
        return {
            "status": value,
            "reviewer": ((decisions_doc or {}).get("reviewer") or {}).get("reviewer_id", ""),
            "reviewed_at": decision.get("reviewed_at", ""),
            "decision_reason": decision.get("rationale", ""),
            "decision": value,
            "checks": decision.get("checks") or {},
        }, [f"rejected_by_human: human_review.decision='{value}'."]

    if value not in {"approved_for_dry_run", "approved_for_admission"}:
        return {
            "status": value or "(absent)",
            "reviewer": ((decisions_doc or {}).get("reviewer") or {}).get("reviewer_id", ""),
            "reviewed_at": decision.get("reviewed_at", ""),
            "decision_reason": decision.get("rationale", ""),
            "decision": value,
            "checks": decision.get("checks") or {},
        }, [f"blocked_missing_human_review: human_review.decision='{value}'."]

    checks = decision.get("checks") or {}
    failed = [name for name, ok in checks.items() if ok is not True]
    if failed:
        return None, [f"blocked_missing_human_review: approval checks not true: {failed}."]

    reviewer = (decisions_doc or {}).get("reviewer") or {}
    return {
        "status": "approved",
        "reviewer": reviewer.get("reviewer_id", ""),
        "reviewed_at": decision.get("reviewed_at", ""),
        "decision_reason": decision.get("rationale", ""),
        "decision": value,
        "checks": checks,
    }, []


def apply_persisted_human_review(
    candidate: dict[str, Any],
    decisions_doc: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    updated = json.loads(json.dumps(candidate))
    if decisions_doc is None:
        return updated, []
    human_review, notes = human_review_block(str(updated.get("candidate_id") or ""), decisions_doc)
    if human_review is not None:
        updated["human_review"] = human_review
    else:
        updated.pop("human_review", None)
    return updated, notes


def batch_human_review_block(
    candidate: dict[str, Any],
    batch_doc: dict[str, Any] | None,
    batch_summary: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    cid = str(candidate.get("candidate_id") or "")
    if batch_doc is None:
        return None, []
    decision = approved_batch_decision(batch_doc)
    if decision is None:
        return None, ["blocked_missing_human_review: no persisted S0142 batch approval."]

    approved_ids = set(str(item) for item in decision.get("candidate_ids") or [])
    current_hash = str((batch_summary or {}).get("batch_sha256") or "")
    approved_hash = str(decision.get("batch_sha256") or "")
    if approved_hash != current_hash:
        return None, [
            f"blocked_batch_hash_mismatch: approved batch_sha256='{approved_hash}' "
            f"!= current batch_sha256='{current_hash}'."
        ]

    if cid not in approved_ids:
        return None, ["blocked_missing_human_review: candidate not included in approved S0142 batch."]

    current_ready_ids = set(str(item) for item in (batch_summary or {}).get("batch_ready_candidate_ids") or [])
    if cid not in current_ready_ids:
        return None, ["blocked_batch_membership: candidate is no longer batch_ready."]

    reviewer = (batch_doc or {}).get("reviewer") or {}
    return {
        "status": "approved",
        "reviewer": reviewer.get("reviewer_id", ""),
        "reviewed_at": decision.get("reviewed_at", ""),
        "decision_reason": decision.get("rationale", ""),
        "decision": "approved_for_dry_run",
        "decision_source": "batch",
        "batch_id": decision.get("batch_id", ""),
        "batch_sha256": decision.get("batch_sha256", ""),
        "checks": decision.get("checks") or {},
    }, []


def apply_review_sources(
    candidate: dict[str, Any],
    decisions_doc: dict[str, Any] | None,
    batch_doc: dict[str, Any] | None,
    batch_summary: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    cid = str(candidate.get("candidate_id") or "")
    if cid in human_decisions_by_candidate(decisions_doc):
        return apply_persisted_human_review(candidate, decisions_doc)

    updated = json.loads(json.dumps(candidate))
    human_review, notes = batch_human_review_block(updated, batch_doc, batch_summary)
    if human_review is not None:
        updated["human_review"] = human_review
    else:
        updated.pop("human_review", None)
    return updated, notes


# ── Human review validator ────────────────────────────────────────────────────

def validate_human_review(hr: Any) -> list[str]:
    """Validate the human_review block. Returns list of blocking reasons."""
    reasons: list[str] = []

    if not hr or not isinstance(hr, dict):
        reasons.append("GATE-001: human_review ausente o no es un objeto.")
        return reasons

    status = hr.get("status", "")
    if status != "approved":
        reasons.append(
            f"GATE-002: human_review.status='{status}' — "
            "se requiere 'approved' para avanzar."
        )

    if not hr.get("reviewer", "").strip():
        reasons.append("GATE-003: human_review.reviewer ausente o vacío.")

    if not hr.get("reviewed_at", "").strip():
        reasons.append("GATE-004: human_review.reviewed_at ausente o vacío.")

    if not hr.get("decision_reason", "").strip():
        reasons.append("GATE-005: human_review.decision_reason ausente o vacío.")

    return reasons


def validate_candidate_human_review_decision(candidate: dict[str, Any], hr: Any) -> list[str]:
    """S0164 admission decision gate; legacy approvals are not canon admission."""
    reasons: list[str] = []
    direct = candidate.get("human_review_decision")

    if is_technical_candidate(candidate):
        if direct not in VALID_HUMAN_REVIEW_DECISIONS:
            reasons.append(
                "GATE-015: human_review_decision ausente o inválido; "
                f"permitidos={sorted(VALID_HUMAN_REVIEW_DECISIONS)}."
            )
        if direct != ADMISSION_HUMAN_REVIEW_DECISION:
            reasons.append(
                "GATE-016: human_review_decision != approved_for_admission; "
                f"encontrado={direct!r}."
            )
        if direct in S0165_APPLY_HUMAN_DECISIONS:
            reason_code = str(candidate.get("human_review_reason_code") or "")
            allowed_reasons = DECISION_REASON_CODES.get(str(direct), frozenset()) | EXCEPTION_REASON_CODES
            if reason_code not in allowed_reasons:
                reasons.append("GATE-024: human_review_reason_code ausente o inválido.")
        if direct == ADMISSION_HUMAN_REVIEW_DECISION:
            if candidate.get("approval_scope") != "canonical_admission":
                reasons.append(
                    "GATE-025: approval_scope != canonical_admission; "
                    f"encontrado={candidate.get('approval_scope')!r}."
                )
        return reasons

    return reasons


# ── Gate evaluator ────────────────────────────────────────────────────────────

def evaluate_gate(
    candidate: dict[str, Any],
    canon: dict[str, dict[str, Any]],
    *,
    type_policy: dict[str, dict[str, Any]] | None = None,
    human_review_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate a single candidate through the admission gate."""
    reasons_blocked: list[str] = []
    reasons_ok: list[str] = []

    cid = candidate.get("candidate_id", "")
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    evidence = candidate.get("evidence") or {}
    human_review = candidate.get("human_review")

    src_id = endpoint_id(source)
    tgt_id = endpoint_id(target)
    rel_type = relation_type_for(candidate)
    ev_kind = evidence_kind_for(candidate)
    excerpt = evidence_excerpt_for(candidate)
    resolution_status = target.get("resolution_status", "")
    score = confidence_score_for(candidate)
    technical_candidate = is_technical_candidate(candidate)
    candidate_family = candidate_artifact_family(candidate)

    # ── Criterio 1: candidato_id válido ───────────────────────────────────────
    if not cid or not CANDIDATE_ID_RE.match(cid):
        reasons_blocked.append(f"GATE-000: candidate_id='{cid}' inválido.")
    else:
        reasons_ok.append("candidate_id válido.")

    # ── Criterio 1B: separación candidate/review_queue/admitted_relation ─────
    if candidate_family in ADMITTED_RELATION_FAMILIES:
        reasons_blocked.append(
            f"GATE-017: artifact_family='{candidate_family}' no puede ingresar por cola candidata."
        )
    if candidate_family in REVIEW_QUEUE_FAMILIES:
        reasons_blocked.append(
            f"GATE-018: review_queue no es admitted_relation ni relación canónica admitida."
        )
    if str(candidate.get("status") or "") in {"admitted", "admitted_relation"}:
        reasons_blocked.append(
            "GATE-019: candidate.status declara admisión; el gate solo acepta candidatas dry-run."
        )

    # ── Criterio 2: human_review ──────────────────────────────────────────────
    if human_review_notes:
        reasons_blocked.extend(f"GATE-001B: {note}" for note in human_review_notes)
    hr_issues = [] if technical_candidate else validate_human_review(human_review)
    decision_issues = validate_candidate_human_review_decision(candidate, human_review)
    if technical_candidate:
        reasons_blocked.extend(decision_issues)
        if decision_issues:
            hr_issues = []
    elif decision_issues:
        reasons_blocked.extend(decision_issues)

    if hr_issues:
        reasons_blocked.extend(hr_issues)
    else:
        if technical_candidate:
            reasons_ok.append("human_review_decision aprobada para admisión dry-run.")
        else:
            reasons_ok.append(
                f"human_review aprobado por '{(human_review or {}).get('reviewer', '')}' "
                f"en {(human_review or {}).get('reviewed_at', '')}."
            )

    # ── Criterio 3: tipo relacional no histórico bloqueado ────────────────────
    s0139_block = relation_policy_block_reason(rel_type, type_policy or {})
    if s0139_block:
        reasons_blocked.append(f"GATE-006B: {s0139_block}")
    elif rel_type in HISTORICAL_BLOCKED_TYPES:
        reasons_blocked.append(
            f"GATE-006: relation.type='{rel_type}' es un tipo histórico bloqueado para "
            "nuevos candidatos (S0137). Usar tipo del catálogo DT029/DT031."
        )
    elif rel_type not in ALLOWED_RELATION_TYPES:
        reasons_blocked.append(
            f"GATE-007: relation.type='{rel_type}' no está en el catálogo "
            "DT029/DT031 ni en tipos históricos conocidos."
        )
    else:
        reasons_ok.append(f"Tipo relacional '{rel_type}' del catálogo formal.")

    # ── Criterio 4: source existe en canon ────────────────────────────────────
    src_tiddler = canon.get(src_id)
    if not src_tiddler:
        reasons_blocked.append(
            f"GATE-008: source.canonical_id/tiddler_id='{src_id}' no encontrado en el canon vigente."
        )
    else:
        reasons_ok.append(f"Fuente en canon: '{endpoint_title(source, src_tiddler)[:60]}'.")

    # ── Criterio 5: target resuelto en canon ──────────────────────────────────
    tgt_tiddler = canon.get(tgt_id)
    if not technical_candidate and resolution_status and resolution_status not in RESOLVED_TARGET_STATUSES:
        reasons_blocked.append(
            f"GATE-009A: target.resolution_status='{resolution_status}' no es resoluble."
        )
    if not tgt_tiddler:
        reasons_blocked.append(
            f"GATE-009: target.canonical_id/tiddler_id='{tgt_id}' no encontrado en el canon vigente "
            f"(resolution_status='{resolution_status}')."
        )
    else:
        reasons_ok.append(f"Destino en canon: '{endpoint_title(target, tgt_tiddler)[:60]}'.")

    # ── Criterio 5B: lifecycle + staleness + build artifacts ─────────────────
    for role, endpoint, canon_record in (
        ("source", source, src_tiddler),
        ("target", target, tgt_tiddler),
    ):
        lifecycle = endpoint_lifecycle(endpoint, canon_record)
        repo_path = endpoint_repo_path(endpoint, canon_record)
        path_status = repo_path_status(repo_path, lifecycle)
        if technical_candidate and not lifecycle:
            reasons_blocked.append(f"GATE-020: {role}.lifecycle_state ausente.")
        elif lifecycle:
            reasons_ok.append(f"{role}.lifecycle_state='{lifecycle}'.")
        if path_status == "build_artifact":
            reasons_blocked.append(
                f"GATE-021: {role}.repo_path apunta a build artifact: {repo_path!r}."
            )
        elif path_status == "stale" and lifecycle not in HISTORICAL_REPO_LIFECYCLE_STATES:
            reasons_blocked.append(
                f"GATE-022: {role}.repo_path stale sin lifecycle histórico explícito: {repo_path!r}."
            )
        elif path_status in {"current", "historical", "not_applicable"}:
            reasons_ok.append(f"{role}.repo_path_status='{path_status}'.")

    # ── Criterio 6: excerpt verificable ───────────────────────────────────────
    src_text = (src_tiddler or {}).get("text", "") if src_tiddler else ""
    excerpt_ok = verify_excerpt_in_source(excerpt, src_text)
    if technical_candidate:
        if not ev_kind or not excerpt:
            reasons_blocked.append("GATE-023: evidencia verificable ausente en candidato técnico.")
        else:
            reasons_ok.append("Evidencia técnica presente para revisión humana.")
    elif excerpt_ok is False:
        reasons_blocked.append(
            f"GATE-010: excerpt '{excerpt[:60]}...' no verificado en texto fuente."
        )
    elif excerpt_ok is None:
        reasons_blocked.append(
            "GATE-011: texto fuente ausente; excerpt no verificable."
        )
    else:
        reasons_ok.append("Excerpt verificado en texto fuente.")

    # ── Criterio 7: self-relation ─────────────────────────────────────────────
    if src_id and src_id == tgt_id:
        reasons_blocked.append("GATE-012: Auto-relación detectada (source == target).")

    # ── Criterio 8: duplicado canónico existente ──────────────────────────────
    if (src_id, tgt_id, rel_type) in canonical_relations_set(canon):
        reasons_blocked.append(
            "GATE-013: blocked_duplicate_existing: relacion canonica equivalente ya existe."
        )

    # ── Criterio 9: umbral de confianza ───────────────────────────────────────
    min_score = confidence_threshold(rel_type)
    if score < min_score:
        reasons_blocked.append(
            f"GATE-014: confidence.score={score:.2f} < minimo {min_score:.2f} para '{rel_type}'."
        )
    else:
        reasons_ok.append(f"Confidence score {score:.2f} >= {min_score:.2f}.")

    # ── Determinar estado final ───────────────────────────────────────────────
    status = BLOCKED if reasons_blocked else ADMISSION_READY
    decision = classify_gate_decision(status, reasons_blocked)
    primary_block_reason = reasons_blocked[0] if reasons_blocked else ""
    blocking_stage = blocking_stage_for(decision, reasons_blocked)

    # ── Hash de evidencia ─────────────────────────────────────────────────────
    evidence_str = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
    evidence_hash = "sha256:" + hashlib.sha256(evidence_str.encode()).hexdigest()[:16]

    # ── Log ID ────────────────────────────────────────────────────────────────
    log_payload = f"{cid}|{src_id}|{tgt_id}|{rel_type}|{status}"
    log_id = "sha256:" + hashlib.sha256(log_payload.encode()).hexdigest()[:16]

    hr = human_review or {}
    return {
        "candidate_id": cid,
        "gate_status": status,
        "decision": decision,
        "source_tiddler_id": src_id,
        "target_tiddler_id": tgt_id,
        "relation_type": rel_type,
        "confidence_score": score,
        "evidence_kind": ev_kind,
        "blocking_reasons": reasons_blocked,
        "primary_block_reason": primary_block_reason,
        "all_block_reasons": reasons_blocked,
        "blocking_stage": blocking_stage,
        "ok_reasons": reasons_ok,
        "human_review_status": candidate.get(
            "human_review_decision",
            hr.get("decision", hr.get("status", "(absent)")),
        ),
        "human_review_decision": candidate.get(
            "human_review_decision",
            hr.get("decision", hr.get("status", "(absent)")),
        ),
        "human_review_reason_code": candidate.get("human_review_reason_code"),
        "human_review_note": candidate.get("human_review_note"),
        "decision_batch_id": candidate.get("decision_batch_id"),
        "multi_review_operation_id": candidate.get("multi_review_operation_id"),
        "reviewer": hr.get("reviewer", ""),
        "reviewed_at": hr.get("reviewed_at", ""),
        "decision_reason": hr.get("decision_reason", ""),
        "evidence_hash": evidence_hash,
        "log_id": log_id,
        "source_fields_contract_checked": True,
        "relation_type_compatibility_checked": True,
        "type_policy_checked": bool(type_policy is not None),
        "applied_to_canon": False,
        "canon_modified": False,
        "dry_run": True,
    }


def classify_gate_decision(status: str, blocking_reasons: list[str]) -> str:
    if status == ADMISSION_READY:
        return ADMISSION_READY
    joined = "\n".join(blocking_reasons)
    if "blocked_batch_hash_mismatch" in joined:
        return "blocked_batch_hash_mismatch"
    if "rejected_by_human" in joined:
        return "rejected_by_human"
    if "blocked_legacy_alias_policy" in joined:
        return "blocked_legacy_alias_policy"
    if "legacy_readonly" in joined or "structural_only" in joined or "S0139" in joined:
        return "blocked_s0139_type_policy"
    if "blocked_missing_human_review" in joined or "human_review" in joined or "GATE-001" in joined:
        return "blocked_missing_human_review"
    if "GATE-021" in joined or "build artifact" in joined:
        return "blocked_build_artifact"
    if "GATE-020" in joined or "GATE-022" in joined or "repo_path stale" in joined:
        return "blocked_repo_path_stale_or_lifecycle"
    if "GATE-017" in joined or "GATE-018" in joined or "GATE-019" in joined:
        return "blocked_candidate_admitted_separation"
    if "resolution_status" in joined or "GATE-009" in joined:
        return "blocked_unresolved_target"
    if "excerpt" in joined or "no verificable" in joined:
        return "blocked_unverified_evidence"
    if "blocked_duplicate_existing" in joined:
        return "blocked_duplicate_existing"
    if "confidence.score" in joined or "candidate_id" in joined:
        return "blocked_contract_or_policy"
    return BLOCKED


def blocking_stage_for(decision: str, blocking_reasons: list[str]) -> str:
    if decision == ADMISSION_READY:
        return "ready_dry_run"
    joined = "\n".join(blocking_reasons)
    if "GATE-015" in joined or "GATE-016" in joined or "human_review" in joined:
        return "human_review"
    if "GATE-008" in joined or "GATE-009" in joined:
        return "canon_resolution"
    if "GATE-020" in joined or "GATE-021" in joined or "GATE-022" in joined:
        return "repo_path_lifecycle"
    if "GATE-013" in joined:
        return "duplicate_detection"
    if "GATE-006" in joined or "GATE-007" in joined:
        return "relation_type_policy"
    if "GATE-010" in joined or "GATE-011" in joined or "GATE-023" in joined:
        return "evidence"
    if "GATE-017" in joined or "GATE-018" in joined or "GATE-019" in joined:
        return "artifact_separation"
    return "contract_or_policy"


# ── Log writer (append-only) ──────────────────────────────────────────────────

def append_to_log(
    result: dict[str, Any],
    candidate: dict[str, Any],
    log_path: Path,
    *,
    session: str = "s0137",
) -> dict[str, str]:
    """Append a gate decision to the admission log. Returns status info."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cid = result["candidate_id"]
    existing: list[dict[str, Any]] = []
    conflict = None

    if log_path.exists():
        with log_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    existing.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Check for duplicate or conflict
    for prev in existing:
        if prev.get("candidate_id") == cid:
            if prev.get("new_status") == result["gate_status"]:
                return {"outcome": "duplicate_exact", "log_id": prev.get("log_id", "")}
            else:
                conflict = f"Conflicto: mismo candidato {cid}, " \
                           f"estado previo={prev['new_status']} vs nuevo={result['gate_status']}"

    hr = candidate.get("human_review") or {}
    entry = {
        "schema": SCHEMA_LOG,
        "session": session.upper(),
        "log_id": result["log_id"],
        "candidate_id": cid,
        "source_tiddler_id": result["source_tiddler_id"],
        "target_tiddler_id": result["target_tiddler_id"],
        "relation_type": result["relation_type"],
        "previous_status": candidate.get("status", "candidate"),
        "new_status": result["gate_status"],
        "decision": result.get("decision", result["gate_status"]),
        "human_review": {
            "status": hr.get("status", "(absent)"),
            "decision": hr.get("decision", hr.get("status", "(absent)")),
            "reviewer": hr.get("reviewer", ""),
            "reviewed_at": hr.get("reviewed_at", ""),
            "decision_reason": hr.get("decision_reason", ""),
        },
        "evidence_hash": result["evidence_hash"],
        "source_fields_contract_checked": result["source_fields_contract_checked"],
        "relation_type_compatibility_checked": result["relation_type_compatibility_checked"],
        "applied_to_canon": False,
        "canon_modified": False,
        "blocking_reasons": result["blocking_reasons"],
        "dry_run": True,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "conflict_detected": conflict,
    }

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {
        "outcome": "conflict" if conflict else "appended",
        "log_id": result["log_id"],
        "conflict_note": conflict or "",
    }


# ── Report builder ────────────────────────────────────────────────────────────

def build_dry_run_report(
    results: list[dict[str, Any]],
    *,
    session: str,
    candidates_file: Path,
    canon_glob: str,
    persistent_human_decisions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a report from the exact candidate domain evaluated in this run.

    Persistent human decisions are durable authority, not proof that their
    candidate belongs to this particular run.  Every aggregate human
    disposition below is therefore derived only from decisions whose
    ``candidate_id`` appears in ``results``.  A duplicate result ID would make
    that one-decision-per-candidate domain ambiguous, so fail closed instead
    of silently double-counting it.
    """
    current_result_ids = [str(result.get("candidate_id") or "") for result in results]
    duplicate_result_ids = sorted(
        candidate_id
        for candidate_id, count in Counter(current_result_ids).items()
        if count > 1
    )
    if duplicate_result_ids:
        raise ValueError(
            "duplicate candidate_id in evaluated results: "
            + ", ".join(repr(candidate_id) for candidate_id in duplicate_result_ids)
        )

    current_result_id_set = set(current_result_ids)
    scoped_human_decisions = {
        candidate_id: decision
        for candidate_id, decision in (persistent_human_decisions or {}).items()
        if candidate_id in current_result_id_set
    }
    ready = [r for r in results if r["gate_status"] == ADMISSION_READY]
    blocked = [r for r in results if r["gate_status"] == BLOCKED]
    decisions = Counter(str(r.get("decision") or BLOCKED) for r in results)
    human_decisions = Counter(
        str(row.get("human_review_decision") or row.get("decision") or "")
        for row in scoped_human_decisions.values()
    )
    missing_or_deferred = decisions.get("blocked_missing_human_review", 0)
    deferred = human_decisions.get("deferred", 0)
    rejected = human_decisions.get("rejected", 0)
    approved = human_decisions.get("approved_for_admission", 0)
    awaiting = len(results) - approved - deferred - rejected
    if awaiting < 0:
        raise AssertionError("human decision partition exceeds evaluated results")
    technically_invalid = len(blocked) - missing_or_deferred - decisions.get("rejected_by_human", 0)
    return {
        "schema": SCHEMA_REPORT,
        "session": session.upper(),
        "mode": "dry-run",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "inputs": {
            "candidates_file": str(candidates_file),
            "canon_glob": canon_glob,
        },
        "summary": {
            "total_evaluated": len(results),
            "evaluated": len(results),
            "technically_invalid": technically_invalid,
            "awaiting_human_review": awaiting,
            "human_rejected": rejected,
            "human_deferred": deferred,
            "approved_for_admission": approved,
            "admission_ready": len(ready),
            "admission_ready_dry_run": len(ready),
            "applied_to_canon": False,
            "canon_modified": False,
            "dry_run": True,
        },
        "items": [
            {
                "candidate_id": r["candidate_id"],
                "admission_ready_dry_run": r["gate_status"] == ADMISSION_READY,
                "gate_status": r["gate_status"],
                "decision": r.get("decision", r["gate_status"]),
                "relation_type": r["relation_type"],
                "blocking_reasons": r["blocking_reasons"],
                "primary_block_reason": r.get("primary_block_reason", ""),
                "all_block_reasons": r.get("all_block_reasons", r["blocking_reasons"]),
                "blocking_stage": r.get("blocking_stage", ""),
                "ok_reasons": r["ok_reasons"],
                "human_review_status": r["human_review_status"],
                "human_review_decision": r.get("human_review_decision", r["human_review_status"]),
                "human_review_reason_code": r.get("human_review_reason_code"),
                "human_review_note": r.get("human_review_note"),
                "decision_batch_id": r.get("decision_batch_id"),
                "multi_review_operation_id": r.get("multi_review_operation_id"),
                "applied_to_canon": False,
                "canon_modified": False,
                "dry_run": True,
            }
            for r in results
        ],
    }


def sha256_path(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def aggregate_canon_hash(canon_glob: str) -> str:
    digest = hashlib.sha256()
    for name in sorted(glob.glob(canon_glob)):
        digest.update(Path(name).read_bytes())
    return digest.hexdigest()


CURRENT_RUN_ARTIFACT_NAMES = (
    "admission_gate_dry_run.json",
    "current_relation_admission_dry_run_report.json",
    "current_relation_admission_log.jsonl",
    "current_run_manifest.json",
    "relation_apply_plan.json",
    "relation_apply_report.json",
    "relational_audit_index.json",
    "relational_operational_state.json",
)


def _current_run_files(out: Path) -> list[Path]:
    """Return only explicit artifacts that may belong to the current run."""
    return [out / name for name in CURRENT_RUN_ARTIFACT_NAMES if (out / name).is_file()]


def rotate_current_run(out: Path) -> dict[str, Any]:
    """Atomically archive the previous current run or leave it untouched.

    The historical directory is staged on the same filesystem.  Until it is
    published, a failed move is rolled back in reverse order so consumers keep
    seeing one complete current run rather than a partial archive.
    """
    previous_files = _current_run_files(out)
    if not previous_files:
        return {"rotated": False, "archived_files": [], "history_path": None}
    previous_manifest = load_json(out / "current_run_manifest.json", default={}) or {}
    prior_seed = sha256_path(out / "admission_gate_dry_run.json") or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = str(previous_manifest.get("run_id") or f"run-{prior_seed[:16]}")
    history = out.parent / "history" / run_id
    if history.exists():
        raise FileExistsError(f"history collision for current run: {history}")
    temporary_history = history.parent / f".{run_id}.tmp"
    if temporary_history.exists():
        raise FileExistsError(f"temporary history collision for current run: {temporary_history}")

    temporary_history.mkdir(parents=True, exist_ok=False)
    moved: list[tuple[Path, Path, str]] = []
    try:
        for path in previous_files:
            destination = temporary_history / path.name
            digest = sha256_path(path)
            if digest is None:
                raise RuntimeError(f"current artifact disappeared before archive: {path}")
            shutil.move(str(path), str(destination))
            moved.append((path, destination, digest))
            if sha256_path(destination) != digest:
                raise RuntimeError(f"current artifact hash changed during archive: {path}")

        archive_manifest = {
            "schema_version": "relation-admission-history-archive/v1",
            "previous_run_id": run_id,
            "files": [
                {
                    "source": str(source),
                    "temporary_destination": str(destination),
                    "sha256_before": digest,
                }
                for source, destination, digest in moved
            ],
        }
        archive_manifest_path = temporary_history / "archive_manifest.json"
        archive_manifest_path.write_text(
            json.dumps(archive_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if len(moved) != len(previous_files) or any(sha256_path(destination) != digest for _, destination, digest in moved):
            raise RuntimeError("current archive verification failed")
        temporary_history.replace(history)
    except Exception as error:
        for source, destination, _ in reversed(moved):
            if destination.exists():
                shutil.move(str(destination), str(source))
        archive_manifest_path = temporary_history / "archive_manifest.json"
        archive_manifest_path.unlink(missing_ok=True)
        try:
            temporary_history.rmdir()
        except OSError:
            pass
        raise RuntimeError(f"current run archive aborted: {error}") from error

    return {
        "rotated": True,
        "archived_files": [path.name for path in previous_files],
        "history_path": str(history),
    }


def write_current_run_manifest(
    *, out: Path, candidates_file: Path, canon_glob: str, report_path: Path,
    log_path: Path, evaluated: int, human_decisions_path: Path | None,
    rotation: dict[str, Any],
) -> Path:
    if not report_path.is_file() or not log_path.is_file():
        raise RuntimeError("current run manifest requires published report and log")
    candidate_dir = candidates_file.parent
    candidate_manifest = candidate_dir / "current_candidate_manifest.json"
    reconciliation_manifest = candidate_dir / "reconciliation_manifest.json"
    reviewable_manifest = candidate_dir / "reviewable_candidate_manifest.json"
    generated_at = datetime.now(tz=timezone.utc).isoformat()
    run_id = "current-" + hashlib.sha256(
        f"{sha256_path(report_path)}|{generated_at}".encode()
    ).hexdigest()[:16]
    payload = {
        "schema_version": "relation-admission-current-run-manifest/v1",
        "run_id": run_id,
        "generated_at": generated_at,
        "canon_hash": aggregate_canon_hash(canon_glob),
        "candidate_manifest_path": str(candidate_manifest),
        "candidate_manifest_hash": sha256_path(candidate_manifest),
        "reconciliation_manifest_path": str(reconciliation_manifest),
        "reconciliation_manifest_hash": sha256_path(reconciliation_manifest),
        "reviewable_manifest_path": str(reviewable_manifest),
        "reviewable_manifest_hash": sha256_path(reviewable_manifest),
        "human_review_decisions_path": str(human_decisions_path) if human_decisions_path else None,
        "human_review_decisions_hash": sha256_path(human_decisions_path) if human_decisions_path else None,
        "gate_contract_path": str(Path(__file__).resolve()),
        "gate_contract_hash": sha256_path(Path(__file__).resolve()),
        "evaluated": evaluated,
        "log_path": str(log_path),
        "log_hash": sha256_path(log_path),
        "report_path": str(report_path),
        "report_hash": sha256_path(report_path),
        "rotation": rotation,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
    }
    path = out / "current_run_manifest.json"
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary_path.replace(path)
    return path


def dry_run_report_is_recent(path: Path, *, max_age_minutes: int = 1440) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing_dry_run_report: {path}"
    age_seconds = datetime.now(tz=timezone.utc).timestamp() - path.stat().st_mtime
    max_age_seconds = max_age_minutes * 60
    if age_seconds > max_age_seconds:
        return False, (
            f"stale_dry_run_report: age_seconds={int(age_seconds)} "
            f"> max_age_seconds={max_age_seconds}"
        )
    return True, ""


def load_dry_run_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def dry_run_p0_block_reasons(
    report: dict[str, Any], *, candidate_ids: set[str] | None = None,
) -> list[str]:
    reasons: list[str] = []
    for item in report.get("items") or []:
        if candidate_ids is not None and str(item.get("candidate_id") or "") not in candidate_ids:
            continue
        for reason in item.get("all_block_reasons") or item.get("blocking_reasons") or []:
            reasons.append(str(reason))
    return reasons


def build_admitted_relation(candidate: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    src_id = endpoint_id(source)
    tgt_id = endpoint_id(target)
    rel_type = relation_type_for(candidate)
    cid = str(candidate.get("candidate_id") or "")
    payload = f"{cid}|{src_id}|{tgt_id}|{rel_type}"
    relation_id = "cr1_" + hashlib.sha256(payload.encode()).hexdigest()[:24]
    return {
        "type": "application/json",
        "artifact_family": "canonical_relation",
        "relation_schema_version": SCHEMA_CANONICAL_RELATION,
        "relation_id": relation_id,
        "relation_type": rel_type,
        "source_id": src_id,
        "target_id": tgt_id,
        "evidence": {
            "candidate_id": cid,
            "reviewed_evidence_paths": review.get("reviewed_evidence_paths") or [],
        },
        "authority": {
            "admitted_by": review.get("human_review_actor") or "operator",
            "admission_session": review.get("session_id") or "",
            "human_review_decision": review.get("human_review_decision"),
            "human_review_reason_code": review.get("human_review_reason_code"),
            "human_review_note": review.get("human_review_note"),
            "decision_batch_id": review.get("decision_batch_id"),
            "multi_review_operation_id": review.get("multi_review_operation_id"),
            "review_policy_id": review.get("review_policy_id"),
        },
        "lifecycle_state": "admitted_to_canon",
    }


def validate_admitted_relation_schema(record: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be object"]
    required = {
        "type",
        "artifact_family",
        "relation_schema_version",
        "relation_id",
        "relation_type",
        "source_id",
        "target_id",
        "evidence",
        "authority",
        "lifecycle_state",
    }
    missing = sorted(k for k in required if k not in record)
    if missing:
        errors.append(f"missing required fields: {missing}")
    if record.get("artifact_family") != "canonical_relation":
        errors.append("artifact_family must be canonical_relation")
    if record.get("relation_schema_version") != SCHEMA_CANONICAL_RELATION:
        errors.append(f"relation_schema_version must be {SCHEMA_CANONICAL_RELATION}")
    if record.get("lifecycle_state") != "admitted_to_canon":
        errors.append("lifecycle_state must be admitted_to_canon")
    evidence = record.get("evidence") or {}
    if not isinstance(evidence, dict) or not evidence.get("candidate_id"):
        errors.append("evidence.candidate_id required")
    authority = record.get("authority") or {}
    if not isinstance(authority, dict):
        errors.append("authority must be object")
    else:
        if authority.get("human_review_decision") != ADMISSION_HUMAN_REVIEW_DECISION:
            errors.append("authority.human_review_decision must be approved_for_admission")
        if not str(authority.get("human_review_reason_code") or "").strip():
            errors.append("authority.human_review_reason_code required")
    return errors


def build_apply_plan(
    *,
    candidates: list[dict[str, Any]],
    canon_glob: str,
    human_review_decisions: dict[str, dict[str, Any]],
    dry_run_report: dict[str, Any],
    dry_run_report_path: Path,
    dry_run_recent: bool,
    dry_run_recent_reason: str = "",
    binding_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    approved_ids = {
        cid for cid, decision in human_review_decisions.items()
        if decision.get("human_review_decision") == ADMISSION_HUMAN_REVIEW_DECISION
        and decision.get("approval_scope") == "canonical_admission"
        and str(decision.get("human_review_reason_code") or "").strip()
    }
    dry_run_items = dry_run_report.get("items") or []
    ready_ids = {
        str(item.get("candidate_id"))
        for item in dry_run_items
        if item.get("gate_status") == ADMISSION_READY
        or item.get("admission_ready_dry_run") is True
    }
    p0_reasons = dry_run_p0_block_reasons(dry_run_report, candidate_ids=approved_ids)
    selected_approved_ids = sorted(approved_ids & ready_ids) if dry_run_recent and not p0_reasons else []
    candidates_by_id = {str(candidate.get("candidate_id") or ""): candidate for candidate in candidates}
    would_apply_ids: list[str] = []
    omitted_duplicate_ids: list[str] = []
    seen_signatures: set[tuple[str, str, str]] = set()
    for candidate_id in selected_approved_ids:
        candidate = candidates_by_id.get(candidate_id) or {}
        signature = (
            endpoint_id(candidate.get("source") or {}),
            endpoint_id(candidate.get("target") or {}),
            relation_type_for(candidate),
        )
        if signature in seen_signatures:
            omitted_duplicate_ids.append(candidate_id)
            continue
        seen_signatures.add(signature)
        would_apply_ids.append(candidate_id)
    block_reasons: list[str] = []
    if not human_review_decisions:
        block_reasons.append("missing_human_review")
    if not approved_ids:
        block_reasons.append("no_approved_for_admission_decisions")
    if not dry_run_recent:
        block_reasons.append(dry_run_recent_reason or "missing_or_stale_dry_run")
    if p0_reasons:
        block_reasons.append("p0_block_reasons_present")
    if not would_apply_ids and approved_ids and ready_ids and not block_reasons:
        block_reasons.append("no_candidates_selected_for_apply")
    canon_before_count = count_canon_records(canon_glob)
    canon_before_hash = aggregate_canon_hash(canon_glob)
    bindings = {
        name: {"path": str(path), "sha256": sha256_path(path)}
        for name, path in sorted((binding_paths or {}).items())
    }
    missing_bindings = sorted(name for name, binding in bindings.items() if binding["sha256"] is None)
    if missing_bindings:
        block_reasons.extend(f"missing_exact_binding:{name}" for name in missing_bindings)
        would_apply_ids = []
    apply_plan_id = "apply_" + hashlib.sha256(
        json.dumps({
            "approved_ids": sorted(approved_ids),
            "ready_ids": sorted(ready_ids),
            "canon_before_count": canon_before_count,
            "canon_before_hash": canon_before_hash,
            "dry_run_report": str(dry_run_report_path),
            "bindings": bindings,
        }, sort_keys=True).encode()
    ).hexdigest()[:16]
    return {
        "schema": SCHEMA_APPLY_PLAN,
        "apply_plan_id": apply_plan_id,
        "generated_at": utc_now(),
        "canon_before_count": canon_before_count,
        "canon_before_hash": canon_before_hash,
        "candidate_count": len(candidates),
        "approved_count": len(approved_ids),
        "blocked_count": len(candidates) - len(selected_approved_ids),
        "omitted_planned_count": len(omitted_duplicate_ids),
        "omitted_planned_candidate_ids": omitted_duplicate_ids,
        "would_apply_count": len(would_apply_ids),
        "would_apply_candidate_ids": would_apply_ids,
        "block_reasons": block_reasons,
        "dry_run_report": str(dry_run_report_path),
        "dry_run_recent": dry_run_recent,
        "p0_block_reason_count": len(p0_reasons),
        "exact_bindings": bindings,
        "canon_modified": False,
    }


def write_apply_plan(plan: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "relation_apply_plan.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _canon_inventory(canon_glob: str) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for name in sorted(glob.glob(canon_glob)):
        path = Path(name)
        payload = path.read_bytes()
        inventory.append({
            "path": str(path.resolve()),
            "name": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "records": sum(1 for line in payload.splitlines() if line.strip()),
        })
    return inventory


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    )


def _append_transaction_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _future_apply_id(
    *,
    apply_plan_id: str,
    authorization_id: str | None,
    started_at: str,
) -> str:
    material = {
        "apply_plan_id": apply_plan_id,
        "authorization_id": authorization_id,
        "started_at": started_at,
    }
    digest = hashlib.sha256(
        json.dumps(
            material, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"apply_exec_{digest[:24]}"


def _validate_authorized_plan(
    *,
    authorization_path: Path,
    authorized_plan_path: Path,
    observed_plan: dict[str, Any],
    canon_glob: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    errors: list[str] = []
    authorization = load_json(authorization_path, default={}) or {}
    authorized_plan = load_json(authorized_plan_path, default={}) or {}
    bindings = authorization.get("bindings") or {}
    if authorization.get("schema_version") != "gate-g-authorization/v1":
        errors.append("invalid_authorization_schema")
    if authorization.get("decision") != "authorized":
        errors.append("authorization_not_authorized")
    if authorization.get("authorized_operation") != APPLY_CONFIRMATION:
        errors.append("authorization_operation_mismatch")
    if authorization.get("single_use") is not True:
        errors.append("authorization_not_single_use")
    if authorization.get("consumed") is True:
        errors.append("authorization_already_consumed")
    if authorization.get("superseded") is True:
        errors.append("authorization_superseded")
    if authorization.get("authorization_current") is not True:
        errors.append("authorization_not_current")
    if authorization.get("single_use_exhausted") is True:
        errors.append("authorization_single_use_exhausted")
    if authorized_plan.get("schema") != SCHEMA_APPLY_PLAN:
        errors.append("invalid_authorized_plan_schema")
    if bindings.get("apply_plan_id") != authorized_plan.get("apply_plan_id"):
        errors.append("authorization_plan_id_mismatch")
    if bindings.get("apply_plan_hash") != sha256_path(authorized_plan_path):
        errors.append("authorization_plan_hash_mismatch")
    if authorized_plan.get("canon_before_hash") != aggregate_canon_hash(canon_glob):
        errors.append("authorized_plan_canon_hash_mismatch")
    if int(authorized_plan.get("canon_before_count") or -1) != count_canon_records(canon_glob):
        errors.append("authorized_plan_canon_count_mismatch")
    for name, binding in sorted((authorized_plan.get("exact_bindings") or {}).items()):
        path = Path(str((binding or {}).get("path") or ""))
        if not path.is_file() or sha256_path(path) != (binding or {}).get("sha256"):
            errors.append(f"authorized_plan_binding_mismatch:{name}")
    comparable_fields = (
        "candidate_count",
        "approved_count",
        "blocked_count",
        "omitted_planned_count",
        "omitted_planned_candidate_ids",
        "would_apply_count",
        "would_apply_candidate_ids",
        "canon_before_count",
        "canon_before_hash",
    )
    for field in comparable_fields:
        if authorized_plan.get(field) != observed_plan.get(field):
            errors.append(f"authorized_plan_observed_mismatch:{field}")
    return authorization, authorized_plan, errors


def _mark_authorization_in_progress(
    path: Path,
    authorization: dict[str, Any],
    *,
    apply_id: str,
    apply_plan_id: str,
    started_at: str,
) -> None:
    updated = dict(authorization)
    updated.update({
        "consumption_state": "in_progress",
        "consumption_started_at": started_at,
        "consumption_apply_id": apply_id,
        "consumption_apply_plan_id": apply_plan_id,
        "single_use_exhausted": True,
        "authorization_current": False,
    })
    _atomic_write_json(path, updated)


def _mark_authorization_failed(
    path: Path,
    *,
    apply_id: str,
    failure: str,
) -> None:
    authorization = load_json(path, default={}) or {}
    authorization.update({
        "consumed": False,
        "consumption_state": "failed_rolled_back_requires_reauthorization",
        "failed_apply_id": apply_id,
        "failure": failure,
        "failed_at": utc_now(),
        "single_use_exhausted": True,
        "authorization_current": False,
        "production_apply_executed": False,
        "canon_modified": False,
    })
    _atomic_write_json(path, authorization)


def _mark_authorization_consumed(
    path: Path,
    *,
    apply_id: str,
    receipt_path: Path,
    canon_before_hash: str,
    canon_after_hash: str,
    relations_written: int,
) -> None:
    authorization = load_json(path, default={}) or {}
    authorization.update({
        "consumed": True,
        "consumed_once": True,
        "consumed_by_apply_id": apply_id,
        "consumed_at": utc_now(),
        "consumption_state": "consumed",
        "single_use_exhausted": True,
        "authorization_current": False,
        "production_apply_executed": True,
        "canon_modified": relations_written > 0,
        "production_effect": {
            "relations_written": relations_written,
            "pre_canon_hash": canon_before_hash,
            "post_canon_hash": canon_after_hash,
        },
        "receipt_path": str(receipt_path),
        "receipt_hash": sha256_path(receipt_path),
    })
    _atomic_write_json(path, authorization)


def create_rollback_snapshot(
    *,
    canon_glob: str,
    snapshot_root: Path,
    apply_plan_path: Path,
    apply_plan: dict[str, Any],
    target_scope: str,
    apply_id: str | None = None,
    authorization_id: str | None = None,
) -> Path:
    """Create or verify a byte-exact snapshot before the first shard mutation."""
    inventory = _canon_inventory(canon_glob)
    if not inventory:
        raise ValueError("cannot snapshot an empty canon target")
    snapshot_dir = snapshot_root / str(apply_id or apply_plan["apply_plan_id"])
    backup_dir = snapshot_dir / "canon"
    manifest_path = snapshot_dir / "snapshot_manifest.json"
    if manifest_path.exists():
        existing = load_json(manifest_path, default={}) or {}
        if existing.get("apply_plan_hash") != sha256_path(apply_plan_path):
            raise ValueError("existing snapshot is bound to a different apply plan")
        for item in existing.get("files") or []:
            backup = snapshot_dir / str(item.get("backup_path") or "")
            if sha256_path(backup) != item.get("sha256"):
                raise ValueError("existing rollback snapshot failed hash verification")
        return manifest_path

    backup_dir.mkdir(parents=True, exist_ok=False)
    files: list[dict[str, Any]] = []
    for item in inventory:
        source = Path(item["path"])
        backup = backup_dir / item["name"]
        shutil.copyfile(source, backup)
        if sha256_path(backup) != item["sha256"]:
            raise RuntimeError(f"snapshot copy hash mismatch: {source}")
        files.append(item | {"backup_path": str(backup.relative_to(snapshot_dir))})
    manifest = {
        "schema_version": SCHEMA_SNAPSHOT,
        "created_at": utc_now(),
        "apply_plan_id": apply_plan["apply_plan_id"],
        "apply_id": apply_id,
        "authorization_id": authorization_id,
        "apply_plan_path": str(apply_plan_path),
        "apply_plan_hash": sha256_path(apply_plan_path),
        "target_scope": target_scope,
        "canon_before_hash": apply_plan["canon_before_hash"],
        "canon_before_count": apply_plan["canon_before_count"],
        "exact_bindings": apply_plan.get("exact_bindings") or {},
        "files": files,
        "snapshot_complete": True,
        "canon_modified": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _validate_canon_files(paths: list[Path]) -> None:
    seen_ids: set[str] = set()
    for path in paths:
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict) or not str(row.get("id") or ""):
                raise ValueError(f"{path}:{line_no}: canonical object with id required")
            candidate_id = str(row["id"])
            if candidate_id in seen_ids:
                raise ValueError(f"duplicate canonical id after apply: {candidate_id}")
            seen_ids.add(candidate_id)


def rollback_relational_apply(
    *,
    snapshot_manifest_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    """Restore a snapshot byte for byte; a repeated rollback is idempotent."""
    manifest = load_json(snapshot_manifest_path, default={}) or {}
    if manifest.get("schema_version") != SCHEMA_SNAPSHOT or manifest.get("snapshot_complete") is not True:
        raise ValueError("invalid or incomplete rollback snapshot")
    snapshot_dir = snapshot_manifest_path.parent
    files = manifest.get("files") or []
    already_restored = all(
        sha256_path(Path(str(item["path"]))) == item.get("sha256")
        for item in files
    )
    restored = 0
    if not already_restored:
        for item in files:
            destination = Path(str(item["path"]))
            backup = snapshot_dir / str(item["backup_path"])
            if sha256_path(backup) != item.get("sha256"):
                raise ValueError(f"rollback backup hash mismatch: {backup}")
            _atomic_write_bytes(destination, backup.read_bytes())
            restored += 1
    exact = all(sha256_path(Path(str(item["path"]))) == item.get("sha256") for item in files)
    report = {
        "schema_version": SCHEMA_ROLLBACK,
        "rolled_back_at": utc_now(),
        "apply_id": manifest.get("apply_id"),
        "authorization_id": manifest.get("authorization_id"),
        "apply_plan_id": manifest.get("apply_plan_id"),
        "snapshot_manifest_path": str(snapshot_manifest_path),
        "snapshot_manifest_hash": sha256_path(snapshot_manifest_path),
        "status": "already_restored" if already_restored else ("restored" if exact else "failed"),
        "restored_shards": restored,
        "byte_exact": exact,
        "canon_modified": not exact,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rollback_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not exact:
        raise RuntimeError("rollback did not restore the snapshot byte for byte")
    return report


def _transactional_apply(
    *,
    canon_glob: str,
    selected_by_source: dict[str, list[dict[str, Any]]],
    plan: dict[str, Any],
    plan_path: Path,
    out_dir: Path,
    target_scope: str,
    inject_failure_after_shards: int | None,
    apply_id: str,
    authorization_id: str | None = None,
    omitted_equivalent_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshot_path = create_rollback_snapshot(
        canon_glob=canon_glob,
        snapshot_root=out_dir / "rollback_snapshots",
        apply_plan_path=plan_path,
        apply_plan=plan,
        target_scope=target_scope,
        apply_id=apply_id,
        authorization_id=authorization_id,
    )
    journal_path = out_dir / "relation_apply_journal.jsonl"
    journal_path.unlink(missing_ok=True)
    event_identity = {
        "apply_id": apply_id,
        "authorization_id": authorization_id,
        "apply_plan_id": plan["apply_plan_id"],
    }
    _append_transaction_event(journal_path, {
        "event": "transaction_started",
        "at": utc_now(),
        "snapshot_manifest_hash": sha256_path(snapshot_path),
        **event_identity,
    })
    prepared: dict[Path, bytes] = {}
    applied_count = 0
    omitted_existing = 0
    changed_shards: list[str] = []
    source_shards: dict[str, str] = {}
    candidate_results: list[dict[str, Any]] = []
    for name in sorted(glob.glob(canon_glob)):
        path = Path(name)
        shard_before_hash = sha256_path(path)
        lines: list[str] = []
        changed = False
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            record = json.loads(raw)
            relations = selected_by_source.get(str(record.get("id") or ""))
            if relations:
                source_shards[str(record.get("id") or "")] = str(path)
                current = record.get("relations")
                if not isinstance(current, list):
                    current = []
                existing = {
                    (
                        str(relation.get("source_id") or record.get("id") or ""),
                        str(relation.get("target_id") or ""),
                        str(relation.get("relation_type") or relation.get("type") or ""),
                    )
                    for relation in current
                    if (
                        isinstance(relation, dict)
                        and (
                            relation.get("relation_schema_version")
                            or relation.get("schema_version")
                            or relation.get("relation_schema")
                        ) == SCHEMA_CANONICAL_RELATION
                    )
                }
                for relation in relations:
                    key = (relation["source_id"], relation["target_id"], relation["relation_type"])
                    candidate_event = {
                        "schema_version": SCHEMA_CANDIDATE_JOURNAL,
                        "event": "candidate_result",
                        "candidate_id": str(
                            (relation.get("evidence") or {}).get("candidate_id") or ""
                        ),
                        "source": relation["source_id"],
                        "predicate": relation["relation_type"],
                        "target": relation["target_id"],
                        "relation_schema_version": relation["relation_schema_version"],
                        "relation_id": relation["relation_id"],
                        "shard": str(path),
                        "shard_before_hash": shard_before_hash,
                        **event_identity,
                    }
                    if key in existing:
                        omitted_existing += 1
                        candidate_results.append(candidate_event | {
                            "result": "omitted_existing_equivalent",
                        })
                        continue
                    current.append(relation)
                    existing.add(key)
                    applied_count += 1
                    changed = True
                    candidate_results.append(candidate_event | {"result": "written"})
                record["relations"] = current
            lines.append(json.dumps(record, ensure_ascii=False))
        if changed:
            prepared[path] = ("\n".join(lines) + "\n").encode()
            changed_shards.append(str(path))

    staging_dir = Path(tempfile.mkdtemp(prefix="relation-apply-", dir=out_dir))
    try:
        staged_paths: list[Path] = []
        for index, (destination, payload) in enumerate(sorted(prepared.items(), key=lambda item: str(item[0]))):
            staged = staging_dir / destination.name
            staged.write_bytes(payload)
            staged_paths.append(staged)
            _append_transaction_event(journal_path, {
                "event": "shard_prepared", "index": index, "destination": str(destination),
                "sha256": sha256_path(staged),
                **event_identity,
            })
        _validate_canon_files(
            [next((staging_dir / path.name for path in prepared if path == original), original) for original in map(Path, sorted(glob.glob(canon_glob)))]
        )
        promoted = 0
        for destination in sorted(prepared, key=str):
            staged = staging_dir / destination.name
            _atomic_write_bytes(destination, staged.read_bytes())
            promoted += 1
            _append_transaction_event(journal_path, {
                "event": "shard_promoted", "index": promoted, "destination": str(destination),
                "sha256": sha256_path(destination),
                **event_identity,
            })
            if inject_failure_after_shards is not None and promoted >= inject_failure_after_shards:
                raise RuntimeError(f"injected failure after {promoted} shard promotions")
        _validate_canon_files([Path(name) for name in sorted(glob.glob(canon_glob))])
        for candidate_event in candidate_results:
            candidate_event["shard_after_hash"] = sha256_path(Path(candidate_event["shard"]))
            _append_transaction_event(journal_path, candidate_event)
        for omitted in omitted_equivalent_records or []:
            _append_transaction_event(journal_path, {
                "schema_version": SCHEMA_CANDIDATE_JOURNAL,
                "event": "candidate_result",
                "candidate_id": omitted.get("candidate_id"),
                "source": omitted.get("source"),
                "predicate": omitted.get("predicate"),
                "target": omitted.get("target"),
                "relation_schema_version": SCHEMA_CANONICAL_RELATION,
                "result": "omitted_equivalent_representation",
                "representative_candidate_id": omitted.get("representative_candidate_id"),
                "physical_edge_written": False,
                "shard": source_shards.get(str(omitted.get("source") or "")),
                **event_identity,
            })
        _append_transaction_event(journal_path, {
            "event": "transaction_committed", "at": utc_now(), "applied_count": applied_count,
            "omitted_equivalent_count": len(omitted_equivalent_records or []),
            **event_identity,
        })
    except Exception as error:
        _append_transaction_event(journal_path, {
            "event": "transaction_failed",
            "at": utc_now(),
            "failure": str(error),
            **event_identity,
        })
        rollback = rollback_relational_apply(
            snapshot_manifest_path=snapshot_path, out_dir=out_dir,
        )
        for candidate_event in candidate_results:
            _append_transaction_event(journal_path, candidate_event | {
                "event": "candidate_rollback",
                "result": "rolled_back_after_failure",
                "failure": str(error),
            })
        _append_transaction_event(journal_path, {
            "event": "rollback_completed",
            "at": utc_now(),
            "byte_exact": rollback.get("byte_exact"),
            **event_identity,
        })
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
    return {
        "applied_count": applied_count,
        "failed_count": 0,
        "omitted_existing_count": omitted_existing,
        "omitted_equivalent_count": len(omitted_equivalent_records or []),
        "changed_shards": changed_shards,
        "apply_id": apply_id,
        "authorization_id": authorization_id,
        "rollback_snapshot": str(snapshot_path),
        "rollback_snapshot_hash": sha256_path(snapshot_path),
        "journal_path": str(journal_path),
        "journal_hash": sha256_path(journal_path),
    }


def prepare_gate_g_package(
    *,
    candidates_file: Path,
    canon_glob: str,
    human_review_decisions_file: Path,
    dry_run_report_path: Path,
    out_dir: Path,
    binding_paths: dict[str, Path],
    safety_verification_report: Path,
    max_dry_run_age_minutes: int = 1440,
) -> dict[str, Any]:
    """Prepare an exact, non-authorizing Gate G package without applying."""
    candidates = load_jsonl(candidates_file)
    decisions, decision_errors = load_persistent_human_review_decisions(human_review_decisions_file)
    if decision_errors:
        raise ValueError("invalid human review decisions: " + "; ".join(decision_errors))
    dry_run_report = load_dry_run_report(dry_run_report_path)
    recent, reason = dry_run_report_is_recent(
        dry_run_report_path, max_age_minutes=max_dry_run_age_minutes,
    )
    all_bindings = dict(binding_paths)
    all_bindings.update({
        "human_review_decisions": human_review_decisions_file,
        "dry_run_report": dry_run_report_path,
        "safety_verification_report": safety_verification_report,
    })
    plan = build_apply_plan(
        candidates=candidates,
        canon_glob=canon_glob,
        human_review_decisions=decisions,
        dry_run_report=dry_run_report,
        dry_run_report_path=dry_run_report_path,
        dry_run_recent=recent,
        dry_run_recent_reason=reason,
        binding_paths=all_bindings,
    )
    if plan["block_reasons"]:
        raise ValueError("Gate G apply plan is blocked: " + "; ".join(plan["block_reasons"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = write_apply_plan(plan, out_dir)
    snapshot_path = create_rollback_snapshot(
        canon_glob=canon_glob,
        snapshot_root=out_dir / "rollback_snapshots",
        apply_plan_path=plan_path,
        apply_plan=plan,
        target_scope="production_preapply_snapshot",
    )
    readiness = {
        "schema_version": "s0183-gate-g-readiness/v1",
        "session_id": "m04-s0183",
        "prepared_at": utc_now(),
        "canon_hash": plan["canon_before_hash"],
        "canon_records": plan["canon_before_count"],
        "would_apply_count": plan["would_apply_count"],
        "would_apply_candidate_ids": plan["would_apply_candidate_ids"],
        "omitted_planned_count": plan.get("omitted_planned_count", 0),
        "omitted_planned_candidate_ids": plan.get("omitted_planned_candidate_ids", []),
        "apply_plan_path": str(plan_path),
        "apply_plan_hash": sha256_path(plan_path),
        "snapshot_path": str(snapshot_path),
        "snapshot_hash": sha256_path(snapshot_path),
        "safety_verification_report_path": str(safety_verification_report),
        "safety_verification_report_hash": sha256_path(safety_verification_report),
        "exact_bindings": plan["exact_bindings"],
        "apply_authorized": False,
        "apply_executed": False,
        "production_apply_authorized_by_contract": False,
        "rollback_ready": True,
        "canon_modified": False,
        "verdict": "IMPACT_REQUIRES_REAUTHORIZATION",
        "next_action": "REQUEST_EXPLICIT_REAUTHORIZATION_FOR_APPLY_RELATIONS",
    }
    readiness_path = out_dir / "gate_g_readiness.json"
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return readiness | {"readiness_path": str(readiness_path)}


def verify_apply_safety_on_temp_copy(
    *,
    source_canon_glob: str,
    temp_work_root: Path,
    candidates_file: Path,
    human_review_decisions_file: Path,
    dry_run_report_path: Path,
    binding_paths: dict[str, Path],
    report_path: Path,
) -> dict[str, Any]:
    """Exercise apply, idempotency, rollback, and recovery on isolated copies."""
    source_files = [Path(name) for name in sorted(glob.glob(source_canon_glob))]
    if not source_files:
        raise ValueError("source canon is empty")
    if temp_work_root.exists():
        raise ValueError(f"temporary safety root already exists: {temp_work_root}")
    source_hash = aggregate_canon_hash(source_canon_glob)
    source_inventory = {path.name: sha256_path(path) for path in source_files}

    def copy_canon(destination: Path) -> str:
        destination.mkdir(parents=True, exist_ok=False)
        for source in source_files:
            shutil.copyfile(source, destination / source.name)
        target_glob = str(destination / "tiddlers_*.jsonl")
        if aggregate_canon_hash(target_glob) != source_hash:
            raise RuntimeError("temporary canon copy does not match production input")
        return target_glob

    success_glob = copy_canon(temp_work_root / "success" / "canon")
    success_out = temp_work_root / "success" / "audit"
    code, first = guarded_apply_relations(
        candidates_file=candidates_file,
        canon_glob=success_glob,
        human_review_decisions_file=human_review_decisions_file,
        dry_run_report_path=dry_run_report_path,
        out_dir=success_out,
        terminal_confirmation=APPLY_CONFIRMATION,
        perform_write=True,
        target_scope="tmp_path",
        binding_paths=binding_paths,
    )
    if code != 0 or first.get("status") != "applied":
        raise RuntimeError(f"temporary positive apply failed: {first.get('status')}")
    retry_out = temp_work_root / "success" / "retry-audit"
    retry_code, retry = guarded_apply_relations(
        candidates_file=candidates_file,
        canon_glob=success_glob,
        human_review_decisions_file=human_review_decisions_file,
        dry_run_report_path=dry_run_report_path,
        out_dir=retry_out,
        terminal_confirmation=APPLY_CONFIRMATION,
        perform_write=True,
        target_scope="tmp_path",
        binding_paths=binding_paths,
    )
    if retry_code != 0 or int(retry.get("applied_count") or 0) != 0:
        raise RuntimeError("second temporary apply was not idempotent")
    rollback = rollback_relational_apply(
        snapshot_manifest_path=Path(str(first["rollback_snapshot"])),
        out_dir=success_out,
    )
    repeated_rollback = rollback_relational_apply(
        snapshot_manifest_path=Path(str(first["rollback_snapshot"])),
        out_dir=success_out,
    )
    success_restored = aggregate_canon_hash(success_glob) == source_hash

    failure_glob = copy_canon(temp_work_root / "failure" / "canon")
    failure_out = temp_work_root / "failure" / "audit"
    failure_code, failure = guarded_apply_relations(
        candidates_file=candidates_file,
        canon_glob=failure_glob,
        human_review_decisions_file=human_review_decisions_file,
        dry_run_report_path=dry_run_report_path,
        out_dir=failure_out,
        terminal_confirmation=APPLY_CONFIRMATION,
        perform_write=True,
        target_scope="tmp_path",
        binding_paths=binding_paths,
        inject_failure_after_shards=1,
    )
    failure_restored = aggregate_canon_hash(failure_glob) == source_hash
    production_unchanged = (
        aggregate_canon_hash(source_canon_glob) == source_hash
        and all(sha256_path(path) == digest for path, digest in (
            (path, source_inventory[path.name]) for path in source_files
        ))
    )
    passed = all((
        int(first.get("applied_count") or 0) > 0,
        int(first.get("applied_count") or 0) == int((first.get("apply_plan") or {}).get("would_apply_count") or 0),
        int(retry.get("applied_count") or 0) == 0,
        rollback.get("byte_exact") is True,
        repeated_rollback.get("status") == "already_restored",
        success_restored,
        failure_code != 0,
        failure.get("status") == "rolled_back_after_failure",
        failure_restored,
        production_unchanged,
    ))
    report = {
        "schema_version": "s0183-transactional-apply-safety-verification/v1",
        "session_id": "m04-s0183",
        "verified_at": utc_now(),
        "source_canon_glob": source_canon_glob,
        "source_canon_hash": source_hash,
        "source_shards": len(source_files),
        "positive_apply": {
            "status": first.get("status"),
            "applied_count": first.get("applied_count"),
            "approved_count": (first.get("apply_plan") or {}).get("approved_count"),
            "would_apply_count": (first.get("apply_plan") or {}).get("would_apply_count"),
            "omitted_planned_count": (first.get("apply_plan") or {}).get("omitted_planned_count"),
            "omitted_planned_candidate_ids": (first.get("apply_plan") or {}).get("omitted_planned_candidate_ids"),
            "receipt_path": str(success_out / "relation_apply_receipt.json"),
            "receipt_hash": sha256_path(success_out / "relation_apply_receipt.json"),
            "snapshot_path": first.get("rollback_snapshot"),
            "snapshot_hash": first.get("rollback_snapshot_hash"),
            "journal_path": first.get("journal_path"),
            "journal_hash": first.get("journal_hash"),
        },
        "second_apply": {
            "status": retry.get("status"),
            "applied_count": retry.get("applied_count"),
            "omitted_existing_count": retry.get("omitted_existing_count"),
        },
        "rollback": rollback,
        "repeated_rollback": repeated_rollback,
        "injected_failure": {
            "status": failure.get("status"),
            "failure": failure.get("failure"),
            "rollback_report": failure.get("rollback_report"),
            "restored_exactly": failure_restored,
        },
        "success_copy_restored_exactly": success_restored,
        "production_canon_unchanged": production_unchanged,
        "passed": passed,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not passed:
        raise RuntimeError("temporary transactional safety verification failed")
    return report | {"report_path": str(report_path)}


def guarded_apply_relations(
    *,
    candidates_file: Path,
    canon_glob: str,
    human_review_decisions_file: Path | None,
    dry_run_report_path: Path,
    out_dir: Path,
    terminal_confirmation: str,
    max_dry_run_age_minutes: int = 1440,
    perform_write: bool = False,
    target_scope: str = "unspecified",
    binding_paths: dict[str, Path] | None = None,
    inject_failure_after_shards: int | None = None,
    authorization_path: Path | None = None,
    authorized_plan_path: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Apply an exact authorized plan, or exercise the same engine on a temp fixture."""
    candidates = load_jsonl(candidates_file) if candidates_file.exists() else []
    decisions, decision_errors = load_persistent_human_review_decisions(human_review_decisions_file)
    dry_run_report = load_dry_run_report(dry_run_report_path)
    dry_run_recent, dry_run_recent_reason = dry_run_report_is_recent(
        dry_run_report_path,
        max_age_minutes=max_dry_run_age_minutes,
    )
    observed_plan = build_apply_plan(
        candidates=candidates,
        canon_glob=canon_glob,
        human_review_decisions=decisions,
        dry_run_report=dry_run_report,
        dry_run_report_path=dry_run_report_path,
        dry_run_recent=dry_run_recent,
        dry_run_recent_reason=dry_run_recent_reason,
        binding_paths=binding_paths,
    )
    if decision_errors:
        observed_plan["block_reasons"].extend(
            f"invalid_human_review: {err}" for err in decision_errors
        )
        observed_plan["would_apply_count"] = 0
        observed_plan["would_apply_candidate_ids"] = []
        observed_plan["blocked_count"] = len(candidates)
    if terminal_confirmation != APPLY_CONFIRMATION:
        observed_plan["block_reasons"].append("missing_exact_terminal_confirmation")
        observed_plan["would_apply_count"] = 0
        observed_plan["would_apply_candidate_ids"] = []
        observed_plan["blocked_count"] = len(candidates)

    authorization: dict[str, Any] = {}
    plan = observed_plan
    exact_authorized_plan_reused = False
    authorization_required = target_scope == "production_path"
    if authorization_required and (authorization_path is None or authorized_plan_path is None):
        observed_plan["block_reasons"].append("missing_gate_g_authorization_or_authorized_plan")
    elif authorization_path is not None or authorized_plan_path is not None:
        if authorization_path is None or authorized_plan_path is None:
            observed_plan["block_reasons"].append("incomplete_authorization_binding")
        else:
            authorization, authorized_plan, authorization_errors = _validate_authorized_plan(
                authorization_path=authorization_path,
                authorized_plan_path=authorized_plan_path,
                observed_plan=observed_plan,
                canon_glob=canon_glob,
            )
            observed_plan["block_reasons"].extend(authorization_errors)
            if not observed_plan["block_reasons"]:
                plan = authorized_plan
                exact_authorized_plan_reused = True

    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "relation_apply_plan.json"
    if exact_authorized_plan_reused and authorized_plan_path is not None:
        _atomic_write_bytes(plan_path, authorized_plan_path.read_bytes())
    else:
        plan_path = write_apply_plan(observed_plan, out_dir)

    report = {
        "schema": SCHEMA_APPLY_REPORT,
        "generated_at": utc_now(),
        "report_kind": "blocked_apply_report",
        "target_scope": target_scope,
        "apply_executed": False,
        "apply_plan_path": str(plan_path),
        "apply_plan": plan,
        "exact_authorized_plan_reused": exact_authorized_plan_reused,
        "authorization_id": authorization.get("authorization_id"),
        "would_apply_count": plan["would_apply_count"],
        "blocked_count": plan["blocked_count"],
        "omitted_planned_count": plan.get("omitted_planned_count", 0),
        "applied_count": 0,
        "canon_before_count": plan["canon_before_count"],
        "canon_after_count": plan["canon_before_count"],
        "canon_modified": False,
        "status": "blocked",
    }
    if observed_plan["block_reasons"]:
        report["apply_plan"] = observed_plan
        report["would_apply_count"] = observed_plan["would_apply_count"]
        report["blocked_count"] = observed_plan["blocked_count"]
        (out_dir / "relation_apply_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return 1, report

    if not perform_write:
        report["status"] = "planned_not_applied"
        report["report_kind"] = "apply_plan_report"
        (out_dir / "relation_apply_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return 1, report

    # The write path is intentionally narrow: add relation objects to source records.
    candidates_by_id = {str(c.get("candidate_id") or ""): c for c in candidates}
    selected = [candidates_by_id[cid] for cid in plan["would_apply_candidate_ids"] if cid in candidates_by_id]
    selected_by_source: dict[str, list[dict[str, Any]]] = {}
    representative_by_signature: dict[tuple[str, str, str], str] = {}
    for candidate in selected:
        review = decisions[str(candidate.get("candidate_id"))]
        relation = build_admitted_relation(candidate, review)
        schema_errors = validate_admitted_relation_schema(relation)
        if schema_errors:
            report["status"] = "blocked"
            plan["block_reasons"].append(f"invalid_admitted_relation_schema: {schema_errors}")
            (out_dir / "relation_apply_report.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            return 1, report
        selected_by_source.setdefault(relation["source_id"], []).append(relation)
        representative_by_signature[
            (relation["source_id"], relation["target_id"], relation["relation_type"])
        ] = str(candidate.get("candidate_id") or "")

    omitted_equivalent_records: list[dict[str, Any]] = []
    for candidate_id in plan.get("omitted_planned_candidate_ids") or []:
        candidate = candidates_by_id.get(str(candidate_id)) or {}
        source = endpoint_id(candidate.get("source") or {})
        target = endpoint_id(candidate.get("target") or {})
        predicate = relation_type_for(candidate)
        omitted_equivalent_records.append({
            "candidate_id": candidate_id,
            "source": source,
            "predicate": predicate,
            "target": target,
            "representative_candidate_id": representative_by_signature.get(
                (source, target, predicate),
            ),
        })

    started_at = utc_now()
    apply_id = _future_apply_id(
        apply_plan_id=str(plan["apply_plan_id"]),
        authorization_id=authorization.get("authorization_id"),
        started_at=started_at,
    )
    report["apply_id"] = apply_id
    report["started_at"] = started_at
    if authorization_path is not None:
        _mark_authorization_in_progress(
            authorization_path,
            authorization,
            apply_id=apply_id,
            apply_plan_id=str(plan["apply_plan_id"]),
            started_at=started_at,
        )

    try:
        transaction = _transactional_apply(
            canon_glob=canon_glob,
            selected_by_source=selected_by_source,
            plan=plan,
            plan_path=plan_path,
            out_dir=out_dir,
            target_scope=target_scope,
            inject_failure_after_shards=inject_failure_after_shards,
            apply_id=apply_id,
            authorization_id=authorization.get("authorization_id"),
            omitted_equivalent_records=omitted_equivalent_records,
        )
    except Exception as error:
        if authorization_path is not None:
            _mark_authorization_failed(
                authorization_path, apply_id=apply_id, failure=str(error),
            )
        report.update({
            "status": "rolled_back_after_failure",
            "report_kind": "failed_apply_rollback_report",
            "failure": str(error),
            "rollback_report": str(out_dir / "rollback_report.json"),
            "canon_after_hash": aggregate_canon_hash(canon_glob),
            "completed_at": utc_now(),
        })
        (out_dir / "relation_apply_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return 1, report

    canon_after_count = count_canon_records(canon_glob)
    applied_count = int(transaction["applied_count"])
    report.update({
        "status": "applied",
        "report_kind": (
            "fixture_positive_apply_report"
            if target_scope == "tmp_path" and applied_count > 0
            else "applied_apply_report"
        ),
        "apply_executed": applied_count > 0,
        "applied_count": applied_count,
        "canon_after_count": canon_after_count,
        "canon_before_hash": plan["canon_before_hash"],
        "canon_after_hash": aggregate_canon_hash(canon_glob),
        "canon_modified": applied_count > 0,
        **transaction,
    })
    report["completed_at"] = utc_now()
    report["apply_plan"] = plan | {"canon_modified": applied_count > 0}
    (out_dir / "relation_apply_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema_version": SCHEMA_RECEIPT,
        "apply_id": apply_id,
        "authorization_id": authorization.get("authorization_id"),
        "authorization_path": str(authorization_path) if authorization_path else None,
        "apply_plan_id": plan["apply_plan_id"],
        "apply_plan_hash": sha256_path(plan_path),
        "status": report["status"],
        "attempted_count": plan["approved_count"],
        "applied_count": applied_count,
        "failed_count": transaction["failed_count"],
        "omitted_planned_count": plan.get("omitted_planned_count", 0),
        "omitted_planned_candidate_ids": plan.get("omitted_planned_candidate_ids", []),
        "omitted_existing_count": transaction["omitted_existing_count"],
        "omitted_count": (
            int(plan.get("omitted_planned_count") or 0)
            + int(transaction["omitted_existing_count"])
        ),
        "blocked_count": plan["blocked_count"],
        "canon_before_hash": plan["canon_before_hash"],
        "canon_after_hash": report["canon_after_hash"],
        "canon_before_count": plan["canon_before_count"],
        "canon_after_count": canon_after_count,
        "canon_before_shards": len(_canon_inventory(canon_glob)),
        "canon_after_shards": len(_canon_inventory(canon_glob)),
        "rollback_snapshot": transaction["rollback_snapshot"],
        "rollback_snapshot_hash": transaction["rollback_snapshot_hash"],
        "journal_path": transaction["journal_path"],
        "journal_hash": transaction["journal_hash"],
        "exact_bindings": plan.get("exact_bindings") or {},
        "target_scope": target_scope,
        "exact_authorized_plan_reused": exact_authorized_plan_reused,
    }
    receipt_path = out_dir / "relation_apply_receipt.json"
    try:
        _atomic_write_json(receipt_path, receipt)
        if authorization_path is not None:
            _mark_authorization_consumed(
                authorization_path,
                apply_id=apply_id,
                receipt_path=receipt_path,
                canon_before_hash=str(plan["canon_before_hash"]),
                canon_after_hash=str(report["canon_after_hash"]),
                relations_written=applied_count,
            )
    except Exception as error:
        rollback = rollback_relational_apply(
            snapshot_manifest_path=Path(str(transaction["rollback_snapshot"])),
            out_dir=out_dir,
        )
        for candidate in selected:
            _append_transaction_event(
                Path(str(transaction["journal_path"])),
                {
                    "schema_version": SCHEMA_CANDIDATE_JOURNAL,
                    "event": "candidate_rollback",
                    "candidate_id": candidate.get("candidate_id"),
                    "result": "rolled_back_after_receipt_or_consumption_failure",
                    "failure": str(error),
                    "apply_id": apply_id,
                    "authorization_id": authorization.get("authorization_id"),
                    "apply_plan_id": plan["apply_plan_id"],
                },
            )
        _append_transaction_event(
            Path(str(transaction["journal_path"])),
            {
                "event": "postcommit_rollback_completed",
                "at": utc_now(),
                "failure": str(error),
                "byte_exact": rollback.get("byte_exact"),
                "apply_id": apply_id,
                "authorization_id": authorization.get("authorization_id"),
                "apply_plan_id": plan["apply_plan_id"],
            },
        )
        if authorization_path is not None:
            _mark_authorization_failed(
                authorization_path, apply_id=apply_id, failure=str(error),
            )
        report.update({
            "status": "rolled_back_after_receipt_or_consumption_failure",
            "apply_executed": False,
            "canon_modified": False,
            "canon_after_hash": aggregate_canon_hash(canon_glob),
            "failure": str(error),
            "rollback_report": str(out_dir / "rollback_report.json"),
            "completed_at": utc_now(),
        })
        _atomic_write_json(out_dir / "relation_apply_report.json", report)
        if receipt_path.exists():
            receipt.update({
                "status": report["status"],
                "applied_count": 0,
                "failed_count": len(selected),
                "canon_after_hash": report["canon_after_hash"],
                "journal_hash": sha256_path(Path(str(transaction["journal_path"]))),
                "rolled_back": True,
            })
            _atomic_write_json(receipt_path, receipt)
        return 1, report
    return 0, report


def build_review_queue(
    admissibility_report: dict[str, Any],
    *,
    source_report: str,
) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for item in admissibility_report.get("results") or []:
        if item.get("decision") != "review_required":
            continue
        queue.append({
            "candidate_id": item.get("candidate_id", ""),
            "source_id": item.get("source_id", ""),
            "source_title": item.get("source_title", ""),
            "target_id": item.get("target_id", ""),
            "target_title": item.get("target_title", ""),
            "relation_type": item.get("relation_type", ""),
            "confidence_score": item.get("confidence_score", 0.0),
            "evidence_kind": item.get("evidence_kind", ""),
            "evidence_excerpt": item.get("evidence_excerpt", ""),
            "current_decision": "review_required",
            "risk_level": item.get("risk_level", ""),
            "review_prompt": (
                "Revisar source, target, evidencia textual, tipo relacional y "
                "ausencia de duplicado antes de aprobar para dry-run."
            ),
            "source_report": source_report,
        })
    return queue


def build_deferred_human_decisions(
    queue: list[dict[str, Any]],
    *,
    session: str = "S0140",
    rationale: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_HUMAN_DECISIONS,
        "session": session,
        "dry_run": True,
        "applied_to_canon": False,
        "reviewer": {
            "reviewer_id": "local-operator",
            "reviewer_role": "human_operator",
        },
        "decisions": [
            {
                "candidate_id": item["candidate_id"],
                "decision": "deferred",
                "reviewed_at": "",
                "rationale": rationale or (
                    f"{session} no encontro una aprobacion humana explicita y persistida "
                    "para este candidato. Queda pendiente."
                ),
                "checks": {
                    "source_verified": False,
                    "target_verified": False,
                    "evidence_excerpt_verified": False,
                    "relation_type_checked_against_s0139": False,
                    "not_duplicate_of_existing_relation": False,
                    "no_canonical_write_requested": True,
                },
            }
            for item in queue
        ],
    }


def write_human_review_schema(path: Path, *, session: str = "S0140") -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "relation-human-review-decisions/v1",
        "type": "object",
        "required": ["schema", "session", "dry_run", "applied_to_canon", "reviewer", "decisions"],
        "properties": {
            "schema": {"const": SCHEMA_HUMAN_DECISIONS},
            "session": {"const": session},
            "dry_run": {"const": True},
            "applied_to_canon": {"const": False},
            "reviewer": {
                "type": "object",
                "required": ["reviewer_id", "reviewer_role"],
                "properties": {
                    "reviewer_id": {"type": "string"},
                    "reviewer_role": {"type": "string"},
                },
            },
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["candidate_id", "decision", "reviewed_at", "rationale", "checks"],
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "decision": {"enum": sorted(VALID_HUMAN_DECISIONS)},
                        "reviewed_at": {"type": "string"},
                        "rationale": {"type": "string"},
                        "checks": {"type": "object"},
                    },
                },
            },
        },
    }
    path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_review_artifacts(
    review_dir: Path,
    queue: list[dict[str, Any]],
    decisions_doc: dict[str, Any],
    *,
    session: str | None = None,
) -> dict[str, Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    queue_path = review_dir / "human_review_queue.jsonl"
    decisions_path = review_dir / "human_review_decisions.json"
    schema_path = review_dir / "human_review_decisions.schema.json"
    audit_path = review_dir / "human_review_audit_log.jsonl"
    summary_path = review_dir / "human_review_summary.md"

    with queue_path.open("w", encoding="utf-8") as fh:
        for item in queue:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    decisions_path.write_text(
        json.dumps(decisions_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    session_label = session or str(decisions_doc.get("session") or "S0140")
    write_human_review_schema(schema_path, session=session_label)

    generated_at = datetime.now(tz=timezone.utc).isoformat()
    with audit_path.open("w", encoding="utf-8") as fh:
        for decision in decisions_doc.get("decisions") or []:
            fh.write(json.dumps({
                "schema": "relation-human-review-audit-log/v1",
                "session": session_label,
                "candidate_id": decision.get("candidate_id", ""),
                "decision": decision.get("decision", ""),
                "reviewer_id": (decisions_doc.get("reviewer") or {}).get("reviewer_id", ""),
                "generated_at": generated_at,
                "dry_run": True,
                "applied_to_canon": False,
                "canon_modified": False,
            }, ensure_ascii=False) + "\n")

    decision_counts = Counter(d.get("decision") for d in decisions_doc.get("decisions") or [])
    summary_path.write_text(
        "\n".join([
            f"# {session_label} - Human review summary",
            "",
            f"- Candidatos en cola: {len(queue)}",
            f"- Decisiones persistidas: {len(decisions_doc.get('decisions') or [])}",
            f"- approved_for_dry_run: {decision_counts.get('approved_for_dry_run', 0)}",
            f"- rejected_by_human: {decision_counts.get('rejected_by_human', 0)}",
            f"- needs_changes: {decision_counts.get('needs_changes', 0)}",
            f"- deferred: {decision_counts.get('deferred', 0)}",
            "- dry_run: true",
            "- applied_to_canon: false",
            "- canon_modified: false",
            "",
            "No se encontro aprobacion humana explicita para marcar candidatos como approved_for_dry_run.",
            "",
        ]),
        encoding="utf-8",
    )
    return {
        "queue": queue_path,
        "decisions": decisions_path,
        "schema": schema_path,
        "audit": audit_path,
        "summary": summary_path,
    }


def build_patch_preview(results: list[dict[str, Any]], *, session: str = "S0140") -> dict[str, Any]:
    ready = [r for r in results if r["gate_status"] == ADMISSION_READY]
    return {
        "schema": SCHEMA_PATCH_PREVIEW,
        "session": session,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "not_a_patch": True,
        "applicable": False,
        "total_operations_previewed": len(ready),
        "operations": [
            {
                "operation": "add_relation_preview_only",
                "candidate_id": r["candidate_id"],
                "source_id": r["source_tiddler_id"],
                "target_id": r["target_tiddler_id"],
                "relation_type": r["relation_type"],
                "applied": False,
            }
            for r in ready
        ],
    }


def write_session_admission_outputs(
    out_dir: Path,
    results: list[dict[str, Any]],
    *,
    candidates_file: Path,
    canon_glob: str,
    session_tag: str = "s0140",
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ready = [r for r in results if r["gate_status"] == ADMISSION_READY]
    blocked = [r for r in results if r["gate_status"] == BLOCKED]
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    session_label = session_tag.upper()

    ready_doc = {
        "schema": "relation-admission-ready-dry-run/v1",
        "session": session_label,
        "generated_at": generated_at,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "summary": {"total": len(ready)},
        "items": ready,
    }
    blocked_doc = {
        "schema": "relation-admission-blocked/v1",
        "session": session_label,
        "generated_at": generated_at,
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "summary": {
            "total": len(blocked),
            "by_decision": dict(Counter(r.get("decision", BLOCKED) for r in blocked)),
        },
        "items": blocked,
    }
    patch_preview = build_patch_preview(results, session=session_label)
    report = build_dry_run_report(
        results,
        session=session_tag,
        candidates_file=candidates_file,
        canon_glob=canon_glob,
    )

    paths = {
        "ready": out_dir / "admission_ready_dry_run.json",
        "blocked": out_dir / "admission_blocked.json",
        "patch_preview": out_dir / "admission_patch_preview.json",
        "summary": out_dir / "admission_gate_summary.md",
        "review_csv": out_dir / "admission_gate_review.csv",
        "audit": out_dir / "admission_gate_audit_log.jsonl",
        "legacy_report": out_dir / f"{session_tag}_relation_admission_dry_run_report.json",
    }
    paths["ready"].write_text(json.dumps(ready_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["blocked"].write_text(json.dumps(blocked_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["patch_preview"].write_text(json.dumps(patch_preview, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["legacy_report"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with paths["review_csv"].open("w", encoding="utf-8", newline="") as fh:
        fieldnames = [
            "candidate_id",
            "decision",
            "gate_status",
            "human_review_decision",
            "relation_type",
            "source_id",
            "target_id",
            "blocking_reasons",
            "dry_run",
            "applied_to_canon",
            "canon_modified",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({
                "candidate_id": result["candidate_id"],
                "decision": result.get("decision", ""),
                "gate_status": result["gate_status"],
                "human_review_decision": result.get("human_review_decision", ""),
                "relation_type": result["relation_type"],
                "source_id": result["source_tiddler_id"],
                "target_id": result["target_tiddler_id"],
                "blocking_reasons": " | ".join(result["blocking_reasons"]),
                "dry_run": "true",
                "applied_to_canon": "false",
                "canon_modified": "false",
            })

    with paths["audit"].open("w", encoding="utf-8") as fh:
        for result in results:
            fh.write(json.dumps({
                "schema": "relation-admission-gate-audit-log/v1",
                "session": session_label,
                "candidate_id": result["candidate_id"],
                "decision": result.get("decision", ""),
                "gate_status": result["gate_status"],
                "dry_run": True,
                "applied_to_canon": False,
                "canon_modified": False,
                "created_at": generated_at,
            }, ensure_ascii=False) + "\n")

    summary_counts = Counter(r.get("decision", BLOCKED) for r in results)
    paths["summary"].write_text(
        "\n".join([
            f"# {session_label} - Admission gate summary",
            "",
            f"- Total evaluados: {len(results)}",
            f"- admission_ready_dry_run: {len(ready)}",
            f"- blocked: {len(blocked)}",
            f"- blocked_missing_human_review: {summary_counts.get('blocked_missing_human_review', 0)}",
            f"- blocked_legacy_alias_policy: {summary_counts.get('blocked_legacy_alias_policy', 0)}",
            f"- blocked_unresolved_target: {summary_counts.get('blocked_unresolved_target', 0)}",
            f"- blocked_unverified_evidence: {summary_counts.get('blocked_unverified_evidence', 0)}",
            f"- blocked_duplicate_existing: {summary_counts.get('blocked_duplicate_existing', 0)}",
            f"- blocked_batch_hash_mismatch: {summary_counts.get('blocked_batch_hash_mismatch', 0)}",
            f"- rejected_by_human: {summary_counts.get('rejected_by_human', 0)}",
            "- dry_run: true",
            "- applied_to_canon: false",
            "- canon_modified: false",
            "",
            "El patch preview es informativo y no aplicable.",
            "",
        ]),
        encoding="utf-8",
    )
    return paths


def write_s0140_admission_outputs(
    out_dir: Path,
    results: list[dict[str, Any]],
    *,
    candidates_file: Path,
    canon_glob: str,
) -> dict[str, Path]:
    return write_session_admission_outputs(
        out_dir,
        results,
        candidates_file=candidates_file,
        canon_glob=canon_glob,
        session_tag="s0140",
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Compuerta humana mínima de admisión relacional (S0137). "
            "Dry-run por defecto; --apply exige revisión humana persistente y confirmación exacta."
        )
    )
    p.add_argument("--candidates-file", "--candidate-file", dest="candidates_file", type=Path, default=DEFAULT_CANDIDATES_FILE)
    p.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    p.add_argument("--human-review", type=Path, default=None)
    p.add_argument("--human-review-decisions", type=Path, default=None)
    p.add_argument("--human-review-batch", type=Path, default=None)
    p.add_argument("--dry-run-report", type=Path, default=None)
    p.add_argument("--terminal-confirmation", default="")
    p.add_argument("--authorization-file", type=Path)
    p.add_argument("--authorized-plan", type=Path)
    p.add_argument("--rollback-snapshot", type=Path)
    p.add_argument("--rollback-confirmation", default="")
    p.add_argument("--prepare-gate-g", action="store_true")
    p.add_argument("--binding", action="append", default=[], metavar="NAME=PATH")
    p.add_argument("--safety-verification-report", type=Path)
    p.add_argument("--verify-safety-temp", action="store_true")
    p.add_argument("--temp-work-root", type=Path)
    p.add_argument("--safety-report", type=Path)
    p.add_argument("--max-dry-run-age-minutes", type=int, default=1440)
    p.add_argument("--type-policy-dir", type=Path, default=S0140_TYPE_POLICY_DIR)
    p.add_argument("--review-dir", type=Path, default=S0140_REVIEW_DIR)
    p.add_argument("--admissibility-report", type=Path, default=S0140_ADMISSIBILITY_REPORT)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--session", default="s0137")
    p.add_argument("--dry-run", action="store_true", default=False)
    p.add_argument("--apply", action="store_true", default=False)
    p.add_argument("--verbose", "-v", action="store_true", default=False)
    return p


def infer_session_tag(args: argparse.Namespace) -> str:
    requested = str(args.session or "").lower()
    if requested and requested != "s0137":
        return requested

    for path in (args.human_review, args.human_review_batch, args.out_dir, args.review_dir):
        if not path:
            continue
        for part in Path(path).parts:
            if re.fullmatch(r"s\d{4}", part.lower()):
                return part.lower()
    return requested or "s0137"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session_tag = infer_session_tag(args)
    session_label = session_tag.upper()
    out = args.output.parent if args.output else args.out_dir
    if args.verify_safety_temp:
        if (
            not args.human_review_decisions
            or not args.dry_run_report
            or not args.temp_work_root
            or not args.safety_report
        ):
            print(
                "Gate F requiere decisiones, dry-run, --temp-work-root y --safety-report.",
                file=sys.stderr,
            )
            return 2
        safety_bindings: dict[str, Path] = {}
        for raw_binding in args.binding:
            if "=" not in raw_binding:
                print(f"Binding inválido: {raw_binding!r}; use NAME=PATH.", file=sys.stderr)
                return 2
            name, raw_path = raw_binding.split("=", 1)
            if not name.strip() or not raw_path.strip() or name in safety_bindings:
                print(f"Binding inválido o duplicado: {raw_binding!r}.", file=sys.stderr)
                return 2
            safety_bindings[name] = Path(raw_path)
        try:
            verification = verify_apply_safety_on_temp_copy(
                source_canon_glob=args.canon_glob,
                temp_work_root=args.temp_work_root,
                candidates_file=args.candidates_file,
                human_review_decisions_file=args.human_review_decisions,
                dry_run_report_path=args.dry_run_report,
                binding_paths=safety_bindings,
                report_path=args.safety_report,
            )
        except (OSError, ValueError, RuntimeError) as error:
            print(f"Gate F bloqueado: {error}", file=sys.stderr)
            return 3
        print(json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.prepare_gate_g:
        if not args.human_review_decisions or not args.dry_run_report or not args.safety_verification_report:
            print(
                "Gate G requiere --human-review-decisions, --dry-run-report y "
                "--safety-verification-report.",
                file=sys.stderr,
            )
            return 2
        bindings: dict[str, Path] = {}
        for raw_binding in args.binding:
            if "=" not in raw_binding:
                print(f"Binding inválido: {raw_binding!r}; use NAME=PATH.", file=sys.stderr)
                return 2
            name, raw_path = raw_binding.split("=", 1)
            if not name.strip() or not raw_path.strip() or name in bindings:
                print(f"Binding inválido o duplicado: {raw_binding!r}.", file=sys.stderr)
                return 2
            bindings[name] = Path(raw_path)
        try:
            readiness = prepare_gate_g_package(
                candidates_file=args.candidates_file,
                canon_glob=args.canon_glob,
                human_review_decisions_file=args.human_review_decisions,
                dry_run_report_path=args.dry_run_report,
                out_dir=out,
                binding_paths=bindings,
                safety_verification_report=args.safety_verification_report,
                max_dry_run_age_minutes=args.max_dry_run_age_minutes,
            )
        except (OSError, ValueError, RuntimeError) as error:
            print(f"Gate G bloqueado: {error}", file=sys.stderr)
            return 3
        print(json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.rollback_snapshot:
        if args.rollback_confirmation != "ROLLBACK RELATIONS":
            print("ROLLBACK RELATIONS bloqueado: falta confirmación exacta.", file=sys.stderr)
            return 1
        try:
            rollback = rollback_relational_apply(
                snapshot_manifest_path=args.rollback_snapshot,
                out_dir=out,
            )
        except (OSError, ValueError, RuntimeError) as error:
            print(f"ROLLBACK RELATIONS falló: {error}", file=sys.stderr)
            return 1
        print(json.dumps(rollback, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    # Forbid ambiguous apply-like flags. The single supported mutating flag is
    # --apply, guarded below by persistent review + dry-run + terminal confirmation.
    raw = argv if argv is not None else sys.argv[1:]
    for arg in raw:
        if any(arg.lower().startswith(f) for f in ("--write", "--admit", "--force")):
            print(
                f"\nBLOQUEADO: flag mutante no soportado. "
                f"El flag '{arg}' está prohibido.\n",
                file=sys.stderr,
            )
            return 1

    if args.apply:
        dry_run_report = args.dry_run_report or args.output or (out / "admission_gate_dry_run.json")
        exact_bindings = {
            "candidate_manifest": args.candidates_file.parent / "current_candidate_manifest.json",
            "reconciliation_manifest": args.candidates_file.parent / "reconciliation_manifest.json",
            "reviewable_manifest": args.candidates_file.parent / "reviewable_candidate_manifest.json",
            "human_review_decisions": args.human_review_decisions,
            "dry_run_report": dry_run_report,
            "current_run_manifest": out / "current_run_manifest.json",
        }
        code, report = guarded_apply_relations(
            candidates_file=args.candidates_file,
            canon_glob=args.canon_glob,
            human_review_decisions_file=args.human_review_decisions,
            dry_run_report_path=dry_run_report,
            out_dir=out,
            terminal_confirmation=args.terminal_confirmation,
            max_dry_run_age_minutes=args.max_dry_run_age_minutes,
            perform_write=True,
            target_scope="production_path",
            binding_paths={
                name: path for name, path in exact_bindings.items() if path is not None
            },
            authorization_path=args.authorization_file,
            authorized_plan_path=args.authorized_plan,
        )
        plan = report["apply_plan"]
        if code != 0:
            print("APPLY RELATIONS bloqueado.", file=sys.stderr)
            if "missing_human_review" in plan.get("block_reasons", []):
                print(
                    "Motivo: no existe human_review_decision=approved_for_admission.",
                    file=sys.stderr,
                )
            elif "p0_block_reasons_present" in plan.get("block_reasons", []):
                print("Motivo: existen bloqueos P0 en admission gate.", file=sys.stderr)
            else:
                print(f"Motivo: {', '.join(plan.get('block_reasons') or ['blocked'])}.", file=sys.stderr)
            print("No se modificó el canon.", file=sys.stderr)
            print(f"[OK] Apply plan → {out / 'relation_apply_plan.json'}", file=sys.stderr)
            print(f"[OK] Apply report → {out / 'relation_apply_report.json'}", file=sys.stderr)
            return code
        print(f"[OK] Apply report → {out / 'relation_apply_report.json'}", file=sys.stderr)
        return 0

    # Load canon
    canon = load_canon_index(args.canon_glob)
    if args.verbose:
        print(f"  Canon: {len(canon)} tiddlers", file=sys.stderr)

    # Load candidates
    if not args.candidates_file.exists():
        print(f"[ERROR] candidates_file no existe: {args.candidates_file}", file=sys.stderr)
        return 2
    candidates = load_jsonl(args.candidates_file)

    if args.verbose:
        print(f"  Candidatos cargados: {len(candidates)}", file=sys.stderr)

    decisions_doc: dict[str, Any] | None = None
    batch_doc: dict[str, Any] | None = None
    batch_summary: dict[str, Any] | None = None
    type_policy: dict[str, dict[str, Any]] | None = None
    admissibility = load_json(args.admissibility_report, default={}) or {}
    admissibility_by_id = {
        str(item.get("candidate_id")): item
        for item in admissibility.get("results") or []
        if item.get("candidate_id")
    }

    persistent_decisions: dict[str, dict[str, Any]] = {}
    if args.human_review_decisions:
        persistent_decisions, decision_errors = load_persistent_human_review_decisions(args.human_review_decisions)
        if decision_errors:
            print(f"[ERROR] human_review_decisions inválido: {decision_errors}", file=sys.stderr)
            return 3
        candidates = apply_persistent_review_decisions_to_candidates(candidates, persistent_decisions)

    if session_tag in {"s0140", "s0141"} or args.human_review:
        # Build review queue artifacts if the admissibility report is available.
        queue = build_review_queue(
            admissibility,
            source_report=str(args.admissibility_report),
        )
        review_dir = args.review_dir
        if args.human_review and args.review_dir == S0140_REVIEW_DIR and session_tag != "s0140":
            review_dir = args.human_review.parent
        review_path = args.human_review or (review_dir / "human_review_decisions.json")
        if review_path.exists():
            decisions_doc = load_json(review_path, default={}) or {}
        else:
            decisions_doc = build_deferred_human_decisions(queue, session=session_label)
        review_errors = validate_human_review_decisions_doc(
            decisions_doc,
            expected_session=session_label,
        )
        if review_errors:
            print(f"[ERROR] human_review inválido: {review_errors}", file=sys.stderr)
            return 3
        write_review_artifacts(review_dir, queue, decisions_doc, session=session_label)
        type_policy = load_s0139_type_policy(args.type_policy_dir)

    if session_tag == "s0142" or args.human_review_batch:
        type_policy = load_s0139_type_policy(args.type_policy_dir)
        if args.human_review_batch:
            if args.human_review_batch.exists():
                batch_doc = load_json(args.human_review_batch, default={}) or {}
            else:
                batch_doc = empty_batch_decisions_doc()
        else:
            batch_doc = empty_batch_decisions_doc()
        batch_errors = validate_batch_decisions_doc(batch_doc)
        if batch_errors:
            print(f"[ERROR] human_review_batch inválido: {batch_errors}", file=sys.stderr)
            return 4
        classifications = classify_batch_candidates(
            candidates,
            canon,
            type_policy=type_policy,
            admissibility=admissibility_by_id,
            individual_decisions=human_decisions_by_candidate(decisions_doc),
        )
        batch_summary = build_batch_summary(classifications)

    # Evaluate each candidate through the gate
    results: list[dict[str, Any]] = []
    if decisions_doc and batch_doc is None:
        decision_ids = set(human_decisions_by_candidate(decisions_doc))
        candidates = [c for c in candidates if c.get("candidate_id") in decision_ids]
    for candidate in candidates:
        candidate_for_gate, human_notes = apply_review_sources(
            candidate,
            decisions_doc,
            batch_doc,
            batch_summary,
        )
        results.append(
            evaluate_gate(
                candidate_for_gate,
                canon,
                type_policy=type_policy,
                human_review_notes=human_notes,
            )
        )

    # A current operational run is a replaceable snapshot, not an append-only
    # mixture of historical namespaces. Historical runs remain archived.
    rotation = {"rotated": False, "archived_files": [], "history_path": None}
    out.mkdir(parents=True, exist_ok=True)
    if session_tag == "current":
        rotation = rotate_current_run(out)

    # Produce current outputs privately first.  If production fails after a
    # successful archive, no previous run is left visible as current.
    log_path = out / f"{session_tag}_relation_admission_log.jsonl"
    temporary_log_path = log_path.with_name(f"{log_path.name}.tmp") if session_tag == "current" else log_path
    if session_tag == "current":
        temporary_log_path.unlink(missing_ok=True)
    log_outcomes: list[dict[str, str]] = []
    for result, candidate in zip(results, candidates):
        outcome = append_to_log(result, candidate, temporary_log_path, session=session_tag)
        log_outcomes.append(outcome)

    report = build_dry_run_report(
        results,
        session=session_tag,
        candidates_file=args.candidates_file,
        canon_glob=args.canon_glob,
        persistent_human_decisions=persistent_decisions,
    )
    report_path = args.output or (out / f"{session_tag}_relation_admission_dry_run_report.json")
    temporary_report_path = report_path.with_name(f"{report_path.name}.tmp") if session_tag == "current" else report_path
    if session_tag == "current":
        temporary_report_path.unlink(missing_ok=True)
    temporary_report_path.parent.mkdir(parents=True, exist_ok=True)
    with temporary_report_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    if session_tag == "current":
        temporary_log_path.replace(log_path)
        temporary_report_path.replace(report_path)
        manifest_path = write_current_run_manifest(
            out=out,
            candidates_file=args.candidates_file,
            canon_glob=args.canon_glob,
            report_path=report_path,
            log_path=log_path,
            evaluated=len(results),
            human_decisions_path=args.human_review_decisions,
            rotation=rotation,
        )
        print(f"[OK] Manifiesto current → {manifest_path}", file=sys.stderr)
    print(f"[OK] Reporte → {report_path}", file=sys.stderr)
    print(f"[OK] Log → {log_path}", file=sys.stderr)

    if session_tag in {"s0140", "s0141", "s0142"} or args.human_review or args.human_review_batch:
        session_paths = write_session_admission_outputs(
            out,
            results,
            candidates_file=args.candidates_file,
            canon_glob=args.canon_glob,
            session_tag=session_tag,
        )
        for label, path in session_paths.items():
            print(f"[OK] {label} → {path}", file=sys.stderr)

    s = report["summary"]
    print(
        f"\n=== Relation Admission Gate ({session_tag.upper()}) — DRY-RUN ===\n"
        f"  Total evaluados          : {s['total_evaluated']}\n"
        f"  awaiting_human_review    : {s['awaiting_human_review']}\n"
        f"  technically_invalid      : {s['technically_invalid']}\n"
        f"  admission_ready_dry_run  : {s['admission_ready_dry_run']}\n"
    )
    if batch_summary is not None:
        decision = approved_batch_decision(batch_doc)
        print(
            "=== Relation Admission Gate — BATCH DRY-RUN ===\n"
            f"batch_id: {batch_summary.get('batch_id', '')}\n"
            f"batch_sha256: {batch_summary.get('batch_sha256', '')}\n"
            f"batch_approved: {str(decision is not None).lower()}\n"
        )
    print("[OK] Compuerta dry-run completada. El canon NO fue modificado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
