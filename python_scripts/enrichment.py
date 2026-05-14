"""
enrichment.py — Enriched record builder extracted from derive_layers.py (Fase D, S0113).

Contains build_enriched_record() and the helper functions it requires.
All helper functions here are also re-exported via derive_layers.py so that
build_ai_record() and other callers continue to work unchanged.

Dependency chain (no circular imports):
  corpus_governance → (no local deps)
  text_utils        → (no local deps)
  enrichment        → corpus_governance, text_utils
  derive_layers     → enrichment (and others)
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python_scripts"))

from corpus_governance import (
    CANON_POLICY_BUNDLE_REL,
    classify_role_primary_value,
    load_canon_policy_bundle,
    resolve_corpus_policy,
)
from text_utils import estimate_tokens, safe_str

# Loaded once at import time — same data file as derive_layers.py loads.
CANON_POLICY_BUNDLE = load_canon_policy_bundle()

# Derivation session tag — must stay in sync with derive_layers.SESSION.
SESSION = "S55"


# ── Text field computation ─────────────────────────────────────────────────────

def compute_preview_text(rec: dict, max_chars: int = 400) -> str:
    """
    preview_text: deterministic head-tail preview of the content.
    Not a summary — literally the beginning (and end if long) of the text.
    """
    text = safe_str(rec.get("text"))
    if not text:
        content = rec.get("content") or {}
        text = safe_str(content.get("plain"))
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2].strip()
    tail = text[-(max_chars // 2) :].strip()
    return head + " … " + tail


def compute_semantic_text(rec: dict, max_chars: int = 600) -> str:
    """
    semantic_text: the most semantically useful text fragment for this node.
    Uses content.plain preferentially; falls back to text.
    This is usable base text for AI indexing — not a summary.
    """
    existing = rec.get("semantic_text")
    if isinstance(existing, str):
        existing = existing.strip()
        if existing:
            return existing

    content = rec.get("content") or {}
    plain = safe_str(content.get("plain")).strip()
    if plain:
        if len(plain) <= max_chars:
            return plain
        # Try to end at sentence boundary
        truncated = plain[:max_chars]
        for sep in (". ", ".\n", "! ", "? "):
            pos = truncated.rfind(sep)
            if pos > max_chars * 0.5:
                return truncated[: pos + 1].strip()
        return truncated.rstrip() + "…"
    text = safe_str(rec.get("text")).strip()
    if text:
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        for sep in (". ", ".\n", "! ", "? "):
            pos = truncated.rfind(sep)
            if pos > max_chars * 0.5:
                return truncated[: pos + 1].strip()
        return truncated.rstrip() + "…"
    return ""


# ── Secondary roles ────────────────────────────────────────────────────────────

def build_secondary_roles(rec: dict, role: str) -> list:
    """
    Derive secondary_roles with deduplication and maximum of 4.
    Must not be a semantic garbage dump.
    """
    existing = rec.get("roles_secondary")
    if isinstance(existing, list):
        seen = {role}
        final = []
        for item in existing:
            val = safe_str(item).strip()
            if not val or val in seen or len(final) >= 4:
                continue
            seen.add(val)
            final.append(val)
        if final:
            return final

    roles = []
    title_lower = safe_str(rec.get("title")).lower()
    tags_lower = [safe_str(t).lower() for t in (rec.get("tags") or [])]
    tags_joined = " ".join(tags_lower)
    ct = safe_str(rec.get("content_type"))

    # Cross-cutting secondary roles
    if "hipótesis" in tags_joined or "hipotesis" in tags_joined:
        if role != "hypothesis":
            roles.append("hypothesis")
    if "procedencia" in tags_joined:
        if role != "provenance":
            roles.append("provenance")
    if "sesion" in tags_joined or "sesión" in tags_joined:
        if role != "session":
            roles.append("session")
    if "protocolo" in tags_joined:
        if role != "protocol":
            roles.append("protocol")

    # Content-type based
    if ct == "application/json" and role not in ("config", "manifest", "schema"):
        roles.append("config")
    if ct in ("image/png", "image/jpeg") and role != "asset":
        roles.append("asset")

    # Title-based
    if "readme" in title_lower and role != "readme":
        roles.append("readme")

    # Deduplicate, remove primary role, cap at 4
    seen = {role}
    final = []
    for r in roles:
        if r not in seen and len(final) < 4:
            seen.add(r)
            final.append(r)
    return final


# ── Quality flags ──────────────────────────────────────────────────────────────

def compute_quality_flags(rec: dict) -> dict:
    flags = {}
    source_fields = rec.get("source_fields") or {}
    if "PENDIENTE" in safe_str(source_fields.get("tmap.id", "")):
        flags["has_pendiente_tmap_id"] = True
    if rec.get("content_type") == "unknown":
        flags["has_unknown_content_type"] = True
    if not rec.get("normalized_tags"):
        flags["has_empty_normalized_tags"] = True
    text = safe_str(rec.get("text"))
    if len(text.strip()) < 10:
        flags["has_minimal_text"] = True
    content = rec.get("content") or {}
    if not content.get("plain") and len(text.strip()) < 10:
        flags["has_empty_content"] = True
    return flags


# ── is_reference_only ──────────────────────────────────────────────────────────

def compute_is_reference_only(rec: dict, role: str) -> bool:
    """
    True only if the node genuinely contains just a link/reference and no
    substantive text payload.
    """
    text = safe_str(rec.get("text")).strip()
    content = rec.get("content") or {}
    plain = safe_str(content.get("plain")).strip()
    # If text is very short and role is reference → reference_only
    if role == "reference" and len(text) < 80 and len(plain) < 80:
        return True
    # If node has no text at all
    if not text and not plain:
        return True
    return False


# ── Corpus policy ──────────────────────────────────────────────────────────────

def derive_corpus_policy(rec: dict, role: str) -> dict:
    """Assign corpus state and chunking policy from governed machine rules."""
    del role  # corpus_state currently depends on governed source evidence, not role
    return resolve_corpus_policy(rec, CANON_POLICY_BUNDLE)


# ── Enriched record builder ────────────────────────────────────────────────────

def build_enriched_record(rec: dict, shard_file: str, line_num: int,
                           role: str, taxonomy: list, section: list) -> dict:
    text = safe_str(rec.get("text"))
    content = rec.get("content") or {}
    token_est = estimate_tokens(text)
    qflags = compute_quality_flags(rec)
    corpus_policy = derive_corpus_policy(rec, role)
    role_check = classify_role_primary_value(rec.get("role_primary"), CANON_POLICY_BUNDLE)

    ct = safe_str(rec.get("content_type"))
    is_prose = ct in ("text/markdown", "text/vnd.tiddlywiki", "text/plain")

    enriched = {
        # Copied deterministic fields
        "id": rec.get("id"),
        "title": rec.get("title"),
        "canon_role_primary": rec.get("role_primary"),
        "role_primary": role,
        "role_primary_contract_verdict": role_check["verdict"],
        "role_primary_contract_canonical": role_check.get("canonical_role"),
        "text": text,
        "content_type": ct,
        "source_type": rec.get("source_type"),
        "source_fields": rec.get("source_fields"),
        "source_tags": rec.get("source_tags"),
        "normalized_tags": rec.get("normalized_tags"),
        "source_ref": rec.get("raw_payload_ref"),
        "relations": rec.get("relations"),
        "document_id": rec.get("document_id"),
        "section_path": section,
        "taxonomy_path": taxonomy,
        "order_in_document": rec.get("order_in_document"),
        "tags": rec.get("tags"),
        "schema_version": rec.get("schema_version"),
        "key": rec.get("key"),
        "canonical_slug": rec.get("canonical_slug"),
        "version_id": rec.get("version_id"),
        "modality": rec.get("modality"),
        "encoding": rec.get("encoding"),
        "is_binary": rec.get("is_binary"),
        "is_reference_only": compute_is_reference_only(rec, role),
        "mime_type": rec.get("mime_type"),
        "source_position": rec.get("source_position"),
        "created": rec.get("created"),
        "modified": rec.get("modified"),
        "corpus_state": corpus_policy["corpus_state"],
        "chunk_eligibility": corpus_policy["chunk_eligibility"],
        "chunk_exclusion_reason": corpus_policy["chunk_exclusion_reason"],
        "corpus_state_rule_id": corpus_policy["corpus_state_rule_id"],
        # Derived deterministic fields
        "preview_text": compute_preview_text(rec),
        "semantic_text": compute_semantic_text(rec),
        "content": {
            "plain": safe_str(content.get("plain")),
            "markdown": text if is_prose else None,
        },
        "size_metrics": {
            "text_length": len(text),
            "content_plain_length": len(safe_str(content.get("plain"))),
            "token_estimate": token_est,
        },
        # Heuristic fields (marked)
        "secondary_roles": build_secondary_roles(rec, role),
        "quality_flags": qflags,
        "readability": "prose" if is_prose else "structured",
        # Derivation traceability
        "derivation": {
            "session": SESSION,
            "source_shard": shard_file,
            "source_line": line_num,
            "role_source": "canon_contract_inherited" if role_check.get("canonical_role") == role else "s52_classifier",
            "role_contract_ref": CANON_POLICY_BUNDLE_REL + "#role_primary_contract",
            "taxonomy_source": "s52_derived" if not rec.get("taxonomy_path") else "canon_inherited",
            "corpus_state_rule_id": corpus_policy["corpus_state_rule_id"],
            "governance_policy_ref": CANON_POLICY_BUNDLE_REL,
        },
    }
    return enriched
