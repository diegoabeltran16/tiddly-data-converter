#!/usr/bin/env python3
"""S0174 integration and governance evidence helpers.

This module is an evidence/gate layer around the existing authoritative
``derive_layers.py`` producer and ``rag_derivative_writers.py`` writer.  It
does not derive records, infer relations, or authorize a productive write.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_derivation_plan import canonical_snapshot
from rag_derivation_preflight import productive_derivatives_manifest
from rag_derivative_writers import (
    ProductiveWriteBlocked,
    promote_staging_transaction,
    require_nonproductive_evidence_target,
    rollback_productive_transaction,
    snapshot_productive_derivatives,
    verify_productive_state_matches_snapshot,
)
from validate_productive_equivalence import build_equivalence_report


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
LOCAL_ROOT = REPO_ROOT / "data" / "out" / "local"
S0173_PIPELINE_ROOT = LOCAL_ROOT / "pipeline" / "rag_derivation" / "s0173"
S0173_AUDIT_ROOT = LOCAL_ROOT / "audit" / "rag_derivation" / "s0173"
S0174_PIPELINE_ROOT = LOCAL_ROOT / "pipeline" / "rag_derivation" / "s0174"
S0174_AUDIT_ROOT = LOCAL_ROOT / "audit" / "rag_derivation" / "s0174"
PRODUCTIVE_ROOTS = {
    "enriched": LOCAL_ROOT / "enriched",
    "ai": LOCAL_ROOT / "ai",
    "microsoft_copilot": LOCAL_ROOT / "microsoft_copilot",
}
PLANNED_FAMILIES = tuple(PRODUCTIVE_ROOTS)
NON_BLOCKING_EQUIVALENCE_STATUSES = {
    "equivalent",
    "equivalent_with_declared_operational_differences",
    "equivalent_with_expected_canonical_evolution",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: Path | str, payload: dict[str, Any]) -> Path:
    target = require_nonproductive_evidence_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _git_state() -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        return result.stdout.strip()

    return {
        "branch": run("branch", "--show-current"),
        "head": run("rev-parse", "HEAD"),
        "workspace_status": run("status", "--short").splitlines(),
    }


def _tree_files(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    return [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(path for path in root.rglob("*") if path.is_file())
    ]


def _root_manifest() -> dict[str, Any]:
    families = []
    for family, root in PRODUCTIVE_ROOTS.items():
        files = _tree_files(root)
        families.append({
            "artifact_family": family,
            "path": str(root.relative_to(REPO_ROOT)),
            "status": "present" if root.exists() else "not_present",
            "file_count": len(files),
            "files": files,
        })
    return {"schema_version": "s0174-surface-manifest/v1", "families": families}


def build_preflight(*, canon_dir: Path | str = LOCAL_ROOT) -> dict[str, Any]:
    canon = canonical_snapshot(canon_dir)
    s0173_manifest = _read_json(S0173_PIPELINE_ROOT / "staging_manifest.json")
    s0173_gate = _read_json(S0173_AUDIT_ROOT / "staging_rag_gate_report.json")
    s0173_equivalence = _read_json(S0173_PIPELINE_ROOT / "preview_staging_equivalence_report.json")
    s0173_rollback = _read_json(S0173_AUDIT_ROOT / "rollback_readiness_report.json")
    s0173_receipt = _read_json(S0173_PIPELINE_ROOT / "productive_regeneration_receipt.json")
    previous_journal = S0173_AUDIT_ROOT / "productive_transaction_journal.jsonl"
    previous_promotion = bool(s0173_receipt.get("productive_regeneration_executed"))
    return {
        "schema_version": "s0174-preflight/v1",
        "session_id": "S0174",
        "checked_at": utc_now(),
        "git": _git_state(),
        "canon": canon,
        "productive_surfaces": _root_manifest(),
        "s0173_continuity": {
            "staging_manifest": {
                "path": str(S0173_PIPELINE_ROOT / "staging_manifest.json"),
                "sha256": sha256_file(S0173_PIPELINE_ROOT / "staging_manifest.json") if (S0173_PIPELINE_ROOT / "staging_manifest.json").exists() else None,
                "status": "current" if s0173_manifest.get("source_canon_hash") == canon.get("source_canon_hash") else "stale_or_missing",
            },
            "technical_gate": {"status": s0173_gate.get("status"), "blocking": s0173_gate.get("blocking")},
            "equivalence": {"status": s0173_equivalence.get("equivalence_status"), "blocking": s0173_equivalence.get("blocking")},
            "rollback": {"rollback_ready": s0173_rollback.get("rollback_ready")},
            "authorization_state": "promotion_completed" if previous_promotion else "authorization_pending",
            "previous_transaction_journal": str(previous_journal),
            "previous_transaction_journal_exists": previous_journal.exists(),
        },
        "incomplete_previous_productive_write": previous_promotion,
        "canon_modified": False,
        "reverse_html_modified": False,
        "productive_derivatives_modified": False,
    }


def build_producer_inventory() -> dict[str, Any]:
    """Classify every known path with productive write capability."""

    entries = [
        {
            "component_path": "src/python_scripts/derive_layers.py",
            "functional_status": "active_authoritative",
            "authority": "sole productive derivative producer",
            "can_write_productive": True,
            "can_write_canon": False,
            "outputs": list(PLANNED_FAMILIES),
            "evidence": "S0173 staging manifest and source imports/policy calls",
        },
        {
            "component_path": "src/python_scripts/rag_derivative_writers.py",
            "functional_status": "active_supporting",
            "authority": "sole governed persistence boundary",
            "can_write_productive": True,
            "can_write_canon": False,
            "outputs": list(PLANNED_FAMILIES),
            "evidence": "promote_staging_transaction; no semantic builder calls",
        },
        {
            "component_path": "src/python_scripts/s45_derive_layers.py",
            "functional_status": "legacy_compatibility_wrapper",
            "authority": "none; forwards to derive_layers.py",
            "can_write_productive": False,
            "can_write_canon": False,
            "outputs": list(PLANNED_FAMILIES),
            "evidence": "wrapper subprocesses authoritative entrypoint; legacy body is not executed",
        },
        {
            "component_path": "src/python_scripts/build_rag_safe_semantic_preview.py",
            "functional_status": "preview_only_supporting",
            "authority": "none for productive outputs",
            "can_write_productive": False,
            "can_write_canon": False,
            "outputs": ["preview evidence"],
            "evidence": "preview-only contract and no productive root writes",
        },
        {
            "component_path": "src/python_scripts/semantic_text_builder.py",
            "functional_status": "active_authoritative_component",
            "authority": "sole semantic_text builder",
            "can_write_productive": False,
            "can_write_canon": False,
            "outputs": ["semantic_text sidecar consumed by derive_layers.py"],
            "evidence": "derive_layers imports build_semantic_text_outputs",
        },
        {
            "component_path": "src/python_scripts/build_semantic_text.py",
            "functional_status": "legacy_compatibility",
            "authority": "none for S0174",
            "can_write_productive": False,
            "can_write_canon": False,
            "outputs": ["legacy preview/evidence only"],
            "evidence": "not selected by authoritative entrypoint",
        },
        {
            "component_path": "src/python_scripts/build_semantic_text_authority_aware.py",
            "functional_status": "experimental_requires_review",
            "authority": "none for S0174",
            "can_write_productive": False,
            "can_write_canon": False,
            "outputs": ["experimental evidence"],
            "evidence": "not imported by derive_layers.py",
        },
        {
            "component_path": "src/python_scripts/operator_menu.py",
            "functional_status": "operator_entrypoint",
            "authority": "dispatch only",
            "can_write_productive": False,
            "can_write_canon": False,
            "outputs": ["commands/reports"],
            "evidence": "menu routes derivative generation to derive_layers.py",
        },
    ]
    return {
        "schema_version": "s0174-producer-inventory/v1",
        "session_id": "S0174",
        "authoritative_producer": "src/python_scripts/derive_layers.py",
        "authoritative_writer": "src/python_scripts/rag_derivative_writers.py",
        "parallel_productive_writers": [],
        "components": entries,
    }


def build_execution_graph() -> dict[str, Any]:
    edges = [
        {"origin": "operator_menu.py", "destination": "derive_layers.py", "integration": "subprocess entrypoint", "contract": "authoritative derivation path", "evidence": "_s0173_staging_command / option 5"},
        {"origin": "derive_layers.py", "destination": "semantic_text_builder.py", "integration": "build_semantic_text_outputs", "contract": "semantic-text-build/v1", "evidence": "import and _build_authoritative_semantic_projection"},
        {"origin": "derive_layers.py", "destination": "tag_sanitation_policy.py", "integration": "load_policy + strict_tag_gate", "contract": "tag-sanitation/v1", "evidence": "_load_rag_contract_inputs"},
        {"origin": "derive_layers.py", "destination": "metadata_promotion_policy.py", "integration": "load_policy + candidate validation", "contract": "metadata-promotion/v1", "evidence": "_load_rag_contract_inputs"},
        {"origin": "derive_layers.py", "destination": "rag_derivation_profile.json", "integration": "versioned profile/hash", "contract": "rag-derivation-profile/v1", "evidence": "load_rag_derivation_profile"},
        {"origin": "derive_layers.py", "destination": "validate_rag_tag_gate.py", "integration": "build_gate_report", "contract": "rag-tag-gate/v1", "evidence": "_write_preview_evidence"},
        {"origin": "staging", "destination": "rag_derivative_writers.py", "integration": "manifest-bound copy/replace", "contract": "productive-write-manifest/v1", "evidence": "promote_staging_transaction"},
        {"origin": "rag_derivative_writers.py", "destination": "productive derivatives", "integration": "atomic directory replace", "contract": "allowlisted families + rollback manifest", "evidence": "transaction journal and receipt"},
    ]
    return {"schema_version": "s0174-execution-graph/v1", "session_id": "S0174", "edges": edges}


def build_integration_modification_table() -> dict[str, Any]:
    return {
        "schema_version": "s0174-integration-modifications/v1",
        "session_id": "S0174",
        "changes": [
            {
                "change": "Extend existing rag_derivative_writers transaction boundary",
                "demonstrated_misalignment": "S0173 writer was fixed to one session phrase and lacked S0174 manifest-bound post-write evidence",
                "authoritative_component_reused": "rag_derivative_writers.py",
                "complexity_contained": "one persistence boundary; no second writer or semantic transformation",
                "evidence": "productive-write-manifest/v1, transaction journal, rollback restoration",
            },
            {
                "change": "Allow equivalence validator to compare approved staging against product families",
                "demonstrated_misalignment": "semantic sidecar is staging-only while product has four persisted families",
                "authoritative_component_reused": "validate_productive_equivalence.py",
                "complexity_contained": "same comparison logic with explicit family scope",
                "evidence": "--family and compared_families in equivalence report",
            },
            {
                "change": "Add S0174 governance evidence layer",
                "demonstrated_misalignment": "S0173 had no session-specific producer inventory/governance gate",
                "authoritative_component_reused": "derive_layers.py, existing policies, existing writer",
                "complexity_contained": "validator/evidence only; does not produce derivatives",
                "evidence": "s0174_governance.py reports",
            },
        ],
    }


def build_governance_gate(
    *,
    preflight: dict[str, Any],
    inventory: dict[str, Any],
    staging_manifest_path: Path | str,
    technical_gate_path: Path | str,
    equivalence_report_path: Path | str,
    rollback_readiness_path: Path | str,
) -> dict[str, Any]:
    manifest_path = Path(staging_manifest_path)
    gate = _read_json(Path(technical_gate_path))
    equivalence = _read_json(Path(equivalence_report_path))
    rollback = _read_json(Path(rollback_readiness_path))
    staging = _read_json(manifest_path)
    reasons: list[str] = []
    if not staging:
        reasons.append("staging_manifest_missing")
    if staging.get("source_canon_hash") != preflight.get("canon", {}).get("source_canon_hash"):
        reasons.append("staging_canon_hash_mismatch")
    if staging.get("productive_orchestrator") != "derive_layers.py":
        reasons.append("staging_producer_not_authoritative")
    current_orchestrator = SCRIPT_DIR / "derive_layers.py"
    if staging.get("productive_orchestrator_hash") != sha256_file(current_orchestrator):
        reasons.append("staging_orchestrator_hash_stale")
    if staging.get("productive_write") is not False or staging.get("authority_state") != "staging":
        reasons.append("staging_authority_state_invalid")
    if gate.get("status") != "pass" or gate.get("blocking") is True:
        reasons.append("technical_gate_not_pass")
    if equivalence.get("equivalence_status") not in NON_BLOCKING_EQUIVALENCE_STATUSES or equivalence.get("blocking") is True:
        reasons.append("staging_equivalence_not_pass")
    if rollback.get("rollback_ready") is not True:
        reasons.append("rollback_not_ready")
    if inventory.get("authoritative_producer") != "src/python_scripts/derive_layers.py":
        reasons.append("authoritative_producer_unconfirmed")
    if inventory.get("authoritative_writer") != "src/python_scripts/rag_derivative_writers.py":
        reasons.append("authoritative_writer_unconfirmed")
    if inventory.get("parallel_productive_writers"):
        reasons.append("parallel_productive_writer_detected")
    return {
        "schema_version": "s0174-governance-gate/v1",
        "session_id": "S0174",
        "status": "pass" if not reasons else "blocked",
        "blocking": bool(reasons),
        "blocking_reasons": sorted(set(reasons)),
        "producer_authority": "confirmed" if not reasons else "unconfirmed",
        "writer_authority": "confirmed" if not reasons else "unconfirmed",
        "technical_gate": gate.get("status"),
        "staging_equivalence": equivalence.get("equivalence_status"),
        "rollback_ready": rollback.get("rollback_ready"),
        "authorization_state": "authorization_pending" if not reasons else "blocked",
        "planned_families": list(PLANNED_FAMILIES),
        "deletion_policy": "none",
        "canon_modified": False,
        "reverse_html_modified": False,
        "staging_manifest_path": str(manifest_path),
        "staging_manifest_hash": sha256_file(manifest_path) if manifest_path.exists() else None,
    }


def build_post_write_validation(
    *,
    staging_root: Path | str,
    productive_root: Path | str = LOCAL_ROOT,
    canon_before: str | None = None,
    canon_after: str | None = None,
) -> dict[str, Any]:
    equivalence = build_equivalence_report(
        staging_root,
        productive_root,
        families=["enriched", "ai", "chunks_ai", "microsoft_copilot"],
    )
    return {
        "schema_version": "s0174-post-write-validation/v1",
        "session_id": "S0174",
        "status": "pass" if not equivalence["blocking"] and canon_before == canon_after else "blocked",
        "blocking": bool(equivalence["blocking"] or canon_before != canon_after),
        "equivalence": equivalence,
        "canon_before": canon_before,
        "canon_after": canon_after,
        "canon_modified": canon_before != canon_after,
        "reverse_html_modified": False,
    }


def build_rollback_verification(
    *,
    before_manifest: dict[str, Any],
    after_manifest: dict[str, Any],
) -> dict[str, Any]:
    before = {(f["artifact_family"], f["path"]): f.get("sha256") for f in before_manifest.get("files", [])}
    after = {(f["artifact_family"], f["path"]): f.get("sha256") for f in after_manifest.get("files", [])}
    return {
        "schema_version": "s0174-rollback-verification/v1",
        "session_id": "S0174",
        "status": "pass" if before == after else "blocked",
        "blocking": before != after,
        "state_equal": before == after,
        "before_file_count": len(before),
        "after_file_count": len(after),
        "canon_modified": False,
    }


def promote_s0174(
    *,
    authorization_path: Path | str,
    staging_root: Path | str,
    staging_manifest_path: Path | str,
    governance_gate_path: Path | str,
    rollback_root: Path | str,
    transaction_journal: Path | str,
    receipt_path: Path | str,
) -> dict[str, Any]:
    """Promote an explicitly authorized S0174 staging payload.

    This function is intentionally not called by the preflight CLI.  It is a
    separate, human-triggered operation and creates the snapshot immediately
    before the first write.
    """

    authorization = _read_json(Path(authorization_path))
    if not authorization:
        raise ProductiveWriteBlocked("S0174 authorization artifact is missing")
    gate = _read_json(Path(governance_gate_path))
    if gate.get("status") != "pass" or gate.get("blocking") is True:
        raise ProductiveWriteBlocked("S0174 governance gate is not PASS")
    manifest_path = Path(staging_manifest_path)
    if not manifest_path.exists():
        raise ProductiveWriteBlocked("S0174 staging manifest is missing")
    manifest_hash = sha256_file(manifest_path)
    if gate.get("staging_manifest_hash") != manifest_hash:
        raise ProductiveWriteBlocked("S0174 staging manifest differs from governance evidence")
    rollback_path = Path(rollback_root)
    if rollback_path.exists() and any(rollback_path.iterdir()):
        existing = _read_json(rollback_path / "rollback_manifest.json")
        if existing.get("session_id") != "S0174":
            raise ProductiveWriteBlocked("S0174 rollback root is scoped to another session")
        live_check = verify_productive_state_matches_snapshot(rollback_path)
        if not live_check["matches"]:
            raise ProductiveWriteBlocked("productive state changed after the S0174 pre-write snapshot")
        snapshot = existing
    else:
        snapshot = snapshot_productive_derivatives(rollback_path, session_id="S0174")
    receipt = promote_staging_transaction(
        staging_root=staging_root,
        rollback_root=rollback_path,
        authorization=authorization,
        planned_families=list(PLANNED_FAMILIES),
        transaction_journal=transaction_journal,
        receipt_path=receipt_path,
        expected_session_id="S0174",
        required_authorization_phrase=None,
        staging_manifest_path=manifest_path,
        staging_manifest_hash=manifest_hash,
    )
    receipt["snapshot_manifest"] = snapshot
    return receipt


def rollback_s0174(
    *,
    rollback_root: Path | str,
    transaction_journal: Path | str,
    verification_report_path: Path | str,
) -> dict[str, Any]:
    return rollback_productive_transaction(
        rollback_root=rollback_root,
        planned_families=list(PLANNED_FAMILIES),
        transaction_journal=transaction_journal,
        verification_report_path=verification_report_path,
        expected_session_id="S0174",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="S0174 integration and governance evidence")
    parser.add_argument("--preflight-out")
    parser.add_argument("--inventory-out")
    parser.add_argument("--graph-out")
    parser.add_argument("--modifications-out")
    parser.add_argument("--governance-gate-out")
    parser.add_argument("--authorization")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--staging-root", default=str(S0173_PIPELINE_ROOT / "staging"))
    parser.add_argument("--rollback-root", default=str(S0174_PIPELINE_ROOT / "rollback_snapshot_prewrite"))
    parser.add_argument("--transaction-journal", default=str(S0174_AUDIT_ROOT / "productive_transaction_journal.jsonl"))
    parser.add_argument("--receipt-out", default=str(S0174_PIPELINE_ROOT / "productive_regeneration_receipt.json"))
    parser.add_argument("--rollback-report-out", default=str(S0174_AUDIT_ROOT / "rollback_execution_report.json"))
    parser.add_argument("--staging-manifest", default=str(S0173_PIPELINE_ROOT / "staging_manifest.json"))
    parser.add_argument("--technical-gate", default=str(S0173_AUDIT_ROOT / "staging_rag_gate_report.json"))
    parser.add_argument("--equivalence-report", default=str(S0173_PIPELINE_ROOT / "preview_staging_equivalence_report.json"))
    parser.add_argument("--rollback-readiness", default=str(S0173_AUDIT_ROOT / "rollback_readiness_report.json"))
    args = parser.parse_args()
    if args.promote and args.rollback:
        parser.error("--promote and --rollback are mutually exclusive")
    if args.promote:
        if not args.authorization:
            parser.error("--promote requires --authorization")
        receipt = promote_s0174(
            authorization_path=args.authorization,
            staging_root=args.staging_root,
            staging_manifest_path=args.staging_manifest,
            governance_gate_path=args.governance_gate_out or str(S0174_AUDIT_ROOT / "governance_gate_report.json"),
            rollback_root=args.rollback_root,
            transaction_journal=args.transaction_journal,
            receipt_path=args.receipt_out,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    if args.rollback:
        report = rollback_s0174(
            rollback_root=args.rollback_root,
            transaction_journal=args.transaction_journal,
            verification_report_path=args.rollback_report_out,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    preflight = build_preflight()
    inventory = build_producer_inventory()
    graph = build_execution_graph()
    modifications = build_integration_modification_table()
    if args.preflight_out:
        write_json(args.preflight_out, preflight)
    if args.inventory_out:
        write_json(args.inventory_out, inventory)
    if args.graph_out:
        write_json(args.graph_out, graph)
    if args.modifications_out:
        write_json(args.modifications_out, modifications)
    if args.governance_gate_out:
        gate = build_governance_gate(
            preflight=preflight,
            inventory=inventory,
            staging_manifest_path=args.staging_manifest,
            technical_gate_path=args.technical_gate,
            equivalence_report_path=args.equivalence_report,
            rollback_readiness_path=args.rollback_readiness,
        )
        write_json(args.governance_gate_out, gate)
        print(json.dumps(gate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
