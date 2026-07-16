#!/usr/bin/env python3
"""
ai_records.py — AI record builder cluster (extracted S0114).

Dependency chain (no circular imports):
  corpus_governance → (no local deps)
  text_utils        → (no local deps)
  chunking          → text_utils
  enrichment        → corpus_governance, text_utils
  ai_records        → corpus_governance, text_utils, enrichment, chunking
  derive_layers     → ai_records, enrichment, chunking, classification, ...
"""

import json
import re
from collections import Counter

from corpus_governance import (
    CANON_POLICY_BUNDLE_REL,
    classify_role_primary_value,
    load_canon_policy_bundle,
)
from text_utils import (
    estimate_tokens,
    normalize_for_dedup,
    safe_str,
    strip_emoji,
)
from enrichment import (
    build_secondary_roles,
    compute_is_reference_only,
    compute_preview_text,
    compute_quality_flags,
    compute_semantic_text,
    derive_corpus_policy,
)
from chunking import (
    densify_microchunks,
    extract_chunk_heading,
    hard_split,
    split_structurally,
)

# ── Session / governance ──────────────────────────────────────────────────────
SESSION = "S55"
CANON_POLICY_BUNDLE = load_canon_policy_bundle()

# ── Relation policy constants ─────────────────────────────────────────────────
RELATION_PROPAGATION_POLICY_VERSION = "controlled_v1"
MAX_RELATION_TARGETS_PER_CHUNK = 8

SEMANTIC_RELATION_TYPES = frozenset({
    "define",
    "requiere",
    "contiene",
    "pertenece_a",
    "prueba_de",
    "references",
})
STRUCTURAL_RELATION_TYPES = frozenset({"child_of", "parte_de"})
TECHNICAL_RELATION_TYPES = frozenset()
GENERIC_RELATION_TYPES = frozenset({"usa"})
DECORATIVE_RELATION_TYPES = frozenset()

# Stop words for retrieval hint extraction
STOP_WORDS = {
    "para", "como", "este", "esta", "todo", "cada", "donde", "cuando",
    "tiddly", "data", "converter", "desde", "hasta", "sobre", "entre",
    "pero", "sino", "porque", "aunque", "mientras", "durante", "tras",
    "ante", "bajo", "cabe", "con", "contra", "desde", "hace",
    "hacia", "mediante", "para", "por", "segun", "según", "sin",
    "sobre", "tras", "versus", "the", "and", "for", "from", "with",
    "that", "this", "are", "was", "were", "has", "have", "been",
    "not", "all", "can", "will", "its", "into", "than", "then",
    "they", "them", "what", "when", "also",
}

# S84: capa-2 semantic embedded relation types
_EMBEDDED_RELATION_TYPES = frozenset({
    "usa", "define", "requiere", "parte_de",
    "pertenece_a", "contiene", "prueba_de",
})


def compute_ai_summary(rec: dict, role: str) -> str:
    """
    ai_summary: a short, intentional description of the node's purpose.
    Constructed deterministically from title, role, and text beginning.
    This is NOT a mechanical truncation — it's a short purposeful description.
    """
    title = safe_str(rec.get("title")).strip()
    content = rec.get("content") or {}
    plain = safe_str(content.get("plain")).strip()
    text = safe_str(rec.get("text")).strip()

    # For sessions, hypothesis, provenance: use first meaningful sentence
    if role in ("session", "hypothesis", "provenance"):
        body = plain or text
        if body:
            # Extract first non-empty line that is not a markdown heading
            for line in body.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and len(line) > 20:
                    return line[:300]
        return f"{role.capitalize()}: {title}"

    # For reference: use title as summary (it IS the reference)
    if role == "reference":
        return f"Academic reference: {title}"

    # For algorithm: use title + first equation-like line
    if role == "algorithm":
        body = plain or text
        if body:
            for line in body.splitlines():
                line = line.strip()
                if line and len(line) > 10:
                    return line[:250]
        return f"Algorithm: {title}"

    # For policy/protocol/contract: use first substantive line
    if role in ("policy", "protocol", "contract", "schema"):
        body = plain or text
        if body:
            for line in body.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and len(line) > 15:
                    return line[:280]
        return f"{role.capitalize()}: {title}"

    # Default: first substantive sentence
    body = plain or text
    if body:
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                return line[:280]

    return title[:200] if title else ""


