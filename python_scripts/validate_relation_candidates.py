#!/usr/bin/env python3
"""
validate_relation_candidates.py — S0125
Validador dry-run de candidatos relacionales contra el contrato DT031.

Modo --dry-run obligatorio por defecto.
La opción --apply está explícitamente bloqueada en esta sesión.

Uso:
    python3 python_scripts/validate_relation_candidates.py \
      --input  data/out/local/pipeline/relations_candidates/relations_candidates.sample.jsonl \
      --canon-root data/out/local \
      --report data/out/local/pipeline/relations_candidates/relations_candidates.validation_report.json \
      --human-review data/out/local/pipeline/relations_candidates/relations_candidates.human_review.md \
      --dry-run
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Catálogo de tipos de relación permitidos (DT029 P0 + DT031)
# ---------------------------------------------------------------------------
ALLOWED_RELATION_TYPES: frozenset[str] = frozenset({
    # DT029 P0 — generación automática segura en pipeline
    "referencia_a",
    "deriva_de",
    "menciona_script",
    "menciona_diagnostico",
    "menciona_sesion",
    "produce_artefacto",
    "valida",
    # DT031 schema — tipos del contrato de salida
    "references",
    "derived_from",
    "validates",
    "diagnoses",
    "related_to",
})

# Umbral de confianza bajo la cual se considera evidencia débil
WEAK_EVIDENCE_THRESHOLD: float = 0.50

# Regex para candidate_id válido (DT031)
CANDIDATE_ID_RE = re.compile(r"^rc1_[a-f0-9]{16,64}$")

# Valores permitidos para resolution_status
RESOLUTION_STATUS_VALUES = {"resolved", "resolved_id", "resolved_title_unique", "unresolved", "ambiguous"}

# Valores permitidos para status
ALLOWED_STATUSES = {"candidate", "needs_review", "rejected", "unresolved_target", "duplicate", "accepted_for_admission"}

# ---------------------------------------------------------------------------
# Carga del canon
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


def validate_candidate(
    raw_line: str,
    line_number: int,
    canon_ids: set[str],
    seen_ids: dict[str, int],
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

    # 2. Campos obligatorios de primer nivel
    required_top = ["candidate_id", "status", "source", "target", "relation", "evidence", "confidence", "provenance", "created_at"]
    missing = [f for f in required_top if f not in obj or obj[f] is None]
    if missing:
        errors.append(f"Campos obligatorios ausentes: {missing}")

    # 3. candidate_id — formato
    cid = obj.get("candidate_id", "")
    if cid:
        if not CANDIDATE_ID_RE.match(cid):
            warnings.append(f"candidate_id no cumple formato ^rc1_[a-f0-9]{{16,64}}$: {cid!r}")
        # 3b. Duplicados
        if cid in seen_ids:
            categories.append("duplicate")
            errors.append(f"candidate_id duplicado; visto en línea {seen_ids[cid]}: {cid!r}")
        else:
            seen_ids[cid] = line_number

    # 4. status
    status = obj.get("status")
    if status is not None and status != "candidate":
        errors.append(f"status debe ser 'candidate'; encontrado: {status!r}")

    # 5. source.*
    source = obj.get("source") or {}
    src_id = _get_nested(source, "tiddler_id") if isinstance(source, dict) else None
    if isinstance(source, dict):
        if not source.get("field_path"):
            errors.append("source.field_path ausente o vacío")
        if src_id:
            if src_id not in canon_ids:
                errors.append(f"source.tiddler_id no existe en el canon: {src_id!r}")
        else:
            errors.append("source.tiddler_id ausente o vacío")

    # 6. target.*
    target = obj.get("target") or {}
    if isinstance(target, dict):
        res_status = target.get("resolution_status")
        if res_status not in RESOLUTION_STATUS_VALUES:
            errors.append(f"target.resolution_status inválido: {res_status!r}. Permitidos: {sorted(RESOLUTION_STATUS_VALUES)}")
        # Si no resuelto, validar marca
        if res_status in {"unresolved", "ambiguous"}:
            categories.append("unresolved_target")
            # OK — permitido solo si está marcado explícitamente
            if not target.get("tiddler_id") and not target.get("title"):
                warnings.append("target sin tiddler_id ni title — muy difícil de revisar")
        else:
            # Resuelto pero sin id
            if not target.get("tiddler_id"):
                errors.append("target.resolution_status='resolved' pero target.tiddler_id ausente")

    # 7. relation.type
    rel = obj.get("relation") or {}
    if isinstance(rel, dict):
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
    if isinstance(conf, dict):
        score = conf.get("score")
        if score is None:
            errors.append("confidence.score ausente")
        elif not isinstance(score, (int, float)):
            errors.append(f"confidence.score debe ser numérico; encontrado: {type(score).__name__}")
        elif not (0.0 <= float(score) <= 1.0):
            errors.append(f"confidence.score fuera de rango [0.0, 1.0]: {score}")
        else:
            if float(score) < WEAK_EVIDENCE_THRESHOLD:
                categories.append("weak_evidence")
                warnings.append(f"confidence.score bajo ({score}) — evidencia débil")

    # 9. evidence.excerpt
    evidence = obj.get("evidence") or {}
    if isinstance(evidence, dict):
        excerpt = evidence.get("excerpt", "")
        if not excerpt or not excerpt.strip():
            errors.append("evidence.excerpt ausente o vacío")
        if not evidence.get("kind"):
            errors.append("evidence.kind ausente o vacío")
        if not evidence.get("location"):
            warnings.append("evidence.location ausente — reduce auditabilidad")

    # 10. provenance.*
    prov = obj.get("provenance") or {}
    if isinstance(prov, dict):
        if not prov.get("generated_by"):
            errors.append("provenance.generated_by ausente")
        if not prov.get("generated_at"):
            errors.append("provenance.generated_at ausente")

    # 11. created_at
    if not obj.get("created_at"):
        errors.append("created_at ausente")

    # Resultado final
    if errors:
        result["ok"] = False
        if "invalid" not in categories:
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
) -> dict:
    """Valida todas las líneas del JSONL y devuelve un diccionario de resultados."""
    results: list[dict] = []
    seen_ids: dict[str, int] = {}
    total = 0

    for ln, raw in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        total += 1
        res = validate_candidate(raw, ln, canon_ids, seen_ids)
        results.append(res)

    # Clasificar
    valid = [r for r in results if "valid" in r["categories"]]
    invalid = [r for r in results if "invalid" in r["categories"]]
    unresolved = [r for r in results if "unresolved_target" in r["categories"] and "invalid" not in r["categories"]]
    weak = [r for r in results if "weak_evidence" in r["categories"] and "invalid" not in r["categories"]]
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
        "schema": "relations-candidate-validation-report/v1",
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
    }


def build_human_review(summary: dict, input_path: Path, run_at: str) -> str:
    total = summary["total"]
    valid_n = len(summary["valid"])
    invalid_n = len(summary["invalid"])
    unresolved_n = len(summary["unresolved_target"])
    weak_n = len(summary["weak_evidence"])
    dup_n = len(summary["duplicate"])

    lines = [
        "# Reporte de revisión humana — Relaciones candidatas (S0125)",
        "",
        f"**Generado:** {run_at}",
        f"**Fuente:** `{input_path}`",
        f"**Modo:** dry-run (ningún candidato fue escrito en el canon)",
        "",
        "---",
        "",
        "## Resumen",
        "",
        f"| Categoría | Cantidad |",
        f"|---|---|",
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
        "> considerados para admisión gobernada en una sesión futura (S0126+).",
        "",
        "_Fin del reporte._",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI principal
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Validador dry-run de candidatos relacionales (DT031) — S0125"
    )
    p.add_argument("--input", required=True, type=Path, help="JSONL de candidatos a validar")
    p.add_argument("--canon-root", required=True, type=Path, help="Directorio raíz del canon (contiene tiddlers_*.jsonl)")
    p.add_argument("--report", required=True, type=Path, help="Ruta de salida del reporte JSON")
    p.add_argument("--human-review", required=True, type=Path, help="Ruta de salida del reporte Markdown")
    p.add_argument("--dry-run", action="store_true", required=True,
                   help="Modo dry-run — obligatorio. Sin esta flag, el script se niega a ejecutar.")
    p.add_argument("--apply", action="store_true", default=False,
                   help=argparse.SUPPRESS)  # opción bloqueada explícitamente
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Bloqueo explícito de --apply (S0125)
    if args.apply:
        print("[ERROR] --apply está explícitamente bloqueada en S0125.", file=sys.stderr)
        print("[ERROR] La admisión gobernada de relaciones al canon queda reservada para sesiones posteriores.", file=sys.stderr)
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

    print(f"[S0125] Cargando canon desde: {args.canon_root}")
    canon_ids = load_canon_ids(args.canon_root)
    print(f"[S0125] Canon cargado: {len(canon_ids)} tiddler IDs")

    print(f"[S0125] Validando: {args.input}")
    summary = validate_file(args.input, canon_ids)
    total = summary["total"]
    print(f"[S0125] Total evaluados: {total}")
    print(f"[S0125]   válidos:            {len(summary['valid'])}")
    print(f"[S0125]   inválidos:          {len(summary['invalid'])}")
    print(f"[S0125]   target no resuelto: {len(summary['unresolved_target'])}")
    print(f"[S0125]   evidencia débil:    {len(summary['weak_evidence'])}")
    print(f"[S0125]   duplicados:         {len(summary['duplicate'])}")

    # Generar reporte JSON
    report = build_json_report(summary, args.input, args.canon_root, run_at, dry_run=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[S0125] Reporte JSON:     {args.report}")

    # Generar reporte humano
    human = build_human_review(summary, args.input, run_at)
    args.human_review.write_text(human, encoding="utf-8")
    print(f"[S0125] Reporte humano:  {args.human_review}")

    # Garantía final — no se escribió en tiddlers_*.jsonl
    modified = [
        str(p) for p in args.canon_root.glob("tiddlers_*.jsonl")
        if p == args.report or p == args.human_review
    ]
    if modified:
        print(f"[ERROR] Colisión de rutas con tiddlers_*.jsonl — abortar revisión.", file=sys.stderr)
        sys.exit(3)
    print("[S0125] Garantía dry-run: ningún tiddlers_*.jsonl fue modificado.")

    if summary["invalid"]:
        print(f"[S0125] ⚠️  {len(summary['invalid'])} candidatos inválidos detectados — revisar reporte.")
        sys.exit(0)  # No es error fatal en dry-run; el reporte lo documenta
    else:
        print("[S0125] ✅ Todos los candidatos pasaron validación estructural.")


if __name__ == "__main__":
    main()
