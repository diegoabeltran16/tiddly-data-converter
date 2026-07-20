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
import re
import shutil
import sys
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
SCHEMA_HUMAN_DECISION_LINE = "relation-human-review-decision/v1"
SCHEMA_HUMAN_QUEUE = "relation-human-review-queue/v1"
SCHEMA_PATCH_PREVIEW = "relation-admission-patch-preview/v1"
SCHEMA_APPLY_PLAN = "relation-admission-apply-plan/v1"
SCHEMA_APPLY_REPORT = "relation-admission-apply-report/v1"
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


def validate_human_review_decision_record(record: Any) -> list[str]:
    """Validate one S0165 persistent human-review JSONL record."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be object"]
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
    if decision == ADMISSION_HUMAN_REVIEW_DECISION:
        if not str(record.get("human_review_rationale") or "").strip():
            errors.append("human_review_rationale required for approval")
        if record.get("approval_scope") != "canonical_admission":
            errors.append("approval_scope must be canonical_admission for approval")
    evidence_paths = record.get("reviewed_evidence_paths")
    if evidence_paths is not None and not isinstance(evidence_paths, list):
        errors.append("reviewed_evidence_paths must be list")
    session_id = str(record.get("session_id") or "")
    if session_id and not re.fullmatch(r"S\d{4}", session_id):
        errors.append("session_id must match SNNNN")
    return errors


def load_human_review_decisions_jsonl(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
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
            record_errors = validate_human_review_decision_record(record)
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
        record_errors = validate_human_review_decision_record(record)
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
        if direct == ADMISSION_HUMAN_REVIEW_DECISION:
            if not str(candidate.get("human_review_rationale") or "").strip():
                reasons.append("GATE-024: human_review_rationale ausente o vacío.")
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
        "human_review_status": hr.get("status", "(absent)"),
        "human_review_decision": candidate.get(
            "human_review_decision",
            hr.get("decision", hr.get("status", "(absent)")),
        ),
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
    ready = [r for r in results if r["gate_status"] == ADMISSION_READY]
    blocked = [r for r in results if r["gate_status"] == BLOCKED]
    decisions = Counter(str(r.get("decision") or BLOCKED) for r in results)
    human_decisions = Counter(
        str(row.get("human_review_decision") or row.get("decision") or "")
        for row in (persistent_human_decisions or {}).values()
    )
    awaiting = decisions.get("blocked_missing_human_review", 0)
    rejected = decisions.get("rejected_by_human", 0)
    deferred = human_decisions.get("deferred", 0)
    technically_invalid = max(0, len(blocked) - awaiting - rejected - deferred)
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
            "approved_for_admission": human_decisions.get("approved_for_admission", 0),
            "admission_ready": len(ready),
            "admission_ready_dry_run": len(ready),
            "blocked": len(blocked),
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


def rotate_current_run(out: Path) -> dict[str, Any]:
    """Archive the previous operational current run and reset its mixed log."""
    log_path = out / "current_relation_admission_log.jsonl"
    previous_files = sorted(path for path in out.glob("*") if path.is_file())
    if not previous_files:
        return {"rotated": False, "archived_files": [], "history_path": None}
    previous_manifest = load_json(out / "current_run_manifest.json", default={}) or {}
    prior_seed = sha256_path(out / "admission_gate_dry_run.json") or datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = str(previous_manifest.get("run_id") or f"run-{prior_seed[:16]}")
    history = out.parent / "history" / run_id
    suffix = 1
    while history.exists():
        history = out.parent / "history" / f"{run_id}-{suffix}"
        suffix += 1
    history.mkdir(parents=True, exist_ok=False)
    archived = []
    for path in previous_files:
        shutil.copy2(path, history / path.name)
        archived.append(path.name)
    log_path.unlink(missing_ok=True)
    return {
        "rotated": True,
        "archived_files": archived,
        "history_path": str(history),
    }


def write_current_run_manifest(
    *, out: Path, candidates_file: Path, canon_glob: str, report_path: Path,
    log_path: Path, evaluated: int, human_decisions_path: Path | None,
    rotation: dict[str, Any],
) -> Path:
    candidate_dir = candidates_file.parent
    candidate_manifest = candidate_dir / "current_candidate_manifest.json"
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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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


def dry_run_p0_block_reasons(report: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for item in report.get("items") or []:
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
            "human_review_rationale": review.get("human_review_rationale") or "",
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
        if not str(authority.get("human_review_rationale") or "").strip():
            errors.append("authority.human_review_rationale required")
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
) -> dict[str, Any]:
    approved_ids = {
        cid for cid, decision in human_review_decisions.items()
        if decision.get("human_review_decision") == ADMISSION_HUMAN_REVIEW_DECISION
        and decision.get("approval_scope") == "canonical_admission"
        and str(decision.get("human_review_rationale") or "").strip()
    }
    dry_run_items = dry_run_report.get("items") or []
    ready_ids = {
        str(item.get("candidate_id"))
        for item in dry_run_items
        if item.get("gate_status") == ADMISSION_READY
        or item.get("admission_ready_dry_run") is True
    }
    p0_reasons = dry_run_p0_block_reasons(dry_run_report)
    would_apply_ids = sorted(approved_ids & ready_ids) if dry_run_recent and not p0_reasons else []
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
    apply_plan_id = "apply_" + hashlib.sha256(
        json.dumps({
            "approved_ids": sorted(approved_ids),
            "ready_ids": sorted(ready_ids),
            "canon_before_count": canon_before_count,
            "dry_run_report": str(dry_run_report_path),
        }, sort_keys=True).encode()
    ).hexdigest()[:16]
    return {
        "schema": SCHEMA_APPLY_PLAN,
        "apply_plan_id": apply_plan_id,
        "generated_at": utc_now(),
        "canon_before_count": canon_before_count,
        "candidate_count": len(candidates),
        "approved_count": len(approved_ids),
        "blocked_count": len(candidates) - len(would_apply_ids),
        "would_apply_count": len(would_apply_ids),
        "would_apply_candidate_ids": would_apply_ids,
        "block_reasons": block_reasons,
        "dry_run_report": str(dry_run_report_path),
        "dry_run_recent": dry_run_recent,
        "p0_block_reason_count": len(p0_reasons),
        "canon_modified": False,
    }


def write_apply_plan(plan: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "relation_apply_plan.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


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
) -> tuple[int, dict[str, Any]]:
    """Build an apply plan and optionally mutate canon only after all guards pass."""
    candidates = load_jsonl(candidates_file) if candidates_file.exists() else []
    decisions, decision_errors = load_persistent_human_review_decisions(human_review_decisions_file)
    dry_run_report = load_dry_run_report(dry_run_report_path)
    dry_run_recent, dry_run_recent_reason = dry_run_report_is_recent(
        dry_run_report_path,
        max_age_minutes=max_dry_run_age_minutes,
    )
    plan = build_apply_plan(
        candidates=candidates,
        canon_glob=canon_glob,
        human_review_decisions=decisions,
        dry_run_report=dry_run_report,
        dry_run_report_path=dry_run_report_path,
        dry_run_recent=dry_run_recent,
        dry_run_recent_reason=dry_run_recent_reason,
    )
    if decision_errors:
        plan["block_reasons"].extend(f"invalid_human_review: {err}" for err in decision_errors)
        plan["would_apply_count"] = 0
        plan["would_apply_candidate_ids"] = []
        plan["blocked_count"] = len(candidates)
    if terminal_confirmation != APPLY_CONFIRMATION:
        plan["block_reasons"].append("missing_exact_terminal_confirmation")
        plan["would_apply_count"] = 0
        plan["would_apply_candidate_ids"] = []
        plan["blocked_count"] = len(candidates)
    plan_path = write_apply_plan(plan, out_dir)

    report = {
        "schema": SCHEMA_APPLY_REPORT,
        "generated_at": utc_now(),
        "report_kind": "blocked_apply_report",
        "target_scope": target_scope,
        "apply_executed": False,
        "apply_plan_path": str(plan_path),
        "apply_plan": plan,
        "would_apply_count": plan["would_apply_count"],
        "blocked_count": plan["blocked_count"],
        "applied_count": 0,
        "canon_before_count": plan["canon_before_count"],
        "canon_after_count": plan["canon_before_count"],
        "canon_modified": False,
        "status": "blocked",
    }
    if plan["block_reasons"]:
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

    applied_count = 0
    for fpath in sorted(glob.glob(canon_glob)):
        path = Path(fpath)
        lines: list[str] = []
        changed = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            relations = selected_by_source.get(str(rec.get("id") or ""))
            if relations:
                current = rec.get("relations")
                if not isinstance(current, list):
                    current = []
                existing = {
                    (
                        str(r.get("source_id") or rec.get("id") or ""),
                        str(r.get("target_id") or ""),
                        str(r.get("relation_type") or r.get("type") or ""),
                    )
                    for r in current
                    if isinstance(r, dict)
                }
                for relation in relations:
                    key = (relation["source_id"], relation["target_id"], relation["relation_type"])
                    if key not in existing:
                        current.append(relation)
                        existing.add(key)
                        applied_count += 1
                        changed = True
                rec["relations"] = current
            lines.append(json.dumps(rec, ensure_ascii=False))
        if changed:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    canon_after_count = count_canon_records(canon_glob)
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
        "canon_modified": applied_count > 0,
    })
    report["apply_plan"]["canon_modified"] = applied_count > 0
    (out_dir / "relation_apply_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
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
        code, report = guarded_apply_relations(
            candidates_file=args.candidates_file,
            canon_glob=args.canon_glob,
            human_review_decisions_file=args.human_review_decisions,
            dry_run_report_path=dry_run_report,
            out_dir=out,
            terminal_confirmation=args.terminal_confirmation,
            max_dry_run_age_minutes=args.max_dry_run_age_minutes,
            perform_write=True,
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
    if session_tag == "current":
        rotation = rotate_current_run(out)

    # Append to log
    log_path = out / f"{session_tag}_relation_admission_log.jsonl"
    log_outcomes: list[dict[str, str]] = []
    for result, candidate in zip(results, candidates):
        outcome = append_to_log(result, candidate, log_path, session=session_tag)
        log_outcomes.append(outcome)

    # Build and write report
    report = build_dry_run_report(
        results,
        session=session_tag,
        candidates_file=args.candidates_file,
        canon_glob=args.canon_glob,
        persistent_human_decisions=persistent_decisions,
    )
    report_path = args.output or (out / f"{session_tag}_relation_admission_dry_run_report.json")
    out.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    if session_tag == "current":
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
        f"  admission_ready_dry_run  : {s['admission_ready_dry_run']}\n"
        f"  blocked                  : {s['blocked']}\n"
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
