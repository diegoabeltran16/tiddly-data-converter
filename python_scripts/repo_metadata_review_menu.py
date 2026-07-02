#!/usr/bin/env python3
"""Local menu for S0147/S0148 repo metadata review and dry-run gate.

The script inspects S0147 artifacts and, in S0148, records terminal decisions
only when an explicit token is provided by the operator. It never applies
metadata to canon.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import repo_metadata_admission_gate as gate
import repo_metadata_refresh_patch as refresh


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_review" / "s0147"
DEFAULT_S0148_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_review" / "s0148"
DEFAULT_S0149_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_admission" / "s0149"
DEFAULT_S0151_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_admission" / "s0151"
DEFAULT_LATEST_METADATA_PATCH_MANIFEST = (
    REPO_ROOT / "data" / "out" / "local" / "pipeline" / "repo_metadata_admission" / "latest_metadata_patch_manifest.json"
)
DEFAULT_SEMANTIC_AUTHORITY_OUT_DIR = REPO_ROOT / "data" / "out" / "local" / "pipeline" / "semantic_text_authority" / "s0149"

APPROVAL_REQUIRES_TERMINAL_TOKEN = "approval_requires_terminal_token"


def _paths(out_dir: Path) -> dict[str, Path]:
    return {
        "patch_preview": out_dir / "s0147_repo_metadata_patch_preview.jsonl",
        "summary": out_dir / "s0147_repo_metadata_patch_summary.json",
        "summary_md": out_dir / "s0147_repo_metadata_patch_summary.md",
        "review_queue": out_dir / "s0147_repo_metadata_review_queue.jsonl",
        "batches": out_dir / "s0147_repo_metadata_review_batches.json",
        "csv": out_dir / "s0147_repo_metadata_review.csv",
        "excluded": out_dir / "s0147_repo_metadata_excluded_records.jsonl",
        "risk": out_dir / "s0147_repo_metadata_risk_report.json",
        "dry_run": out_dir / "s0147_repo_metadata_dry_run_report.json",
        "contract": out_dir / "s0147_repo_metadata_menu_contract.md",
        "hashes": out_dir / "s0147_repo_metadata_patch_hashes.json",
        "validation": out_dir / "s0147_repo_metadata_validation_report.json",
        "instructions": out_dir / "s0147_repo_metadata_operator_instructions.md",
    }


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError(f"expected JSON object line in {path}")
                rows.append(value)
    return rows


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _print_limited_rows(rows: list[dict[str, Any]], *, limit: int = 30) -> None:
    for row in rows[:limit]:
        title = row.get("target_title", "")
        target = row.get("target_id", "")
        lane = row.get("patch_lane", "")
        risk = row.get("source_risk_level", row.get("risk_level", ""))
        reason = row.get("reason", row.get("summary", row.get("excluded_reason", "")))
        print(f"- {target} | {lane} | risk={risk} | {title}")
        if reason:
            print(f"  {reason}")
    if len(rows) > limit:
        print(f"... {len(rows) - limit} registros adicionales no mostrados")


def show_summary(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    p = _paths(out_dir)
    summary = _load_json(p["summary"])
    hashes = _load_json(p["hashes"]) if p["hashes"].exists() else {}
    print("S0147 repo metadata patch preview")
    print(f"- classification_records_read: {summary.get('classification_records_read')}")
    print(f"- patch_operations_generated: {summary.get('patch_operations_generated')}")
    print(f"- excluded_records: {summary.get('excluded_records')}")
    print(f"- preserve_artifact_family_count: {summary.get('preserve_artifact_family_count')}")
    print(f"- future_artefacto_repositorio_count: {summary.get('future_artefacto_repositorio_count')}")
    print(f"- canon_modified: {summary.get('canon_modified')}")
    print(f"- human_approved: {summary.get('human_approved')}")
    print(f"- applied_to_canon: {summary.get('applied_to_canon')}")
    print(f"- patch_preview_sha256: {hashes.get('patch_preview_sha256', '')}")
    print("Carriles:")
    for lane, count in sorted((summary.get("patch_lane_counts") or {}).items()):
        print(f"- {lane}: {count}")


def list_batches(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    batches = _load_json(_paths(out_dir)["batches"]).get("batches", {})
    print("S0147 batches")
    for batch_id, batch in sorted(batches.items()):
        print(
            f"- {batch_id}: {batch.get('record_count')} registros, "
            f"approved={batch.get('human_approved')}, "
            f"approval_disabled={batch.get('approval_disabled_in_s0147')}"
        )


def show_batch(batch_id: str, out_dir: Path = DEFAULT_OUT_DIR) -> None:
    p = _paths(out_dir)
    batches = _load_json(p["batches"]).get("batches", {})
    if batch_id not in batches:
        raise KeyError(f"batch not found: {batch_id}")
    batch = batches[batch_id]
    print(_stable_json(batch))
    print("Registros:")
    if batch_id == "batch_excluded_review_required":
        rows = _load_jsonl(p["excluded"])
    else:
        rows = [row for row in _load_jsonl(p["patch_preview"]) if row.get("batch_id") == batch_id]
    _print_limited_rows(rows, limit=50)


def show_excluded(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    rows = _load_jsonl(_paths(out_dir)["excluded"])
    print(f"S0147 excluded records: {len(rows)}")
    _print_limited_rows(rows, limit=80)


def show_risks(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    report = _load_json(_paths(out_dir)["risk"])
    print("S0147 risk report")
    print(f"- high_or_critical_operations: {report.get('high_or_critical_operations')}")
    print(f"- excluded_records: {report.get('excluded_records')}")
    print("Risk counts:")
    for risk, count in sorted((report.get("risk_counts") or {}).items()):
        print(f"- {risk}: {count}")
    print("Excluded reasons:")
    for reason, count in sorted((report.get("excluded_reason_counts") or {}).items()):
        print(f"- {reason}: {count}")
    items = report.get("items") or []
    if items:
        print("Items:")
        _print_limited_rows(items, limit=50)


def show_hashes(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    print(_stable_json(_load_json(_paths(out_dir)["hashes"])))


def export_csv(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    path = _paths(out_dir)["csv"]
    if not path.exists():
        raise FileNotFoundError(path)
    row_count = 0
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for _ in reader:
            row_count += 1
    print(f"CSV disponible: {_display(path)}")
    print(f"Registros: {row_count}")


def show_contract(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    path = _paths(out_dir)["contract"]
    if not path.exists():
        raise FileNotFoundError(path)
    print(path.read_text(encoding="utf-8"))


def validate_dry_run_contract(out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Any]:
    p = _paths(out_dir)
    operations = _load_jsonl(p["patch_preview"])
    queue = _load_jsonl(p["review_queue"])
    excluded = _load_jsonl(p["excluded"])
    batches_doc = _load_json(p["batches"])
    summary = _load_json(p["summary"])
    dry = _load_json(p["dry_run"])
    validation = _load_json(p["validation"])
    hashes = _load_json(p["hashes"])

    violations: list[str] = []

    for op in operations:
        if op.get("dry_run") is not True:
            violations.append(f"operation_not_dry_run:{op.get('op_id')}")
        if op.get("applied_to_canon") is not False:
            violations.append(f"operation_applied:{op.get('op_id')}")
        if op.get("human_approved") is not False:
            violations.append(f"operation_human_approved:{op.get('op_id')}")
        if "relations" in op or "candidate_relations" in op:
            violations.append(f"operation_relation_field:{op.get('op_id')}")
        fields = op.get("fields_preview") or {}
        if isinstance(fields, dict) and ("relations" in fields or "candidate_relations" in fields):
            violations.append(f"operation_field_relation:{op.get('op_id')}")

    for item in queue:
        if item.get("human_approved") is not False:
            violations.append(f"queue_human_approved:{item.get('review_id')}")
        if item.get("human_decision") in {"approved", "accepted"}:
            violations.append(f"queue_positive_decision:{item.get('review_id')}")

    for item in excluded:
        if item.get("dry_run") is not True:
            violations.append(f"excluded_not_dry_run:{item.get('target_id')}")
        if item.get("applied_to_canon") is not False:
            violations.append(f"excluded_applied:{item.get('target_id')}")
        if item.get("human_approved") is not False:
            violations.append(f"excluded_human_approved:{item.get('target_id')}")

    for batch_id, batch in (batches_doc.get("batches") or {}).items():
        if batch.get("human_approved") is not False:
            violations.append(f"batch_human_approved:{batch_id}")
        if batch.get("approval_disabled_in_s0147") is not True:
            violations.append(f"batch_approval_not_disabled:{batch_id}")
        if batch.get("applied_to_canon") is not False:
            violations.append(f"batch_applied:{batch_id}")

    if summary.get("relations_generated") is not False:
        violations.append("summary_relations_generated")
    if summary.get("candidate_relations_generated") is not False:
        violations.append("summary_candidate_relations_generated")
    if summary.get("formal_relation_candidates_generated") is not False:
        violations.append("summary_formal_relation_candidates_generated")
    if dry.get("relations_generated") is not False:
        violations.append("dry_run_relations_generated")
    if dry.get("candidate_relations_generated") is not False:
        violations.append("dry_run_candidate_relations_generated")
    if dry.get("formal_relation_candidates_generated") is not False:
        violations.append("dry_run_formal_relation_candidates_generated")
    if validation.get("valid") is not True:
        violations.append("validation_report_invalid")

    expected_hashes = {
        "patch_preview_sha256": p["patch_preview"],
        "review_queue_sha256": p["review_queue"],
        "review_batches_sha256": p["batches"],
        "dry_run_report_sha256": p["dry_run"],
    }
    for field, file_path in expected_hashes.items():
        expected = hashes.get(field)
        actual = _file_sha256(file_path)
        if expected != actual:
            violations.append(f"hash_mismatch:{field}")

    return {
        "schema": "repo-metadata-menu-validation/v1",
        "session": "S0147",
        "valid": not violations,
        "violations": violations,
        "patch_records": len(operations),
        "queue_records": len(queue),
        "excluded_records": len(excluded),
        "batch_count": len(batches_doc.get("batches") or {}),
        "hashes_valid": not any(item.startswith("hash_mismatch:") for item in violations),
        "approval_disabled_in_s0147": True,
        "human_approved": False,
        "applied_to_canon": False,
        "dry_run": True,
    }


def run_validate_dry_run(out_dir: Path = DEFAULT_OUT_DIR) -> int:
    result = validate_dry_run_contract(out_dir)
    print(_stable_json(result))
    return 0 if result["valid"] else 1


def _prompt_token(batch_id: str, decision: str) -> str:
    expected = gate.expected_token(batch_id, decision)
    print(f"Token requerido: {expected}")
    try:
        return input("Token: ").strip()
    except EOFError:
        return ""


def record_batch_decision(
    *,
    batch_id: str,
    decision: str,
    token: str | None,
    out_dir: Path = DEFAULT_OUT_DIR,
    decision_dir: Path = DEFAULT_S0148_OUT_DIR,
) -> int:
    if token is None:
        token = _prompt_token(batch_id, decision)
    if not token:
        print(f"{APPROVAL_REQUIRES_TERMINAL_TOKEN}: no token provided for {batch_id}")
        return 2
    result = gate.record_terminal_decision(
        batch_id=batch_id,
        decision=decision,
        token=token,
        patch_preview=_paths(out_dir)["patch_preview"],
        review_batches=_paths(out_dir)["batches"],
        patch_hashes=_paths(out_dir)["hashes"],
        human_decisions=gate.s0148_paths(decision_dir)["human_decisions"],
        out_dir=decision_dir,
    )
    print(_stable_json(result))
    return 0 if result.get("status") == "ok" else 2


def run_gate_dry_run(
    out_dir: Path = DEFAULT_OUT_DIR,
    decision_dir: Path = DEFAULT_S0148_OUT_DIR,
    *,
    canon_glob: str | None = None,
    s0146_classification: Path | None = None,
) -> int:
    report = gate.run_gate(
        patch_preview=_paths(out_dir)["patch_preview"],
        review_batches=_paths(out_dir)["batches"],
        patch_hashes=_paths(out_dir)["hashes"],
        dry_run_report=_paths(out_dir)["dry_run"],
        human_decisions=gate.s0148_paths(decision_dir)["human_decisions"],
        canon_glob=canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        s0146_classification=s0146_classification
        or (
            REPO_ROOT
            / "data"
            / "out"
            / "local"
            / "pipeline"
            / "repo_artifacts"
            / "s0146"
            / "s0146_repo_artifact_classification.jsonl"
        ),
        out_dir=decision_dir,
        session="S0148",
        dry_run=True,
    )
    print(_stable_json(report))
    return 0


def show_last_gate_report(decision_dir: Path = DEFAULT_S0148_OUT_DIR) -> int:
    path = gate.s0148_paths(decision_dir)["gate_report"]
    if not path.exists():
        print("No existe reporte de compuerta S0148 todavia.")
        return 1
    print(_stable_json(_load_json(path)))
    return 0


def show_s0149_summary(out_dir: Path = DEFAULT_OUT_DIR) -> None:
    show_summary(out_dir)
    catalog = gate.s0149_batch_catalog(_paths(out_dir)["batches"])
    print("\nS0149 batches seleccionables")
    for batch_id, item in sorted(catalog.items(), key=lambda pair: pair[1].get("choice", "")):
        marker = "recomendado" if item["recommended"] else "no recomendado"
        if item["blocked"]:
            marker = "bloqueado"
        print(
            f"- {item.get('choice')}) {batch_id}: {item.get('record_count')} operaciones, "
            f"{marker}, risk={item.get('risk_profile')}"
        )


def select_s0149_batches(selection: str, out_dir: Path = DEFAULT_OUT_DIR, admission_dir: Path = DEFAULT_S0149_OUT_DIR) -> int:
    doc = gate.select_s0149_batches(
        selection,
        review_batches=_paths(out_dir)["batches"],
        out_dir=admission_dir,
    )
    print(_stable_json(doc))
    return 0 if doc.get("valid") is True else 2


def run_s0149_gate_dry_run(
    out_dir: Path = DEFAULT_OUT_DIR,
    admission_dir: Path = DEFAULT_S0149_OUT_DIR,
    *,
    canon_glob: str | None = None,
    s0146_classification: Path | None = None,
) -> int:
    selected = gate.s0149_paths(admission_dir)["selected_batches"]
    if not selected.exists():
        print(f"No existe seleccion S0149: {_display(selected)}")
        return 2
    report = gate.run_s0149_dry_run(
        patch_preview=_paths(out_dir)["patch_preview"],
        review_batches=_paths(out_dir)["batches"],
        patch_hashes=_paths(out_dir)["hashes"],
        dry_run_report=_paths(out_dir)["dry_run"],
        selected_batches=selected,
        canon_glob=canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        s0146_classification=s0146_classification
        or (
            REPO_ROOT
            / "data"
            / "out"
            / "local"
            / "pipeline"
            / "repo_artifacts"
            / "s0146"
            / "s0146_repo_artifact_classification.jsonl"
        ),
        out_dir=admission_dir,
    )
    print(_stable_json(report))
    return 0


def show_s0149_gate_report(admission_dir: Path = DEFAULT_S0149_OUT_DIR) -> int:
    path = gate.s0149_paths(admission_dir)["dry_run_report"]
    if not path.exists():
        print("No existe reporte dry-run S0149 todavia.")
        return 1
    print(_stable_json(_load_json(path)))
    return 0


def show_s0149_apply_status(admission_dir: Path = DEFAULT_S0149_OUT_DIR) -> int:
    path = gate.s0149_paths(admission_dir)["apply_report"]
    if not path.exists():
        report = gate.s0149_apply_not_executed_report("apply_not_requested")
        gate.write_json(path, report)
    print(_stable_json(_load_json(path)))
    return 0


def apply_s0149_metadata_from_menu(
    out_dir: Path = DEFAULT_OUT_DIR,
    admission_dir: Path = DEFAULT_S0149_OUT_DIR,
    *,
    canon_glob: str | None = None,
    s0146_classification: Path | None = None,
    apply_token: str | None = None,
) -> int:
    if apply_token is None:
        print("Vas a aplicar metadata al canon local.")
        print("Canon sera modificado: SI")
        print("Relaciones seran generadas: NO")
        print("semantic_text sera regenerado: NO en este paso")
        print(f"Para confirmar, escribe exactamente: {gate.S0149_APPLY_TOKEN}")
        try:
            apply_token = input("Token: ").strip()
        except EOFError:
            apply_token = ""
    report = gate.apply_s0149_metadata(
        patch_preview=_paths(out_dir)["patch_preview"],
        review_batches=_paths(out_dir)["batches"],
        patch_hashes=_paths(out_dir)["hashes"],
        s0147_dry_run_report=_paths(out_dir)["dry_run"],
        dry_run_report_path=gate.s0149_paths(admission_dir)["dry_run_report"],
        selected_batches=gate.s0149_paths(admission_dir)["selected_batches"],
        canon_glob=canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        s0146_classification=s0146_classification
        or (
            REPO_ROOT
            / "data"
            / "out"
            / "local"
            / "pipeline"
            / "repo_artifacts"
            / "s0146"
            / "s0146_repo_artifact_classification.jsonl"
        ),
        out_dir=admission_dir,
        apply_token=apply_token,
    )
    print(_stable_json(report))
    return 0 if report.get("apply_executed") is True else 2


def rollback_s0149_metadata(admission_dir: Path = DEFAULT_S0149_OUT_DIR) -> int:
    report = gate.rollback_s0149_metadata(out_dir=admission_dir)
    print(_stable_json(report))
    return 0 if report.get("rollback_executed") is True else 2


def run_semantic_authority(mode: str, *, canon_glob: str | None = None, out_dir: Path = DEFAULT_SEMANTIC_AUTHORITY_OUT_DIR) -> int:
    if mode not in {"preview", "generate"}:
        raise ValueError(f"invalid semantic authority mode: {mode}")
    script = SCRIPT_DIR / "build_semantic_text_authority_aware.py"
    args = [
        sys.executable,
        str(script),
        "--canon-glob",
        canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        "--out-dir",
        str(out_dir),
        "--session",
        "S0149",
        f"--{mode}",
    ]
    result = subprocess.run(args, cwd=REPO_ROOT, check=False, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    return result.returncode


def should_use_s0149_gate(out_dir: Path, admission_dir: Path) -> bool:
    selected = gate.s0149_paths(admission_dir)["selected_batches"]
    try:
        return out_dir.resolve() == DEFAULT_OUT_DIR.resolve() and selected.exists()
    except OSError:
        return out_dir == DEFAULT_OUT_DIR and selected.exists()


S0149_MENU_HEADER = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Metadata técnica / admisión gobernada [EXPERIMENTAL]
  Modo: DRY-RUN por defecto
  Canon: PROTEGIDO
  Apply: requiere confirmación humana explícita
  Relaciones: BLOQUEADAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Ver resumen de metadata técnica
2) Seleccionar batches para revisión/dry-run
3) Ver detalle de batch
4) Ejecutar compuerta dry-run con selección actual
5) Ver último resultado dry-run
6) Aplicar metadata aprobada al canon [requiere confirmación]
7) Rollback último apply de metadata
8) Semantic_text authority-aware
9) Avanzado / mantenimiento
0) Volver
"""


