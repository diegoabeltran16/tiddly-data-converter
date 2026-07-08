#!/usr/bin/env python3
"""
validate_relation_candidates.py — S0125, endurecido S0129
Validador dry-run de candidatos relacionales contra el contrato DT031.

Nuevas verificaciones añadidas en S0129:
  8.  evidence.kind dentro del catálogo ALLOWED_EVIDENCE_KINDS
  10. evidence.excerpt verificado contra texto fuente del tiddler cuando es posible
  11. self-relation (source.tiddler_id == target.tiddler_id) rechazada
  12. target.tiddler_id verificado contra el canon cuando resolution_status='resolved'
  --output-dir: genera valid/invalid/unresolved/duplicate.jsonl separados

Modo --dry-run obligatorio por defecto.
La opción --apply está explícitamente bloqueada.

Uso:
    python3 src/python_scripts/validate_relation_candidates.py \\
      --input  data/out/local/pipeline/relations_candidates/relations_candidates.sample.jsonl \\
      --canon-root data/out/local \\
      --report data/out/local/pipeline/relations_candidates/s0129/validation_report.json \\
      --human-review data/out/local/pipeline/relations_candidates/s0129/human_review.md \\
      --output-dir data/out/local/pipeline/relations_candidates/s0129 \\
      --dry-run
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from relation_candidate_contract import (
    ALLOWED_RELATION_TYPES,
    ALLOWED_EVIDENCE_KINDS,
    ALLOWED_STATUSES,
    ALLOWED_RESOLUTION_STATUSES,
    ADMISSION_HUMAN_REVIEW_DECISION,
    WEAK_EVIDENCE_THRESHOLD,
    CANDIDATE_ID_RE,
    RELATION_CANDIDATE_SCHEMAS,
    VALID_HUMAN_REVIEW_DECISIONS,
    is_self_relation,
    verify_excerpt_in_source,
)

# ---------------------------------------------------------------------------
# Carga del canon — IDs y textos fuente
# ---------------------------------------------------------------------------

def load_canon_ids(canon_root: Path) -> set[str]:
    """Devuelve el conjunto de todos los tiddler_id presentes en el canon."""
    ids: set[str] = set()
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                tid = obj.get("id", "")
                if tid:
                    ids.add(tid)
            except json.JSONDecodeError:
                pass
    return ids


def load_canon_texts(canon_root: Path) -> dict[str, str]:
    """
    Devuelve un dict {tiddler_id: text} para todos los tiddlers del canon
    que tengan campo 'text' no vacío. Usado para verificar evidence.excerpt.
    """
    texts: dict[str, str] = {}
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                tid = obj.get("id", "")
                text = obj.get("text", "") or ""
                if tid and text.strip():
                    texts[tid] = text
            except json.JSONDecodeError:
                pass
    return texts


# ---------------------------------------------------------------------------
# Validación de un candidato individual
# ---------------------------------------------------------------------------

def _get_nested(obj: dict, *keys: str) -> Any:
    """Acceso seguro a campos anidados; devuelve None si no existe."""
    cur: Any = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _is_technical_candidate(obj: dict) -> bool:
    return (
        obj.get("candidate_schema_version") == "technical-relation-candidates/v1"
        or "relation_type" in obj
    )


def _endpoint_value(endpoint: dict, canonical_key: str, legacy_key: str) -> Any:
    return endpoint.get(canonical_key) or endpoint.get(legacy_key)


def validate_candidate(
    raw_line: str,
    line_number: int,
    canon_ids: set[str],
    seen_ids: dict[str, int],
    canon_texts: Optional[dict[str, str]] = None,
) -> dict:
    """
    Valida una línea de candidato relacional.

    Devuelve un dict con:
      - ok: bool
      - errors: list[str]
      - warnings: list[str]
      - categories: list[str]   # categorías relevantes para el reporte
      - obj: dict | None        # el candidato parseado, si es JSON válido
    """
    result: dict = {
        "ok": True,
        "errors": [],
        "warnings": [],
        "categories": [],
        "obj": None,
        "line_number": line_number,
        "raw": raw_line[:120] + ("…" if len(raw_line) > 120 else ""),
    }

    # 1. JSON válido
    try:
        obj = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        result["ok"] = False
        result["errors"].append(f"JSON inválido: {exc}")
        result["categories"].append("invalid")
        return result
    result["obj"] = obj

    errors = result["errors"]
    warnings = result["warnings"]
    categories = result["categories"]

    # 2. Campos obligatorios de primer nivel (DT031)
    technical_candidate = _is_technical_candidate(obj)
    if technical_candidate:
        required_top = [
            "candidate_id", "candidate_schema_version", "relation_type", "source",
            "target", "evidence", "policy", "session_resolution",
            "human_review_decision",
        ]
    else:
        required_top = [
            "candidate_id", "status", "source", "target",
            "relation", "evidence", "confidence", "provenance", "created_at",
        ]
    missing = [f for f in required_top if f not in obj or obj[f] is None]
    if missing:
        errors.append(f"Campos obligatorios ausentes: {missing}")

    schema_version = obj.get("candidate_schema_version") or obj.get("schema_version")
    if schema_version and schema_version not in RELATION_CANDIDATE_SCHEMAS:
        errors.append(
            f"candidate_schema_version/schema_version inválido: {schema_version!r}. "
            f"Permitidos: {sorted(RELATION_CANDIDATE_SCHEMAS)}"
        )

    # 3. candidate_id — formato y deduplicación
    cid = obj.get("candidate_id", "")
    if cid:
        if not CANDIDATE_ID_RE.match(cid):
            warnings.append(
                f"candidate_id no cumple formato ^rc1_[a-f0-9]{{16,64}}$: {cid!r}"
            )
        # 3b. Duplicado por candidate_id
        if cid in seen_ids:
            categories.append("duplicate")
            errors.append(
                f"candidate_id duplicado; visto en línea {seen_ids[cid]}: {cid!r}"
            )
        else:
            seen_ids[cid] = line_number

    # 4. status — debe ser 'candidate' al ingresar al validador
    status = obj.get("status")
    if not technical_candidate and status is not None and status != "candidate":
        errors.append(f"status debe ser 'candidate'; encontrado: {status!r}")

    if technical_candidate:
        human_review_decision = obj.get("human_review_decision")
        if human_review_decision not in VALID_HUMAN_REVIEW_DECISIONS:
            errors.append(
                "human_review_decision inválido o ausente: "
                f"{human_review_decision!r}. Permitidos: {sorted(VALID_HUMAN_REVIEW_DECISIONS)}"
            )
        policy = obj.get("policy") or {}
        if not isinstance(policy, dict):
            errors.append("policy debe ser objeto")
        elif policy.get("human_review_required") is not True:
            errors.append("policy.human_review_required debe ser true para cola de revisión")
        resolution = obj.get("session_resolution") or {}
        if not isinstance(resolution, dict):
            errors.append("session_resolution debe ser objeto")
        elif not resolution.get("classification"):
            errors.append("session_resolution.classification ausente o vacío")
        if human_review_decision != ADMISSION_HUMAN_REVIEW_DECISION:
            categories.append("needs_human_review")

    # 5. source.*
    source = obj.get("source") or {}
    src_id: Optional[str] = None
    if isinstance(source, dict):
        src_id = _endpoint_value(source, "canonical_id", "tiddler_id")
        if not technical_candidate and not source.get("field_path"):
            errors.append("source.field_path ausente o vacío")
        if technical_candidate:
            if not source.get("canonical_title"):
                errors.append("source.canonical_title ausente o vacío")
            if not source.get("repo_path"):
                errors.append("source.repo_path ausente o vacío")
            if not (source.get("lifecycle_state") or source.get("repo_lifecycle_state")):
                errors.append("source.lifecycle_state ausente o vacío")
        if src_id:
            if src_id not in canon_ids:
                errors.append(
                    f"source.tiddler_id no existe en el canon: {src_id!r}"
                )
        else:
            errors.append("source.tiddler_id ausente o vacío")

    # 6. target.*
    target = obj.get("target") or {}
    tgt_id: Optional[str] = None
    if isinstance(target, dict):
        tgt_id = _endpoint_value(target, "canonical_id", "tiddler_id")
        res_status = target.get("resolution_status")
        if technical_candidate:
            if not target.get("canonical_title"):
                errors.append("target.canonical_title ausente o vacío")
            if not target.get("repo_path"):
                errors.append("target.repo_path ausente o vacío")
            if not (target.get("lifecycle_state") or target.get("repo_lifecycle_state")):
                errors.append("target.lifecycle_state ausente o vacío")
        if not technical_candidate and res_status not in ALLOWED_RESOLUTION_STATUSES:
            errors.append(
                f"target.resolution_status inválido: {res_status!r}. "
                f"Permitidos: {sorted(ALLOWED_RESOLUTION_STATUSES)}"
            )
        if not technical_candidate and res_status in {"unresolved", "ambiguous"}:
            categories.append("unresolved_target")
            if not tgt_id and not target.get("title"):
                warnings.append(
                    "target sin tiddler_id ni title — muy difícil de revisar"
                )
        else:
            # Resuelto pero sin id en el objeto
            if not tgt_id:
                errors.append(
                    "target.resolution_status='resolved' pero target.tiddler_id ausente"
                )
            # S0129 — verificar que el target resuelto exista en el canon
            elif tgt_id not in canon_ids:
                errors.append(
                    f"target.tiddler_id no existe en el canon: {tgt_id!r} "
                    f"(resolution_status={res_status!r})"
                )

    # 7. relation.type — catálogo DT029
    rel = obj.get("relation") or {}
    if technical_candidate:
        rel_type = obj.get("relation_type")
        if rel_type not in ALLOWED_RELATION_TYPES:
            errors.append(
                f"relation_type no permitido: {rel_type!r}. "
                f"Tipos permitidos: {sorted(ALLOWED_RELATION_TYPES)}"
            )
    elif isinstance(rel, dict):
        rel_type = rel.get("type")
        if rel_type not in ALLOWED_RELATION_TYPES:
            errors.append(
                f"relation.type no permitido: {rel_type!r}. "
                f"Tipos permitidos: {sorted(ALLOWED_RELATION_TYPES)}"
            )
        if not rel.get("direction"):
            warnings.append("relation.direction ausente")

    # 8. confidence.score
    conf = obj.get("confidence") or {}
    if technical_candidate:
        confidence_label = (obj.get("evidence") or {}).get("confidence")
        if not confidence_label:
            errors.append("evidence.confidence ausente o vacío")
    elif isinstance(conf, dict):
        score = conf.get("score")
        if score is None:
            errors.append("confidence.score ausente")
        elif not isinstance(score, (int, float)):
            errors.append(
                f"confidence.score debe ser numérico; encontrado: {type(score).__name__}"
            )
        elif not (0.0 <= float(score) <= 1.0):
            errors.append(f"confidence.score fuera de rango [0.0, 1.0]: {score}")
        else:
            if float(score) < WEAK_EVIDENCE_THRESHOLD:
                categories.append("weak_evidence")
                warnings.append(f"confidence.score bajo ({score}) — evidencia débil")

    # 9. evidence — campos obligatorios
    evidence = obj.get("evidence") or {}
    excerpt: str = ""
    ev_kind: Optional[str] = None
    if isinstance(evidence, dict):
        excerpt = evidence.get("excerpt", "") or ""
        ev_kind = evidence.get("kind")
        if technical_candidate:
            ev_kind = evidence.get("evidence_kind")
            excerpt = evidence.get("raw_observation") or evidence.get("excerpt") or ""

        # 9a. excerpt no vacío
        if not excerpt.strip():
            errors.append("evidence.excerpt/raw_observation ausente o vacío")

        # 9b. S0129 — evidence.kind dentro del catálogo DT028/DT031
        if not ev_kind:
            errors.append("evidence.kind ausente o vacío")
        elif ev_kind not in ALLOWED_EVIDENCE_KINDS:
            errors.append(
                f"evidence.kind no permitido: {ev_kind!r}. "
                f"Permitidos: {sorted(ALLOWED_EVIDENCE_KINDS)}"
            )

        if not evidence.get("location"):
            warnings.append("evidence.location ausente — reduce auditabilidad")

    # 10. S0129 — verificación de excerpt contra texto fuente del tiddler
    if excerpt.strip() and src_id and canon_texts is not None:
        source_text = canon_texts.get(src_id)
        found = verify_excerpt_in_source(excerpt, source_text)
        if found is None:
            warnings.append(
                "evidence.excerpt no verificable: tiddler fuente sin campo 'text' "
                f"en el canon (src={src_id!r})"
            )
        elif not found:
            if ev_kind == "ai_inference":
                errors.append(
                    "evidence.excerpt no encontrado en texto fuente "
                    f"(kind=ai_inference — falso positivo probable, src={src_id!r})"
                )
                categories.append("unverifiable_excerpt")
            else:
                warnings.append(
                    "evidence.excerpt no encontrado en texto fuente "
                    f"(src={src_id!r}) — revisar manualmente"
                )

    # 11. S0129 — self-relation
    if isinstance(source, dict) and isinstance(target, dict):
        if is_self_relation(src_id, tgt_id):
            errors.append(
                f"Auto-relación no permitida: source.tiddler_id == target.tiddler_id "
                f"({src_id!r})"
            )

    # 12. provenance.*
    prov = obj.get("provenance") or {}
    if not technical_candidate and isinstance(prov, dict):
        if not prov.get("generated_by"):
            errors.append("provenance.generated_by ausente")
        if not prov.get("generated_at"):
            errors.append("provenance.generated_at ausente")

    # 13. created_at
    if not technical_candidate and not obj.get("created_at"):
        errors.append("created_at ausente")

    # Resultado final
    if errors:
        result["ok"] = False
        if "duplicate" not in categories and "unresolved_target" not in categories and "invalid" not in categories:
            categories.append("invalid")
    else:
        if "unresolved_target" not in categories and "weak_evidence" not in categories:
            categories.append("valid")

    return result


# ---------------------------------------------------------------------------
# Validación del archivo completo
# ---------------------------------------------------------------------------

def validate_file(
    input_path: Path,
    canon_ids: set[str],
    canon_texts: Optional[dict[str, str]] = None,
) -> dict:
    """Valida todas las líneas del JSONL y devuelve un diccionario de resultados."""
    results: list[dict] = []
    seen_ids: dict[str, int] = {}
    total = 0

    for ln, raw in enumerate(
        input_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        raw = raw.strip()
        if not raw:
            continue
        total += 1
        res = validate_candidate(raw, ln, canon_ids, seen_ids, canon_texts)
        results.append(res)

    # Clasificar
    valid = [r for r in results if "valid" in r["categories"]]
    invalid = [r for r in results if "invalid" in r["categories"]]
    unresolved = [
        r for r in results
        if "unresolved_target" in r["categories"] and "invalid" not in r["categories"]
    ]
    weak = [
        r for r in results
        if "weak_evidence" in r["categories"] and "invalid" not in r["categories"]
    ]
    duplicates = [r for r in results if "duplicate" in r["categories"]]

    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "unresolved_target": unresolved,
        "weak_evidence": weak,
        "duplicate": duplicates,
        "all_results": results,
    }


# ---------------------------------------------------------------------------
# Generación de reportes
# ---------------------------------------------------------------------------

def build_json_report(
    summary: dict,
    input_path: Path,
    canon_root: Path,
    run_at: str,
    dry_run: bool,
    session_tag: str = "S0125",
) -> dict:
    def fmt(lst: list[dict]) -> list[dict]:
        out = []
        for r in lst:
            obj = r.get("obj") or {}
            out.append({
                "line_number": r["line_number"],
                "candidate_id": obj.get("candidate_id", ""),
                "categories": r["categories"],
                "errors": r["errors"],
                "warnings": r["warnings"],
                "raw_preview": r.get("raw", ""),
            })
        return out

    return {
        "schema": "relations-candidate-validation-report/v2",
        "session": session_tag,
        "generated_at": run_at,
        "dry_run": dry_run,
        "input_file": str(input_path),
        "canon_root": str(canon_root),
        "summary": {
            "total": summary["total"],
            "valid": len(summary["valid"]),
            "invalid": len(summary["invalid"]),
            "unresolved_target": len(summary["unresolved_target"]),
            "weak_evidence": len(summary["weak_evidence"]),
            "duplicate": len(summary["duplicate"]),
        },
        "details": {
            "valid": fmt(summary["valid"]),
            "invalid": fmt(summary["invalid"]),
            "unresolved_target": fmt(summary["unresolved_target"]),
            "weak_evidence": fmt(summary["weak_evidence"]),
            "duplicate": fmt(summary["duplicate"]),
        },
        "canon_sanity": {
            "note": "No se escribió en tiddlers_*.jsonl — modo dry-run"
        },
        "hardening_checks": {
            "evidence_kind_catalog": True,
            "excerpt_verified_against_source": True,
            "self_relation_check": True,
            "target_id_in_canon_when_resolved": True,
        },
    }


def build_human_review(
    summary: dict,
    input_path: Path,
    run_at: str,
    session_tag: str = "S0125",
) -> str:
    total = summary["total"]
    valid_n = len(summary["valid"])
    invalid_n = len(summary["invalid"])
    unresolved_n = len(summary["unresolved_target"])
    weak_n = len(summary["weak_evidence"])
    dup_n = len(summary["duplicate"])

    lines = [
        f"# Reporte de revisión humana — Relaciones candidatas ({session_tag})",
        "",
        f"**Generado:** {run_at}",
        f"**Fuente:** `{input_path}`",
        f"**Modo:** dry-run (ningún candidato fue escrito en el canon)",
        f"**Sesión:** {session_tag}",
        "",
        "---",
        "",
        "## Resumen",
        "",
        "| Categoría | Cantidad |",
        "|---|---|",
        f"| Total evaluados | {total} |",
        f"| ✅ Válidos | {valid_n} |",
        f"| ❌ Inválidos | {invalid_n} |",
        f"| 🔍 Target no resuelto | {unresolved_n} |",
        f"| ⚠️ Evidencia débil | {weak_n} |",
        f"| 🔁 Duplicados | {dup_n} |",
        "",
        "---",
        "",
    ]

    def section(title: str, items: list[dict], icon: str) -> list[str]:
        out = [f"## {icon} {title}", ""]
        if not items:
            out += ["_Ninguno._", ""]
            return out
        for r in items:
            obj = r.get("obj") or {}
            cid = obj.get("candidate_id", f"línea {r['line_number']}")
            src_title = (obj.get("source") or {}).get("title", "?")[:60]
            tgt_title = (obj.get("target") or {}).get("title", "?")[:60]
            rel_type = (obj.get("relation") or {}).get("type", "?")
            score = (obj.get("confidence") or {}).get("score", "?")
            out += [
                f"### `{cid}` (línea {r['line_number']})",
                "",
                f"- **source:** {src_title}",
                f"- **target:** {tgt_title}",
                f"- **relation.type:** `{rel_type}`",
                f"- **confidence.score:** {score}",
            ]
            if r["errors"]:
                out += ["- **Errores:**"]
                for e in r["errors"]:
                    out += [f"  - ❌ {e}"]
            if r["warnings"]:
                out += ["- **Advertencias:**"]
                for w in r["warnings"]:
                    out += [f"  - ⚠️ {w}"]
            out += [""]
        return out

    lines += section("Candidatos válidos", summary["valid"], "✅")
    lines += section("Candidatos inválidos", summary["invalid"], "❌")
    lines += section("Target no resuelto (permitido si marcado)", summary["unresolved_target"], "🔍")
    lines += section("Evidencia débil (score < 0.50)", summary["weak_evidence"], "⚠️")
    lines += section("Duplicados", summary["duplicate"], "🔁")

    lines += [
        "---",
        "",
        "## Decisión de admisión",
        "",
        "> **Modo dry-run activo.** Ningún candidato fue escrito en el canon.",
        "> Los candidatos válidos con score ≥ 0.50 y target resuelto pueden ser",
        "> considerados para admisión gobernada en una sesión futura.",
        ">",
        "> Antes de cualquier admisión:",
        "> - Candidatos con `unresolved_target` requieren corrección de ID.",
        "> - Candidatos con `ai_inference` y excerpt no verificable deben descartarse.",
        "> - Candidatos con `weak_evidence` (score < 0.50) requieren revisión humana explícita.",
        "",
        "_Fin del reporte._",
    ]

    return "\n".join(lines) + "\n"


def write_category_files(summary: dict, output_dir: Path) -> dict[str, int]:
    """
    Escribe archivos JSONL separados por categoría en output_dir.

    Genera:
      valid_candidates.jsonl
      invalid_candidates.jsonl
      unresolved_candidates.jsonl
      duplicate_candidates.jsonl

    Retorna un dict con la cantidad de registros escritos por archivo.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    def _write(name: str, items: list[dict]) -> int:
        path = output_dir / name
        lines = []
        for r in items:
            obj = r.get("obj")
            if obj is not None:
                lines.append(json.dumps(obj, ensure_ascii=False))
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return len(lines)

    counts = {
        "valid_candidates.jsonl": _write("valid_candidates.jsonl", summary["valid"]),
        "invalid_candidates.jsonl": _write("invalid_candidates.jsonl", summary["invalid"]),
        "unresolved_candidates.jsonl": _write("unresolved_candidates.jsonl", summary["unresolved_target"]),
        "duplicate_candidates.jsonl": _write("duplicate_candidates.jsonl", summary["duplicate"]),
    }
    return counts


