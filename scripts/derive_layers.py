#!/usr/bin/env python3
"""
derive_layers.py — Stable entrypoint for local derivation (S46+).

Reads canon shards (out/tiddlers_*.jsonl) and produces:
  - out/enriched/tiddlers_enriched_{N}.jsonl  (Capa A: Enriched Canonical Export)
  - out/ai/tiddlers_ai_{N}.jsonl              (Capa B: AI-friendly Projection)
  - out/ai/chunks_ai_{N}.jsonl                (Capa B: Chunks)
  - out/enriched/manifest.json
  - out/ai/manifest.json
  - out/ai/reports/classification_report.json
  - out/ai/reports/chunk_qc_report.json
  - out/ai/reports/retrieval_qc_report.json
  - out/ai/reports/relations_qc_report.json
  - out/ai/reports/derivation_report.json

Hardening principles (S46):
  - 100% shard-aware: no monolithic input, no hardcoded shard count
  - Controlled vocabulary for role_primary (26 types)
  - Hierarchical chunker with hard max guardrail
  - Retrieval hints: normalized dedup, split into terms + aliases
  - Relations validated against known node IDs
  - Three distinct text fields: preview_text, semantic_text, ai_summary
  - Deterministic: no fabrication, no metadata invention
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── Derivation session identifier ────────────────────────────────────────────
SESSION = "S46"
SCHEMA_VERSION = "v1"

# ── Default configuration ─────────────────────────────────────────────────────
DEFAULT_ENRICHED_SHARD_SIZE = 100
DEFAULT_AI_SHARD_SIZE = 100
DEFAULT_CHUNK_SHARD_SIZE = 200
DEFAULT_CHUNK_TARGET_TOKENS = 1800
DEFAULT_CHUNK_MAX_TOKENS = 4000   # hard max — no chunk may exceed this
DEFAULT_TIDDLER_SHARD_SIZE = 100
DEFAULT_CHUNK_SHARD_SIZE_ARG = 200

# ── Controlled vocabulary for role_primary ────────────────────────────────────
VALID_ROLES = {
    "session", "hypothesis", "provenance", "protocol", "contract",
    "policy", "schema", "report", "reference", "glossary", "dictionary",
    "architecture", "component", "requirements", "objective", "dofa",
    "algorithm", "code_source", "test_fixture", "dataset", "manifest",
    "html_artifact", "readme", "config", "asset", "unclassified",
}

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

# ── Helpers ────────────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for mixed content."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def safe_str(val) -> str:
    return "" if val is None else str(val)


def normalize_for_dedup(s: str) -> str:
    """Normalize string for deduplication: lowercase + remove accents."""
    s = s.lower().strip()
    # Remove accents
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def strip_emoji(s: str) -> str:
    """Remove emoji characters from a string."""
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001FFFF"
        "\U00002600-\U000027BF"
        "\U0000FE00-\U0000FE0F"
        "\u200d"
        "\u20E3"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", s).strip()


# ── Semantic classifier ────────────────────────────────────────────────────────

def classify_role(rec: dict) -> str:
    """
    Classify role_primary using controlled vocabulary.
    Uses title, tags, section_path, content_type, and source fields.
    """
    title = safe_str(rec.get("title"))
    title_lower = title.lower()
    title_stripped = strip_emoji(title).lower()
    ct = safe_str(rec.get("content_type"))
    section_path = rec.get("section_path") or []
    sp_joined = " ".join(safe_str(s).lower() for s in section_path)
    tags = rec.get("tags") or []
    tags_lower = [safe_str(t).lower() for t in tags]
    tags_joined = " ".join(tags_lower)
    source_fields = rec.get("source_fields") or {}
    source_tags_raw = safe_str(source_fields.get("tags", "")).lower()

    # Helper: check any of these patterns appear in text
    def match_any(text, patterns):
        return any(p in text for p in patterns)

    # ── Session tiddlers ──
    # "#### 🌀 Sesión NN = ..."
    if re.match(r"####\s+[🌀 ]+sesión\s+\d+", title_lower):
        # Check if it's NOT hypothesis or provenance
        if "hipótesis" not in title_lower and "hipotesis" not in title_lower and "procedencia" not in title_lower:
            return "session"

    # "#### 🌀🧪 Hipótesis de sesión NN = ..."
    if re.search(r"(hipótesis|hipotesis)\s+de\s+sesión", title_lower):
        return "hypothesis"
    if match_any(title_lower, ["🧪 hipótesis de sesión", "🧪 hipotesis de sesion"]):
        return "hypothesis"

    # "#### 🌀🧾 Procedencia de sesión NN"
    if "procedencia de sesión" in title_lower or "procedencia de sesion" in title_lower:
        return "provenance"
    if "🧾 procedencia de sesión" in title_lower or "🧾 procedencia" in title_lower:
        return "provenance"

    # ── Dependency tiddlers ──
    if "hipótesis de dependencias" in title_lower or "hipotesis de dependencias" in title_lower:
        return "hypothesis"
    if "procedencia de dependencias" in title_lower:
        return "provenance"
    if "política de dependencias" in title_lower or "politica de dependencias" in title_lower:
        return "policy"
    if "registro de dependencias" in title_lower:
        return "report"

    # ── Protocol ──
    if "protocolo de sesión" in title_lower or "protocolo" in title_stripped:
        if "🧭" in title or "protocolo" in title_lower:
            return "protocol"

    # ── Glossary / Dictionary ──
    if "glosario" in title_lower:
        return "glossary"
    if "diccionario" in title_lower:
        return "dictionary"

    # ── Hypothesis tiddlers (structural) ──
    if re.match(r"##\s+🧪", title) or title_lower.strip().startswith("## 🧪"):
        return "hypothesis"
    if "hipótesis" in title_lower and title.startswith("##"):
        return "hypothesis"
    if "hipótesis inicial" in title_lower or "hipotesis inicial" in title_lower:
        return "hypothesis"

    # ── Provenance (structural) ──
    if "procedencia epistemológica" in title_lower or "procedencia epistemologica" in title_lower:
        return "provenance"
    if "procedencia inicial" in title_lower:
        return "provenance"

    # ── Policy ──
    if "política de memoria" in title_lower or "politica de memoria" in title_lower:
        return "policy"
    if "principios de gestion" in title_lower or "principios de gestión" in title_lower:
        return "policy"
    if "buen gusto" in title_lower:
        return "policy"
    if "calidad de referencias" in title_lower:
        return "policy"
    if "reglas de relaciones" in title_lower:
        return "policy"
    if "usabilidad y robustez" in title_lower:
        return "policy"
    if "complejidad esencial" in title_lower:
        return "policy"
    if "modularidad y estado" in title_lower:
        return "policy"
    if "diseño" in title_lower and title.startswith("## "):
        return "policy"

    # ── Architecture ──
    if "arquitectura" in title_lower:
        return "architecture"

    # ── Components / Elements ──
    if "elementos específicos" in title_lower or "elementos especificos" in title_lower:
        return "component"

    # ── Objective ──
    if re.search(r"(objetivos|objetivo)", title_lower) and "🎯" in title:
        return "objective"

    # ── Requirements ──
    if "requisitos" in title_lower and title.startswith("###"):
        return "requirements"

    # ── DOFA ──
    if "dofa" in title_lower:
        return "dofa"

    # ── Canon role inheritance ──
    # Preserve explicit canon typing for concrete nodes once structural
    # session/protocol roles have had a chance to resolve.
    existing = rec.get("role_primary")
    if existing in VALID_ROLES and existing != "unclassified":
        return existing

    # ── Algorithm ──
    if "algoritmos" in title_lower or "matematicas" in title_lower or "matemáticas" in title_lower:
        return "algorithm"
    # Algorithm equations by pattern
    if re.search(r"(algorithm|equation|momentum|continuity|modality)", title_lower):
        return "algorithm"

    # ── Contract ──
    if "contratos/" in title_lower or title_lower.startswith("contratos/"):
        return "contract"
    if re.search(r"m\d+-s\d+-.+-contract", title_lower):
        return "contract"
    if re.search(r"m\d+-s\d+", title_lower) and title_lower.endswith((".json", ".md", ".md.json")):
        return "contract"

    # ── Report ──
    if "report" in title_lower or "reporte" in title_lower:
        return "report"
    if "audit" in title_lower and "session" not in title_lower:
        return "report"

    # ── Schema ──
    if "schema" in title_lower and "canon" in title_lower:
        return "schema"
    if title_lower.startswith("esquemas/") or "esquemas/" in title_lower:
        return "schema"

    # ── Reference (academic papers) ──
    # Pattern: "NN. Some Title" typical of paper lists (both "01. Title" and "08. ¿Puede...")
    if re.match(r"^\d{2}\.\s+", title):
        return "reference"
    if re.search(r"(self-referential|learning module|semantic|knowledge graph|provenance|ecosystem|annotation)", title_lower):
        return "reference"

    # ── README ──
    if "readme" in title_lower or title.lower().endswith("readme.md"):
        return "readme"

    # ── Manifest ──
    if "manifest" in title_lower:
        return "manifest"

    # ── HTML artifact ──
    if ct == "text/html" or title_lower.endswith(".html") or title_lower.endswith(".derived.html"):
        return "html_artifact"

    # ── Test fixture: Go test files or fixture paths ──
    if title_lower.endswith("_test.go") or "tests/" in title_lower or "fixture" in title_lower:
        return "test_fixture"

    # ── Code source: Go, Rust, Python, shell source files ──
    if re.search(r"\.(go|rs|py|sh|ts|js)$", title_lower):
        if not title_lower.endswith("_test.go") and "test" not in title_lower.rsplit("/", 1)[-1]:
            return "code_source"

    # ── Config: YAML, TOML, env, gitignore, CI files ──
    if re.search(r"\.(ya?ml|toml|ini|env|cfg|conf)$", title_lower):
        return "config"
    if title_lower in (".gitignore", "gitignore", ".gitattributes"):
        return "config"
    if "workflows/" in title_lower or "github/workflows" in title_lower:
        return "config"

    # ── Policy: instruction files ──
    if "instructions/" in title_lower and title_lower.endswith(".md"):
        return "policy"

    # ── Dataset / data files ──
    if title_lower.endswith(".txt") and "data" in title_lower:
        return "dataset"
    if title_lower.endswith(".csv"):
        return "dataset"

    # ── Manifest for structure files ──
    if title_lower in ("estructura.txt", "scripts.txt", "contratos.txt"):
        return "manifest"

    # ── Documentation stubs: "-- Emoji.md" pattern ──
    if re.match(r"^--\s+", title) and title.endswith(".md"):
        # These are markdown stubs documenting structural tiddlers
        return "policy"

    # ── Draft tiddlers ──
    if title_lower.startswith("draft of"):
        # Extract session type from the title
        inner = title_lower.replace("draft of '", "").replace("'", "")
        if "sesión" in inner or "sesion" in inner:
            return "session"
        if "hipótesis" in inner or "hipotesis" in inner:
            return "hypothesis"
        if "procedencia" in inner:
            return "provenance"
        return "session"  # default for drafts

    # ── Asset (binary / image) ──
    if rec.get("is_binary") or ct in ("image/png", "image/jpeg", "image/gif", "image/svg+xml",
                                       "application/octet-stream"):
        return "asset"

    # ── Default ──
    return "unclassified"


def derive_taxonomy_and_section(rec: dict) -> tuple:
    """
    Improve taxonomy_path and section_path where deterministically derivable.
    Returns (taxonomy_path, section_path) lists.
    """
    title = safe_str(rec.get("title"))
    title_lower = title.lower()
    existing_tp = rec.get("taxonomy_path") or []
    existing_sp = rec.get("section_path") or []
    role = rec.get("_derived_role") or classify_role(rec)

    taxonomy = list(existing_tp) if existing_tp else []
    section = list(existing_sp) if existing_sp else []

    # Derive taxonomy from role when missing
    if not taxonomy:
        role_to_taxonomy = {
            "session": ["project/sessions"],
            "hypothesis": ["project/sessions/hypothesis"],
            "provenance": ["project/sessions/provenance"],
            "protocol": ["project/governance/protocol"],
            "contract": ["project/governance/contract"],
            "policy": ["project/governance/policy"],
            "schema": ["project/governance/schema"],
            "report": ["project/operations/report"],
            "reference": ["project/docs/reference"],
            "glossary": ["project/docs/glossary"],
            "dictionary": ["project/docs/dictionary"],
            "architecture": ["project/architecture"],
            "component": ["project/architecture/component"],
            "requirements": ["project/governance/requirements"],
            "objective": ["project/governance/objective"],
            "dofa": ["project/governance/dofa"],
            "algorithm": ["project/algorithms"],
            "code_source": ["project/code"],
            "test_fixture": ["project/tests/fixture"],
            "dataset": ["project/data"],
            "manifest": ["project/artifacts/manifest"],
            "html_artifact": ["project/artifacts/html"],
            "readme": ["project/docs/readme"],
            "config": ["project/config"],
            "asset": ["project/assets"],
        }
        derived = role_to_taxonomy.get(role)
        if derived:
            taxonomy = derived

    # Derive section from title when missing
    if not section and title:
        # If title contains markdown heading info
        if re.match(r"#{1,5}\s+", title):
            level = len(re.match(r"(#{1,5})\s+", title).group(1))
            section = [title]
        elif title.startswith("#### 🌀"):
            section = [title]

    return taxonomy, section


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


# ── Retrieval hints ────────────────────────────────────────────────────────────

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


# ── Confidence ─────────────────────────────────────────────────────────────────

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


# ── Chunker ────────────────────────────────────────────────────────────────────

def classify_payload(rec: dict) -> dict:
    """
    Classify payload for chunking decisions.
    Returns dict with is_large_payload, is_chunkable_text, chunk_strategy.
    """
    ct = safe_str(rec.get("content_type"))
    text = safe_str(rec.get("text"))
    is_binary = rec.get("is_binary", False)
    token_est = estimate_tokens(text)

    chunkable_types = {
        "text/markdown", "text/vnd.tiddlywiki", "text/plain",
    }
    binary_types = {
        "image/png", "image/jpeg", "image/gif", "image/svg+xml",
        "application/octet-stream",
    }

    is_large_payload = token_est > 1000
    is_chunkable_text = (
        not is_binary
        and ct in chunkable_types
        and bool(text.strip())
    )

    if is_binary or ct in binary_types:
        strategy = "binary_skip"
    elif ct == "application/json":
        strategy = "json_no_chunk"
    elif ct == "text/html":
        strategy = "html_defensive"
    elif is_chunkable_text and token_est > 4000:
        strategy = "hierarchical_chunk"
    elif is_chunkable_text and token_est > 1000:
        strategy = "paragraph_chunk"
    elif is_chunkable_text:
        strategy = "no_chunk_small"
    else:
        strategy = "no_chunk_type"

    return {
        "is_large_payload": is_large_payload,
        "is_chunkable_text": is_chunkable_text,
        "chunk_strategy": strategy,
        "token_estimate": token_est,
    }


def chunk_by_headers(text: str) -> list:
    """Split text by markdown headers into sections."""
    # Split on lines starting with # heading
    sections = []
    current = []
    for line in text.splitlines(keepends=True):
        if re.match(r"^#{1,6}\s+", line) and current:
            sections.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("".join(current))
    return [s for s in sections if s.strip()]


def chunk_by_paragraphs(text: str) -> list:
    """Split text by double newlines (paragraph breaks)."""
    paras = re.split(r"\n{2,}", text)
    return [p.strip() for p in paras if p.strip()]


def chunk_by_sentences(text: str) -> list:
    """Split text by sentence-ending punctuation."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def hard_split(text: str, max_tokens: int) -> list:
    """Emergency hard split: split at max_tokens boundary."""
    max_chars = max_tokens * 4
    chunks = []
    while len(text) > max_chars:
        chunks.append(text[:max_chars])
        text = text[max_chars:]
    if text:
        chunks.append(text)
    return chunks


