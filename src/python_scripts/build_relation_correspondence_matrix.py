#!/usr/bin/env python3
"""
build_relation_correspondence_matrix.py — S0130

Construye una matriz de correspondencia entre tres capas del proyecto:
  1. Tags nativos del canon (campo 'tags')
  2. Metadata canónica (relaciones explícitas en campo 'relations')
  3. Relaciones candidatas en staging (pipeline/relations_candidates/)

Modo no destructivo: nunca escribe en tiddlers_*.jsonl.

CLI:
    python3 src/python_scripts/build_relation_correspondence_matrix.py \\
      --canon-glob "data/out/local/tiddlers_*.jsonl" \\
      --candidates-root "data/out/local/pipeline/relations_candidates" \\
      --out-dir "data/out/local/pipeline/relation_correspondence" \\
      --session "s0130" \\
      --dry-run
"""

import argparse
import csv
import glob as _glob
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Clasificaciones de densidad de metadata
DENSITY_RICH = "metadata_rich"          # fuente + relaciones + metadata completa
DENSITY_PARTIAL = "metadata_partial"    # fuente + semantic/text, sin relaciones
DENSITY_CONDENSED = "markdown_condensed"  # solo texto y tags
DENSITY_TAG_ONLY = "tag_only"           # solo tags, sin texto ni relaciones
DENSITY_MINIMAL = "minimal"             # ni tags ni texto útiles
DENSITY_UNKNOWN = "unknown"

# Estados de correspondencia
CORR_ALIGNED = "aligned"
CORR_TAG_ONLY = "tag_only"
CORR_METADATA_ONLY = "metadata_only"
CORR_CANDIDATE_ONLY = "candidate_only"
CORR_TAG_META_ALIGNED = "tag_metadata_aligned"
CORR_TAG_CAND_ALIGNED = "tag_candidate_aligned"
CORR_META_CAND_ALIGNED = "metadata_candidate_aligned"
CORR_CONFLICT = "conflict"
CORR_UNRESOLVED = "unresolved_target"
CORR_WEAK_EVIDENCE = "weak_evidence"
CORR_MISSING_EVIDENCE = "missing_evidence"
CORR_DUPLICATE = "duplicate_candidate"
CORR_NEEDS_REVIEW = "needs_human_review"

# Niveles de riesgo
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_CRITICAL = "critical"

# Umbrales
WEAK_CONFIDENCE_THRESHOLD = 0.50
METADATA_DENSE_SF_FIELDS = 3  # source_fields con al menos N campos = metadata rica


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------

def load_canon(canon_glob: str) -> dict[str, dict]:
    """
    Carga el canon completo desde los shards JSONL.
    Retorna dict {tiddler_id: record}.
    """
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


def classify_metadata_density(record: dict) -> str:
    """Clasifica la densidad de metadata de un tiddler."""
    tags = record.get("tags") or []
    text = record.get("text") or ""
    semantic = record.get("semantic_text") or ""
    source_fields = record.get("source_fields") or {}
    relations = record.get("relations") or []

    has_rich_meta = (
        isinstance(source_fields, dict) and len(source_fields) >= METADATA_DENSE_SF_FIELDS
    )
    has_relations = len(relations) > 0
    has_text = len(text.strip()) > 100
    has_semantic = len(semantic.strip()) > 100
    has_tags = len(tags) > 0

    if has_rich_meta and has_relations:
        return DENSITY_RICH
    if has_rich_meta or has_semantic:
        return DENSITY_PARTIAL
    if has_text and has_tags:
        return DENSITY_CONDENSED
    if has_tags:
        return DENSITY_TAG_ONLY
    if has_text:
        return DENSITY_CONDENSED
    return DENSITY_MINIMAL


def normalize_tags(tags: list) -> list[str]:
    """
    Normaliza una lista de tags: lowercase, strip, elimina vacíos.
    Los tags con prefijos especiales (status:, layer:, artifact:, milestone:)
    se mantienen pero también en forma normalizada.
    """
    result = []
    for t in tags:
        if isinstance(t, str):
            norm = t.strip().lower()
            if norm:
                result.append(norm)
    return sorted(set(result))


