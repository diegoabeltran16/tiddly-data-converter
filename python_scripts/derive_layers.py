#!/usr/bin/env python3
"""
derive_layers.py — Stable entrypoint for local derivation (S52+).

Reads canon shards from the governed local canon root and produces:
  - data/out/local/enriched/tiddlers_enriched_{N}.jsonl
  - data/out/local/ai/tiddlers_ai_{N}.jsonl
  - data/out/local/ai/chunks_ai_{N}.jsonl
  - data/out/local/enriched/manifest.json
  - data/out/local/ai/manifest.json
  - data/out/local/microsoft_copilot/manifest.json
  - data/out/local/microsoft_copilot/navigation_index.json
  - data/out/local/microsoft_copilot/entities.json
  - data/out/local/microsoft_copilot/topics.json
  - data/out/local/microsoft_copilot/source_arbitration_report.json
  - data/out/local/microsoft_copilot/nodes.csv
  - data/out/local/microsoft_copilot/edges.csv
  - data/out/local/microsoft_copilot/artifacts.csv
  - data/out/local/microsoft_copilot/coverage.csv
  - data/out/local/microsoft_copilot/overview.txt
  - data/out/local/microsoft_copilot/reading_guide.txt
  - data/out/local/microsoft_copilot/bundles/*.txt
  - data/out/local/microsoft_copilot/spec/**/*.md
  - data/out/local/microsoft_copilot/spec/**/*.json
  - data/out/local/microsoft_copilot/copilot_agent/corpus.txt
  - data/out/local/microsoft_copilot/copilot_agent/entities.json
  - data/out/local/microsoft_copilot/copilot_agent/relations.csv
  - data/out/local/ai/reports/classification_report.json
  - data/out/local/ai/reports/chunk_qc_report.json
  - data/out/local/ai/reports/retrieval_qc_report.json
  - data/out/local/ai/reports/relations_qc_report.json
  - data/out/local/ai/reports/derivation_report.json

Hardening principles (S55):
  - 100% shard-aware: no monolithic input, no hardcoded shard count
  - Controlled vocabulary for role_primary loaded from the S79 policy contract
  - Token-aware structural chunker with hard max guardrail
  - Corpus eligibility policy loaded from machine-readable governance rules
  - Retrieval hints: normalized dedup, split into terms + aliases
  - Relations validated against known node IDs
  - Three distinct text fields: preview_text, semantic_text, ai_summary
  - Deterministic: no fabrication, no metadata invention
  - Chunk-level traceability back to canon shard, line and structural context
"""

import argparse
import csv
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from corpus_governance import (
    CANON_POLICY_BUNDLE_REL,
    DERIVED_LAYERS_REGISTRY_REL,
    classify_role_primary_value,
    load_canon_policy_bundle,
    load_layer_registry,
    role_primary_canonical_roles,
    resolve_corpus_policy,
)
from path_governance import (
    DEFAULT_AI_DIR,
    DEFAULT_AI_REPORTS_DIR,
    DEFAULT_AUDIT_DIR,
    DEFAULT_CANON_DIR,
    DEFAULT_ENRICHED_DIR,
    DEFAULT_EXPORT_DIR,
    DEFAULT_MICROSOFT_COPILOT_DIR,
    as_display_path,
    resolve_repo_path,
    sorted_canon_shards,
)
from text_utils import (
    estimate_tokens,
    safe_str,
    normalize_for_dedup,
)
from chunking import (
    DEFAULT_MICROCHUNK_MIN_TOKENS,
    split_structurally,
    is_separator_only_chunk,
    densify_microchunks,
)
from classification import (
    classify_role,
    derive_taxonomy_and_section,
)
from enrichment import (
    build_enriched_record,
)
from ai_records import (
    build_ai_record,
    build_relation_resolution_index,
    classify_payload,
    chunk_node,
    validate_relations,
    extract_embedded_content_rels,
    relation_family,
    RELATION_PROPAGATION_POLICY_VERSION,
    MAX_RELATION_TARGETS_PER_CHUNK,
    GENERIC_RELATION_TYPES,
)
from qc_reports import (
    write_classification_report,
    write_chunk_qc_report,
    write_retrieval_qc_report,
    write_relations_qc_report,
    write_derivation_report,
)

# ── Derivation session identifier ────────────────────────────────────────────
SESSION = "S55"
SCHEMA_VERSION = "v2"
MICROSOFT_COPILOT_GENERATED_FROM_SESSION = "m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0"
MICROSOFT_COPILOT_FORMAT_VERSION = "json_csv_txt_mvp_v0"
MICROSOFT_COPILOT_OVERVIEW_MAX_ITEMS = 12
COPILOT_AGENT_GENERATED_FROM_SESSION = "m03-s64-copilot-agent-semantic-compression-and-reversible-canon-hardening-v0"
COPILOT_AGENT_INTEGRATION_BASELINE_SESSION = "m03-s63-copilot-agent-generator-integration-and-canonicalization-v0"
COPILOT_AGENT_SEMANTIC_REFERENCE_SESSION = "m03-s62-copilot-agent-three-master-files-pack-v0"
COPILOT_AGENT_FORMAT_VERSION = "semantic_reversible_pack_v1"
COPILOT_AGENT_ENTITY_LIMIT = 50
COPILOT_AGENT_CORPUS_MAX_CHARS = 32000
COPILOT_AGENT_FAMILY_ORDER = [
    "integration_flow",
    "semantic_compression",
    "copilot_projection",
    "minimal_canon",
    "strict_reversibility",
]
COPILOT_AGENT_FAMILY_TARGETS = {
    "integration_flow": 8,
    "semantic_compression": 10,
    "copilot_projection": 12,
    "minimal_canon": 8,
    "strict_reversibility": 7,
}
COPILOT_AGENT_TYPE_CAPS = {
    "session": 7,
    "contract": 8,
    "hypothesis": 6,
    "provenance": 6,
}
COPILOT_AGENT_RECENT_MARKERS = {
    "m03-s59",
    "m03-s60",
    "m03-s61",
    "m03-s62",
    "m03-s63",
    "m03-s64",
}
COPILOT_AGENT_REVERSE_MARKERS = {"m03-s50", "m03-s57"}
COPILOT_AGENT_STRICT_ANCHOR_TITLES = {
    "contratos/policy/canon_policy_bundle.json",
    "go/canon/embedded_json_text.go",
    "go/canon/identity.go",
}
COPILOT_AGENT_FAMILY_PURPOSES = {
    "integration_flow": "Pipeline real, capas oficiales y entrypoints que sostienen la integración del flujo.",
    "semantic_compression": "Reglas madre y nodos orientadores que hacen posible una compresión semántica legible.",
    "copilot_projection": "Lineaje S59-S64 que gobierna la proyección Microsoft Copilot y el subpaquete copilot_agent.",
    "minimal_canon": "Cierre documental mínimo que debe permanecer absorbido en canon y seguir siendo trazable.",
    "strict_reversibility": "Reglas, artefactos y componentes que condicionan normalización determinística y reverse estricto.",
}
MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF = {
    "title": "Formatos de archivo admitidos por Microsoft 365 Copilot",
    "url": "https://support.microsoft.com/es-es/topic/formatos-de-archivo-admitidos-por-microsoft-365-copilot-1afb9a70-2232-4753-85c2-602c422af3a8",
    "observed_support": {
        "json": "configuration and markup",
        "txt": "document creation and plain text",
        "csv": "data analysis and spreadsheets",
    },
    "consulted_at": "2026-04-22",
}
CANON_POLICY_BUNDLE = load_canon_policy_bundle()
LAYER_REGISTRY = load_layer_registry()

# ── Default configuration ─────────────────────────────────────────────────────
DEFAULT_ENRICHED_SHARD_SIZE = 100
DEFAULT_AI_SHARD_SIZE = 100
DEFAULT_CHUNK_SHARD_SIZE = 200
DEFAULT_CHUNK_TARGET_TOKENS = 1800
DEFAULT_CHUNK_MAX_TOKENS = 4000   # hard max — no chunk may exceed this
DEFAULT_TIDDLER_SHARD_SIZE = 100
DEFAULT_CHUNK_SHARD_SIZE_ARG = 200
HUB_RELATIVE_THRESHOLD = 0.05
HUB_ABSOLUTE_MIN_COUNT = 20
HUB_FAMILY_DOMINANCE_THRESHOLD = 0.40
HUB_FAMILY_MIN_COUNT = 10

# ── Controlled vocabulary for role_primary ────────────────────────────────────
VALID_ROLES = role_primary_canonical_roles(CANON_POLICY_BUNDLE)


def get_layer_registry_entry(layer_id: str) -> dict:
    for layer in LAYER_REGISTRY["layers"]:
        if layer.get("layer_id") == layer_id:
            return layer
    raise KeyError(f"unknown governed layer: {layer_id}")


def build_relation_propagation_context(classified_records: list, relation_index: dict) -> dict:
    """Detect corpus-wide hubs before propagating relation targets to chunks."""
    target_counts: Counter = Counter()
    target_type_counts: dict[str, Counter] = defaultdict(Counter)
    family_target_counts: dict[str, Counter] = defaultdict(Counter)
    family_totals: Counter = Counter()
    type_counts: Counter = Counter()
    stale_relation_target_candidates = 0

    for rec, _shard_file, _line_num, role, taxonomy, _section in classified_records:
        valid_rels, invalid_rels = validate_relations(
            rec.get("relations") or [],
            relation_index.get("ids", set()),
            relation_index,
        )
        embedded_rels, _stale, _urn, embedded_invalid = extract_embedded_content_rels(
            rec,
            relation_index,
        )
        stale_relation_target_candidates += len(invalid_rels) + len(embedded_invalid)
        family = relation_family(rec, role, taxonomy)
        for rel in [*valid_rels, *embedded_rels]:
            target_id = safe_str(rel.get("target_id")).strip()
            if not target_id:
                continue
            rel_type = safe_str(rel.get("type")).lower().strip() or "unknown"
            target_counts[target_id] += 1
            target_type_counts[target_id][rel_type] += 1
            family_target_counts[family][target_id] += 1
            family_totals[family] += 1
            type_counts[rel_type] += 1

    total_candidates = sum(target_counts.values())
    global_threshold = max(
        HUB_ABSOLUTE_MIN_COUNT,
        math.ceil(total_candidates * HUB_RELATIVE_THRESHOLD),
    ) if total_candidates else HUB_ABSOLUTE_MIN_COUNT

    hub_target_ids: set[str] = {
        target_id
        for target_id, count in target_counts.items()
        if count >= global_threshold
    }
    family_hub_reasons: dict[str, list[str]] = defaultdict(list)
    for family, counter in family_target_counts.items():
        family_total = family_totals[family]
        if not family_total:
            continue
        family_threshold = max(
            HUB_FAMILY_MIN_COUNT,
            math.ceil(family_total * HUB_FAMILY_DOMINANCE_THRESHOLD),
        )
        for target_id, count in counter.items():
            if count >= family_threshold:
                hub_target_ids.add(target_id)
                family_hub_reasons[target_id].append(
                    f"{family}:{count}/{family_total}"
                )

    hub_targets = []
    for target_id in sorted(hub_target_ids, key=lambda tid: (-target_counts[tid], tid)):
        target_rec = relation_index.get("by_id", {}).get(target_id, {})
        hub_targets.append({
            "target_id": target_id,
            "title": target_rec.get("title"),
            "canonical_slug": target_rec.get("canonical_slug"),
            "count": target_counts[target_id],
            "relation_types": dict(target_type_counts[target_id].most_common()),
            "family_dominance": family_hub_reasons.get(target_id, []),
        })

    return {
        "policy_version": RELATION_PROPAGATION_POLICY_VERSION,
        "max_relation_targets_per_chunk": MAX_RELATION_TARGETS_PER_CHUNK,
        "candidate_relation_count": total_candidates,
        "relation_type_distribution": dict(type_counts.most_common()),
        "generic_relation_type_distribution": {
            rel_type: type_counts[rel_type]
            for rel_type in sorted(GENERIC_RELATION_TYPES)
            if type_counts.get(rel_type)
        },
        "hub_thresholds": {
            "global_min_count": global_threshold,
            "global_relative_threshold": HUB_RELATIVE_THRESHOLD,
            "family_min_count": HUB_FAMILY_MIN_COUNT,
            "family_dominance_threshold": HUB_FAMILY_DOMINANCE_THRESHOLD,
        },
        "hub_target_ids": hub_target_ids,
        "hub_targets": hub_targets,
        "stale_relation_target_candidates": stale_relation_target_candidates,
    }


# ── Load canon shards ──────────────────────────────────────────────────────────

def discover_shards(input_dir: Path) -> list:
    """Discover all canon shards matching tiddlers_*.jsonl pattern."""
    shards = sorted_canon_shards(input_dir)
    if not shards:
        print(f"ERROR: No tiddlers_*.jsonl shards found in {input_dir}", file=sys.stderr)
        sys.exit(1)
    return shards