def merge_segments(segments: list, target_tokens: int, max_tokens: int) -> list:
    """
    Merge small segments up to target_tokens, never exceeding max_tokens.
    Any single segment exceeding max_tokens gets hard-split first.
    """
    result = []
    current = ""
    current_tokens = 0

    for seg in segments:
        seg_tokens = estimate_tokens(seg)

        # If single segment exceeds hard max, split it first
        if seg_tokens > max_tokens:
            # Flush current
            if current.strip():
                result.append(current.strip())
                current = ""
                current_tokens = 0
            # Hard split the oversized segment
            for part in hard_split(seg, max_tokens):
                result.append(part.strip())
            continue

        if current_tokens + seg_tokens > target_tokens and current:
            result.append(current.strip())
            current = seg + "\n\n"
            current_tokens = seg_tokens
        else:
            current += seg + "\n\n"
            current_tokens += seg_tokens

    if current.strip():
        result.append(current.strip())

    return result


def chunk_node(
    rec: dict,
    node_id: str,
    payload_info: dict,
    target_tokens: int,
    max_tokens: int,
) -> tuple:
    """
    Chunk a node using hierarchical strategy.
    Returns (chunks: list, fallback_used: bool, exclusion_reason: str or None)
    """
    strategy = payload_info["chunk_strategy"]
    text = safe_str(rec.get("text")).strip()
    title = safe_str(rec.get("title"))

    # Non-chunkable cases
    if strategy in ("binary_skip", "no_chunk_type"):
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
        segments = chunk_by_paragraphs(clean)
        chunks_text = merge_segments(segments, target_tokens, max_tokens)
    elif strategy in ("hierarchical_chunk", "paragraph_chunk"):
        # 1. Try headers first
        header_sections = chunk_by_headers(text)
        if len(header_sections) > 1:
            # Merge header sections to target size
            chunks_text = merge_segments(header_sections, target_tokens, max_tokens)
        else:
            # 2. Try paragraphs
            paras = chunk_by_paragraphs(text)
            if len(paras) > 1:
                chunks_text = merge_segments(paras, target_tokens, max_tokens)
            else:
                # 3. Try sentences
                sentences = chunk_by_sentences(text)
                if len(sentences) > 1:
                    chunks_text = merge_segments(sentences, target_tokens, max_tokens)
                else:
                    # 4. Hard split as last resort
                    chunks_text = hard_split(text, max_tokens)
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

    # Build chunk records
    chunks = []
    for idx, chunk_text in enumerate(validated):
        tok = estimate_tokens(chunk_text)
        chunks.append({
            "chunk_id": f"{node_id}::chunk:{idx}",
            "node_id": node_id,
            "title": title,
            "chunk_index": idx,
            "chunk_total": len(validated),
            "text": chunk_text,
            "token_estimate": tok,
            "within_target": tok <= target_tokens,
            "within_hard_max": tok <= max_tokens,
            "derivation_method": strategy,
            "fallback": fallback_used,
        })

    return chunks, fallback_used, None