def build_retrieval_hints(rec: dict, role: str) -> dict:
    """
    Build retrieval_terms and retrieval_aliases.
    - retrieval_terms: canonical, normalized, deduplicated
    - retrieval_aliases: useful variants (accented vs non-accented, etc.)
    Returns {"retrieval_terms": [...], "retrieval_aliases": [...], "retrieval_hints": [...]}
    """
    seen_normalized = {}   # normalized_form -> canonical form
    terms = []
    aliases = []

    def add_term(word: str):
        """Add word as canonical term if not already seen."""
        w = word.strip()
        if not w or len(w) < 3 or w in STOP_WORDS:
            return
        norm = normalize_for_dedup(w)
        if norm not in seen_normalized:
            seen_normalized[norm] = w
            terms.append(w)

    def add_alias(word: str):
        """Add word as alias if it provides value beyond existing terms."""
        w = word.strip()
        if not w or len(w) < 3 or w in STOP_WORDS:
            return
        norm = normalize_for_dedup(w)
        if norm in seen_normalized:
            # Already have canonical; add as alias if different spelling
            canonical = seen_normalized[norm]
            if w.lower() != canonical.lower() and w not in aliases and w not in terms:
                aliases.append(w)
        else:
            # Not seen — treat as a new term
            seen_normalized[norm] = w
            terms.append(w)

    title = safe_str(rec.get("title")).strip()
    # Clean title: remove emoji, markdown syntax
    clean_title = strip_emoji(title)
    clean_title = re.sub(r"^#+\s*", "", clean_title)
    clean_title = re.sub(r"^-+\s*", "", clean_title)

    # Add meaningful words from title
    for word in re.findall(r"[^\W\d_]{3,}", clean_title, re.UNICODE):
        add_term(word.lower())

    # Session/hypothesis/provenance number as term
    m = re.search(r"sesión\s+(\d+)|sesion\s+(\d+)", title.lower())
    if m:
        num = m.group(1) or m.group(2)
        add_term(f"sesion-{num}")
        add_alias(f"sesión-{num}")

    # Tags as terms
    for tag in (rec.get("tags") or []):
        clean_tag = strip_emoji(safe_str(tag))
        clean_tag = re.sub(r"^#+\s*", "", clean_tag)
        for word in re.findall(r"[^\W\d_]{3,}", clean_tag, re.UNICODE):
            add_alias(word.lower())

    # normalized_tags
    for tag in (rec.get("normalized_tags") or []):
        for word in re.findall(r"[^\W\d_]{3,}", safe_str(tag), re.UNICODE):
            add_alias(word.lower())

    # taxonomy_path
    for path_part in (rec.get("taxonomy_path") or []):
        clean_p = strip_emoji(safe_str(path_part))
        for word in re.findall(r"[^\W\d_]{3,}", clean_p, re.UNICODE):
            add_alias(word.lower())

    # role as a term
    if role and role != "unclassified":
        add_term(role)

    # Limit output
    final_terms = [t for t in terms if len(t) >= 3][:15]
    final_aliases = [a for a in aliases if len(a) >= 3 and a not in final_terms][:10]

    return {
        "retrieval_terms": final_terms,
        "retrieval_aliases": final_aliases,
        "retrieval_hints": final_terms + final_aliases,  # combined for compatibility
    }


def compute_confidence(rec: dict, role: str, qflags: dict) -> int:
    """
    Confidence score 1–5 based on data completeness and role certainty.
    5 = high confidence in classification and data quality
    1 = very low confidence
    """
    score = 5

    # Role uncertainty
    if role == "unclassified":
        score -= 2
    elif role == "config":
        # config might be misclassified
        score -= 1

    # Data quality issues
    source_fields = rec.get("source_fields") or {}
    if "PENDIENTE" in safe_str(source_fields.get("tmap.id", "")):
        score -= 1
    if qflags.get("has_unknown_content_type"):
        score -= 1
    if qflags.get("has_empty_normalized_tags"):
        score -= 1
    if qflags.get("has_minimal_text"):
        score -= 1

    # taxonomy/section coverage bonus
    if rec.get("taxonomy_path"):
        score += 0  # already good
    else:
        score -= 1

    return max(1, min(5, score))


