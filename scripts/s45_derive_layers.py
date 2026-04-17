#!/usr/bin/env python3
"""
S45 — DEPRECATED compatibility wrapper.

This script has been superseded by scripts/derive_layers.py (S46+).

This wrapper forwards to derive_layers.py with S45-compatible defaults.
For new usage, call derive_layers.py directly:

    python3 scripts/derive_layers.py \\
        --input-dir out \\
        --enriched-dir out/enriched \\
        --ai-dir out/ai

S45 original docstring preserved for reference:
  Reads out/tiddlers_{1..7}.jsonl (canon shards) and produces:
    - out/enriched/tiddlers_enriched_{N}.jsonl  (Capa A)
    - out/ai/tiddlers_ai_{N}.jsonl              (Capa B)
    - out/ai/chunks_ai_{N}.jsonl                (Capa B — chunks)
    - out/enriched/manifest.json
    - out/ai/manifest.json
    - out/derivation-report-s45.json
"""
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    print("[s45_derive_layers.py] DEPRECATED — forwarding to scripts/derive_layers.py (S46+)")
    derive = Path(__file__).resolve().parent / "derive_layers.py"
    result = subprocess.run(
        [sys.executable, str(derive)] + sys.argv[1:],
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    sys.exit(result.returncode)

# ── Legacy code preserved below for reference only ────────────────────────────
# (Not executed — all derivation logic now lives in derive_layers.py)

import json
import os
import re
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone

# ── Configuration ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "out"
ENRICHED_DIR = OUT_DIR / "enriched"
AI_DIR = OUT_DIR / "ai"

SHARD_COUNT = 7
ENRICHED_SHARD_SIZE = 100   # records per enriched shard
AI_SHARD_SIZE = 100         # records per AI shard
CHUNK_SHARD_SIZE = 200      # chunks per chunk shard
CHUNK_TOKEN_THRESHOLD = 4000  # nodes above this get chunked
CHUNK_TARGET_TOKENS = 2000    # target chunk size in tokens
LARGE_NODE_THRESHOLD = 4000   # token threshold for is_large_node

# ── Helpers ────────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for mixed content."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def safe_str(val) -> str:
    if val is None:
        return ""
    return str(val)


def truncate_text(text: str, max_chars: int = 500) -> str:
    """Truncate text to max_chars, ending at word boundary."""
    if not text or len(text) <= max_chars:
        return text or ""
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.6:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"


def derive_semantic_text(rec: dict) -> str:
    """Derive semantic_text from content.plain, falling back to text."""
    content = rec.get("content") or {}
    plain = content.get("plain") or ""
    if plain:
        return truncate_text(plain, 500)
    text = rec.get("text") or ""
    if text:
        return truncate_text(text, 500)
    return ""


def derive_quality_flags(rec: dict) -> dict:
    """Compute quality flags from known data issues."""
    flags = {}
    sf = rec.get("source_fields") or {}
    tmap_id = sf.get("tmap.id", "")
    if "PENDIENTE" in tmap_id:
        flags["has_pendiente_tmap_id"] = True
    if rec.get("content_type") == "unknown":
        flags["has_unknown_content_type"] = True
    nt = rec.get("normalized_tags")
    if not nt:
        flags["has_empty_normalized_tags"] = True
    semantic = rec.get("semantic_text")
    if not semantic:
        flags["canon_semantic_text_absent"] = True
    text = rec.get("text") or ""
    if len(text.strip()) < 10:
        flags["has_minimal_text"] = True
    return flags


def derive_secondary_roles(rec: dict) -> list:
    """Heuristically derive secondary roles from tags, title, and content_type."""
    roles = []
    title = (rec.get("title") or "").lower()
    tags = rec.get("normalized_tags") or []
    tags_lower = [t.lower() for t in tags]
    ct = rec.get("content_type") or ""

    # Pattern-based role detection
    if any("hipotesis" in t or "hipótesis" in t for t in tags_lower):
        roles.append("hipótesis")
    if any("procedencia" in t for t in tags_lower):
        roles.append("procedencia")
    if any("sesion" in t or "sesión" in t for t in tags_lower):
        roles.append("sesión")
    if any("diccionario" in t for t in tags_lower):
        roles.append("referencia")
    if any("referencias" in t for t in tags_lower):
        roles.append("referencia")
    if any("principios" in t or "gestion" in t for t in tags_lower):
        roles.append("normativo")
    if any("protocolo" in t for t in tags_lower):
        roles.append("protocolo")
    if any("glosario" in t for t in tags_lower):
        roles.append("glosario")

    # Title-based
    if "readme" in title:
        roles.append("documentación")
    if title.startswith("--") or title.startswith("_"):
        roles.append("documentación")

    # Content type based
    if ct == "application/json":
        if "config" not in roles:
            roles.append("config")
    if ct == "image/png":
        roles.append("visual")

    return list(dict.fromkeys(roles))  # deduplicate preserving order


def derive_retrieval_hints(rec: dict) -> list:
    """Extract retrieval hints from tags, title, taxonomy_path."""
    hints = set()
    title = rec.get("title") or ""
    # Extract meaningful words from title
    words = re.findall(r"[\w]+", title.lower())
    for w in words:
        if len(w) > 3 and w not in ("para", "como", "este", "esta", "todo", "cada",
                                      "donde", "cuando", "tiddly", "data", "converter"):
            hints.add(w)

    tags = rec.get("normalized_tags") or []
    for t in tags:
        tag_words = re.findall(r"[\w]+", t.lower())
        for w in tag_words:
            if len(w) > 3:
                hints.add(w)

    tp = rec.get("taxonomy_path") or []
    for p in tp:
        path_words = re.findall(r"[\w]+", p.lower())
        for w in path_words:
            if len(w) > 3:
                hints.add(w)

    return sorted(hints)[:20]  # cap at 20 hints


def derive_confidence(rec: dict, qflags: dict) -> int:
    """Heuristic confidence 1-3 based on data completeness."""
    score = 3
    if qflags.get("has_pendiente_tmap_id"):
        score -= 1
    if qflags.get("has_unknown_content_type"):
        score -= 1
    if qflags.get("has_empty_normalized_tags"):
        score -= 1
    if qflags.get("has_minimal_text"):
        score -= 1
    if rec.get("role_primary") == "unclassified":
        score -= 0  # expected, not penalized
    return max(1, min(3, score))


def derive_is_foundational(rec: dict) -> bool:
    """Heuristic: foundational if it's a structural block (## level) or arranque node."""
    title = rec.get("title") or ""
    sp = rec.get("section_path") or []
    if title.startswith("## ") or title.startswith("# "):
        return True
    if len(sp) == 1:
        return True
    if any(k in title.lower() for k in ("readme", "protocolo", "principios", "glosario",
                                          "arquitectura", "objetivos", "requisitos")):
        return True
    return False


def derive_chunk_group(rec: dict, token_est: int) -> str:
    """Assign a chunk group based on content_type and size."""
    ct = rec.get("content_type") or ""
    if ct in ("image/png",):
        return "binary_no_chunk"
    if ct == "application/json":
        return "config_no_chunk"
    if token_est > CHUNK_TOKEN_THRESHOLD:
        return "large_text_chunk"
    if token_est > 1000:
        return "medium_text"
    return "small_text"


def chunk_text(text: str, node_id: str, title: str, chunk_target: int = CHUNK_TARGET_TOKENS) -> list:
    """Split text into chunks of ~chunk_target tokens, preserving paragraph boundaries."""
    if not text:
        return []
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    current_tokens = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        if current_tokens + para_tokens > chunk_target and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = para + "\n\n"
            current_tokens = para_tokens
        else:
            current_chunk += para + "\n\n"
            current_tokens += para_tokens

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    result = []
    for idx, chunk_text_val in enumerate(chunks):
        chunk_id = f"{node_id}::chunk:{idx}"
        result.append({
            "chunk_id": chunk_id,
            "node_id": node_id,
            "title": title,
            "chunk_index": idx,
            "chunk_total": len(chunks),
            "text": chunk_text_val,
            "token_estimate": estimate_tokens(chunk_text_val),
            "derivation": "deterministic_split",
        })
    return result


# ── Loading canon shards ───────────────────────────────────────────────────

def load_canon() -> list:
    """Load all canon shards into a list of (record, shard_file, line_num)."""
    records = []
    for i in range(1, SHARD_COUNT + 1):
        shard_path = OUT_DIR / f"tiddlers_{i}.jsonl"
        if not shard_path.exists():
            print(f"WARNING: {shard_path} not found, skipping", file=sys.stderr)
            continue
        with open(shard_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                records.append((rec, shard_path.name, line_num))
    return records


# ── Enriched Canonical Export (Capa A) ─────────────────────────────────────

def build_enriched_record(rec: dict, shard_file: str, line_num: int) -> dict:
    """Build enriched canonical record from canon record."""
    text = rec.get("text") or ""
    content = rec.get("content") or {}
    token_est = estimate_tokens(text)
    qflags = derive_quality_flags(rec)
    sec_roles = derive_secondary_roles(rec)

    enriched = {
        # ── Copied deterministic fields ──
        "id": rec.get("id"),
        "title": rec.get("title"),
        "role_primary": rec.get("role_primary"),
        "text": text,
        "content_type": rec.get("content_type"),
        "source_type": rec.get("source_type"),
        "source_fields": rec.get("source_fields"),
        "source_tags": rec.get("source_tags"),
        "normalized_tags": rec.get("normalized_tags"),
        "source_ref": rec.get("raw_payload_ref"),
        "relations": rec.get("relations"),
        "document_id": rec.get("document_id"),
        "section_path": rec.get("section_path"),
        "taxonomy_path": rec.get("taxonomy_path"),
        "order_in_document": rec.get("order_in_document"),
        "tags": rec.get("tags"),
        "schema_version": rec.get("schema_version"),
        "key": rec.get("key"),
        "canonical_slug": rec.get("canonical_slug"),
        "version_id": rec.get("version_id"),
        "modality": rec.get("modality"),
        "encoding": rec.get("encoding"),
        "is_binary": rec.get("is_binary"),
        "is_reference_only": rec.get("is_reference_only"),
        "mime_type": rec.get("mime_type"),
        "source_position": rec.get("source_position"),
        "created": rec.get("created"),
        "modified": rec.get("modified"),
        # ── Derived deterministic fields ──
        "semantic_text": derive_semantic_text(rec),
        "content": {
            "plain": content.get("plain") or "",
            "markdown": text if rec.get("content_type") in ("text/markdown", "text/vnd.tiddlywiki") else None,
        },
        "size_metrics": {
            "text_length": len(text),
            "content_plain_length": len(content.get("plain") or ""),
            "token_estimate": token_est,
        },
        # ── Heuristic fields (marked) ──
        "secondary_roles": sec_roles,
        "quality_flags": qflags,
        "readability": "prose" if rec.get("content_type") in ("text/markdown", "text/vnd.tiddlywiki", "text/plain") else "structured",
        # ── Derivation traceability ──
        "derivation": {
            "session": "S45",
            "source_shard": shard_file,
            "source_line": line_num,
            "fields_copied": [
                "id", "title", "role_primary", "text", "content_type",
                "source_type", "source_fields", "source_tags", "normalized_tags",
                "relations", "document_id", "section_path", "taxonomy_path",
                "order_in_document", "tags", "schema_version", "key",
                "canonical_slug", "version_id", "modality", "encoding",
                "is_binary", "is_reference_only", "mime_type",
                "source_position", "created", "modified",
            ],
            "fields_derived_deterministic": [
                "semantic_text", "content.plain", "content.markdown",
                "size_metrics", "readability",
            ],
            "fields_heuristic": [
                "secondary_roles", "quality_flags",
            ],
            "fields_absent": [
                "provenance", "metacognition",
            ],
        },
        "provisionality": "partial" if qflags else "stable",
    }
    return enriched


# ── AI-friendly Projection (Capa B) ───────────────────────────────────────

def build_ai_record(rec: dict, shard_file: str, line_num: int) -> tuple:
    """Build AI-friendly record and optional chunks from canon record.
    Returns (ai_record, [chunks])."""
    text = rec.get("text") or ""
    content = rec.get("content") or {}
    token_est = estimate_tokens(text)
    qflags = derive_quality_flags(rec)
    sec_roles = derive_secondary_roles(rec)
    semantic = derive_semantic_text(rec)
    hints = derive_retrieval_hints(rec)
    confidence = derive_confidence(rec, qflags)
    is_found = derive_is_foundational(rec)
    is_large = token_est > LARGE_NODE_THRESHOLD
    cg = derive_chunk_group(rec, token_est)
    node_id = rec.get("id")

    # Simplified relations
    rels = rec.get("relations") or []
    rel_targets = []
    for r in rels:
        rt = {"type": r.get("type"), "target_id": r.get("target_id")}
        if r.get("evidence"):
            rt["evidence"] = r["evidence"]
        rel_targets.append(rt)

    ai_rec = {
        "node_id": node_id,
        "title": rec.get("title"),
        "role_primary": rec.get("role_primary"),
        "secondary_roles": sec_roles,
        "semantic_text": semantic,
        "ai_summary": truncate_text(content.get("plain") or text, 300),
        "retrieval_hints": hints,
        "relation_targets": rel_targets,
        "source_anchor": {
            "canon_id": node_id,
            "shard_file": shard_file,
            "shard_line": line_num,
        },
        "quality_flags": qflags,
        "confidence": confidence,
        "is_reference_only": rec.get("is_reference_only", False),
        "is_foundational": is_found,
        "is_large_node": is_large,
        "token_estimate": token_est,
        "chunk_group": cg,
        "document_id": rec.get("document_id"),
        "section_path": rec.get("section_path"),
        "taxonomy_path": rec.get("taxonomy_path"),
        "content_type": rec.get("content_type"),
        "derivation": {
            "session": "S45",
            "method": "projection",
            "fields_heuristic": [
                "secondary_roles", "confidence", "is_foundational",
                "retrieval_hints", "chunk_group",
            ],
            "fields_derived_deterministic": [
                "semantic_text", "ai_summary", "token_estimate",
                "is_large_node", "source_anchor",
            ],
        },
    }

    # Generate chunks for large text nodes
    chunks = []
    if cg == "large_text_chunk" and text:
        chunks = chunk_text(text, node_id, rec.get("title", ""), CHUNK_TARGET_TOKENS)

    return ai_rec, chunks


# ── Sharding helpers ───────────────────────────────────────────────────────

def write_sharded(records: list, output_dir: Path, prefix: str, shard_size: int) -> list:
    """Write records to sharded JSONL files. Returns list of shard info dicts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    shards = []
    shard_num = 1
    count_in_shard = 0
    current_file = None
    total = 0

    for rec in records:
        if count_in_shard == 0 or count_in_shard >= shard_size:
            if current_file:
                current_file.close()
                shards[-1]["record_count"] = count_in_shard
            fname = f"{prefix}_{shard_num}.jsonl"
            fpath = output_dir / fname
            current_file = open(fpath, "w", encoding="utf-8")
            shards.append({
                "file": fname,
                "shard_index": shard_num,
                "record_count": 0,
            })
            shard_num += 1
            count_in_shard = 0

        line = json.dumps(rec, ensure_ascii=False)
        current_file.write(line + "\n")
        count_in_shard += 1
        total += 1

    if current_file:
        current_file.close()
        if shards:
            shards[-1]["record_count"] = count_in_shard

    return shards


def write_manifest(output_dir: Path, layer_name: str, shards_info: list,
                   total_records: int, source_shards: int, extra: dict = None):
    """Write manifest.json for a layer."""
    manifest = {
        "layer": layer_name,
        "session": "S45",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "canon_shards": source_shards,
            "canon_dir": "out/",
            "canon_pattern": "tiddlers_{N}.jsonl",
        },
        "output": {
            "total_records": total_records,
            "shard_count": len(shards_info),
            "shards": shards_info,
        },
    }
    if extra:
        manifest.update(extra)
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest_path


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("S45 — Loading canon shards...")
    canon = load_canon()
    print(f"  Loaded {len(canon)} records from {SHARD_COUNT} shards.")

    if not canon:
        print("ERROR: No canon records found.", file=sys.stderr)
        sys.exit(1)

    # ── Build Capa A: Enriched Canonical Export ──
    print("Building Capa A — Enriched Canonical Export...")
    enriched_records = []
    for rec, shard_file, line_num in canon:
        enriched_records.append(build_enriched_record(rec, shard_file, line_num))

    enriched_shards = write_sharded(
        enriched_records, ENRICHED_DIR, "tiddlers_enriched", ENRICHED_SHARD_SIZE
    )
    enriched_manifest = write_manifest(
        ENRICHED_DIR, "enriched_canonical_export", enriched_shards,
        len(enriched_records), SHARD_COUNT,
    )
    print(f"  Wrote {len(enriched_records)} enriched records across {len(enriched_shards)} shards.")

    # ── Build Capa B: AI-friendly Projection ──
    print("Building Capa B — AI-friendly Projection...")
    ai_records = []
    all_chunks = []
    for rec, shard_file, line_num in canon:
        ai_rec, chunks = build_ai_record(rec, shard_file, line_num)
        ai_records.append(ai_rec)
        all_chunks.extend(chunks)

    ai_shards = write_sharded(ai_records, AI_DIR, "tiddlers_ai", AI_SHARD_SIZE)
    chunk_shards = []
    if all_chunks:
        chunk_shards = write_sharded(all_chunks, AI_DIR, "chunks_ai", CHUNK_SHARD_SIZE)
    ai_manifest = write_manifest(
        AI_DIR, "ai_friendly_projection", ai_shards, len(ai_records), SHARD_COUNT,
        extra={
            "chunks": {
                "total_chunks": len(all_chunks),
                "shard_count": len(chunk_shards),
                "shards": chunk_shards,
                "chunk_token_threshold": CHUNK_TOKEN_THRESHOLD,
                "chunk_target_tokens": CHUNK_TARGET_TOKENS,
            }
        }
    )
    print(f"  Wrote {len(ai_records)} AI records across {len(ai_shards)} shards.")
    print(f"  Wrote {len(all_chunks)} chunks across {len(chunk_shards)} chunk shards.")

    # ── Derivation report ──
    print("Writing derivation report...")
    report = {
        "session": "S45",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input": {
            "canon_shards": SHARD_COUNT,
            "total_records": len(canon),
            "shard_files": [f"tiddlers_{i}.jsonl" for i in range(1, SHARD_COUNT + 1)],
        },
        "output": {
            "enriched": {
                "total_records": len(enriched_records),
                "shard_count": len(enriched_shards),
                "directory": "out/enriched/",
            },
            "ai": {
                "total_records": len(ai_records),
                "shard_count": len(ai_shards),
                "directory": "out/ai/",
            },
            "chunks": {
                "total_chunks": len(all_chunks),
                "shard_count": len(chunk_shards),
            },
        },
        "identity_check": {
            "input_ids": len(canon),
            "enriched_ids": len(enriched_records),
            "ai_ids": len(ai_records),
            "ids_match": len(canon) == len(enriched_records) == len(ai_records),
        },
        "quality_summary": {
            "role_primary_distribution": {},
            "content_type_distribution": {},
            "semantic_text_derived": 0,
            "quality_flags_triggered": 0,
            "pendiente_tmap_ids": 0,
            "large_nodes_chunked": 0,
        },
        "derivation_rules": {
            "deterministic_copied": [
                "id", "title", "role_primary", "text", "content_type",
                "source_type", "source_fields", "source_tags", "normalized_tags",
                "relations", "document_id", "section_path", "taxonomy_path",
                "order_in_document", "tags", "is_binary", "is_reference_only",
                "content.plain", "created", "modified",
            ],
            "deterministic_derived": [
                "semantic_text", "content.markdown", "size_metrics",
                "token_estimate", "is_large_node", "ai_summary",
                "readability",
            ],
            "heuristic_marked": [
                "secondary_roles", "quality_flags", "confidence",
                "is_foundational", "retrieval_hints", "chunk_group",
            ],
            "prohibited_not_invented": [
                "provenance", "metacognition", "strong_relations_defines_contradicts_requires",
                "author_intent", "epistemological_history",
            ],
        },
        "warnings": [],
    }

    # Compute summary stats
    from collections import Counter
    role_counts = Counter()
    ct_counts = Counter()
    sem_derived = 0
    qf_triggered = 0
    pend = 0
    chunked_nodes = 0

    for i, (rec, sf, ln) in enumerate(canon):
        role_counts[rec.get("role_primary", "<missing>")] += 1
        ct_counts[rec.get("content_type", "<missing>")] += 1
        if enriched_records[i].get("semantic_text"):
            sem_derived += 1
        if enriched_records[i].get("quality_flags"):
            qf_triggered += 1
        sfields = rec.get("source_fields") or {}
        if "PENDIENTE" in sfields.get("tmap.id", ""):
            pend += 1
        if ai_records[i].get("chunk_group") == "large_text_chunk":
            chunked_nodes += 1

    report["quality_summary"]["role_primary_distribution"] = dict(role_counts)
    report["quality_summary"]["content_type_distribution"] = dict(ct_counts)
    report["quality_summary"]["semantic_text_derived"] = sem_derived
    report["quality_summary"]["quality_flags_triggered"] = qf_triggered
    report["quality_summary"]["pendiente_tmap_ids"] = pend
    report["quality_summary"]["large_nodes_chunked"] = chunked_nodes

    # Warnings
    if pend > 0:
        report["warnings"].append(f"{pend} records have PENDIENTE-* in source_fields.tmap.id (not resolved, preserved as-is)")
    if any(r.get("content_type") == "unknown" for r, _, _ in canon):
        report["warnings"].append("1+ records have content_type=unknown (preserved, flagged)")
    if sem_derived < len(canon):
        absent = len(canon) - sem_derived
        report["warnings"].append(f"{absent} records could not derive semantic_text (content.plain and text empty or minimal)")

    report_path = OUT_DIR / "derivation-report-s45.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nDerivation report: {report_path}")
    print(f"Enriched manifest: {enriched_manifest}")
    print(f"AI manifest: {AI_DIR / 'manifest.json'}")
    print("\n── Summary ──")
    print(f"  Canon input:     {len(canon)} records, {SHARD_COUNT} shards")
    print(f"  Enriched output: {len(enriched_records)} records, {len(enriched_shards)} shards")
    print(f"  AI output:       {len(ai_records)} records, {len(ai_shards)} shards")
    print(f"  Chunks:          {len(all_chunks)} chunks, {len(chunk_shards)} shards")
    print(f"  IDs match:       {report['identity_check']['ids_match']}")
    print(f"  Warnings:        {len(report['warnings'])}")
    for w in report["warnings"]:
        print(f"    - {w}")
    print("\nS45 derivation complete.")


if __name__ == "__main__":
    main()