# ── Relations validation ───────────────────────────────────────────────────────

def validate_relations(relations: list, known_ids: set) -> tuple:
    """
    Validate relation targets against known node IDs.
    Returns (valid_relations, invalid_relations).
    """
    valid = []
    invalid = []
    for rel in (relations or []):
        target = rel.get("target_id") or rel.get("target") or ""
        if target and target not in known_ids:
            invalid.append({"type": rel.get("type"), "target_id": target, "reason": "target_not_found"})
        else:
            valid.append(rel)
    return valid, invalid


# ── Load canon shards ──────────────────────────────────────────────────────────

def discover_shards(input_dir: Path) -> list:
    """Discover all canon shards matching tiddlers_*.jsonl pattern."""
    shards = sorted(input_dir.glob("tiddlers_*.jsonl"))
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

def write_sharded(records: list, output_dir: Path, prefix: str, shard_size: int) -> list:
    """Write records to sharded JSONL files. Returns shard info list."""
    output_dir.mkdir(parents=True, exist_ok=True)
    shards_info = []
    shard_num = 1
    count_in_shard = 0
    current_file = None

    for rec in records:
        if count_in_shard == 0 or count_in_shard >= shard_size:
            if current_file:
                current_file.close()
                shards_info[-1]["record_count"] = count_in_shard
            fname = f"{prefix}_{shard_num}.jsonl"
            fpath = output_dir / fname
            current_file = open(fpath, "w", encoding="utf-8")
            shards_info.append({
                "file": fname,
                "shard_index": shard_num,
                "record_count": 0,
            })
            shard_num += 1
            count_in_shard = 0

        current_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
        count_in_shard += 1

    if current_file:
        current_file.close()
        if shards_info:
            shards_info[-1]["record_count"] = count_in_shard

    return shards_info


