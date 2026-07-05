"""
evaluate_relation_admissibility.py — S0132

Evaluador dry-run de admisibilidad relacional.

Lee los candidatos relacionales del staging gobernado, aplica la política de
evidencia diseñada en S0131 y produce un reporte operativo por candidato.

NO modifica canon, NO admite relaciones, NO escribe en tiddlers_*.jsonl.

CLI:
    python3 src/python_scripts/evaluate_relation_admissibility.py \\
      --canon-glob "data/out/local/tiddlers_*.jsonl" \\
      --candidates-root "data/out/local/pipeline/relations_candidates" \\
      --out-dir "data/out/local/pipeline/relation_admissibility" \\
      --session "s0132"
"""

from __future__ import annotations

import argparse
import csv
import glob as _glob
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Imports de módulos previos del pipeline relacional
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))

from relation_candidate_contract import (
    ALLOWED_RELATION_TYPES,
    ALLOWED_EVIDENCE_KINDS,
    verify_excerpt_in_source,
)
from relation_admission_policy import (
    evaluate_admissibility,
    AdmissibilityResult,
    STATE_ADMISSIBLE,
    STATE_REJECTED,
    STATE_NEEDS_REVIEW,
    ALWAYS_HUMAN_REVIEW_TYPES,
    P0_RELATION_TYPES,
)

# ---------------------------------------------------------------------------
# Constantes de sesión S0132
# ---------------------------------------------------------------------------

SCHEMA = "relation-admissibility-report/v1"

# Taxonomía de decisiones S0132 (mapea sobre eligible_state de S0131)
DEC_ADMISSIBLE = "admissible_dry_run"
DEC_REVIEW = "review_required"
DEC_BLOCKED = "blocked"
DEC_REJECTED = "rejected"
DEC_DUPLICATE = "duplicate_or_existing"
DEC_INVALID = "invalid_contract"
DEC_UNRESOLVED = "unresolved_target"

# Campos obligatorios del schema relations-candidate/v1 (DT031)
REQUIRED_CANDIDATE_FIELDS = (
    "candidate_id",
    "status",
    "source",
    "target",
    "relation",
    "evidence",
    "confidence",
    "provenance",
    "created_at",
)

REQUIRED_NESTED = {
    "source": ("tiddler_id",),
    "target": ("tiddler_id", "resolution_status"),
    "relation": ("type",),
    "evidence": ("kind", "excerpt"),
    "confidence": ("score",),
    "provenance": ("generated_by",),
}

# Campos del reporte por candidato (CSV columns)
REPORT_FIELDS = (
    "candidate_id",
    "source_id",
    "source_title",
    "target_id",
    "target_title",
    "target_resolution_status",
    "relation_type",
    "evidence_kind",
    "evidence_excerpt",
    "confidence_score",
    "risk_level",
    "decision",
    "decision_reasons",
    "would_modify_canon",
)


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------

def load_canon(canon_glob: str) -> dict[str, dict]:
    """Carga el canon desde shards JSONL. Retorna dict {id: record}."""
    canon: dict[str, dict] = {}
    for path in sorted(Path(p) for p in _glob.glob(canon_glob)):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                tid = obj.get("id", "")
                if tid:
                    canon[tid] = obj
            except json.JSONDecodeError:
                pass
    return canon


def load_candidates_from_dir(candidates_root: Path) -> tuple[list[dict], str]:
    """
    Carga candidatos desde la raíz del staging.
    Prioridad: s0129/ categorizados → sample original.
    Retorna (candidatos, fuente_usada).
    """
    candidates: list[dict] = []
    seen_ids: set[str] = set()
    source_used = ""

    def _load_file(path: Path, category: str) -> int:
        if not path.exists():
            return 0
        loaded = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                cid = obj.get("candidate_id", "")
                if cid and cid not in seen_ids:
                    obj["_staging_category"] = category
                    candidates.append(obj)
                    seen_ids.add(cid)
                    loaded += 1
            except json.JSONDecodeError:
                pass
        return loaded

    s0129 = candidates_root / "s0129"
    total_from_s0129 = 0
    total_from_s0129 += _load_file(s0129 / "valid_candidates.jsonl", "valid")
    total_from_s0129 += _load_file(s0129 / "invalid_candidates.jsonl", "invalid")
    total_from_s0129 += _load_file(s0129 / "unresolved_candidates.jsonl", "unresolved_target")
    total_from_s0129 += _load_file(s0129 / "duplicate_candidates.jsonl", "duplicate")

    if total_from_s0129 > 0:
        source_used = str(s0129)
    else:
        _load_file(candidates_root / "relations_candidates.sample.jsonl", "unknown")
        source_used = str(candidates_root / "relations_candidates.sample.jsonl")

    return candidates, source_used