def classify_payload(rec: dict, role: str, target_tokens: int) -> dict:
    """
    Classify payload for chunking decisions and corpus eligibility.
    """
    ct = safe_str(rec.get("content_type"))
    text = safe_str(rec.get("text"))
    is_binary = rec.get("is_binary", False)
    token_est = estimate_tokens(text)
    corpus_policy = derive_corpus_policy(rec, role)

    chunkable_types = {
        "text/markdown", "text/vnd.tiddlywiki", "text/plain", "text/html",
    }
    binary_types = {
        "image/png", "image/jpeg", "image/gif", "image/svg+xml",
        "application/octet-stream",
    }

    is_textual_payload = (
        not is_binary
        and ct in chunkable_types
        and bool(text.strip())
    )
    is_large_payload = token_est > target_tokens
    is_chunkable_text = False

    if is_binary or ct in binary_types:
        strategy = "binary_skip"
        eligibility = "excluded"
        exclusion_reason = "binary_skip"
    elif ct == "application/json":
        strategy = "json_no_chunk"
        eligibility = "excluded"
        exclusion_reason = "json_no_chunk"
    elif corpus_policy["chunk_eligibility"] == "excluded":
        strategy = corpus_policy["chunk_exclusion_reason"]
        eligibility = corpus_policy["chunk_eligibility"]
        exclusion_reason = corpus_policy["chunk_exclusion_reason"]
    elif not is_textual_payload:
        strategy = "no_chunk_type"
        eligibility = "excluded"
        exclusion_reason = "no_chunk_type"
    elif token_est <= target_tokens:
        strategy = "no_chunk_small"
        eligibility = corpus_policy["chunk_eligibility"]
        exclusion_reason = None
        is_chunkable_text = True
    elif ct == "text/html":
        strategy = "html_defensive"
        eligibility = corpus_policy["chunk_eligibility"]
        exclusion_reason = None
        is_chunkable_text = True
    elif is_textual_payload:
        strategy = "structured_chunk"
        eligibility = corpus_policy["chunk_eligibility"]
        exclusion_reason = None
        is_chunkable_text = True
    else:
        strategy = "no_chunk_type"
        eligibility = "excluded"
        exclusion_reason = "no_chunk_type"

    return {
        "is_large_payload": is_large_payload,
        "is_textual_payload": is_textual_payload,
        "is_chunkable_text": is_chunkable_text,
        "chunk_strategy": strategy,
        "token_estimate": token_est,
        "corpus_state": corpus_policy["corpus_state"],
        "corpus_state_rule_id": corpus_policy["corpus_state_rule_id"],
        "chunk_eligibility": eligibility,
        "chunk_exclusion_reason": exclusion_reason,
    }


def normalize_relation_targets(relation_targets: list | None) -> list[dict]:
    """Return deterministic compact relation targets for AI projections."""
    normalized: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for rel in relation_targets or []:
        if isinstance(rel, dict):
            target = rel.get("target_id") or rel.get("target") or rel.get("id")
            rel_type = rel.get("type") or ""
            evidence = rel.get("evidence") or ""
        elif isinstance(rel, str):
            target = rel
            rel_type = ""
            evidence = ""
        else:
            continue
        if not target:
            continue
        key = (safe_str(rel_type), safe_str(target), safe_str(evidence))
        if key in seen:
            continue
        seen.add(key)
        compact = {"target_id": safe_str(target)}
        if rel_type:
            compact["type"] = safe_str(rel_type)
        if evidence:
            compact["evidence"] = safe_str(evidence)
        normalized.append(compact)
    return normalized


def relation_targets_from_relations(relations: list | None) -> list[dict]:
    """Derive compact relation_targets from canonical relations."""
    return normalize_relation_targets(relations)


def relation_targets_from_record(rec: dict) -> list[dict]:
    """Prefer existing relation_targets; fall back to canonical relations."""
    if isinstance(rec.get("relation_targets"), list):
        return normalize_relation_targets(rec.get("relation_targets"))
    return relation_targets_from_relations(rec.get("relations") or [])


def _canon_record_from_entry(entry) -> dict:
    if isinstance(entry, (tuple, list)) and entry:
        return entry[0]
    return entry


def build_relation_resolution_index(canon_records: list) -> dict:
    """Build a conservative target resolver for id, canonical_slug, key and title."""
    by_ref: dict[str, dict] = {}
    by_id: dict[str, dict] = {}

    def add_ref(ref: str, rec: dict) -> None:
        ref_s = safe_str(ref).strip()
        if not ref_s:
            return
        by_ref.setdefault(ref_s, rec)
        by_ref.setdefault(normalize_for_dedup(ref_s), rec)

    for entry in canon_records:
        rec = _canon_record_from_entry(entry)
        if not isinstance(rec, dict):
            continue
        rec_id = safe_str(rec.get("id")).strip()
        if rec_id:
            by_id[rec_id] = rec
            add_ref(rec_id, rec)
        for field in ("canonical_slug", "key", "title"):
            add_ref(rec.get(field), rec)

    return {
        "by_ref": by_ref,
        "by_id": by_id,
        "ids": set(by_id),
    }


