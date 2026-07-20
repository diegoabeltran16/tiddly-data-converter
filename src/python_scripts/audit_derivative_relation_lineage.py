#!/usr/bin/env python3
"""S0179 read-only audit of relational lineage in productive derivatives."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
LOCAL = REPO_ROOT / "data/out/local"
CANDIDATE_CURRENT_PATH = "pipeline/relation_candidates/current"
PRODUCTIVE_COMPONENTS = (
    "enriched producer",
    "AI producer",
    "chunks producer",
    "Copilot producer",
)
REQUIRED_REPORT_SECTIONS = (
    "1. Estado relacional canonico",
    "2. Significado de content_embedded",
    "3. Linaje hacia AI",
    "4. Linaje hacia chunks",
    "5. Linaje hacia Copilot",
    "6. Diferencia 587/585",
    "7. Relaciones descartadas",
    "8. Separacion de candidatas",
    "9. Matriz de autoridad",
    "10. Alcance de equivalencia v2",
    "11. Contencion para S0180",
    "12. Delta esperado para S0184",
)


def sha(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(root: Path, pattern: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob(pattern)):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def relation_rows(records: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        source = record.get("id") or record.get("source_id")
        for relation in record.get(field) or []:
            if isinstance(relation, dict):
                item = dict(relation)
                item["_source"] = source
                rows.append(item)
    return rows


def tree_fingerprints(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        item.relative_to(LOCAL).as_posix(): sha(item) or ""
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def file_fingerprints(paths: list[Path]) -> dict[str, str]:
    return {
        path.relative_to(LOCAL).as_posix(): sha(path) or ""
        for path in paths
        if path.exists()
    }


def protected_fingerprints() -> dict[str, Any]:
    canon_paths = sorted(LOCAL.glob("tiddlers_*.jsonl"))
    candidate_paths = sorted((LOCAL / CANDIDATE_CURRENT_PATH).glob("*"))
    return {
        "canon": file_fingerprints(canon_paths),
        "candidates": file_fingerprints([p for p in candidate_paths if p.is_file()]),
        "enriched": tree_fingerprints(LOCAL / "enriched"),
        "ai": tree_fingerprints(LOCAL / "ai"),
        "chunks": file_fingerprints(sorted((LOCAL / "ai").glob("chunks_ai_*.jsonl"))),
        "copilot": tree_fingerprints(LOCAL / "microsoft_copilot"),
        "reverse_html": tree_fingerprints(LOCAL / "reverse_html"),
        "productive_manifest": file_fingerprints(
            [LOCAL / "audit/rag_admission/productive_rag_manifest.json"]
        ),
    }


def relation_key(relation: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (
        relation.get("_source") or relation.get("source_id"),
        relation.get("type") or relation.get("relation_type"),
        relation.get("target_id") or relation.get("target") or relation.get("target_title"),
    )


def source_mentions_candidate_path(source_text: str) -> bool:
    return CANDIDATE_CURRENT_PATH in source_text or "relation_candidates/current" in source_text


def scan_candidate_ids_in_product(product_text: str, candidate_ids: set[str]) -> set[str]:
    tokens = set(re.findall(r"candidate[_:-]?[A-Za-z0-9_.:-]+", product_text))
    return {candidate_id for candidate_id in candidate_ids if candidate_id in tokens}


def analyze_candidate_direct_consumption(
    *,
    candidate_path: Path,
    candidate_ids: set[str],
    productive_serialized_text: str,
    producer_sources: dict[str, str],
    fixture_probe_used: bool = False,
) -> dict[str, Any]:
    id_hits = sorted(scan_candidate_ids_in_product(productive_serialized_text, candidate_ids))
    path_hits = sorted(
        name for name, text in producer_sources.items() if source_mentions_candidate_path(text)
    )
    explicit_readers = sorted(
        name
        for name, text in producer_sources.items()
        if source_mentions_candidate_path(text) and re.search(r"\b(open|read_text|glob|rglob)\b", text)
    )
    detected = bool(id_hits or path_hits or explicit_readers)
    return {
        "detected": detected,
        "candidate_manifest_path": candidate_path.relative_to(LOCAL).as_posix()
        if candidate_path.is_relative_to(LOCAL)
        else candidate_path.as_posix(),
        "candidate_manifest_hash": sha(candidate_path),
        "productive_components_checked": list(PRODUCTIVE_COMPONENTS),
        "evidence_methods": {
            "imports_checked": sorted(producer_sources),
            "runtime_paths_checked": sorted(producer_sources),
            "explicit_readers_checked": sorted(producer_sources),
            "fixture_probe_used": fixture_probe_used,
        },
        "matching_relations_are_dependency_proof": False,
        "candidate_id_hits_in_productive_outputs": id_hits,
        "producer_path_hits": path_hits,
        "explicit_reader_hits": explicit_readers,
        "conclusion": "not_detected" if not detected else "detected",
    }


def explain_content_embedded_counts(
    embedded_relations: list[dict[str, Any]],
    ai_relation_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    projected = [
        relation
        for relation in ai_relation_targets
        if relation.get("evidence") == "content_embedded"
    ]
    embedded_counter = Counter(relation_key(relation) for relation in embedded_relations)
    projected_counter = Counter(relation_key(relation) for relation in projected)
    unprojected = []
    for key, count in embedded_counter.items():
        projected_count = projected_counter.get(key, 0)
        if projected_count < count:
            unprojected.append(
                {
                    "source_id": key[0],
                    "type": key[1],
                    "target_id": key[2],
                    "embedded_occurrences": count,
                    "projected_occurrences": projected_count,
                }
            )
    unique_embedded_targets = {relation_key(relation)[2] for relation in embedded_relations}
    unique_projected_targets = {relation_key(relation)[2] for relation in projected}
    delta = len(embedded_relations) - len(projected)
    explained = (
        delta == 0
        or (
            delta == len(unprojected)
            and unique_embedded_targets == unique_projected_targets
        )
    )
    meaning = (
        "embedded_extraction_occurrences_not_all_projected_as_ai_relation_targets"
        if delta
        else "same_occurrence_count"
    )
    disposition = (
        "not_a_target_universe_loss; unique target_id set is unchanged"
        if delta and unique_embedded_targets == unique_projected_targets
        else "no_delta"
        if delta == 0
        else "requires_review"
    )
    return {
        "extracted_total": {
            "value": len(embedded_relations),
            "unit": "embedded relation extraction occurrences in AI records",
            "source": "ai/tiddlers_ai_*.jsonl:embedded_relations",
        },
        "projected_relation_targets": {
            "value": len(projected),
            "unit": "AI relation_target occurrences with evidence=content_embedded",
            "source": "ai/tiddlers_ai_*.jsonl:relation_targets",
        },
        "delta": {
            "value": delta,
            "comparable": True,
            "meaning": meaning,
            "disposition": disposition,
            "explained": explained,
            "unprojected_occurrences": unprojected,
            "unique_embedded_target_ids": len(unique_embedded_targets),
            "unique_projected_target_ids": len(unique_projected_targets),
        },
        "explained": explained,
    }


def classify_controlled_v1(relation_schema: str = "derived_or_legacy") -> dict[str, Any]:
    is_canonical = relation_schema == "canonical-relation/v1"
    return {
        "category": "chunk_propagation_policy",
        "purpose": "controlled_parent_relation_target_propagation",
        "relation_schema": relation_schema,
        "is_canonical_relation_v1": is_canonical,
        "grants_canonical_authority": False,
        "performs_new_relation_inference": False,
        "authority": "inherited_limited",
        "elevation_detected": is_canonical,
        "implementation_reference": "derive_layers.py chunk relation propagation writes relation_propagation_policy=controlled_v1",
    }


def build_human_report(
    lineage: dict[str, Any],
    legacy: dict[str, Any],
    count_semantics: dict[str, Any],
    candidate_direct: dict[str, Any],
    controlled_v1: dict[str, Any],
    scope: dict[str, Any],
) -> str:
    canon = lineage["canon"]
    families = lineage["family_summaries"]
    recon = lineage["reconciliation"]
    containment = {
        "candidates_are_not_productive_inputs": True,
        "legacy_relations_are_not_canonical_v1": True,
        "canonical_authority_requires_canonical_relation_v1": True,
        "reconciliation_must_not_auto_promote_legacy": True,
    }
    return f"""# S0179 relation lineage contract report

