#!/usr/bin/env python3
"""validate_source_fields_contract.py — S0133

Validador local no destructivo de source_fields por artifact_family.

Implementa el contrato formal definido en DT035.

Uso
---
  # Validar directorio completo (modo baseline, por defecto)
  python3 validate_source_fields_contract.py data/out/local/sessions/

  # Validar un archivo JSONL con nivel DT035 completo
  python3 validate_source_fields_contract.py --level dt035 \\
      data/out/local/pipeline/relations_candidates/rc_candidates.jsonl

  # Validar múltiples rutas con nivel family (incluye declared_* por familia)
  python3 validate_source_fields_contract.py --level family \\
      data/out/local/sessions/ data/out/local/pipeline/

  # Guardar reporte JSON
  python3 validate_source_fields_contract.py \\
      --report-json /tmp/report.json \\
      data/out/local/sessions/

  # Modo estricto legacy (campos TW históricos tratados como error)
  python3 validate_source_fields_contract.py --legacy-as-error \\
      data/out/local/sessions/

Comportamiento
--------------
  - Lee archivos .json y .jsonl dentro de las rutas indicadas.
  - No modifica ningún archivo revisado.
  - Sale con código 0 si no hay errores de contrato (puede haber warnings).
  - Sale con código 1 si hay al menos un ERROR de contrato.
  - Sale con código 2 si hay un error de ejecución del script.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from source_fields_contract import (  # noqa: E402
    ERROR,
    WARNING,
    validate_source_fields,
    summarize_issues,
)

REPO_ROOT = SCRIPT_DIR.parent

# ── Helpers ───────────────────────────────────────────────────────────────────

def _iter_records(path: Path) -> list[tuple[Path, int, dict[str, Any]]]:
    """Yield (file_path, line_number, record) from a JSON or JSONL file."""
    records = []
    if path.suffix == ".jsonl":
        try:
            with path.open(encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append((path, lineno, json.loads(line)))
                    except json.JSONDecodeError as e:
                        records.append((path, lineno, {"__parse_error__": str(e)}))
        except OSError as e:
            print(f"[WARN] No se pudo leer {path}: {e}", file=sys.stderr)
    else:
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for i, rec in enumerate(data, 1):
                    records.append((path, i, rec))
            else:
                records.append((path, 1, data))
        except (json.JSONDecodeError, OSError) as e:
            records.append((path, 1, {"__parse_error__": str(e)}))
    return records


def _collect_files(paths: list[Path]) -> list[Path]:
    """Expand paths to a flat list of .json and .jsonl files."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*.json")):
                files.append(f)
            for f in sorted(p.rglob("*.jsonl")):
                files.append(f)
        elif p.is_file():
            if p.suffix in (".json", ".jsonl"):
                files.append(p)
            else:
                print(f"[WARN] Ignorando {p}: extensión no soportada (.json o .jsonl).",
                      file=sys.stderr)
        else:
            print(f"[WARN] Ruta no encontrada: {p}", file=sys.stderr)
    return files


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ── Función principal de validación ──────────────────────────────────────────