def interactive_s0149_menu(
    out_dir: Path = DEFAULT_OUT_DIR,
    admission_dir: Path = DEFAULT_S0149_OUT_DIR,
    *,
    canon_glob: str | None = None,
    s0146_classification: Path | None = None,
) -> int:
    while True:
        print(S0149_MENU_HEADER)
        try:
            choice = input("Seleccion: ").strip()
        except EOFError:
            return 0
        if choice == "0":
            return 0
        if choice == "1":
            show_s0149_summary(out_dir)
        elif choice == "2":
            show_s0149_summary(out_dir)
            raw = input("Selecciona batches separados por coma: ").strip()
            select_s0149_batches(raw, out_dir, admission_dir)
        elif choice == "3":
            batch_id = input("Batch ID o numero: ").strip()
            show_batch(gate.normalize_s0149_batch_token(batch_id), out_dir)
        elif choice == "4":
            print(f"Para ejecutar dry-run, escribe exactamente: {gate.S0149_DRY_RUN_TOKEN}")
            token = input("Token: ").strip()
            if token != gate.S0149_DRY_RUN_TOKEN:
                print("Dry-run bloqueado: token invalido.")
            else:
                run_s0149_gate_dry_run(
                    out_dir,
                    admission_dir,
                    canon_glob=canon_glob,
                    s0146_classification=s0146_classification,
                )
        elif choice == "5":
            show_s0149_gate_report(admission_dir)
        elif choice == "6":
            apply_s0149_metadata_from_menu(
                out_dir,
                admission_dir,
                canon_glob=canon_glob,
                s0146_classification=s0146_classification,
            )
        elif choice == "7":
            rollback_s0149_metadata(admission_dir)
        elif choice == "8":
            print("1) Preview authority-aware")
            print("2) Generate authority-aware")
            semantic_choice = input("Seleccion: ").strip()
            if semantic_choice == "1":
                run_semantic_authority("preview", canon_glob=canon_glob)
            elif semantic_choice == "2":
                print("Generate solo se recomienda despues de metadata apply exitoso y canon validado.")
                run_semantic_authority("generate", canon_glob=canon_glob)
            else:
                print("Opcion no reconocida")
        elif choice == "9":
            print("Reportes:")
            for key, path in gate.s0149_paths(admission_dir).items():
                if key != "backups":
                    print(f"- {key}: {_display(path)}")
        else:
            print("Opcion no reconocida")
        print()


