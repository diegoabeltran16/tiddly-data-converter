"""QC Reports — extracted from derive_layers.py in S0119.

Five write_* functions that produce the QC report files under
data/out/local/ai/reports/. Each function is purely functional:
it receives all data it needs as parameters and writes one JSON file.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from chunking import DEFAULT_MICROCHUNK_MIN_TOKENS, is_separator_only_chunk
from corpus_governance import (
    CANON_POLICY_BUNDLE_REL,
    DERIVED_LAYERS_REGISTRY_REL,
    load_canon_policy_bundle,
)
from text_utils import normalize_for_dedup, safe_str

SESSION = "S55"
SCHEMA_VERSION = "v2"
CANON_POLICY_BUNDLE = load_canon_policy_bundle()


def write_classification_report(output_dir: Path, ai_records: list,
                                  enriched_records: list) -> Path:
    role_dist = Counter(r["role_primary"] for r in ai_records)
    unclassified_count = role_dist.get("unclassified", 0)
    total = len(ai_records)

    with_taxonomy = sum(1 for r in enriched_records if r.get("taxonomy_path"))
    with_section = sum(1 for r in enriched_records if r.get("section_path"))
    taxonomy_coverage = round(with_taxonomy / total, 4) if total else 0
    section_coverage = round(with_section / total, 4) if total else 0

    # Per-role sample titles for auditability
    role_samples = defaultdict(list)
    for r in ai_records:
        rp = r["role_primary"]
        if len(role_samples[rp]) < 3:
            role_samples[rp].append(safe_str(r.get("title"))[:60])

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_nodes": total,
        "role_primary_distribution": dict(role_dist.most_common()),
        "unclassified_count": unclassified_count,
        "unclassified_fraction": round(unclassified_count / total, 4) if total else 0,
        "taxonomy_path_coverage": {
            "nodes_with_taxonomy": with_taxonomy,
            "total": total,
            "coverage_fraction": taxonomy_coverage,
        },
        "section_path_coverage": {
            "nodes_with_section": with_section,
            "total": total,
            "coverage_fraction": section_coverage,
        },
        "role_samples": {k: v for k, v in role_samples.items()},
    }
    p = output_dir / "classification_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


def write_chunk_qc_report(output_dir: Path, ai_records: list,
                            all_chunks: list,
                            chunk_qc_events: list,
                            target_tokens: int, max_tokens: int,
                            relation_propagation_summary: dict | None = None) -> Path:
    text_capable_nodes = [r for r in ai_records if r.get("is_textual_payload")]
    chunkable_nodes = [r for r in ai_records if r.get("is_chunkable_text")]
    chunked_node_ids = {c.get("node_id") for c in all_chunks if c.get("node_id")}

    over_target = [c for c in all_chunks if not c.get("within_target")]
    over_max = [c for c in all_chunks if not c.get("within_hard_max")]
    with_fallback = [c for c in all_chunks if c.get("fallback")]

    excluded_reasons = Counter()
    for ev in chunk_qc_events:
        if ev.get("exclusion_reason"):
            excluded_reasons[ev["exclusion_reason"]] += 1

    eligibility_dist = Counter(r.get("chunk_eligibility", "unknown") for r in ai_records)
    token_sizes = [c.get("token_estimate", 0) for c in all_chunks]
    microchunks = [c for c in all_chunks if c.get("token_estimate", 0) < DEFAULT_MICROCHUNK_MIN_TOKENS]
    heading_only = [c for c in all_chunks if is_separator_only_chunk(safe_str(c.get("text")))]
    size_stats = {}
    if token_sizes:
        ordered = sorted(token_sizes)
        size_stats = {
            "avg_tokens": round(statistics.mean(token_sizes), 2),
            "median_tokens": statistics.median(ordered),
            "p95_tokens": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)],
            "max_tokens": ordered[-1],
        }
    top_oversized = Counter(
        (c.get("title"), c.get("node_id"))
        for c in over_target
    )

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {
            "chunk_target_tokens": target_tokens,
            "chunk_hard_max_tokens": max_tokens,
            "microchunk_threshold_tokens": DEFAULT_MICROCHUNK_MIN_TOKENS,
        },
        "total_nodes": len(ai_records),
        "text_capable_nodes": len(text_capable_nodes),
        "chunkable_nodes": len(chunkable_nodes),
        "nodes_that_produced_chunks": len(chunked_node_ids),
        "total_chunks_generated": len(all_chunks),
        "chunks_above_target": len(over_target),
        "chunks_above_hard_max": len(over_max),
        "chunks_below_micro_threshold": len(microchunks),
        "heading_only_chunks": len(heading_only),
        "chunks_with_fallback": len(with_fallback),
        "nodes_excluded_from_chunking": sum(excluded_reasons.values()),
        "exclusion_reasons": dict(excluded_reasons),
        "chunk_eligibility_distribution": dict(eligibility_dist),
        "chunk_size_distribution": size_stats,
        "traceability_summary": {
            "chunks_with_source_anchor": sum(1 for c in all_chunks if c.get("source_anchor")),
            "chunks_with_source_id": sum(1 for c in all_chunks if c.get("source_id")),
            "chunks_with_source_title": sum(1 for c in all_chunks if c.get("source_title")),
            "chunks_with_source_canonical_slug": sum(1 for c in all_chunks if c.get("source_canonical_slug")),
            "chunks_with_relation_target_count": sum(1 for c in all_chunks if "relation_target_count" in c),
            "chunks_with_relation_propagation_policy": sum(1 for c in all_chunks if c.get("relation_propagation_policy")),
            "chunks_with_section_path": sum(1 for c in all_chunks if c.get("section_path")),
            "chunks_with_taxonomy_path": sum(1 for c in all_chunks if c.get("taxonomy_path")),
        },
        "hard_max_violated": len(over_max) > 0,
    }
    if relation_propagation_summary is not None:
        report["relation_propagation"] = relation_propagation_summary
    if over_target:
        report["top_oversized_nodes"] = [
            {
                "title": title,
                "node_id": node_id,
                "oversized_chunks": count,
            }
            for (title, node_id), count in top_oversized.most_common(10)
        ]
    if over_max:
        report["hard_max_violations"] = [
            {"chunk_id": c["chunk_id"], "token_estimate": c["token_estimate"]}
            for c in over_max[:10]
        ]
    p = output_dir / "chunk_qc_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


def write_retrieval_qc_report(output_dir: Path, ai_records: list) -> Path:
    total_hints = 0
    total_terms = 0
    total_aliases = 0
    nodes_with_aliases = 0
    nodes_with_empty_hints = 0
    dedup_resolved = 0

    for r in ai_records:
        terms = r.get("retrieval_terms") or []
        aliases = r.get("retrieval_aliases") or []
        hints = r.get("retrieval_hints") or []
        total_terms += len(terms)
        total_aliases += len(aliases)
        total_hints += len(hints)
        if aliases:
            nodes_with_aliases += 1
        if not hints:
            nodes_with_empty_hints += 1
        # Measure how many aliases were resolved from duplicates
        dedup_resolved += max(0, len(terms) + len(aliases) - len(set(normalize_for_dedup(h) for h in hints)))

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_nodes": len(ai_records),
        "total_retrieval_hints": total_hints,
        "total_retrieval_terms": total_terms,
        "total_retrieval_aliases": total_aliases,
        "nodes_with_aliases": nodes_with_aliases,
        "nodes_with_empty_hints": nodes_with_empty_hints,
        "avg_hints_per_node": round(total_hints / len(ai_records), 2) if ai_records else 0,
        "dedup_resolved_count": dedup_resolved,
    }
    p = output_dir / "retrieval_qc_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


def write_relations_qc_report(output_dir: Path, ai_records: list,
                                all_invalid_rels: list,
                                all_chunks: list | None = None,
                                relation_propagation_summary: dict | None = None) -> Path:
    total_rels = sum(len(r.get("relation_targets") or []) for r in ai_records)
    type_dist = Counter()
    for r in ai_records:
        for rel in (r.get("relation_targets") or []):
            type_dist[rel.get("type", "unknown")] += 1
    chunk_type_dist = Counter()
    for chunk in all_chunks or []:
        for rel in chunk.get("relation_targets") or []:
            chunk_type_dist[rel.get("type", "unknown")] += 1

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_nodes": len(ai_records),
        "total_valid_relations": total_rels,
        "relation_type_distribution": dict(type_dist.most_common()),
        "total_invalid_relations_discarded": len(all_invalid_rels),
        "invalid_relation_reason_distribution": dict(
            Counter(rel.get("reason", "unknown") for rel in all_invalid_rels).most_common()
        ),
        "invalid_relation_source_distribution": dict(
            Counter(rel.get("relation_source", "unknown") for rel in all_invalid_rels).most_common()
        ),
        "invalid_relation_samples": all_invalid_rels[:20],
        "chunk_relation_type_distribution": dict(chunk_type_dist.most_common()),
    }
    if relation_propagation_summary is not None:
        report["chunk_relation_propagation"] = relation_propagation_summary
    p = output_dir / "relations_qc_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


def write_derivation_report(output_dir: Path, canon: list,
                              enriched_records: list, ai_records: list,
                              all_chunks: list, shard_paths: list,
                              target_tokens: int, max_tokens: int) -> Path:
    role_dist = Counter(r["role_primary"] for r in ai_records)
    ct_dist = Counter(rec.get("content_type", "<missing>") for rec, _, _ in canon)
    corpus_state_dist = Counter(r.get("corpus_state", "unknown") for r in ai_records)
    corpus_state_rule_dist = Counter(r.get("corpus_state_rule_id", "unknown") for r in ai_records)

    report = {
        "session": SESSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input": {
            "canon_shard_count": len(shard_paths),
            "canon_shard_files": [p.name for p in shard_paths],
            "total_records": len(canon),
        },
        "output": {
            "enriched_records": len(enriched_records),
            "ai_records": len(ai_records),
            "total_chunks": len(all_chunks),
        },
        "identity_check": {
            "ids_match": len(canon) == len(enriched_records) == len(ai_records),
            "canon_count": len(canon),
            "enriched_count": len(enriched_records),
            "ai_count": len(ai_records),
        },
        "classification_summary": {
            "role_distribution": dict(role_dist.most_common()),
            "unclassified_count": role_dist.get("unclassified", 0),
            "unclassified_fraction": round(
                role_dist.get("unclassified", 0) / len(canon), 4
            ) if canon else 0,
        },
        "governance": {
            "policy_bundle_ref": CANON_POLICY_BUNDLE_REL,
            "layer_registry_ref": DERIVED_LAYERS_REGISTRY_REL,
            "defined_corpus_states": list(CANON_POLICY_BUNDLE["corpus_state_catalog"].keys()),
            "observed_corpus_state_distribution": dict(corpus_state_dist.most_common()),
            "observed_corpus_state_rule_distribution": dict(corpus_state_rule_dist.most_common()),
        },
        "content_type_distribution": dict(ct_dist.most_common()),
        "chunking_summary": {
            "target_tokens": target_tokens,
            "hard_max_tokens": max_tokens,
            "total_chunks": len(all_chunks),
            "over_hard_max": sum(1 for c in all_chunks if not c.get("within_hard_max")),
            "over_target": sum(1 for c in all_chunks if not c.get("within_target")),
        },
        "hardening_notes": {
            "shard_discovery": "dynamic — pattern tiddlers_*.jsonl",
            "role_vocabulary": "controlled — 26 roles",
            "chunker": "token-aware structural chunker with recursive boundary refinement and post-pass microchunk densification",
            "chunk_eligibility": "resolved from canon_policy_bundle.json before chunking or AI projection",
            "retrieval": "normalized dedup with terms + aliases",
            "relations": "validated against known node IDs",
            "text_fields": "three distinct: preview_text, semantic_text, ai_summary",
            "traceability": "chunks include source_id/tiddler_id aliases, source_anchor, section_path and taxonomy_path",
        },
    }
    p = output_dir / "derivation_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p