def relation_target_ref(rel) -> str:
    if isinstance(rel, dict):
        return safe_str(rel.get("target_id") or rel.get("target") or rel.get("id")).strip()
    return safe_str(rel).strip()


def resolve_relation_target(target_or_rel, relation_index: dict | None) -> dict | None:
    if not relation_index:
        return None
    target = relation_target_ref(target_or_rel)
    if not target:
        return None
    if "by_ref" in relation_index:
        return (
            relation_index["by_ref"].get(target)
            or relation_index["by_ref"].get(normalize_for_dedup(target))
        )
    # Backward-compatible support for the old title->id map shape.
    if target in relation_index:
        return {"id": relation_index[target], "title": target}
    return None


def relation_type_category(rel_type: str) -> str:
    rtype = safe_str(rel_type).lower().strip() or "unknown"
    if rtype in SEMANTIC_RELATION_TYPES:
        return "semantic"
    if rtype in STRUCTURAL_RELATION_TYPES:
        return "structural"
    if rtype in TECHNICAL_RELATION_TYPES:
        return "technical"
    if rtype in GENERIC_RELATION_TYPES:
        return "generic"
    if rtype in DECORATIVE_RELATION_TYPES:
        return "decorative"
    return "unknown"


def relation_family(rec: dict, role: str | None = None, taxonomy: list | None = None) -> str:
    if isinstance(taxonomy, list) and taxonomy:
        return safe_str(taxonomy[0])[:160]
    taxonomy_path = rec.get("taxonomy_path")
    if isinstance(taxonomy_path, list) and taxonomy_path:
        return safe_str(taxonomy_path[0])[:160]
    for key in ("source_tags", "tags", "normalized_tags"):
        tags = rec.get(key)
        if not isinstance(tags, list):
            continue
        for tag in tags:
            tag_s = safe_str(tag)
            if tag_s.startswith(("session:", "topic:", "layer:", "core:", "channel:")):
                return tag_s[:160]
        for tag in tags:
            tag_s = safe_str(tag)
            if tag_s.startswith(("#", "##", "###", "####")):
                return tag_s[:160]
    return safe_str(role or rec.get("role_primary") or "unknown")


def relation_usefulness_rank(rel: dict) -> tuple[int, int]:
    category_rank = {
        "semantic": 0,
        "technical": 1,
        "structural": 2,
        "generic": 3,
        "decorative": 4,
        "unknown": 5,
    }
    source_rank = {
        "canonical_relation": 0,
        "content_embedded": 1,
    }
    category = relation_type_category(rel.get("type"))
    source = rel.get("relation_source") or rel.get("evidence") or ""
    return (category_rank.get(category, 5), source_rank.get(source, 2))


def _compact_controlled_relation(rel: dict) -> dict:
    compact = {"target_id": safe_str(rel.get("target_id"))}
    if rel.get("type"):
        compact["type"] = safe_str(rel.get("type")).lower().strip()
    if rel.get("evidence"):
        compact["evidence"] = safe_str(rel.get("evidence"))
    return compact


def validate_relations(relations: list, known_ids: set, relation_index: dict | None = None) -> tuple:
    """
    Validate relation targets against known node IDs.
    Returns (valid_relations, invalid_relations).
    """
    valid = []
    invalid = []
    for rel in (relations or []):
        target = rel.get("target_id") or rel.get("target") or ""
        if not target:
            invalid.append({
                "type": rel.get("type"),
                "target_id": target,
                "reason": "target_missing",
            })
            continue
        target_rec = resolve_relation_target(rel, relation_index) if relation_index else None
        if target_rec:
            resolved = dict(rel)
            resolved["target_id"] = target_rec.get("id")
            if target_rec.get("title"):
                resolved.setdefault("target_title", target_rec.get("title"))
            valid.append(resolved)
        elif target not in known_ids:
            invalid.append({
                "type": rel.get("type"),
                "target_id": target,
                "target_ref": target,
                "reason": "target_not_found",
            })
        else:
            valid.append(rel)
    return valid, invalid