def write_manifest(output_dir: Path, layer_name: str, shards_info: list,
                   total_records: int, source_shard_count: int,
                   source_shard_files: list, extra: dict = None):
    """Write manifest.json for a layer."""
    manifest = {
        "layer": layer_name,
        "session": SESSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "canon_shard_count": source_shard_count,
            "canon_dir": "out/",
            "canon_pattern": "tiddlers_*.jsonl",
            "canon_shard_files": [str(p) for p in source_shard_files],
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


# ── Enriched record builder ────────────────────────────────────────────────────

def build_enriched_record(rec: dict, shard_file: str, line_num: int,
                           role: str, taxonomy: list, section: list) -> dict:
    text = safe_str(rec.get("text"))
    content = rec.get("content") or {}
    token_est = estimate_tokens(text)
    qflags = compute_quality_flags(rec)

    ct = safe_str(rec.get("content_type"))
    is_prose = ct in ("text/markdown", "text/vnd.tiddlywiki", "text/plain")

    enriched = {
        # Copied deterministic fields
        "id": rec.get("id"),
        "title": rec.get("title"),
        "role_primary": role,
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
            "role_source": "s46_classifier",
            "taxonomy_source": "s46_derived" if not rec.get("taxonomy_path") else "canon_inherited",
        },
    }
    return enriched


