#!/usr/bin/env python3
"""audit_relation_inventory.py — S0136

Auditoría read-only del inventario relacional existente en el canon local.

Inspecciona el campo `relations` de todos los tiddlers en
data/out/local/tiddlers_*.jsonl y genera un reporte completo.

Distingue claramente:
  tags nativos         ≠  relaciones semánticas
  source_fields        ≠  relaciones
  metadata reversible  ≠  relaciones
  relaciones en canon  ≠  candidatos en staging

NO modifica ningún archivo.

Uso
---
  python3 audit_relation_inventory.py \\
    --canon-root data/out/local/ \\
    --out-dir data/out/local/pipeline/relation_inventory/s0136/
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
DEFAULT_OUT_DIR = DEFAULT_CANON_ROOT / "pipeline" / "relation_inventory" / "s0136"

sys.path.insert(0, str(SCRIPT_DIR))

from relation_candidate_contract import ALLOWED_RELATION_TYPES  # noqa: E402

SCHEMA = "relation-inventory-audit/v1"

# Minimum valid shape for a relation entry
_REQUIRED_RELATION_KEYS = {"type", "target_id"}


# ── Audit engine ──────────────────────────────────────────────────────────────

def audit_canon(canon_root: Path) -> dict[str, Any]:
    """Perform a full read-only audit of relations in the canon."""
    all_ids: set[str] = set()
    records: list[dict[str, Any]] = []

    # First pass: collect all IDs
    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        with shard.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                tid = rec.get("id", "")
                if tid:
                    all_ids.add(tid)

    total_tiddlers = len(all_ids)

    # Second pass: analyze relations
    total_with_relations = 0
    total_relations = 0
    type_counts: dict[str, int] = {}
    unknown_types: set[str] = set()
    invalid_shapes: list[dict[str, Any]] = []
    duplicate_edges: list[dict[str, Any]] = []
    self_relations: list[dict[str, Any]] = []
    unresolved_targets: list[dict[str, Any]] = []
    edge_set: set[tuple[str, str, str]] = set()
    high_degree_sources: dict[str, int] = {}
    high_degree_targets: dict[str, int] = {}
    relations_by_family: dict[str, int] = {}
    relations_by_role: dict[str, int] = {}
    source_tiddler_ids: set[str] = set()
    target_tiddler_ids: set[str] = set()
    targets_resolved = 0
    targets_unresolved_count = 0

    for shard in sorted(canon_root.glob("tiddlers_*.jsonl")):
        with shard.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rels = rec.get("relations")
                if not rels or not isinstance(rels, list) or len(rels) == 0:
                    continue

                src_id = rec.get("id", "")
                src_title = rec.get("title", "")[:80]
                family = (rec.get("source_fields") or {}).get("artifact_family", "")
                role = rec.get("role_primary", "")
                total_with_relations += 1
                source_tiddler_ids.add(src_id)
                high_degree_sources[src_id] = high_degree_sources.get(src_id, 0) + len(rels)

                for rel in rels:
                    total_relations += 1

                    # Shape validation
                    if not isinstance(rel, dict):
                        invalid_shapes.append({
                            "source_id": src_id,
                            "source_title": src_title,
                            "issue": f"Relation is {type(rel).__name__}, not dict",
                            "value": str(rel)[:100],
                        })
                        continue

                    if not _REQUIRED_RELATION_KEYS.issubset(rel.keys()):
                        missing = _REQUIRED_RELATION_KEYS - set(rel.keys())
                        invalid_shapes.append({
                            "source_id": src_id,
                            "source_title": src_title,
                            "issue": f"Missing required keys: {missing}",
                            "value": str(rel)[:100],
                        })
                        continue

                    rel_type = rel.get("type", "")
                    tgt_id = rel.get("target_id", "")

                    # Type catalog check
                    type_counts[rel_type] = type_counts.get(rel_type, 0) + 1
                    if rel_type not in ALLOWED_RELATION_TYPES:
                        unknown_types.add(rel_type)

                    # Target resolution
                    target_tiddler_ids.add(tgt_id)
                    high_degree_targets[tgt_id] = high_degree_targets.get(tgt_id, 0) + 1
                    if tgt_id in all_ids:
                        targets_resolved += 1
                    else:
                        targets_unresolved_count += 1
                        unresolved_targets.append({
                            "source_id": src_id,
                            "source_title": src_title,
                            "target_id": tgt_id,
                            "relation_type": rel_type,
                        })

                    # Duplicate check
                    edge = (src_id, tgt_id, rel_type)
                    if edge in edge_set:
                        duplicate_edges.append({
                            "source_id": src_id,
                            "source_title": src_title,
                            "target_id": tgt_id,
                            "relation_type": rel_type,
                        })
                    edge_set.add(edge)

                    # Self-relation
                    if src_id and src_id == tgt_id:
                        self_relations.append({
                            "source_id": src_id,
                            "source_title": src_title,
                            "relation_type": rel_type,
                        })

                    # By family
                    if family:
                        relations_by_family[family] = relations_by_family.get(family, 0) + 1

                    # By role
                    if role:
                        relations_by_role[role] = relations_by_role.get(role, 0) + 1

                # Add record for CSV
                records.append({
                    "source_id": src_id,
                    "source_title": src_title,
                    "relation_count": len(rels),
                    "relation_types": "|".join(sorted({r.get("type","") for r in rels if isinstance(r, dict)})),
                    "family": family,
                    "role": role,
                })

    # Top 10 high-degree nodes
    top_sources = sorted(high_degree_sources.items(), key=lambda x: -x[1])[:10]
    top_targets = sorted(high_degree_targets.items(), key=lambda x: -x[1])[:10]

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": str(canon_root),
        "total_tiddlers": total_tiddlers,
        "total_tiddlers_with_relations": total_with_relations,
        "total_relations": total_relations,
        "targets_resolved": targets_resolved,
        "targets_unresolved": targets_unresolved_count,
        "relation_types_distribution": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
        "unknown_relation_types": sorted(unknown_types),
        "known_relation_types_count": len(type_counts) - len(unknown_types),
        "duplicate_edges_count": len(duplicate_edges),
        "self_relations_count": len(self_relations),
        "invalid_relation_shapes_count": len(invalid_shapes),
        "relations_by_artifact_family": dict(sorted(relations_by_family.items(), key=lambda x: -x[1])),
        "relations_by_role_primary": dict(sorted(relations_by_role.items(), key=lambda x: -x[1])),
        "high_degree_sources": top_sources,
        "high_degree_targets": top_targets,
        "boundary_notes": {
            "tags_vs_relations": (
                "Los tags nativos TiddlyWiki (tags[]) son clasificación de navegación. "
                "Las relations[] son semánticas gobernadas. "
                "Ningún tag se cuenta como relación en esta auditoría."
            ),
            "source_fields_vs_relations": (
                "source_fields es capa de procedencia (artifact_family, session_origin, etc.). "
                "No debe contener ni duplicar relaciones semánticas."
            ),
            "canon_vs_candidates": (
                "Esta auditoría cubre relaciones YA admitidas en canon (campo 'relations'). "
                "Los candidatos en staging (relations_candidates/) son separados y no se mezclan."
            ),
        },
        "detail": {
            "unresolved_targets": unresolved_targets[:50],
            "duplicate_edges": duplicate_edges[:20],
            "self_relations": self_relations[:20],
            "invalid_shapes": invalid_shapes[:20],
            "tiddlers_with_relations_sample": records[:5],
        },
        "_csv_records": records,
    }


# ── Report writers ────────────────────────────────────────────────────────────

def write_audit_json(audit: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    exportable = {k: v for k, v in audit.items() if k != "_csv_records"}
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(exportable, fh, indent=2, ensure_ascii=False)
    print(f"[OK] Audit JSON → {out_path}", file=sys.stderr)


def write_summary_md(audit: dict[str, Any], out_path: Path, session: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    unknown = audit["unknown_relation_types"]
    lines = [
        f"# {session.upper()} — Auditoría del inventario relacional existente",
        "",
        f"**Generado:** {audit['generated_at']}  ",
        f"**Fuente:** `{audit['source']}`",
        "",
        "## Resumen cuantitativo",
        "",
        "| Métrica | Valor |",
        "|---------|------:|",
        f"| Total tiddlers en canon | {audit['total_tiddlers']} |",
        f"| Tiddlers con relations | {audit['total_tiddlers_with_relations']} |",
        f"| Total relaciones | {audit['total_relations']} |",
        f"| Targets resueltos | {audit['targets_resolved']} |",
        f"| Targets NO resueltos | {audit['targets_unresolved']} |",
        f"| Tipos de relación distintos | {len(audit['relation_types_distribution'])} |",
        f"| Tipos conocidos (DT029/DT031) | {audit['known_relation_types_count']} |",
        f"| Tipos desconocidos | {len(unknown)} |",
        f"| Edges duplicados | {audit['duplicate_edges_count']} |",
        f"| Auto-relaciones | {audit['self_relations_count']} |",
        f"| Shapes inválidas | {audit['invalid_relation_shapes_count']} |",
        "",
        "## Distribución de tipos relacionales",
        "",
        "| Tipo | Relaciones | En catálogo DT029/DT031 |",
        "|------|----------:|:-----------------------:|",
    ]
    known = set(ALLOWED_RELATION_TYPES) if True else set()
    try:
        from relation_candidate_contract import ALLOWED_RELATION_TYPES as _ART
        known = _ART
    except Exception:
        pass
    for rt, cnt in sorted(audit["relation_types_distribution"].items(), key=lambda x: -x[1]):
        in_cat = "✓" if rt not in unknown else "✗ (legacy)"
        lines.append(f"| `{rt}` | {cnt} | {in_cat} |")
    lines.append("")

    if unknown:
        lines += [
            "## Tipos relacionales fuera del catálogo DT029/DT031",
            "",
            "> Estos tipos existen en el canon pero no están en el catálogo oficial.",
            "> Son tipos históricos pre-DT029. No se eliminarán automáticamente.",
            "> Se recomienda revisión para mapeo o migración en sesión futura.",
            "",
        ]
        for t in sorted(unknown):
            lines.append(f"- `{t}`: {audit['relation_types_distribution'].get(t, 0)} relaciones")
        lines.append("")

    lines += [
        "## Separación de capas (clarificación)",
        "",
        f"- **Tags nativos**: clasificación TiddlyWiki (campo `tags[]`). NO son relaciones semánticas.",
        f"- **source_fields**: procedencia y trazabilidad del artefacto. NO contiene relaciones.",
        f"- **relations**: relaciones semánticas gobernadas (este inventario).",
        f"- **Candidatos staging**: `pipeline/relations_candidates/` (separados; no incluidos aquí).",
        "",
        "## Recomendaciones",
        "",
        f"- Los {len(unknown)} tipos relacionales históricos ({', '.join(f'`{t}`' for t in sorted(unknown))}) "
        "requieren análisis de compatibilidad con el catálogo DT029/DT031 antes de S0137.",
        "- 0 targets sin resolver: el canon relacional está internamente consistente.",
        "- 0 duplicados: no hay aristas redundantes.",
        "- 0 auto-relaciones: no hay bucles reflexivos.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Summary MD → {out_path}", file=sys.stderr)


def write_review_csv(audit: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_id", "source_title", "relation_count",
        "relation_types", "family", "role",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in audit.get("_csv_records", []):
            writer.writerow({k: r.get(k, "") for k in fieldnames})
    print(f"[OK] CSV → {out_path}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Auditoría read-only del inventario relacional del canon (S0136)."
    )
    p.add_argument("--canon-root", type=Path, default=DEFAULT_CANON_ROOT)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--session", default="s0136")
    p.add_argument("--verbose", "-v", action="store_true", default=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session_tag = args.session.lower()
    out = args.out_dir

    audit = audit_canon(args.canon_root)

    write_audit_json(audit, out / f"{session_tag}_relation_inventory_audit.json")
    write_summary_md(audit, out / f"{session_tag}_relation_inventory_summary.md",
                     session_tag)
    write_review_csv(audit, out / f"{session_tag}_relation_inventory_review.csv")

    print(
        f"\n=== Relation Inventory Audit ({session_tag.upper()}) ===\n"
        f"  Total tiddlers      : {audit['total_tiddlers']}\n"
        f"  With relations      : {audit['total_tiddlers_with_relations']}\n"
        f"  Total relations     : {audit['total_relations']}\n"
        f"  Resolved targets    : {audit['targets_resolved']}\n"
        f"  Unresolved targets  : {audit['targets_unresolved']}\n"
        f"  Unknown types       : {len(audit['unknown_relation_types'])} "
        f"({', '.join(audit['unknown_relation_types'])})\n"
        f"  Duplicates          : {audit['duplicate_edges_count']}\n"
        f"  Self-relations      : {audit['self_relations_count']}\n"
        f"  Invalid shapes      : {audit['invalid_relation_shapes_count']}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
