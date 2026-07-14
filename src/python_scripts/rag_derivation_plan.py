#!/usr/bin/env python3
"""Contractual preview-to-production plan support for S0172.

The module validates evidence.  It never writes productive derivatives and
does not decide to enable production by itself.
"""

from __future__ import annotations

import hashlib
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_derivation_profile import sha256_file, stable_json
from rag_derivative_writers import require_nonproductive_evidence_target


PLAN_SCHEMA_VERSION = "rag-derivation-plan/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_snapshot(input_dir: Path | str) -> dict[str, Any]:
    root = Path(input_dir)
    files = sorted(root.glob("tiddlers_*.jsonl"), key=lambda item: item.name)
    digest = hashlib.sha256()
    records = 0
    entries: list[dict[str, Any]] = []
    for path in files:
        content = path.read_bytes()
        lines = sum(1 for line in content.splitlines() if line.strip())
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
        records += lines
        entries.append({"path": str(path), "sha256": hashlib.sha256(content).hexdigest(), "line_count": lines})
    if not entries:
        raise FileNotFoundError(f"no canon shards found in {root}")
    canon_hash = digest.hexdigest()
    return {
        "source_canon_version_id": f"sha256:{canon_hash}",
        "source_canon_hash": canon_hash,
        "source_canon_record_count": records,
        "source_canon_shard_count": len(entries),
        "source_canon_files": entries,
    }


def write_json(path: Path | str, payload: dict[str, Any]) -> Path:
    target = require_nonproductive_evidence_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_json(path: Path | str, *, label: str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"{label} is required: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {target}")
    return payload


def build_plan(
    *,
    run_id: str,
    canon: dict[str, Any],
    preview_manifest_path: Path | str,
    gate_report_path: Path | str,
    profile_path: Path | str,
    tag_policy_path: Path | str,
    metadata_policy_path: Path | str,
    metadata_candidates_path: Path | str | None = None,
    tag_inventory_path: Path | str | None = None,
    semantic_builder_path: Path | str | None = None,
    semantic_type_policy_path: Path | str | None = None,
    productive_orchestrator_path: Path | str | None = None,
    equivalence_contract_path: Path | str | None = None,
    status_override: str | None = None,
    productive_write_reason: str | None = None,
    gate_report: dict[str, Any],
    planned_productive_outputs: list[str] | None = None,
) -> dict[str, Any]:
    preview_path = Path(preview_manifest_path)
    gate_path = Path(gate_report_path)
    profile = Path(profile_path)
    tag_policy = Path(tag_policy_path)
    metadata_policy = Path(metadata_policy_path)
    candidates = Path(metadata_candidates_path) if metadata_candidates_path else None
    tag_inventory = Path(tag_inventory_path) if tag_inventory_path else None
    semantic_builder = Path(semantic_builder_path) if semantic_builder_path else None
    semantic_type_policy = Path(semantic_type_policy_path) if semantic_type_policy_path else None
    payload = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": utc_now(),
        "status": status_override or (
            "validated_preview"
            if gate_report.get("status") == "pass" and gate_report.get("blocking") is not True
            else "preview_not_validated"
        ),
        **canon,
        "preview_manifest_path": str(preview_path),
        "preview_manifest_hash": sha256_file(preview_path),
        "gate_report_path": str(gate_path),
        "gate_report_hash": sha256_file(gate_path),
        "gate_status": gate_report.get("status"),
        "derivation_profile_path": str(profile),
        "derivation_profile_hash": sha256_file(profile),
        "tag_policy_path": str(tag_policy),
        "tag_policy_hash": sha256_file(tag_policy),
        "metadata_policy_path": str(metadata_policy),
        "metadata_policy_hash": sha256_file(metadata_policy),
        "planned_productive_outputs": planned_productive_outputs or [],
        "productive_write_allowed": False,
        "productive_write_reason": productive_write_reason or "S0172 validates plan only; execution reserved for S0173",
        "canon_modified": False,
        "productive_derivatives_modified": False,
    }
    if candidates is not None:
        payload["metadata_candidates_path"] = str(candidates)
        payload["metadata_candidates_hash"] = sha256_file(candidates)
    for key, path in (
        ("tag_inventory", tag_inventory),
        ("semantic_builder", semantic_builder),
        ("semantic_type_policy", semantic_type_policy),
        ("productive_orchestrator", Path(productive_orchestrator_path) if productive_orchestrator_path else None),
        ("equivalence_contract", Path(equivalence_contract_path) if equivalence_contract_path else None),
    ):
        if path is not None:
            payload[f"{key}_path"] = str(path)
            payload[f"{key}_hash"] = sha256_file(path)
    return payload