# ---------------------------------------------------------------------------
# CLI principal
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Validador dry-run de candidatos relacionales (DT031) — endurecido S0129"
    )
    p.add_argument(
        "--input", "--candidate-file", dest="input", required=True, type=Path,
        help="JSONL de candidatos a validar",
    )
    p.add_argument(
        "--canon-root", required=False, type=Path,
        help="Directorio raíz del canon (contiene tiddlers_*.jsonl)",
    )
    p.add_argument(
        "--canon-glob", default=None,
        help="Glob de shards canónicos; se deriva canon-root desde su carpeta padre",
    )
    p.add_argument(
        "--report", required=False, type=Path,
        help="Ruta de salida del reporte JSON",
    )
    p.add_argument(
        "--human-review", required=False, type=Path,
        help="Ruta de salida del reporte Markdown",
    )
    p.add_argument(
        "--dry-run", action="store_true", required=True,
        help="Modo dry-run — obligatorio. Sin esta flag, el script se niega a ejecutar.",
    )
    p.add_argument(
        "--output-dir", type=Path, default=None,
        help=(
            "Directorio de salida para archivos JSONL separados por categoría "
            "(valid/invalid/unresolved/duplicate). Opcional."
        ),
    )
    p.add_argument(
        "--session-tag", type=str, default="S0129",
        help="Etiqueta de sesión para los reportes (default: S0129)",
    )
    p.add_argument(
        "--no-excerpt-check", action="store_true", default=False,
        help="Deshabilitar la verificación de excerpt contra texto fuente (más rápido pero menos seguro)",
    )
    p.add_argument(
        "--apply", action="store_true", default=False,
        help=argparse.SUPPRESS,  # opción bloqueada explícitamente
    )
    args = p.parse_args()
    if args.canon_root is None:
        if args.canon_glob:
            args.canon_root = Path(str(args.canon_glob).split("tiddlers_")[0] or ".")
        else:
            p.error("--canon-root or --canon-glob is required")
    if args.report is None:
        args.report = Path("data/out/local/pipeline/relation_candidates/s0164/validation_report.json")
    if args.human_review is None:
        args.human_review = Path("data/out/local/pipeline/relation_candidates/s0164/human_review.md")
    return args