def load_canon(input_dir: Path) -> tuple:
    """
    Load all canon shards. Returns (records_list, shard_paths).
    records_list: list of (record_dict, shard_filename, line_num)
    """
    shard_paths = discover_shards(input_dir)
    records = []
    for shard_path in shard_paths:
        with open(shard_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                records.append((rec, shard_path.name, line_num))
    return records, shard_paths


# ── Sharding writer ────────────────────────────────────────────────────────────

def _plan_shards(records: list, prefix: str, shard_size: int) -> list:
    """Compute shard layout without any I/O.

    Returns a list of dicts: [{"file": fname, "shard_index": n, "record_count": count}, ...]
    This is the single source of truth for shard boundaries used by both
    write_sharded(dry_run=True) and write_sharded(dry_run=False).
    """
    plan = []
    shard_num = 1
    count_in_shard = 0

    for _ in records:
        if count_in_shard == 0 or count_in_shard >= shard_size:
            if plan:
                plan[-1]["record_count"] = count_in_shard
            plan.append({
                "file": f"{prefix}_{shard_num}.jsonl",
                "shard_index": shard_num,
                "record_count": 0,
            })
            shard_num += 1
            count_in_shard = 0
        count_in_shard += 1

    if plan:
        plan[-1]["record_count"] = count_in_shard

    return plan


def write_sharded(records: list, output_dir: Path, prefix: str, shard_size: int,
                  dry_run: bool = False):
    """Write records to sharded JSONL files.

    dry_run=False (default): creates output_dir, deletes stale prefix shards,
        writes records, returns list of shard info dicts (backward-compatible).

    dry_run=True: computes the write plan using the same shard logic as the
        real write, without touching the filesystem. Returns a plan dict:
            {
              "dry_run": True,
              "output_dir": str,
              "prefix": str,
              "shard_size": int,
              "total_records": int,
              "shard_count": int,
              "shards_to_write": [{file, shard_index, record_count}, ...],
              "stale_shards_to_delete": [filename, ...],
            }
    """
    plan = _plan_shards(records, prefix, shard_size)

    if dry_run:
        stale = []
        if output_dir.exists():
            stale = sorted(p.name for p in output_dir.glob(f"{prefix}_*.jsonl"))
        return {
            "dry_run": True,
            "output_dir": str(output_dir),
            "prefix": prefix,
            "shard_size": shard_size,
            "total_records": len(records),
            "shard_count": len(plan),
            "shards_to_write": plan,
            "stale_shards_to_delete": stale,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_shard in output_dir.glob(f"{prefix}_*.jsonl"):
        stale_shard.unlink()

    record_iter = iter(records)
    shards_info = []
    for shard_info in plan:
        fpath = output_dir / shard_info["file"]
        with open(fpath, "w", encoding="utf-8") as f:
            for _ in range(shard_info["record_count"]):
                f.write(json.dumps(next(record_iter), ensure_ascii=False) + "\n")
        shards_info.append(dict(shard_info))

    return shards_info


def write_manifest(output_dir: Path, layer_name: str, shards_info: list,
                   total_records: int, source_shard_count: int,
                   source_shard_files: list, extra: dict = None,
                   layer_id: str | None = None):
    """Write manifest.json for a layer."""
    manifest = {
        "layer": layer_name,
        "session": SESSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "canon_shard_count": source_shard_count,
            "canon_dir": "data/out/local",
            "canon_pattern": "tiddlers_*.jsonl",
            "canon_shard_files": [as_display_path(p) if hasattr(p, 'parts') else str(p) for p in source_shard_files],
        },
        "output": {
            "total_records": total_records,
            "shard_count": len(shards_info),
            "shards": shards_info,
        },
    }
    if layer_id:
        layer = get_layer_registry_entry(layer_id)
        manifest["governance"] = {
            "policy_bundle_ref": CANON_POLICY_BUNDLE_REL,
            "layer_registry_ref": DERIVED_LAYERS_REGISTRY_REL,
            "layer_id": layer_id,
            "layer_class": layer.get("layer_class"),
            "authority": layer.get("authority"),
            "lineage_parents": layer.get("lineage_parents"),
            "validation_inputs": layer.get("validation_inputs"),
        }
    if extra:
        manifest.update(extra)
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest_path


def write_json_file(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def load_optional_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def shard_path_for_record(output_dir: Path, prefix: str, record_index: int, shard_size: int) -> str:
    shard_index = ((record_index - 1) // shard_size) + 1
    return as_display_path(output_dir / f"{prefix}_{shard_index}.jsonl")


def collect_microsoft_copilot_source_inventory(
    shard_paths: list,
    enriched_dir: Path,
    enriched_shards_info: list,
    ai_dir: Path,
    ai_shards_info: list,
    chunk_shards_info: list,
    reports_dir: Path,
    audit_dir: Path,
    export_dir: Path,
) -> dict:
    audit_manifest = load_optional_json(audit_dir / "manifest.json")
    export_files = sorted(path for path in export_dir.rglob("*") if path.is_file()) if export_dir.exists() else []
    ai_report_files = sorted(path for path in reports_dir.glob("*.json")) if reports_dir.exists() else []

    return {
        "canon": {
            "path": as_display_path(DEFAULT_CANON_DIR),
            "pattern": "tiddlers_*.jsonl",
            "shards": [as_display_path(path) for path in shard_paths],
        },
        "enriched": {
            "path": as_display_path(enriched_dir),
            "manifest_path": as_display_path(enriched_dir / "manifest.json"),
            "shards": [as_display_path(enriched_dir / shard["file"]) for shard in enriched_shards_info],
        },
        "ai": {
            "path": as_display_path(ai_dir),
            "manifest_path": as_display_path(ai_dir / "manifest.json"),
            "shards": [as_display_path(ai_dir / shard["file"]) for shard in ai_shards_info],
            "chunk_shards": [as_display_path(ai_dir / shard["file"]) for shard in chunk_shards_info],
            "reports": [as_display_path(path) for path in ai_report_files],
        },
        "audit": {
            "path": as_display_path(audit_dir),
            "present": audit_dir.exists(),
            "manifest_path": as_display_path(audit_dir / "manifest.json") if (audit_dir / "manifest.json").exists() else None,
            "summary_path": as_display_path(audit_dir / "compliance_summary.md") if (audit_dir / "compliance_summary.md").exists() else None,
            "latest_snapshot": {
                "generated_at": audit_manifest.get("generated_at"),
                "corpus": audit_manifest.get("corpus"),
                "audit": audit_manifest.get("audit"),
            } if audit_manifest else None,
        },
        "export": {
            "path": as_display_path(export_dir),
            "present": bool(export_files),
            "artifacts": [as_display_path(path) for path in export_files[:12]],
        },
        "governance_inputs": [
            "docs/Informe_Tecnico_de_Tiddler (Esp).md",
            "README.md",
            "data/README.md",
            ".github/instructions/tiddlers_sesiones.instructions.md",
            ".github/instructions/contratos.instructions.md",
            ".github/instructions/sesiones.instructions.md",
            "contratos/projections/derived_layers_registry.json",
            "contratos/m03-s59-microsoft-copilot-projection-governance-v0.md.json",
            "contratos/m03-s60-microsoft-copilot-derived-projection-mvp-v0.md.json",
            "contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json",
        ],
    }


def derive_microsoft_copilot_summary(canon_rec: dict, ai_rec: dict, role: str) -> str:
    if canon_rec.get("is_binary"):
        title = safe_str(canon_rec.get("title")).strip()
        return f"Binary asset metadata for: {title}" if title else "Binary asset metadata"

    fallback = safe_str(ai_rec.get("ai_summary")).strip()
    if canon_rec.get("content_type") != "application/json":
        return fallback

    text = safe_str(canon_rec.get("text")).strip()
    if not text.startswith("{"):
        return fallback

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return fallback

    if role == "session":
        content = payload.get("content") or {}
        summary = safe_str(content.get("plain")).strip()
        return summary[:280] if summary else fallback
    if role == "hypothesis":
        summary = safe_str(payload.get("hipotesis")).strip()
        return summary[:280] if summary else fallback
    if role == "provenance":
        summary = safe_str(payload.get("origen")).strip()
        return summary[:280] if summary else fallback
    return fallback


# ── Microsoft Copilot S61 JSON/CSV/TXT projection ─────────────────────────────

S61_SPEC_SUMMARIES = [
    {
        "slug": "contratos-instructions",
        "title": "contratos.instructions.md",
        "source_files": [".github/instructions/contratos.instructions.md"],
        "summary": "Define que toda sesion sustantiva debe cerrar con contrato `.md.json` importable en TiddlyWiki, artefactos afectados, decisiones, validaciones y absorcion canónica del nodo de contrato cuando corresponda.",
        "rules": [
            "emitir contrato `.md.json` por sesion sustantiva",
            "documentar alcance, decisiones, archivos tocados, limites y validaciones",
            "mantener contrato legible por humano e importable por TiddlyWiki",
            "absorber el nodo de contrato en canon cuando la sesion produce memoria documental",
        ],
        "artifacts": ["contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json"],
        "impact": "Obliga a que S61 no cierre solo con outputs derivados; debe dejar contrato trazable y canon reversible.",
        "projection_impact": ["procedencia", "autoridad", "regeneracion"],
    },
    {
        "slug": "dependencia-y-superficie-externa",
        "title": "dependencia_y_superficie_externa.instructions.md",
        "source_files": [".github/instructions/dependencia_y_superficie_externa.instructions.md"],
        "summary": "Gobierna dependencias, superficie externa, seguridad y reproducibilidad; exige justificar referencias externas sin convertirlas en nuevas dependencias del sistema.",
        "rules": [
            "separar referencia externa de dependencia operativa",
            "no introducir integraciones cloud ni nuevas credenciales por defecto",
            "registrar superficie externa solo si afecta decisiones reales",
            "mantener reproducibilidad local-first",
        ],
        "artifacts": ["source_arbitration_report.json", "spec/summaries/microsoft-support-formats.json"],
        "impact": "La fuente de Microsoft se usa solo para confirmar coherencia de formatos, no como autoridad del canon.",
        "projection_impact": ["seleccion de fuentes", "procedencia", "autoridad"],
    },
    {
        "slug": "desarrollo-y-evolucion",
        "title": "desarrollo_y_evolucion.instructions.md",
        "source_files": [".github/instructions/desarrollo_y_evolucion.instructions.md"],
        "summary": "Ordena registrar cambios de estado del proyecto, razones, pendientes y continuidad historica sin borrar contexto previo.",
        "rules": [
            "explicar que cambio y por que",
            "preservar continuidad entre S59, S60 y S61",
            "distinguir cierre operativo de deuda residual",
            "no borrar decisiones anteriores sin declarar reemplazo",
        ],
        "artifacts": ["spec/memoria_decisiones_s61.md", "bundles/recent_sessions.txt"],
        "impact": "S61 documenta la transicion de JSONL de S60 a JSON/CSV/TXT sin ocultar el reemplazo.",
        "projection_impact": ["bundles TXT", "regeneracion", "procedencia"],
    },
    {
        "slug": "detalles-del-tema",
        "title": "detalles_del_tema.instructions.md",
        "source_files": [".github/instructions/detalles_del_tema.instructions.md"],
        "summary": "Delimita alcance tematico, evita mezclar normativa, ejecucion y contenido sustantivo sin senalarlo.",
        "rules": [
            "separar diseno de proyeccion de autoridad canónica",
            "mantener foco en utilidad real para agentes",
            "evitar expansion conceptual innecesaria",
        ],
        "artifacts": ["overview.txt", "reading_guide.txt"],
        "impact": "La capa se describe como superficie de lectura, no como regimen normativo nuevo.",
        "projection_impact": ["estructura JSON", "bundles TXT", "autoridad"],
    },
    {
        "slug": "elementos-especificos",
        "title": "elementos_especificos.istructions.md",
        "source_files": [".github/instructions/elementos_especificos.istructions.md"],
        "summary": "Exige preservar artefactos concretos con identidad, contexto y recuperabilidad.",
        "rules": [
            "no dejar artefactos huerfanos",
            "cada recurso debe tener ruta y rol",
            "la salida debe ser navegable por agente",
            "las referencias deben conservar identidad",
        ],
        "artifacts": ["artifacts.csv", "navigation_index.json"],
        "impact": "Todos los outputs de S61 quedan inventariados y enlazados desde manifest/navigation.",
        "projection_impact": ["tablas CSV", "estructura JSON", "procedencia"],
    },
    {
        "slug": "glosario-y-convenciones",
        "title": "glosario_y_convenciones.instructions.md",
        "source_files": [".github/instructions/glosario_y_convenciones.instructions.md"],
        "summary": "Estabiliza nombres, alias y convenciones compartidas para reducir ambiguedad semantica.",
        "rules": [
            "usar nombres consistentes para capas y artefactos",
            "no cambiar convenciones sin justificacion",
            "declarar equivalencias cuando existan",
        ],
        "artifacts": ["entities.json", "topics.json", "nodes.csv"],
        "impact": "Fija `JSON/CSV/TXT` como familias de salida y evita que `.jsonl` siga nombrado como target final.",
        "projection_impact": ["estructura JSON", "tablas CSV", "regeneracion"],
    },
    {
        "slug": "hipotesis",
        "title": "hipotesis.instructions.md",
        "source_files": [".github/instructions/hipotesis.instructions.md"],
        "summary": "Gobierna afirmaciones tentativas: deben declararse como hipotesis, con evidencia base y sin confundirse con hechos.",
        "rules": [
            "formular hipotesis de trabajo con evidencia",
            "mantener estatuto tentativo hasta validacion",
            "no presentar preferencia de formato como verdad canónica",
        ],
        "artifacts": ["spec/memoria_decisiones_s61.md", "canon:hipotesis_s61"],
        "impact": "La hipotesis JSON/CSV/TXT queda registrada en memoria y canon, no dispersa en conversacion.",
        "projection_impact": ["procedencia", "autoridad", "bundles TXT"],
    },
    {
        "slug": "politica-de-memoria-activa",
        "title": "politica_de_memoria_activa.instructions.md",
        "source_files": [".github/instructions/politica_de_memoria_activa.instructions.md"],
        "summary": "Ordena memoria selectiva, situada y util, evitando copiar todo sin criterio.",
        "rules": [
            "seleccionar memoria por relevancia",
            "evitar duplicacion indiscriminada",
            "preservar texto sustantivo cuando sea util",
            "declarar transformaciones y limites",
        ],
        "artifacts": ["bundles/*.txt", "spec/memoria_decisiones_s61.md"],
        "impact": "Los bundles TXT preservan texto relevante de sesiones, contratos y gobernanza sin clonar todo el canon.",
        "projection_impact": ["bundles TXT", "seleccion de fuentes", "procedencia"],
    },
    {
        "slug": "prcommits",
        "title": "PRcommits.instructions.md",
        "source_files": [".github/instructions/PRcommits.instructions.md"],
        "summary": "Regula propuestas de PR y commits; en S61 aplica solo como cautela documental, no como obligacion de abrir PR.",
        "rules": [
            "si hay PR, usar estructura de commits vigente",
            "todo cambio sustantivo conserva contrato",
            "no convertir la sesion en PR si el usuario no lo pide",
        ],
        "artifacts": ["contrato S61"],
        "impact": "No altera el output Copilot; confirma que el cierre contractual es independiente de PR.",
        "projection_impact": ["procedencia"],
    },
    {
        "slug": "principios-de-gestion",
        "title": "principios_de_gestion.instructions.md",
        "source_files": [".github/instructions/principios_de_gestion.instructions.md"],
        "summary": "Fija principios transversales y resolucion de tensiones entre coherencia, utilidad, trazabilidad, simplicidad y documentacion.",
        "rules": [
            "priorizar coherencia con sistema actual",
            "evitar complejidad accidental",
            "resolver conflictos explicitamente",
            "documentar decisiones necesarias",
        ],
        "artifacts": ["spec/plan_de_implementacion_s61.md", "source_arbitration_report.json"],
        "impact": "La resolucion principal reemplaza el JSONL final por JSON/CSV/TXT sin crear subsistema nuevo.",
        "projection_impact": ["estructura JSON", "tablas CSV", "bundles TXT", "autoridad"],
    },
    {
        "slug": "procedencia-epistemologica",
        "title": "procedencia_epistemologica.instructions.md",
        "source_files": [".github/instructions/procedencia_epistemologica.instructions.md"],
        "summary": "Exige declarar origen, metodo, actor y estatuto de lo generado, distinguiendo observacion, inferencia y transformacion.",
        "rules": [
            "cada artefacto declara fuentes usadas",
            "distinguir observacion de inferencia",
            "registrar fuente externa oficial cuando se usa",
            "mantener reversible la transformacion",
        ],
        "artifacts": ["source_arbitration_report.json", "coverage.csv", "canon:procedencia_s61"],
        "impact": "La proyeccion declara `source_of_truth`, `source_inputs`, linaje y autoridad no autoritativa.",
        "projection_impact": ["procedencia", "autoridad", "regeneracion"],
    },
    {
        "slug": "protocolo-de-sesion",
        "title": "protocolo_de_sesion.instructions.md",
        "source_files": [".github/instructions/protocolo_de_sesion.instructions.md"],
        "summary": "Define disciplina de sesion: leer situado, actuar sobre archivos reales, validar y cerrar con artefactos.",
        "rules": [
            "no cerrar solo con analisis",
            "leer lo minimo suficiente y pertinente",
            "mantener autoridad humana",
            "validar el flujo afectado",
        ],
        "artifacts": ["checklist_global_s61.md", "contrato S61", "canon family S61"],
        "impact": "S61 implementa y valida la capa, no solo la especifica.",
        "projection_impact": ["regeneracion", "procedencia"],
    },
    {
        "slug": "sesiones",
        "title": "sesiones.instructions.md",
        "source_files": [".github/instructions/sesiones.instructions.md"],
        "summary": "Establece que el canon local manda, que los derivados son subordinados y que toda sesion con memoria debe cerrar en canon con validacion strict/reverse.",
        "rules": [
            "canon local `tiddlers_*.jsonl` es fuente de verdad",
            "derivados no sustituyen canon",
            "cerrar con contrato, sesion, hipotesis y procedencia",
            "si cambia canon, correr strict, reverse-preflight y reverse real",
        ],
        "artifacts": ["canon:session_s61", "canon:hypothesis_s61", "canon:provenance_s61", "canon:contract_s61"],
        "impact": "Obliga a que la materializacion Copilot no sea el unico cierre de S61.",
        "projection_impact": ["autoridad", "procedencia", "regeneracion"],
    },
    {
        "slug": "tiddlers-sesiones",
        "title": "tiddlers_sesiones.instructions.md",
        "source_files": [".github/instructions/tiddlers_sesiones.instructions.md"],
        "summary": "Detalle operativo de cierre directo en canon: familia minima de sesion, hipotesis, procedencia y nodo de contrato, todos reverse-ready.",
        "rules": [
            "crear nodo de sesion",
            "crear nodo de hipotesis",
            "crear nodo de procedencia",
            "crear nodo path-like del contrato",
            "validar canon y reverse",
        ],
        "artifacts": ["data/out/local/tiddlers_7.jsonl", "contrato S61"],
        "impact": "S61 agrega las cuatro lineas canonicas reversibles y actualiza derivados desde ese canon.",
        "projection_impact": ["procedencia", "regeneracion", "autoridad"],
    },
    {
        "slug": "contratos-s58-s59-s60",
        "title": "Contratos S58-S60",
        "source_files": [
            "contratos/m03-s58-route-fix-readme-structural-cleanup.md.json",
            "contratos/m03-s59-microsoft-copilot-projection-governance-v0.md.json",
            "contratos/m03-s60-microsoft-copilot-derived-projection-mvp-v0.md.json",
        ],
        "summary": "S58 estabiliza rutas y README, S59 registra la capa como derivada gobernada, S60 la materializa como MVP JSONL que S61 debe sustituir por JSON/CSV/TXT.",
        "rules": [
            "mantener rutas reales `python_scripts/` y `shell_scripts/`",
            "microsoft_copilot no es canon",
            "registrar linaje multifuente",
            "reemplazar el MVP JSONL de S60 sin borrar su memoria historica",
        ],
        "artifacts": ["bundles/recent_sessions.txt", "spec/memoria_decisiones_s61.md"],
        "impact": "Aporta la base historica que explica por que S61 conserva la capa pero cambia el formato final.",
        "projection_impact": ["bundles TXT", "procedencia", "regeneracion"],
    },
    {
        "slug": "repo-y-derivados-actuales",
        "title": "Estructura vigente y derivados actuales",
        "source_files": [
            "README.md",
            "data/README.md",
            "data/out/local/enriched/manifest.json",
            "data/out/local/ai/manifest.json",
            "data/out/local/audit/manifest.json",
            "contratos/projections/derived_layers_registry.json",
        ],
        "summary": "El repo ya tiene canon shardeado, derivados enriched/ai/audit/export/reverse y registry machine-readable; `microsoft_copilot` debe quedar integrada al mismo sistema.",
        "rules": [
            "usar `derive_layers.py` como flujo real de generacion",
            "mantener registry alineado con outputs existentes",
            "no dejar carpeta huerfana",
            "validar presencia y autoridad de la capa",
        ],
        "artifacts": ["manifest.json", "coverage.csv", "artifacts.csv"],
        "impact": "S61 queda como salida regenerable del pipeline, no como salida manual.",
        "projection_impact": ["regeneracion", "tablas CSV", "estructura JSON"],
    },
    {
        "slug": "microsoft-support-formats",
        "title": "Microsoft Support file formats",
        "source_files": [MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF["url"]],
        "summary": "La documentacion oficial de Microsoft 365 Copilot lista `.json`, `.txt` y `.csv` como formatos soportados en categorias de markup/configuracion, documentos y analisis de datos.",
        "rules": [
            "usar JSON para estructura y metadatos",
            "usar CSV para datos tabulares y relaciones",
            "usar TXT para lectura narrativa",
            "recordar que rutas locales requieren carga o ubicacion cloud para Copilot",
        ],
        "artifacts": ["source_arbitration_report.json", "spec/summaries/microsoft-support-formats.md"],
        "impact": "Confirma que el enfoque JSON/CSV/TXT es coherente con superficie soportada, sin crear dependencia cloud.",
        "projection_impact": ["estructura JSON", "tablas CSV", "bundles TXT", "seleccion de fuentes"],
    },
]


def json_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return safe_str(value)


def write_csv_file(path: Path, fieldnames: list[str], rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json_cell(row.get(field)) for field in fieldnames})
    return path


def write_text_file(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    return path


def text_artifact_lines(title: str, purpose: str, source: str,
                        tags: list[str], content_lines: list[str],
                        updated_at: str) -> list[str]:
    return [
        f"TITLE: {title}",
        f"PURPOSE: {purpose}",
        "AUTHORITY: derived_non_authoritative_agent_projection",
        f"SOURCE: {source}",
        f"UPDATED_AT: {updated_at}",
        f"TAGS: {', '.join(tags)}",
        "",
        "CONTENT:",
        *content_lines,
    ]


def parse_embedded_json_payload(rec: dict) -> dict | None:
    text = safe_str(rec.get("text")).strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def embedded_json_primary_text(payload: dict) -> str:
    content = payload.get("content") or {}
    if isinstance(content, dict):
        markdown = safe_str(content.get("markdown")).strip()
        plain = safe_str(content.get("plain")).strip()
        if markdown:
            return markdown
        if plain:
            return plain
    for key in (
        "descripcion",
        "descripcion_breve",
        "hallazgo_clave",
        "hipotesis",
        "origen",
        "objetivo",
        "purpose",
        "summary",
        "resultado_esperado",
    ):
        value = safe_str(payload.get(key)).strip()
        if value:
            return value
    return ""


def canonical_reading_text(rec: dict) -> str:
    payload = parse_embedded_json_payload(rec)
    if payload:
        primary_text = embedded_json_primary_text(payload)
        if primary_text:
            return primary_text
    content = rec.get("content") or {}
    return safe_str(content.get("plain") or rec.get("text")).strip()


def truncate_declared(text: str, max_chars: int, source_label: str) -> str:
    text = safe_str(text).strip()
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + f"\n\n[TRUNCATED_DECLARED: {source_label} excede {max_chars} caracteres; "
        + "consultar la fuente canonica o archivo fuente indicado para texto completo.]"
    )


def source_ref_for_record(canon_rec: dict, shard_file: str, line_num: int,
                          record_index: int, enriched_dir: Path, ai_dir: Path,
                          tiddler_shard_size: int) -> dict:
    return {
        "canon": {
            "path": as_display_path(DEFAULT_CANON_DIR / shard_file),
            "line": line_num,
            "id": canon_rec.get("id"),
            "source_position": canon_rec.get("source_position"),
            "content_hash": canon_rec.get("version_id"),
        },
        "enriched": {
            "path": shard_path_for_record(enriched_dir, "tiddlers_enriched", record_index, tiddler_shard_size),
            "id": canon_rec.get("id"),
        },
        "ai": {
            "path": shard_path_for_record(ai_dir, "tiddlers_ai", record_index, tiddler_shard_size),
            "id": canon_rec.get("id"),
        },
    }


def build_s61_projection_items(
    classified: list,
    enriched_records: list,
    ai_records: list,
    enriched_dir: Path,
    ai_dir: Path,
    tiddler_shard_size: int,
) -> list[dict]:
    copilot_layer = get_layer_registry_entry("microsoft_copilot")
    items = []
    for record_index, ((canon_rec, shard_file, line_num, _, _, _), enriched_rec, ai_rec) in enumerate(
        zip(classified, enriched_records, ai_records),
        start=1,
    ):
        role = enriched_rec.get("role_primary") or ai_rec.get("role_primary") or canon_rec.get("role_primary")
        source_refs = source_ref_for_record(
            canon_rec,
            shard_file,
            line_num,
            record_index,
            enriched_dir,
            ai_dir,
            tiddler_shard_size,
        )
        relation_targets = []
        for rel in canon_rec.get("relations") or []:
            target = rel.get("target_id") or rel.get("target")
            if target:
                relation_targets.append(target)
        for rel in ai_rec.get("relation_targets") or []:
            target = rel.get("target_id") if isinstance(rel, dict) else safe_str(rel)
            if target and target not in relation_targets:
                relation_targets.append(target)
        tags = canon_rec.get("normalized_tags") or canon_rec.get("tags") or []
        items.append(
            {
                "id": canon_rec.get("id"),
                "title": canon_rec.get("title"),
                "type": role,
                "summary": derive_microsoft_copilot_summary(canon_rec, ai_rec, role),
                "tags": tags,
                "source_refs": source_refs,
                "authority_level": copilot_layer.get("authority"),
                "derived_from": ["canon", "enriched", "ai"],
                "lineage_parents": copilot_layer.get("lineage_parents"),
                "related_ids": relation_targets[:50],
                "bundle_path": None,
                "updated_at": None,
                "content_hash": canon_rec.get("version_id"),
                "content_type": canon_rec.get("content_type"),
                "is_binary": bool(canon_rec.get("is_binary")),
                "corpus_state": ai_rec.get("corpus_state") or enriched_rec.get("corpus_state"),
                "retrieval_terms": ai_rec.get("retrieval_terms") or [],
                "retrieval_aliases": ai_rec.get("retrieval_aliases") or [],
                "confidence": ai_rec.get("confidence"),
                "taxonomy_path": enriched_rec.get("taxonomy_path") or ai_rec.get("taxonomy_path") or [],
                "section_path": enriched_rec.get("section_path") or ai_rec.get("section_path") or [],
                "canon_ref": source_refs["canon"],
                "source_primary": source_refs["canon"]["path"],
                "_canon_rec": canon_rec,
                "_ai_rec": ai_rec,
            }
        )
    return items


def select_bundle_members(items: list[dict]) -> dict[str, list[dict]]:
    recent_session_re = re.compile(r"(sesión|sesion)\s+(5[8-9]|6[0-1])|m03-s(58|59|60|61)", re.IGNORECASE)
    bundles = {
        "bundles/recent_sessions.txt": [],
        "bundles/governance_core.txt": [],
        "bundles/pipeline_and_layers.txt": [],
    }
    governance_titles = {
        "_🧱README.md",
        "README.md",
        "data/README.md",
        "docs/Informe_Tecnico_de_Tiddler (Esp).md",
        "contratos/projections/derived_layers_registry.json",
        "contratos/policy/canon_policy_bundle.json",
    }
    pipeline_titles = {
        "python_scripts/derive_layers.py",
        "python_scripts/corpus_governance.py",
        "python_scripts/path_governance.py",
        "python_scripts/validate_corpus_governance.py",
        "data/out/local/enriched/manifest.json",
        "data/out/local/ai/manifest.json",
        "data/out/local/audit/manifest.json",
    }
    for item in items:
        title = safe_str(item.get("title"))
        role = safe_str(item.get("type"))
        if recent_session_re.search(title):
            bundles["bundles/recent_sessions.txt"].append(item)
        if title in governance_titles or role in {"protocol", "policy", "readme", "glossary", "schema"}:
            if len(bundles["bundles/governance_core.txt"]) < 24:
                bundles["bundles/governance_core.txt"].append(item)
        if title in pipeline_titles:
            bundles["bundles/pipeline_and_layers.txt"].append(item)
    for bundle_path, members in bundles.items():
        for item in members:
            item["bundle_path"] = bundle_path
    return bundles


def build_topics_payload(items: list[dict], updated_at: str) -> dict:
    role_counts = Counter(safe_str(item.get("type") or "unknown") for item in items)
    tag_counts = Counter()
    for item in items:
        for tag in item.get("tags") or []:
            tag_counts[safe_str(tag)] += 1
    role_topics = [
        {
            "id": f"role:{role}",
            "title": role,
            "type": "role_topic",
            "summary": f"{count} nodos clasificados como {role}",
            "source_refs": ["data/out/local/enriched/manifest.json", "data/out/local/ai/manifest.json"],
            "authority_level": "derived_non_authoritative_agent_projection",
            "derived_from": ["enriched", "ai"],
            "related_ids": [item["id"] for item in items if item.get("type") == role][:50],
            "bundle_path": None,
            "updated_at": updated_at,
        }
        for role, count in role_counts.most_common()
    ]
    tag_topics = [
        {
            "id": f"tag:{normalize_for_dedup(tag).replace(' ', '-')[:80]}",
            "title": tag,
            "type": "tag_topic",
            "summary": f"{count} nodos con tag normalizado {tag}",
            "source_refs": ["data/out/local/tiddlers_*.jsonl", "data/out/local/enriched/"],
            "authority_level": "derived_non_authoritative_agent_projection",
            "derived_from": ["canon", "enriched"],
            "related_ids": [item["id"] for item in items if tag in (item.get("tags") or [])][:50],
            "bundle_path": None,
            "updated_at": updated_at,
        }
        for tag, count in tag_counts.most_common(40)
    ]
    return {
        "layer_id": "microsoft_copilot",
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "authority_class": "derived_non_authoritative_agent_projection",
        "projection_purpose": "topic and role map for agent navigation in JSON",
        "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "topics": role_topics + tag_topics,
    }


def build_navigation_index_s61(items: list[dict], source_inventory: dict,
                               bundles: dict[str, list[dict]], updated_at: str) -> dict:
    copilot_layer = get_layer_registry_entry("microsoft_copilot")
    role_dist = Counter(item.get("type", "unknown") for item in items)
    by_title = {safe_str(item.get("title")): item for item in items}
    foundational_titles = [
        "README.md",
        "data/README.md",
        "_🧱README.md",
        "contratos/policy/canon_policy_bundle.json",
        "contratos/projections/derived_layers_registry.json",
    ]
    foundational_nodes = [
        {
            "id": by_title[title].get("id"),
            "title": by_title[title].get("title"),
            "type": by_title[title].get("type"),
            "summary": by_title[title].get("summary"),
            "source_refs": by_title[title].get("source_refs"),
            "bundle_path": by_title[title].get("bundle_path"),
        }
        for title in foundational_titles
        if title in by_title
    ]
    recent_sessions = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "type": item.get("type"),
            "summary": item.get("summary"),
            "source_refs": item.get("source_refs"),
            "bundle_path": item.get("bundle_path"),
        }
        for item in sorted(
            [item for item in items if safe_str(item.get("title")).lower().find("sesión") >= 0 or safe_str(item.get("title")).lower().find("sesion") >= 0],
            key=lambda entry: (entry.get("canon_ref") or {}).get("line") or 0,
            reverse=True,
        )[:MICROSOFT_COPILOT_OVERVIEW_MAX_ITEMS]
    ]
    return {
        "layer_id": "microsoft_copilot",
        "format_version": MICROSOFT_COPILOT_FORMAT_VERSION,
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "source_inputs": source_inventory,
        "authority_class": copilot_layer.get("authority"),
        "lineage_parents": copilot_layer.get("lineage_parents"),
        "projection_purpose": "start-here navigation map for JSON/CSV/TXT Microsoft Copilot projection",
        "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "multisource_arbitration": True,
        "corpus_snapshot": {
            "total_records": len(items),
            "role_distribution": dict(role_dist.most_common()),
            "json_final": ["manifest.json", "navigation_index.json", "entities.json", "topics.json", "source_arbitration_report.json"],
            "csv_final": ["nodes.csv", "edges.csv", "artifacts.csv", "coverage.csv"],
            "txt_final": ["overview.txt", "reading_guide.txt", "bundles/*.txt"],
            "jsonl_final_primary": False,
        },
        "navigation": {
            "start_here": [
                {"path": "data/out/local/microsoft_copilot/overview.txt", "purpose": "plain-text orientation for agents"},
                {"path": "data/out/local/microsoft_copilot/manifest.json", "purpose": "layer identity, authority and artifact inventory"},
                {"path": "data/out/local/microsoft_copilot/navigation_index.json", "purpose": "navigation map"},
                {"path": "data/out/local/microsoft_copilot/entities.json", "purpose": "structured entity index"},
                {"path": "data/out/local/microsoft_copilot/nodes.csv", "purpose": "tabular node list"},
                {"path": "data/out/local/microsoft_copilot/edges.csv", "purpose": "tabular relation list"},
                {"path": "data/out/local/microsoft_copilot/reading_guide.txt", "purpose": "plain-text reading flow"},
            ],
            "foundational_nodes": foundational_nodes,
            "recent_sessions": recent_sessions,
            "bundles": [
                {
                    "path": f"data/out/local/microsoft_copilot/{bundle_path}",
                    "member_count": len(members),
                    "purpose": "preserve substantive text for agent reading",
                }
                for bundle_path, members in bundles.items()
            ],
        },
        "layer_status": {
            "audit_manifest": (source_inventory.get("audit") or {}).get("manifest_path"),
            "export_present": (source_inventory.get("export") or {}).get("present"),
            "external_format_reference": MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF,
        },
    }


