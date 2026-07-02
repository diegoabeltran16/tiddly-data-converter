#!/usr/bin/env python3
"""Read-only validator for S0152 layer authority, grounding and freshness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from layer_authority_policy import (LAYER_POLICIES, TRANSITION_CONTRACTS, coverage_state,
                                    final_evidence_allowed, observed_metadata, relation_status)
from path_governance import DEFAULT_AI_DIR, DEFAULT_AUDIT_DIR, DEFAULT_CANON_DIR, DEFAULT_ENRICHED_DIR, sorted_canon_shards


def _jsonl(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def _status(findings: list[dict]) -> str:
    order = {"ok": 0, "notice": 1, "warning": 2, "blocked": 3}
    return max((item.get("severity", "ok") for item in findings), key=lambda value: order[value], default="ok")


def _result(layer: str, findings: list[dict], lineage: str, freshness: str, grounding: str, authority: str, next_action: str) -> dict:
    return {
        "layer": layer, "state": _status(findings), "lineage": lineage, "freshness": freshness,
        "grounding": grounding, "authority": authority, "warnings": findings,
        "next_safe_action": next_action,
    }


def _check_projection(layer: str, rows: list[dict], canon: dict[str, dict]) -> tuple[list[dict], int]:
    findings, stale = [], 0
    for row in rows:
        source_id = str(row.get("id") or row.get("source_id") or "")
        parent = canon.get(source_id)
        if not parent:
            stale += 1
            findings.append({"severity": "blocked", "code": "source_not_recoverable", "id": source_id})
        elif row.get("version_id") and row.get("version_id") != parent.get("version_id"):
            stale += 1
            findings.append({"severity": "warning", "code": "stale_version", "id": source_id})
    return findings, stale


def validate_layers(canon_dir: Path = DEFAULT_CANON_DIR, enriched_dir: Path = DEFAULT_ENRICHED_DIR,
                    ai_dir: Path = DEFAULT_AI_DIR, audit_dir: Path = DEFAULT_AUDIT_DIR) -> dict:
    canon_rows = _jsonl(sorted_canon_shards(canon_dir))
    canon = {str(row.get("id")): row for row in canon_rows if row.get("id")}
    observed = [observed_metadata(row) for row in canon_rows]
    authority_present = sum(bool(item["authority"]) for item in observed)
    lifecycle_present = sum(bool(item["repo_lifecycle"]) for item in observed)
    canon_findings = []
    authority_coverage = coverage_state(authority_present, len(canon_rows))
    lifecycle_coverage = coverage_state(lifecycle_present, len(canon_rows))
    if authority_coverage != "ok":
        canon_findings.append({"severity": "warning", "code": "authority_level_partial", "coverage": authority_coverage, "present": authority_present, "total": len(canon_rows)})
    if lifecycle_coverage != "ok":
        canon_findings.append({"severity": "warning", "code": "repo_lifecycle_partial_not_universal", "coverage": lifecycle_coverage, "present": lifecycle_present, "total": len(canon_rows)})

    enriched_rows = _jsonl(sorted(enriched_dir.glob("tiddlers_enriched_*.jsonl")))
    enriched_findings, enriched_stale = _check_projection("enriched", enriched_rows, canon)
    ai_rows = _jsonl(sorted(ai_dir.glob("tiddlers_ai_*.jsonl")))
    ai_findings, ai_stale = _check_projection("ai", ai_rows, canon)

    chunk_findings, chunk_stale = [], 0
    chunks = _jsonl(sorted(ai_dir.glob("chunks_ai_*.jsonl")))
    derived_relation_targets = 0
    for chunk in chunks:
        source_id = str(chunk.get("source_id") or "")
        anchor = chunk.get("source_anchor")
        missing = [name for name, value in (("source_id", source_id), ("source_title", chunk.get("source_title")), ("source_anchor", anchor)) if not value]
        if missing:
            chunk_findings.append({"severity": "blocked", "code": "chunk_missing_grounding", "chunk_id": chunk.get("chunk_id"), "fields": missing})
            continue
        parent = canon.get(source_id)
        if not parent or not isinstance(anchor, dict) or anchor.get("canon_id") != source_id:
            chunk_stale += 1
            chunk_findings.append({"severity": "blocked", "code": "chunk_source_not_recoverable", "chunk_id": chunk.get("chunk_id")})
        elif chunk.get("source_version_id") and chunk.get("source_version_id") != parent.get("version_id"):
            chunk_stale += 1
            chunk_findings.append({"severity": "warning", "code": "chunk_stale_version", "chunk_id": chunk.get("chunk_id")})
        derived_relation_targets += len(chunk.get("relation_targets") or [])
    if derived_relation_targets:
        chunk_findings.append({"severity": "notice", "code": "relation_targets_not_admitted", "count": derived_relation_targets})

    audit_manifest = audit_dir / "manifest.json"
    audit_findings = [] if audit_manifest.exists() else [{"severity": "warning", "code": "audit_manifest_not_recorded"}]
    enriched_manifest = enriched_dir / "manifest.json"
    ai_manifest = ai_dir / "manifest.json"
    transitions = [
        {"transition": "source_to_session", "coverage": "not_recorded", "severity": "warning", "required": TRANSITION_CONTRACTS["source_to_session"], "next_safe_action": "record source reference when a new session is created"},
        {"transition": "session_to_candidate", "coverage": "partial", "severity": "warning", "required": TRANSITION_CONTRACTS["session_to_candidate"], "next_safe_action": "use session_sync/schema evidence for new candidates"},
        {"transition": "candidate_to_canon", "coverage": "not_recorded", "severity": "warning", "required": TRANSITION_CONTRACTS["candidate_to_canon"], "next_safe_action": "require admission decision and report; do not infer history"},
        {"transition": "canon_to_enriched", "coverage": "ok" if enriched_rows and enriched_manifest.exists() else "partial", "severity": "ok" if enriched_rows and enriched_manifest.exists() else "warning", "required": TRANSITION_CONTRACTS["canon_to_enriched"], "next_safe_action": "return to canon for final evidence"},
        {"transition": "canon_to_ai", "coverage": "ok" if ai_rows and ai_manifest.exists() else "partial", "severity": "notice" if ai_rows and ai_manifest.exists() else "warning", "required": TRANSITION_CONTRACTS["canon_to_ai"], "next_safe_action": "ground summaries in canon/session/report"},
        {"transition": "canon_to_chunk", "coverage": "ok" if chunks and not chunk_stale else "partial", "severity": "notice" if chunks and not chunk_stale else "blocked", "required": TRANSITION_CONTRACTS["canon_to_chunk"], "next_safe_action": "retrieve source or abstain"},
        {"transition": "canon_to_pipeline_audit", "coverage": "ok" if audit_manifest.exists() else "partial", "severity": "ok" if audit_manifest.exists() else "warning", "required": TRANSITION_CONTRACTS["canon_to_pipeline_audit"], "next_safe_action": "re-run read-only validation before acting"},
    ]
    results = [
        _result("canon", canon_findings, f"{len(canon_rows)} canonical records", "current source snapshot", "self-governed", "primary", "use governed metadata; lifecycle only for applicable repo artifacts"),
        _result("enriched", enriched_findings, f"{len(enriched_rows)} records -> canon", "stale" if enriched_stale else "current", "id/version return to canon", "derived_non_authoritative", "return to canon before final claim"),
        _result("ai", ai_findings + [{"severity": "notice", "code": "ai_summary_not_final_evidence"}] if ai_rows else ai_findings, f"{len(ai_rows)} records -> canon/enriched", "stale" if ai_stale else "current", "id/version return to canon", "derived_non_authoritative", "return to canon/session/report before final answer"),
        _result("chunks", chunk_findings, f"{len(chunks)} chunks -> source canon", "stale" if chunk_stale else "current", "source_id + title + source_anchor", "derived_non_authoritative", "retrieve source or abstain"),
        _result("pipeline/audit", audit_findings, "operational reports over local layers", "snapshot" if audit_manifest.exists() else "unknown", "manifest/input declaration", "evidence_non_authoritative", "re-run read-only validation before acting"),
    ]
    return {"schema": "layer-authority-validation/v2", "read_only": True, "policy_layers": list(LAYER_POLICIES), "coverage": {"authority_level": {"present": authority_present, "total": len(canon_rows), "state": authority_coverage}, "repo_lifecycle_state": {"present": lifecycle_present, "total": len(canon_rows), "state": lifecycle_coverage}}, "final_evidence": {layer: final_evidence_allowed(layer) for layer in LAYER_POLICIES}, "relation_status": {layer: relation_status(layer) for layer in LAYER_POLICIES}, "layers": results, "transitions": transitions}


def render_human(report: dict) -> str:
    lines = ["capa | estado | linaje | frescura | grounding | autoridad | acción segura"]
    for row in report["layers"]:
        lines.append(" | ".join(str(row[key]) for key in ("layer", "state", "lineage", "freshness", "grounding", "authority", "next_safe_action")))
    lines.append("transición | cobertura | severidad | acción segura")
    for row in report["transitions"]:
        lines.append(" | ".join(str(row[key]) for key in ("transition", "coverage", "severity", "next_safe_action")))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate layer authority without modifying local data.")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--canon-dir", type=Path, default=DEFAULT_CANON_DIR)
    parser.add_argument("--enriched-dir", type=Path, default=DEFAULT_ENRICHED_DIR)
    parser.add_argument("--ai-dir", type=Path, default=DEFAULT_AI_DIR)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    args = parser.parse_args()
    report = validate_layers(args.canon_dir, args.enriched_dir, args.ai_dir, args.audit_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