def extract_embedded_content_rels(rec: dict, relation_index: dict) -> tuple[list[dict], int, int, list[dict]]:
    """
    Extract capa-2 semantic relations from the content.plain JSON payload.

    Returns (resolved_rels, stale_count, urn_count, invalid_rels) where resolved_rels is a
    list of dicts with keys type, target_id, target_title, evidence='content_embedded'.
    Only types in _EMBEDDED_RELATION_TYPES are extracted; canonical types
    (child_of, references) are intentionally excluded.
    Stale targets (not resolved by id/title/key/slug, not URN) increment stale_count.
    URN targets (urn:uuid:...) that don't resolve increment urn_count.
    """
    try:
        content = rec.get("content") or {}
        plain = content.get("plain") if isinstance(content, dict) else None
        if not plain:
            return [], 0, 0, []
        inner = json.loads(plain)
        raw_rels = inner.get("relations") or []
    except Exception:
        return [], 0, 0, []

    resolved = []
    stale = 0
    urn = 0
    invalid = []
    own_title = rec.get("title", "")

    for r in raw_rels:
        rtype = (r.get("type") or "").lower().strip()
        if rtype not in _EMBEDDED_RELATION_TYPES:
            continue
        target = (r.get("target") or r.get("target_id") or "").strip()
        if not target:
            continue
        if target == own_title:
            continue  # suppress self-references
        target_rec = resolve_relation_target(target, relation_index)
        if target_rec:
            resolved.append({
                "type": rtype,
                "target_id": target_rec.get("id"),
                "target_title": target_rec.get("title") or target,
                "evidence": "content_embedded",
            })
        elif target.startswith("urn:uuid:"):
            urn += 1
            invalid.append({
                "type": rtype,
                "target_id": target,
                "target_ref": target,
                "reason": "urn_target_not_found",
                "relation_source": "content_embedded",
                "source_id": rec.get("id"),
                "source_title": rec.get("title"),
            })
        else:
            stale += 1
            invalid.append({
                "type": rtype,
                "target_id": target,
                "target_ref": target,
                "reason": "target_not_found",
                "relation_source": "content_embedded",
                "source_id": rec.get("id"),
                "source_title": rec.get("title"),
            })

    return resolved, stale, urn, invalid


def build_controlled_chunk_relation_targets(
    source_rec: dict,
    valid_rels: list,
    embedded_rels: list,
    relation_index: dict,
    propagation_context: dict,
) -> tuple[list[dict], dict]:
    """Merge capa-1 and capa-2 relations for chunks under controlled_v1."""
    hub_target_ids = propagation_context.get("hub_target_ids", set())
    flags: set[str] = set()
    candidates: list[dict] = []
    event = {
        "source_id": source_rec.get("id"),
        "source_title": source_rec.get("title"),
        "source_canonical_slug": source_rec.get("canonical_slug"),
        "policy": RELATION_PROPAGATION_POLICY_VERSION,
        "input_relation_targets": 0,
        "resolved_relation_targets": 0,
        "relation_targets_after": 0,
        "stale_relation_targets_blocked": 0,
        "duplicate_relation_targets_collapsed": 0,
        "hub_targets_filtered": 0,
        "generic_relation_types_detected": Counter(),
        "generic_relation_types_filtered_or_flagged": 0,
        "relation_targets_capped": 0,
        "filtered_relation_samples": [],
    }

    merged_inputs = []
    for rel in valid_rels:
        merged_inputs.append((rel, "canonical_relation"))
    for rel in embedded_rels:
        merged_inputs.append((rel, "content_embedded"))

    for order, (rel, relation_source) in enumerate(merged_inputs):
        event["input_relation_targets"] += 1
        target_rec = resolve_relation_target(rel, relation_index)
        target_id = safe_str(rel.get("target_id") if isinstance(rel, dict) else "").strip()
        if not target_rec and target_id:
            target_rec = relation_index.get("by_id", {}).get(target_id)
        if not target_rec:
            event["stale_relation_targets_blocked"] += 1
            flags.add("stale_target_blocked")
            event["filtered_relation_samples"].append({
                "target_ref": relation_target_ref(rel),
                "reason": "target_not_found",
            })
            continue

        rel_type = safe_str(rel.get("type") if isinstance(rel, dict) else "").lower().strip()
        category = relation_type_category(rel_type)
        resolved_target_id = safe_str(target_rec.get("id")).strip()
        event["resolved_relation_targets"] += 1
        if rel_type in GENERIC_RELATION_TYPES:
            event["generic_relation_types_detected"][rel_type] += 1

        if resolved_target_id in hub_target_ids and category in {"generic", "structural"}:
            event["hub_targets_filtered"] += 1
            if rel_type in GENERIC_RELATION_TYPES:
                event["generic_relation_types_filtered_or_flagged"] += 1
            flags.add("hub_target_filtered")
            event["filtered_relation_samples"].append({
                "target_id": resolved_target_id,
                "target_title": target_rec.get("title"),
                "type": rel_type,
                "reason": "generic_or_structural_hub",
            })
            continue

        if rel_type in GENERIC_RELATION_TYPES:
            event["generic_relation_types_filtered_or_flagged"] += 1
            flags.add("generic_relation_type_flagged")

        candidate = {
            "target_id": resolved_target_id,
            "target_title": target_rec.get("title"),
            "type": rel_type,
            "evidence": (
                safe_str(rel.get("evidence")).strip()
                if isinstance(rel, dict) and rel.get("evidence")
                else relation_source
            ),
            "relation_source": relation_source,
            "_order": order,
        }
        candidates.append(candidate)

    by_target: dict[str, dict] = {}
    for candidate in candidates:
        target_id = candidate["target_id"]
        previous = by_target.get(target_id)
        if previous is None:
            by_target[target_id] = candidate
            continue
        event["duplicate_relation_targets_collapsed"] += 1
        flags.add("duplicate_relation_target_collapsed")
        if (
            relation_usefulness_rank(candidate),
            candidate["_order"],
        ) < (
            relation_usefulness_rank(previous),
            previous["_order"],
        ):
            by_target[target_id] = candidate

    ordered = sorted(
        by_target.values(),
        key=lambda rel: (relation_usefulness_rank(rel), rel["_order"]),
    )
    if len(ordered) > MAX_RELATION_TARGETS_PER_CHUNK:
        event["relation_targets_capped"] = len(ordered) - MAX_RELATION_TARGETS_PER_CHUNK
        flags.add("relation_target_limit_applied")
        ordered = ordered[:MAX_RELATION_TARGETS_PER_CHUNK]

    relation_targets = [_compact_controlled_relation(rel) for rel in ordered]
    event["relation_targets_after"] = len(relation_targets)
    event["generic_relation_types_detected"] = dict(event["generic_relation_types_detected"])
    event["relation_quality_flags"] = sorted(flags)
    return relation_targets, event


