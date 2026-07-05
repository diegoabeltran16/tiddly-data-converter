#!/usr/bin/env python3
"""analyze_relation_type_compatibility.py — S0137

Análisis de compatibilidad de tipos relacionales históricos vs catálogo DT029/DT031.

Lee el canon en modo read-only y clasifica los tipos relacionales existentes:
  - Tipos formales del catálogo DT029/DT031
  - Tipos históricos fuera del catálogo: usa, parte_de, define, requiere, child_of

Clasificación por tipo:
  formal_catalog_type       — está en el catálogo DT029/DT031
  legacy_compatible         — semánticamente compatible; puede usarse como alias
  legacy_alias_candidate    — candidato a mapear a tipo formal (revisión recomendada)
  legacy_readonly           — conservar en canon histórico; bloqueado para nuevos
  requires_catalog_extension— no tiene equivalente; el catálogo debería ampliarse
  blocked_for_new_candidates— no puede usarse en nuevos candidatos relacionales
  requires_human_review     — ambigüedad semántica; requiere decisión humana

NO modifica ningún archivo del canon.

Uso
---
  python3 analyze_relation_type_compatibility.py \\
    --canon-root data/out/local/ \\
    --out-dir data/out/local/pipeline/relation_type_compatibility/s0137/
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CANON_ROOT = REPO_ROOT / "data" / "out" / "local"
DEFAULT_OUT_DIR = DEFAULT_CANON_ROOT / "pipeline" / "relation_type_compatibility" / "s0137"

sys.path.insert(0, str(SCRIPT_DIR))

from relation_candidate_contract import ALLOWED_RELATION_TYPES  # noqa: E402

SCHEMA = "relation-type-compatibility/v1"

# ── Tipo de clasificación ─────────────────────────────────────────────────────

FORMAL_CATALOG_TYPE = "formal_catalog_type"
LEGACY_COMPATIBLE = "legacy_compatible"
LEGACY_ALIAS_CANDIDATE = "legacy_alias_candidate"
LEGACY_READONLY = "legacy_readonly"
REQUIRES_CATALOG_EXTENSION = "requires_catalog_extension"
BLOCKED_FOR_NEW_CANDIDATES = "blocked_for_new_candidates"
REQUIRES_HUMAN_REVIEW = "requires_human_review"

# ── Definición estática del análisis de tipos históricos ─────────────────────
# Basado en DT029 (tipología mínima) + DT031 (contrato de salida) + S0136 (auditoría)

HISTORICAL_TYPE_ANALYSIS: dict[str, dict[str, Any]] = {
    "usa": {
        "classification": LEGACY_ALIAS_CANDIDATE,
        "catalog_mapping": "references",
        "semantic_note": (
            "'usa' es una relación de uso/dependencia funcional entre tiddlers. "
            "Semánticamente compatible con 'references' (uso explícito) o 'related_to' "
            "(dependencia general). Predomina en artefactos config y glossary."
        ),
        "decision": (
            "Tratar como alias de 'references' para nuevos candidatos. "
            "Conservar en canon histórico sin reescribir. "
            "Bloqueado para nuevos candidatos hasta que el catálogo lo formalice."
        ),
        "blocked_for_new": True,
        "requires_catalog_update": True,
        "affected_roles": ["config", "glossary", "evidence"],
    },
    "parte_de": {
        "classification": LEGACY_READONLY,
        "catalog_mapping": None,
        "semantic_note": (
            "'parte_de' es una relación de composición/pertenencia estructural. "
            "No tiene equivalente directo en el catálogo DT029/DT031. "
            "Predomina en artefactos config y glossary. "
            "Semánticamente diferente de 'child_of' (que es más jerárquico)."
        ),
        "decision": (
            "Conservar en canon histórico (162 relaciones). "
            "No crear nuevos candidatos con este tipo. "
            "Si se necesita composición en nuevos candidatos, usar 'related_to' "
            "con label descriptivo hasta que el catálogo se amplíe."
        ),
        "blocked_for_new": True,
        "requires_catalog_update": False,
        "affected_roles": ["config", "glossary"],
    },
    "define": {
        "classification": LEGACY_READONLY,
        "catalog_mapping": None,
        "semantic_note": (
            "'define' es una relación de definición/declaración. "
            "No tiene equivalente directo en el catálogo. "
            "Predomina en artefactos glossary y config. "
            "Distinto de 'valida' (validación) y 'references' (referencia)."
        ),
        "decision": (
            "Conservar en canon histórico (55 relaciones). "
            "No crear nuevos candidatos con este tipo. "
            "Para nuevos candidatos de definición, usar 'related_to' "
            "o proponer extensión formal del catálogo."
        ),
        "blocked_for_new": True,
        "requires_catalog_update": False,
        "affected_roles": ["glossary", "config"],
    },
    "requiere": {
        "classification": LEGACY_ALIAS_CANDIDATE,
        "catalog_mapping": "depende_de",
        "semantic_note": (
            "'requiere' es una relación de dependencia necesaria. "
            "Semánticamente equivalente a 'depende_de' del catálogo DT029 (P1). "
            "Predomina en artefactos config y glossary. "
            "IMPORTANTE: 'depende_de' es tipo P1, que siempre requiere revisión humana "
            "per DT036 — la misma política debe aplicar a 'requiere' histórico."
        ),
        "decision": (
            "Tratar como alias de 'depende_de' en nuevos candidatos. "
            "Conservar en canon histórico sin reescribir. "
            "Bloqueado para nuevos candidatos; usar 'depende_de' con revisión humana obligatoria."
        ),
        "blocked_for_new": True,
        "requires_catalog_update": True,
        "affected_roles": ["config", "glossary", "evidence"],
    },
    "child_of": {
        "classification": LEGACY_READONLY,
        "catalog_mapping": None,
        "semantic_note": (
            "'child_of' es una relación jerárquica padre-hijo. "
            "No tiene equivalente directo en el catálogo DT029/DT031. "
            "Principalmente en artefactos evidence, glossary y config. "
            "Similar a 'parte_de' pero con connotación jerárquica más explícita."
        ),
        "decision": (
            "Conservar en canon histórico (31 relaciones). "
            "No crear nuevos candidatos con este tipo. "
            "Si se necesita jerarquía en nuevos candidatos, evaluar extensión del catálogo."
        ),
        "blocked_for_new": True,
        "requires_catalog_update": False,
        "affected_roles": ["evidence", "glossary", "config"],
    },
}

# ── Canon reader ──────────────────────────────────────────────────────────────

def scan_canon_relations(canon_root: Path) -> dict[str, Any]:
    """Scan all canon tiddlers and collect relation type statistics."""
    all_ids: set[str] = set()
    type_counts: dict[str, int] = {}
    type_by_role: dict[str, dict[str, int]] = {}
    type_by_family: dict[str, dict[str, int]] = {}
    canon_files: list[str] = []
    total_tiddlers = 0
    total_relations = 0

    # Collect all IDs first
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        canon_files.append(str(shard.relative_to(REPO_ROOT) if shard.is_relative_to(REPO_ROOT) else shard))
        with shard.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                all_ids.add(rec.get("id", ""))
                total_tiddlers += 1

    # Analyze relations
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        with shard.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rels = rec.get("relations") or []
                if not rels:
                    continue
                role = rec.get("role_primary", "") or ""
                sf = rec.get("source_fields") or {}
                family = sf.get("artifact_family", "") or ""

                for r in rels:
                    if not isinstance(r, dict):
                        continue
                    rt = r.get("type", "")
                    if not rt:
                        continue
                    total_relations += 1
                    type_counts[rt] = type_counts.get(rt, 0) + 1
                    if rt not in type_by_role:
                        type_by_role[rt] = {}
                    type_by_role[rt][role] = type_by_role[rt].get(role, 0) + 1
                    if rt not in type_by_family:
                        type_by_family[rt] = {}
                    if family:
                        type_by_family[rt][family] = type_by_family[rt].get(family, 0) + 1

    return {
        "canon_files": canon_files,
        "total_tiddlers": total_tiddlers,
        "total_relations": total_relations,
        "type_counts": type_counts,
        "type_by_role": type_by_role,
        "type_by_family": type_by_family,
    }


# ── Compatibility analyzer ────────────────────────────────────────────────────

def analyze_compatibility(scan: dict[str, Any]) -> dict[str, Any]:
    """Build the full compatibility analysis."""
    type_counts = scan["type_counts"]
    type_by_role = scan["type_by_role"]
    type_by_family = scan["type_by_family"]

    historical_types: dict[str, Any] = {}
    decisions: list[dict[str, Any]] = []
    blocking_findings: list[str] = []
    recommendations: list[str] = []

    for rt, meta in HISTORICAL_TYPE_ANALYSIS.items():
        count = type_counts.get(rt, 0)
        entry = {
            "type": rt,
            "count_in_canon": count,
            "classification": meta["classification"],
            "catalog_mapping": meta["catalog_mapping"],
            "blocked_for_new_candidates": meta["blocked_for_new"],
            "requires_catalog_update": meta["requires_catalog_update"],
            "semantic_note": meta["semantic_note"],
            "decision": meta["decision"],
            "distribution_by_role": type_by_role.get(rt, {}),
            "distribution_by_family": type_by_family.get(rt, {}),
        }
        historical_types[rt] = entry

        decisions.append({
            "type": rt,
            "count": count,
            "action": meta["classification"],
            "mapping": meta["catalog_mapping"],
            "blocked_for_new": meta["blocked_for_new"],
        })

        if meta["blocked_for_new"]:
            blocking_findings.append(
                f"'{rt}' ({count} relaciones) — bloqueado para nuevos candidatos. "
                f"Clasificación: {meta['classification']}."
            )

    # Catalog types found/not found
    catalog_comparison: dict[str, Any] = {}
    for ct in sorted(ALLOWED_RELATION_TYPES):
        count = type_counts.get(ct, 0)
        catalog_comparison[ct] = {
            "count_in_canon": count,
            "classification": FORMAL_CATALOG_TYPE,
        }

    # Types found in canon but not in catalog or historical analysis
    all_known = set(ALLOWED_RELATION_TYPES) | set(HISTORICAL_TYPE_ANALYSIS.keys())
    unaccounted = {rt: cnt for rt, cnt in type_counts.items() if rt not in all_known}

    # Recommendations
    total_hist = sum(type_counts.get(rt, 0) for rt in HISTORICAL_TYPE_ANALYSIS)
    total_cat = sum(type_counts.get(rt, 0) for rt in ALLOWED_RELATION_TYPES)
    recommendations.append(
        f"Los 5 tipos históricos suman {total_hist} relaciones ({total_hist/(scan['total_relations'] or 1)*100:.1f}% del total). "
        "Ninguno debe usarse en nuevos candidatos relacionales."
    )
    recommendations.append(
        f"Solo 'references' ({type_counts.get('references', 0)} relaciones) "
        "del catálogo formal está presente en el canon histórico."
    )
    recommendations.append(
        "'usa' y 'requiere' son candidatos a alias formales ('references' y 'depende_de' "
        "respectivamente). Requieren decisión explícita en catálogo antes de S0138."
    )
    recommendations.append(
        "'parte_de', 'define' y 'child_of' no tienen equivalente directo en DT029/DT031. "
        "Se recomienda conservarlos como legacy_readonly sin ampliar el catálogo."
    )
    recommendations.append(
        "Para S0138 (compuerta humana): el validador debe rechazar candidatos con tipos "
        "históricos y exigir que los nuevos candidatos usen solo tipos del catálogo formal."
    )

    return {
        "schema": SCHEMA,
        "session": "S0137",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "canon_files_scanned": scan["canon_files"],
        "total_tiddlers_scanned": scan["total_tiddlers"],
        "total_relations_found": scan["total_relations"],
        "catalog_types_in_canon": {
            rt: type_counts.get(rt, 0) for rt in sorted(ALLOWED_RELATION_TYPES)
        },
        "historical_relation_types": historical_types,
        "catalog_comparison": catalog_comparison,
        "unaccounted_types": unaccounted,
        "decisions": decisions,
        "blocking_findings": blocking_findings,
        "recommendations": recommendations,
        "summary": {
            "total_historical_relations": total_hist,
            "total_catalog_relations": total_cat,
            "total_unaccounted_relations": sum(unaccounted.values()),
            "all_historical_blocked_for_new": all(
                meta["blocked_for_new"] for meta in HISTORICAL_TYPE_ANALYSIS.values()
            ),
        },
    }


# ── Report writers ────────────────────────────────────────────────────────────

def write_report_json(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Reporte JSON → {out_path}", file=sys.stderr)


def write_summary_md(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hist = report["historical_relation_types"]
    s = report["summary"]

    lines = [
        "# S0137 — Compatibilidad de tipos relacionales históricos",
        "",
        f"**Generado:** {report['generated_at']}",
        "",
        "## Resumen ejecutivo",
        "",
        f"| Métrica | Valor |",
        f"|---------|------:|",
        f"| Total tiddlers escaneados | {report['total_tiddlers_scanned']} |",
        f"| Total relaciones en canon | {report['total_relations_found']} |",
        f"| Relaciones con tipos históricos | {s['total_historical_relations']} |",
        f"| Relaciones con tipos del catálogo | {s['total_catalog_relations']} |",
        f"| Todos los tipos históricos bloqueados para nuevos | {'Sí' if s['all_historical_blocked_for_new'] else 'No'} |",
        "",
        "## Clasificación de tipos históricos",
        "",
        "| Tipo | Relaciones | Clasificación | Mapa a catálogo | Bloqueado nuevo |",
        "|------|----------:|---------------|-----------------|:---------------:|",
    ]
    for rt, d in sorted(hist.items(), key=lambda x: -x[1]["count_in_canon"]):
        mapping = d["catalog_mapping"] or "—"
        blocked = "✓" if d["blocked_for_new_candidates"] else "✗"
        lines.append(
            f"| `{rt}` | {d['count_in_canon']} "
            f"| `{d['classification']}` "
            f"| `{mapping}` "
            f"| {blocked} |"
        )
    lines.append("")

    lines += [
        "## Tipos del catálogo formal (DT029/DT031)",
        "",
        "| Tipo | Relaciones en canon |",
        "|------|--------------------:|",
    ]
    for rt, cnt in sorted(report["catalog_types_in_canon"].items(), key=lambda x: -x[1]):
        lines.append(f"| `{rt}` | {cnt} |")
    lines.append("")

    lines += ["## Decisiones por tipo", ""]
    for d in report["decisions"]:
        lines.append(f"### `{d['type']}` ({d['count']} relaciones)")
        meta = hist[d["type"]]
        lines.append(f"- **Clasificación**: `{d['action']}`")
        lines.append(f"- **Mapa a catálogo**: `{d['mapping'] or 'ninguno'}`")
        lines.append(f"- **Decisión**: {meta['decision']}")
        lines.append("")

    lines += ["## Recomendaciones", ""]
    for r in report["recommendations"]:
        lines.append(f"- {r}")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Resumen MD → {out_path}", file=sys.stderr)


def write_review_csv(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hist = report["historical_relation_types"]
    # Add catalog types
    all_types = {}
    for rt, cnt in report["catalog_types_in_canon"].items():
        all_types[rt] = {
            "count": cnt,
            "classification": FORMAL_CATALOG_TYPE,
            "catalog_mapping": rt,
            "blocked_for_new": False,
            "decision": "Usar normalmente para nuevos candidatos.",
        }
    for rt, d in hist.items():
        all_types[rt] = {
            "count": d["count_in_canon"],
            "classification": d["classification"],
            "catalog_mapping": d["catalog_mapping"] or "",
            "blocked_for_new": d["blocked_for_new_candidates"],
            "decision": d["decision"][:150],
        }

    fieldnames = ["type", "count_in_canon", "classification", "catalog_mapping",
                  "blocked_for_new_candidates", "decision"]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for rt, d in sorted(all_types.items(), key=lambda x: -x[1]["count"]):
            writer.writerow({
                "type": rt,
                "count_in_canon": d["count"],
                "classification": d["classification"],
                "catalog_mapping": d["catalog_mapping"],
                "blocked_for_new_candidates": d["blocked_for_new"],
                "decision": d["decision"],
            })
    print(f"[OK] CSV → {out_path}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Análisis de compatibilidad de tipos relacionales históricos (S0137)."
    )
    p.add_argument("--canon-root", type=Path, default=DEFAULT_CANON_ROOT)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--session", default="s0137")
    p.add_argument("--verbose", "-v", action="store_true", default=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session_tag = args.session.lower()
    out = args.out_dir

    scan = scan_canon_relations(args.canon_root)
    if args.verbose:
        print(f"  Shards escaneados: {len(scan['canon_files'])}", file=sys.stderr)
        print(f"  Tiddlers: {scan['total_tiddlers']}, Relaciones: {scan['total_relations']}",
              file=sys.stderr)

    report = analyze_compatibility(scan)

    write_report_json(report, out / f"{session_tag}_relation_type_compatibility_report.json")
    write_summary_md(report, out / f"{session_tag}_relation_type_compatibility_summary.md")
    write_review_csv(report, out / f"{session_tag}_relation_type_compatibility_review.csv")

    s = report["summary"]
    print(
        f"\n=== Relation Type Compatibility ({session_tag.upper()}) ===\n"
        f"  Total relaciones   : {report['total_relations_found']}\n"
        f"  Tipos históricos   : {s['total_historical_relations']}\n"
        f"  Tipos catálogo     : {s['total_catalog_relations']}\n"
        f"  Todos bloqueados   : {s['all_historical_blocked_for_new']}\n"
    )
    for d in report["decisions"]:
        print(f"  {d['type']:<12} → {d['action']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