def extract_canonical_relation_target_ids(record: dict) -> set[str]:
    """
    Extrae los target_ids de las relaciones canónicas explícitas de un tiddler.
    """
    ids: set[str] = set()
    for rel in (record.get("relations") or []):
        if isinstance(rel, dict):
            tid = rel.get("target_id", "")
            if tid:
                ids.add(tid)
    return ids


def load_candidates_from_dir(candidates_root: Path) -> list[dict]:
    """
    Carga todos los candidatos disponibles desde la raíz de candidatos.
    Preferencia: s0129/ (saneado), luego sample original.
    Cada candidato recibe un campo '_staging_category' con su categoría.
    """
    candidates: list[dict] = []
    seen_ids: set[str] = set()

    def _load_file(path: Path, category: str) -> None:
        if not path.exists():
            return
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
            except json.JSONDecodeError:
                pass

    # Prioridad: archivos categorizados de s0129
    s0129 = candidates_root / "s0129"
    _load_file(s0129 / "valid_candidates.jsonl", "valid")
    _load_file(s0129 / "invalid_candidates.jsonl", "invalid")
    _load_file(s0129 / "unresolved_candidates.jsonl", "unresolved_target")
    _load_file(s0129 / "duplicate_candidates.jsonl", "duplicate")

    # Si no hay nada de s0129, intentar el sample original
    if not candidates:
        _load_file(candidates_root / "relations_candidates.sample.jsonl", "unknown")

    return candidates


# ---------------------------------------------------------------------------
# Determinación de correspondencia
# ---------------------------------------------------------------------------

def _has_tag_covering_target(
    source_record: dict,
    target_record: Optional[dict],
    candidate: dict,
) -> bool:
    """
    Heurística: ¿algún tag nativo del source menciona el título/slug del target?
    """
    if target_record is None:
        return False
    target_title = (target_record.get("title") or "").lower().strip()
    target_slug = (target_record.get("canonical_slug") or "").lower().strip()
    source_tags_norm = normalize_tags(source_record.get("tags") or [])
    for tag in source_tags_norm:
        if target_title and target_title in tag:
            return True
        if target_slug and target_slug in tag:
            return True
    return False


