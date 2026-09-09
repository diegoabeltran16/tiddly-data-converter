#!/usr/bin/env python3
"""Family-first routing and evidence-only canonical comparison.

This boundary intentionally dispatches to existing family owners.  It does not
generate candidates, write the canon, or redefine family identity/schema
contracts.  Unknown authority is reported as ``UNRESOLVED`` fail-closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from diagnostic_governance import validate_full_path
from generate_session_deliverables import validate_deliverable_file
from session_artifact_governance import classify_artifact_family


SESSION_FAMILIES = {
    "contrato_de_sesion",
    "procedencia_de_sesion",
    "detalles_de_sesion",
    "hipotesis_de_sesion",
    "balance_de_sesion",
    "propuesta_de_sesion",
    "diagnostico_de_sesion",
}


@dataclass(frozen=True)
class RouteEvidence:
    family: str
    owner: str | None
    path: str
    reason: str

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def route_artifact(path: Path, payload: dict[str, Any], sessions_dir: Path) -> RouteEvidence:
    """Route using durable family signals before selecting a validator."""
    family_spec = classify_artifact_family(path, sessions_dir)
    if family_spec is not None:
        if family_spec.family in SESSION_FAMILIES:
            return RouteEvidence("session_deliverable", "session_artifact_governance", str(path), "known session family")
        if family_spec.family == "diagnostico_tematico":
            return RouteEvidence("thematic_diagnostic", "diagnostic_governance", str(path), "thematic diagnosis root")

    title = str(payload.get("title") or "")
    if title in {"#### 🤖🌀 Agente de Contexto de Sesión", "#### 🤖🌀 Agente de Calidad y Reconstrucción"}:
        return RouteEvidence("agent_definition", "canonical_agent_contract", str(path), "canonical agent title")
    if str((payload.get("source_fields") or {}).get("artifact_family") or "") == "policy":
        return RouteEvidence("policy", "policy_owner", str(path), "declared policy family")
    if payload.get("technical_report") is True:
        return RouteEvidence("technical_report", "technical_report_owner", str(path), "declared technical report")
    return RouteEvidence("other_or_unsupported", None, str(path), "no supported family owner")


def validate_routed_artifact(route: RouteEvidence, path: Path, payload: dict[str, Any], sessions_dir: Path) -> dict[str, Any]:
    """Validate only through the owner selected by routing."""
    if route.family == "session_deliverable":
        errors = validate_deliverable_file(path)
        return {"valid": not errors, "errors": [str(error) for error in errors], "owner": route.owner}
    if route.family == "thematic_diagnostic":
        valid, reason = validate_full_path(str(path), sessions_dir)
        return {"valid": valid, "errors": [] if valid else [reason], "owner": route.owner}
    if route.family == "agent_definition":
        required = [field for field in ("id", "title", "version_id") if not payload.get(field)]
        return {"valid": not required, "errors": [f"missing:{field}" for field in required], "owner": route.owner}
    if route.family in {"policy", "technical_report"}:
        return {"valid": bool(payload.get("title")), "errors": [] if payload.get("title") else ["missing:title"], "owner": route.owner}
    return {"valid": False, "errors": ["unsupported_family_owner"], "owner": None}


def _fingerprint(record: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def compare_canonical(route: RouteEvidence, payload: dict[str, Any], canon_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return evidence for SAME/MISSING/REPLACEMENT/CONFLICT/UNRESOLVED.

    Family routing precedes this function.  The function only compares supplied
    evidence and deliberately has no candidate-preparation or canon-write path.
    """
    if route.family == "other_or_unsupported":
        return {"decision": "UNRESOLVED", "reason": "unsupported_family_owner"}
    if route.family == "thematic_diagnostic":
        return {"decision": "UNRESOLVED", "reason": "canonical_scope_not_authorized_for_thematic_diagnostic"}

    identity = payload.get("id")
    if not isinstance(identity, str) or not identity:
        return {"decision": "UNRESOLVED", "reason": "identity_evidence_missing"}

    records = list(canon_records)
    same_id = [record for record in records if record.get("id") == identity]
    if len(same_id) > 1:
        return {"decision": "CONFLICT", "reason": "multiple_canon_records_for_identity", "identity": identity}
    if same_id:
        existing = same_id[0]
        if _fingerprint(existing) == _fingerprint(payload):
            return {"decision": "SAME", "reason": "family_contract_exact_evidence", "identity": identity}
        if route.family == "agent_definition" and existing.get("version_id") == payload.get("version_id"):
            return {"decision": "SAME", "reason": "agent_revision_evidence", "identity": identity}
        return {"decision": "REPLACEMENT", "reason": "same_family_identity_material_revision", "identity": identity}

    title = payload.get("title")
    title_matches = [record for record in records if title and record.get("title") == title]
    if title_matches:
        return {"decision": "CONFLICT", "reason": "title_collision_with_different_identity", "identity": identity}
    return {"decision": "MISSING", "reason": "identity_and_scope_resolved_absent_from_canon", "identity": identity}
