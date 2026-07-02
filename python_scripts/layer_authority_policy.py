"""Executable authority and grounding policy for local TDC layers (S0152)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayerPolicy:
    name: str
    role: str
    authority: str
    consumers: tuple[str, ...]
    allowed_uses: tuple[str, ...]
    prohibited_uses: tuple[str, ...]
    minimum_fields: tuple[str, ...]
    grounding: str
    freshness: str
    fallback: str
    severity: str


LAYER_POLICIES = {
    "canon": LayerPolicy(
        "canon", "primary governed record", "primary", ("validation", "operator", "future_rag"),
        ("final evidence", "identity", "admitted relations"),
        ("repository-current-code assertion without governed metadata",),
        ("id", "title", "version_id"), "self-governed canonical record", "not applicable",
        "report unknown; do not infer lifecycle", "error",
    ),
    "enriched": LayerPolicy(
        "enriched", "derived structured projection", "derived_non_authoritative", ("search", "audit", "future_rag"),
        ("navigation", "filtering", "derived inspection"), ("final evidence", "identity override"),
        ("id", "title", "version_id"), "must resolve to canon by id", "version_id equals canon",
        "return canonical record or report unavailable", "warning",
    ),
    "ai": LayerPolicy(
        "ai", "derived AI retrieval projection", "derived_non_authoritative", ("retrieval", "audit", "future_rag"),
        ("retrieval hints", "summaries", "candidate context"), ("final evidence", "citation without source return"),
        ("id", "title", "source_anchor"), "must resolve to canon by id", "version_id equals canon",
        "return canon/session/report source", "warning",
    ),
    "chunks": LayerPolicy(
        "chunks", "derived retrieval fragment", "derived_non_authoritative", ("retrieval", "future_rag"),
        ("localized retrieval", "candidate context"), ("final evidence", "admitted relation", "authority claim"),
        ("source_id", "source_title", "source_anchor"), "source and anchor must resolve to canon", "source_version_id equals canon",
        "return source canon/session/report; otherwise abstain", "error",
    ),
    "pipeline_audit": LayerPolicy(
        "pipeline/audit", "operational report and validation evidence", "evidence_non_authoritative", ("operator", "audit"),
        ("status", "warnings", "next safe action"), ("canonical identity override", "final semantic evidence"),
        ("generated_at",), "must identify its inputs when available", "generated snapshot may become stale",
        "report snapshot age/unknown and re-run read-only validation", "warning",
    ),
}

# Observed canon metadata.  These aliases are explicit compatibility facts, not
# title-based guesses and not a promise of universal coverage.
OBSERVED_METADATA_FIELDS = {
    "authority": ("authority_level",),
    "repo_lifecycle": ("repo_lifecycle_state",),
}

SEVERITY_ORDER = {"ok": 0, "notice": 1, "warning": 2, "blocked": 3}

TRANSITION_CONTRACTS = {
    "source_to_session": ("source_ref_or_path", "session_id", "limit"),
    "session_to_candidate": ("identity", "source_path", "scan_or_schema"),
    "candidate_to_canon": ("identity", "admission_decision", "validation_report"),
    "canon_to_enriched": ("id", "version_id", "manifest", "timestamp", "process"),
    "canon_to_ai": ("id", "source_anchor", "version_id", "manifest", "qc"),
    "canon_to_chunk": ("source_id", "source_title", "source_anchor", "chunk_index", "source_version_id", "qc"),
    "canon_to_pipeline_audit": ("input", "process", "result", "risk", "validation"),
}


def policy_for(layer: str) -> LayerPolicy:
    return LAYER_POLICIES[layer]


def final_evidence_allowed(layer: str) -> bool:
    """Only canon is final evidence; all other layers must return to it."""
    return policy_for(layer).authority == "primary"


def relation_status(layer: str) -> str:
    return "admitted" if layer == "canon" else "candidate_or_derived_not_admitted"


def observed_metadata(record: dict) -> dict:
    """Return explicitly observed fields; absent values remain not_recorded."""
    fields = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    return {name: next((fields[key] for key in aliases if fields.get(key) not in (None, "")), None)
            for name, aliases in OBSERVED_METADATA_FIELDS.items()}


def coverage_state(present: int, total: int) -> str:
    if not total:
        return "unknown"
    if not present:
        return "not_recorded"
    return "ok" if present == total else "partial"