def build_edges_rows(items: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    for item in items:
        source_id = item.get("id")
        canon_rec = item.get("_canon_rec") or {}
        ai_rec = item.get("_ai_rec") or {}
        source_file = ((item.get("source_refs") or {}).get("canon") or {}).get("path")
        for rel in canon_rec.get("relations") or []:
            target = rel.get("target_id") or rel.get("target")
            relation_type = rel.get("type") or "canonical_relation"
            key = (source_id, target, relation_type, "canon")
            if target and key not in seen:
                seen.add(key)
                rows.append(
                    {
                        "source_id": source_id,
                        "target_id": target,
                        "relation_type": relation_type,
                        "provenance": "canon.relations",
                        "confidence": "1.0",
                        "source_file": source_file,
                    }
                )
        for rel in ai_rec.get("relation_targets") or []:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target_id")
            relation_type = rel.get("type") or "ai_relation_target"
            key = (source_id, target, relation_type, "ai")
            if target and key not in seen:
                seen.add(key)
                rows.append(
                    {
                        "source_id": source_id,
                        "target_id": target,
                        "relation_type": relation_type,
                        "provenance": f"ai.relation_targets:{rel.get('evidence') or 'derived'}",
                        "confidence": safe_str(item.get("confidence") or ""),
                        "source_file": source_file,
                    }
                )
        # S84: add capa-2 embedded relations to edges
        for rel in ai_rec.get("embedded_relations") or []:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target_id")
            relation_type = rel.get("type") or "embedded"
            key = (source_id, target, relation_type, "embedded")
            if target and key not in seen:
                seen.add(key)
                rows.append(
                    {
                        "source_id": source_id,
                        "target_id": target,
                        "relation_type": relation_type,
                        "provenance": "content_embedded",
                        "confidence": "0.9",
                        "source_file": source_file,
                    }
                )
    return rows


def build_coverage_rows(source_inventory: dict) -> list[dict]:
    return [
        {"source_layer": "canon", "artifact_target": "entities.json,nodes.csv,edges.csv,bundles/*.txt", "coverage_status": "used", "notes": "source of truth for IDs, titles, text, relations, hashes and line refs"},
        {"source_layer": "enriched", "artifact_target": "entities.json,topics.json,nodes.csv", "coverage_status": "used", "notes": "roles, taxonomy, section paths, quality flags"},
        {"source_layer": "ai", "artifact_target": "entities.json,topics.json,edges.csv,navigation_index.json", "coverage_status": "used", "notes": "summaries, retrieval terms, relation targets and confidence"},
        {"source_layer": "audit", "artifact_target": "manifest.json,coverage.csv,navigation_index.json", "coverage_status": "used_if_present", "notes": "latest validation context from audit manifest/summary"},
        {"source_layer": "export", "artifact_target": "manifest.json,coverage.csv", "coverage_status": "optional_present" if (source_inventory.get("export") or {}).get("present") else "optional_absent", "notes": "export artifacts are not required for S61 MVP"},
        {"source_layer": "manifests", "artifact_target": "manifest.json,source_arbitration_report.json", "coverage_status": "used", "notes": "layer counts, authority, lineage and last derived status"},
        {"source_layer": "contratos_recientes", "artifact_target": "bundles/recent_sessions.txt,spec/*.md", "coverage_status": "used", "notes": "S58-S60 historical decisions and S61 closure"},
        {"source_layer": "microsoft_support", "artifact_target": "source_arbitration_report.json,spec/summaries/microsoft-support-formats.*", "coverage_status": "used_as_external_reference", "notes": "format coherence only; no authority over canon"},
    ]


def write_bundle_files(copilot_dir: Path, bundles: dict[str, list[dict]], updated_at: str) -> list[Path]:
    written = []
    purposes = {
        "bundles/recent_sessions.txt": "Preservar memoria reciente S58-S61 y la transicion S60 JSONL -> S61 JSON/CSV/TXT.",
        "bundles/governance_core.txt": "Exponer reglas y documentos fundacionales necesarios para leer la proyeccion.",
        "bundles/pipeline_and_layers.txt": "Explicar el flujo de derivacion y estado de capas sin convertirlo en canon.",
    }
    for bundle_path, members in bundles.items():
        content = [
            "Este bundle es texto plano derivado y no autoritativo.",
            "No reemplaza `data/out/local/tiddlers_*.jsonl` ni los archivos fuente.",
            "",
        ]
        for item in members:
            canon_rec = item.get("_canon_rec") or {}
            source = ((item.get("source_refs") or {}).get("canon") or {})
            content.extend(
                [
                    f"--- SOURCE_TITLE: {item.get('title')}",
                    f"SOURCE_ID: {item.get('id')}",
                    f"SOURCE_REF: {source.get('path')}:{source.get('line')}",
                    f"CONTENT_HASH: {item.get('content_hash')}",
                    "",
                    truncate_declared(canonical_reading_text(canon_rec), 14000, safe_str(item.get("title"))),
                    "",
                ]
            )
        path = copilot_dir / bundle_path
        lines = text_artifact_lines(
            title=bundle_path.rsplit("/", 1)[-1],
            purpose=purposes[bundle_path],
            source="canon + enriched + ai + recent contracts, selected by S61 relevance",
            tags=["microsoft_copilot", "bundle", "txt", "derived"],
            content_lines=content,
            updated_at=updated_at,
        )
        written.append(write_text_file(path, lines))
    return written


def write_overview_and_reading_guide(copilot_dir: Path, navigation_index: dict,
                                     source_inventory: dict, updated_at: str) -> list[Path]:
    snapshot = navigation_index.get("corpus_snapshot") or {}
    overview_lines = text_artifact_lines(
        title="microsoft_copilot JSON/CSV/TXT projection",
        purpose="Superficie de lectura derivada para Microsoft Copilot y agentes remotos.",
        source="canon local + enriched + ai + audit/export manifests + contratos recientes",
        tags=["microsoft_copilot", "overview", "txt", "derived"],
        updated_at=updated_at,
        content_lines=[
            "`microsoft_copilot/` es derivada y no autoritativa.",
            "El canon local sigue siendo `data/out/local/tiddlers_*.jsonl`.",
            "S61 elimina `.jsonl` como salida final primaria de esta capa.",
            "",
            "FORMAT FAMILIES:",
            "- JSON: manifest, navigation, entities, topics, source arbitration.",
            "- CSV: nodes, edges, artifacts, coverage.",
            "- TXT: overview, reading guide and curated bundles.",
            "",
            f"TOTAL_RECORDS: {snapshot.get('total_records')}",
            f"JSONL_FINAL_PRIMARY: {snapshot.get('jsonl_final_primary')}",
            "",
            "START:",
            "- Leer `reading_guide.txt` para flujo narrativo.",
            "- Usar `navigation_index.json` para explorar sesiones, documentos fundacionales y bundles.",
            "- Usar `entities.json` y `nodes.csv` para buscar nodos.",
            "- Usar `edges.csv` para relaciones.",
            "- Usar `source_arbitration_report.json` para verificar fuentes reales por artefacto.",
        ],
    )
    guide_lines = text_artifact_lines(
        title="reading guide",
        purpose="Ruta de lectura para agentes remotos que no conocen la jerarquia del repo.",
        source="manifest + navigation_index + source_arbitration_report",
        tags=["microsoft_copilot", "reading-guide", "txt", "derived"],
        updated_at=updated_at,
        content_lines=[
            "1. Confirmar autoridad: esta capa no es canon.",
            "2. Leer `overview.txt` para alcance y familias de formato.",
            "3. Abrir `manifest.json` para linaje, conteos y artefactos.",
            "4. Abrir `navigation_index.json` para nodos fundacionales y sesiones recientes.",
            "5. Consultar `bundles/recent_sessions.txt` para S58-S61.",
            "6. Consultar `bundles/governance_core.txt` para reglas y documentos base.",
            "7. Usar `entities.json` para estructura semantica y `nodes.csv` para tabla plana.",
            "8. Usar `edges.csv` para relaciones y `coverage.csv` para saber que capas alimentaron cada salida.",
            "",
            "Si una respuesta exige texto exacto o codigo completo, volver al canon o a la fuente indicada por `source_refs`.",
        ],
    )
    return [
        write_text_file(copilot_dir / "overview.txt", overview_lines),
        write_text_file(copilot_dir / "reading_guide.txt", guide_lines),
    ]


def write_s61_spec_artifacts(copilot_dir: Path, updated_at: str) -> list[Path]:
    written = []
    summaries_dir = copilot_dir / "spec" / "summaries"
    for summary in S61_SPEC_SUMMARIES:
        payload = {
            "id": summary["slug"],
            "title": summary["title"],
            "summary": summary["summary"],
            "source_files": summary["source_files"],
            "rules": summary["rules"],
            "required_artifacts": summary["artifacts"],
            "impact": summary["impact"],
            "reference": summary["source_files"],
            "projection_impact": summary["projection_impact"],
            "authority": "derived_non_authoritative",
            "updated_at": updated_at,
        }
        written.append(write_json_file(summaries_dir / f"{summary['slug']}.json", payload))
        md_lines = [
            f"# {summary['title']}",
            "",
            "## Resumen",
            summary["summary"],
            "",
            "## Reglas",
            *[f"- {rule}" for rule in summary["rules"]],
            "",
            "## Artefactos",
            *[f"- {artifact}" for artifact in summary["artifacts"]],
            "",
            "## Impacto",
            summary["impact"],
            "",
            "## Referencia",
            *[f"- `{ref}`" for ref in summary["source_files"]],
            "",
            "## Impacto en proyeccion Copilot",
            *[f"- {impact}" for impact in summary["projection_impact"]],
            "",
            f"UPDATED_AT: {updated_at}",
        ]
        written.append(write_text_file(summaries_dir / f"{summary['slug']}.md", md_lines))

    mapping = [
        {
            "id": "s61-json-structure",
            "title": "JSON estructural",
            "summary": "Manifest, navegacion, entidades, topicos y arbitraje.",
            "source_files": ["canon", "enriched", "ai", "manifests", "contratos recientes"],
            "required_artifacts": ["manifest.json", "navigation_index.json", "entities.json", "topics.json", "source_arbitration_report.json"],
            "actions": ["generar objetos compactos", "mantener source_refs", "declarar autoridad"],
            "priority": "P0",
            "projection_role": "estructura y navegacion",
        },
        {
            "id": "s61-csv-tables",
            "title": "CSV relacional y tabular",
            "summary": "Nodos, edges, artefactos y cobertura.",
            "source_files": ["canon", "ai", "registry", "manifest outputs"],
            "required_artifacts": ["nodes.csv", "edges.csv", "artifacts.csv", "coverage.csv"],
            "actions": ["materializar tablas simples", "serializar listas como JSON en celdas", "mantener rutas fuente"],
            "priority": "P0",
            "projection_role": "relaciones y cobertura",
        },
        {
            "id": "s61-txt-reading",
            "title": "TXT contextual",
            "summary": "Overview, guia y bundles narrativos seleccionados.",
            "source_files": ["canon", "contratos recientes", "README", "registry"],
            "required_artifacts": ["overview.txt", "reading_guide.txt", "bundles/*.txt"],
            "actions": ["preservar texto sustantivo", "declarar truncados", "no copiar todo indiscriminadamente"],
            "priority": "P0",
            "projection_role": "lectura contextual",
        },
        {
            "id": "s61-registry-docs",
            "title": "Registro y documentacion",
            "summary": "Actualizar registry, README y data/README para reflejar JSON/CSV/TXT.",
            "source_files": ["contratos/projections/derived_layers_registry.json", "README.md", "data/README.md"],
            "required_artifacts": ["registry actualizado", "docs actualizadas"],
            "actions": ["retirar path patterns JSONL", "declarar no autoridad", "mantener flujo derive_layers.py"],
            "priority": "P1",
            "projection_role": "gobernanza minima",
        },
    ]
    plan_lines = [
        "# Plan de implementacion S61",
        "",
        "## Mapeo",
        "```json",
        json.dumps(mapping, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Conflictos y resoluciones",
        "- Conflicto: S60 emitia `tiddlers_microsoft_copilot_*.jsonl` como lectura final; S61 fija JSON/CSV/TXT. Opcion A: conservar JSONL como legacy oculto, pro: compatibilidad, contra: ambiguedad. Opcion B: eliminar JSONL final y registrar reemplazo, pro: cumple S61, contra: requiere regeneracion. Resolucion aplicada: opcion B.",
        "- Conflicto: preservar texto vs evitar duplicacion. Opcion A: copiar todo el canon a TXT, pro: maxima disponibilidad, contra: costo y ruido. Opcion B: bundles seleccionados con source_refs, pro: util y mantenible, contra: exige volver al canon para texto completo. Resolucion aplicada: opcion B con truncado declarado.",
        "- Conflicto: instruccion propia de Copilot vs derivado normal. Opcion A: recrear instruccion, pro: visibilidad local, contra: complejidad normativa. Opcion B: registry/manifests/spec, pro: menor complejidad. Resolucion aplicada: opcion B.",
        "",
        "## Backlog priorizado",
        "- P0: Generar JSON/CSV/TXT desde `derive_layers.py`; depende de canon/enriched/ai.",
        "- P0: Retirar JSONL como salida final primaria; depende de limpieza de outputs obsoletos.",
        "- P1: Actualizar registry y docs; depende de modelo de artefactos cerrado.",
        "- P1: Crear contrato y familia canonica S61; depende de implementacion validable.",
        "- P1: Validar strict, reverse-preflight, reverse real, derivacion y tests focalizados.",
        "",
        "## Arbitraje de fuentes",
        "- Canon: IDs, texto, relaciones, hashes y reversibilidad.",
        "- Enriched: roles, taxonomia, contexto estructural y calidad.",
        "- AI: resumen, retrieval terms, relation_targets y confianza.",
        "- Audit/export/manifests: estado, cobertura y validacion.",
        "- Contratos recientes/docs: decisiones activas y continuidad S58-S61.",
    ]
    written.append(write_text_file(copilot_dir / "spec" / "plan_de_implementacion_s61.md", plan_lines))

    checklist_lines = [
        "# Checklist global S61",
        "",
        "- [x] Leer gobernanza interna obligatoria.",
        "- [x] Revisar S58, S59 y S60.",
        "- [x] Revisar estructura `data/out/local/` y `microsoft_copilot/` actual.",
        "- [x] Confirmar referencia oficial Microsoft para JSON/CSV/TXT.",
        "- [x] Reemplazar salida final JSONL por JSON/CSV/TXT.",
        "- [x] Mantener autoridad del canon intacta.",
        "- [x] Declarar fuentes y arbitraje por artefacto.",
        "- [x] Cerrar contrato S61 y familia canonica.",
        "- [x] Ejecutar validaciones finales tras cierre canonico.",
    ]
    written.append(write_text_file(copilot_dir / "spec" / "checklist_global_s61.md", checklist_lines))

    memory_lines = [
        "# Memoria de decisiones S61",
        "",
        "## Hipotesis inicial",
        "Si `microsoft_copilot/` usa JSON para estructura, CSV para relaciones/tablas y TXT para lectura contextual, entonces mejora su legibilidad por agentes externos sin invertir la autoridad del canon.",
        "",
        "## Decisiones",
        "- `microsoft_copilot/` sigue siendo derivada y no autoritativa.",
        "- `.jsonl` queda excluido como salida final primaria de S61.",
        "- JSON se usa para navegacion, entidades, topicos, manifest y arbitraje.",
        "- CSV se usa para nodos, relaciones, artefactos y cobertura.",
        "- TXT se usa para overview, guia y bundles narrativos seleccionados.",
        "- No se recrea una instruccion especifica de Copilot; se usa registry, manifest y spec.",
        "",
        "## Procedencia",
        "- Fuentes internas: instrucciones, contratos S58-S60, README, data/README, registry, manifests y canon.",
        f"- Fuente externa oficial: {MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF['url']}",
        "",
        "## Reversibilidad",
        "Los cambios al canon se cierran con familia S61 y validaciones strict, reverse-preflight y reverse real. Los outputs de `microsoft_copilot/` son regenerables por `python_scripts/derive_layers.py`.",
    ]
    written.append(write_text_file(copilot_dir / "spec" / "memoria_decisiones_s61.md", memory_lines))
    return written


def build_source_arbitration_report_s61(copilot_dir: Path, source_inventory: dict,
                                        artifacts: list[dict], updated_at: str) -> dict:
    copilot_layer = get_layer_registry_entry("microsoft_copilot")
    return {
        "layer_id": "microsoft_copilot",
        "format_version": MICROSOFT_COPILOT_FORMAT_VERSION,
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "source_inputs": source_inventory,
        "authority_class": copilot_layer.get("authority"),
        "lineage_parents": copilot_layer.get("lineage_parents"),
        "projection_purpose": "artifact-level source arbitration for JSON/CSV/TXT agent projection",
        "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "multisource_arbitration": True,
        "format_decision": {
            "json": "structure, nodes, metadata, navigation and arbitration",
            "csv": "relations, artifact inventory and coverage tables",
            "txt": "plain contextual reading and curated substantive bundles",
            "excluded_as_final_primary": [".jsonl", ".rdf", ".owl", ".graphml"],
        },
        "external_format_reference": MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF,
        "artifacts": artifacts,
        "arbitration_by_family": [
            {
                "family": "json",
                "source_priority": ["canon", "enriched", "ai", "manifests", "audit/export"],
                "reason": "needs structure, source refs, semantic navigation and authority metadata",
                "reversible_by": "source_refs + content_hash + canon shard line",
            },
            {
                "family": "csv",
                "source_priority": ["canon", "ai", "registry", "manifest outputs"],
                "reason": "needs tabular relation and coverage extraction",
                "reversible_by": "source_id/target_id plus source_file/provenance",
            },
            {
                "family": "txt",
                "source_priority": ["canon", "contracts", "README", "registry"],
                "reason": "needs contextual reading without hiding source authority",
                "reversible_by": "SOURCE_REF and CONTENT_HASH headers per bundle section",
            },
        ],
    }


# ── Copilot Agent compressed sublayer (S64) ───────────────────────────────────

def compact_agent_text(text: str, max_chars: int) -> str:
    text = safe_str(text).replace("\r", "\n")
    if not text.strip():
        return ""

    text = re.sub(r"```.*?```", " [code omitted] ", text, flags=re.DOTALL)
    cleaned_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("```"):
            continue
        if line.startswith(("TITLE:", "PURPOSE:", "AUTHORITY:", "SOURCE:", "UPDATED_AT:", "TAGS:")):
            continue
        line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", line)
        line = re.sub(r"^[-*#>\s]+", "", line)
        line = line.replace("|", " ")
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned_lines.append(line)
        if len(cleaned_lines) >= 8:
            break

    compact = re.sub(r"\s+", " ", " ".join(cleaned_lines)).strip()
    if len(compact) <= max_chars:
        return compact
    shortened = compact[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return f"{shortened}..."


def infer_copilot_agent_entity_type(item: dict) -> str:
    if item.get("synthetic"):
        return "layer"

    title = safe_str(item.get("title")).strip()
    role = safe_str(item.get("type")).strip() or "unclassified"

    if title.startswith("contratos/") and title.endswith(".md.json"):
        return "contract"
    if title.endswith("/manifest.json"):
        return "manifest"
    if title in {
        "contratos/policy/canon_policy_bundle.json",
        "contratos/projections/derived_layers_registry.json",
    }:
        return "structural_node"
    if role == "config" and title.startswith(("# ", "## ", "### ", "#### ")):
        return "structural_node"
    return role


def infer_copilot_agent_family(item: dict, entity_type: str) -> str:
    title = normalize_for_dedup(safe_str(item.get("title")))
    summary = normalize_for_dedup(safe_str(item.get("summary")))
    source = normalize_for_dedup(safe_str(item.get("source_primary")))
    tags = " ".join(normalize_for_dedup(safe_str(tag)) for tag in (item.get("tags") or []))
    haystack = " ".join(part for part in (title, summary, source, tags) if part)

    if item.get("synthetic"):
        return "integration_flow"
    if (
        "microsoft-copilot" in haystack
        or "microsoft_copilot" in haystack
        or "copilot-agent" in haystack
        or "copilot_agent" in haystack
        or re.search(r"m03-s(59|60|61|62|63|64)", haystack)
    ):
        return "copilot_projection"
    if (
        "reverse" in haystack
        or "authoritative-upsert" in haystack
        or "reverse-preflight" in haystack
        or "canonical_slug" in haystack
        or "version_id" in haystack
        or "normalized_tags" in haystack
        or "embedded_json" in haystack
        or "go/canon/" in haystack
        or "canon_policy" in haystack
        or "identity.go" in haystack
        or "normalizer.go" in haystack
        or "embedded_json_text.go" in haystack
    ):
        return "strict_reversibility"
    if entity_type in {"session", "hypothesis", "provenance", "contract"}:
        return "minimal_canon"
    if entity_type in {"policy", "protocol", "glossary", "schema"}:
        return "semantic_compression"
    return "integration_flow"


def copilot_agent_priority_score(item: dict, entity_type: str, family: str) -> int:
    family_weight = {
        "integration_flow": 70,
        "semantic_compression": 75,
        "copilot_projection": 90,
        "minimal_canon": 68,
        "strict_reversibility": 85,
    }
    type_weight = {
        "layer": 80,
        "policy": 50,
        "protocol": 48,
        "contract": 46,
        "session": 38,
        "hypothesis": 32,
        "provenance": 32,
        "readme": 28,
        "architecture": 28,
        "manifest": 24,
        "structural_node": 24,
        "code_source": 24,
        "glossary": 20,
        "schema": 20,
    }

    title = normalize_for_dedup(safe_str(item.get("title")))
    source = normalize_for_dedup(safe_str(item.get("source_primary")))
    marker = extract_session_marker(item)
    score = family_weight.get(family, 40) + type_weight.get(entity_type, 12)
    score += min(len(item.get("related_ids") or []), 12)
    score += min(len(item.get("tags") or []), 8)

    if item.get("synthetic"):
        return score + 1000
    if title in {
        "readme.md",
        "## 🗂🧱 principios de gestion",
        "## 🧭🧱 protocolo de sesion",
        "## 🎯🧱 detalles del tema",
        "contratos/policy/canon_policy_bundle.json",
        "contratos/projections/derived_layers_registry.json",
        "python_scripts/derive_layers.py",
    }:
        score += 35
    if marker in COPILOT_AGENT_RECENT_MARKERS or re.search(r"m03-s(59|60|61|62|63|64)", title):
        score += 55
    if marker in COPILOT_AGENT_REVERSE_MARKERS:
        score += 30
    if "microsoft-copilot" in title or "copilot-agent" in title:
        score += 35
    if source.startswith("go/canon/") or source.startswith("python_scripts/"):
        score += 18
    if entity_type == "session" and marker in COPILOT_AGENT_RECENT_MARKERS:
        score += 30
    if entity_type in {"contract", "hypothesis", "provenance"} and marker and marker not in (COPILOT_AGENT_RECENT_MARKERS | COPILOT_AGENT_REVERSE_MARKERS):
        score -= 120
    if entity_type == "session" and marker and marker not in (COPILOT_AGENT_RECENT_MARKERS | COPILOT_AGENT_REVERSE_MARKERS):
        score -= 260
    return score


def copilot_agent_selection_reason(entity_type: str, family: str) -> str:
    if entity_type == "layer":
        return "captures official layer lineage and authority boundaries."
    if family == "integration_flow":
        return "keeps the real pipeline surface legible without reopening the architecture."
    if family == "semantic_compression":
        return "preserves the rules that make the compressed pack cognitively readable."
    if family == "copilot_projection":
        return "anchors the Microsoft Copilot and copilot_agent lineage inside the real flow."
    if family == "minimal_canon":
        return "tracks the minimum session closure that must remain absorbed in canon."
    if family == "strict_reversibility":
        return "pins the deterministic inputs required for strict reverse compatibility."
    return "retained as a high-value structural anchor."


def build_copilot_agent_layer_entities() -> list[dict]:
    canon_layer = get_layer_registry_entry("canon")
    enriched_layer = get_layer_registry_entry("enriched")
    ai_layer = get_layer_registry_entry("ai")
    copilot_layer = get_layer_registry_entry("microsoft_copilot")
    return [
        {
            "id": "layer:canon",
            "title": "Layer: canon",
            "summary": "Local source of truth backed by data/out/local/tiddlers_*.jsonl and required for strict, reverse-preflight and reverse authoritativo.",
            "type": "layer",
            "authority_level": canon_layer.get("authority"),
            "source_primary": "data/out/local/tiddlers_*.jsonl",
            "tags": ["layer:canon", "authority:local-source-of-truth"],
            "related_ids": ["layer:enriched", "layer:ai", "layer:microsoft_copilot"],
            "taxonomy_path": ["layer", "canon"],
            "synthetic": True,
        },
        {
            "id": "layer:enriched",
            "title": "Layer: enriched",
            "summary": "First derived layer that adds structural enrichment, role inference, taxonomy and section context without changing canonical authority.",
            "type": "layer",
            "authority_level": enriched_layer.get("authority"),
            "source_primary": "data/out/local/enriched/manifest.json",
            "tags": ["layer:enriched", "derived:non-authoritative"],
            "related_ids": ["layer:canon", "layer:microsoft_copilot"],
            "taxonomy_path": ["layer", "enriched"],
            "synthetic": True,
        },
        {
            "id": "layer:ai",
            "title": "Layer: ai",
            "summary": "Second derived layer for summaries, retrieval hints, relation targets and chunk-ready records used by downstream agent projections.",
            "type": "layer",
            "authority_level": ai_layer.get("authority"),
            "source_primary": "data/out/local/ai/manifest.json",
            "tags": ["layer:ai", "derived:non-authoritative"],
            "related_ids": ["layer:canon", "layer:microsoft_copilot"],
            "taxonomy_path": ["layer", "ai"],
            "synthetic": True,
        },
        {
            "id": "layer:microsoft_copilot",
            "title": "Layer: microsoft_copilot",
            "summary": "Official JSON/CSV/TXT projection introduced in S61. It remains derived, traces to canon plus enriched/ai and feeds copilot_agent.",
            "type": "layer",
            "authority_level": copilot_layer.get("authority"),
            "source_primary": "data/out/local/microsoft_copilot/manifest.json",
            "tags": ["layer:microsoft_copilot", "derived:agent-projection"],
            "related_ids": ["layer:canon", "layer:enriched", "layer:ai", "layer:copilot_agent"],
            "taxonomy_path": ["layer", "microsoft_copilot"],
            "synthetic": True,
        },
        {
            "id": "layer:copilot_agent",
            "title": "Layer: copilot_agent",
            "summary": "Compressed three-file snapshot for external agents. S63 integrated it into the pipeline and S64 hardens semantic balance plus reversibility constraints.",
            "type": "layer",
            "authority_level": "derived_non_authoritative_agent_projection",
            "source_primary": "data/out/local/microsoft_copilot/copilot_agent/",
            "tags": ["layer:copilot_agent", "derived:agent-projection", "format:three-file-pack"],
            "related_ids": ["layer:microsoft_copilot", "layer:canon"],
            "taxonomy_path": ["layer", "copilot_agent"],
            "synthetic": True,
        },
    ]


def decorate_copilot_agent_item(item: dict) -> dict:
    entity_type = infer_copilot_agent_entity_type(item)
    family = infer_copilot_agent_family(item, entity_type)
    decorated = dict(item)
    decorated["entity_type"] = entity_type
    decorated["semantic_family"] = family
    decorated["related_count"] = len(item.get("related_ids") or [])
    decorated["priority_score"] = copilot_agent_priority_score(item, entity_type, family)
    decorated["selection_reason"] = copilot_agent_selection_reason(entity_type, family)
    decorated["tier"] = 1 if decorated["priority_score"] >= 120 else 2
    return decorated


def sort_copilot_agent_entities(items: list[dict]) -> list[dict]:
    family_order = {family: idx for idx, family in enumerate(COPILOT_AGENT_FAMILY_ORDER)}
    return sorted(
        items,
        key=lambda item: (
            family_order.get(item.get("semantic_family"), 99),
            -int(item.get("priority_score") or 0),
            normalize_for_dedup(safe_str(item.get("title"))),
        ),
    )


def select_copilot_agent_entities(items: list[dict]) -> list[dict]:
    synthetic_entities = [decorate_copilot_agent_item(item) for item in build_copilot_agent_layer_entities()]
    decorated_items = [decorate_copilot_agent_item(item) for item in items]

    selected = []
    seen_ids = set()
    type_counts = Counter()

    def add_candidate(candidate: dict) -> bool:
        candidate_id = safe_str(candidate.get("id"))
        if not candidate_id or candidate_id in seen_ids:
            return False
        entity_type = safe_str(candidate.get("entity_type"))
        marker = extract_session_marker(candidate)
        if entity_type == "session":
            title_norm = normalize_for_dedup(safe_str(candidate.get("title")))
            title_is_priority_session = bool(
                re.search(r"sesion\s+(50|57|59|60|61|62|63|64)\b", title_norm)
                or "microsoft-copilot" in title_norm
                or "copilot-agent" in title_norm
                or "reverse" in title_norm
                or "canon-direct-close" in title_norm
            )
            if marker not in (COPILOT_AGENT_RECENT_MARKERS | COPILOT_AGENT_REVERSE_MARKERS) and not title_is_priority_session:
                return False
        type_cap = COPILOT_AGENT_TYPE_CAPS.get(entity_type)
        if type_cap is not None and type_counts[entity_type] >= type_cap:
            return False
        selected.append(candidate)
        seen_ids.add(candidate_id)
        type_counts[entity_type] += 1
        return True

    for candidate in synthetic_entities:
        add_candidate(candidate)

    recent_session_candidates = sorted(
        [
            candidate
            for candidate in decorated_items
            if candidate.get("entity_type") == "session"
            and extract_session_marker(candidate) in (COPILOT_AGENT_RECENT_MARKERS | COPILOT_AGENT_REVERSE_MARKERS)
        ],
        key=lambda item: (-int(item.get("priority_score") or 0), normalize_for_dedup(safe_str(item.get("title")))),
    )
    for candidate in recent_session_candidates[:5]:
        if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
            break
        add_candidate(candidate)

    strict_anchor_candidates = sort_copilot_agent_entities(
        [
            candidate
            for candidate in decorated_items
            if candidate.get("semantic_family") == "strict_reversibility"
            and safe_str(candidate.get("title")) in COPILOT_AGENT_STRICT_ANCHOR_TITLES
        ]
    )
    for candidate in strict_anchor_candidates:
        if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
            break
        add_candidate(candidate)

    reverse_session_candidates = sort_copilot_agent_entities(
        [
            candidate
            for candidate in decorated_items
            if candidate.get("semantic_family") == "strict_reversibility"
            and candidate.get("entity_type") == "session"
            and extract_session_marker(candidate) in COPILOT_AGENT_REVERSE_MARKERS
        ]
    )
    for candidate in reverse_session_candidates:
        if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
            break
        add_candidate(candidate)

    by_family = defaultdict(list)
    for candidate in decorated_items:
        by_family[candidate.get("semantic_family")].append(candidate)
    for family in COPILOT_AGENT_FAMILY_ORDER:
        by_family[family] = sort_copilot_agent_entities(by_family.get(family, []))

    for family in COPILOT_AGENT_FAMILY_ORDER:
        target = COPILOT_AGENT_FAMILY_TARGETS.get(family, 0)
        added = 0
        for candidate in by_family.get(family, []):
            if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
                break
            if add_candidate(candidate):
                added += 1
            if added >= target:
                break

    for candidate in sorted(
        decorated_items,
        key=lambda item: (-int(item.get("priority_score") or 0), normalize_for_dedup(safe_str(item.get("title")))),
    ):
        if len(selected) >= COPILOT_AGENT_ENTITY_LIMIT:
            break
        add_candidate(candidate)

    return sort_copilot_agent_entities(selected[:COPILOT_AGENT_ENTITY_LIMIT])


def copilot_agent_source_ref(item: dict) -> str:
    source = safe_str(item.get("source_primary"))
    line = ((item.get("canon_ref") or {}).get("line"))
    if line:
        return f"{source}:{line}"
    return source or "derived"


def extract_copilot_agent_signals(item: dict) -> list[str]:
    payload = parse_embedded_json_payload(item.get("_canon_rec") or {})
    signals = []
    seen = set()

    def add_signal(value, max_chars: int) -> None:
        compact = compact_agent_text(value, max_chars)
        if compact and compact not in seen:
            seen.add(compact)
            signals.append(compact)

    if payload:
        add_signal(embedded_json_primary_text(payload), 160)
        for key in ("content",):
            content = payload.get(key)
            if isinstance(content, dict):
                add_signal(content.get("plain") or content.get("markdown"), 160)
        for key in ("descripcion", "descripcion_breve", "hallazgo_clave", "hipotesis", "origen", "objetivo", "purpose", "summary"):
            add_signal(payload.get(key), 160)
        for key in ("decisiones_documentadas", "decisiones", "evidencia_base", "rules", "required_artifacts"):
            values = payload.get(key)
            if isinstance(values, list):
                for value in values[:2]:
                    add_signal(value, 120)
        if len(signals) < 2:
            for key in ("fuentes_usadas", "source_files", "reference"):
                values = payload.get(key)
                if isinstance(values, list):
                    for value in values[:2]:
                        add_signal(value, 90)
                if len(signals) >= 2:
                    break

    if not signals:
        fallback_signal = safe_str(item.get("summary")).strip()
        if fallback_signal.startswith(("{", "[")):
            fallback_signal = canonical_reading_text(item.get("_canon_rec") or {})
        add_signal(fallback_signal, 160)
    return signals[:2]


def copilot_agent_display_summary(item: dict, max_chars: int) -> str:
    summary = safe_str(item.get("summary")).strip()
    if summary.startswith(("{", "[")):
        summary = canonical_reading_text(item.get("_canon_rec") or {})
    if not summary and not item.get("synthetic"):
        summary = canonical_reading_text(item.get("_canon_rec") or {})
    if not summary and item.get("synthetic"):
        summary = safe_str(item.get("summary"))
    return compact_agent_text(summary, max_chars)


def resolve_copilot_agent_target_id(target, selected_by_id: dict, selected_title_to_id: dict) -> str | None:
    target_str = safe_str(target).strip()
    if not target_str:
        return None
    if target_str in selected_by_id:
        return target_str
    return selected_title_to_id.get(normalize_for_dedup(target_str))


def extract_session_marker(item: dict) -> str:
    for tag in (item.get("tags") or []):
        tag_str = safe_str(tag).strip()
        if tag_str.startswith("session:"):
            return tag_str.removeprefix("session:")
    title = normalize_for_dedup(safe_str(item.get("title")))
    match = re.search(r"m\d\d-s\d\d", title)
    return match.group(0) if match else ""


def build_copilot_agent_relations(selected_entities: list[dict]) -> list[dict]:
    relation_rows = []
    seen = set()
    selected_by_id = {safe_str(item.get("id")): item for item in selected_entities}
    selected_title_to_id = {
        normalize_for_dedup(safe_str(item.get("title"))): safe_str(item.get("id"))
        for item in selected_entities
    }

    def add_relation(source_id: str, target_id: str, relation_type: str,
                     provenance: str, confidence: str, source_layer: str, notes: str) -> None:
        if not source_id or not target_id or source_id == target_id:
            return
        key = (source_id, target_id, relation_type)
        if key in seen:
            return
        seen.add(key)
        relation_rows.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation_type,
                "provenance": provenance,
                "confidence": confidence,
                "source_layer": source_layer,
                "notes": notes,
            }
        )

    for item in selected_entities:
        if item.get("synthetic"):
            continue
        source_id = safe_str(item.get("id"))
        source_ref = copilot_agent_source_ref(item)
        for rel in (item.get("_canon_rec") or {}).get("relations") or []:
            target_id = resolve_copilot_agent_target_id(
                rel.get("target_id") or rel.get("target"),
                selected_by_id,
                selected_title_to_id,
            )
            relation_type = safe_str(rel.get("type")) or "canonical_relation"
            add_relation(source_id, target_id, relation_type, "canon.relations", "1.0", "canon", source_ref)
        for rel in (item.get("_ai_rec") or {}).get("relation_targets") or []:
            if not isinstance(rel, dict):
                continue
            target_id = resolve_copilot_agent_target_id(rel.get("target_id"), selected_by_id, selected_title_to_id)
            relation_type = safe_str(rel.get("type")) or "ai_relation_target"
            add_relation(
                source_id,
                target_id,
                relation_type,
                f"ai.relation_targets:{rel.get('evidence') or 'derived'}",
                safe_str(item.get("confidence") or ""),
                "ai",
                source_ref,
            )

    synthetic_layer_edges = [
        ("layer:enriched", "layer:canon", "layer_derives_from"),
        ("layer:ai", "layer:canon", "layer_derives_from"),
        ("layer:microsoft_copilot", "layer:canon", "layer_derives_from"),
        ("layer:microsoft_copilot", "layer:enriched", "layer_uses_as_source"),
        ("layer:microsoft_copilot", "layer:ai", "layer_uses_as_source"),
        ("layer:copilot_agent", "layer:microsoft_copilot", "layer_derives_from"),
        ("layer:copilot_agent", "layer:canon", "canon_is_source_of"),
    ]
    for source_id, target_id, relation_type in synthetic_layer_edges:
        add_relation(
            source_id,
            target_id,
            relation_type,
            "copilot_agent.layer_model",
            "1.0",
            "copilot_agent",
            "layer lineage synthesized for graph reconstruction",
        )

    session_groups = defaultdict(list)
    for item in selected_entities:
        marker = extract_session_marker(item)
        if marker:
            session_groups[marker].append(item)

    layer_by_session = {
        "m03-s59": ("layer:microsoft_copilot", "session_governs_layer"),
        "m03-s60": ("layer:microsoft_copilot", "session_generates_layer"),
        "m03-s61": ("layer:microsoft_copilot", "session_generates_layer"),
        "m03-s62": ("layer:copilot_agent", "session_defines_pack"),
        "m03-s63": ("layer:copilot_agent", "session_integrates_layer"),
        "m03-s64": ("layer:copilot_agent", "session_hardens_layer"),
        "m03-s50": ("layer:canon", "session_repairs_reversibility"),
        "m03-s57": ("layer:canon", "session_governs_layer"),
    }

    for marker, members in session_groups.items():
        sessions = [item for item in members if item.get("entity_type") == "session"]
        hypotheses = [item for item in members if item.get("entity_type") == "hypothesis"]
        provenances = [item for item in members if item.get("entity_type") == "provenance"]
        contracts = [item for item in members if item.get("entity_type") == "contract"]

        for session in sessions:
            session_id = safe_str(session.get("id"))
            for hypothesis in hypotheses:
                add_relation(
                    session_id,
                    safe_str(hypothesis.get("id")),
                    "defines",
                    "copilot_agent.session_family",
                    "1.0",
                    "copilot_agent",
                    marker,
                )
            for provenance in provenances:
                add_relation(
                    session_id,
                    safe_str(provenance.get("id")),
                    "defines",
                    "copilot_agent.session_family",
                    "1.0",
                    "copilot_agent",
                    marker,
                )
            for contract in contracts:
                add_relation(
                    session_id,
                    safe_str(contract.get("id")),
                    "session_closes_contract",
                    "copilot_agent.session_family",
                    "1.0",
                    "copilot_agent",
                    marker,
                )

            layer_target = layer_by_session.get(marker)
            if layer_target:
                target_id, relation_type = layer_target
                add_relation(
                    session_id,
                    target_id,
                    relation_type,
                    "copilot_agent.session_layer_map",
                    "1.0",
                    "copilot_agent",
                    marker,
                )

        for contract in contracts:
            layer_target = layer_by_session.get(marker)
            if not layer_target:
                continue
            target_id, _ = layer_target
            add_relation(
                safe_str(contract.get("id")),
                target_id,
                "defines",
                "copilot_agent.contract_layer_map",
                "1.0",
                "copilot_agent",
                marker,
            )

    governance_edges = [
        ("## 🗂🧱 Principios de Gestion", "## 🎯🧱 Detalles del tema", "governs"),
        ("## 🧭🧱 Protocolo de Sesión", "layer:copilot_agent", "governs"),
        ("## 🧭🧱 Protocolo de Sesión", "## 🌀🧱 Desarrollo y Evolución", "informs"),
        ("contratos/policy/canon_policy_bundle.json", "layer:canon", "governs"),
        ("contratos/projections/derived_layers_registry.json", "layer:microsoft_copilot", "defines"),
        ("contratos/projections/derived_layers_registry.json", "layer:copilot_agent", "defines"),
        ("python_scripts/derive_layers.py", "layer:microsoft_copilot", "generates"),
        ("python_scripts/derive_layers.py", "layer:copilot_agent", "generates"),
        ("README.md", "layer:canon", "informs"),
        ("go/canon/identity.go", "layer:canon", "defines"),
        ("go/canon/normalizer.go", "layer:canon", "hardens"),
    ]
    for source_title, target_ref, relation_type in governance_edges:
        source_id = selected_title_to_id.get(normalize_for_dedup(source_title))
        target_id = resolve_copilot_agent_target_id(target_ref, selected_by_id, selected_title_to_id)
        add_relation(
            source_id,
            target_id,
            relation_type,
            "copilot_agent.governance_map",
            "0.95",
            "copilot_agent",
            "governance anchors retained in compressed graph",
        )

    protocol_id = selected_title_to_id.get(normalize_for_dedup("## 🧭🧱 Protocolo de Sesión"))
    evolution_id = selected_title_to_id.get(normalize_for_dedup("## 🌀🧱 Desarrollo y Evolución"))
    for item in selected_entities:
        marker = extract_session_marker(item)
        entity_type = safe_str(item.get("entity_type"))
        source_id = safe_str(item.get("id"))
        if entity_type in {"session", "hypothesis", "provenance", "contract"} and evolution_id:
            add_relation(
                source_id,
                evolution_id,
                "part_of",
                "copilot_agent.session_context",
                "0.95",
                "copilot_agent",
                marker or "session family context",
            )
        if entity_type in {"session", "hypothesis", "provenance", "contract"} and protocol_id:
            add_relation(
                source_id,
                protocol_id,
                "uses",
                "copilot_agent.session_context",
                "0.9",
                "copilot_agent",
                marker or "session family context",
            )

    return sorted(
        relation_rows,
        key=lambda row: (
            safe_str(row.get("source_id")),
            safe_str(row.get("target_id")),
            safe_str(row.get("relation_type")),
        ),
    )


def assign_copilot_agent_anchors(selected_entities: list[dict]) -> list[dict]:
    family_prefix = {
        "integration_flow": "INT",
        "semantic_compression": "SEM",
        "copilot_projection": "COP",
        "minimal_canon": "CAN",
        "strict_reversibility": "REV",
    }
    counters = Counter()
    anchored = []
    for item in selected_entities:
        family = safe_str(item.get("semantic_family"))
        counters[family] += 1
        anchored_item = dict(item)
        anchored_item["txt_anchor"] = f"{family_prefix.get(family, 'DOC')}-{counters[family]:02d}"
        anchored.append(anchored_item)
    return anchored


def render_copilot_agent_corpus_lines(
    selected_entities: list[dict],
    relation_rows: list[dict],
    updated_at: str,
    *,
    summary_max_chars: int,
    signal_max_chars: int,
    max_signals: int,
    max_related: int,
    include_signals: bool,
    include_related: bool,
    include_why: bool,
) -> list[str]:
    relation_adjacency = defaultdict(list)
    title_by_id = {
        safe_str(item.get("id")): safe_str(item.get("title"))
        for item in selected_entities
    }
    for row in relation_rows:
        relation_adjacency[safe_str(row.get("source_id"))].append(
            {
                "target_title": title_by_id.get(safe_str(row.get("target_id")), safe_str(row.get("target_id"))),
                "relation_type": safe_str(row.get("relation_type")),
            }
        )

    by_family = defaultdict(list)
    for item in selected_entities:
        by_family[safe_str(item.get("semantic_family"))].append(item)

    type_counts = Counter(safe_str(item.get("entity_type")) for item in selected_entities)
    family_counts = Counter(safe_str(item.get("semantic_family")) for item in selected_entities)
    relation_types = Counter(safe_str(row.get("relation_type")) for row in relation_rows)

    lines = [
        "PROJECT_ID: tiddly-data-converter",
        f"PROFILE: {COPILOT_AGENT_FORMAT_VERSION}",
        f"GENERATED_FROM_SESSION: {COPILOT_AGENT_GENERATED_FROM_SESSION}",
        f"INTEGRATION_BASELINE: {COPILOT_AGENT_INTEGRATION_BASELINE_SESSION}",
        f"SEMANTIC_REFERENCE: {COPILOT_AGENT_SEMANTIC_REFERENCE_SESSION}",
        f"PARENT_LAYER_SESSION: {MICROSOFT_COPILOT_GENERATED_FROM_SESSION}",
        "AUTHORITY: derived_non_authoritative_agent_projection",
        f"UPDATED_AT: {updated_at}",
        "SOURCE_OF_TRUTH: data/out/local/tiddlers_*.jsonl",
        "OFFICIAL_PATH: data/out/local/microsoft_copilot/copilot_agent/",
        "NOISE_POLICY: compact summaries only; exact text stays in canon and microsoft_copilot/",
        "",
    ]

    for family in COPILOT_AGENT_FAMILY_ORDER:
        family_entities = by_family.get(family, [])
        lines.extend(
            [
                f"SECTION_ID: {family}",
                f"PURPOSE: {COPILOT_AGENT_FAMILY_PURPOSES[family]}",
                f"ENTITY_COUNT: {len(family_entities)}",
                "",
            ]
        )
        for item in family_entities:
            related = relation_adjacency.get(safe_str(item.get("id")), [])
            related_bits = []
            if include_related:
                for rel in related[:max_related]:
                    related_bits.append(f"{rel['relation_type']} -> {rel['target_title']}")
            summary = copilot_agent_display_summary(item, summary_max_chars)
            signals = []
            if include_signals:
                for signal in extract_copilot_agent_signals(item)[:max_signals]:
                    compact_signal = compact_agent_text(signal, signal_max_chars)
                    if compact_signal:
                        signals.append(compact_signal)
            lines.extend(
                [
                    f"DOC_ID: {item.get('txt_anchor')}",
                    f"ENTITY_ID: {item.get('id')}",
                    f"TITLE: {item.get('title')}",
                    f"TYPE: {item.get('entity_type')}",
                    f"SOURCE_REF: {copilot_agent_source_ref(item)}",
                    f"SUMMARY: {summary}",
                ]
            )
            if include_why:
                lines.append(f"WHY_IT_MATTERS: {item.get('selection_reason')}")
            if signals:
                lines.append(f"SIGNALS: {' | '.join(signals)}")
            if related_bits:
                lines.append(f"RELATED: {' | '.join(related_bits)}")
            lines.append("")

    lines.extend(
        [
            "SECTION_ID: compression_notes",
            "PURPOSE: Balance, density and fallback guidance for the compressed pack.",
            "",
            f"TOTAL_SELECTED_ENTITIES: {len(selected_entities)}",
            f"TOTAL_RELATIONS: {len(relation_rows)}",
            "FAMILY_COUNTS: " + ", ".join(f"{family}={family_counts[family]}" for family in COPILOT_AGENT_FAMILY_ORDER),
            "TYPE_COUNTS: " + ", ".join(f"{entity_type}={count}" for entity_type, count in type_counts.most_common()),
            "RELATION_TYPES: " + ", ".join(f"{rtype}={count}" for rtype, count in relation_types.most_common()),
            "REFERENCE_LINEAGE: S62 semantic pack -> S63 pipeline integration -> S64 semantic and reverse hardening.",
            "FOR_FULL_TEXT: consult data/out/local/tiddlers_*.jsonl and data/out/local/microsoft_copilot/.",
        ]
    )
    return lines


def build_copilot_agent_corpus(selected_entities: list[dict], relation_rows: list[dict], updated_at: str) -> str:
    render_profiles = [
        {
            "summary_max_chars": 220,
            "signal_max_chars": 150,
            "max_signals": 2,
            "max_related": 3,
            "include_signals": True,
            "include_related": True,
            "include_why": True,
        },
        {
            "summary_max_chars": 170,
            "signal_max_chars": 110,
            "max_signals": 1,
            "max_related": 2,
            "include_signals": True,
            "include_related": True,
            "include_why": False,
        },
        {
            "summary_max_chars": 130,
            "signal_max_chars": 90,
            "max_signals": 1,
            "max_related": 1,
            "include_signals": False,
            "include_related": True,
            "include_why": False,
        },
        {
            "summary_max_chars": 105,
            "signal_max_chars": 80,
            "max_signals": 0,
            "max_related": 0,
            "include_signals": False,
            "include_related": False,
            "include_why": False,
        },
    ]

    best_lines = None
    for profile in render_profiles:
        lines = render_copilot_agent_corpus_lines(selected_entities, relation_rows, updated_at, **profile)
        corpus_text = "\n".join(lines).rstrip() + "\n"
        best_lines = lines
        if len(corpus_text) <= COPILOT_AGENT_CORPUS_MAX_CHARS:
            return corpus_text

    fallback_text = "\n".join(best_lines or []).rstrip() + "\n"
    if len(fallback_text) > COPILOT_AGENT_CORPUS_MAX_CHARS:
        return fallback_text[:COPILOT_AGENT_CORPUS_MAX_CHARS].rsplit("\n", 2)[0].rstrip() + "\n"
    return fallback_text


def write_copilot_agent_artifacts(items: list[dict], copilot_agent_dir: Path, updated_at: str) -> list[Path]:
    """
    Generate the hardened three-file pack for copilot_agent/:
      - corpus.txt    : curated cognitive snapshot with DOC_ID anchors
      - entities.json : balanced semantic index
      - relations.csv : reconstructible graph subset
    """
    copilot_agent_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in copilot_agent_dir.iterdir():
        if stale_path.is_file() and stale_path.name not in {"corpus.txt", "entities.json", "relations.csv"}:
            stale_path.unlink()

    written = []
    selected_entities = assign_copilot_agent_anchors(select_copilot_agent_entities(items))
    relation_rows = build_copilot_agent_relations(selected_entities)

    entity_records = []
    for item in selected_entities:
        canon_ref = item.get("canon_ref") or {}
        entity_records.append(
            {
                "id": item.get("id"),
                "type": item.get("entity_type"),
                "source_type": item.get("type"),
                "semantic_family": item.get("semantic_family"),
                "title": item.get("title"),
                "summary": copilot_agent_display_summary(item, 220),
                "authority_level": item.get("authority_level"),
                "source_primary": item.get("source_primary"),
                "source_line": canon_ref.get("line"),
                "txt_anchor": item.get("txt_anchor"),
                "related_count": item.get("related_count"),
                "tier": item.get("tier"),
                "tags": (item.get("tags") or [])[:6],
                "taxonomy_path": (item.get("taxonomy_path") or [])[:4],
                "selection_reason": item.get("selection_reason"),
            }
        )

    entities_payload = {
        "layer_id": "microsoft_copilot/copilot_agent",
        "format_version": COPILOT_AGENT_FORMAT_VERSION,
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "authority_class": "derived_non_authoritative_agent_projection",
        "generated_from_session": COPILOT_AGENT_GENERATED_FROM_SESSION,
        "integration_baseline": COPILOT_AGENT_INTEGRATION_BASELINE_SESSION,
        "semantic_reference": COPILOT_AGENT_SEMANTIC_REFERENCE_SESSION,
        "parent_layer_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "entity_limit": COPILOT_AGENT_ENTITY_LIMIT,
        "balance_policy": {
            "family_targets": COPILOT_AGENT_FAMILY_TARGETS,
            "type_caps": COPILOT_AGENT_TYPE_CAPS,
            "synthetic_layers": 5,
            "family_order": COPILOT_AGENT_FAMILY_ORDER,
        },
        "entity_counts": {
            "by_type": dict(Counter(record["type"] for record in entity_records).most_common()),
            "by_family": dict(Counter(record["semantic_family"] for record in entity_records).most_common()),
        },
        "entities": entity_records,
    }
    written.append(write_json_file(copilot_agent_dir / "entities.json", entities_payload))

    written.append(
        write_csv_file(
            copilot_agent_dir / "relations.csv",
            ["source_id", "target_id", "relation_type", "provenance", "confidence", "source_layer", "notes"],
            relation_rows,
        )
    )

    corpus_text = build_copilot_agent_corpus(selected_entities, relation_rows, updated_at)
    written.append(write_text_file(copilot_agent_dir / "corpus.txt", corpus_text.splitlines()))
    return written


def cleanup_s61_copilot_output(copilot_dir: Path) -> None:
    copilot_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("tiddlers_microsoft_copilot_*.jsonl", "overview.md"):
        for path in copilot_dir.glob(pattern):
            path.unlink()


def write_microsoft_copilot_s61_artifacts(
    classified: list,
    enriched_records: list,
    enriched_shards_info: list,
    ai_records: list,
    ai_shards_info: list,
    chunk_shards_info: list,
    shard_paths: list,
    enriched_dir: Path,
    ai_dir: Path,
    reports_dir: Path,
    audit_dir: Path,
    export_dir: Path,
    copilot_dir: Path,
    tiddler_shard_size: int,
) -> dict:
    cleanup_s61_copilot_output(copilot_dir)
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source_inventory = collect_microsoft_copilot_source_inventory(
        shard_paths,
        enriched_dir,
        enriched_shards_info,
        ai_dir,
        ai_shards_info,
        chunk_shards_info,
        reports_dir,
        audit_dir,
        export_dir,
    )
    source_inventory["governance_inputs"] = source_inventory.get("governance_inputs", []) + [
        ".github/instructions/contratos.instructions.md",
        ".github/instructions/sesiones.instructions.md",
        ".github/instructions/tiddlers_sesiones.instructions.md",
        "contratos/m03-s61-microsoft-copilot-json-csv-txt-projection-mvp-v0.md.json",
    ]
    source_inventory["external_reference"] = MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF

    items = build_s61_projection_items(
        classified,
        enriched_records,
        ai_records,
        enriched_dir,
        ai_dir,
        tiddler_shard_size,
    )
    bundles = select_bundle_members(items)
    public_entities = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in items
    ]
    topics_payload = build_topics_payload(items, updated_at)
    navigation_index = build_navigation_index_s61(items, source_inventory, bundles, updated_at)

    paths = []
    paths.append(write_json_file(copilot_dir / "entities.json", {
        "layer_id": "microsoft_copilot",
        "format_version": MICROSOFT_COPILOT_FORMAT_VERSION,
        "source_of_truth": "data/out/local/tiddlers_*.jsonl",
        "authority_class": get_layer_registry_entry("microsoft_copilot").get("authority"),
        "projection_purpose": "structured entity index for agent navigation",
        "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
        "updated_at": updated_at,
        "entities": public_entities,
    }))
    paths.append(write_json_file(copilot_dir / "topics.json", topics_payload))
    paths.append(write_json_file(copilot_dir / "navigation_index.json", navigation_index))

    nodes_rows = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "type": item.get("type"),
            "authority_level": item.get("authority_level"),
            "bundle_path": item.get("bundle_path"),
            "source_primary": item.get("source_primary"),
            "tags": item.get("tags") or [],
        }
        for item in items
    ]
    paths.append(write_csv_file(
        copilot_dir / "nodes.csv",
        ["id", "title", "type", "authority_level", "bundle_path", "source_primary", "tags"],
        nodes_rows,
    ))
    paths.append(write_csv_file(
        copilot_dir / "edges.csv",
        ["source_id", "target_id", "relation_type", "provenance", "confidence", "source_file"],
        build_edges_rows(items),
    ))
    coverage_rows = build_coverage_rows(source_inventory)
    paths.append(write_csv_file(
        copilot_dir / "coverage.csv",
        ["source_layer", "artifact_target", "coverage_status", "notes"],
        coverage_rows,
    ))

    paths.extend(write_bundle_files(copilot_dir, bundles, updated_at))
    paths.extend(write_overview_and_reading_guide(copilot_dir, navigation_index, source_inventory, updated_at))
    paths.extend(write_s61_spec_artifacts(copilot_dir, updated_at))

    artifact_rows = [
        {
            "artifact_id": path.relative_to(copilot_dir).as_posix().replace("/", ":"),
            "artifact_type": path.suffix.lstrip(".") or "directory",
            "generated_from": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "path": as_display_path(path),
            "status": "generated",
        }
        for path in sorted(paths, key=lambda p: p.as_posix())
    ]
    artifact_rows.append(
        {
            "artifact_id": "manifest.json",
            "artifact_type": "json",
            "generated_from": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "path": as_display_path(copilot_dir / "manifest.json"),
            "status": "generated",
        }
    )
    artifact_rows.append(
        {
            "artifact_id": "source_arbitration_report.json",
            "artifact_type": "json",
            "generated_from": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "path": as_display_path(copilot_dir / "source_arbitration_report.json"),
            "status": "generated",
        }
    )
    artifact_rows.append(
        {
            "artifact_id": "artifacts.csv",
            "artifact_type": "csv",
            "generated_from": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "path": as_display_path(copilot_dir / "artifacts.csv"),
            "status": "generated",
        }
    )

    artifact_descriptions = [
        {
            "artifact": row["path"],
            "artifact_type": row["artifact_type"],
            "source_inputs": {
                "json": ["canon", "enriched", "ai", "manifests"],
                "csv": ["canon", "ai", "registry"],
                "txt": ["canon", "contracts", "README", "registry"],
            }.get(row["artifact_type"], ["self_outputs"]),
            "selection_reason": "selected by S61 JSON/CSV/TXT MVP according to artifact family",
            "transformation_notes": "non-authoritative derived projection; source refs preserve reversibility",
        }
        for row in artifact_rows
    ]
    source_report = build_source_arbitration_report_s61(
        copilot_dir,
        source_inventory,
        artifact_descriptions,
        updated_at,
    )
    paths.append(write_json_file(copilot_dir / "source_arbitration_report.json", source_report))
    paths.append(write_csv_file(
        copilot_dir / "artifacts.csv",
        ["artifact_id", "artifact_type", "generated_from", "path", "status"],
        artifact_rows,
    ))

    manifest_path = write_manifest(
        copilot_dir,
        "microsoft_copilot_json_csv_txt_projection_mvp",
        [],
        len(items),
        len(shard_paths),
        shard_paths,
        extra={
            "session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
            "pipeline_session": SESSION,
            "projection": {
                "format_version": MICROSOFT_COPILOT_FORMAT_VERSION,
                "source_of_truth": "data/out/local/tiddlers_*.jsonl",
                "authority_class": get_layer_registry_entry("microsoft_copilot").get("authority"),
                "lineage_parents": get_layer_registry_entry("microsoft_copilot").get("lineage_parents"),
                "projection_purpose": "JSON/CSV/TXT agent-readable surface derived from canon with contextual source arbitration",
                "generated_from_session": MICROSOFT_COPILOT_GENERATED_FROM_SESSION,
                "generated_via_pipeline_session": SESSION,
                "multisource_arbitration": True,
                "jsonl_final_primary": False,
                "authority_note": "derived and non-authoritative; does not replace canon, enriched or ai",
            },
            "artifacts": artifact_rows,
            "corpus_snapshot": navigation_index.get("corpus_snapshot"),
            "source_inventory": source_inventory,
            "external_format_reference": MICROSOFT_COPILOT_MICROSOFT_SUPPORT_REF,
        },
        layer_id="microsoft_copilot",
    )

    return {
        "records": public_entities,
        "manifest_path": manifest_path,
        "navigation_path": copilot_dir / "navigation_index.json",
        "source_report_path": copilot_dir / "source_arbitration_report.json",
        "overview_path": copilot_dir / "overview.txt",
        "artifact_count": len(artifact_rows),
        "copilot_agent_paths": write_copilot_agent_artifacts(
            items,
            copilot_dir / "copilot_agent",
            updated_at,
        ),
    }