# ── AI record builder ──────────────────────────────────────────────────────────

def build_ai_record(rec: dict, shard_file: str, line_num: int,
                     role: str, taxonomy: list, section: list,
                     known_ids: set,
                     target_tokens: int, max_tokens: int) -> tuple:
    """
    Build AI-friendly record and optional chunks.
    Returns (ai_record, chunks, invalid_relations, payload_info)
    """
    text = safe_str(rec.get("text"))
    token_est = estimate_tokens(text)
    qflags = compute_quality_flags(rec)
    node_id = rec.get("id")

    hints = build_retrieval_hints(rec, role)
    payload_info = classify_payload(rec)

    # Validate relations
    raw_rels = rec.get("relations") or []
    valid_rels, invalid_rels = validate_relations(raw_rels, known_ids)

    # Compact relation targets
    rel_targets = []
    for r in valid_rels:
        rt = {"type": r.get("type"), "target_id": r.get("target_id")}
        if r.get("evidence"):
            rt["evidence"] = r["evidence"]
        rel_targets.append(rt)

    ai_rec = {
        "node_id": node_id,
        "title": rec.get("title"),
        "role_primary": role,
        "secondary_roles": build_secondary_roles(rec, role),
        # Three distinct text fields
        "preview_text": compute_preview_text(rec),
        "semantic_text": compute_semantic_text(rec),
        "ai_summary": compute_ai_summary(rec, role),
        # Retrieval
        "retrieval_terms": hints["retrieval_terms"],
        "retrieval_aliases": hints["retrieval_aliases"],
        "retrieval_hints": hints["retrieval_hints"],
        # Relations (validated)
        "relation_targets": rel_targets,
        # Source anchor
        "source_anchor": {
            "canon_id": node_id,
            "shard_file": shard_file,
            "shard_line": line_num,
        },
        # Quality and classification signals
        "quality_flags": qflags,
        "confidence": compute_confidence(rec, role, qflags),
        "is_reference_only": compute_is_reference_only(rec, role),
        "is_foundational": _is_foundational(rec, role),
        # Payload signals
        "is_large_payload": payload_info["is_large_payload"],
        "is_chunkable_text": payload_info["is_chunkable_text"],
        "chunk_strategy": payload_info["chunk_strategy"],
        "token_estimate": token_est,
        # Structure
        "document_id": rec.get("document_id"),
        "section_path": section,
        "taxonomy_path": taxonomy,
        "content_type": rec.get("content_type"),
        "derivation": {
            "session": SESSION,
            "method": "projection_v1",
            "role_source": "s46_classifier",
        },
    }

    # Generate chunks
    chunks = []
    if payload_info["is_chunkable_text"] and token_est > target_tokens:
        chunks, _, _ = chunk_node(rec, node_id, payload_info, target_tokens, max_tokens)

    return ai_rec, chunks, invalid_rels, payload_info


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