def run_validation(
    input_paths: list[Path],
    *,
    level: str = "baseline",
    family_check: bool = False,
    strict_forbidden: bool = True,
    strict_status: bool = True,
    strict_path: bool = True,
    legacy_as_error: bool = False,
) -> dict[str, Any]:
    """Valida todos los archivos en input_paths y devuelve el reporte completo."""

    files = _collect_files(input_paths)
    total_records = 0
    valid_records = 0
    invalid_records = 0
    warning_only_records = 0
    errors_by_code: dict[str, int] = {}
    warnings_by_code: dict[str, int] = {}
    artifact_families: dict[str, int] = {}
    forbidden_fields: dict[str, int] = {}
    missing_required_fields: dict[str, int] = {}
    path_issues: list[str] = []
    file_results: list[dict[str, Any]] = []

    for fpath in files:
        for fpath2, lineno, record in _iter_records(fpath):
            total_records += 1

            if "__parse_error__" in record:
                invalid_records += 1
                file_results.append({
                    "file": _relative(fpath2),
                    "line": lineno,
                    "record_id": None,
                    "title": None,
                    "artifact_family": None,
                    "source_path": None,
                    "status": "parse_error",
                    "issues": [{"code": "PARSE", "severity": ERROR,
                                "message": record["__parse_error__"]}],
                })
                errors_by_code["PARSE"] = errors_by_code.get("PARSE", 0) + 1
                continue

            title = record.get("title", "")
            rec_id = record.get("id") or record.get("canonical_slug") or title or f"line:{lineno}"
            family = (
                record.get("artifact_family")
                or (record.get("source_fields") or {}).get("artifact_family")
                or ""
            )
            sp = (record.get("source_fields") or {}).get("source_path", "")

            if family:
                artifact_families[family] = artifact_families.get(family, 0) + 1

            issues = validate_source_fields(
                record,
                level=level,
                family_check=family_check,
                strict_forbidden=strict_forbidden,
                strict_status=strict_status,
                strict_path=strict_path,
                legacy_as_error=legacy_as_error,
            )

            has_errors = any(i.severity == ERROR for i in issues)
            has_warnings = any(i.severity == WARNING for i in issues)

            if has_errors:
                invalid_records += 1
                rec_status = "invalid"
            elif has_warnings:
                warning_only_records += 1
                rec_status = "warning"
                valid_records += 1
            else:
                valid_records += 1
                rec_status = "valid"

            for i in issues:
                if i.severity == ERROR:
                    errors_by_code[i.code] = errors_by_code.get(i.code, 0) + 1
                    if i.code == "SF006":
                        fname = i.field.replace("source_fields.", "")
                        forbidden_fields[fname] = forbidden_fields.get(fname, 0) + 1
                    if i.code in ("SF003", "SF004", "SF005"):
                        fname = i.field.replace("source_fields.", "")
                        missing_required_fields[fname] = missing_required_fields.get(fname, 0) + 1
                    if i.code == "SF009":
                        path_issues.append(f"{_relative(fpath2)}:{lineno} — {i.message}")
                elif i.severity == WARNING:
                    warnings_by_code[i.code] = warnings_by_code.get(i.code, 0) + 1
                    if i.code in ("SF003", "SF004", "SF005"):
                        fname = i.field.replace("source_fields.", "")
                        missing_required_fields[fname] = missing_required_fields.get(fname, 0) + 1

            file_results.append({
                "file": _relative(fpath2),
                "line": lineno,
                "record_id": rec_id,
                "title": title[:120] if title else None,
                "artifact_family": family or None,
                "source_path": sp or None,
                "status": rec_status,
                "issues": summarize_issues(issues)["issues"] if issues else [],
            })

    checked_paths = [_relative(p) for p in files]

    return {
        "session_id": "m04-s0133",
        "contract_version": "DT035-v1",
        "validation_level": level,
        "checked_paths": checked_paths,
        "total_files_checked": len(files),
        "total_records_checked": total_records,
        "valid_records": valid_records,
        "invalid_records": invalid_records,
        "warning_only_records": warning_only_records,
        "errors_by_code": errors_by_code,
        "warnings_by_code": warnings_by_code,
        "artifact_families_detected": artifact_families,
        "forbidden_fields_detected": forbidden_fields,
        "missing_required_fields": missing_required_fields,
        "path_safety_issues": path_issues,
        "recommendations": _build_recommendations(
            errors_by_code, warnings_by_code, artifact_families, missing_required_fields
        ),
        "records": file_results,
    }


def _build_recommendations(
    errors: dict[str, int],
    warnings: dict[str, int],
    families: dict[str, int],
    missing: dict[str, int],
) -> list[str]:
    recs = []
    if errors.get("SF001"):
        recs.append(
            "SF001: Agregar source_fields con mínimos DT035 v1 a los artefactos de sesión "
            "antes de su admisión canónica."
        )
    if errors.get("SF002"):
        recs.append("SF002: source_fields debe ser un objeto dict, no string ni lista.")
    if errors.get("SF003") or errors.get("SF004"):
        recs.append(
            "SF003/SF004: Completar los campos mínimos requeridos en source_fields "
            "(artifact_family, canonical_status, session_origin, source_path, provenance_ref)."
        )
    if errors.get("SF006"):
        recs.append(
            "SF006: Eliminar campos prohibidos de source_fields. "
            "Ver DT035 §8 para la lista completa."
        )
    if warnings.get("SF007"):
        recs.append(
            "SF007 (WARNING): Migrar campos legados TW (type, tags, created, modified) "
            "a sus equivalentes DT035 (source_type, source_tags_json, source_created, source_modified)."
        )
    if errors.get("SF009"):
        recs.append(
            "SF009: Corregir rutas source_path absolutas o con '..' para garantizar "
            "portabilidad y evitar path traversal."
        )
    if errors.get("SF010"):
        recs.append(
            "SF010: Resolver discrepancias entre artifact_family superior y source_fields.artifact_family."
        )
    if warnings.get("SF004"):
        recs.append(
            "SF004 (WARNING): Completar los campos DT035 v1 extendidos para nuevos artefactos "
            "(source_title, source_type, source_created, source_modified, source_tags_json, document_key)."
        )
    if not recs:
        recs.append("No se detectaron problemas bloqueantes de contrato.")
    return recs