# ── QC Reports ────────────────────────────────────────────────────────────────

def load_existing_chunk_relation_baseline(ai_dir: Path) -> dict:
    """Read current chunks_ai shards before regeneration for before/after QC."""
    chunks_total = 0
    chunks_with_relation_targets = 0
    relation_targets_total = 0
    shard_files = sorted(ai_dir.glob("chunks_ai_*.jsonl")) if ai_dir.exists() else []
    for shard in shard_files:
        with open(shard, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rels = rec.get("relation_targets") if isinstance(rec.get("relation_targets"), list) else []
                chunks_total += 1
                relation_targets_total += len(rels)
                if rels:
                    chunks_with_relation_targets += 1
    return {
        "source": "existing_chunks_ai_before_regeneration",
        "chunks_total_before": chunks_total,
        "chunks_with_relation_targets_before": chunks_with_relation_targets,
        "chunks_without_relation_targets_before": chunks_total - chunks_with_relation_targets,
        "relation_targets_total_before": relation_targets_total,
        "shard_count_before": len(shard_files),
        "shard_files_before": [p.name for p in shard_files],
    }


def build_relation_propagation_summary(
    all_chunks: list,
    all_invalid_rels: list,
    relation_events: list,
    propagation_context: dict,
    baseline: dict | None,
) -> dict:
    chunks_total = len(all_chunks)
    chunks_with_relation_targets_after = sum(
        1 for chunk in all_chunks
        if isinstance(chunk.get("relation_targets"), list) and bool(chunk.get("relation_targets"))
    )
    relation_targets_total_after = sum(
        len(chunk.get("relation_targets") or [])
        for chunk in all_chunks
        if isinstance(chunk.get("relation_targets"), list)
    )
    relation_types_chunks = Counter()
    target_counts = Counter()
    for chunk in all_chunks:
        for rel in chunk.get("relation_targets") or []:
            relation_types_chunks[safe_str(rel.get("type") or "unknown")] += 1
            target_id = safe_str(rel.get("target_id")).strip()
            if target_id:
                target_counts[target_id] += 1

    before_with = (baseline or {}).get("chunks_with_relation_targets_before", 0)
    before_total = (baseline or {}).get("chunks_total_before", 0)
    before_pct = _pct_local(before_with, before_total)
    after_pct = _pct_local(chunks_with_relation_targets_after, chunks_total)
    stale_blocked = len(all_invalid_rels)
    invalid_reason_dist = Counter(rel.get("reason", "unknown") for rel in all_invalid_rels)
    invalid_source_dist = Counter(rel.get("relation_source", "unknown") for rel in all_invalid_rels)
    hub_filtered = sum(ev.get("hub_targets_filtered", 0) for ev in relation_events)
    generic_filtered_or_flagged = sum(
        ev.get("generic_relation_types_filtered_or_flagged", 0)
        for ev in relation_events
    )
    capped = sum(ev.get("relation_targets_capped", 0) for ev in relation_events)
    duplicates = sum(ev.get("duplicate_relation_targets_collapsed", 0) for ev in relation_events)
    precision_risk_level = "low"
    if stale_blocked or propagation_context.get("hub_target_ids"):
        precision_risk_level = "medium_controlled"
    if any(
        len(chunk.get("relation_targets") or []) > MAX_RELATION_TARGETS_PER_CHUNK
        for chunk in all_chunks
    ):
        precision_risk_level = "high"

    return {
        "chunks_total": chunks_total,
        "chunks_with_relation_targets_before": before_with,
        "chunks_with_relation_targets_after": chunks_with_relation_targets_after,
        "chunks_without_relation_targets_after": chunks_total - chunks_with_relation_targets_after,
        "relation_targets_total_after": relation_targets_total_after,
        "resolved_relation_targets_propagated": relation_targets_total_after,
        "source_level_relation_targets_after_filter": sum(
            ev.get("relation_targets_after", 0) for ev in relation_events
        ),
        "stale_relation_targets_blocked": stale_blocked,
        "stale_relation_target_reason_distribution": dict(invalid_reason_dist.most_common()),
        "stale_relation_target_source_distribution": dict(invalid_source_dist.most_common()),
        "hub_targets_detected": len(propagation_context.get("hub_target_ids", set())),
        "hub_targets_filtered_or_capped": hub_filtered,
        "generic_relation_types_detected": propagation_context.get("generic_relation_type_distribution", {}),
        "generic_relation_types_filtered_or_flagged": generic_filtered_or_flagged,
        "duplicate_relation_targets_collapsed": duplicates,
        "relation_targets_capped_by_limit": capped,
        "max_relation_targets_per_chunk": MAX_RELATION_TARGETS_PER_CHUNK,
        "chunk_max_relation_targets_observed": max(
            (len(chunk.get("relation_targets") or []) for chunk in all_chunks),
            default=0,
        ),
        "chunks_over_relation_target_limit": sum(
            1 for chunk in all_chunks
            if len(chunk.get("relation_targets") or []) > MAX_RELATION_TARGETS_PER_CHUNK
        ),
        "propagation_policy_version": RELATION_PROPAGATION_POLICY_VERSION,
        "coverage_delta": {
            "chunks_with_relation_targets_delta": chunks_with_relation_targets_after - before_with,
            "coverage_pct_before": before_pct,
            "coverage_pct_after": after_pct,
            "coverage_pct_delta": round(after_pct - before_pct, 2),
        },
        "precision_risk_level": precision_risk_level,
        "relation_types_en_chunks_after": dict(relation_types_chunks.most_common()),
        "hub_target_samples": propagation_context.get("hub_targets", [])[:12],
        "top_chunk_relation_targets_after": [
            {"target_id": target_id, "count": count}
            for target_id, count in target_counts.most_common(12)
        ],
        "baseline": baseline or {},
    }


def _pct_local(part: int, total: int) -> float:
    return round((part / total) * 100, 2) if total else 0.0


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="derive_layers.py — S55 governed derivation entrypoint for tiddly-data-converter"
    )
    parser.add_argument(
        "--input-dir", default=None,
        help="Directory containing canon shards tiddlers_*.jsonl (default: data/out/local)"
    )
    parser.add_argument(
        "--enriched-dir", default=None,
        help="Output directory for enriched layer (default: data/out/local/enriched)"
    )
    parser.add_argument(
        "--ai-dir", default=None,
        help="Output directory for AI-friendly layer (default: data/out/local/ai)"
    )
    parser.add_argument(
        "--reports-dir", default=None,
        help="Output directory for QC reports (default: <ai-dir>/reports)"
    )
    parser.add_argument(
        "--audit-dir", default=None,
        help="Optional audit layer directory consulted for last known validation context (default: data/out/local/audit)"
    )
    parser.add_argument(
        "--export-dir", default=None,
        help="Optional export layer directory consulted for current export visibility (default: data/out/local/export)"
    )
    parser.add_argument(
        "--microsoft-copilot-dir", default=None,
        help="Output directory for microsoft_copilot derived projection (default: data/out/local/microsoft_copilot)"
    )
    parser.add_argument(
        "--chunk-target-tokens", type=int, default=DEFAULT_CHUNK_TARGET_TOKENS,
        help=f"Target tokens per chunk (default: {DEFAULT_CHUNK_TARGET_TOKENS})"
    )
    parser.add_argument(
        "--chunk-max-tokens", type=int, default=DEFAULT_CHUNK_MAX_TOKENS,
        help=f"Hard max tokens per chunk — no chunk may exceed this (default: {DEFAULT_CHUNK_MAX_TOKENS})"
    )
    parser.add_argument(
        "--tiddler-shard-size", type=int, default=DEFAULT_TIDDLER_SHARD_SIZE,
        help=f"Records per tiddler shard (default: {DEFAULT_TIDDLER_SHARD_SIZE})"
    )
    parser.add_argument(
        "--chunk-shard-size", type=int, default=DEFAULT_CHUNK_SHARD_SIZE_ARG,
        help=f"Chunks per chunk shard (default: {DEFAULT_CHUNK_SHARD_SIZE_ARG})"
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing outputs (default: overwrite always; flag kept for explicitness)"
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit with error if any chunk exceeds hard max"
    )
    parser.add_argument(
        "--fail-on-chunk-violation", action="store_true",
        help="Exit with error code 2 if any chunk exceeds hard max"
    )
    return parser.parse_args()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    input_dir = resolve_repo_path(args.input_dir, DEFAULT_CANON_DIR)
    enriched_dir = resolve_repo_path(args.enriched_dir, DEFAULT_ENRICHED_DIR)
    ai_dir = resolve_repo_path(args.ai_dir, DEFAULT_AI_DIR)
    reports_dir = resolve_repo_path(args.reports_dir, DEFAULT_AI_REPORTS_DIR)
    audit_dir = resolve_repo_path(args.audit_dir, DEFAULT_AUDIT_DIR)
    export_dir = resolve_repo_path(args.export_dir, DEFAULT_EXPORT_DIR)
    microsoft_copilot_dir = resolve_repo_path(args.microsoft_copilot_dir, DEFAULT_MICROSOFT_COPILOT_DIR)

    target_tokens = args.chunk_target_tokens
    max_tokens = args.chunk_max_tokens
    tiddler_shard_size = args.tiddler_shard_size
    chunk_shard_size = args.chunk_shard_size

    print(f"[{SESSION}] derive_layers.py — hardened derivation pipeline with governed corpus_state")
    print(f"  input_dir:       {input_dir}")
    print(f"  enriched_dir:    {enriched_dir}")
    print(f"  ai_dir:          {ai_dir}")
    print(f"  reports_dir:     {reports_dir}")
    print(f"  audit_dir:       {audit_dir}")
    print(f"  export_dir:      {export_dir}")
    print(f"  copilot_dir:     {microsoft_copilot_dir}")
    print(f"  chunk_target:    {target_tokens} tokens")
    print(f"  chunk_hard_max:  {max_tokens} tokens")

    # ── Load canon ──
    print(f"\n[{SESSION}] Discovering and loading canon shards from {input_dir}...")
    canon, shard_paths = load_canon(input_dir)
    print(f"  Found {len(shard_paths)} shards: {[p.name for p in shard_paths]}")
    print(f"  Loaded {len(canon)} records total.")

    if not canon:
        print("ERROR: No canon records found.", file=sys.stderr)
        sys.exit(1)

    # ── Build known IDs set for relation validation ──
    relation_index = build_relation_resolution_index(canon)
    known_ids = relation_index["ids"]
    print(f"  Known node IDs: {len(known_ids)}")

    # ── Phase 1: Classify roles and derive taxonomy ──
    print(f"\n[{SESSION}] Phase 1: Classifying roles and deriving taxonomy...")
    classified = []
    for rec, shard_file, line_num in canon:
        role = classify_role(rec)
        rec["_derived_role"] = role  # temp field for taxonomy derivation
        taxonomy, section = derive_taxonomy_and_section(rec)
        del rec["_derived_role"]
        classified.append((rec, shard_file, line_num, role, taxonomy, section))

    role_counts = Counter(role for _, _, _, role, _, _ in classified)
    print(f"  Classification summary: {dict(role_counts.most_common())}")

    relation_propagation_context = build_relation_propagation_context(classified, relation_index)
    print(
        "  Relation propagation policy: "
        f"{relation_propagation_context['policy_version']} "
        f"(max {relation_propagation_context['max_relation_targets_per_chunk']} targets/chunk, "
        f"hubs detected: {len(relation_propagation_context['hub_target_ids'])})"
    )

    # ── Phase 2: Build enriched layer (Capa A) ──
    print(f"\n[{SESSION}] Phase 2: Building Capa A — Enriched Canonical Export...")
    enriched_records = []
    for rec, shard_file, line_num, role, taxonomy, section in classified:
        enriched_records.append(
            build_enriched_record(rec, shard_file, line_num, role, taxonomy, section)
        )

    enriched_shards_info = write_sharded(
        enriched_records, enriched_dir, "tiddlers_enriched", tiddler_shard_size
    )
    write_manifest(
        enriched_dir, "enriched_canonical_export",
        enriched_shards_info, len(enriched_records),
        len(shard_paths), shard_paths,
        layer_id="enriched",
    )
    print(f"  Wrote {len(enriched_records)} enriched records → {len(enriched_shards_info)} shards in {enriched_dir}")

    # ── Phase 3: Build AI layer (Capa B) ──
    print(f"\n[{SESSION}] Phase 3: Building Capa B — AI-friendly Projection v2...")
    chunk_relation_baseline = load_existing_chunk_relation_baseline(ai_dir)
    print(
        "  Chunk relation baseline: "
        f"{chunk_relation_baseline['chunks_with_relation_targets_before']}/"
        f"{chunk_relation_baseline['chunks_total_before']} chunks with relation_targets"
    )
    ai_records = []
    all_chunks = []
    all_invalid_rels = []
    all_relation_propagation_events = []
    chunk_qc_events = []

    for rec, shard_file, line_num, role, taxonomy, section in classified:
        ai_rec, chunks, invalid_rels, payload_info, relation_event = build_ai_record(
            rec, shard_file, line_num, role, taxonomy, section,
            known_ids, relation_index, target_tokens, max_tokens,
            relation_propagation_context,
        )
        ai_records.append(ai_rec)
        all_chunks.extend(chunks)
        all_invalid_rels.extend(invalid_rels)
        all_relation_propagation_events.append(relation_event)
        chunk_qc_events.append({
            "node_id": rec.get("id"),
            "chunk_strategy": payload_info["chunk_strategy"],
            "exclusion_reason": payload_info.get("chunk_exclusion_reason"),
        })

    ai_shards_info = write_sharded(
        ai_records, ai_dir, "tiddlers_ai", tiddler_shard_size
    )
    chunk_shards_info = []
    if all_chunks:
        chunk_shards_info = write_sharded(
            all_chunks, ai_dir, "chunks_ai", chunk_shard_size
        )

    write_manifest(
        ai_dir, "ai_friendly_projection_v2",
        ai_shards_info, len(ai_records),
        len(shard_paths), shard_paths,
        extra={
            "chunks": {
                "total_chunks": len(all_chunks),
                "shard_count": len(chunk_shards_info),
                "shards": chunk_shards_info,
                "chunk_target_tokens": target_tokens,
                "chunk_hard_max_tokens": max_tokens,
            }
        },
        layer_id="ai",
    )
    print(f"  Wrote {len(ai_records)} AI records → {len(ai_shards_info)} shards")
    print(f"  Wrote {len(all_chunks)} chunks → {len(chunk_shards_info)} chunk shards")
    print(f"  Invalid relations discarded: {len(all_invalid_rels)}")
    relation_propagation_summary = build_relation_propagation_summary(
        all_chunks,
        all_invalid_rels,
        all_relation_propagation_events,
        relation_propagation_context,
        chunk_relation_baseline,
    )

    # ── Phase 4: QC Reports ──
    print(f"\n[{SESSION}] Phase 4: Writing QC reports to {reports_dir}...")
    reports_dir.mkdir(parents=True, exist_ok=True)

    p1 = write_classification_report(reports_dir, ai_records, enriched_records)
    p2 = write_chunk_qc_report(reports_dir, ai_records, all_chunks, chunk_qc_events,
                                 target_tokens, max_tokens, relation_propagation_summary)
    p3 = write_retrieval_qc_report(reports_dir, ai_records)
    p4 = write_relations_qc_report(reports_dir, ai_records, all_invalid_rels,
                                    all_chunks, relation_propagation_summary)
    p5 = write_derivation_report(reports_dir, canon, enriched_records, ai_records,
                                   all_chunks, shard_paths, target_tokens, max_tokens)

    print(f"  {p1}")
    print(f"  {p2}")
    print(f"  {p3}")
    print(f"  {p4}")
    print(f"  {p5}")

    # ── Phase 5: Microsoft Copilot derived projection ──
    print(f"\n[{SESSION}] Phase 5: Building microsoft_copilot derived projection...")
    copilot_artifacts = write_microsoft_copilot_s61_artifacts(
        classified,
        enriched_records,
        enriched_shards_info,
        ai_records,
        ai_shards_info,
        chunk_shards_info,
        shard_paths,
        enriched_dir,
        ai_dir,
        reports_dir,
        audit_dir,
        export_dir,
        microsoft_copilot_dir,
        tiddler_shard_size,
    )
    print(
        f"  Wrote {len(copilot_artifacts['records'])} microsoft_copilot entities"
        f" → {copilot_artifacts['artifact_count']} JSON/CSV/TXT artifacts"
    )
    print(f"  {copilot_artifacts['manifest_path']}")
    print(f"  {copilot_artifacts['navigation_path']}")
    print(f"  {copilot_artifacts['source_report_path']}")
    print(f"  {copilot_artifacts['overview_path']}")

    # ── Summary ──
    over_max = sum(1 for c in all_chunks if not c.get("within_hard_max"))
    print(f"\n[{SESSION}] ── Final Summary ──")
    print(f"  Canon shards discovered:  {len(shard_paths)}")
    print(f"  Canon records loaded:     {len(canon)}")
    print(f"  Enriched records:         {len(enriched_records)}")
    print(f"  AI records:               {len(ai_records)}")
    print(f"  Chunks generated:         {len(all_chunks)}")
    print(f"  Copilot entities:         {len(copilot_artifacts['records'])}")
    print(f"  Chunks above hard max:    {over_max}  ({'⚠ VIOLATION' if over_max else 'OK'})")
    print(f"  Relations discarded:      {len(all_invalid_rels)}")
    print(f"  IDs consistent:           {len(canon) == len(enriched_records) == len(ai_records)}")
    print(f"\n  Top roles: {dict(role_counts.most_common(8))}")

    if over_max and (args.strict or args.fail_on_chunk_violation):
        print(f"\nERROR: {over_max} chunks exceed hard max ({max_tokens} tokens). Exiting with code 2.",
              file=sys.stderr)
        sys.exit(2)

    print(f"\n[{SESSION}] Derivation complete.")


if __name__ == "__main__":
    main()