def chunk_node(
    rec: dict,
    node_id: str,
    shard_file: str,
    line_num: int,
    role: str,
    taxonomy: list,
    section: list,
    retrieval_hints: list,
    payload_info: dict,
    target_tokens: int,
    max_tokens: int,
    relation_targets: list | None = None,
    relation_propagation_meta: dict | None = None,
) -> tuple:
    """
    Chunk a node using hierarchical strategy.
    Returns (chunks: list, fallback_used: bool, exclusion_reason: str or None)
    """
    strategy = payload_info["chunk_strategy"]
    text = safe_str(rec.get("text")).strip()
    title = safe_str(rec.get("title"))
    source_anchor = {
        "canon_id": node_id,
        "shard_file": shard_file,
        "shard_line": line_num,
        "source_position": rec.get("source_position"),
    }

    # Non-chunkable cases
    if strategy in (
        "binary_skip",
        "no_chunk_type",
        "archival_only",
        "archival_only_skip",
        "historical_snapshot",
        "historical_out_artifact_skip",
    ):
        return [], False, strategy
    if strategy == "json_no_chunk":
        return [], False, "json_payload_no_chunk"
    if strategy == "no_chunk_small":
        return [], False, None  # small enough, no chunk needed

    if not text:
        return [], False, "empty_text"

    # HTML: defensive chunk (extract text content, then chunk)
    if strategy == "html_defensive":
        # Strip HTML tags for chunking
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean or estimate_tokens(clean) <= target_tokens:
            return [], False, "html_small_after_strip"
        chunks_text = split_structurally(clean, title, role, target_tokens, max_tokens)
    elif strategy == "structured_chunk":
        chunks_text = split_structurally(text, title, role, target_tokens, max_tokens)
    else:
        return [], False, "no_chunk_strategy_matched"

    # Validate all chunks are within hard max
    fallback_used = False
    validated = []
    for ct in chunks_text:
        tok = estimate_tokens(ct)
        if tok > max_tokens:
            # Emergency hard split
            for part in hard_split(ct, max_tokens):
                validated.append(part)
            fallback_used = True
        else:
            validated.append(ct)

    validated = densify_microchunks(validated, target_tokens)
    compact_relation_targets = (
        normalize_relation_targets(relation_targets)
        if relation_targets is not None
        else relation_targets_from_record(rec)
    )
    propagation_meta = relation_propagation_meta or {}
    relation_quality_flags = list(propagation_meta.get("relation_quality_flags") or [])

    # Build chunk records
    chunks = []
    for idx, chunk_text in enumerate(validated):
        tok = estimate_tokens(chunk_text)
        chunks.append({
            "chunk_id": f"{node_id}::chunk:{idx}",
            "source_id": node_id,
            "source_title": title,
            "source_canonical_slug": rec.get("canonical_slug"),
            "tiddler_id": node_id,
            "node_id": node_id,
            "title": title,
            "role_primary": role,
            "chunk_index": idx,
            "chunk_total": len(validated),
            "chunk_heading": extract_chunk_heading(chunk_text, section, title),
            "text": chunk_text,
            "token_estimate": tok,
            "within_target": tok <= target_tokens,
            "within_hard_max": tok <= max_tokens,
            "derivation_method": strategy,
            "fallback": fallback_used,
            "content_type": rec.get("content_type"),
            "document_id": rec.get("document_id"),
            "section_path": section,
            "taxonomy_path": taxonomy,
            "retrieval_hints": retrieval_hints[:8],
            "relation_targets": list(compact_relation_targets),
            "relation_count": len(compact_relation_targets),
            "relation_target_count": len(compact_relation_targets),
            "corpus_state": payload_info["corpus_state"],
            "corpus_state_rule_id": payload_info["corpus_state_rule_id"],
            "chunk_eligibility": payload_info["chunk_eligibility"],
            "source_anchor": source_anchor,
            "source_position": rec.get("source_position"),
            "source_version_id": rec.get("version_id"),
        })
        if propagation_meta:
            chunks[-1].update({
                "relation_propagation_policy": RELATION_PROPAGATION_POLICY_VERSION,
                "relation_propagation_source": "source_tiddler",
                "relation_quality_flags": relation_quality_flags,
            })

    return chunks, fallback_used, None