# ---------------------------------------------------------------------------
# Verificación de contrato DT031
# ---------------------------------------------------------------------------

def check_contract(candidate: dict) -> list[str]:
    """
    Verifica que el candidato cumple el contrato mínimo DT031.
    Retorna lista de errores de contrato (vacía si ok).
    """
    errors: list[str] = []
    for field in REQUIRED_CANDIDATE_FIELDS:
        if field not in candidate:
            errors.append(f"campo obligatorio ausente: '{field}'")
    for nested_field, subfields in REQUIRED_NESTED.items():
        nested = candidate.get(nested_field)
        if not isinstance(nested, dict):
            if nested_field not in errors:  # ya reportado arriba
                errors.append(f"'{nested_field}' debe ser un objeto")
            continue
        for sf in subfields:
            if sf not in nested:
                errors.append(f"'{nested_field}.{sf}' ausente")
    return errors


# ---------------------------------------------------------------------------
# Mapeo S0131 eligible_state → S0132 decision
# ---------------------------------------------------------------------------

def _map_decision(
    result: AdmissibilityResult,
    candidate: dict,
) -> tuple[str, list[str], str]:
    """
    Mapea el resultado de evaluate_admissibility() a la taxonomía S0132.

    Retorna (decision, decision_reasons, risk_level).
    """
    reasons = list(result.blocking_reasons)
    # Agregar warnings como contexto secundario si no hay blocking reasons
    if not reasons and result.warnings:
        reasons = [f"[warning] {w}" for w in result.warnings]

    state = result.eligible_state

    # Duplicado canónico
    if not result.checks.get("not_duplicate_canonical", True):
        return DEC_DUPLICATE, reasons, "medium"

    # Hard blocks → rejected o blocked
    if state == STATE_REJECTED:
        hard_markers = ["no permitido", "auto-relación", "idéntica ya existe"]
        if any(any(m in r for m in hard_markers) for r in reasons):
            return DEC_REJECTED, reasons, "high"
        # Source/target not in canon → blocked
        if (
            not result.checks.get("source_in_canon", True)
            or not result.checks.get("target_in_canon", True)
        ):
            return DEC_BLOCKED, reasons, "high"
        return DEC_REJECTED, reasons, "high"

    # Needs review
    if state == STATE_NEEDS_REVIEW:
        # Target unresolved/ambiguous
        if not result.checks.get("target_resolved", True):
            return DEC_UNRESOLVED, reasons, "medium"
        # Otros soft blocks
        return DEC_REVIEW, reasons, "medium"

    # Admissible
    if state == STATE_ADMISSIBLE:
        rel_type = (candidate.get("relation") or {}).get("type", "")
        always_human = rel_type in ALWAYS_HUMAN_REVIEW_TYPES
        # Admissible pero requiere aprobación humana explícita
        if always_human or not result.checks.get("human_review_done", True):
            notes = [f"elegible para admisión — pendiente de aprobación humana"]
            if result.warnings:
                notes.extend(result.warnings)
            return DEC_REVIEW, notes, "medium"
        return DEC_ADMISSIBLE, reasons or ["todos los checks pasaron"], "low"

    # Fallback
    return DEC_REVIEW, reasons or ["estado indeterminado"], "medium"


# ---------------------------------------------------------------------------
# Evaluación de un candidato
# ---------------------------------------------------------------------------