# ── QC Reports ────────────────────────────────────────────────────────────────

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
                            target_tokens: int, max_tokens: int) -> Path:
    chunkable_nodes = [r for r in ai_records if r.get("is_chunkable_text")]
    chunked_nodes = [r for r in ai_records if r.get("chunk_strategy") in
                     ("hierarchical_chunk", "paragraph_chunk", "html_defensive")]

    over_target = [c for c in all_chunks if not c.get("within_target")]
    over_max = [c for c in all_chunks if not c.get("within_hard_max")]
    with_fallback = [c for c in all_chunks if c.get("fallback")]

    excluded_reasons = Counter()
    for ev in chunk_qc_events:
        if ev.get("exclusion_reason"):
            excluded_reasons[ev["exclusion_reason"]] += 1

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {
            "chunk_target_tokens": target_tokens,
            "chunk_hard_max_tokens": max_tokens,
        },
        "total_nodes": len(ai_records),
        "chunkable_nodes": len(chunkable_nodes),
        "nodes_that_produced_chunks": len(chunked_nodes),
        "total_chunks_generated": len(all_chunks),
        "chunks_above_target": len(over_target),
        "chunks_above_hard_max": len(over_max),
        "chunks_with_fallback": len(with_fallback),
        "nodes_excluded_from_chunking": sum(excluded_reasons.values()),
        "exclusion_reasons": dict(excluded_reasons),
        "hard_max_violated": len(over_max) > 0,
    }
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
                                all_invalid_rels: list) -> Path:
    total_rels = sum(len(r.get("relation_targets") or []) for r in ai_records)
    type_dist = Counter()
    for r in ai_records:
        for rel in (r.get("relation_targets") or []):
            type_dist[rel.get("type", "unknown")] += 1

    report = {
        "session": SESSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_nodes": len(ai_records),
        "total_valid_relations": total_rels,
        "relation_type_distribution": dict(type_dist.most_common()),
        "total_invalid_relations_discarded": len(all_invalid_rels),
        "invalid_relation_samples": all_invalid_rels[:20],
    }
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
        "content_type_distribution": dict(ct_dist.most_common()),
        "chunking_summary": {
            "target_tokens": target_tokens,
            "hard_max_tokens": max_tokens,
            "total_chunks": len(all_chunks),
            "over_hard_max": sum(1 for c in all_chunks if not c.get("within_hard_max")),
        },
        "hardening_notes": {
            "shard_discovery": "dynamic — pattern tiddlers_*.jsonl",
            "role_vocabulary": "controlled — 26 roles",
            "chunker": "hierarchical with hard max guardrail",
            "retrieval": "normalized dedup with terms + aliases",
            "relations": "validated against known node IDs",
            "text_fields": "three distinct: preview_text, semantic_text, ai_summary",
        },
    }
    p = output_dir / "derivation_report.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return p


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="derive_layers.py — S46 stable derivation entrypoint for tiddly-data-converter"
    )
    parser.add_argument(
        "--input-dir", default="out",
        help="Directory containing canon shards tiddlers_*.jsonl (default: out)"
    )
    parser.add_argument(
        "--enriched-dir", default="out/enriched",
        help="Output directory for enriched layer (default: out/enriched)"
    )
    parser.add_argument(
        "--ai-dir", default="out/ai",
        help="Output directory for AI-friendly layer (default: out/ai)"
    )
    parser.add_argument(
        "--reports-dir", default=None,
        help="Output directory for QC reports (default: <ai-dir>/reports)"
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

    base_dir = Path(__file__).resolve().parent.parent
    input_dir = (base_dir / args.input_dir).resolve()
    enriched_dir = (base_dir / args.enriched_dir).resolve()
    ai_dir = (base_dir / args.ai_dir).resolve()
    reports_dir = (base_dir / (args.reports_dir or (args.ai_dir + "/reports"))).resolve()

    target_tokens = args.chunk_target_tokens
    max_tokens = args.chunk_max_tokens
    tiddler_shard_size = args.tiddler_shard_size
    chunk_shard_size = args.chunk_shard_size

    print(f"[{SESSION}] derive_layers.py — hardened derivation pipeline")
    print(f"  input_dir:       {input_dir}")
    print(f"  enriched_dir:    {enriched_dir}")
    print(f"  ai_dir:          {ai_dir}")
    print(f"  reports_dir:     {reports_dir}")
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
    known_ids = {rec.get("id") for rec, _, _ in canon if rec.get("id")}
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
    )
    print(f"  Wrote {len(enriched_records)} enriched records → {len(enriched_shards_info)} shards in {enriched_dir}")

    # ── Phase 3: Build AI layer (Capa B) ──
    print(f"\n[{SESSION}] Phase 3: Building Capa B — AI-friendly Projection v1...")
    ai_records = []
    all_chunks = []
    all_invalid_rels = []
    chunk_qc_events = []

    for rec, shard_file, line_num, role, taxonomy, section in classified:
        ai_rec, chunks, invalid_rels, payload_info = build_ai_record(
            rec, shard_file, line_num, role, taxonomy, section,
            known_ids, target_tokens, max_tokens
        )
        ai_records.append(ai_rec)
        all_chunks.extend(chunks)
        all_invalid_rels.extend(invalid_rels)
        chunk_qc_events.append({
            "node_id": rec.get("id"),
            "chunk_strategy": payload_info["chunk_strategy"],
            "exclusion_reason": None if payload_info["is_chunkable_text"] else payload_info["chunk_strategy"],
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
        ai_dir, "ai_friendly_projection_v1",
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
        }
    )
    print(f"  Wrote {len(ai_records)} AI records → {len(ai_shards_info)} shards")
    print(f"  Wrote {len(all_chunks)} chunks → {len(chunk_shards_info)} chunk shards")
    print(f"  Invalid relations discarded: {len(all_invalid_rels)}")

    # ── Phase 4: QC Reports ──
    print(f"\n[{SESSION}] Phase 4: Writing QC reports to {reports_dir}...")
    reports_dir.mkdir(parents=True, exist_ok=True)

    p1 = write_classification_report(reports_dir, ai_records, enriched_records)
    p2 = write_chunk_qc_report(reports_dir, ai_records, all_chunks, chunk_qc_events,
                                 target_tokens, max_tokens)
    p3 = write_retrieval_qc_report(reports_dir, ai_records)
    p4 = write_relations_qc_report(reports_dir, ai_records, all_invalid_rels)
    p5 = write_derivation_report(reports_dir, canon, enriched_records, ai_records,
                                   all_chunks, shard_paths, target_tokens, max_tokens)

    print(f"  {p1.relative_to(base_dir)}")
    print(f"  {p2.relative_to(base_dir)}")
    print(f"  {p3.relative_to(base_dir)}")
    print(f"  {p4.relative_to(base_dir)}")
    print(f"  {p5.relative_to(base_dir)}")

    # ── Summary ──
    over_max = sum(1 for c in all_chunks if not c.get("within_hard_max"))
    print(f"\n[{SESSION}] ── Final Summary ──")
    print(f"  Canon shards discovered:  {len(shard_paths)}")
    print(f"  Canon records loaded:     {len(canon)}")
    print(f"  Enriched records:         {len(enriched_records)}")
    print(f"  AI records:               {len(ai_records)}")
    print(f"  Chunks generated:         {len(all_chunks)}")
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