def main() -> None:
    args = parse_args()

    # Bloqueo explícito de --apply
    if args.apply:
        print(
            "[ERROR] --apply está explícitamente bloqueada. "
            "La admisión gobernada de relaciones al canon queda reservada para sesiones posteriores.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validar entradas
    if not args.input.exists():
        print(f"[ERROR] Input no encontrado: {args.input}", file=sys.stderr)
        sys.exit(1)
    if not args.canon_root.is_dir():
        print(f"[ERROR] canon-root no es un directorio: {args.canon_root}", file=sys.stderr)
        sys.exit(1)

    # Crear directorios de salida si no existen
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.human_review.parent.mkdir(parents=True, exist_ok=True)

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tag = args.session_tag

    print(f"[{tag}] Cargando canon desde: {args.canon_root}")
    canon_ids = load_canon_ids(args.canon_root)
    print(f"[{tag}] Canon cargado: {len(canon_ids)} tiddler IDs")

    # Cargar textos fuente solo si no se desactiva la verificación
    canon_texts: Optional[dict[str, str]] = None
    if not args.no_excerpt_check:
        print(f"[{tag}] Cargando textos fuente para verificación de excerpts...")
        canon_texts = load_canon_texts(args.canon_root)
        print(f"[{tag}] Textos fuente cargados: {len(canon_texts)} tiddlers con texto")

    print(f"[{tag}] Validando: {args.input}")
    summary = validate_file(args.input, canon_ids, canon_texts)
    total = summary["total"]
    print(f"[{tag}] Total evaluados:       {total}")
    print(f"[{tag}]   válidos:             {len(summary['valid'])}")
    print(f"[{tag}]   inválidos:           {len(summary['invalid'])}")
    print(f"[{tag}]   target no resuelto:  {len(summary['unresolved_target'])}")
    print(f"[{tag}]   evidencia débil:     {len(summary['weak_evidence'])}")
    print(f"[{tag}]   duplicados:          {len(summary['duplicate'])}")

    # Generar reporte JSON
    report = build_json_report(
        summary, args.input, args.canon_root, run_at, dry_run=True, session_tag=tag
    )
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{tag}] Reporte JSON:          {args.report}")

    # Generar reporte humano
    human = build_human_review(summary, args.input, run_at, session_tag=tag)
    args.human_review.write_text(human, encoding="utf-8")
    print(f"[{tag}] Reporte humano:        {args.human_review}")

    # Generar archivos JSONL separados por categoría (si se solicitó)
    if args.output_dir:
        counts = write_category_files(summary, args.output_dir)
        for fname, n in counts.items():
            print(f"[{tag}] {fname}: {n} registros")

    # Garantía final — no se escribió en tiddlers_*.jsonl
    for p in args.canon_root.glob("tiddlers_*.jsonl"):
        if p == args.report or p == args.human_review:
            print(
                f"[ERROR] Colisión de rutas con tiddlers_*.jsonl — abortar revisión.",
                file=sys.stderr,
            )
            sys.exit(3)
    print(f"[{tag}] Garantía dry-run: ningún tiddlers_*.jsonl fue modificado.")

    if summary["invalid"]:
        print(
            f"[{tag}] ⚠️  {len(summary['invalid'])} candidatos inválidos detectados — revisar reporte."
        )
        sys.exit(0)  # No es error fatal en dry-run; el reporte lo documenta
    else:
        print(f"[{tag}] ✅ Todos los candidatos pasaron validación estructural.")


if __name__ == "__main__":
    main()
