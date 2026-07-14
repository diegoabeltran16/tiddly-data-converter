#!/usr/bin/env python3
"""Read-only characterization and manifest utilities for S0172.

The only writes performed by this supporting module target explicit audit or
pipeline evidence paths supplied by the caller.  It never writes a productive
derivative family.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_derivation_profile import stable_json
from rag_derivation_plan import canonical_snapshot
from rag_derivative_writers import (
    require_nonproductive_evidence_target,
    snapshot_productive_derivatives,
    verify_rollback_snapshot,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
PRODUCTIVE_FAMILIES = {
    "enriched": "data/out/local/enriched",
    "ai": "data/out/local/ai",
    "microsoft_copilot": "data/out/local/microsoft_copilot",
    "reverse_html": "data/out/local/reverse_html",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def productive_derivatives_manifest(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    families: list[dict[str, Any]] = []
    for family, relative in PRODUCTIVE_FAMILIES.items():
        root = repo_root / relative
        if not root.exists():
            families.append({"artifact_family": family, "path": relative, "status": "not_present"})
            continue
        family_files = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda item: str(item))
        families.append(
            {
                "artifact_family": family,
                "path": relative,
                "status": "present",
                "file_count": len(family_files),
            }
        )
        for path in family_files:
            stat = path.stat()
            files.append(
                {
                    "path": repo_relative(path),
                    "artifact_family": family,
                    "size_bytes": stat.st_size,
                    "line_count": line_count(path),
                    "sha256": sha256_file(path),
                    "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "producer_expected": "derive_layers.py",
                }
            )
    return {
        "schema_version": "productive-derivatives-manifest/v1",
        "captured_at": utc_now(),
        "producer_expected": "derive_layers.py",
        "families": families,
        "files": files,
        "canon_modified": False,
        "productive_derivatives_modified": False,
    }


def write_json(path: Path | str, payload: dict[str, Any]) -> Path:
    target = require_nonproductive_evidence_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")
    return target


def manifest_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = {entry["path"]: entry for entry in before.get("files", [])}
    new = {entry["path"]: entry for entry in after.get("files", [])}
    added = sorted(path for path in new if path not in old)
    removed = sorted(path for path in old if path not in new)
    changed = sorted(
        path
        for path in old.keys() & new.keys()
        if any(old[path].get(key) != new[path].get(key) for key in ("sha256", "size_bytes", "line_count"))
    )
    return {
        "schema_version": "productive-derivatives-diff-report/v1",
        "productive_derivatives_diff": "empty" if not (added or removed or changed) else "non_empty",
        "added": added,
        "removed": removed,
        "changed": changed,
        "canon_modified": False,
        "productive_derivatives_modified": bool(added or removed or changed),
    }


def _input_state(path: Path, expected_hash: str | None = None) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "status": "missing"}
    digest = sha256_file(path)
    status = "current" if expected_hash is None or digest == expected_hash else "stale"
    return {"path": str(path), "status": status, "sha256": digest}


def build_s0173_preflight(
    *,
    s0172_plan_path: Path | str,
    s0172_manifest_path: Path | str,
    s0172_gate_path: Path | str,
    s0172_profile_path: Path | str,
    tag_policy_path: Path | str,
    metadata_policy_path: Path | str,
    metadata_candidates_path: Path | str,
    tag_inventory_path: Path | str,
    semantic_type_policy_path: Path | str,
    semantic_builder_path: Path | str,
    productive_orchestrator_path: Path | str,
    canon_dir: Path | str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Revalidate S0172 inputs and classify whether its preview may be reused."""

    plan_path = Path(s0172_plan_path)
    manifest_path = Path(s0172_manifest_path)
    gate_path = Path(s0172_gate_path)
    profile_path = Path(s0172_profile_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    gate = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.exists() else {}
    canon = canonical_snapshot(canon_dir)
    artifacts = {
        "s0172_plan": _input_state(plan_path),
        "s0172_preview_manifest": _input_state(manifest_path, plan.get("preview_manifest_hash")),
        "s0172_gate": _input_state(gate_path, plan.get("gate_report_hash")),
        "profile": _input_state(profile_path, plan.get("derivation_profile_hash")),
        "tag_policy": _input_state(Path(tag_policy_path), plan.get("tag_policy_hash")),
        "metadata_policy": _input_state(Path(metadata_policy_path), plan.get("metadata_policy_hash")),
        "candidates": _input_state(Path(metadata_candidates_path), plan.get("metadata_candidates_hash")),
        "inventory": _input_state(Path(tag_inventory_path), plan.get("tag_inventory_hash")),
        "semantic_builder": _input_state(Path(semantic_builder_path), plan.get("semantic_builder_hash")),
        "type_policy": _input_state(Path(semantic_type_policy_path), plan.get("semantic_type_policy_hash")),
        "productive_orchestrator": _input_state(Path(productive_orchestrator_path)),
    }
    reasons: list[str] = []
    if not plan.get("productive_orchestrator_hash"):
        reasons.append("s0172_plan_missing_productive_orchestrator_hash")
    if not manifest.get("productive_orchestrator_hash"):
        reasons.append("s0172_manifest_missing_productive_orchestrator_hash")
    if not manifest.get("schema_version") == "rag-preview-manifest/v1":
        reasons.append("s0172_preview_manifest_schema_invalid")
    if gate.get("status") != "pass" or gate.get("blocking") is True:
        reasons.append("s0172_gate_not_current_pass")
    if plan.get("status") != "validated_preview":
        reasons.append("s0172_plan_not_validated_preview")
    if plan.get("productive_write_allowed") is not False:
        reasons.append("s0172_plan_authority_state_invalid")
    if plan.get("source_canon_hash") != canon.get("source_canon_hash"):
        reasons.append("canon_hash_changed_since_s0172")
    if plan.get("source_canon_version_id") != canon.get("source_canon_version_id"):
        reasons.append("canon_version_changed_since_s0172")
    for key, value in artifacts.items():
        if value.get("status") in {"missing", "stale", "invalid"} and key != "productive_orchestrator":
            if value.get("status") == "missing":
                reasons.append(f"missing_{key}")
            elif value.get("status") == "stale":
                reasons.append(f"stale_{key}")
    # The historical gate did not include a product-equivalence contract, so
    # it cannot authorize reuse for S0173 even when all raw inputs match.
    reasons.append("s0172_productive_equivalence_contract_missing")
    revalidation = {
        "schema_version": "s0172-evidence-revalidation/v1",
        "session_id": "S0173",
        "source_session": "S0172",
        "evidence_status": "stale" if reasons else "current",
        "may_be_reused": False if reasons else True,
        "reasons": sorted(set(reasons)),
        "canon": canon,
        "artifacts": artifacts,
        "historical_plan_productive_write_allowed": plan.get("productive_write_allowed"),
        "historical_gate_status": gate.get("status"),
    }
    preflight = {
        "schema_version": "s0173-current-preflight/v1",
        "session_id": "S0173",
        "checked_at": utc_now(),
        "status": "current_preflight_pass" if not reasons else "current_preflight_stale",
        "classification": "current" if not reasons else "stale",
        "canon": canon,
        "inputs": artifacts,
        "s0172_evidence_revalidation": revalidation,
        "productive_write_allowed": False,
        "authorization_required": True,
        "rollback_ready": False,
        "blocking_reasons": sorted(set(reasons)),
    }
    return preflight, revalidation


def _imports(tree: ast.AST) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return sorted(set(filter(None, imports)))


def characterize_derive_layers(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(target))
    functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    imports = _imports(tree)
    cli_flags = sorted(set(__import__("re").findall(r'"(--[a-z0-9-]+)"', source)))
    writers = [name for name in functions if name.startswith("write_") or "cleanup" in name]
    public = [name for name in functions if not name.startswith("_")]
    source_tag_mentions = source.count("source_tags")
    return {
        "schema_version": "derive-layers-characterization/v1",
        "path": repo_relative(target),
        "line_count": len(source.splitlines()),
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "public_functions": public,
        "internal_functions": [name for name in functions if name.startswith("_")],
        "imports": imports,
        "writers": writers,
        "cli": {"flags": cli_flags, "has_mode": "--mode" in cli_flags, "has_dry_run": "--dry-run" in cli_flags},
        "answers": {
            "constructs_semantic_text_locally": (
                "compute_semantic_text" in source
                or ("build_enriched_record" in source and "build_ai_record" in source and "semantic_text_builder" not in source)
            ),
            "consumes_source_tags_directly": source_tag_mentions > 0,
            "builds_retrieval_hints_directly": (
                "build_retrieval_hints" in source
                or ("build_ai_record" in source and "semantic_text_builder" not in source)
            ),
            "builds_embedding_metadata_directly": "embedding_metadata" in source,
            "consumes_tag_sanitation_v1": "tag_sanitation_policy" in source,
            "consumes_metadata_promotion_v1": "metadata_promotion_policy" in source,
            "delegates_semantic_builder": "semantic_text_builder" in source,
            "runs_rag_gate": "validate_rag_tag_gate" in source,
            "requires_authoritative_semantic_projection": "authoritative semantic projection" in source,
            "writers_protected_by_preflight": "require_productive_write_permission" in source,
            "consumes_versioned_derivation_profile": "load_rag_derivation_profile" in source,
            "consumes_preview_to_production_plan": "evaluate_productive_write_preflight" in source,
            "supports_isolated_preview_equivalence": (
                "--mode" in cli_flags and "--out-dir" in cli_flags and "build_semantic_text_outputs" in source
            ),
            "uses_dynamic_relation_preview_inputs": "dry_run_ready_glob=\"\"" not in source,
            "isolated_output_root_supported": "--out-dir" in cli_flags,
            "real_dry_run_supported": "--dry-run" in cli_flags,
            "writes_productive_paths_by_default": not (
                "--mode" in cli_flags and "require_productive_write_permission" in source
            ),
            "has_rollback": False,
        },
        "known_wrappers": [
            "src/python_scripts/s45_derive_layers.py",
            "src/python_scripts/operator_menu.py",
            "src/python_scripts/audit_normative_projection.py",
        ],
        "associated_tests": sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "tests").glob("test_*derive*py")
        ),
    }