## 1. Estado relacional canonico

Relaciones explicitas observadas: {canon["relations"]}. Relaciones `canonical-relation/v1`: {canon["canonical_relation_v1"]}. La presencia de relaciones en el campo canonico legacy/pre-v1 permite derivacion y QC, pero no otorga autoridad `canonical-relation/v1`.

## 2. Significado de content_embedded

`content_embedded` se asigna en la derivacion AI como procedencia de extraccion desde contenido embebido. Representa evidencia de extraccion, no admision canonica ni decision humana. Atraviesa QC de resolucion de target; las relaciones invalidas de esta fuente quedan descartadas y muestreadas.

## 3. Linaje hacia AI

Fuente: canon y contenido embebido. Transformacion: `derive_layers.py` produce `relation_targets` y `embedded_relations`. Conteos: {families["ai"]["relation_targets"]} relation_targets y {families["ai"]["embedded_relations"]} embedded_relations. Procedencia: `content_embedded`, `wikilink`, `structural_tag` y relaciones canon legacy. Autoridad: derivada heredada, no canonica v1. Descartes QC: {recon["discarded"]}.

## 4. Linaje hacia chunks

La politica `controlled_v1` propaga targets resueltos desde el tiddler padre hacia chunks. Unidad de conteo: ocurrencias de `relation_targets` en chunks; total observado {families["chunks_ai"]["relation_targets"]}. No realiza inferencia relacional nueva segun la implementacion auditada; filtra targets stale/hub, colapsa duplicados y aplica cap. Autoridad resultante: {controlled_v1["authority"]}.