HUMAN_BATCH_LABELS = {
    "batch_current_verified": "Código vigente verificado",
    "batch_embedded_code": "Código embebido",
    "batch_narrative_reference": "Narrativa técnica",
    "batch_historical_review": "Histórico/divergente",
    "batch_generated_derivative": "Generados",
    "batch_excluded_review_required": "Excluidos / requieren revisión",
}


S0151_MENU_HEADER = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Metadata técnica
  Canon: PROTEGIDO
  Modo normal: guiado
  IDs y hashes: solo en avanzado
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1) Ver estado simple
2) Usar selección recomendada
3) Solo código vigente verificado
4) Solo metadata auxiliar
5) Selección personalizada guiada
6) Refrescar patch contra canon actual
7) Ejecutar dry-run
8) Ver resultado dry-run
9) Aplicar metadata al canon
10) Rollback último apply
11) Avanzado / IDs, hashes y reportes
0) Volver
"""


S0151_ADVANCED_HEADER = """Avanzado / IDs, hashes y reportes
1) Ver batch IDs
2) Ver patch hashes
3) Ver canon_before_sha256
4) Ver op_ids
5) Ver rutas de reportes JSON/CSV
6) Validar JSON/JSONL
7) Abrir resumen técnico
0) Volver
"""


def _human_label(batch_id: str) -> str:
    return HUMAN_BATCH_LABELS.get(batch_id, batch_id)


def _batch_counts_from_selection(selected_doc: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in selected_doc.get("selected_batches") or []:
        if isinstance(item, dict):
            counts[str(item.get("batch_id") or "")] = int(item.get("record_count") or 0)
    return counts


def show_s0151_status(
    *,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
    canon_glob: str | None = None,
) -> int:
    print("Estado metadata técnica")
    if not manifest.exists():
        print("- patch vigente: no disponible")
        print("- acción sugerida: refrescar patch contra canon actual")
        return 1
    try:
        hash_doc = gate.s0151_hash_verification(
            manifest=manifest,
            canon_glob=canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        )
    except Exception as exc:  # noqa: BLE001 - operator-facing menu
        print(f"- patch vigente: inválido ({exc})")
        return 1
    print(f"- patch vigente: {'compatible' if hash_doc['all_hashes_match'] else 'requiere refresh'}")
    selected_path = gate.s0151_paths(admission_dir)["selected_batches"]
    if selected_path.exists():
        selected = gate.read_json(selected_path)
        counts = _batch_counts_from_selection(selected)
        print("- selección actual:")
        if counts:
            for batch_id, count in counts.items():
                print(f"  - {_human_label(batch_id)}: {count}")
        else:
            print("  - sin operaciones seleccionadas")
        if selected.get("operator_warnings"):
            print(f"- advertencias: {', '.join(selected['operator_warnings'])}")
    else:
        print("- selección actual: no definida")
    dry_path = gate.s0151_paths(admission_dir)["dry_run_report"]
    if dry_path.exists():
        report = gate.read_json(dry_path)
        print(f"- dry-run: {'bloqueado' if report.get('blocked') else 'listo'}")
        print(f"- operaciones listas: {report.get('admission_ready', 0)}")
        print(f"- operaciones bloqueadas: {report.get('blocked_records', 0)}")
    else:
        print("- dry-run: no ejecutado")
    apply_path = gate.s0151_paths(admission_dir)["apply_report"]
    if apply_path.exists():
        apply_report = gate.read_json(apply_path)
        print(f"- apply ejecutado: {'SÍ' if apply_report.get('apply_executed') else 'NO'}")
        print(f"- canon modificado: {'SÍ' if apply_report.get('canon_modified') else 'NO'}")
    else:
        print("- apply ejecutado: NO")
        print("- canon modificado: NO")
    return 0


def select_s0151_guided(
    selection: str | list[str],
    *,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
    selection_source: str = "guided_terminal",
) -> int:
    doc = gate.select_s0151_batches(
        selection,
        manifest=manifest,
        out_dir=admission_dir,
        selection_source=selection_source,
    )
    print("Selección guardada")
    counts = _batch_counts_from_selection(doc)
    for batch_id, count in counts.items():
        print(f"- {_human_label(batch_id)}: {count}")
    if doc.get("operator_warnings"):
        print(f"Advertencias: {', '.join(doc['operator_warnings'])}")
    if doc.get("blocked_batch_ids"):
        print("Selección bloqueada: incluye excluidos / requieren revisión.")
    if doc.get("invalid_batch_ids"):
        print("Selección bloqueada: hay opciones no disponibles en el patch actual.")
    print("Relaciones serán generadas: NO")
    return 0 if doc.get("valid") is True else 2


def select_s0151_recommended(
    *,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
) -> int:
    print("Selección recomendada:")
    print("- Código vigente verificado")
    print("- Código embebido")
    print("- Narrativa técnica")
    print("No incluye histórico/divergente, excluidos ni relaciones.")
    print("Esta selección agrega metadata técnica sin generar relaciones.")
    return select_s0151_guided("recommended", manifest=manifest, admission_dir=admission_dir, selection_source="recommended_preset")


def refresh_s0151_patch_from_menu(
    *,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    canon_glob: str | None = None,
) -> dict[str, Any]:
    source = refresh.resolve_source_patch(
        "auto",
        patch_preview=DEFAULT_OUT_DIR / "s0147_repo_metadata_patch_preview.jsonl",
        review_batches=DEFAULT_OUT_DIR / "s0147_repo_metadata_review_batches.json",
        patch_hashes=DEFAULT_OUT_DIR / "s0147_repo_metadata_patch_hashes.json",
        latest_manifest=manifest,
    )
    report = refresh.refresh_metadata_patch(
        patch_preview=Path(source["patch_preview"]),
        review_batches=Path(source["review_batches"]),
        patch_hashes=Path(source["patch_hashes"]),
        canon_glob=canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        out_dir=admission_dir,
        session="S0151",
        source_session=str(source["source_session"]),
        manifest_path=manifest,
        dry_run=True,
    )
    print("Patch actualizado.")
    print(f"- Operaciones preservadas: {report.get('operations_preserved')}")
    print(f"- Operaciones bloqueadas: {report.get('operations_blocked')}")
    print("- Manifest vigente actualizado.")
    return report


def _manifest_needs_refresh(manifest: Path, *, canon_glob: str | None = None) -> bool:
    if not manifest.exists():
        return True
    try:
        return not gate.s0151_hash_verification(
            manifest=manifest,
            canon_glob=canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        )["all_hashes_match"]
    except Exception:  # noqa: BLE001 - operator-facing menu
        return True


def _offer_refresh_if_needed(
    *,
    manifest: Path,
    admission_dir: Path,
    canon_glob: str | None,
) -> bool:
    if not _manifest_needs_refresh(manifest, canon_glob=canon_glob):
        return True
    print("El canon cambió desde que se generó el patch.")
    print("1) Refrescar patch contra canon actual")
    print("2) Ver diferencias")
    print("3) Cancelar")
    print("0) Volver")
    try:
        choice = input("Selección: ").strip()
    except EOFError:
        return False
    if choice == "1":
        refresh_s0151_patch_from_menu(admission_dir=admission_dir, manifest=manifest, canon_glob=canon_glob)
        return True
    if choice == "2":
        try:
            hash_doc = gate.s0151_hash_verification(manifest=manifest, canon_glob=canon_glob or gate.DEFAULT_CANON_GLOB)
            print("Diferencias detectadas:")
            for check in hash_doc["checks"]:
                if not check["match"]:
                    print(f"- {check['name']}: no coincide")
        except Exception as exc:  # noqa: BLE001
            print(f"No fue posible calcular diferencias: {exc}")
        return False
    return False


def run_s0151_gate_dry_run(
    *,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
    canon_glob: str | None = None,
    require_token: bool = False,
) -> int:
    selected = gate.s0151_paths(admission_dir)["selected_batches"]
    if not selected.exists():
        print("No hay selección guiada todavía.")
        return 2
    if require_token:
        selected_doc = gate.read_json(selected)
        counts = _batch_counts_from_selection(selected_doc)
        print("Vas a ejecutar dry-run de metadata.")
        print("Selección:")
        for batch_id, count in counts.items():
            print(f"- {_human_label(batch_id)}: {count}")
        print(f"Total operaciones: {selected_doc.get('selected_operation_count', 0)}")
        print("Canon será modificado: NO")
        print("Relaciones serán generadas: NO")
        print("Semantic_text será modificado: NO")
        print(f"Para continuar escribe:\n{gate.S0151_DRY_RUN_TOKEN}")
        try:
            token = input("Token: ").strip()
        except EOFError:
            token = ""
        if token != gate.S0151_DRY_RUN_TOKEN:
            print("Dry-run cancelado: token inválido.")
            return 2
    report = gate.run_s0151_dry_run(
        manifest=manifest,
        selected_batches=selected,
        canon_glob=canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        out_dir=admission_dir,
    )
    print("Dry-run ejecutado.")
    print(f"- Estado: {'bloqueado' if report.get('blocked') else 'listo'}")
    print(f"- Operaciones listas: {report.get('admission_ready')}")
    print(f"- Operaciones bloqueadas: {report.get('blocked_records')}")
    print("Relaciones generadas: NO")
    return 0 if report.get("blocked") is False else 2


def show_s0151_gate_report(admission_dir: Path = DEFAULT_S0151_OUT_DIR) -> int:
    path = gate.s0151_paths(admission_dir)["dry_run_report"]
    if not path.exists():
        print("No existe reporte dry-run S0151 todavía.")
        return 1
    report = gate.read_json(path)
    print("Resultado dry-run S0151")
    print(f"- estado: {'bloqueado' if report.get('blocked') else 'listo'}")
    print(f"- operaciones listas: {report.get('admission_ready')}")
    print(f"- operaciones bloqueadas: {report.get('blocked_records')}")
    print(f"- relaciones generadas: {'SÍ' if report.get('relations_generated') else 'NO'}")
    return 0


def apply_s0151_metadata_from_menu(
    *,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
    canon_glob: str | None = None,
    apply_token: str | None = None,
) -> int:
    if apply_token is None:
        print("Vas a MODIFICAR el canon JSONL.")
        print("Esto actualizará líneas existentes dentro de data/out/local/tiddlers_*.jsonl")
        print("No creará archivos JSON independientes por tiddler.")
        print("No generará relaciones.")
        print("No modificará semantic_text.")
        print("Backup y rollback serán creados antes del cambio.")
        print(f"Para confirmar escribe exactamente:\n{gate.S0151_APPLY_TOKEN}")
        try:
            apply_token = input("Token: ").strip()
        except EOFError:
            apply_token = ""
    report = gate.apply_s0151_metadata(
        manifest=manifest,
        dry_run_report_path=gate.s0151_paths(admission_dir)["dry_run_report"],
        selected_batches=gate.s0151_paths(admission_dir)["selected_batches"],
        canon_glob=canon_glob or str(REPO_ROOT / "data" / "out" / "local" / "tiddlers_*.jsonl"),
        out_dir=admission_dir,
        apply_token=apply_token,
    )
    print("Apply metadata S0151")
    print(f"- apply ejecutado: {'SÍ' if report.get('apply_executed') else 'NO'}")
    print(f"- canon modificado: {'SÍ' if report.get('canon_modified') else 'NO'}")
    if report.get("block_reasons"):
        print(f"- bloqueo: {', '.join(report['block_reasons'])}")
    return 0 if report.get("apply_executed") is True else 2


def rollback_s0151_metadata(admission_dir: Path = DEFAULT_S0151_OUT_DIR) -> int:
    report = gate.rollback_s0151_metadata(out_dir=admission_dir)
    print("Rollback metadata S0151")
    print(f"- rollback ejecutado: {'SÍ' if report.get('rollback_executed') else 'NO'}")
    return 0 if report.get("rollback_executed") is True else 2


def validate_s0151_outputs(
    *,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
) -> int:
    paths = gate.s0151_paths(admission_dir)
    json_paths = [
        manifest,
        paths["selected_batches"],
        paths["dry_run_report"],
        paths["apply_report"],
    ]
    jsonl_paths = [paths["ready"], paths["blocked"], paths["patch_preview"]]
    errors: list[str] = []
    for path in json_paths:
        if not path.exists():
            errors.append(f"missing:{_display(path)}")
            continue
        try:
            _load_json(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid_json:{_display(path)}:{exc}")
    for path in jsonl_paths:
        if not path.exists():
            errors.append(f"missing:{_display(path)}")
            continue
        try:
            _load_jsonl(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid_jsonl:{_display(path)}:{exc}")
    if errors:
        print("Validación con errores:")
        for error in errors:
            print(f"- {error}")
        return 2
    print("JSON/JSONL válidos.")
    return 0


def interactive_s0151_advanced(
    *,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
) -> int:
    while True:
        print(S0151_ADVANCED_HEADER)
        try:
            choice = input("Selección: ").strip()
        except EOFError:
            return 0
        if choice == "0":
            return 0
        if choice == "1":
            batches = gate.read_json(gate.s0151_manifest_paths(manifest)["review_batches"]).get("batches", {})
            for batch_id, batch in sorted(batches.items()):
                print(f"- {batch_id}: {batch.get('record_count')}")
        elif choice == "2":
            print(_stable_json(gate.read_json(gate.s0151_manifest_paths(manifest)["patch_hashes"])))
        elif choice == "3":
            print(gate.load_s0151_manifest(manifest).get("canon_before_sha256", ""))
        elif choice == "4":
            for row in gate.read_jsonl(gate.s0151_manifest_paths(manifest)["patch_preview"])[:100]:
                print(f"- {row.get('op_id')} -> {row.get('target_id')}")
        elif choice == "5":
            for key, path in {**gate.s0151_paths(admission_dir), "latest_manifest": manifest}.items():
                if key != "backups":
                    print(f"- {key}: {_display(path)}")
        elif choice == "6":
            validate_s0151_outputs(manifest=manifest, admission_dir=admission_dir)
        elif choice == "7":
            path = gate.s0151_paths(admission_dir)["summary"]
            if path.exists():
                print(path.read_text(encoding="utf-8"))
            else:
                print("No existe resumen técnico todavía.")
        else:
            print("Opción no reconocida")
        print()


def interactive_s0151_menu(
    *,
    manifest: Path = DEFAULT_LATEST_METADATA_PATCH_MANIFEST,
    admission_dir: Path = DEFAULT_S0151_OUT_DIR,
    canon_glob: str | None = None,
) -> int:
    while True:
        print(S0151_MENU_HEADER)
        try:
            choice = input("Selección: ").strip()
        except EOFError:
            return 0
        if choice == "0":
            return 0
        if choice == "1":
            show_s0151_status(manifest=manifest, admission_dir=admission_dir, canon_glob=canon_glob)
        elif choice == "2":
            select_s0151_recommended(manifest=manifest, admission_dir=admission_dir)
        elif choice == "3":
            print("Solo metadata fuerte para artefactos actuales verificados del repositorio.")
            select_s0151_guided("current_only", manifest=manifest, admission_dir=admission_dir, selection_source="current_only_preset")
        elif choice == "4":
            print("Metadata auxiliar para tiddlers que contienen código o mencionan referencias técnicas, sin convertirlos en artefactos de repositorio.")
            select_s0151_guided("auxiliary_only", manifest=manifest, admission_dir=admission_dir, selection_source="auxiliary_only_preset")
        elif choice == "5":
            print("1) Código vigente verificado")
            print("2) Código embebido")
            print("3) Narrativa técnica")
            print("4) Histórico/divergente")
            print("5) Generados")
            print("6) Excluidos / requieren revisión")
            raw = input("Escribe números separados por coma: ").strip()
            select_s0151_guided(raw, manifest=manifest, admission_dir=admission_dir, selection_source="guided_custom")
        elif choice == "6":
            refresh_s0151_patch_from_menu(admission_dir=admission_dir, manifest=manifest, canon_glob=canon_glob)
        elif choice == "7":
            if _offer_refresh_if_needed(manifest=manifest, admission_dir=admission_dir, canon_glob=canon_glob):
                run_s0151_gate_dry_run(manifest=manifest, admission_dir=admission_dir, canon_glob=canon_glob, require_token=True)
        elif choice == "8":
            show_s0151_gate_report(admission_dir)
        elif choice == "9":
            if _offer_refresh_if_needed(manifest=manifest, admission_dir=admission_dir, canon_glob=canon_glob):
                apply_s0151_metadata_from_menu(manifest=manifest, admission_dir=admission_dir, canon_glob=canon_glob)
        elif choice == "10":
            rollback_s0151_metadata(admission_dir)
        elif choice == "11":
            interactive_s0151_advanced(manifest=manifest, admission_dir=admission_dir)
        else:
            print("Opción no reconocida")
        print()


def option_repo_metadata_admission_menu() -> int:
    return interactive_s0151_menu()


MENU_HEADER = """S0148 repo metadata review menu
1) Ver resumen de patch preview
2) Ver lotes disponibles
3) Ver detalle de lote
4) Ver riesgos / excluidos
5) Aprobar batch por terminal
6) Rechazar batch
7) Diferir batch
8) Ejecutar compuerta dry-run con decisiones actuales
9) Ver ultimo reporte de compuerta
10) Ver hashes del patch
11) Ayuda / instrucciones de operador
0) Volver / salir
"""


def interactive_menu(
    out_dir: Path = DEFAULT_OUT_DIR,
    decision_dir: Path = DEFAULT_S0148_OUT_DIR,
    *,
    canon_glob: str | None = None,
    s0146_classification: Path | None = None,
) -> int:
    while True:
        print(MENU_HEADER)
        try:
            choice = input("Seleccion: ").strip()
        except EOFError:
            return 0
        if choice == "0":
            return 0
        if choice == "1":
            show_summary(out_dir)
        elif choice == "2":
            list_batches(out_dir)
        elif choice == "3":
            batch_id = input("Batch ID: ").strip()
            show_batch(batch_id, out_dir)
        elif choice == "4":
            show_risks(out_dir)
            show_excluded(out_dir)
        elif choice == "5":
            batch_id = input("Batch ID: ").strip()
            record_batch_decision(batch_id=batch_id, decision="approved", token=None, out_dir=out_dir, decision_dir=decision_dir)
        elif choice == "6":
            batch_id = input("Batch ID: ").strip()
            record_batch_decision(batch_id=batch_id, decision="rejected", token=None, out_dir=out_dir, decision_dir=decision_dir)
        elif choice == "7":
            batch_id = input("Batch ID: ").strip()
            record_batch_decision(batch_id=batch_id, decision="deferred", token=None, out_dir=out_dir, decision_dir=decision_dir)
        elif choice == "8":
            run_gate_dry_run(
                out_dir,
                decision_dir,
                canon_glob=canon_glob,
                s0146_classification=s0146_classification,
            )
        elif choice == "9":
            show_last_gate_report(decision_dir)
        elif choice == "10":
            show_hashes(out_dir)
        elif choice == "11":
            show_contract(out_dir)
        else:
            print("Opcion no reconocida")
        print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review S0147 repo metadata patch preview")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--decision-dir", default=str(DEFAULT_S0148_OUT_DIR))
    parser.add_argument("--admission-dir", default=str(DEFAULT_S0149_OUT_DIR))
    parser.add_argument("--summary", action="store_true", help="Show patch summary")
    parser.add_argument("--list-batches", action="store_true", help="List review batches")
    parser.add_argument("--show-batch", help="Show one batch by id")
    parser.add_argument("--show-excluded", action="store_true", help="Show excluded records")
    parser.add_argument("--show-risks", action="store_true", help="Show risk report")
    parser.add_argument("--show-hashes", action="store_true", help="Show patch hashes")
    parser.add_argument("--export-csv", action="store_true", help="Print CSV path and row count")
    parser.add_argument("--validate-dry-run", action="store_true", help="Validate dry-run invariants")
    parser.add_argument("--contract", action="store_true", help="Show menu contract")
    parser.add_argument("--approve-batch", help="Approve one batch with explicit terminal token")
    parser.add_argument("--reject-batch", help="Reject one batch with explicit terminal token")
    parser.add_argument("--defer-batch", help="Defer one batch with explicit terminal token")
    parser.add_argument("--decision-token", help="Explicit decision token; if omitted, prompt on terminal")
    parser.add_argument("--select-batches", help="Select S0149 metadata batches by id or comma-separated menu numbers")
    parser.add_argument("--run-gate-dry-run", action="store_true", help="Run S0148 or S0149 dry-run admission gate")
    parser.add_argument("--show-last-gate-report", action="store_true", help="Show latest S0148/S0149 gate report")
    parser.add_argument("--show-apply-status", action="store_true", help="Show S0149 metadata apply status")
    parser.add_argument("--apply-metadata", action="store_true", help="Apply S0149 metadata with explicit token")
    parser.add_argument("--apply-token", help="Exact S0149 apply token")
    parser.add_argument("--rollback-last-apply", action="store_true", help="Rollback latest S0149 metadata apply")
    parser.add_argument("--semantic-authority-preview", action="store_true", help="Run S0149 semantic_text authority-aware preview")
    parser.add_argument("--semantic-authority-generate", action="store_true", help="Run S0149 semantic_text authority-aware generate")
    parser.add_argument("--canon-glob", default=None, help="Canon glob for S0148 gate")
    parser.add_argument("--s0146-classification", default=None, help="S0146 classification path for S0148 gate")
    parser.add_argument("--interactive", action="store_true", help="Open interactive review menu")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    decision_dir = Path(args.decision_dir)
    admission_dir = Path(args.admission_dir)

    if args.summary:
        show_summary(out_dir)
        return 0
    if args.list_batches:
        list_batches(out_dir)
        return 0
    if args.show_batch:
        show_batch(args.show_batch, out_dir)
        return 0
    if args.show_excluded:
        show_excluded(out_dir)
        return 0
    if args.show_risks:
        show_risks(out_dir)
        return 0
    if args.show_hashes:
        show_hashes(out_dir)
        return 0
    if args.export_csv:
        export_csv(out_dir)
        return 0
    if args.validate_dry_run:
        return run_validate_dry_run(out_dir)
    if args.contract:
        show_contract(out_dir)
        return 0
    if args.approve_batch:
        return record_batch_decision(
            batch_id=args.approve_batch,
            decision="approved",
            token=args.decision_token,
            out_dir=out_dir,
            decision_dir=decision_dir,
        )
    if args.reject_batch:
        return record_batch_decision(
            batch_id=args.reject_batch,
            decision="rejected",
            token=args.decision_token,
            out_dir=out_dir,
            decision_dir=decision_dir,
        )
    if args.defer_batch:
        return record_batch_decision(
            batch_id=args.defer_batch,
            decision="deferred",
            token=args.decision_token,
            out_dir=out_dir,
            decision_dir=decision_dir,
        )
    if args.select_batches:
        return select_s0149_batches(args.select_batches, out_dir, admission_dir)
    if args.run_gate_dry_run:
        if should_use_s0149_gate(out_dir, admission_dir):
            return run_s0149_gate_dry_run(
                out_dir,
                admission_dir,
                canon_glob=args.canon_glob,
                s0146_classification=Path(args.s0146_classification) if args.s0146_classification else None,
            )
        return run_gate_dry_run(
            out_dir,
            decision_dir,
            canon_glob=args.canon_glob,
            s0146_classification=Path(args.s0146_classification) if args.s0146_classification else None,
        )
    if args.show_last_gate_report:
        if should_use_s0149_gate(out_dir, admission_dir):
            return show_s0149_gate_report(admission_dir)
        return show_last_gate_report(decision_dir)
    if args.show_apply_status:
        return show_s0149_apply_status(admission_dir)
    if args.apply_metadata:
        return apply_s0149_metadata_from_menu(
            out_dir,
            admission_dir,
            canon_glob=args.canon_glob,
            s0146_classification=Path(args.s0146_classification) if args.s0146_classification else None,
            apply_token=args.apply_token,
        )
    if args.rollback_last_apply:
        return rollback_s0149_metadata(admission_dir)
    if args.semantic_authority_preview:
        return run_semantic_authority("preview", canon_glob=args.canon_glob)
    if args.semantic_authority_generate:
        return run_semantic_authority("generate", canon_glob=args.canon_glob)
    if args.interactive:
        if should_use_s0149_gate(out_dir, admission_dir):
            return interactive_s0149_menu(
                out_dir,
                admission_dir,
                canon_glob=args.canon_glob,
                s0146_classification=Path(args.s0146_classification) if args.s0146_classification else None,
            )
        return interactive_menu(
            out_dir,
            decision_dir,
            canon_glob=args.canon_glob,
            s0146_classification=Path(args.s0146_classification) if args.s0146_classification else None,
        )

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