# ── Escritura de reportes ─────────────────────────────────────────────────────

def write_json_report(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compact = {k: v for k, v in report.items() if k != "records"}
    compact["records_count"] = len(report.get("records", []))
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(compact, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Reporte JSON → {out_path}", file=sys.stderr)


def write_csv_report(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "record_id", "title", "artifact_family", "source_path",
        "status", "issue_code", "severity", "message", "recommendation",
    ]
    rows = []
    for rec in report.get("records", []):
        if not rec.get("issues"):
            rows.append({
                "record_id": rec.get("record_id", ""),
                "title": rec.get("title", ""),
                "artifact_family": rec.get("artifact_family", ""),
                "source_path": rec.get("source_path", ""),
                "status": rec.get("status", ""),
                "issue_code": "",
                "severity": "",
                "message": "",
                "recommendation": "",
            })
        else:
            for iss in rec["issues"]:
                rows.append({
                    "record_id": rec.get("record_id", ""),
                    "title": rec.get("title", ""),
                    "artifact_family": rec.get("artifact_family", ""),
                    "source_path": rec.get("source_path", ""),
                    "status": rec.get("status", ""),
                    "issue_code": iss.get("code", ""),
                    "severity": iss.get("severity", ""),
                    "message": iss.get("message", ""),
                    "recommendation": iss.get("recommendation", ""),
                })
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] Reporte CSV → {out_path}", file=sys.stderr)


def write_md_summary(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = report["total_records_checked"]
    valid = report["valid_records"]
    invalid = report["invalid_records"]
    warn_only = report["warning_only_records"]
    families = report["artifact_families_detected"]
    errors_by_code = report["errors_by_code"]
    warnings_by_code = report["warnings_by_code"]
    missing = report["missing_required_fields"]
    forbidden = report["forbidden_fields_detected"]
    recs = report["recommendations"]
    paths = report["checked_paths"]

    lines = [
        "# Reporte de validación source_fields — S0133",
        "",
        f"**Sesión:** `m04-s0133`  ",
        f"**Contrato:** `DT035-v1`  ",
        f"**Nivel de validación:** `{report['validation_level']}`",
        "",
        "## Resumen de validación",
        "",
        f"| Métrica | Valor |",
        f"|---------|-------|",
        f"| Total registros revisados | {total} |",
        f"| Registros válidos (sin errores) | {valid} |",
        f"| Registros con errores bloqueantes | {invalid} |",
        f"| Registros con solo warnings | {warn_only} |",
        f"| Total archivos revisados | {report['total_files_checked']} |",
        "",
        "## Rutas revisadas",
        "",
    ]
    for p in paths[:20]:
        lines.append(f"- `{p}`")
    if len(paths) > 20:
        lines.append(f"- *(y {len(paths) - 20} más)*")
    lines.append("")

    lines += [
        "## artifact_family detectados",
        "",
        "| artifact_family | Registros |",
        "|-----------------|----------:|",
    ]
    for fam, cnt in sorted(families.items(), key=lambda x: -x[1]):
        lines.append(f"| `{fam}` | {cnt} |")
    if not families:
        lines.append("| *(ninguno)* | 0 |")
    lines.append("")

    lines += [
        "## Errores de contrato (bloqueantes)",
        "",
    ]
    if errors_by_code:
        lines += [
            "| Código | Ocurrencias |",
            "|--------|------------:|",
        ]
        for code, cnt in sorted(errors_by_code.items()):
            lines.append(f"| `{code}` | {cnt} |")
    else:
        lines.append("No se detectaron errores bloqueantes.")
    lines.append("")

    lines += [
        "## Advertencias (no bloqueantes)",
        "",
    ]
    if warnings_by_code:
        lines += [
            "| Código | Ocurrencias |",
            "|--------|------------:|",
        ]
        for code, cnt in sorted(warnings_by_code.items()):
            lines.append(f"| `{code}` | {cnt} |")
    else:
        lines.append("No se detectaron advertencias.")
    lines.append("")

    if missing:
        lines += [
            "## Campos mínimos ausentes más frecuentes",
            "",
            "| Campo | Ocurrencias |",
            "|-------|------------:|",
        ]
        for fld, cnt in sorted(missing.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"| `{fld}` | {cnt} |")
        lines.append("")

    if forbidden:
        lines += [
            "## Campos prohibidos detectados en source_fields",
            "",
            "| Campo | Ocurrencias |",
            "|-------|------------:|",
        ]
        for fld, cnt in sorted(forbidden.items(), key=lambda x: -x[1]):
            lines.append(f"| `{fld}` | {cnt} |")
        lines.append("")

    lines += [
        "## Recomendaciones",
        "",
    ]
    for rec in recs:
        lines.append(f"- {rec}")
    lines.append("")

    lines += [
        "## Qué queda pendiente",
        "",
        "- Backfill de campos DT035 v1 extendidos en artefactos históricos (S0134+).",
        "- Integración del validador en el evaluador de admisibilidad relacional.",
        "- Validación de campos `declared_*` por familia al generar nuevos artefactos.",
        "- Generación experimental de `source_fields` enriquecidos desde corpus real.",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Resumen Markdown → {out_path}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validador local no destructivo de source_fields por artifact_family (DT035 v1).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Archivos .json/.jsonl o directorios a revisar.",
    )
    p.add_argument(
        "--level",
        choices=["baseline", "dt035", "family"],
        default="baseline",
        help=(
            "Nivel de validación: "
            "'baseline' (5 campos mínimos S0133), "
            "'dt035' (11 campos DT035 v1), "
            "'family' (dt035 + declared_* por familia). "
            "Default: baseline."
        ),
    )
    p.add_argument(
        "--legacy-as-error",
        action="store_true",
        default=False,
        help="Tratar campos legados TW (type, tags, created, modified) como ERROR en lugar de WARNING.",
    )
    p.add_argument(
        "--no-strict-forbidden",
        action="store_true",
        default=False,
        help="Degradar campos prohibidos a WARNING en vez de ERROR.",
    )
    p.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="Ruta donde guardar el reporte JSON completo.",
    )
    p.add_argument(
        "--report-csv",
        type=Path,
        default=None,
        help="Ruta donde guardar el reporte CSV.",
    )
    p.add_argument(
        "--report-md",
        type=Path,
        default=None,
        help="Ruta donde guardar el resumen Markdown.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suprimir salida de progreso; solo mostrar errores y el resumen final.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.quiet:
        print(
            f"[validate_source_fields_contract] nivel={args.level} "
            f"rutas={[str(p) for p in args.paths]}",
            file=sys.stderr,
        )

    report = run_validation(
        args.paths,
        level=args.level,
        strict_forbidden=not args.no_strict_forbidden,
        legacy_as_error=args.legacy_as_error,
    )

    # Escribir reportes opcionales
    if args.report_json:
        write_json_report(report, args.report_json)
    if args.report_csv:
        write_csv_report(report, args.report_csv)
    if args.report_md:
        write_md_summary(report, args.report_md)

    # Siempre imprimir resumen en stdout
    total = report["total_records_checked"]
    valid = report["valid_records"]
    invalid = report["invalid_records"]
    warn_only = report["warning_only_records"]
    errors_by_code = report["errors_by_code"]
    warnings_by_code = report["warnings_by_code"]

    print(
        f"\n=== source_fields contract validation ({args.level}) ===\n"
        f"  Archivos revisados : {report['total_files_checked']}\n"
        f"  Registros revisados: {total}\n"
        f"  Válidos            : {valid}\n"
        f"  Con errores        : {invalid}\n"
        f"  Solo warnings      : {warn_only}\n"
    )

    if errors_by_code:
        print("Errores por código:")
        for code, cnt in sorted(errors_by_code.items()):
            print(f"  {code}: {cnt}")
    if warnings_by_code:
        print("Advertencias por código:")
        for code, cnt in sorted(warnings_by_code.items()):
            print(f"  {code}: {cnt}")

    print("\nRecomendaciones:")
    for rec in report["recommendations"]:
        print(f"  - {rec}")

    if invalid > 0:
        print(f"\n[FAIL] {invalid} registros con errores de contrato.", file=sys.stderr)
        return 1

    print("\n[OK] No se detectaron errores bloqueantes de contrato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