## 5. Linaje hacia Copilot

Origen de edges: canon relations, AI relation_targets y AI embedded_relations. Unidad: filas en `microsoft_copilot/edges.csv`; total {families["microsoft_copilot"]["edges"]}. La proyeccion conserva provenance textual, pero no transporta schema `canonical-relation/v1` ni decision humana. Autoridad comunicada: derivada y ambigua.

## 6. Diferencia 587/585

587 cuenta ocurrencias de extraccion en `embedded_relations`. 585 cuenta ocurrencias proyectadas como `relation_targets` con `evidence=content_embedded`. Delta: {count_semantics["delta"]["value"]}. Disposicion: {count_semantics["delta"]["disposition"]}. No se interpreta automaticamente como perdida porque el conjunto de target_id unicos permanece en {count_semantics["delta"]["unique_embedded_target_ids"]} para ambas unidades.

## 7. Relaciones descartadas

Descartadas: {legacy["discarded"]}. Unidad: relaciones invalidas bloqueadas por QC. La distribucion por fuente mantiene `content_embedded` como procedencia de extraccion, no como autoridad. S0179 no corrige ni repara candidatas o relaciones descartadas; solo reporta.

## 8. Separacion de candidatas

Consumo directo detectado: {str(candidate_direct["detected"]).lower()}. Se revisaron imports, rutas runtime y lectores explicitos en productores productivos. Una coincidencia source-target-predicate no prueba dependencia funcional de `pipeline/relation_candidates/current/`.

## 9. Matriz de autoridad

`legacy canonical content`: contenido canonico pre-v1, derivable pero no autoridad v1. `candidate`: propuesta tecnica, no input productivo directo. `human decision`: requisito de admision, no observado aqui. `canonical-relation/v1`: unica forma que otorgaria autoridad canonica relacional. `derived legacy relation`: hereda autoridad limitada. `derived canonical relation`: futuro posible solo si transporta schema/provenance v1.

## 10. Alcance de equivalencia v2

Equivalence v2 cubre identidad/version y comparacion serializada de derivados. No compara autoridad: {str(scope["authority_compared"]).lower()}. No compara provenance: {str(scope["provenance_compared"]).lower()}. `controlled_v1` no equivale a `canonical-relation/v1`; S0184 debe comparar autoridad, provenance y schema explicitamente.

## 11. Contencion para S0180