def evaluate_candidate(
    candidate: dict,
    canon: dict[str, dict],
) -> dict[str, Any]:
    """
    Evalúa un candidato y retorna un dict con todos los campos REPORT_FIELDS.
    `would_modify_canon` siempre es False (dry-run).
    """
    cid = candidate.get("candidate_id", "")
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    relation = candidate.get("relation") or {}
    evidence = candidate.get("evidence") or {}
    confidence = candidate.get("confidence") or {}

    src_id = source.get("tiddler_id", "")
    src_title = source.get("title", "") or (canon.get(src_id, {}).get("title", "") if src_id else "")
    tgt_id = target.get("tiddler_id", "")
    tgt_title = target.get("title", "") or (canon.get(tgt_id, {}).get("title", "") if tgt_id else "")
    tgt_res = target.get("resolution_status", "")
    rel_type = relation.get("type", "")
    ev_kind = evidence.get("kind", "")
    excerpt = evidence.get("excerpt", "") or ""
    score = float(confidence.get("score") or 0.0)

    # 1. Check contrato DT031
    contract_errors = check_contract(candidate)
    if contract_errors:
        return {
            "candidate_id": cid,
            "source_id": src_id,
            "source_title": src_title[:80],
            "target_id": tgt_id,
            "target_title": tgt_title[:80],
            "target_resolution_status": tgt_res,
            "relation_type": rel_type,
            "evidence_kind": ev_kind,
            "evidence_excerpt": excerpt[:120],
            "confidence_score": score,
            "risk_level": "high",
            "decision": DEC_INVALID,
            "decision_reasons": "; ".join(contract_errors),
            "would_modify_canon": False,
        }

    # 2. Evaluar admisibilidad con política S0131
    result = evaluate_admissibility(
        candidate,
        canon,
        require_human_approval=True,
        human_approved=False,  # en dry-run, nunca pre-aprobado
    )

    decision, reasons, risk = _map_decision(result, candidate)

    # 3. Verificación adicional: excerpt vs texto fuente
    # (el evaluador puede añadir contexto sin bloquear si S0131 ya lo hizo)
    if decision not in {DEC_INVALID, DEC_REJECTED, DEC_BLOCKED, DEC_DUPLICATE}:
        src_record = canon.get(src_id, {})
        src_text = src_record.get("text") or src_record.get("semantic_text") or ""
        excerpt_result = verify_excerpt_in_source(excerpt, src_text)
        if excerpt_result is False and ev_kind == "ai_inference":
            # DT030: ai_inference + not found → hard block
            decision = DEC_REJECTED
            reasons = [f"evidence.excerpt not found in source text (kind=ai_inference — DT030)"] + reasons
            risk = "high"
        elif excerpt_result is False and decision == DEC_REVIEW:
            reasons = [f"[warning] excerpt no encontrado en texto fuente — verificar manualmente"] + reasons
        elif excerpt_result is None and ev_kind != "ai_inference":
            reasons = [f"[warning] texto fuente ausente — excerpt no verificable"] + reasons

    return {
        "candidate_id": cid,
        "source_id": src_id,
        "source_title": src_title[:80],
        "target_id": tgt_id,
        "target_title": tgt_title[:80],
        "target_resolution_status": tgt_res,
        "relation_type": rel_type,
        "evidence_kind": ev_kind,
        "evidence_excerpt": excerpt[:120],
        "confidence_score": score,
        "risk_level": risk,
        "decision": decision,
        "decision_reasons": "; ".join(reasons) if isinstance(reasons, list) else str(reasons),
        "would_modify_canon": False,
    }


def evaluate_all(
    candidates: list[dict],
    canon: dict[str, dict],
) -> list[dict[str, Any]]:
    """Evalúa todos los candidatos y retorna lista de resultados."""
    return [evaluate_candidate(c, canon) for c in candidates]


# ---------------------------------------------------------------------------
# Generación de reportes
# ---------------------------------------------------------------------------