def characterization_markdown(payload: dict[str, Any]) -> str:
    answers = payload["answers"]
    lines = [
        "# Caracterización de derive_layers.py",
        "",
        f"- Ruta: `{payload['path']}`",
        f"- Líneas medidas: `{payload['line_count']}`",
        f"- CLI: `{', '.join(payload['cli']['flags'])}`",
        f"- Funciones públicas: `{', '.join(payload['public_functions'])}`",
        f"- Writers: `{', '.join(payload['writers'])}`",
        "",
        "## Respuestas",
        "",
    ]
    for key, value in answers.items():
        lines.append(f"- {key}: `{str(value).lower()}`")
    lines.extend(["", "## Imports", "", *[f"- `{item}`" for item in payload["imports"]]])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="S0172 read-only preflight evidence utilities.")
    parser.add_argument("--productive-manifest")
    parser.add_argument("--characterize")
    parser.add_argument("--characterization-json")
    parser.add_argument("--characterization-md")
    parser.add_argument("--before-manifest")
    parser.add_argument("--after-manifest")
    parser.add_argument("--diff-report")
    parser.add_argument("--s0173-preflight", action="store_true")
    parser.add_argument("--s0172-plan")
    parser.add_argument("--s0172-preview-manifest")
    parser.add_argument("--s0172-gate")
    parser.add_argument("--s0172-profile")
    parser.add_argument("--tag-policy")
    parser.add_argument("--metadata-policy")
    parser.add_argument("--metadata-candidates")
    parser.add_argument("--tag-inventory")
    parser.add_argument("--semantic-type-policy")
    parser.add_argument("--semantic-builder")
    parser.add_argument("--productive-orchestrator")
    parser.add_argument("--canon-dir")
    parser.add_argument("--current-preflight-out")
    parser.add_argument("--revalidation-out")
    parser.add_argument("--rollback-snapshot")
    parser.add_argument("--rollback-readiness-out")
    parser.add_argument("--snapshot-session-id", default="S0173")
    args = parser.parse_args()
    if args.s0173_preflight:
        required = {
            "--s0172-plan": args.s0172_plan,
            "--s0172-preview-manifest": args.s0172_preview_manifest,
            "--s0172-gate": args.s0172_gate,
            "--s0172-profile": args.s0172_profile,
            "--tag-policy": args.tag_policy,
            "--metadata-policy": args.metadata_policy,
            "--metadata-candidates": args.metadata_candidates,
            "--tag-inventory": args.tag_inventory,
            "--semantic-type-policy": args.semantic_type_policy,
            "--semantic-builder": args.semantic_builder,
            "--productive-orchestrator": args.productive_orchestrator,
            "--canon-dir": args.canon_dir,
            "--current-preflight-out": args.current_preflight_out,
            "--revalidation-out": args.revalidation_out,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error("--s0173-preflight requires " + ", ".join(missing))
        preflight, revalidation = build_s0173_preflight(
            s0172_plan_path=args.s0172_plan,
            s0172_manifest_path=args.s0172_preview_manifest,
            s0172_gate_path=args.s0172_gate,
            s0172_profile_path=args.s0172_profile,
            tag_policy_path=args.tag_policy,
            metadata_policy_path=args.metadata_policy,
            metadata_candidates_path=args.metadata_candidates,
            tag_inventory_path=args.tag_inventory,
            semantic_type_policy_path=args.semantic_type_policy,
            semantic_builder_path=args.semantic_builder,
            productive_orchestrator_path=args.productive_orchestrator,
            canon_dir=args.canon_dir,
        )
        write_json(args.current_preflight_out, preflight)
        write_json(args.revalidation_out, revalidation)
        print(stable_json(preflight, indent=2))
        return 0
    if args.rollback_snapshot:
        if not args.rollback_readiness_out:
            parser.error("--rollback-snapshot requires --rollback-readiness-out")
        manifest = snapshot_productive_derivatives(args.rollback_snapshot, session_id=args.snapshot_session_id)
        readiness = {
            "schema_version": "rollback-readiness-report/v1",
            "snapshot_root": str(Path(args.rollback_snapshot).resolve()),
            "rollback_ready": verify_rollback_snapshot(args.rollback_snapshot, manifest)["restored_manifest_matches"],
            "manifest": manifest,
            "fixture_verification": "not_applicable; persistent snapshot hashes verified",
        }
        write_json(args.rollback_readiness_out, readiness)
        print(stable_json(readiness, indent=2))
        return 0
    if args.productive_manifest:
        write_json(args.productive_manifest, productive_derivatives_manifest())
    if args.characterize:
        payload = characterize_derive_layers(args.characterize)
        if args.characterization_json:
            write_json(args.characterization_json, payload)
        if args.characterization_md:
            markdown_target = require_nonproductive_evidence_target(args.characterization_md)
            markdown_target.parent.mkdir(parents=True, exist_ok=True)
            markdown_target.write_text(characterization_markdown(payload), encoding="utf-8")
    if args.diff_report:
        if not args.before_manifest or not args.after_manifest:
            parser.error("--diff-report requires --before-manifest and --after-manifest")
        before = json.loads(Path(args.before_manifest).read_text(encoding="utf-8"))
        after = json.loads(Path(args.after_manifest).read_text(encoding="utf-8"))
        write_json(args.diff_report, manifest_diff(before, after))
    if not args.productive_manifest and not args.characterize and not args.diff_report and not args.s0173_preflight:
        parser.error("one of --productive-manifest, --characterize, or --diff-report is required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
