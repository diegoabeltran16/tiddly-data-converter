#!/usr/bin/env python3
"""Build S0147 dry-run repo metadata patch preview.

Consumes the S0146 repo-artifact classification matrix and emits a reversible
metadata preview plus human-review batches. This module never writes canon
shards and never records human approval.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

DEFAULT_CLASSIFICATION = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "repo_artifacts"
    / "s0146"
    / "s0146_repo_artifact_classification.jsonl"
)
DEFAULT_METADATA_CONTRACT = (
    REPO_ROOT
    / "data"
    / "out"
    / "local"
    / "pipeline"
    / "repo_artifacts"
    / "s0146"
    / "s0146_repo_artifact_metadata_contract.md"
)
DEFAULT_CANON_GLOB = str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl")
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_review" / "s0147"

PATCH_REVIEW_COLUMNS = [
    "op_id",
    "batch_id",
    "target_id",
    "target_title",
    "patch_lane",
    "current_artifact_family",
    "fields_preview",
    "risk_level",
    "requires_human_review",
    "human_approved",
    "applied_to_canon",
    "dry_run",
    "reason",
]

LANE_BATCHES = {
    "lane_a_current_verified": "batch_current_verified",
    "lane_b_historical_review": "batch_historical_review",
    "lane_c_generated_derivative": "batch_generated_derivative",
    "lane_d_embedded_code": "batch_embedded_code",
    "lane_e_narrative_reference": "batch_narrative_reference",
    "lane_f_excluded_review_required": "batch_excluded_review_required",
}

BATCH_LABELS = {
    "batch_current_verified": "Carril A - codigo vigente verificado",
    "batch_historical_review": "Carril B - historico, divergente, missing o moved",
    "batch_generated_derivative": "Carril C - outputs generados",
    "batch_embedded_code": "Carril D - bloques de codigo embebidos",
    "batch_narrative_reference": "Carril E - sesiones o diagnosticos narrativos",
    "batch_excluded_review_required": "Carril F - excluidos por revision/riesgo",
}

TECHNICAL_CANON_FAMILY_VALUES = {"", "unknown", "tiddler_tecnico"}
HISTORICAL_CATEGORIES = {
    "repo_snapshot_drifted",
    "repo_snapshot_missing",
    "moved_candidate",
    "deleted_historical_candidate",
}
EMBEDDED_CATEGORIES = {"embedded_code_block", "documentation_with_code_example"}
NARRATIVE_CATEGORIES = {"session_or_diagnostic_narrative", "narrative_code_reference"}


def stable_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tree_sha256(glob_pattern: str) -> str:
    digest = hashlib.sha256()
    for path_str in sorted(glob.glob(glob_pattern)):
        path = Path(path_str)
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            item = json.loads(raw)
            if isinstance(item, dict):
                item["_source_line"] = line_no
                rows.append(item)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(stable_json(row) + "\n" for row in rows), encoding="utf-8")


def write_csv(path: Path, operations: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PATCH_REVIEW_COLUMNS)
        writer.writeheader()
        for op in operations:
            writer.writerow(
                {
                    "op_id": op["op_id"],
                    "batch_id": op["batch_id"],
                    "target_id": op["target_id"],
                    "target_title": op["target_title"],
                    "patch_lane": op["patch_lane"],
                    "current_artifact_family": op["current_artifact_family"],
                    "fields_preview": stable_json(op["fields_preview"]),
                    "risk_level": op["source_risk_level"],
                    "requires_human_review": op["requires_human_review"],
                    "human_approved": op["human_approved"],
                    "applied_to_canon": op["applied_to_canon"],
                    "dry_run": op["dry_run"],
                    "reason": op["reason"],
                }
            )


def slugify(text: str) -> str:
    value = text.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:120]


def current_family(record: dict[str, Any] | None) -> str:
    if not record:
        return "unknown"
    source_fields = record.get("source_fields") if isinstance(record.get("source_fields"), dict) else {}
    raw = source_fields.get("artifact_family") or record.get("artifact_family") or record.get("family") or ""
    value = str(raw).strip()
    return value or "unknown"


def load_canon_index(canon_glob: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for path_str in sorted(glob.glob(canon_glob)):
        for row in read_jsonl(Path(path_str)):
            row_id = str(row.get("id") or "")
            if row_id:
                index[row_id] = row
    return index


def lane_for(row: dict[str, Any]) -> str:
    category = str(row.get("diagnostic_category") or "")
    authority = str(row.get("candidate_authority_level") or "")
    is_current = str(row.get("candidate_is_current_repo_artifact") or "").lower()
    risk = str(row.get("risk_level") or "")
    confidence = str(row.get("confidence") or "")
    if category == "review_required" or risk == "critical" or confidence == "requires_human_review":
        return "lane_f_excluded_review_required"
    if (
        category == "repo_snapshot_current"
        and authority == "current_verified"
        and is_current == "true"
    ):
        return "lane_a_current_verified"
    if category in HISTORICAL_CATEGORIES:
        return "lane_b_historical_review"
    if category == "generated_output":
        return "lane_c_generated_derivative"
    if category in EMBEDDED_CATEGORIES:
        return "lane_d_embedded_code"
    if category in NARRATIVE_CATEGORIES:
        return "lane_e_narrative_reference"
    return "lane_f_excluded_review_required"


def may_set_repo_artifact_family(row: dict[str, Any], family: str, *, require_current: bool) -> bool:
    if family not in TECHNICAL_CANON_FAMILY_VALUES:
        return False
    if str(row.get("candidate_artifact_family") or "") != "artefacto_repositorio":
        return False
    if require_current:
        return (
            row.get("diagnostic_category") == "repo_snapshot_current"
            and row.get("candidate_authority_level") == "current_verified"
            and str(row.get("candidate_is_current_repo_artifact")).lower() == "true"
            and row.get("risk_level") != "critical"
        )
    return True


def fields_for_lane(row: dict[str, Any], lane: str, family: str) -> dict[str, str]:
    if lane == "lane_a_current_verified":
        fields = {
            "repo_path": str(row.get("candidate_repo_path") or ""),
            "repo_directory": str(row.get("candidate_repo_directory") or ""),
            "repo_extension": str(row.get("candidate_repo_extension") or ""),
            "repo_artifact_kind": str(row.get("candidate_repo_artifact_kind") or ""),
            "content_sha256": str(row.get("candidate_content_sha256") or row.get("canon_content_sha256") or ""),
            "repo_lifecycle_state": "current_repo_artifact",
            "is_current_repo_artifact": "true",
            "authority_level": "current_verified",
        }
        if may_set_repo_artifact_family(row, family, require_current=True):
            fields = {"artifact_family": "artefacto_repositorio", **fields}
        return fields
    if lane == "lane_b_historical_review":
        lifecycle = str(row.get("candidate_repo_lifecycle_state") or "historical_snapshot")
        fields = {
            "repo_path": str(row.get("candidate_repo_path") or ""),
            "repo_directory": str(row.get("candidate_repo_directory") or ""),
            "repo_extension": str(row.get("candidate_repo_extension") or ""),
            "repo_artifact_kind": str(row.get("candidate_repo_artifact_kind") or ""),
            "repo_lifecycle_state": lifecycle,
            "is_current_repo_artifact": "false",
            "authority_level": "historical_snapshot",
        }
        moved_to = str(row.get("moved_to_candidate") or "")
        if moved_to:
            fields["moved_to_candidate"] = moved_to
        return fields
    if lane == "lane_c_generated_derivative":
        return {
            "technical_content_role": "generated_output",
            "authority_level": "generated_derivative",
            "is_current_repo_artifact": "false",
        }
    if lane == "lane_d_embedded_code":
        return {
            "contains_code": "true",
            "technical_content_role": "embedded_code_block",
            "authority_level": "narrative_reference",
        }
    if lane == "lane_e_narrative_reference":
        return {
            "contains_repo_references": "true",
            "technical_content_role": "session_or_diagnostic_narrative",
            "authority_level": "narrative_reference",
        }
    return {}


def op_id_for(row: dict[str, Any], lane: str, fields: dict[str, str]) -> str:
    source = {
        "session": "S0147",
        "target_id": row.get("id", ""),
        "lane": lane,
        "fields": fields,
    }
    return "s0147_" + sha256_text(stable_json(source))[:24]


def operation_for(row: dict[str, Any], lane: str, canon_row: dict[str, Any] | None) -> dict[str, Any]:
    family = current_family(canon_row)
    fields = fields_for_lane(row, lane, family)
    return {
        "op_id": op_id_for(row, lane, fields),
        "session": "S0147",
        "target_id": str(row.get("id") or ""),
        "target_title": str(row.get("title") or ""),
        "target_slug": slugify(str(row.get("title") or "")),
        "current_artifact_family": family,
        "patch_lane": lane,
        "batch_id": LANE_BATCHES[lane],
        "operation": "metadata_preview",
        "fields_preview": fields,
        "source_classification_id": str(row.get("id") or ""),
        "source_diagnostic_category": str(row.get("diagnostic_category") or ""),
        "source_authority_level": str(row.get("candidate_authority_level") or ""),
        "source_risk_level": str(row.get("risk_level") or ""),
        "evidence": [
            f"diagnostic_category={row.get('diagnostic_category')}",
            f"authority_level={row.get('candidate_authority_level')}",
            f"content_comparison={row.get('content_comparison')}",
            f"repo_path={row.get('candidate_repo_path') or ''}",
        ],
        "reason": reason_for_lane(row, lane, family, fields),
        "requires_human_review": True,
        "human_approved": False,
        "applied_to_canon": False,
        "dry_run": True,
    }


def reason_for_lane(row: dict[str, Any], lane: str, family: str, fields: dict[str, str]) -> str:
    if lane == "lane_a_current_verified":
        if fields.get("artifact_family") == "artefacto_repositorio":
            return "Current verified repo snapshot; eligible for future human-reviewed metadata patch."
        return f"Current verified repo snapshot, but existing artifact_family {family!r} is preserved."
    if lane == "lane_b_historical_review":
        return "Historical, drifted, missing or moved repo snapshot; separated from current verified batch."
    if lane == "lane_c_generated_derivative":
        return "Generated output receives derivative role metadata only; no repo source authority."
    if lane == "lane_d_embedded_code":
        return "Embedded code block receives auxiliary technical-content metadata only."
    if lane == "lane_e_narrative_reference":
        return "Session/diagnostic narrative receives repo-reference metadata only."
    return "Excluded from patch preview pending human review."


def excluded_record(row: dict[str, Any], lane: str, canon_row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "session": "S0147",
        "target_id": str(row.get("id") or ""),
        "target_title": str(row.get("title") or ""),
        "current_artifact_family": current_family(canon_row),
        "patch_lane": lane,
        "excluded_reason": excluded_reason(row),
        "source_diagnostic_category": str(row.get("diagnostic_category") or ""),
        "source_risk_level": str(row.get("risk_level") or ""),
        "source_confidence": str(row.get("confidence") or ""),
        "human_approved": False,
        "applied_to_canon": False,
        "dry_run": True,
    }


def excluded_reason(row: dict[str, Any]) -> str:
    category = str(row.get("diagnostic_category") or "")
    if category == "review_required":
        return "review_required"
    if str(row.get("risk_level") or "") == "critical":
        return "critical_risk"
    if str(row.get("confidence") or "") == "requires_human_review":
        return "requires_human_review"
    return "insufficient_metadata_rule"


def review_item_from_operation(op: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": "review_" + op["op_id"],
        "batch_id": op["batch_id"],
        "target_id": op["target_id"],
        "target_title": op["target_title"],
        "patch_lane": op["patch_lane"],
        "summary": op["reason"],
        "risk_level": op["source_risk_level"],
        "recommended_action": "review_metadata_preview",
        "status": "pending_review",
        "human_decision": "not_recorded",
        "human_approved": False,
    }


def review_item_from_excluded(item: dict[str, Any]) -> dict[str, Any]:
    review_id = "review_excluded_" + sha256_text(stable_json(item))[:24]
    return {
        "review_id": review_id,
        "batch_id": LANE_BATCHES["lane_f_excluded_review_required"],
        "target_id": item["target_id"],
        "target_title": item["target_title"],
        "patch_lane": item["patch_lane"],
        "summary": item["excluded_reason"],
        "risk_level": item["source_risk_level"],
        "recommended_action": "defer_or_review_manually",
        "status": "pending_review",
        "human_decision": "not_recorded",
        "human_approved": False,
    }


def subset_sha(rows: list[dict[str, Any]]) -> str:
    return sha256_text("".join(stable_json(row) + "\n" for row in rows))


def build_batches(
    operations: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    *,
    classification_sha: str,
    canon_sha: str,
) -> dict[str, Any]:
    rows_by_batch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for op in operations:
        rows_by_batch[op["batch_id"]].append(op)
    rows_by_batch[LANE_BATCHES["lane_f_excluded_review_required"]].extend(excluded)

    batches: dict[str, Any] = {
        "schema": "repo-metadata-review-batches/v1",
        "session": "S0147",
        "dry_run": True,
        "applied_to_canon": False,
        "human_approved": False,
        "batches": {},
    }
    for lane, batch_id in LANE_BATCHES.items():
        rows = sorted(rows_by_batch.get(batch_id, []), key=lambda row: stable_json(row))
        risk_profile = dict(sorted(Counter(str(row.get("source_risk_level") or row.get("risk_level") or "") for row in rows).items()))
        batches["batches"][batch_id] = {
            "batch_id": batch_id,
            "batch_label": BATCH_LABELS[batch_id],
            "patch_lane": lane,
            "record_count": len(rows),
            "patch_sha256": subset_sha(rows),
            "source_classification_sha256": classification_sha,
            "canon_before_sha256": canon_sha,
            "risk_profile": risk_profile,
            "recommended_for_future_approval": batch_id == "batch_current_verified" and bool(rows),
            "human_approved": False,
            "approval_disabled_in_s0147": True,
            "applied_to_canon": False,
        }
    return batches


def build_summary(
    classification_rows: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    batches: dict[str, Any],
) -> dict[str, Any]:
    lane_counts = dict(sorted(Counter(op["patch_lane"] for op in operations).items()))
    lane_counts["lane_f_excluded_review_required"] = len(excluded)
    return {
        "schema": "repo-metadata-patch-summary/v1",
        "session": "S0147",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "human_approved": False,
        "classification_records_read": len(classification_rows),
        "patch_operations_generated": len(operations),
        "excluded_records": len(excluded),
        "patch_lane_counts": lane_counts,
        "diagnostic_category_counts": dict(sorted(Counter(row.get("source_diagnostic_category") for row in operations).items())),
        "authority_level_counts": dict(sorted(Counter(row.get("source_authority_level") for row in operations).items())),
        "risk_level_counts": dict(sorted(Counter(row.get("source_risk_level") for row in operations).items())),
        "preserve_artifact_family_count": sum(1 for op in operations if "artifact_family" not in op["fields_preview"]),
        "future_artefacto_repositorio_count": sum(1 for op in operations if op["fields_preview"].get("artifact_family") == "artefacto_repositorio"),
        "batch_count": len(batches["batches"]),
        "relations_generated": False,
        "candidate_relations_generated": False,
        "formal_relation_candidates_generated": False,
    }


def summary_markdown(summary: dict[str, Any], hashes: dict[str, str] | None = None) -> str:
    hashes = hashes or {}
    lines = [
        "# S0147 repo metadata patch summary",
        "",
        f"- Registros S0146 leidos: {summary['classification_records_read']}",
        f"- Operaciones de patch preview: {summary['patch_operations_generated']}",
        f"- Excluidos carril F: {summary['excluded_records']}",
        f"- Preservan artifact_family original: {summary['preserve_artifact_family_count']}",
        f"- Podrian recibir artefacto_repositorio en futuro: {summary['future_artefacto_repositorio_count']}",
        f"- Batches creados: {summary['batch_count']}",
        f"- Relaciones formales generadas: {summary['formal_relation_candidates_generated']}",
        "",
        "## Carriles",
    ]
    for lane, count in summary["patch_lane_counts"].items():
        lines.append(f"- {lane}: {count}")
    if hashes:
        lines.extend(
            [
                "",
                "## Hashes",
                f"- patch_preview_sha256: `{hashes.get('patch_preview_sha256', '')}`",
                f"- s0146_classification_sha256: `{hashes.get('s0146_classification_sha256', '')}`",
                f"- canon_before_sha256: `{hashes.get('canon_before_sha256', '')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Estado",
            "- `human_approved`: false en todos los registros y batches.",
            "- `applied_to_canon`: false en todos los registros y batches.",
            "- `dry_run`: true.",
            "- El menu de S0147 permite inspeccion, no aprobacion.",
        ]
    )
    return "\n".join(lines) + "\n"


def risk_report(operations: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> dict[str, Any]:
    risky_ops = [op for op in operations if op["source_risk_level"] in {"high", "critical"}]
    return {
        "schema": "repo-metadata-risk-report/v1",
        "session": "S0147",
        "dry_run": True,
        "applied_to_canon": False,
        "human_approved": False,
        "high_or_critical_operations": len(risky_ops),
        "excluded_records": len(excluded),
        "risk_counts": dict(sorted(Counter(op["source_risk_level"] for op in operations).items())),
        "excluded_reason_counts": dict(sorted(Counter(item["excluded_reason"] for item in excluded).items())),
        "items": [
            {
                "target_id": op["target_id"],
                "target_title": op["target_title"],
                "patch_lane": op["patch_lane"],
                "risk_level": op["source_risk_level"],
                "reason": op["reason"],
            }
            for op in risky_ops[:200]
        ],
    }


def risk_report_md(report: dict[str, Any]) -> str:
    lines = [
        "# S0147 repo metadata risk report",
        "",
        f"- High/critical patch operations: {report['high_or_critical_operations']}",
        f"- Excluded records: {report['excluded_records']}",
        "",
        "## Risk counts",
    ]
    for risk, count in report["risk_counts"].items():
        lines.append(f"- {risk}: {count}")
    lines.append("")
    lines.append("## Excluded reasons")
    for reason, count in report["excluded_reason_counts"].items():
        lines.append(f"- {reason}: {count}")
    return "\n".join(lines) + "\n"


def dry_run_report(
    summary: dict[str, Any],
    excluded: list[dict[str, Any]],
    queue: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "repo-metadata-dry-run-report/v1",
        "session": "S0147",
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "human_approved": False,
        "approval_required_for_future_apply": True,
        "metadata_patch_preview_generated": True,
        "menu_review_prepared": True,
        "relations_generated": False,
        "candidate_relations_generated": False,
        "formal_relation_candidates_generated": False,
        "counts": {
            "patch_lane": summary["patch_lane_counts"],
            "diagnostic_category": summary["diagnostic_category_counts"],
            "authority_level": summary["authority_level_counts"],
            "risk_level": summary["risk_level_counts"],
            "recommended_action": dict(sorted(Counter(item["recommended_action"] for item in queue).items())),
            "excluded_reason": dict(sorted(Counter(item["excluded_reason"] for item in excluded).items())),
        },
    }


def menu_contract_md() -> str:
    return """# S0147 repo metadata review menu contract