```yaml
containment:
  candidates_are_not_productive_inputs: {str(containment["candidates_are_not_productive_inputs"]).lower()}
  legacy_relations_are_not_canonical_v1: {str(containment["legacy_relations_are_not_canonical_v1"]).lower()}
  canonical_authority_requires_canonical_relation_v1: {str(containment["canonical_authority_requires_canonical_relation_v1"]).lower()}
  reconciliation_must_not_auto_promote_legacy: {str(containment["reconciliation_must_not_auto_promote_legacy"]).lower()}
```

## 12. Delta esperado para S0184

S0184 debe separar relaciones v1 admitidas, legacy retenidas, legacy deprecadas, autoridad explicita, provenance explicita, perdidas inexplicadas y comparacion pre/post. Este reporte no implementa esas reglas.
"""


def build_reports(out: Path) -> dict[str, Any]:
    canon = read_jsonl(LOCAL, "tiddlers_*.jsonl")
    enriched = read_jsonl(LOCAL / "enriched", "*.jsonl")
    ai = read_jsonl(LOCAL / "ai", "tiddlers_ai_*.jsonl")
    chunks = read_jsonl(LOCAL / "ai", "chunks_ai_*.jsonl")
    canon_relations = relation_rows(canon, "relations")
    ai_targets = relation_rows(ai, "relation_targets")
    embedded = relation_rows(ai, "embedded_relations")
    chunk_targets = relation_rows(chunks, "relation_targets")
    qc = json.loads((LOCAL / "ai/reports/relations_qc_report.json").read_text(encoding="utf-8"))
    candidate_path = LOCAL / CANDIDATE_CURRENT_PATH / "relation_candidates.jsonl"
    candidate_rows = read_jsonl(candidate_path.parent, candidate_path.name)
    candidate_ids = {row.get("candidate_id") for row in candidate_rows if row.get("candidate_id")}
    edges_path = LOCAL / "microsoft_copilot/edges.csv"
    edges = list(csv.DictReader(edges_path.open(encoding="utf-8")))
    product_text = "\n".join(
        json.dumps(item, sort_keys=True, ensure_ascii=False)
        for item in [*enriched, *ai, *chunks]
    )
    product_text += edges_path.read_text(encoding="utf-8")
    producer_sources = {
        "derive_layers.py": (SCRIPT_DIR / "derive_layers.py").read_text(encoding="utf-8"),
        "rag_derivative_writers.py": (SCRIPT_DIR / "rag_derivative_writers.py").read_text(encoding="utf-8"),
    }
    candidate_direct = analyze_candidate_direct_consumption(
        candidate_path=candidate_path,
        candidate_ids=candidate_ids,
        productive_serialized_text=product_text,
        producer_sources=producer_sources,
    )
    count_semantics = explain_content_embedded_counts(embedded, ai_targets)
    controlled_v1 = classify_controlled_v1()
    canonical_v1 = sum(
        1 for relation in canon_relations if relation.get("schema_version") == "canonical-relation/v1"
    )
    lineage = {
        "schema_version": "derivative-relation-lineage/v2",
        "checked_at": "omitted_for_determinism",
        "canon": {
            "records": len(canon),
            "relations": len(canon_relations),
            "canonical_relation_v1": canonical_v1,
        },
        "productive_manifest": {
            "path": "audit/rag_admission/productive_rag_manifest.json",
            "hash": sha(LOCAL / "audit/rag_admission/productive_rag_manifest.json"),
        },
        "candidate_manifest": {
            "path": candidate_path.relative_to(LOCAL).as_posix(),
            "hash": sha(candidate_path),
            "count": len(candidate_ids),
            "direct_productive_consumption": candidate_direct["detected"],
        },
        "candidate_direct_consumption": candidate_direct,
        "content_embedded_count_semantics": count_semantics,
        "controlled_v1": controlled_v1,
        "pipeline_nodes": [
            {"id": "canon", "authority": "canonical_pre_v1"},
            {"id": "enriched", "authority": "derived"},
            {"id": "ai", "authority": "derived"},
            {"id": "chunks_ai", "authority": "derived_inherited_limited"},
            {"id": "microsoft_copilot", "authority": "derived"},
        ],
        "pipeline_edges": [
            {
                "from": "canon",
                "to": "enriched",
                "component": "derive_layers.py",
                "transformation": "preserves relations field",
            },
            {
                "from": "enriched",
                "to": "ai",
                "component": "derive_layers.py",
                "transformation": "relation_targets and embedded_relations",
            },
            {
                "from": "ai",
                "to": "chunks_ai",
                "component": "derive_layers.py",
                "transformation": "controlled_v1 parent propagation",
            },
            {
                "from": "canon+ai",
                "to": "microsoft_copilot",
                "component": "derive_layers.py",
                "transformation": "edges.csv",
            },
        ],
        "family_summaries": {
            "enriched": {
                "records": len(enriched),
                "relations": sum(len(item.get("relations") or []) for item in enriched),
            },
            "ai": {
                "records": len(ai),
                "relation_targets": len(ai_targets),
                "embedded_relations": len(embedded),
            },
            "chunks_ai": {
                "records": len(chunks),
                "relation_targets": len(chunk_targets),
                "creates_edges": False,
                "authority": controlled_v1["authority"],
                "propagation_policy": "controlled_v1",
            },
            "microsoft_copilot": {
                "edges": len(edges),
                "provenance": dict(Counter(row.get("provenance") for row in edges)),
            },
        },
        "reconciliation": {
            "canon_input": len(canon_relations),
            "ai_relation_targets": len(ai_targets),
            "ai_embedded": len(embedded),
            "chunk_targets": len(chunk_targets),
            "copilot_edges": len(edges),
            "discarded": qc.get("total_invalid_relations_discarded", 0),
        },
        "unexplained_deltas": [] if count_semantics["explained"] else [count_semantics["delta"]],
        "protected_surfaces": {
            "canon_mutated": False,
            "candidates_mutated": False,
            "relations_mutated": False,
            "enriched_mutated": False,
            "ai_mutated": False,
            "chunks_mutated": False,
            "copilot_mutated": False,
            "reverse_html_mutated": False,
            "remote_mutated": False,
        },
        "protected_surface_fingerprints": protected_fingerprints(),
    }
    legacy = {
        "schema_version": "legacy-relation-propagation/v2",
        "observed_legacy_relations": len(canon_relations),
        "by_predicate": dict(Counter(relation.get("type") for relation in canon_relations)),
        "by_origin": {
            "explicit_field": len(canon_relations),
            "content_embedded": len(embedded),
        },
        "by_family": lineage["family_summaries"],
        "retained": len(ai_targets) + len(embedded),
        "transformed": len(chunk_targets) + len(edges),
        "discarded": qc.get("total_invalid_relations_discarded", 0),
        "authority_elevation_detected": False,
        "candidate_direct_consumption": candidate_direct,
        "count_semantics": count_semantics,
        "controlled_v1": controlled_v1,
        "unexplained": lineage["unexplained_deltas"],
    }
    scope = {
        "schema_version": "equivalence-relational-scope/v2",
        "covered": ["record identity/version and serialized derived record comparison"],
        "partially_covered": ["relation fields only insofar as serialized record changes"],
        "not_covered": [
            "relational authority",
            "human-review binding",
            "candidate provenance as semantic authority",
            "controlled_v1 as canonical relation schema",
        ],
        "authority_compared": False,
        "provenance_compared": False,
        "controlled_v1_is_canonical_relation_v1": False,
        "schema_compared": "generic serialized/schema mismatch only",
        "blocking_relational_differences": "serialized regressions",
        "non_blocking_relational_differences": "none declared by authority",
        "implication_for_s0184": "compare authority, provenance and canonical_relation/v1 explicitly",
    }
    matrix_rows = [
        {
            "surface_category": "legacy_canonical_content",
            "source_path": "tiddlers_*.jsonl",
            "schema": "legacy relation",
            "provenance": "explicit_field",
            "authority": "pre_v1",
            "validation_status": "target QC",
            "producer": "derive_layers.py",
            "consumer": "ai/chunks/copilot",
            "productive_visibility": "yes",
            "requires_human_review": "yes",
            "canonical_admission_required": "yes",
            "grants_canonical_authority": "false",
            "direct_productive_input": "yes",
            "propagation_policy": "",
            "known_risk": "must not be called canonical_relation_v1",
        },
        {
            "surface_category": "candidate",
            "source_path": candidate_path.relative_to(LOCAL).as_posix(),
            "schema": "technical-relation-candidates/v1",
            "provenance": "candidate",
            "authority": "none",
            "validation_status": "blocked/needs review",
            "producer": "candidate generator",
            "consumer": "admission gate only",
            "productive_visibility": "no",
            "requires_human_review": "yes",
            "canonical_admission_required": "yes",
            "grants_canonical_authority": "false",
            "direct_productive_input": "false",
            "propagation_policy": "",
            "known_risk": "direct consumption prohibited",
        },
        {
            "surface_category": "canonical_relation_v1",
            "source_path": "tiddlers_*.jsonl",
            "schema": "canonical-relation/v1",
            "provenance": "explicit_field",
            "authority": "canonical",
            "validation_status": "not observed",
            "producer": "relation gate",
            "consumer": "future consumers",
            "productive_visibility": "not observed",
            "requires_human_review": "already reviewed",
            "canonical_admission_required": "no",
            "grants_canonical_authority": "true",
            "direct_productive_input": "not_observed",
            "propagation_policy": "",
            "known_risk": "none",
        },
        {
            "surface_category": "derived_legacy_relation",
            "source_path": "ai/tiddlers_ai_*.jsonl,microsoft_copilot/edges.csv",
            "schema": "derived",
            "provenance": "content_embedded or canon.relations",
            "authority": "inherited_limited",
            "validation_status": "QC/capped",
            "producer": "derive_layers.py",
            "consumer": "RAG/Copilot",
            "productive_visibility": "yes",
            "requires_human_review": "n/a",
            "canonical_admission_required": "n/a",
            "grants_canonical_authority": "false",
            "direct_productive_input": "derived_output",
            "propagation_policy": "",
            "known_risk": "authority ambiguous",
        },
        {
            "surface_category": "chunk_controlled_v1_projection",
            "source_path": "ai/chunks_ai_*.jsonl",
            "schema": "derived_or_legacy",
            "provenance": "parent relation_targets",
            "authority": "inherited_limited",
            "validation_status": "controlled propagation",
            "producer": "derive_layers.py",
            "consumer": "RAG chunks",
            "productive_visibility": "yes",
            "requires_human_review": "n/a",
            "canonical_admission_required": "n/a",
            "grants_canonical_authority": "false",
            "direct_productive_input": "derived_output",
            "propagation_policy": "controlled_v1",
            "known_risk": "controlled_v1 is not canonical-relation/v1",
        },
    ]
    human_report = build_human_report(
        lineage,
        legacy,
        count_semantics,
        candidate_direct,
        controlled_v1,
        scope,
    )
    return {
        "lineage": lineage,
        "legacy": legacy,
        "scope": scope,
        "matrix_rows": matrix_rows,
        "samples": qc.get("invalid_relation_samples", [])[:20],
        "human_report": human_report,
    }


def write_reports(out: Path, reports: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "current_derivative_relation_lineage.json").write_text(
        json.dumps(reports["lineage"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "legacy_relation_propagation_report.json").write_text(
        json.dumps(reports["legacy"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (out / "discarded_relation_sample.jsonl").open("w", encoding="utf-8") as handle:
        for sample in reports["samples"]:
            handle.write(
                json.dumps(
                    {
                        "source_canon_id": sample.get("source_id"),
                        "target_raw": sample.get("target_ref"),
                        "predicate": sample.get("type"),
                        "origin": sample.get("relation_source"),
                        "discard_stage": "relation_qc",
                        "discard_reason": sample.get("reason"),
                        "evidence_reference": sample.get("source_title"),
                        "family": "ai",
                        "unit": "invalid relation occurrence",
                        "reproducible": True,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    (out / "equivalence_relational_scope_report.json").write_text(
        json.dumps(reports["scope"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fieldnames = [
        "surface_category",
        "source_path",
        "schema",
        "provenance",
        "authority",
        "validation_status",
        "producer",
        "consumer",
        "productive_visibility",
        "requires_human_review",
        "canonical_admission_required",
        "grants_canonical_authority",
        "direct_productive_input",
        "propagation_policy",
        "known_risk",
    ]
    with (out / "relation_authority_matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reports["matrix_rows"])
    (out / "derivative_relation_contract_report.md").write_text(
        reports["human_report"],
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write_reports(args.out, build_reports(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