def _count_decisions(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {
        DEC_ADMISSIBLE: 0,
        DEC_REVIEW: 0,
        DEC_BLOCKED: 0,
        DEC_REJECTED: 0,
        DEC_DUPLICATE: 0,
        DEC_INVALID: 0,
        DEC_UNRESOLVED: 0,
    }
    for r in results:
        d = r.get("decision", "")
        if d in counts:
            counts[d] += 1
        else:
            counts[d] = counts.get(d, 0) + 1
    return counts


def build_json_report(
    results: list[dict],
    canon_size: int,
    candidates_source: str,
    session: str,
) -> dict:
    counts = _count_decisions(results)
    return {
        "schema": SCHEMA,
        "session": session.upper(),
        "dry_run": True,
        "applied_to_canon": False,
        "would_modify_canon": False,
        "canon_size": canon_size,
        "candidates_source": candidates_source,
        "total_evaluated": len(results),
        "decision_summary": counts,
        "results": results,
        "note": (
            "Este reporte es solo informativo. Ninguna relación fue admitida al canon. "
            "La admisión real requiere implementar Stage 5 del circuito de admisión "
            "(extensión de admit_session_candidates.py para relations-candidate/v1)."
        ),
    }


def build_markdown_summary(
    results: list[dict],
    canon_size: int,
    candidates_source: str,
    session: str,
) -> str:
    counts = _count_decisions(results)
    total = len(results)

    lines = [
        f"# Evaluador dry-run de admisibilidad relacional — {session.upper()}",
        "",
        f"**Modo:** dry-run — ninguna relación fue admitida al canon",
        f"**Session:** {session.upper()}",
        "",
        "---",
        "",
        "## 1. Entradas",
        "",
        f"| Métrica | Valor |",
        f"|---------|-------|",
        f"| Canon (tiddlers) | {canon_size} |",
        f"| Candidatos evaluados | {total} |",
        f"| Fuente de candidatos | `{candidates_source}` |",
        "",
        "---",
        "",
        "## 2. Resultado por decisión",
        "",
        f"| Decisión | Cantidad |",
        f"|----------|---------|",
    ]
    for dec, cnt in counts.items():
        icon = {
            DEC_ADMISSIBLE: "✅",
            DEC_REVIEW: "⏳",
            DEC_BLOCKED: "🚫",
            DEC_REJECTED: "❌",
            DEC_DUPLICATE: "🔁",
            DEC_INVALID: "⚠️",
            DEC_UNRESOLVED: "🔍",
        }.get(dec, "•")
        lines.append(f"| {icon} `{dec}` | {cnt} |")

    lines += [
        "",
        "---",
        "",
        "## 3. Detalle por candidato",
        "",
    ]

    for r in results:
        lines += [
            f"### `{r['candidate_id']}`",
            f"- **source:** {r['source_title'][:70] or r['source_id']}",
            f"- **target:** {r['target_title'][:70] or r['target_id']}",
            f"- **relation.type:** `{r['relation_type']}`",
            f"- **evidence.kind:** `{r['evidence_kind']}`",
            f"- **score:** {r['confidence_score']}",
            f"- **decisión:** `{r['decision']}`",
            f"- **riesgo:** `{r['risk_level']}`",
            f"- **razones:** {r['decision_reasons'][:200]}",
            f"- **would_modify_canon:** `{r['would_modify_canon']}`",
            "",
        ]

    lines += [
        "---",
        "",
        "## 4. Nota sobre admisión futura",
        "",
        "> Los candidatos con `admissible_dry_run` o `review_required` están listos para",
        "> revisión humana. La admisión real al canon requiere:",
        "> 1. Aprobación explícita del operador (`human_approved=True`)",
        "> 2. Implementación del Stage 5 del circuito (extensión de `admit_session_candidates.py`)",
        "> 3. Sesión dedicada con ejecución gobernada",
        "",
        "_Fin del reporte._",
    ]

    return "\n".join(lines)


def build_csv(results: list[dict]) -> str:
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=REPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(results)
    return buf.getvalue()


def build_patch_preview(results: list[dict], session: str) -> dict:
    """
    Vista previa de lo que se podría aplicar en el futuro.
    Declaración explícita: dry_run=True, applied_to_canon=False.
    """
    admissible = [r for r in results if r["decision"] == DEC_ADMISSIBLE]
    patches = []
    for r in admissible:
        patches.append({
            "operation": "add_relation",
            "source_tiddler_id": r["source_id"],
            "target_tiddler_id": r["target_id"],
            "relation_type": r["relation_type"],
            "evidence_kind": r["evidence_kind"],
            "evidence_excerpt": r["evidence_excerpt"],
            "confidence_score": r["confidence_score"],
            "candidate_id": r["candidate_id"],
            "status": "not_applied",
        })
    return {
        "schema": "relation-admission-patch-preview/v1",
        "session": session.upper(),
        "dry_run": True,
        "applied_to_canon": False,
        "would_modify_canon": False,
        "total_patches": len(patches),
        "patches": patches,
        "note": (
            "SOLO VISTA PREVIA. Ninguna de estas operaciones fue aplicada al canon. "
            "Para aplicar, se requiere implementar el Stage 5 del circuito de admisión."
        ),
    }


# ---------------------------------------------------------------------------
# Escritura de reportes
# ---------------------------------------------------------------------------

def write_reports(
    results: list[dict],
    canon_size: int,
    candidates_source: str,
    session: str,
    out_dir: Path,
) -> dict[str, Path]:
    session_out = out_dir / session
    session_out.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}

    # JSON
    json_path = session_out / f"{session}_relation_admissibility_report.json"
    json_path.write_text(
        json.dumps(
            build_json_report(results, canon_size, candidates_source, session),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["json"] = json_path

    # Markdown
    md_path = session_out / f"{session}_relation_admissibility_summary.md"
    md_path.write_text(
        build_markdown_summary(results, canon_size, candidates_source, session),
        encoding="utf-8",
    )
    paths["md"] = md_path

    # CSV
    csv_path = session_out / f"{session}_relation_admissibility_review.csv"
    csv_path.write_text(build_csv(results), encoding="utf-8")
    paths["csv"] = csv_path

    # Patch preview (optional — only if there are admissible candidates)
    admissible_count = sum(1 for r in results if r["decision"] == DEC_ADMISSIBLE)
    if admissible_count > 0:
        patch_path = session_out / f"{session}_relation_admissibility_patch_preview.json"
        patch_path.write_text(
            json.dumps(build_patch_preview(results, session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths["patch"] = patch_path

    return paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluador dry-run de admisibilidad relacional (S0132)"
    )
    parser.add_argument(
        "--canon-glob",
        default="data/out/local/tiddlers_*.jsonl",
        help="Glob para los shards del canon",
    )
    parser.add_argument(
        "--candidates-root",
        default="data/out/local/pipeline/relations_candidates",
        help="Directorio raíz del staging de candidatos",
    )
    parser.add_argument(
        "--out-dir",
        default="data/out/local/pipeline/relation_admissibility",
        help="Directorio de salida para los reportes",
    )
    parser.add_argument(
        "--session",
        default="s0132",
        help="Identificador de sesión para prefijo de archivos",
    )
    args = parser.parse_args()

    tag = args.session.upper()

    print(f"[{tag}] Cargando canon desde: {args.canon_glob}")
    canon = load_canon(args.canon_glob)
    print(f"[{tag}] Canon: {len(canon)} tiddlers")

    candidates_root = Path(args.candidates_root)
    print(f"[{tag}] Cargando candidatos desde: {candidates_root}")
    if not candidates_root.exists():
        print(f"[{tag}] AVISO: directorio de candidatos no encontrado — 0 candidatos", file=sys.stderr)
    candidates, source_used = load_candidates_from_dir(candidates_root)
    print(f"[{tag}] Candidatos: {len(candidates)} (fuente: {source_used})")

    print(f"[{tag}] Evaluando admisibilidad...")
    results = evaluate_all(candidates, canon)

    counts = _count_decisions(results)
    print(f"[{tag}] Decisiones: {counts}")

    out_dir = Path(args.out_dir)
    paths = write_reports(results, len(canon), source_used, args.session, out_dir)

    for key, path in paths.items():
        print(f"[{tag}] {key.upper()}: {path}")

    # Garantía de no-escritura en canon
    for p in (Path(p2) for p2 in _glob.glob(args.canon_glob)):
        for outpath in paths.values():
            if p.resolve() == outpath.resolve():
                print("[ERROR] Colisión con tiddlers_*.jsonl", file=sys.stderr)
                sys.exit(3)
    print(f"[{tag}] Garantía dry-run: ningún tiddlers_*.jsonl fue modificado.")
    print(f"[{tag}] would_modify_canon: False para todos los candidatos.")


if __name__ == "__main__":
    main()