def _is_foundational(rec: dict, role: str) -> bool:
    """Foundational = high-level structural node."""
    title = safe_str(rec.get("title"))
    if role in ("protocol", "policy", "architecture", "schema", "readme"):
        return True
    if title.startswith("## ") or title.startswith("# "):
        return True
    sp = rec.get("section_path") or []
    if len(sp) == 1:
        return True
    return False


def build_ai_record(rec: dict, shard_file: str, line_num: int,
                     role: str, taxonomy: list, section: list,
                     known_ids: set, relation_index: dict,
                     target_tokens: int, max_tokens: int,
                     propagation_context: dict | None = None,
                     rag_projection: dict | None = None) -> tuple:
    """
    Build AI-friendly record and optional chunks.
    Returns (ai_record, chunks, invalid_relations, payload_info)
    """
    text = safe_str(rec.get("text"))
    token_est = estimate_tokens(text)
    qflags = compute_quality_flags(rec)
    node_id = rec.get("id")
    canon_role = rec.get("role_primary")
    role_check = classify_role_primary_value(canon_role, CANON_POLICY_BUNDLE)

    if rag_projection is not None:
        safe_hints = list(rag_projection.get("retrieval_hints") or [])
        hints = {
            "retrieval_terms": safe_hints,
            "retrieval_aliases": [],
            "retrieval_hints": safe_hints,
        }
    else:
        hints = build_retrieval_hints(rec, role)
    payload_info = classify_payload(rec, role, target_tokens)
    role_source = "canon_contract_inherited" if role_check.get("canonical_role") == role else "s52_classifier"

    # Validate capa-1 relations (top-level)
    raw_rels = rec.get("relations") or []
    valid_rels, invalid_rels = validate_relations(raw_rels, known_ids, relation_index)
    for invalid_rel in invalid_rels:
        invalid_rel.setdefault("relation_source", "canonical_relation")
        invalid_rel.setdefault("source_id", node_id)
        invalid_rel.setdefault("source_title", rec.get("title"))

    # Compact relation targets (capa-1 plus any content_embedded relations
    # already materialized in the canonical top-level relations field).
    rel_targets = relation_targets_from_relations(valid_rels)

    # S84: extract capa-2 embedded relations from content.plain
    embedded_rels, _stale, _urn, embedded_invalid_rels = extract_embedded_content_rels(
        rec,
        relation_index,
    )
    invalid_rels.extend(embedded_invalid_rels)

    chunk_relation_targets = rel_targets
    relation_propagation_event = {
        "source_id": node_id,
        "source_title": rec.get("title"),
        "source_canonical_slug": rec.get("canonical_slug"),
        "policy": "legacy_capa1_passthrough",
        "input_relation_targets": len(rel_targets),
        "resolved_relation_targets": len(rel_targets),
        "relation_targets_after": len(rel_targets),
        "stale_relation_targets_blocked": len(invalid_rels),
        "duplicate_relation_targets_collapsed": 0,
        "hub_targets_filtered": 0,
        "generic_relation_types_detected": {},
        "generic_relation_types_filtered_or_flagged": 0,
        "relation_targets_capped": 0,
        "relation_quality_flags": [],
        "filtered_relation_samples": [],
    }
    if propagation_context is not None:
        chunk_relation_targets, relation_propagation_event = build_controlled_chunk_relation_targets(
            rec,
            valid_rels,
            embedded_rels,
            relation_index,
            propagation_context,
        )
        relation_propagation_event["stale_relation_targets_blocked"] += len(invalid_rels)
        if invalid_rels:
            flags = set(relation_propagation_event.get("relation_quality_flags") or [])
            flags.add("stale_target_blocked")
            relation_propagation_event["relation_quality_flags"] = sorted(flags)

    ai_rec = {
        "id": node_id,
        "node_id": node_id,
        # Keep the canonical revision explicit in every derivative family.
        # It is provenance, not a semantic reinterpretation by the writer.
        "version_id": rec.get("version_id"),
        "title": rec.get("title"),
        "canon_role_primary": canon_role,
        "role_primary": role,
        "role_primary_source": role_source,
        "role_primary_contract_verdict": role_check["verdict"],
        "role_primary_contract_canonical": role_check.get("canonical_role"),
        "secondary_roles": build_secondary_roles(rec, role),
        # Three distinct text fields
        "preview_text": compute_preview_text(rec),
        "semantic_text": (
            rag_projection.get("semantic_text", "")
            if rag_projection is not None
            else compute_semantic_text(rec)
        ),
        "ai_summary": compute_ai_summary(rec, role),
        # Retrieval
        "retrieval_terms": hints["retrieval_terms"],
        "retrieval_aliases": hints["retrieval_aliases"],
        "retrieval_hints": hints["retrieval_hints"],
        # Relations: capa-1 (authoritative) and capa-2 embedded (S84)
        "relation_targets": rel_targets,
        "embedded_relations": embedded_rels,
        # Source anchor
        "source_anchor": {
            "canon_id": node_id,
            "shard_file": shard_file,
            "shard_line": line_num,
            "source_position": rec.get("source_position"),
        },
        # Quality and classification signals
        "quality_flags": qflags,
        "confidence": compute_confidence(rec, role, qflags),
        "is_reference_only": compute_is_reference_only(rec, role),
        "is_foundational": _is_foundational(rec, role),
        # Payload signals
        "is_large_payload": payload_info["is_large_payload"],
        "is_textual_payload": payload_info["is_textual_payload"],
        "is_chunkable_text": payload_info["is_chunkable_text"],
        "chunk_eligibility": payload_info["chunk_eligibility"],
        "chunk_exclusion_reason": payload_info["chunk_exclusion_reason"],
        "corpus_state": payload_info["corpus_state"],
        "corpus_state_rule_id": payload_info["corpus_state_rule_id"],
        "chunk_strategy": payload_info["chunk_strategy"],
        "token_estimate": token_est,
        # Structure
        "document_id": rec.get("document_id"),
        "section_path": section,
        "taxonomy_path": taxonomy,
        "content_type": rec.get("content_type"),
        "derivation": {
            "session": SESSION,
            "method": "projection_v2",
            "role_source": role_source,
            "corpus_state_rule_id": payload_info["corpus_state_rule_id"],
            "governance_policy_ref": CANON_POLICY_BUNDLE_REL,
        },
    }
    # Do not alter the historical productive schema when this reusable builder
    # is called without a projection.  The preview receives only tags already
    # permitted by the authoritative semantic builder, never its free-form
    # retrieval hints.
    if rag_projection is not None:
        embedding_metadata = dict(rag_projection.get("embedding_metadata") or {})
        ai_rec["embedding_metadata"] = embedding_metadata
        ai_rec["rag_safe_tags"] = list(embedding_metadata.get("rag_allowed_tags") or [])
        ai_rec["derivation"]["semantic_builder"] = "semantic_text_builder.py"

    # Generate chunks
    chunks = []
    if payload_info["is_chunkable_text"] and token_est > target_tokens:
        chunks, _, _ = chunk_node(
            rec,
            node_id,
            shard_file,
            line_num,
            role,
            taxonomy,
            section,
            hints["retrieval_hints"],
            payload_info,
            target_tokens,
            max_tokens,
            relation_targets=chunk_relation_targets,
            relation_propagation_meta=relation_propagation_event,
        )

    return ai_rec, chunks, invalid_rels, payload_info, relation_propagation_event
