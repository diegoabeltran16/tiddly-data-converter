#!/usr/bin/env python3
"""Build the S0139 historical relation type governance reports.

The script reads canonical `relations` from `data/out/local/tiddlers_*.jsonl`
and writes a decision bundle under a pipeline output directory. It never writes
to canon shards, never applies aliases, and never admits relation candidates.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))

try:
    from relation_candidate_contract import ALLOWED_RELATION_TYPES
except ImportError:  # pragma: no cover
    ALLOWED_RELATION_TYPES = frozenset()

try:
    from relation_admission_policy import EVIDENCE_POLICY, POLICY_TYPE_ALIASES
except ImportError:  # pragma: no cover
    EVIDENCE_POLICY = {}
    POLICY_TYPE_ALIASES = {}


SCHEMA_INVENTORY = "historical-relation-type-inventory/v1"
SCHEMA_DECISIONS = "historical-relation-type-decisions/v1"
SCHEMA_PREVIEW = "historical-relation-type-migration-preview/v1"

MANDATORY_HISTORICAL_TYPES: tuple[str, ...] = (
    "usa",
    "requiere",
    "parte_de",
    "define",
    "child_of",
)

DECISION_STATES: dict[str, str] = {
    "canonical_keep": (
        "El tipo puede mantenerse como tipo canonico valido sin migracion."
    ),
    "legacy_readonly": (
        "El tipo se conserva para lectura historica, pero no debe usarse en "
        "nuevas relaciones."
    ),
    "legacy_alias_candidate": (
        "El tipo parece equivalente a un tipo moderno, pero requiere revision "
        "antes de migrar."
    ),
    "canonical_equivalent": (
        "El tipo tiene equivalencia gobernada con un tipo moderno, pero la "
        "migracion no se aplica en S0139."
    ),
    "deprecated_blocked": (
        "El tipo no debe usarse ni migrarse sin intervencion humana especifica."
    ),
    "structural_only": (
        "El tipo expresa estructura de TiddlyWiki o jerarquia tecnica, no "
        "relacion semantica directa."
    ),
    "requires_human_decision": (
        "La evidencia no alcanza para decidir automaticamente."
    ),
    "unknown_legacy": (
        "Tipo encontrado en canon sin politica previa ni equivalencia segura."
    ),
}

HISTORICAL_POLICY: dict[str, dict[str, Any]] = {
    "usa": {
        "decision_status": "legacy_alias_candidate",
        "proposed_canonical_type": "references",
        "direction_preserved": "true",
        "requires_human_review": True,
        "risk_level": "medium",
        "category": "historical_dependency_or_use",
        "new_candidate_policy": "blocked_use_modern_catalog_type",
        "rationale": (
            "`usa` expresa uso o referencia historica desde source hacia target. "
            "La direccion source->target se conserva para un posible mapeo a "
            "`references`, pero la semantica de uso no equivale siempre a una "
            "referencia textual moderna."
        ),
        "s0141_rule": (
            "Describir como relacion historica de uso; no emitir como "
            "equivalencia definitiva con `references` en semantic_text."
        ),
    },
    "requiere": {
        "decision_status": "legacy_alias_candidate",
        "proposed_canonical_type": "depende_de",
        "direction_preserved": "true",
        "requires_human_review": True,
        "risk_level": "high",
        "category": "historical_dependency",
        "new_candidate_policy": "blocked_use_depende_de_with_human_review",
        "rationale": (
            "`requiere` apunta a dependencia necesaria desde source hacia target. "
            "El mapeo conceptual a `depende_de` preserva direccion, pero "
            "`depende_de` es de mayor riesgo y exige revision humana."
        ),
        "s0141_rule": (
            "No describir como `depende_de` definitiva hasta que una migracion "
            "gobernada revise evidencia y direccion."
        ),
    },
    "parte_de": {
        "decision_status": "legacy_alias_candidate",
        "proposed_canonical_type": "part_of",
        "direction_preserved": "true",
        "requires_human_review": True,
        "risk_level": "medium",
        "category": "historical_composition",
        "new_candidate_policy": "blocked_until_part_of_contract_is_aligned",
        "rationale": (
            "`parte_de` expresa composicion o pertenencia desde source hacia "
            "target. La politica S0131 reconoce `part_of`, pero el contrato de "
            "candidatos S0129 no lo expone de forma uniforme; por eso queda "
            "como alias candidato, no como equivalencia aplicada."
        ),
        "s0141_rule": (
            "Marcar como composicion historica; no mezclar con relaciones "
            "candidatas modernas ni con tags nativos."
        ),
    },
    "define": {
        "decision_status": "legacy_readonly",
        "proposed_canonical_type": "",
        "direction_preserved": "not_applicable",
        "requires_human_review": True,
        "risk_level": "medium",
        "category": "historical_definition",
        "new_candidate_policy": "blocked_pending_catalog_extension_or_review",
        "rationale": (
            "`define` conserva valor documental como declaracion historica de "
            "definicion, pero el catalogo moderno no tiene un tipo de definicion "
            "estable equivalente. No se promueve automaticamente."
        ),
        "s0141_rule": (
            "Puede describirse como relacion historica de definicion, no como "
            "relacion moderna admitida."
        ),
    },
    "child_of": {
        "decision_status": "structural_only",
        "proposed_canonical_type": "",
        "direction_preserved": "not_applicable",
        "requires_human_review": True,
        "risk_level": "medium",
        "category": "historical_structure",
        "new_candidate_policy": "blocked_as_semantic_candidate",
        "rationale": (
            "`child_of` expresa jerarquia o estructura historica. No debe "
            "convertirse automaticamente en dependencia semantica moderna."
        ),
        "s0141_rule": (
            "Marcar como estructura historica o jerarquica, no como dependencia "
            "semantica."
        ),
    },
}


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def modern_relation_types() -> set[str]:
    return set(ALLOWED_RELATION_TYPES) | set(EVIDENCE_POLICY)


def load_canon_records(canon_glob: str) -> tuple[list[Path], list[dict[str, Any]]]:
    paths = [Path(p) for p in sorted(glob.glob(canon_glob))]
    records: list[dict[str, Any]] = []
    for shard in paths:
        with shard.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{shard}:{line_no}: invalid JSON: {exc}") from exc
                if isinstance(rec, dict):
                    rec["_s0139_source_shard"] = repo_relative(shard)
                    rec["_s0139_source_line"] = line_no
                    records.append(rec)
    return paths, records


def build_indexes(records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    for rec in records:
        if rec.get("id"):
            by_id[str(rec["id"])] = rec
        if rec.get("title"):
            by_title[str(rec["title"])] = rec
        if rec.get("key"):
            by_key[str(rec["key"])] = rec
    return {"by_id": by_id, "by_title": by_title, "by_key": by_key}


def relation_target_ref(rel: dict[str, Any]) -> tuple[str, str]:
    for field in ("target_id", "target", "target_title", "target_key"):
        value = rel.get(field)
        if value:
            return field, str(value)
    return "", ""


def resolve_target(rel: dict[str, Any], indexes: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    ref_field, ref_value = relation_target_ref(rel)
    if not ref_value:
        return {
            "target_ref_field": ref_field,
            "target_ref": ref_value,
            "resolution_status": "unresolved_no_target_ref",
            "target_id": "",
            "target_title": "",
        }

    target: dict[str, Any] | None = None
    if ref_field == "target_id":
        target = indexes["by_id"].get(ref_value)
    elif ref_field in {"target", "target_title"}:
        target = indexes["by_title"].get(ref_value) or indexes["by_id"].get(ref_value)
    elif ref_field == "target_key":
        target = indexes["by_key"].get(ref_value) or indexes["by_title"].get(ref_value)

    if target:
        return {
            "target_ref_field": ref_field,
            "target_ref": ref_value,
            "resolution_status": "resolved",
            "target_id": target.get("id") or "",
            "target_title": target.get("title") or target.get("key") or "",
        }

    return {
        "target_ref_field": ref_field,
        "target_ref": ref_value,
        "resolution_status": "unresolved",
        "target_id": ref_value if ref_field == "target_id" else "",
        "target_title": ref_value if ref_field in {"target", "target_title", "target_key"} else "",
    }


def compact_example(
    source: dict[str, Any],
    rel: dict[str, Any],
    target_resolution: dict[str, Any],
    relation_index: int,
) -> dict[str, Any]:
    return {
        "source_id": source.get("id") or "",
        "source_title": source.get("title") or source.get("key") or "",
        "source_role_primary": source.get("role_primary") or "",
        "source_shard": source.get("_s0139_source_shard") or "",
        "source_line": source.get("_s0139_source_line") or 0,
        "relation_index": relation_index,
        "relation_type": rel.get("type") or "",
        "target_ref_field": target_resolution["target_ref_field"],
        "target_ref": target_resolution["target_ref"],
        "target_id": target_resolution["target_id"],
        "target_title": target_resolution["target_title"],
        "resolution_status": target_resolution["resolution_status"],
    }


def scan_canon_relations(canon_glob: str, *, example_limit: int = 5) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    paths, records = load_canon_records(canon_glob)
    indexes = build_indexes(records)
    modern_types = modern_relation_types()

    type_counts: Counter[str] = Counter()
    type_by_role: dict[str, Counter[str]] = defaultdict(Counter)
    type_by_source_shard: dict[str, Counter[str]] = defaultdict(Counter)
    examples_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_resolution_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    relation_entries: list[dict[str, Any]] = []
    invalid_relation_shapes: list[dict[str, Any]] = []
    tiddlers_with_relations = 0
    total_relations_seen = 0

    for rec in records:
        rels = rec.get("relations") or []
        if not isinstance(rels, list) or not rels:
            continue
        tiddlers_with_relations += 1
        for idx, rel in enumerate(rels):
            total_relations_seen += 1
            if not isinstance(rel, dict):
                invalid_relation_shapes.append({
                    "source_id": rec.get("id") or "",
                    "source_title": rec.get("title") or rec.get("key") or "",
                    "relation_index": idx,
                    "value_type": type(rel).__name__,
                })
                continue
            rel_type = str(rel.get("type") or "").strip()
            if not rel_type:
                rel_type = "<missing_type>"
            target_resolution = resolve_target(rel, indexes)
            example = compact_example(rec, rel, target_resolution, idx)
            entry = dict(example)
            entry["raw_relation"] = {k: v for k, v in rel.items() if k in {"type", "target_id", "target", "target_title", "target_key", "evidence"}}
            relation_entries.append(entry)

            type_counts[rel_type] += 1
            role = str(rec.get("role_primary") or "unknown")
            type_by_role[rel_type][role] += 1
            type_by_source_shard[rel_type][str(rec.get("_s0139_source_shard") or "")] += 1
            target_resolution_by_type[rel_type][target_resolution["resolution_status"]] += 1
            if len(examples_by_type[rel_type]) < example_limit:
                examples_by_type[rel_type].append(example)

    relation_types: dict[str, Any] = {}
    for rel_type, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0])):
        relation_types[rel_type] = {
            "count": count,
            "modern_recognized": rel_type in modern_types,
            "modern_sources": modern_sources_for_type(rel_type),
            "mandatory_historical": rel_type in MANDATORY_HISTORICAL_TYPES,
            "known_historical_policy": rel_type in HISTORICAL_POLICY,
            "distribution_by_role_primary": dict(sorted(type_by_role[rel_type].items())),
            "distribution_by_source_shard": dict(sorted(type_by_source_shard[rel_type].items())),
            "target_resolution": dict(sorted(target_resolution_by_type[rel_type].items())),
            "examples": examples_by_type.get(rel_type, []),
        }

    target_resolution_summary = Counter()
    for counter in target_resolution_by_type.values():
        target_resolution_summary.update(counter)

    inventory = {
        "schema": SCHEMA_INVENTORY,
        "session": "S0139",
        "generated_at": utc_now(),
        "dry_run": True,
        "canon_modified": False,
        "canon_glob": canon_glob,
        "canon_files_scanned": [repo_relative(p) for p in paths],
        "total_tiddlers_scanned": len(records),
        "total_tiddlers_with_relations": tiddlers_with_relations,
        "total_relations_seen": total_relations_seen,
        "distinct_relation_types_seen": len(type_counts),
        "relation_type_counts": dict(type_counts.most_common()),
        "relation_types": relation_types,
        "target_resolution_summary": dict(sorted(target_resolution_summary.items())),
        "invalid_relation_shapes": invalid_relation_shapes,
        "modern_catalog_sources": {
            "relation_candidate_contract_allowed": sorted(ALLOWED_RELATION_TYPES),
            "relation_admission_policy_evidence": sorted(EVIDENCE_POLICY),
        },
        "boundary_notes": {
            "tags_native_not_relations": True,
            "source_fields_not_relations": True,
            "historical_relation_not_modern_candidate": True,
            "alias_proposal_not_migration": True,
        },
    }
    return inventory, relation_entries


def modern_sources_for_type(rel_type: str) -> list[str]:
    sources: list[str] = []
    if rel_type in ALLOWED_RELATION_TYPES:
        sources.append("relation_candidate_contract.ALLOWED_RELATION_TYPES")
    if rel_type in EVIDENCE_POLICY:
        sources.append("relation_admission_policy.EVIDENCE_POLICY")
    return sources


def decision_for_type(rel_type: str, inventory: dict[str, Any]) -> dict[str, Any]:
    type_info = inventory["relation_types"].get(rel_type, {})
    count = int(type_info.get("count") or 0)
    examples = type_info.get("examples") or []

    if rel_type in HISTORICAL_POLICY:
        base = dict(HISTORICAL_POLICY[rel_type])
    elif rel_type in modern_relation_types():
        base = {
            "decision_status": "canonical_keep",
            "proposed_canonical_type": rel_type,
            "direction_preserved": "true",
            "requires_human_review": False,
            "risk_level": "low",
            "category": "modern_recognized",
            "new_candidate_policy": "allowed_by_modern_policy",
            "rationale": (
                f"`{rel_type}` is present in the modern relation policy and can "
                "remain canonical without S0139 migration."
            ),
            "s0141_rule": "Puede entrar en representacion semantica deterministica.",
        }
    elif rel_type in POLICY_TYPE_ALIASES:
        canonical = POLICY_TYPE_ALIASES[rel_type]
        base = {
            "decision_status": "legacy_alias_candidate",
            "proposed_canonical_type": canonical,
            "direction_preserved": "requires_review",
            "requires_human_review": True,
            "risk_level": "high",
            "category": "policy_alias_seen_in_canon",
            "new_candidate_policy": "blocked_until_human_decision",
            "rationale": (
                f"`{rel_type}` appears as a policy alias for `{canonical}`, but "
                "S0139 does not apply aliases to canon."
            ),
            "s0141_rule": "No emitir como equivalencia definitiva.",
        }
    else:
        base = {
            "decision_status": "unknown_legacy",
            "proposed_canonical_type": "",
            "direction_preserved": "unknown",
            "requires_human_review": True,
            "risk_level": "high",
            "category": "unknown_legacy",
            "new_candidate_policy": "blocked_until_policy_exists",
            "rationale": (
                f"`{rel_type}` no tiene politica S0139 ni reconocimiento moderno. "
                "Debe quedar como legacy desconocido o pasar a decision humana."
            ),
            "s0141_rule": "No usar en semantic_text como relacion moderna.",
        }

    decision = {
        "relation_type": rel_type,
        "count_in_canon": count,
        "decision_status": base["decision_status"],
        "proposed_canonical_type": base["proposed_canonical_type"],
        "direction_preserved": base["direction_preserved"],
        "requires_human_review": base["requires_human_review"],
        "risk_level": base["risk_level"],
        "category": base["category"],
        "new_candidate_policy": base["new_candidate_policy"],
        "alias_applied": False,
        "migration_allowed_in_s0139": False,
        "applied_to_canon": False,
        "canon_modified": False,
        "rationale": base["rationale"],
        "s0140_implication": (
            "S0140 debe evaluar candidatos con esta politica como contexto de "
            "tipos, sin asumir que la decision de tipo aprueba candidatos."
        ),
        "s0141_rule": base["s0141_rule"],
        "target_resolution": type_info.get("target_resolution") or {},
        "examples": examples,
    }
    return decision


def build_decisions(inventory: dict[str, Any]) -> dict[str, Any]:
    seen_types = set(inventory["relation_types"])
    all_types = seen_types | set(MANDATORY_HISTORICAL_TYPES)
    ordered_types = sorted(
        all_types,
        key=lambda rt: (-(inventory["relation_types"].get(rt, {}).get("count") or 0), rt),
    )
    decisions = [decision_for_type(rt, inventory) for rt in ordered_types]
    decisions_by_type = {d["relation_type"]: d for d in decisions}
    return {
        "schema": SCHEMA_DECISIONS,
        "session": "S0139",
        "generated_at": utc_now(),
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "alias_applied_to_canon": False,
        "migration_allowed_in_s0139": False,
        "decision_state_definitions": DECISION_STATES,
        "mandatory_historical_types": list(MANDATORY_HISTORICAL_TYPES),
        "decisions": decisions,
        "decisions_by_type": decisions_by_type,
        "policy_assertions": {
            "historical_relation_not_modern_candidate": True,
            "type_decision_not_candidate_approval": True,
            "native_tags_not_relation_evidence_by_themselves": True,
            "human_review_not_performed_in_s0139": True,
            "relations_admitted_in_s0139": False,
        },
    }


def build_alias_rows(decisions: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in decisions["decisions"]:
        examples = decision.get("examples") or []
        example = examples[0] if examples else {}
        proposed = decision.get("proposed_canonical_type") or ""
        rows.append({
            "legacy_type": decision["relation_type"],
            "proposed_canonical_type": proposed,
            "decision_status": decision["decision_status"],
            "direction_preserved": decision["direction_preserved"],
            "requires_human_review": str(bool(decision["requires_human_review"])).lower(),
            "example_source_id": example.get("source_id", ""),
            "example_target_id": example.get("target_id", ""),
            "risk_level": decision["risk_level"],
            "notes": decision["rationale"],
        })
    return rows


def alias_cycles(alias_rows: list[dict[str, Any]]) -> list[list[str]]:
    graph: dict[str, str] = {}
    status: dict[str, str] = {}
    for row in alias_rows:
        src = row["legacy_type"]
        dst = row["proposed_canonical_type"]
        if not dst or src == dst:
            continue
        graph[src] = dst
        status[src] = row["decision_status"]

    cycles: list[list[str]] = []
    for start in sorted(graph):
        seen: dict[str, int] = {}
        path: list[str] = []
        node = start
        while node in graph:
            if node in seen:
                cycles.append(path[seen[node]:] + [node])
                break
            seen[node] = len(path)
            path.append(node)
            node = graph[node]
    # Deduplicate cycles by their sorted members and ordered string.
    unique: dict[tuple[str, ...], list[str]] = {}
    for cycle in cycles:
        key = tuple(sorted(cycle))
        unique.setdefault(key, cycle)
    return list(unique.values())


def self_alias_violations(alias_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in alias_rows
        if row["proposed_canonical_type"]
        and row["legacy_type"] == row["proposed_canonical_type"]
        and row["decision_status"] != "canonical_keep"
    ]


def build_migration_preview(inventory: dict[str, Any], decisions: dict[str, Any]) -> dict[str, Any]:
    by_status: Counter[str] = Counter()
    relations_requiring_review = 0
    for decision in decisions["decisions"]:
        count = int(decision["count_in_canon"])
        by_status[decision["decision_status"]] += count
        if decision["requires_human_review"] and count:
            relations_requiring_review += count

    legacy_type_count = sum(
        1 for decision in decisions["decisions"]
        if decision["count_in_canon"]
        and decision["decision_status"] != "canonical_keep"
    )

    return {
        "schema": SCHEMA_PREVIEW,
        "session": "S0139",
        "generated_at": utc_now(),
        "dry_run": True,
        "applied_to_canon": False,
        "canon_modified": False,
        "migration_allowed_in_s0139": False,
        "not_a_patch": True,
        "total_relations_seen": inventory["total_relations_seen"],
        "total_legacy_types_seen": legacy_type_count,
        "relations_that_would_remain_legacy_readonly": by_status["legacy_readonly"],
        "relations_that_would_be_alias_candidates": by_status["legacy_alias_candidate"],
        "relations_that_would_require_human_decision": by_status["requires_human_decision"],
        "relations_with_required_human_review_before_any_future_migration": relations_requiring_review,
        "relations_that_are_structural_only": by_status["structural_only"],
        "relations_that_are_blocked": by_status["deprecated_blocked"],
        "relations_that_are_canonical_keep": by_status["canonical_keep"],
        "exclusive_counts_by_decision_status": dict(sorted(by_status.items())),
        "explicit_non_actions": [
            "No relations[] field is edited.",
            "No alias is applied to canon.",
            "No relation candidate is approved.",
            "No --apply path is used.",
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_alias_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "legacy_type",
        "proposed_canonical_type",
        "decision_status",
        "direction_preserved",
        "requires_human_review",
        "example_source_id",
        "example_target_id",
        "risk_level",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_policy_md(path: Path, inventory: dict[str, Any], decisions: dict[str, Any], preview: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# S0139 - Politica gobernada de tipos relacionales historicos",
        "",
        f"Generado: {decisions['generated_at']}",
        "",
        "## Invariantes",
        "",
        "- S0139 no modifica relaciones canonicas existentes.",
        "- Una relacion historica no equivale a una relacion candidata moderna.",
        "- Un alias propuesto no es una migracion aplicada.",
        "- Una decision de tipo relacional no aprueba candidatos individuales.",
        "- Los tags nativos no son prueba suficiente de relacion semantica.",
        "",
        "## Inventario",
        "",
        f"- Relaciones canonicas inventariadas: {inventory['total_relations_seen']}",
        f"- Tipos relacionales distintos: {inventory['distinct_relation_types_seen']}",
        f"- Targets resueltos: {inventory['target_resolution_summary'].get('resolved', 0)}",
        f"- Targets no resueltos: {sum(v for k, v in inventory['target_resolution_summary'].items() if k != 'resolved')}",
        "",
        "## Decisiones por tipo",
        "",
        "| Tipo | Relaciones | Decision | Alias propuesto | Direccion | Revision humana |",
        "|---|---:|---|---|---|---|",
    ]
    for decision in decisions["decisions"]:
        if not decision["count_in_canon"] and decision["relation_type"] not in MANDATORY_HISTORICAL_TYPES:
            continue
        lines.append(
            f"| `{decision['relation_type']}` | {decision['count_in_canon']} | "
            f"`{decision['decision_status']}` | "
            f"`{decision['proposed_canonical_type'] or 'ninguno'}` | "
            f"`{decision['direction_preserved']}` | "
            f"`{str(decision['requires_human_review']).lower()}` |"
        )
    lines.extend([
        "",
        "## Reglas de alias",
        "",
        "- Ningun alias se aplica automaticamente en S0139.",
        "- Todo alias candidato requiere revision antes de cualquier migracion futura.",
        "- `requiere -> depende_de` preserva direccion source->target, pero exige revision humana por riesgo alto.",
        "- `parte_de -> part_of` preserva direccion source->target como hipotesis de composicion, pero queda bloqueado hasta alinear el contrato de candidatos.",
        "- `usa -> references` conserva direccion source->target, pero no cubre todos los matices de uso/dependencia.",
        "- `define` queda como lectura historica, sin alias seguro.",
        "- `child_of` queda como estructura historica, no como relacion semantica moderna.",
        "",
        "## Preview no aplicable",
        "",
        f"- dry_run: `{str(preview['dry_run']).lower()}`",
        f"- applied_to_canon: `{str(preview['applied_to_canon']).lower()}`",
        f"- canon_modified: `{str(preview['canon_modified']).lower()}`",
        f"- migration_allowed_in_s0139: `{str(preview['migration_allowed_in_s0139']).lower()}`",
        "",
        "## Implicaciones para S0140",
        "",
        "S0140 puede ejecutar un primer ciclo real con `human_review` aprobado en dry-run, pero debe usar esta politica para bloquear tipos historicos ambiguos y no puede tratar decisiones de tipo como aprobaciones de candidatos.",
        "",
        "## Implicaciones para S0141",
        "",
        "S0141 debe representar `legacy_readonly` como relaciones historicas, `structural_only` como estructura, y `legacy_alias_candidate` como alias no definitivos. Las relaciones candidatas no admitidas no deben mezclarse con relaciones canonicas.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_review_md(path: Path, inventory: dict[str, Any], decisions: dict[str, Any], alias_rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cycles = alias_cycles(alias_rows)
    self_violations = self_alias_violations(alias_rows)
    historical_detected = [
        d["relation_type"] for d in decisions["decisions"]
        if d["relation_type"] in MANDATORY_HISTORICAL_TYPES and d["count_in_canon"]
    ]
    lines = [
        "# S0139 - Revision de tipos relacionales historicos",
        "",
        "## Resumen",
        "",
        f"- Relaciones inventariadas: {inventory['total_relations_seen']}",
        f"- Tipos encontrados: {inventory['distinct_relation_types_seen']}",
        f"- Tipos historicos detectados: {', '.join(f'`{t}`' for t in historical_detected) or 'ninguno'}",
        f"- Ciclos de alias detectados: {len(cycles)}",
        f"- Self-alias invalidos: {len(self_violations)}",
        "",
        "## Preguntas cerradas por S0139",
        "",
    ]
    for decision in decisions["decisions"]:
        if decision["count_in_canon"] or decision["relation_type"] in MANDATORY_HISTORICAL_TYPES:
            lines.extend([
                f"### `{decision['relation_type']}`",
                f"- Decision: `{decision['decision_status']}`.",
                f"- Alias propuesto: `{decision['proposed_canonical_type'] or 'ninguno'}`.",
                f"- Direccion preservada: `{decision['direction_preserved']}`.",
                f"- Revision humana requerida: `{str(decision['requires_human_review']).lower()}`.",
                f"- Razon: {decision['rationale']}",
                "",
            ])
    lines.extend([
        "## Comprobaciones",
        "",
        "- Alias aplicados al canon: `false`.",
        "- Migracion aplicada: `false`.",
        "- Relaciones admitidas: `false`.",
        "- Canon modificado: `false`.",
        "",
        "## Deudas formales",
        "",
        "- Las familias documentales S0129-S0137 no aparecen completas bajo `data/out/local/sessions/` en la busqueda dirigida; se usaron sus artefactos tecnicos bajo `data/out/local/pipeline/` como evidencia.",
        "- `part_of` aparece en la politica de admision S0131, pero no en el contrato S0129 de tipos permitidos; por eso `parte_de` queda como alias candidato y no como equivalencia aplicada.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(
    out_dir: Path,
    session: str,
    inventory: dict[str, Any],
    decisions: dict[str, Any],
    alias_rows: list[dict[str, Any]],
    preview: dict[str, Any],
) -> dict[str, str]:
    tag = session.lower()
    paths = {
        "inventory": out_dir / f"{tag}_historical_relation_type_inventory.json",
        "decisions": out_dir / f"{tag}_historical_relation_type_decisions.json",
        "policy": out_dir / f"{tag}_historical_relation_type_policy.md",
        "alias_map": out_dir / f"{tag}_alias_map_proposal.csv",
        "migration_preview": out_dir / f"{tag}_relation_type_migration_preview.json",
        "review": out_dir / f"{tag}_relation_type_review.md",
    }
    write_json(paths["inventory"], inventory)
    write_json(paths["decisions"], decisions)
    write_policy_md(paths["policy"], inventory, decisions, preview)
    write_alias_csv(paths["alias_map"], alias_rows)
    write_json(paths["migration_preview"], preview)
    write_review_md(paths["review"], inventory, decisions, alias_rows)
    return {name: repo_relative(path) for name, path in paths.items()}


def build_governance_bundle(canon_glob: str, *, session: str = "s0139") -> dict[str, Any]:
    inventory, relation_entries = scan_canon_relations(canon_glob)
    session_upper = session.upper()
    inventory["session"] = session_upper
    decisions = build_decisions(inventory)
    decisions["session"] = session_upper
    alias_rows = build_alias_rows(decisions)
    preview = build_migration_preview(inventory, decisions)
    preview["session"] = session_upper
    return {
        "inventory": inventory,
        "decisions": decisions,
        "alias_rows": alias_rows,
        "migration_preview": preview,
        "relation_entries": relation_entries,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build S0139 historical relation type decision reports."
    )
    parser.add_argument(
        "--canon-glob",
        default="data/out/local/tiddlers_*.jsonl",
        help="Glob for canonical tiddler JSONL shards.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/out/local/pipeline/relation_type_governance/s0139"),
        help="Output directory for S0139 governance reports.",
    )
    parser.add_argument("--session", default="s0139")
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dry_run:
        print(
            "ERROR: S0139 only supports --dry-run. No canon migration is available.",
            file=sys.stderr,
        )
        return 2

    bundle = build_governance_bundle(args.canon_glob, session=args.session)
    written = write_outputs(
        args.out_dir,
        args.session,
        bundle["inventory"],
        bundle["decisions"],
        bundle["alias_rows"],
        bundle["migration_preview"],
    )

    inv = bundle["inventory"]
    preview = bundle["migration_preview"]
    print(f"S0139 relation type governance reports written to {repo_relative(args.out_dir)}")
    print(f"  total_relations_seen: {inv['total_relations_seen']}")
    print(f"  distinct_relation_types_seen: {inv['distinct_relation_types_seen']}")
    print(f"  dry_run: {preview['dry_run']}")
    print(f"  canon_modified: {preview['canon_modified']}")
    for name, path in written.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