def evaluate_productive_write_preflight(
    *,
    plan_path: Path | str | None,
    preview_manifest_path: Path | str | None,
    gate_report_path: Path | str | None,
    profile_path: Path | str | None,
    tag_policy_path: Path | str | None,
    metadata_policy_path: Path | str | None,
    metadata_candidates_path: Path | str | None = None,
    tag_inventory_path: Path | str | None = None,
    semantic_builder_path: Path | str | None = None,
    semantic_type_policy_path: Path | str | None = None,
    productive_orchestrator_path: Path | str | None = None,
    canon: dict[str, Any],
) -> dict[str, Any]:
    """Return a deterministic allow/deny verdict without writing outputs."""

    reasons: list[str] = []
    plan: dict[str, Any] = {}
    required = {
        "plan": plan_path,
        "preview_manifest": preview_manifest_path,
        "gate_report": gate_report_path,
        "derivation_profile": profile_path,
        "tag_policy": tag_policy_path,
        "metadata_policy": metadata_policy_path,
        "metadata_candidates": metadata_candidates_path,
        "tag_inventory": tag_inventory_path,
        "semantic_builder": semantic_builder_path,
        "semantic_type_policy": semantic_type_policy_path,
        "productive_orchestrator": productive_orchestrator_path,
    }
    resolved: dict[str, Path] = {}
    for label, raw_path in required.items():
        if not raw_path:
            reasons.append(f"missing_{label}")
            continue
        target = Path(raw_path)
        if not target.exists():
            reasons.append(f"missing_{label}")
            continue
        resolved[label] = target
    if "plan" in resolved:
        try:
            plan = load_json(resolved["plan"], label="rag derivation plan")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"invalid_plan:{exc}")

    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        reasons.append("plan_schema_version_mismatch")
    if plan.get("status") != "validated_preview":
        reasons.append("plan_status_not_validated_preview")

    gate: dict[str, Any] = {}
    if "gate_report" in resolved:
        try:
            gate = load_json(resolved["gate_report"], label="rag gate report")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"invalid_gate_report:{exc}")
    if gate.get("status") != "pass":
        reasons.append("gate_status_not_pass")
    if gate.get("blocking") is True:
        reasons.append("gate_report_blocking")
    if gate.get("schema") != "rag-tag-gate/v1":
        reasons.append("gate_report_schema_version_mismatch")
    for key in (
        "p0_tags_in_semantic_text",
        "p0_tags_in_retrieval_hints",
        "p0_tags_in_embedding_metadata",
        "unknown_tags_in_semantic_text",
        "unknown_tags_in_retrieval_hints",
        "unknown_tags_in_embedding_metadata",
        "p1_raw_tags_in_semantic_text",
        "p1_raw_tags_in_retrieval_hints",
        "p1_raw_tags_in_embedding_metadata",
        "template_nodes_as_topics",
        "formal_relation_edges_emitted",
    ):
        if gate.get(key) != 0:
            reasons.append(f"gate_invariant_not_zero:{key}")

    preview: dict[str, Any] = {}
    if "preview_manifest" in resolved:
        try:
            preview = load_json(resolved["preview_manifest"], label="rag preview manifest")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"invalid_preview_manifest:{exc}")
    if preview.get("schema_version") != "rag-preview-manifest/v1":
        reasons.append("preview_manifest_schema_version_mismatch")
    if preview.get("productive_orchestrator") != "derive_layers.py":
        reasons.append("preview_manifest_orchestrator_mismatch")
    if (
        preview.get("gate_status") != "pass"
        or preview.get("productive_write") is not False
        or preview.get("semantic_dynamic_relation_preview_inputs") is not False
    ):
        reasons.append("preview_manifest_not_guarded_pass")

    comparisons = {
        "preview_manifest_hash": "preview_manifest",
        "derivation_profile_hash": "derivation_profile",
        "tag_policy_hash": "tag_policy",
        "metadata_policy_hash": "metadata_policy",
        "metadata_candidates_hash": "metadata_candidates",
        "tag_inventory_hash": "tag_inventory",
        "semantic_builder_hash": "semantic_builder",
        "semantic_type_policy_hash": "semantic_type_policy",
        "productive_orchestrator_hash": "productive_orchestrator",
        "gate_report_hash": "gate_report",
    }
    for plan_key, path_key in comparisons.items():
        target = resolved.get(path_key)
        if not target:
            continue
        if plan.get(plan_key) != sha256_file(target):
            reasons.append(f"{path_key}_hash_mismatch")
    for key in ("source_canon_version_id", "source_canon_hash"):
        if plan.get(key) != canon.get(key):
            reasons.append(f"{key}_mismatch")
        if preview.get(key) != canon.get(key):
            reasons.append(f"preview_{key}_mismatch")
    for key in (
        "source_canon_version_id",
        "source_canon_hash",
        "derivation_profile_hash",
        "tag_policy_hash",
        "metadata_policy_hash",
        "metadata_candidates_hash",
        "tag_inventory_hash",
        "semantic_builder_hash",
        "semantic_type_policy_hash",
    ):
        if preview.get(key) != plan.get(key):
            reasons.append(f"preview_plan_{key}_mismatch")
    if plan.get("gate_status") != "pass":
        reasons.append("plan_gate_status_not_pass")
    if preview.get("gate_status") != plan.get("gate_status"):
        reasons.append("preview_plan_gate_status_mismatch")
    if plan.get("productive_write_allowed") is not True:
        reasons.append("plan_disallows_productive_write")

    return {
        "schema_version": "rag-productive-write-preflight/v1",
        "checked_at": utc_now(),
        "productive_write_allowed": not reasons,
        "blocking_reasons": sorted(set(reasons)),
        "plan_path": str(resolved["plan"]) if "plan" in resolved else None,
        "gate_status": gate.get("status") if gate else None,
        "canon": canon,
        "S0172_contract": "productive output remains blocked until a future authorized session",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a governed rag-derivation-plan/v1 artifact.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--canon-dir", required=True)
    parser.add_argument("--preview-manifest", required=True)
    parser.add_argument("--gate-report", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--tag-policy", required=True)
    parser.add_argument("--metadata-policy", required=True)
    parser.add_argument("--metadata-candidates", required=True)
    parser.add_argument("--tag-inventory", required=True)
    parser.add_argument("--semantic-builder", required=True)
    parser.add_argument("--semantic-type-policy", required=True)
    parser.add_argument("--productive-orchestrator", required=True)
    parser.add_argument("--equivalence-contract")
    parser.add_argument("--plan-out", required=True)
    parser.add_argument("--plan-md")
    parser.add_argument("--status", default=None)
    parser.add_argument("--productive-write-reason", default=None)
    args = parser.parse_args()
    gate = load_json(args.gate_report, label="RAG gate report")
    plan = build_plan(
        run_id=args.run_id,
        canon=canonical_snapshot(args.canon_dir),
        preview_manifest_path=args.preview_manifest,
        gate_report_path=args.gate_report,
        profile_path=args.profile,
        tag_policy_path=args.tag_policy,
        metadata_policy_path=args.metadata_policy,
        metadata_candidates_path=args.metadata_candidates,
        tag_inventory_path=args.tag_inventory,
        semantic_builder_path=args.semantic_builder,
        semantic_type_policy_path=args.semantic_type_policy,
        productive_orchestrator_path=args.productive_orchestrator,
        equivalence_contract_path=args.equivalence_contract,
        status_override=args.status,
        productive_write_reason=args.productive_write_reason,
        gate_report=gate,
        planned_productive_outputs=[
            "data/out/local/enriched/",
            "data/out/local/ai/",
            "data/out/local/microsoft_copilot/",
        ],
    )
    write_json(args.plan_out, plan)
    if args.plan_md:
        md_target = require_nonproductive_evidence_target(args.plan_md)
        md_target.parent.mkdir(parents=True, exist_ok=True)
        md_target.write_text(
            "# Plan de derivación productiva gobernada\n\n"
            f"- run_id: `{plan['run_id']}`\n"
            f"- status: `{plan['status']}`\n"
            f"- productive_write_allowed: `{str(plan['productive_write_allowed']).lower()}`\n"
            f"- reason: {plan['productive_write_reason']}\n",
            encoding="utf-8",
        )
    print(stable_json(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