def determine_correspondence(
    candidate: dict,
    canon: dict[str, dict],
) -> dict:
    """
    Determina el estado de correspondencia de un candidato contra el canon.

    Retorna un dict con:
      - correspondence_status
      - risk_level
      - recommended_action
      - details (dict de señales observadas)
    """
    staging_cat = candidate.get("_staging_category", "unknown")
    source = candidate.get("source") or {}
    target = candidate.get("target") or {}
    evidence = candidate.get("evidence") or {}
    confidence = candidate.get("confidence") or {}
    relation = candidate.get("relation") or {}

    src_id = source.get("tiddler_id", "") or ""
    tgt_id = target.get("tiddler_id", "") or ""
    tgt_res = target.get("resolution_status", "")
    score = float(confidence.get("score", 0.0))
    ev_kind = evidence.get("kind", "")
    excerpt = evidence.get("excerpt", "") or ""
    rel_type = relation.get("type", "")

    source_record = canon.get(src_id)
    target_record = canon.get(tgt_id) if tgt_id else None

    details: dict[str, Any] = {
        "source_in_canon": src_id in canon,
        "target_in_canon": tgt_id in canon if tgt_id else False,
        "target_resolution_status": tgt_res,
        "confidence_score": score,
        "evidence_kind": ev_kind,
        "has_excerpt": bool(excerpt.strip()),
        "staging_category": staging_cat,
    }

    # --- Casos de fallo estructural ---
    if staging_cat == "invalid":
        details["reason"] = "invalid_by_validator"
        return {
            "correspondence_status": CORR_CONFLICT,
            "risk_level": RISK_HIGH,
            "recommended_action": "discard_or_fix",
            "details": details,
        }

    if staging_cat == "duplicate":
        return {
            "correspondence_status": CORR_DUPLICATE,
            "risk_level": RISK_MEDIUM,
            "recommended_action": "deduplicate_and_keep_highest_score",
            "details": details,
        }

    if tgt_res in ("unresolved", "ambiguous") or staging_cat == "unresolved_target":
        return {
            "correspondence_status": CORR_UNRESOLVED,
            "risk_level": RISK_MEDIUM,
            "recommended_action": "resolve_target_id_before_admission",
            "details": details,
        }

    if not excerpt.strip():
        return {
            "correspondence_status": CORR_MISSING_EVIDENCE,
            "risk_level": RISK_HIGH,
            "recommended_action": "add_evidence_excerpt",
            "details": details,
        }

    if score < WEAK_CONFIDENCE_THRESHOLD:
        return {
            "correspondence_status": CORR_WEAK_EVIDENCE,
            "risk_level": RISK_HIGH,
            "recommended_action": "strengthen_evidence_or_discard",
            "details": details,
        }

    # --- Análisis de correspondencia entre capas ---
    has_canonical_rel = False
    if source_record:
        canon_target_ids = extract_canonical_relation_target_ids(source_record)
        has_canonical_rel = tgt_id in canon_target_ids
        details["source_canonical_relations_count"] = len(canon_target_ids)
        details["target_already_in_canonical_relations"] = has_canonical_rel

    has_tag_signal = False
    if source_record:
        has_tag_signal = _has_tag_covering_target(source_record, target_record, candidate)
        details["tag_covers_target"] = has_tag_signal

    # Clasificación de correspondencia
    if has_canonical_rel and has_tag_signal:
        status = CORR_ALIGNED
        risk = RISK_LOW
        action = "admit_when_governed_circuit_ready"
    elif has_canonical_rel and not has_tag_signal:
        status = CORR_META_CAND_ALIGNED
        risk = RISK_LOW
        action = "admit_when_governed_circuit_ready"
    elif has_tag_signal and not has_canonical_rel:
        status = CORR_TAG_CAND_ALIGNED
        risk = RISK_LOW
        action = "admit_when_governed_circuit_ready"
    else:
        # Candidato válido pero sin confirmación en ninguna otra capa
        status = CORR_CANDIDATE_ONLY
        risk = RISK_MEDIUM
        action = "human_review_before_admission"

    return {
        "correspondence_status": status,
        "risk_level": risk,
        "recommended_action": action,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Construcción de la matriz
# ---------------------------------------------------------------------------

def build_matrix(
    canon: dict[str, dict],
    candidates: list[dict],
) -> list[dict]:
    """
    Construye la lista de entradas de la matriz de correspondencia.
    Una entrada por candidato relacional.
    """
    entries: list[dict] = []

    for cand in candidates:
        source = cand.get("source") or {}
        target = cand.get("target") or {}
        relation = cand.get("relation") or {}
        evidence = cand.get("evidence") or {}
        confidence = cand.get("confidence") or {}

        src_id = source.get("tiddler_id", "") or ""
        tgt_id = target.get("tiddler_id", "") or ""
        source_record = canon.get(src_id)
        target_record = canon.get(tgt_id) if tgt_id else None

        # Metadata del source
        if source_record:
            src_title = source_record.get("title", source.get("title", ""))
            src_slug = source_record.get("canonical_slug", "")
            native_tags_raw = source_record.get("tags") or []
            native_tags_norm = normalize_tags(native_tags_raw)
            canon_relations_count = len(source_record.get("relations") or [])
            metadata_density = classify_metadata_density(source_record)
            canonical_relations_present = canon_relations_count > 0
        else:
            src_title = source.get("title", "")
            src_slug = ""
            native_tags_raw = []
            native_tags_norm = []
            canon_relations_count = 0
            metadata_density = DENSITY_UNKNOWN
            canonical_relations_present = False

        # Correspondencia
        corr = determine_correspondence(cand, canon)

        entry: dict = {
            # Source tiddler
            "source_tiddler_id": src_id,
            "source_title": src_title[:100],
            "source_canonical_slug": src_slug,
            "native_tags_raw": native_tags_raw[:10],  # truncado para legibilidad
            "native_tags_normalized": native_tags_norm[:10],
            "canonical_metadata_present": bool(source_record),
            "canonical_relations_present": canonical_relations_present,
            "metadata_density": metadata_density,
            # Candidate
            "candidate_id": cand.get("candidate_id", ""),
            "candidate_source_id": src_id,
            "candidate_target_id": tgt_id,
            "candidate_target_title": (target_record or {}).get("title", target.get("title", ""))[:80],
            "candidate_relation_type": relation.get("type", ""),
            "candidate_evidence_kind": evidence.get("kind", ""),
            "candidate_evidence_excerpt": (evidence.get("excerpt") or "")[:120],
            "candidate_confidence_score": float(confidence.get("score", 0.0)),
            "staging_category": cand.get("_staging_category", "unknown"),
            # Correspondencia
            "correspondence_status": corr["correspondence_status"],
            "risk_level": corr["risk_level"],
            "recommended_action": corr["recommended_action"],
            "correspondence_details": corr["details"],
        }
        entries.append(entry)

    return entries


def build_canon_metadata_summary(canon: dict[str, dict]) -> dict:
    """Resumen de metadata del canon completo (no por candidato)."""
    density_counts: dict[str, int] = {
        DENSITY_RICH: 0,
        DENSITY_PARTIAL: 0,
        DENSITY_CONDENSED: 0,
        DENSITY_TAG_ONLY: 0,
        DENSITY_MINIMAL: 0,
        DENSITY_UNKNOWN: 0,
    }
    tag_counter: dict[str, int] = {}
    with_tags = 0
    with_relations = 0

    for record in canon.values():
        density = classify_metadata_density(record)
        density_counts[density] = density_counts.get(density, 0) + 1
        tags = record.get("tags") or []
        if tags:
            with_tags += 1
            for t in tags:
                if isinstance(t, str):
                    tag_counter[t] = tag_counter.get(t, 0) + 1
        if record.get("relations"):
            with_relations += 1

    top_tags = sorted(tag_counter.items(), key=lambda x: -x[1])[:20]
    return {
        "total_tiddlers": len(canon),
        "with_tags": with_tags,
        "with_canonical_relations": with_relations,
        "density_distribution": density_counts,
        "top_20_tags": top_tags,
    }


# ---------------------------------------------------------------------------
# Generación de reportes
# ---------------------------------------------------------------------------

def build_json_report(
    matrix: list[dict],
    canon_summary: dict,
    session: str,
    candidates_root: str,
) -> dict:
    corr_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for entry in matrix:
        cs = entry["correspondence_status"]
        rl = entry["risk_level"]
        corr_counts[cs] = corr_counts.get(cs, 0) + 1
        risk_counts[rl] = risk_counts.get(rl, 0) + 1

    return {
        "schema": "relation-correspondence-matrix/v1",
        "session": session,
        "dry_run": True,
        "candidates_root": str(candidates_root),
        "canon_summary": canon_summary,
        "matrix_summary": {
            "total_candidates_analyzed": len(matrix),
            "correspondence_distribution": corr_counts,
            "risk_distribution": risk_counts,
        },
        "matrix": matrix,
    }


def build_markdown_summary(
    matrix: list[dict],
    canon_summary: dict,
    session: str,
) -> str:
    total_tiddlers = canon_summary["total_tiddlers"]
    with_tags = canon_summary["with_tags"]
    with_rels = canon_summary["with_canonical_relations"]
    density = canon_summary["density_distribution"]
    top_tags = canon_summary["top_20_tags"]

    corr_counts: dict[str, int] = {}
    for entry in matrix:
        cs = entry["correspondence_status"]
        corr_counts[cs] = corr_counts.get(cs, 0) + 1

    total_cands = len(matrix)
    aligned = corr_counts.get(CORR_ALIGNED, 0)
    tag_meta = corr_counts.get(CORR_TAG_META_ALIGNED, 0)
    tag_cand = corr_counts.get(CORR_TAG_CAND_ALIGNED, 0)
    meta_cand = corr_counts.get(CORR_META_CAND_ALIGNED, 0)
    cand_only = corr_counts.get(CORR_CANDIDATE_ONLY, 0)
    conflict = corr_counts.get(CORR_CONFLICT, 0)
    unresolved = corr_counts.get(CORR_UNRESOLVED, 0)
    weak = corr_counts.get(CORR_WEAK_EVIDENCE, 0)
    dup = corr_counts.get(CORR_DUPLICATE, 0)

    pct = lambda n, t: f"{n/t*100:.0f}%" if t > 0 else "N/A"

    lines = [
        f"# Matriz de correspondencia relacional — {session.upper()}",
        "",
        f"**Modo:** dry-run — ningún tiddler fue modificado",
        "",
        "---",
        "",
        "## 1. Resumen del canon",
        "",
        f"| Métrica | Valor |",
        f"|---|---|",
        f"| Total tiddlers analizados | {total_tiddlers} |",
        f"| Tiddlers con tags nativos | {with_tags} ({pct(with_tags, total_tiddlers)}) |",
        f"| Tiddlers con relations canónicas | {with_rels} ({pct(with_rels, total_tiddlers)}) |",
        f"| Tiddlers `metadata_rich` (relaciones + fuente) | {density.get(DENSITY_RICH, 0)} |",
        f"| Tiddlers `metadata_partial` (fuente sin relaciones) | {density.get(DENSITY_PARTIAL, 0)} |",
        f"| Tiddlers `markdown_condensed` | {density.get(DENSITY_CONDENSED, 0)} |",
        f"| Tiddlers `tag_only` | {density.get(DENSITY_TAG_ONLY, 0)} |",
        "",
        "### Top 10 tags nativos",
        "",
        "| Tag | Tiddlers |",
        "|---|---|",
    ]
    for tag, count in top_tags[:10]:
        lines.append(f"| `{tag[:60]}` | {count} |")

    lines += [
        "",
        "---",
        "",
        "## 2. Análisis de candidatos relacionales",
        "",
        f"| Métrica | Valor |",
        f"|---|---|",
        f"| Total candidatos detectados | {total_cands} |",
        f"| ✅ Alineados (3 capas) | {aligned} |",
        f"| 🔗 Tag + metadata alineados | {tag_meta} |",
        f"| 🔗 Tag + candidato alineados | {tag_cand} |",
        f"| 🔗 Metadata + candidato alineados | {meta_cand} |",
        f"| 📌 Solo candidato (sin confirmación) | {cand_only} |",
        f"| ❌ Conflicto / inválido | {conflict} |",
        f"| 🔍 Target no resuelto | {unresolved} |",
        f"| ⚠️ Evidencia débil | {weak} |",
        f"| 🔁 Duplicado | {dup} |",
        "",
    ]

    # Detalle por candidato
    lines += [
        "---",
        "",
        "## 3. Detalle por candidato",
        "",
    ]
    for entry in matrix:
        cid = entry["candidate_id"]
        src_title = entry["source_title"][:50]
        tgt_title = entry["candidate_target_title"][:50]
        rel_type = entry["candidate_relation_type"]
        score = entry["candidate_confidence_score"]
        corr = entry["correspondence_status"]
        risk = entry["risk_level"]
        action = entry["recommended_action"]
        lines += [
            f"### `{cid}`",
            f"- **source:** {src_title}",
            f"- **target:** {tgt_title}",
            f"- **relation.type:** `{rel_type}`",
            f"- **score:** {score}",
            f"- **correspondencia:** `{corr}`",
            f"- **riesgo:** `{risk}`",
            f"- **acción recomendada:** {action}",
            "",
        ]

    lines += [
        "---",
        "",
        "## 4. Recomendación para S0131",
        "",
    ]

    admissible = sum(1 for e in matrix if e["risk_level"] == RISK_LOW)
    lines += [
        f"- **Candidatos listos para admisión gobernada** (riesgo bajo): {admissible}",
        f"- **Candidatos que requieren corrección** (unresolved/weak): {unresolved + weak}",
        f"- **Candidatos a descartar** (invalid/conflict): {conflict}",
        "",
        "> S0131 puede avanzar hacia:",
        "> 1. Diseño del circuito de admisión para el schema `relations-candidate/v1`",
        "> 2. Generación de candidatos desde el corpus real con el validador S0129 activo",
        ">",
        "> S0131 NO debe:",
        "> - Admitir relaciones sin revisar la matriz",
        "> - Generar + admitir en la misma sesión",
        "",
        "_Fin del reporte._",
    ]

    return "\n".join(lines) + "\n"


def build_csv(matrix: list[dict]) -> str:
    """Genera el CSV de revisión humana."""
    fieldnames = [
        "candidate_id",
        "source_title",
        "candidate_target_title",
        "candidate_relation_type",
        "candidate_evidence_kind",
        "candidate_confidence_score",
        "metadata_density",
        "canonical_relations_present",
        "staging_category",
        "correspondence_status",
        "risk_level",
        "recommended_action",
    ]
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for entry in matrix:
        row = {k: entry.get(k, "") for k in fieldnames}
        writer.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Construye matriz de correspondencia relacional (S0130)"
    )
    p.add_argument(
        "--canon-glob",
        default="data/out/local/tiddlers_*.jsonl",
        help="Glob para los shards del canon",
    )
    p.add_argument(
        "--candidates-root",
        default="data/out/local/pipeline/relations_candidates",
        type=Path,
        help="Raíz del staging de candidatos relacionales",
    )
    p.add_argument(
        "--out-dir",
        default="data/out/local/pipeline/relation_correspondence",
        type=Path,
        help="Directorio de salida para los reportes",
    )
    p.add_argument(
        "--session",
        default="s0130",
        help="Etiqueta de sesión para nombres de archivo",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Modo dry-run — obligatorio.",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,  # explícitamente bloqueado
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.apply:
        print("[ERROR] --apply bloqueado: este script nunca escribe en el canon.", file=sys.stderr)
        sys.exit(2)

    tag = args.session.upper()

    print(f"[{tag}] Cargando canon desde: {args.canon_glob}")
    canon = load_canon(args.canon_glob)
    print(f"[{tag}] Canon: {len(canon)} tiddlers")

    print(f"[{tag}] Cargando candidatos desde: {args.candidates_root}")
    if not args.candidates_root.exists():
        print(f"[{tag}] AVISO: staging relacional no encontrado en {args.candidates_root}", file=sys.stderr)
        candidates: list[dict] = []
    else:
        candidates = load_candidates_from_dir(args.candidates_root)
    print(f"[{tag}] Candidatos: {len(candidates)}")

    print(f"[{tag}] Construyendo matriz de correspondencia...")
    matrix = build_matrix(canon, candidates)
    canon_summary = build_canon_metadata_summary(canon)

    # Crear directorio de salida
    session_out = args.out_dir / args.session
    session_out.mkdir(parents=True, exist_ok=True)

    # JSON
    report_json = build_json_report(matrix, canon_summary, args.session, str(args.candidates_root))
    json_path = session_out / f"{args.session}_relation_correspondence_matrix.json"
    json_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{tag}] JSON:     {json_path}")

    # Markdown
    md_path = session_out / f"{args.session}_relation_correspondence_summary.md"
    md_path.write_text(
        build_markdown_summary(matrix, canon_summary, args.session), encoding="utf-8"
    )
    print(f"[{tag}] Markdown: {md_path}")

    # CSV
    csv_path = session_out / f"{args.session}_relation_correspondence_review.csv"
    csv_path.write_text(build_csv(matrix), encoding="utf-8")
    print(f"[{tag}] CSV:      {csv_path}")

    # Garantía de no-escritura en canon
    for p in (Path(p2) for p2 in _glob.glob(args.canon_glob)):
        if p in (json_path, md_path, csv_path):
            print("[ERROR] Colisión de ruta con tiddlers_*.jsonl", file=sys.stderr)
            sys.exit(3)
    print(f"[{tag}] Garantía dry-run: ningún tiddlers_*.jsonl fue modificado.")

    # Resumen
    dist = report_json["matrix_summary"]["correspondence_distribution"]
    print(f"[{tag}] Distribución de correspondencia: {dist}")


if __name__ == "__main__":
    main()