## Purpose
The menu exposes S0147 metadata patch preview artifacts for local inspection.
It does not approve batches and does not apply metadata.

## Commands
- `--summary`
- `--list-batches`
- `--show-batch <batch_id>`
- `--show-excluded`
- `--show-risks`
- `--validate-dry-run`
- `--export-csv`

## Approval policy
Approval is disabled in S0147. Any approval-oriented command must return
`approval_disabled_in_s0147`. S0148 is responsible for terminal approval and
dry-run gates.
"""


def operator_instructions_md(batches: dict[str, Any]) -> str:
    batch_lines = [
        f"- `{batch_id}`: {payload['batch_label']} ({payload['record_count']} registros)"
        for batch_id, payload in batches["batches"].items()
    ]
    return "\n".join(
        [
            "# S0147 operator instructions",
            "",
            "## Que genero S0147",
            "Patch preview reversible de metadata tecnica estratificada, cola de revision, batches, hashes y menu local de inspeccion.",
            "",
            "## Que puede revisar el operador",
            "- Resumen del patch.",
            "- Lotes disponibles.",
            "- Detalle de lote.",
            "- Registros excluidos.",
            "- Riesgos alto/critico.",
            "- Hashes y manifiesto.",
            "- CSV de revision.",
            "",
            "## No permitido todavia",
            "- Aprobar lotes.",
            "- Aplicar metadata.",
            "- Modificar canon.",
            "- Generar relaciones formales.",
            "",
            "## Batches",
            *batch_lines,
            "",
            "## Batch mas seguro",
            "`batch_current_verified` es el lote mas seguro para revision futura, pero no queda aprobado en S0147.",
            "",
            "## Comando de menu",
            "`python3 src/python_scripts/repo_metadata_review_menu.py --summary`",
            "",
            "## Responsabilidad de S0148",
            "Registrar aprobacion humana por terminal, verificar hashes y correr compuerta dry-run. En S0147 no se aprueba ningun lote.",
            "",
        ]
    )


def relation_context_md(classification_path: Path) -> str:
    relation_path = classification_path.parent / "s0146_repo_artifact_relation_opportunities.jsonl"
    count = len(read_jsonl(relation_path)) if relation_path.exists() else 0
    return "\n".join(
        [
            "# S0147 relation opportunities context",
            "",
            f"- S0146 relation opportunities observed: {count}",
            "- relations_generated: false",
            "- candidate_relations_generated: false",
            "- formal_relation_candidates_generated: false",
            "- admissible_in_s0147: false",
            "",
            "```json",
            stable_json(
                {
                    "relations_generated": False,
                    "candidate_relations_generated": False,
                    "formal_relation_candidates_generated": False,
                    "admissible_in_s0147": False,
                },
                indent=2,
            ),
            "```",
            "",
            "S0147 only notes that metadata can improve future evidence. It does not create candidate_relations.",
            "",
        ]
    )


def validation_report(
    operations: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    batches: dict[str, Any],
) -> dict[str, Any]:
    patch_violations = [
        op["op_id"]
        for op in operations
        if op.get("dry_run") is not True
        or op.get("applied_to_canon") is not False
        or op.get("human_approved") is not False
    ]
    batch_violations = [
        batch_id
        for batch_id, batch in batches["batches"].items()
        if batch.get("human_approved") is not False
        or batch.get("approval_disabled_in_s0147") is not True
        or batch.get("applied_to_canon") is not False
    ]
    return {
        "schema": "repo-metadata-validation-report/v1",
        "session": "S0147",
        "dry_run": True,
        "patch_records": len(operations),
        "excluded_records": len(excluded),
        "batch_count": len(batches["batches"]),
        "patch_violations": patch_violations,
        "batch_violations": batch_violations,
        "relations_generated": False,
        "candidate_relations_generated": False,
        "formal_relation_candidates_generated": False,
        "valid": not patch_violations and not batch_violations,
    }


def build_repo_metadata_patch_preview(
    *,
    classification: Path = DEFAULT_CLASSIFICATION,
    metadata_contract: Path = DEFAULT_METADATA_CONTRACT,
    canon_glob: str = DEFAULT_CANON_GLOB,
    out_dir: Path = DEFAULT_OUT_DIR,
    session: str = "S0147",
    dry_run: bool = True,
) -> dict[str, Any]:
    if not dry_run:
        raise ValueError("S0147 only supports dry_run=true")
    if session != "S0147":
        raise ValueError("this builder is scoped to S0147")
    if not classification.exists():
        raise FileNotFoundError(classification)
    if not metadata_contract.exists():
        raise FileNotFoundError(metadata_contract)

    out_dir.mkdir(parents=True, exist_ok=True)
    classification_rows = read_jsonl(classification)
    canon_index = load_canon_index(canon_glob)
    classification_sha = file_sha256(classification)
    canon_sha = tree_sha256(canon_glob)

    operations: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in sorted(classification_rows, key=lambda item: (str(item.get("title") or ""), str(item.get("id") or ""))):
        lane = lane_for(row)
        canon_row = canon_index.get(str(row.get("id") or ""))
        if lane == "lane_f_excluded_review_required":
            excluded.append(excluded_record(row, lane, canon_row))
            continue
        operations.append(operation_for(row, lane, canon_row))
    operations = sorted(operations, key=lambda op: op["op_id"])
    excluded = sorted(excluded, key=lambda item: (item["target_title"], item["target_id"]))
    queue = [review_item_from_operation(op) for op in operations] + [review_item_from_excluded(item) for item in excluded]
    queue = sorted(queue, key=lambda item: item["review_id"])
    batches = build_batches(operations, excluded, classification_sha=classification_sha, canon_sha=canon_sha)
    summary = build_summary(classification_rows, operations, excluded, batches)
    risks = risk_report(operations, excluded)
    dry_report = dry_run_report(summary, excluded, queue)
    validation = validation_report(operations, excluded, batches)

    paths = {
        "patch_preview": out_dir / "s0147_repo_metadata_patch_preview.jsonl",
        "summary_json": out_dir / "s0147_repo_metadata_patch_summary.json",
        "summary_md": out_dir / "s0147_repo_metadata_patch_summary.md",
        "review_queue": out_dir / "s0147_repo_metadata_review_queue.jsonl",
        "review_batches": out_dir / "s0147_repo_metadata_review_batches.json",
        "review_csv": out_dir / "s0147_repo_metadata_review.csv",
        "excluded": out_dir / "s0147_repo_metadata_excluded_records.jsonl",
        "risk_json": out_dir / "s0147_repo_metadata_risk_report.json",
        "risk_md": out_dir / "s0147_repo_metadata_risk_report.md",
        "dry_run": out_dir / "s0147_repo_metadata_dry_run_report.json",
        "menu_contract": out_dir / "s0147_repo_metadata_menu_contract.md",
        "hashes": out_dir / "s0147_repo_metadata_patch_hashes.json",
        "validation": out_dir / "s0147_repo_metadata_validation_report.json",
        "operator_instructions": out_dir / "s0147_repo_metadata_operator_instructions.md",
        "relation_context": out_dir / "s0147_relation_opportunities_context.md",
    }

    write_jsonl(paths["patch_preview"], operations)
    write_jsonl(paths["review_queue"], queue)
    write_json(paths["review_batches"], batches)
    write_csv(paths["review_csv"], operations)
    write_jsonl(paths["excluded"], excluded)
    write_json(paths["risk_json"], risks)
    paths["risk_md"].write_text(risk_report_md(risks), encoding="utf-8")
    write_json(paths["dry_run"], dry_report)
    paths["menu_contract"].write_text(menu_contract_md(), encoding="utf-8")
    write_json(paths["validation"], validation)
    paths["operator_instructions"].write_text(operator_instructions_md(batches), encoding="utf-8")
    paths["relation_context"].write_text(relation_context_md(classification), encoding="utf-8")

    hashes = {
        "schema": "repo-metadata-patch-hashes/v1",
        "session": session,
        "canon_before_sha256": canon_sha,
        "s0146_classification_sha256": classification_sha,
        "patch_preview_sha256": file_sha256(paths["patch_preview"]),
        "review_queue_sha256": file_sha256(paths["review_queue"]),
        "review_batches_sha256": file_sha256(paths["review_batches"]),
        "dry_run_report_sha256": file_sha256(paths["dry_run"]),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    write_json(paths["hashes"], hashes)
    write_json(paths["summary_json"], summary)
    paths["summary_md"].write_text(summary_markdown(summary, hashes), encoding="utf-8")

    return {
        "summary": summary,
        "hashes": hashes,
        "paths": {key: str(path) for key, path in paths.items()},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build S0147 repo metadata patch preview")
    parser.add_argument("--classification", default=str(DEFAULT_CLASSIFICATION))
    parser.add_argument("--metadata-contract", default=str(DEFAULT_METADATA_CONTRACT))
    parser.add_argument("--canon-glob", default=DEFAULT_CANON_GLOB)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--session", default="S0147")
    parser.add_argument("--dry-run", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_repo_metadata_patch_preview(
        classification=Path(args.classification),
        metadata_contract=Path(args.metadata_contract),
        canon_glob=args.canon_glob,
        out_dir=Path(args.out_dir),
        session=args.session,
        dry_run=args.dry_run,
    )
    print(stable_json({"status": "ok", **result["summary"], "patch_preview_sha256": result["hashes"]["patch_preview_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
